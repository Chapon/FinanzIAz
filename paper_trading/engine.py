"""
Paper-trading engine — orchestrates scans, executions and approvals.

Public entry points
-------------------
``run_scan(account_id, *, prices_provider=None, history_provider=None)``
    Full scan cycle:
        1. fetch live prices for watchlist ∪ current positions,
        2. fetch OHLCV history for each ticker,
        3. call the account's strategy → list of ``TargetTrade``,
        4. in AUTO mode, fill every trade immediately (create a filled
           ``PaperOrder``, update cash & positions),
        5. in MANUAL mode, create ``pending`` orders for approval,
        6. snapshot equity, stamp ``last_scan_at`` / ``last_monthly_rebalance``.

``approve_order(order_id)`` / ``reject_order(order_id)``
    Pending-order lifecycle for MANUAL mode.

The engine is deterministic given the two *_provider callables, which is
what makes unit tests possible without real yfinance calls.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from time import perf_counter
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from analysis.portfolio_risk import annualized_portfolio_vol, returns_frame
from config.settings_manager import settings
from database.models import session_scope, utcnow_naive
from integrations.slack import (
    OrderNotice,
    SlackNotifier,
    default_notifier,
    format_scan_summary,
    select_notifiable,
)
from paper_trading.account import record_equity_snapshot
from paper_trading.models import (
    PaperAccount,
    PaperOrder,
    PaperPosition,
    PaperWatchlistItem,
)
from paper_trading.strategies import (
    HistoryProvider,
    TargetTrade,
    get_strategy_fn,
)

PricesProvider = Callable[[list[str]], dict[str, float]]
EarningsProvider = Callable[[str], "datetime | None"]


# ── Default live providers (thin wrappers over yfinance cache) ────────────────


def _default_earnings_provider(ticker: str) -> datetime | None:
    """Next-earnings date for the T08 blackout gate. Fail-open (None on error)."""
    from data.yahoo_finance import get_next_earnings_date

    return get_next_earnings_date(ticker)


def _default_prices_provider(tickers: list[str]) -> dict[str, float]:
    from data.yahoo_finance import get_bulk_prices

    out: dict[str, float] = {}
    for ticker, info in get_bulk_prices(tickers).items():
        if info is None:
            continue
        px = info.get("price")
        if px is not None and np.isfinite(px) and px > 0:
            out[ticker] = float(px)
    return out


def _price_out_of_band(ticker: str, price: float | None, side: str | None = None) -> bool:
    """Sanity de escala (E5): True si NO hay que fillar a ``price``.

    Última línea de defensa antes de fillar, por si un precio de escala corrupta
    (~10× tipo KLAC 2026-06-01) esquiva el guard del fetch (provider inyectado en
    tests, precio cacheado de antes del guard, path alternativo). Fail-open si no
    hay referencia (no podemos juzgar la escala → no bloqueamos).

    **Con la referencia en duda (tarea 63): salir sí, entrar no.** El veredicto de
    escala lo da la misma función que usa el guard del fetch
    (``unreliable_reference``) —dos guards que con la misma referencia llegan a
    conclusiones opuestas son cómo una posición queda trabada—, pero encima va una
    decisión de política que **sí** mira el lado, y es la asimetría que el caso
    AVB reveló:

    * **SELL / desconocido → no se bloquea.** Este guard no distinguía el lado, y
      con un histórico podrido eso no evita una compra mala: deja la posición sin
      poder venderse. Quedar trapeado es peor que salir a un precio dudoso.
    * **BUY → se bloquea igual.** No alcanza con que la *cotización* sea creíble:
      el ATR y las barreras salen del **mismo histórico** que está en duda
      (``paper_history_period`` = ``2y``, el frame que en AVB quedó 2.793× fuera
      de escala), así que la posición entraría con un stop calculado en otra
      escala. Entrar es opcional; salir no.

    **Y la zona muerta DEBAJO de la banda (tarea 64): la misma asimetría.** Todo lo
    de arriba arranca cuando el precio vivo se sale de la banda del 50%. Una
    corrupción **menor** —un split fantasma de 1.3— deja el histórico fuera de
    escala con el precio **adentro**, así que nada de esto llega a correr y el ATR
    igual sale del frame podrido. Con los frames ``1d`` en desacuerdo por encima de
    la tolerancia calibrada (``scale_drift``, 10% — ver el bloque de la 64 en
    ``data/yahoo_finance``), **la entrada se bloquea y la salida no**, por el mismo
    argumento: entrar es opcional, salir no.

    **Lo que NO se hace, y es deliberado.** *No* se excluye al ticker del universo:
    eso lo volvería invisible, que es exactamente el modo de falla que la 63 vino a
    arreglar. *No* se elige el frame que coincide con la cotización: darle a la
    cotización el rol de árbitro es lo que hizo E5, y la 63 mostró que ese lado
    también se pudre. Con los dos frames en desacuerdo el cache **no puede
    arbitrar**, y la conducta correcta es no apostar plata nueva sobre él.
    """
    from data.yahoo_finance import (
        is_price_out_of_band,
        reference_close,
        scale_drift,
        unreliable_reference,
    )

    entrando = str(side or "").upper() == "BUY"
    ref = reference_close(ticker)
    if not is_price_out_of_band(price, ref):
        # T64 — el precio está en banda, pero los frames del histórico pueden no
        # estar en la misma escala. Sólo importa para ENTRAR (el ATR sale de ahí).
        drift = scale_drift(ticker)
        if drift is None:
            return False
        from config.logging_config import get_logger

        get_logger(__name__).warning(
            "El precio de %s está EN banda pero los frames del histórico NO coinciden — %s. %s",
            ticker.upper(),
            drift,
            (
                "La ENTRADA se bloquea: el ATR y las barreras saldrían de un histórico "
                "cuya escala el cache no puede arbitrar."
                if entrando
                else "La SALIDA no se bloquea: quedar trapeado es peor que salir con un histórico en duda."
            ),
        )
        return entrando
    reason = unreliable_reference(ticker, price, ref, allow_network=False)
    if reason is None:
        return True

    from config.logging_config import get_logger

    # Llegado aca `is_price_out_of_band` devolvio True, y eso exige que los dos
    # sean no-None (si falta cualquiera, hace fail-open y no llega).
    assert price is not None and ref is not None
    get_logger(__name__).error(
        "%s: %.4f fuera de banda vs el histórico (%.4f), pero la referencia NO es confiable — %s. %s",
        ticker.upper(),
        float(price),
        float(ref),
        reason,
        (
            "La ENTRADA se bloquea igual: el ATR y las barreras salen del mismo histórico en duda."
            if entrando
            else "El fill NO se bloquea: con una referencia dudosa este guard "
            "trabaría también la SELL y dejaría la posición sin salida."
        ),
    )
    return entrando


_VALID_YF_PERIODS = {"1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}


def _resolve_history_period() -> str:
    """Período OHLCV configurable vía ``paper_history_period`` (default ``"2y"``),
    validado contra ``_VALID_YF_PERIODS``. Compartido por el provider per-ticker
    y el warm-up batch del scan para que no se desincronicen."""
    raw = settings.get("paper_history_period", "2y")
    return str(raw) if str(raw) in _VALID_YF_PERIODS else "2y"


def _default_history_provider(ticker: str) -> pd.DataFrame | None:
    """Fetch OHLCV history. Period is configurable via ``paper_history_period``
    (default ``"2y"``) — see ``config/settings_manager.py``."""
    from data.yahoo_finance import get_historical_data

    return get_historical_data(ticker, period=_resolve_history_period())


def _warm_up_history_cache(tickers: list[str]) -> None:
    """Warm-up de la cache OHLCV en UNA descarga batch antes de los
    ``history_provider`` per-ticker (estrategia, ATR exits, sigma).

    ``get_historical_data_batch`` escribe cada ticker a la cache, así que esos
    ``history_provider(ticker)`` pegan a cache fresca y no emiten un request (ni
    un handshake de crumb) por ticker → muchos menos 401.

    SPY entra al warm-up SOLO para cachear el benchmark de Métricas (V1); NO se
    agrega a ``tickers``, así que no toca precios ni gates. Por eso mismo es el
    **único símbolo sin re-fetch per-ticker**: si el batch lo saltea (throttle/
    401), su fila vieja queda intacta y el benchmark se congela mientras la
    equity avanza (tarea 22, BENCH-STALE). Fallback pata (a): cuando el batch no
    devuelve SPY, se lo re-pide solo — un único request, y SPY ya es el canario
    de NET1. Todo best-effort: cualquier fallo se loguea y no corta el scan.
    """
    if not tickers:
        return
    from analysis.metrics_panel import BENCHMARK_TICKER
    from config.logging_config import get_logger

    period = _resolve_history_period()
    warm: dict | None = None
    try:
        from data.yahoo_finance import get_historical_data_batch

        warm = get_historical_data_batch(sorted(set(tickers) | {BENCHMARK_TICKER}), period=period)
    except Exception:
        get_logger(__name__).exception("Batch history warm-up failed; falling back to per-ticker fetch")
    # tarea 22 (a): si el batch salteó/falló SPY, darle su propio fallback
    # per-ticker para que el benchmark no quede congelado en una fecha vieja.
    if (warm or {}).get(BENCHMARK_TICKER) is None:
        try:
            from data.yahoo_finance import get_historical_data

            get_historical_data(BENCHMARK_TICKER, period=period)
        except Exception:
            get_logger(__name__).exception("SPY benchmark fallback fetch failed")


def _declare_scale_drift(tickers: list[str]) -> list[str]:
    """Declara los tickers cuyos frames ``1d`` NO están en la misma escala (T64).

    Corre **incondicional** y después del warm-up —o sea sobre el cache más fresco
    que va a haber este scan—, que es lo que lo distingue de la **63**: aquélla
    cruza los frames sólo cuando el precio vivo ya salió de la banda del 50%, así
    que una corrupción **menor** nunca la despierta. Y una corrupción menor igual
    duele: el ATR y las barreras salen del histórico, así que un frame 1,3× chico
    da un stop 1,3× más ajustado que el que la política dice.

    **Declara, no decide** — la política vive en ``_price_out_of_band``, que es el
    punto donde hay un lado (BUY/SELL) que mirar. Es offline (no pega a la red) y
    barato: 130 tickers en 0,6 s. Best-effort: nunca corta un scan.
    """
    out: list[str] = []
    try:
        from config.logging_config import get_logger
        from data.yahoo_finance import scale_drift

        log = get_logger(__name__)
        for ticker in tickers:
            drift = scale_drift(ticker)
            if drift is None:
                continue
            msg = (
                f"{drift} — el ATR y las barreras salen de ese histórico, así que "
                f"las ENTRADAS de {drift.ticker} quedan bloqueadas hasta que los "
                f"frames coincidan (las SALIDAS no)"
            )
            log.warning("DRIFT DE ESCALA — %s", msg)
            out.append(msg)
    except Exception:
        from config.logging_config import get_logger

        get_logger(__name__).exception("scale drift declaration failed")
    return out


def _is_market_open_safe() -> bool:
    """Wrapper around data.yahoo_finance.is_market_open() that never raises."""
    try:
        from data.yahoo_finance import is_market_open

        open_, _ = is_market_open()
        return bool(open_)
    except Exception:
        return False


def _estimate_book_sigma(positions, prices, history_provider) -> float | None:
    """Annualised σ of the current book for the equity snapshot (T10).

    Best-effort: weights are market-value shares, σ = sqrt(wᵀΣw)·sqrt(252) over
    60-day daily returns. Returns ``None`` when there are no positions or not
    enough history — never raises, so it can't break a scan.
    """
    try:
        if not positions:
            return None
        mv = {}
        total = 0.0
        for p in positions:
            px = prices.get(p.ticker, p.avg_cost) or p.avg_cost
            val = float(p.shares) * float(px)
            if val > 0:
                mv[p.ticker] = val
                total += val
        if total <= 0:
            return None
        weights = {t: v / total for t, v in mv.items()}
        ret_df = returns_frame(list(weights.keys()), history_provider)
        sigma = annualized_portfolio_vol(weights, ret_df)
        return float(sigma) if sigma > 0 else None
    except Exception:
        return None


def _last_closed_cycle_pnl_pct(
    session,
    account_id: int,
    ticker: str,
    within_days: int,
) -> float | None:
    """Return the realized P/L % of the most recent closed cycle for ``ticker``,
    or ``None`` if there is no SELL fill for the ticker within ``within_days``.

    A "cycle" is the set of BUY fills between two consecutive SELLs (or, for
    the first cycle, all BUYs preceding the first SELL). We weight BUY prices
    by ``fill_shares`` and compare against the last SELL's ``fill_price``.

    Used by Gate 5 (anti-whipsaw) to decide whether a fresh BUY should be
    blocked because the same ticker was just sold at a loss.
    """
    if within_days <= 0:
        return None

    cutoff = utcnow_naive() - timedelta(days=within_days)

    last_sell = (
        session.query(PaperOrder)
        .filter(PaperOrder.account_id == account_id)
        .filter(PaperOrder.ticker == ticker)
        .filter(PaperOrder.side == "SELL")
        .filter(PaperOrder.status == "filled")
        .filter(PaperOrder.filled_at >= cutoff)
        .order_by(PaperOrder.filled_at.desc())
        .first()
    )
    if last_sell is None or not last_sell.fill_price:
        return None

    prev_sell = (
        session.query(PaperOrder)
        .filter(PaperOrder.account_id == account_id)
        .filter(PaperOrder.ticker == ticker)
        .filter(PaperOrder.side == "SELL")
        .filter(PaperOrder.status == "filled")
        .filter(PaperOrder.filled_at < last_sell.filled_at)
        .order_by(PaperOrder.filled_at.desc())
        .first()
    )

    buys_q = (
        session.query(PaperOrder)
        .filter(PaperOrder.account_id == account_id)
        .filter(PaperOrder.ticker == ticker)
        .filter(PaperOrder.side == "BUY")
        .filter(PaperOrder.status == "filled")
        .filter(PaperOrder.filled_at <= last_sell.filled_at)
    )
    if prev_sell is not None:
        buys_q = buys_q.filter(PaperOrder.filled_at > prev_sell.filled_at)
    buys = buys_q.all()
    if not buys:
        return None

    total_shares = sum(float(b.fill_shares or 0.0) for b in buys)
    total_cost = sum(float(b.fill_shares or 0.0) * float(b.fill_price or 0.0) for b in buys)
    if total_shares <= 0 or total_cost <= 0:
        return None
    avg_buy = total_cost / total_shares
    if avg_buy <= 0:
        return None
    return (float(last_sell.fill_price) - avg_buy) / avg_buy * 100.0


def _closed_cycles_count(
    session,
    account_id: int,
    ticker: str,
    within_days: int,
) -> int:
    """Count closed cycles for ``ticker`` whose closing SELL filled within
    ``within_days`` (calendar days).

    Walks every filled order for the ticker chronologically tracking net
    shares; a SELL fill that leaves the position at ~zero closes a cycle.
    Partial SELLs (e.g. T09 vol-overlay trims) do NOT count — only full
    exits do, so de-risking a position never feeds the churn counter.

    Used by Gate 5b (anti-churn v2 / T6.5): the anti-whipsaw gate only looks
    at *losing* cycles, which is why it never slowed the KO churn (3 cycles
    in 7 days, the first one a winner). This counter is P/L-agnostic.
    """
    if within_days <= 0:
        return 0

    cutoff = utcnow_naive() - timedelta(days=within_days)

    fills = (
        session.query(PaperOrder)
        .filter(PaperOrder.account_id == account_id)
        .filter(PaperOrder.ticker == ticker)
        .filter(PaperOrder.status == "filled")
        .order_by(PaperOrder.filled_at.asc())
        .all()
    )

    shares = 0.0
    count = 0
    for o in fills:
        qty = float(o.fill_shares or 0.0)
        if qty <= 0:
            continue
        if o.side == "BUY":
            shares += qty
        elif o.side == "SELL":
            shares -= qty
            # Tolerancia relativa: floats de shares fraccionales acumulan ruido.
            if shares <= max(1e-6, abs(qty) * 1e-9):
                shares = 0.0
                if o.filled_at is not None and o.filled_at >= cutoff:
                    count += 1
    return count


# ── ATR-stop gate (T01) ───────────────────────────────────────────────────────


# Re-exported for backward compatibility with callers that import
# ``ATR_EXIT_REASONS`` from this module. Authoritative source is
# ``paper_trading.gates``.
from analysis.impact_score import exit_veto_block
from paper_trading.gates import (
    ATR_EXIT_REASONS,  # noqa: F401 — re-export retrocompatible, ver el comentario de arriba
    adv_capped_notional,
    atr_exit_decision,
    is_atr_forced_exit_reason,
    is_vol_trim_reason,
    is_within_earnings_blackout,
    model_exit_fill_price,
    recent_adv_dollars,
    signal_sell_min_age_block,
)

if TYPE_CHECKING:  # import solo para tipos: en runtime crearia un ciclo
    from analysis.impact_score import CatalystSignal

# Provider for the T-CAT-4 exit-veto: (ticker, scan_at) -> CatalystSignal | None.
# Injected and default None so the default trading path never builds the
# (expensive) reaction table; the veto is also gated behind a default-OFF flag.
CatalystSignalProvider = Callable[[str, datetime], "CatalystSignal | None"]


def _is_atr_forced_exit(reason: str | None) -> bool:
    """True iff ``reason`` was produced by ``_compute_atr_forced_exits``.

    Thin wrapper preserved for backward compatibility — the authoritative
    implementation now lives in :func:`paper_trading.gates.is_atr_forced_exit_reason`.
    """
    return is_atr_forced_exit_reason(reason)


def _compute_atr_forced_exits(
    positions: list,
    prices: dict[str, float],
    history_provider,
) -> list:
    """
    Evaluate each open position against the ATR stop/TP/trailing levels.

    Returns a list of ``TargetTrade`` SELLs for the tickers whose live price
    crossed at least one threshold. The per-position decision is delegated to
    :func:`paper_trading.gates.atr_exit_decision`; this wrapper handles the
    loop, the settings reads, the ATR computation, and the ``TargetTrade``
    construction so the gate module stays pure.

    The caller is responsible for updating ``high_water_mark`` separately,
    *after* this function has read the pre-update high — keeps the trailing
    stop semantics correct.
    """
    from analysis.atr import compute_atr
    from paper_trading.strategies import TargetTrade

    if not bool(settings.get("atr_stops_enabled", False)):
        return []

    period = max(2, int(settings.get("atr_period", 14)))
    stop_mult = max(0.0, float(settings.get("atr_stop_mult", 2.0)))
    tp_mult = max(0.0, float(settings.get("atr_tp_mult", 4.0)))
    trail_enabled = bool(settings.get("atr_trail_enabled", True))
    # T53 — las dos barreras desacopladas. Los defaults son el comportamiento
    # histórico: trail_mult=0 ⇒ el trailing sigue al stop, hard stop prendido.
    trail_mult = max(0.0, float(settings.get("atr_trail_mult", 0.0)))
    hard_stop_enabled = bool(settings.get("atr_hard_stop_enabled", True))

    out: list = []
    for pos in positions:
        px = prices.get(pos.ticker)
        if px is None or not np.isfinite(px) or px <= 0:
            continue
        if pos.shares is None or pos.shares <= 1e-9:
            continue
        if pos.avg_cost is None or pos.avg_cost <= 0:
            continue

        df = history_provider(pos.ticker)
        atr = compute_atr(df, period=period)
        if atr is None or not np.isfinite(atr) or atr <= 0:
            continue

        reason, level = atr_exit_decision(
            current_price=float(px),
            avg_cost=float(pos.avg_cost),
            high_water_mark=pos.high_water_mark,
            atr_value=float(atr),
            stop_mult=stop_mult,
            tp_mult=tp_mult,
            trail_enabled=trail_enabled,
            trail_mult=trail_mult,
            hard_stop_enabled=hard_stop_enabled,
        )
        if reason is None:
            continue

        # Fill realista (T01 #2/#3): el nivel es solo el GATILLO; el fill real
        # depende de cómo la barra cruzó el nivel (gap-open vs touch intradía).
        # Lo modelamos con el OHLC de la última barra y dejamos constancia honesta
        # del precio efectivo + el gap respecto del nivel en el ``reason``.
        bar_o = bar_h = bar_l = None
        try:
            if df is not None and not df.empty:
                if "Open" in df.columns:
                    bar_o = float(df["Open"].iloc[-1])
                if "High" in df.columns:
                    bar_h = float(df["High"].iloc[-1])
                if "Low" in df.columns:
                    bar_l = float(df["Low"].iloc[-1])
        except (ValueError, TypeError, IndexError, KeyError):
            bar_o = bar_h = bar_l = None

        fill_override = None
        if level is not None and np.isfinite(level) and level > 0:
            modeled = model_exit_fill_price(
                reason=reason,
                trigger_level=float(level),
                bar_open=bar_o,
                bar_high=bar_h,
                bar_low=bar_l,
                current_price=float(px),
            )
            if modeled is not None and np.isfinite(modeled) and modeled > 0:
                fill_override = float(modeled)
                gap_pct = (modeled - float(level)) / float(level) * 100.0
                reason = f"{reason} | fill≈{modeled:.2f} (gap {gap_pct:+.2f}% vs nivel)"

        out.append(
            TargetTrade(
                ticker=pos.ticker,
                side="SELL",
                target_shares=float(pos.shares),  # full close
                target_dollars=None,
                reason=reason,
                source="atr_stop_gate",
                signal_score=1.0,  # max conviction — see roadmap T01
                fill_price_override=fill_override,
            )
        )

    return out


def _buy_risk_note(ticker: str, entry_price: float, history_provider) -> str | None:
    """Nota R:R/stop/TP para una BUY (V2, display-only, fail-open).

    Computa el ATR del ticker (mismos params que el gate ATR) y deriva los
    niveles de riesgo ex-ante que el engine enforcearía sobre la posición, para
    estamparlos en ``PaperOrder.notes`` y mostrarlos en la UI de Paper. NO toca
    ninguna decisión (regla 3). Devuelve ``None`` si no se puede computar (sin
    historia/ATR) — la orden se crea igual.
    """
    try:
        from analysis.atr import compute_atr
        from paper_trading.gates import entry_risk_levels, format_entry_risk_note

        if entry_price is None or not np.isfinite(entry_price) or entry_price <= 0:
            return None
        period = max(2, int(settings.get("atr_period", 14)))
        stop_mult = max(0.0, float(settings.get("atr_stop_mult", 2.0)))
        tp_mult = max(0.0, float(settings.get("atr_tp_mult", 4.0)))
        df = history_provider(ticker)
        atr = compute_atr(df, period=period)
        if atr is None or not np.isfinite(atr) or atr <= 0:
            return None
        levels = entry_risk_levels(
            entry_price=float(entry_price),
            atr_value=float(atr),
            stop_mult=stop_mult,
            tp_mult=tp_mult,
            hard_stop_enabled=bool(settings.get("atr_hard_stop_enabled", True)),
        )
        return format_entry_risk_note(levels)
    except Exception:
        return None


def _update_high_water_marks(positions: list, prices: dict[str, float]) -> None:
    """
    Seed / advance ``high_water_mark`` for each position based on the live
    price. NULL HWM is seeded with the current price (or avg_cost, whichever
    is higher — protects against the seed being below entry on a down tick).
    Existing HWM is advanced only if the new price is strictly higher.

    Called *after* ``_compute_atr_forced_exits`` so the trailing stop uses
    the pre-update HWM.
    """
    for pos in positions:
        px = prices.get(pos.ticker)
        if px is None or not np.isfinite(px) or px <= 0:
            continue
        if pos.high_water_mark is None:
            seed = max(float(px), float(pos.avg_cost or 0.0))
            pos.high_water_mark = float(seed)
        elif float(px) > float(pos.high_water_mark):
            pos.high_water_mark = float(px)


# ── Earnings-blackout gate (T08) ───────────────────────────────────────────────


def _earnings_blackout_hit(
    earnings_date: datetime | None,
    scan_at: datetime,
    blackout_days: int,
) -> bool:
    """Thin wrapper preserved for backward compatibility — see
    :func:`paper_trading.gates.is_within_earnings_blackout`.
    """
    return is_within_earnings_blackout(earnings_date, scan_at, blackout_days)


# ── Scan result type ──────────────────────────────────────────────────────────


@dataclass
class ScanResult:
    account_id: int
    scan_at: datetime
    mode: str  # "auto" | "manual"
    strategy: str
    prices: dict[str, float]
    generated: int = 0  # total trades proposed by strategy
    filled: int = 0  # executed immediately
    queued: int = 0  # pending approval
    skipped: int = 0  # rejected by engine (no price, insufficient cash, …)
    prices_requested: int = 0  # tickers para los que se pidió precio este scan
    prices_missing: int = 0  # cuántos quedaron sin precio usable (B3 telemetría)
    # OPS1(c) — timing por fase (segundos): fetch (warm-up + precios), analyze
    # (ATR exits + strategy) y process (loop de gates+fill; van interleaveados en
    # el mismo loop, no se separan en tiempo). ``scan_seconds`` es el total
    # wall-clock del scan. Sin esto no se puede decidir si bajar el intervalo de
    # 15 min es viable ni detectar degradación de Yahoo antes de que muerda.
    phase_seconds: dict[str, float] = field(default_factory=dict)
    scan_seconds: float = 0.0
    equity_before: float = 0.0
    equity_after: float = 0.0
    warnings: list[str] = field(default_factory=list)
    filled_orders: list[int] = field(default_factory=list)
    pending_orders: list[int] = field(default_factory=list)
    # Session-detached snapshots of the orders created this scan, used to build
    # the T12 Slack summary after the transaction closes. Captured at create/
    # fill time so the message is safe to compose outside the DB session.
    new_orders: list[OrderNotice] = field(default_factory=list)
    # LOG-HYGIENE (tarea 25a) — resumen de los entrenamientos XGBoost de este
    # scan, en una línea, en vez de dos líneas por ticker. ``None`` cuando no se
    # entrenó nada, que es el caso normal a partir del 2º scan del día desde que
    # el cache sobrevive (tarea 24).
    ml_training: str | None = None

    # GARCH-FRAGIL (tarea 67) — resumen de los NO-FIT de GARCH de este scan.
    # ``None`` cuando fitearon todos, que es el caso normal (130 de 133 en el
    # barrido de la 29c). Que aparezca es la señal de que hay tickers al filo de
    # la convergencia, y el motivo distingue "no hay datos" de "no converge" —
    # justo lo que el `None` del borde no dejaba ver.
    garch_no_fit: str | None = None

    def summary(self) -> str:
        base = (
            f"Scan {self.scan_at:%Y-%m-%d %H:%M} · {self.strategy} · {self.mode}  "
            f"· generated={self.generated} filled={self.filled} "
            f"queued={self.queued} skipped={self.skipped}  "
            f"· equity ${self.equity_before:,.2f} → ${self.equity_after:,.2f}"
        )
        if self.scan_seconds > 0:
            phases = " ".join(f"{k} {v:.2f}s" for k, v in self.phase_seconds.items())
            base += f"  · {self.scan_seconds:.2f}s ({phases})"
        if self.ml_training:
            base += f"  · {self.ml_training}"
        if self.garch_no_fit:
            base += f"  · {self.garch_no_fit}"
        return base


# ── Main entry point ──────────────────────────────────────────────────────────


def run_scan(
    account_id: int,
    *,
    prices_provider: PricesProvider | None = None,
    history_provider: HistoryProvider | None = None,
    earnings_provider: EarningsProvider | None = None,
    catalyst_signal_provider: CatalystSignalProvider | None = None,
    slack_notifier: SlackNotifier | None = None,
) -> ScanResult | None:
    """Scan the market once, execute trades (or queue them), snapshot equity."""
    prices_provider = prices_provider or _default_prices_provider
    # Recordar si el history_provider fue inyectado (tests): en ese caso el
    # warm-up batch de abajo NO debe tocar la red.
    history_was_injected = history_provider is not None
    history_provider = history_provider or _default_history_provider
    earnings_provider = earnings_provider or _default_earnings_provider

    t_scan_start = perf_counter()  # OPS1(c): timing por fase

    with session_scope() as session:
        # `.first()` devuelve Optional y la linea de abajo ya lo contempla: la
        # anotacion estricta era una promesa que el codigo no hacia.
        acct: PaperAccount | None = session.query(PaperAccount).filter(PaperAccount.id == account_id).first()
        if acct is None or not acct.is_active:
            return None
        account_name = acct.name
        # Per-account Slack opt-out (T12). NULL (legacy) → True (notify).
        account_slack_notify = bool(acct.slack_notify) if acct.slack_notify is not None else True

        watchlist = [
            w.ticker
            for w in (
                session.query(PaperWatchlistItem).filter(PaperWatchlistItem.account_id == account_id).all()
            )
        ]
        positions: list[PaperPosition] = (
            session.query(PaperPosition)
            .filter(PaperPosition.account_id == account_id)
            .filter(PaperPosition.shares > 0)
            .all()
        )

        tickers = sorted(set(watchlist) | {p.ticker for p in positions})

        # Warm-up de la cache OHLCV (+ fallback per-ticker de SPY, tarea 22) en
        # una sola descarga batch antes de las llamadas per-ticker. Best-effort:
        # si falla, el provider per-ticker sigue andando. Solo con el provider por
        # defecto — si se inyectó uno (tests), no tocar la red.
        if tickers and not history_was_injected:
            _warm_up_history_cache(tickers)

        prices = prices_provider(tickers) if tickers else {}

        t_after_fetch = perf_counter()  # OPS1(c): fin de fetch (warm-up + precios)

        # ── Telemetría de cobertura de precios (B3) ──────────────────────────
        # Si Yahoo throttlea, varios tickers vuelven sin precio: las decisiones
        # corren sobre un universo reducido (ATR exits y la strategy ya saltean
        # los tickers sin precio, no operan a ciegas). Lo hacemos VISIBLE en vez
        # de silencioso, y avisamos fuerte si una POSICIÓN abierta quedó sin
        # precio — ahí un stop que debería evaluarse no pudo correr este scan.
        missing_tickers = [t for t in tickers if t not in prices]
        held_without_price = sorted(p.ticker for p in positions if p.ticker not in prices)
        scan_warnings: list[str] = []
        # T64 — drift de escala por DEBAJO de la banda: acá, después del warm-up,
        # porque es el cache más fresco que va a haber este scan.
        scan_warnings.extend(_declare_scale_drift(tickers))
        if missing_tickers:
            from config.logging_config import get_logger

            msg = f"{len(missing_tickers)}/{len(tickers)} tickers sin precio este scan"
            if held_without_price:
                msg += f" — posiciones SIN evaluar (stops no corridos): {', '.join(held_without_price)}"
            get_logger(__name__).warning("Scan %s (cuenta %d): %s", account_name, account_id, msg)
            scan_warnings.append(msg)

        # Equity before any trades. Para los tickers sin precio se mark-to-avg_cost
        # (snapshot de equity tolerante); las DECISIONES de trade no usan ese
        # fallback (ver guards en _compute_atr_forced_exits y la strategy).
        equity_before = acct.cash + sum(p.shares * prices.get(p.ticker, p.avg_cost) for p in positions)

        # ── ATR-stop gate (T01) ──────────────────────────────────────────
        # Runs BEFORE the strategy so a stopped-out position can free up
        # its slot in the same scan. The returned trades use reason starting
        # with ``atr_`` so downstream gates can recognize them as forced
        # exits and bypass min-holding.
        atr_exits: list[TargetTrade] = _compute_atr_forced_exits(positions, prices, history_provider)
        atr_exit_tickers = {t.ticker for t in atr_exits}

        # Advance HWM *after* reading it for the trailing check, so the
        # trailing stop uses the pre-update high. New positions get their
        # HWM seeded here.
        _update_high_water_marks(positions, prices)

        # Run the strategy (reads detached attributes, so safe)
        strategy_fn = get_strategy_fn(acct.strategy)
        strategy_trades: list[TargetTrade] = strategy_fn(acct, watchlist, positions, prices, history_provider)

        # Dedup: if ATR forces a SELL for a ticker, drop any strategy-emitted
        # SELL for the same ticker — the ATR trigger wins (more specific +
        # has signal_score=1.0 for downstream consumers).
        strategy_trades = [
            t for t in strategy_trades if not (t.side == "SELL" and t.ticker in atr_exit_tickers)
        ]
        trades: list[TargetTrade] = atr_exits + strategy_trades

        t_after_analyze = perf_counter()  # OPS1(c): fin de analyze (ATR exits + strategy)

        # LOG-HYGIENE (tarea 25a): los entrenamientos XGBoost de la fase analyze
        # se resumen en una línea. Best-effort — la telemetría de log nunca puede
        # tumbar un scan.
        try:
            from analysis.ml_signals import drain_training_summary

            ml_training = drain_training_summary()
        except Exception:
            ml_training = None

        # T67: mismo patrón, y también best-effort.
        try:
            from analysis.garch_signals import drain_no_fit_summary

            garch_no_fit = drain_no_fit_summary()
        except Exception:
            garch_no_fit = None

        result = ScanResult(
            account_id=account_id,
            scan_at=utcnow_naive(),
            mode=acct.mode,
            strategy=acct.strategy,
            prices=prices,
            generated=len(trades),
            prices_requested=len(tickers),
            prices_missing=len(missing_tickers),
            equity_before=float(equity_before),
            warnings=list(scan_warnings),
            ml_training=ml_training,
            garch_no_fit=garch_no_fit,
        )

        # Process trades in a deterministic order: SELLs first (free up cash), then BUYs.
        trades.sort(key=lambda t: 0 if t.side == "SELL" else 1)

        # ── Lite-pro guardrails ──────────────────────────────────────────────
        # Read configurable thresholds (with safe defaults) and pre-compute
        # state used by the per-trade gates inside the loop below.
        enforce_hours = bool(settings.get("paper_enforce_market_hours", True))
        min_holding_min = max(0, int(settings.get("paper_min_holding_minutes", 60)))
        # T6.4 score-hysteresis: edad mínima (días hábiles) para SELLs de señal.
        signal_sell_min_age = max(0, int(settings.get("paper_signal_sell_min_age_bdays", 3)))
        signal_sell_bypass = float(settings.get("paper_signal_sell_bypass_score", 0.25))
        anti_flap_min = max(0, int(settings.get("paper_anti_flap_minutes", 30)))
        min_trade_usd = max(0.0, float(settings.get("paper_min_trade_dollars", 50.0)))
        # T10 ADV liquidity cap. 0.0 = disabled (default). When >0 a BUY's
        # notional is trimmed to cap_pct of the ticker's recent ADV$.
        adv_cap_pct = max(0.0, float(settings.get("paper_adv_cap_pct", 0.0)))
        adv_lookback_days = max(1, int(settings.get("paper_adv_lookback_days", 20)))
        whipsaw_days = max(0, int(settings.get("paper_whipsaw_lookback_days", 7)))
        whipsaw_min_loss = max(0.0, float(settings.get("paper_whipsaw_min_loss_pct", 0.0)))
        # T6.5 anti-churn v2: frecuencia de ciclos, independiente del P/L.
        churn_max_cycles = max(0, int(settings.get("paper_churn_max_cycles", 3)))
        churn_lookback_days = max(0, int(settings.get("paper_churn_lookback_days", 10)))
        earnings_blackout_days = max(0, int(settings.get("earnings_blackout_days", 2)))
        # T08 (Sprint 0): SELLs señaladas por estrategia pasan por default durante
        # el blackout — el setting permite restaurar el comportamiento legacy.
        earnings_block_sells = bool(settings.get("earnings_blackout_block_sells", False))
        # T-CAT-4 exit-veto (Gate 2c). DEFAULT OFF: solo se activa cuando el
        # backtest de T-CAT-6 lo valide (ver docs\catalyst_t_cat_4_design.md §7).
        # Además requiere un catalyst_signal_provider inyectado — sin él el gate
        # no corre, así que el hot-path por defecto no construye nada.
        catalyst_veto_enabled = bool(settings.get("paper_catalyst_exit_veto_enabled", False))
        catalyst_veto_min_score = float(settings.get("paper_catalyst_veto_min_score", 0.30))
        catalyst_veto_gray_high = float(settings.get("paper_catalyst_veto_gray_high", 0.50))

        # Memoize earnings lookups within this scan so we hit the provider at
        # most once per ticker. Fail-open: a provider that raises is treated as
        # "no known earnings" (None) and logged, so a flaky calendar API never
        # blocks trading.
        _earnings_seen: dict[str, datetime | None] = {}

        def _earnings_date_for(ticker: str) -> datetime | None:
            if ticker in _earnings_seen:
                return _earnings_seen[ticker]
            try:
                edt = earnings_provider(ticker)
            except Exception:
                from config.logging_config import get_logger

                get_logger(__name__).warning(
                    "earnings gate: provider failed for %s — failing open (no block).",
                    ticker,
                    exc_info=True,
                )
                edt = None
            _earnings_seen[ticker] = edt
            return edt

        # Memoize OHLCV history within this scan (used by the T10 ADV cap below).
        # Fail-open: a provider that raises yields None and the cap is skipped.
        _history_seen: dict[str, pd.DataFrame | None] = {}

        def _history_for(ticker: str) -> pd.DataFrame | None:
            if ticker not in _history_seen:
                try:
                    _history_seen[ticker] = history_provider(ticker)
                except Exception:
                    _history_seen[ticker] = None
            return _history_seen[ticker]

        market_blocked = enforce_hours and not _is_market_open_safe()
        if market_blocked and trades:
            result.warnings.append(
                "Mercado cerrado y paper_enforce_market_hours=True — "
                f"se generaron {len(trades)} señales pero no se ejecutarán."
            )

        # ── Prefetch de red ANTES de abrir la ventana de escritura ───────────
        # Desde el primer flush (updates de HWM al autoflush de la próxima
        # query, o el primer fill) esta transacción retiene el write lock de
        # SQLite hasta el commit. Cualquier llamada de red dentro del loop de
        # gates (earnings del Gate 6, history del Gate 3b / nota R:R) estira
        # esa ventana a decenas de segundos, y peor: la escritura de
        # earnings_cache abre su PROPIA conexión y choca contra nuestro propio
        # lock → 30s de busy_timeout + "database is locked" (incidente
        # 2026-07-13: process=99s; harvest, price_cache y earnings_cache
        # muertos a los 30s). Memoizar acá — con la sesión todavía sin flushes
        # pendientes de escritura emitidos — deja el loop de abajo 100% sobre
        # datos locales; los gates leen estos mismos dicts vía los helpers.
        # Fail-open igual que los gates; costo extra: a lo sumo un lookup por
        # ticker que un gate previo hubiese salteado (cacheado con TTL, inocuo).
        if not market_blocked:
            for _t in trades:
                if _t.side == "BUY":
                    _history_for(_t.ticker)  # Gate 3b (ADV cap) + nota R:R
                if (
                    earnings_blackout_days > 0
                    and not _is_atr_forced_exit(_t.reason)
                    and (_t.side == "BUY" or earnings_block_sells)
                ):
                    _earnings_date_for(_t.ticker)

        # In manual mode, remember which (ticker, side) pairs already have a
        # pending order so we don't duplicate the same intent on every scan.
        existing_pending: set[tuple[str, str]] = set()
        if acct.mode == "manual":
            existing_pending = {
                (o.ticker, o.side)
                for o in (
                    session.query(PaperOrder)
                    .filter(PaperOrder.account_id == acct.id)
                    .filter(PaperOrder.status == "pending")
                    .all()
                )
            }

        # ── Cancelar avisos de salida ATR cuyo gatillo ya no aplica ──────────
        # Las salidas de riesgo no expiran por tiempo (reconcile las preserva),
        # pero si el precio se RECUPERA y el ATR ya no dispara para una posición
        # que sigue abierta, el aviso de venta perdió su razón → se cancela para
        # no vender en plena recuperación. Si vuelve a caer, el próximo scan lo
        # re-detecta y re-avisa. No se tocan avisos de tickers cuya posición ya
        # no existe (pudo ejecutarse a mano y falta reconciliar).
        open_tickers = {p.ticker for p in positions}
        for o in (
            session.query(PaperOrder)
            .filter(PaperOrder.account_id == acct.id)
            .filter(PaperOrder.status == "pending")
            .filter(PaperOrder.side == "SELL")
            .all()
        ):
            if not _is_atr_forced_exit(o.reason):
                continue
            if o.ticker in atr_exit_tickers:
                continue  # sigue gatillado → se mantiene el aviso
            if o.ticker not in open_tickers:
                continue  # posición ya no existe → no tocar
            o.status = "expired"
            o.decided_at = utcnow_naive()
            o.notes = (
                (o.notes or "") + "\n[scan] salida de riesgo cancelada: el precio se recuperó, "
                "el gatillo ya no aplica."
            ).strip()
            existing_pending.discard((o.ticker, o.side))
            result.warnings.append(
                f"{o.ticker} SELL (salida de riesgo) cancelada: el precio se "
                "recuperó y el gatillo ya no aplica."
            )

        # Index positions by ticker for the min-holding check.
        pos_by_ticker: dict[str, PaperPosition] = {p.ticker: p for p in positions}

        # Tickers with a recent filled SELL → blocked from BUY (anti-flap).
        recent_sell_tickers: set[str] = set()
        if anti_flap_min > 0:
            cutoff = result.scan_at - timedelta(minutes=anti_flap_min)
            rows = (
                session.query(PaperOrder.ticker)
                .filter(PaperOrder.account_id == acct.id)
                .filter(PaperOrder.side == "SELL")
                .filter(PaperOrder.status == "filled")
                .filter(PaperOrder.filled_at >= cutoff)
                .all()
            )
            recent_sell_tickers = {r[0] for r in rows}

        any_monthly = False
        for trade in trades:
            if "monthly" in (trade.reason or ""):
                any_monthly = True

            # Gate 1 — market hours. Hardest no-op.
            if market_blocked:
                result.skipped += 1
                continue

            # Gate 2 — min holding period (block premature SELLs).
            # Risk-driven exits bypass this gate — a freshly-opened position
            # that collapses (ATR stop) or sits in an over-volatile book (T09
            # vol_trim) should still be cut. ATR reasons start with ``atr_``;
            # trims with ``vol_trim``.
            risk_exit = _is_atr_forced_exit(trade.reason) or is_vol_trim_reason(trade.reason)
            if trade.side == "SELL" and min_holding_min > 0 and not risk_exit:
                p = pos_by_ticker.get(trade.ticker)
                if p is not None and p.opened_at is not None:
                    age_min = (result.scan_at - p.opened_at).total_seconds() / 60.0
                    if age_min < min_holding_min:
                        result.skipped += 1
                        result.warnings.append(
                            f"{trade.ticker} SELL bloqueado: posición abierta hace "
                            f"{age_min:.1f} min < min_holding={min_holding_min} min."
                        )
                        continue

            # Gate 2b — T6.4 score-hysteresis: SELLs de señal (con score) en la
            # zona de convicción media/alta de venta esperan una edad mínima en
            # días hábiles (validado en T6.1: el modelo predice a 5d y los exits
            # a 1-3d cortan el rally). Score < bypass ejecuta directo; exits de
            # riesgo (atr_*/vol_trim) ya quedaron afuera vía ``risk_exit``.
            if trade.side == "SELL" and not risk_exit:
                p = pos_by_ticker.get(trade.ticker)
                block_msg = signal_sell_min_age_block(
                    reason=trade.reason,
                    signal_score=trade.signal_score,
                    opened_at=(p.opened_at if p is not None else None),
                    scan_at=result.scan_at,
                    min_age_bdays=signal_sell_min_age,
                    bypass_score=signal_sell_bypass,
                )
                if block_msg is not None:
                    result.skipped += 1
                    result.warnings.append(f"{trade.ticker} {block_msg}")
                    continue

            # Gate 2c — T-CAT-4 exit-veto. Simétrico del earnings-blackout de
            # BUYs (Gate 6): pospone un SELL de señal en zona gris de score
            # (mismo universo que T6.4) cuando hay un catalyst positivo inminente
            # (earnings próximo). DEFAULT OFF + requiere provider inyectado; los
            # risk-exits (atr_*/vol_trim) nunca se vetan. No toca BUYs.
            if (
                trade.side == "SELL"
                and not risk_exit
                and catalyst_veto_enabled
                and catalyst_signal_provider is not None
            ):
                try:
                    signal = catalyst_signal_provider(trade.ticker, result.scan_at)
                except Exception:
                    from config.logging_config import get_logger

                    get_logger(__name__).warning(
                        "exit-veto: signal provider failed for %s — failing open.",
                        trade.ticker,
                        exc_info=True,
                    )
                    signal = None
                veto_msg = exit_veto_block(
                    reason=trade.reason,
                    signal_score=trade.signal_score,
                    ticker=trade.ticker,
                    scan_at=result.scan_at,
                    signal=signal,
                    enabled=catalyst_veto_enabled,
                    gray_low=signal_sell_bypass,
                    gray_high=catalyst_veto_gray_high,
                    veto_min_score=catalyst_veto_min_score,
                )
                if veto_msg is not None:
                    result.skipped += 1
                    result.warnings.append(f"{trade.ticker} {veto_msg}")
                    continue

            # Gate 3 — anti-flap (block BUYs right after a SELL of the same ticker).
            if trade.side == "BUY" and trade.ticker in recent_sell_tickers:
                result.skipped += 1
                result.warnings.append(
                    f"{trade.ticker} BUY bloqueado: anti-flap activo (SELL en últimos {anti_flap_min} min)."
                )
                continue

            # Gate 3b — ADV liquidity cap (T10). Trim a BUY whose notional
            # exceeds cap_pct of the ticker's recent average daily dollar
            # volume so we never assume we can absorb more than a small slice of
            # a name's liquidity. This *modifies* the order rather than skipping
            # it, then falls through to Gate 4 (min-trade) — so a trim that
            # lands below the dust floor is then skipped there. Fail-open:
            # unknown ADV (thin/missing history) leaves the order untouched.
            if trade.side == "BUY" and adv_cap_pct > 0 and trade.target_dollars:
                adv = recent_adv_dollars(_history_for(trade.ticker), adv_lookback_days)
                capped, was_capped = adv_capped_notional(float(trade.target_dollars), adv, adv_cap_pct)
                if was_capped:
                    result.warnings.append(
                        f"{trade.ticker} BUY recortado por ADV: "
                        f"${float(trade.target_dollars):,.0f} → ${capped:,.0f} "
                        f"({adv_cap_pct:.0%} de ADV ${adv:,.0f})."
                    )
                    trade.target_dollars = capped

            # Gate 4 — minimum trade size (skip dust BUYs whose round-trip cost
            # would dominate any expected edge).
            if trade.side == "BUY" and min_trade_usd > 0:
                td = float(trade.target_dollars or 0.0)
                if 0 < td < min_trade_usd:
                    result.skipped += 1
                    result.warnings.append(
                        f"{trade.ticker} BUY bloqueado: tamaño ${td:.2f} < mínimo ${min_trade_usd:.2f}."
                    )
                    continue

            # Gate 5 — anti-whipsaw (block re-BUY if last closed cycle was a loss
            # within the lookback window). Tightens Gate 3, which is time-only.
            if trade.side == "BUY" and whipsaw_days > 0:
                pnl_pct = _last_closed_cycle_pnl_pct(session, acct.id, trade.ticker, whipsaw_days)
                if pnl_pct is not None and pnl_pct < -whipsaw_min_loss:
                    result.skipped += 1
                    result.warnings.append(
                        f"{trade.ticker} BUY bloqueado: anti-whipsaw — último ciclo "
                        f"cerró con {pnl_pct:+.2f}% (umbral -{whipsaw_min_loss:.2f}%) "
                        f"dentro de {whipsaw_days}d."
                    )
                    continue

            # Gate 5b — anti-churn v2 (T6.5). Block re-BUY by *frequency*,
            # regardless of P/L: >= N closed cycles within the lookback window
            # means we keep flip-flopping on the ticker and the cooldown kicks
            # in. Gate 5 only blocks after losers — KO churned 3 cycles in 7
            # days starting with a winner and sailed through. The cooldown
            # expires on its own as old cycles fall out of the window.
            if trade.side == "BUY" and churn_max_cycles > 0 and churn_lookback_days > 0:
                n_cycles = _closed_cycles_count(session, acct.id, trade.ticker, churn_lookback_days)
                if n_cycles >= churn_max_cycles:
                    result.skipped += 1
                    result.warnings.append(
                        f"{trade.ticker} BUY bloqueado: anti-churn — {n_cycles} ciclos "
                        f"cerrados en {churn_lookback_days}d (máx {churn_max_cycles - 1}). "
                        f"Cooldown hasta que expire la ventana."
                    )
                    continue

            # Gate 6 — earnings blackout. Block BUY (and SELL only when
            # earnings_blackout_block_sells=True, legacy behavior) when the
            # ticker has scheduled earnings within ±earnings_blackout_days.
            # Rationale for the T08 default flip: a strategy-signaled SELL
            # arriving right before earnings is precisely the case where you
            # want to exit, not stay trapped — keeping the position open
            # creates more whipsaws than the gate prevents. BUYs are still
            # blocked (pre-earnings BUY is the classic mousetrap). ATR-forced
            # stop-loss/TP/trail SELLs (T01) bypass this gate regardless — a
            # real stop must always be able to fire. Fail-open: an unknown /
            # failed earnings lookup returns None and does not block.
            if earnings_blackout_days > 0 and not _is_atr_forced_exit(trade.reason):
                should_check = trade.side == "BUY" or earnings_block_sells
                if should_check:
                    edt = _earnings_date_for(trade.ticker)
                    if edt is not None and _earnings_blackout_hit(
                        edt, result.scan_at, earnings_blackout_days
                    ):
                        result.skipped += 1
                        result.warnings.append(
                            f"{trade.ticker} {trade.side} bloqueado: earnings el "
                            f"{edt:%Y-%m-%d} dentro de ±{earnings_blackout_days}d (blackout)."
                        )
                        continue

            # Modo manual: las sugerencias de señal se encolan como orden
            # pendiente (requieren aprobación). EXCEPCIÓN — las salidas de
            # riesgo (atr_stop/trail/tp, vol_trim) se ejecutan al toque igual
            # que en auto: un stop que queda pending puede expirar sin aprobar
            # (reconcile_account → expired) mientras la posición sigue cayendo,
            # y un stop que expira por inacción no es gestión de riesgo (N3/A2).
            # Los risk-exits caen al path de fill de abajo, reusando el
            # fill_price_override modelado (gap/touch) idéntico al camino auto.
            # R:R ex-ante (V2): para cada BUY, estampar los niveles stop/TP + R:R
            # que el engine define, en notes (persistente) y visible en la UI de
            # Paper. Display-only, fail-open, no toca la decisión (regla 3).
            buy_note = None
            if trade.side == "BUY":
                _px = prices.get(trade.ticker)
                if _px is not None and np.isfinite(_px) and _px > 0:
                    buy_note = _buy_risk_note(trade.ticker, float(_px), _history_for)

            if acct.mode == "manual" and not risk_exit:
                key = (trade.ticker, trade.side)
                if key in existing_pending:
                    result.skipped += 1
                    result.warnings.append(
                        f"{trade.ticker} {trade.side}: ya existe una orden pendiente, "
                        "no se encoló una duplicada."
                    )
                    continue
                order = _create_pending_order(
                    session,
                    acct,
                    trade,
                    current_price=prices.get(trade.ticker),
                    notes=buy_note,
                )
                existing_pending.add(key)
                result.queued += 1
                result.pending_orders.append(order.id)
                # T12: capture a session-detached snapshot for the Slack summary.
                result.new_orders.append(
                    OrderNotice(
                        account_name=account_name,
                        ticker=order.ticker,
                        side=order.side,
                        status="pending",
                        shares=order.target_shares,
                        price=prices.get(trade.ticker),
                        dollars=order.target_dollars,
                        reason=order.reason,
                        signal_score=order.signal_score,
                    )
                )
                continue

            # Fill now — camino auto, y también risk-exits de cuentas manuales
            # (ver bifurcación de arriba). Validamos precio de mercado antes de
            # operar; el fill usa el override modelado si está presente.
            px = prices.get(trade.ticker)
            if px is None or not np.isfinite(px) or px <= 0:
                result.skipped += 1
                result.warnings.append(f"{trade.ticker}: sin precio, trade omitido.")
                continue
            # Salidas forzadas por nivel (ATR) con fill modelado: el precio base
            # del fill es el modelado (gap/touch), no el último precio del scan.
            # El slippage se aplica encima igual. Se valida igual que haya precio
            # de mercado para el ticker (px) antes de operar.
            fill_px = px
            if (
                trade.fill_price_override is not None
                and np.isfinite(trade.fill_price_override)
                and trade.fill_price_override > 0
            ):
                fill_px = float(trade.fill_price_override)
            # Guard de sanity (E5): no fillar sobre un precio de escala corrupta
            # (~10× tipo KLAC) aunque haya esquivado el guard del fetch. Preferimos
            # NO operar a operar sobre basura (el notional inflado contamina peso,
            # DD, ADV y la muestra de exits).
            if _price_out_of_band(trade.ticker, fill_px, trade.side):
                result.skipped += 1
                result.warnings.append(
                    f"{trade.ticker}: precio {fill_px:.2f} fuera de banda vs histórico "
                    "— fill rechazado por sanity (posible cotización corrupta)."
                )
                continue
            # `filled` y no `order`: unas lineas mas arriba `order` es la orden
            # PENDIENTE recien creada (no-Optional) y aca es el resultado del fill,
            # que puede ser None. Dos cosas distintas con el mismo nombre.
            filled = _fill_trade(session, acct, trade, price=fill_px, notes=buy_note)
            if filled is None:
                result.skipped += 1
                result.warnings.append(f"{trade.ticker}: fill rechazado (cash o shares insuficientes).")
            else:
                result.filled += 1
                result.filled_orders.append(filled.id)
                # T12: capture a session-detached snapshot for the Slack summary.
                result.new_orders.append(
                    OrderNotice(
                        account_name=account_name,
                        ticker=filled.ticker,
                        side=filled.side,
                        status="filled",
                        shares=filled.fill_shares,
                        price=filled.fill_price,
                        dollars=filled.fill_value,
                        reason=filled.reason,
                        signal_score=filled.signal_score,
                    )
                )

        # Stamp account + monthly rebalance flag
        acct.last_scan_at = result.scan_at
        if any_monthly and acct.mode == "auto":
            acct.last_monthly_rebalance = result.scan_at

        # Recompute equity after fills
        positions_after = (
            session.query(PaperPosition)
            .filter(PaperPosition.account_id == account_id)
            .filter(PaperPosition.shares > 0)
            .all()
        )
        equity_after = acct.cash + sum(p.shares * prices.get(p.ticker, p.avg_cost) for p in positions_after)
        result.equity_after = float(equity_after)
        # session_scope commits automatically on successful exit

    # Snapshot outside the transaction — opens its own session. Estimate the
    # post-scan book volatility (T10) for the equity curve; best-effort / NULL
    # when the overlay is off or history is thin.
    portfolio_sigma = _estimate_book_sigma(positions_after, prices, history_provider)
    record_equity_snapshot(account_id, prices, portfolio_sigma=portfolio_sigma)

    # ── Slack notification (T12) ─────────────────────────────────────────────
    # Send one summary message per scan listing the new orders. Runs OUTSIDE the
    # critical path and is fully fail-open: a missing token, a disabled switch,
    # or a notifier that raises must never affect the scan result.
    _maybe_notify_slack(result, account_name, account_slack_notify, slack_notifier)

    # OPS1(c) — timing por fase. ``process`` absorbe el loop de gates+fill más el
    # snapshot/slack del final; fetch+analyze+process == scan_seconds exacto.
    t_scan_end = perf_counter()
    result.phase_seconds = {
        "fetch": round(t_after_fetch - t_scan_start, 4),
        "analyze": round(t_after_analyze - t_after_fetch, 4),
        "process": round(t_scan_end - t_after_analyze, 4),
    }
    result.scan_seconds = round(t_scan_end - t_scan_start, 4)
    from config.logging_config import get_logger

    get_logger(__name__).info(result.summary())
    return result


def _maybe_notify_slack(
    result: ScanResult,
    account_name: str,
    account_slack_notify: bool,
    slack_notifier: SlackNotifier | None,
) -> None:
    """
    Build and send the per-scan Slack summary, gated by settings. Honors the
    ``slack_notifications_enabled`` master switch (global), the per-account
    ``slack_notify`` opt-out, and the ``slack_notify_on`` filter (pending /
    filled / both). Fail-open: any error is logged and swallowed so the scan
    is never disrupted by a broken Slack integration.
    """
    try:
        if not bool(settings.get("slack_notifications_enabled", False)):
            return
        if not account_slack_notify:
            return
        notify_on = str(settings.get("slack_notify_on", "both"))
        notices = select_notifiable(result.new_orders, notify_on)
        if not notices:
            return
        text = format_scan_summary(
            account_name,
            notices,
            scan_at=result.scan_at,
            equity_after=result.equity_after,
        )
        if not text:
            return
        notifier = slack_notifier or default_notifier
        notifier(text)
    except Exception:
        from config.logging_config import get_logger

        get_logger(__name__).exception(
            "Slack notify: failed for account %r (fail-open, scan unaffected).",
            account_name,
        )


# ── Manual-mode approvals ─────────────────────────────────────────────────────


def _approval_gate_block(order: PaperOrder, earnings_provider: EarningsProvider) -> str | None:
    """T7.2 (M4 del code review): re-correr Gates 1 y 6 al momento de aprobar.

    Una orden pendiente puede aprobarse horas o días después de creada, en
    condiciones distintas a las del scan que la generó — "quedó pendiente del
    viernes, se aprueba el lunes dentro del blackout de earnings" es el
    mousetrap exacto que Gate 6 existe para prevenir. Semántica idéntica a
    ``run_scan``:

    - Gate 1 — market hours (``paper_enforce_market_hours``).
    - Gate 6 — earnings blackout (``earnings_blackout_days``): bloquea BUYs;
      SELLs solo si ``earnings_blackout_block_sells=True``; los exits forzados
      por ATR (T01) siempre pasan. Fail-open si el provider falla.

    Los demás gates (anti-flap, min-holding, hysteresis, churn) NO se
    re-chequean: regulan señales automáticas y la aprobación es una decisión
    manual explícita del usuario.

    Returns the human-readable block reason, or ``None`` if the fill may
    proceed.
    """
    # Gate 1 — market hours.
    if bool(settings.get("paper_enforce_market_hours", True)) and not _is_market_open_safe():
        return "mercado cerrado (paper_enforce_market_hours=True)."

    # Gate 6 — earnings blackout.
    blackout_days = max(0, int(settings.get("earnings_blackout_days", 2)))
    if blackout_days > 0 and not _is_atr_forced_exit(order.reason):
        block_sells = bool(settings.get("earnings_blackout_block_sells", False))
        if order.side == "BUY" or block_sells:
            try:
                edt = earnings_provider(order.ticker)
            except Exception:
                from config.logging_config import get_logger

                get_logger(__name__).warning(
                    "approve re-gate: earnings provider failed for %s — failing open.",
                    order.ticker,
                    exc_info=True,
                )
                edt = None
            if edt is not None and _earnings_blackout_hit(edt, utcnow_naive(), blackout_days):
                return f"earnings el {edt:%Y-%m-%d} dentro de ±{blackout_days}d (blackout)."
    return None


def approve_order(
    order_id: int,
    *,
    prices_provider: PricesProvider | None = None,
    earnings_provider: EarningsProvider | None = None,
    override_gates: bool = False,
) -> PaperOrder | None:
    """Fill a pending order at the current market price.

    T7.2: antes del fill se re-aplican Gate 1 (market hours) y Gate 6
    (earnings blackout) — ver :func:`_approval_gate_block`. Una orden
    bloqueada NO se consume: queda ``pending`` con el motivo en ``notes`` y
    se devuelve tal cual, para que el caller muestre la razón y, si el
    usuario insiste, reintente con ``override_gates=True`` (la aprobación
    humana explícita es el override documentado).
    """
    prices_provider = prices_provider or _default_prices_provider
    earnings_provider = earnings_provider or _default_earnings_provider

    with session_scope() as session:
        order: PaperOrder | None = session.query(PaperOrder).filter(PaperOrder.id == order_id).first()
        if order is None or order.status != "pending":
            return None

        acct = session.query(PaperAccount).filter(PaperAccount.id == order.account_id).first()
        if acct is None:
            return None

        # T7.2 — re-gates en la aprobación (Gates 1 y 6).
        if not override_gates:
            block_reason = _approval_gate_block(order, earnings_provider)
            if block_reason is not None:
                order.notes = (
                    (order.notes or "") + f"\n[approve] bloqueada por re-gate: {block_reason}"
                ).strip()
                session.flush()
                session.refresh(order)
                session.expunge(order)
                return order  # status sigue "pending" — no se consume.

        prices = prices_provider([order.ticker])
        px = prices.get(order.ticker)
        if px is None or not np.isfinite(px) or px <= 0:
            order.status = "expired"
            order.notes = (order.notes or "") + "\n[approve] sin precio, expirada."
            order.decided_at = utcnow_naive()
            session.flush()
            session.refresh(order)
            session.expunge(order)
            return order
        # Guard de sanity (E5): un precio de aprobación con escala corrupta (~10×
        # tipo KLAC) no debe fillarse. Tratado como "sin precio" → expira; el
        # usuario re-genera la orden cuando Yahoo devuelva un precio sano.
        if _price_out_of_band(order.ticker, px, order.side):
            order.status = "expired"
            order.notes = (order.notes or "") + "\n[approve] precio fuera de banda, expirada."
            order.decided_at = utcnow_naive()
            session.flush()
            session.refresh(order)
            session.expunge(order)
            return order

        # Convert the pending order into a TargetTrade and fill.
        trade = TargetTrade(
            ticker=order.ticker,
            side=order.side,
            target_shares=order.target_shares,
            target_dollars=order.target_dollars,
            reason=f"approved: {order.reason or ''}".strip(),
            source=order.source or "manual",
        )

        order.status = "approved"
        order.decided_at = utcnow_naive()

        filled = _fill_trade(session, acct, trade, price=px, reuse_order=order)

        # Si _fill_trade no pudo ejecutar (cash/shares insuficientes), no dejar
        # la orden colgada en "approved" para siempre. _fill_trade exitoso
        # reescribe order.status a "filled" via _stamp_order_filled(reuse_order=
        # order); si sigue "approved" es que falló.
        if filled is None and order.status == "approved":
            # Aprobación encadenada (N2): una BUY que no se llena por falta de
            # cash NO debe expirar si todavía hay una SELL pendiente que, al
            # aprobarse, libera el cash que la financia. El budget se sizea
            # contra cash+est_proceeds del scan, pero en manual las SELL no se
            # ejecutan solas → aprobar la BUY primero la mataba por "cash
            # fantasma" (12 BUYs expiradas, auditoría 2026-06-25). La dejamos
            # pending para reintentar tras aprobar la(s) SELL(s). _fill_trade ya
            # topa el budget en acct.cash al precio de aprobación → nunca sobre-
            # apalanca. reconcile_account la barre igual si nunca se financia.
            if order.side == "BUY" and _has_pending_sells(session, acct.id, exclude_order_id=order.id):
                order.status = "pending"
                order.decided_at = None
                order.notes = (
                    (order.notes or "") + "\n[approve] sin liquidez suficiente; queda pendiente — "
                    "aprobá primero la(s) SELL(s) pendiente(s) para liberar cash."
                ).strip()
            else:
                order.status = "expired"
                order.notes = (
                    (order.notes or "") + "\n[approve] fill rechazado: cash o shares insuficientes."
                ).strip()

        session.flush()

        if filled is not None:
            session.refresh(filled)
            session.expunge(filled)
            return filled
        session.refresh(order)
        session.expunge(order)
        return order


def reject_order(order_id: int, note: str = "") -> PaperOrder | None:
    with session_scope() as session:
        order = session.query(PaperOrder).filter(PaperOrder.id == order_id).first()
        if order is None or order.status != "pending":
            return None
        order.status = "rejected"
        order.decided_at = utcnow_naive()
        if note:
            order.notes = (order.notes or "") + f"\n[reject] {note}"
        session.flush()
        session.refresh(order)
        session.expunge(order)
        return order


# ── Internal: create pending / fill trade ─────────────────────────────────────


def _has_pending_sells(session, account_id: int, *, exclude_order_id: int | None = None) -> bool:
    """¿Hay alguna SELL pendiente en la cuenta (que podría liberar cash)?

    Soporta la aprobación encadenada (N2): una BUY sub-financiada NO expira si
    todavía hay una SELL pendiente que, al aprobarse, libera el cash que la
    financia. Sin SELLs pendientes no hay financiamiento posible → la BUY sí es
    inejecutable y expira como antes.
    """
    q = (
        session.query(PaperOrder.id)
        .filter(PaperOrder.account_id == account_id)
        .filter(PaperOrder.side == "SELL")
        .filter(PaperOrder.status == "pending")
    )
    if exclude_order_id is not None:
        q = q.filter(PaperOrder.id != exclude_order_id)
    return session.query(q.exists()).scalar()


def _create_pending_order(
    session,
    acct: PaperAccount,
    trade: TargetTrade,
    *,
    current_price: float | None = None,
    notes: str | None = None,
) -> PaperOrder:
    """
    Persist a TargetTrade as a pending PaperOrder.

    Si la suggestion es BUY y target_shares no fue seteado por la estrategia,
    lo computamos a partir de target_dollars + current_price + slippage para
    que el usuario vea un número de shares entero en la orden pendiente.
    Para SELL ya se setea target_shares; lo redondeamos hacia abajo a entero.

    ``notes`` (V2, opcional): nota display-only (R:R/stop/TP para BUYs) que se
    guarda en ``PaperOrder.notes`` y se muestra en la UI de Paper.
    """
    target_shares = trade.target_shares

    if (
        trade.side == "BUY"
        and target_shares is None
        and trade.target_dollars is not None
        and current_price is not None
        and np.isfinite(current_price)
        and current_price > 0
    ):
        budget = min(float(trade.target_dollars), acct.cash)
        fill_price = current_price * (1 + acct.slippage)
        raw_shares = (budget * (1 - acct.commission)) / fill_price
        int_shares = int(raw_shares)
        if int_shares >= 1:
            target_shares = float(int_shares)

    elif trade.side == "SELL" and target_shares is not None and target_shares > 0:
        target_shares = float(int(float(target_shares)))  # floor a entero
        if target_shares < 1.0:
            target_shares = trade.target_shares  # dejar lo original

    order = PaperOrder(
        account_id=acct.id,
        ticker=trade.ticker,
        side=trade.side,
        target_shares=target_shares,
        target_dollars=trade.target_dollars,
        reason=trade.reason,
        source=trade.source,
        signal_score=trade.signal_score,
        status="pending",
        notes=notes,
    )
    session.add(order)
    session.flush()
    return order


def _fill_trade(
    session,
    acct: PaperAccount,
    trade: TargetTrade,
    *,
    price: float,
    reuse_order: PaperOrder | None = None,
    notes: str | None = None,
) -> PaperOrder | None:
    """
    Execute a trade against the live account state. Returns the filled
    PaperOrder (new or reused) or None if the trade couldn't happen
    (zero shares, zero cash, etc.).

    Cost models
    -----------
    Slippage: applied via ``PercentSlippage(acct.slippage)`` so that any
    future per-account override (e.g. ``TickSlippage``) plugs in here
    without changing this function.
    Commission: driven by the global ``ibkr_commission_plan`` setting via
    ``get_active_commission_model()``. ``"tiered"``/``"fixed"`` use the
    realistic IBKR Pro model (per-share + min + 1% cap + regulatory/exchange
    pass-through); ``"legacy"`` falls back to the per-account flat % field
    so older tests and pre-migration accounts keep their previous behaviour.
    """
    from config.settings_manager import settings as _settings
    from paper_trading.costs import (
        commission_from_legacy,
        get_active_commission_model,
        slippage_from_legacy,
    )

    side = trade.side
    plan = str(_settings.get("ibkr_commission_plan", "tiered")).lower()
    if plan == "legacy":
        commission_m = commission_from_legacy(acct.commission)
        commission_pct = float(acct.commission)
    else:
        commission_m = get_active_commission_model()
        # Per-share models don't have a meaningful "%" — keep budgeting code
        # working by approximating with the legacy field. The real cost is
        # recomputed from commission_m.cost(...) after the fill anyway.
        commission_pct = float(acct.commission)
    slippage_m = slippage_from_legacy(acct.slippage)

    if side == "BUY":
        budget = trade.target_dollars if trade.target_dollars is not None else 0.0
        budget = min(float(budget), acct.cash)
        if budget <= 1e-6:
            return None
        fill_price = slippage_m.adjust_price(side="BUY", price=price)

        # Shares ahora son ENTEROS — el usuario va a ejecutar manualmente en
        # un broker que no permite fracciones. Floor del cómputo crudo y
        # recalculamos el cash gastado a partir de las shares finales.
        raw_shares = (budget * (1 - commission_pct)) / fill_price
        shares_got = float(int(raw_shares))  # floor a entero
        if shares_got < 1.0:
            return None

        # Real notional + commission a partir de las shares enteras.
        actual_notional = shares_got * fill_price
        commission_paid = commission_m.cost(side="BUY", shares=shares_got, price=fill_price)
        actual_cost = actual_notional + commission_paid
        # Edge case: si el actual_cost supera el budget por redondeo, recortar.
        if actual_cost > acct.cash + 1e-6:
            return None

        # Update / create position
        pos = (
            session.query(PaperPosition)
            .filter(PaperPosition.account_id == acct.id)
            .filter(PaperPosition.ticker == trade.ticker)
            .first()
        )
        if pos is None:
            pos = PaperPosition(
                account_id=acct.id,
                ticker=trade.ticker,
                shares=shares_got,
                avg_cost=fill_price,
                opened_at=utcnow_naive(),
                entry_reason=trade.reason,
                high_water_mark=float(fill_price),
            )
            session.add(pos)
        else:
            new_total_cost = pos.shares * pos.avg_cost + shares_got * fill_price
            pos.shares += shares_got
            pos.avg_cost = new_total_cost / pos.shares
            pos.updated_at = utcnow_naive()
            # Advance HWM on add-ons too, so a later trailing-stop check
            # doesn't ignore a higher post-add fill price.
            if pos.high_water_mark is None or float(fill_price) > float(pos.high_water_mark):
                pos.high_water_mark = float(fill_price)
        acct.cash -= actual_cost

        slippage_cost = shares_got * (fill_price - price)
        return _stamp_order_filled(
            session,
            acct,
            trade,
            reuse_order,
            fill_price=fill_price,
            fill_shares=shares_got,
            commission_paid=commission_paid,
            slippage_cost=slippage_cost,
            notes=notes,
        )

    elif side == "SELL":
        pos = (
            session.query(PaperPosition)
            .filter(PaperPosition.account_id == acct.id)
            .filter(PaperPosition.ticker == trade.ticker)
            .first()
        )
        if pos is None or pos.shares <= 1e-9:
            return None
        want_shares = trade.target_shares
        if want_shares is None or want_shares <= 0:
            want_shares = pos.shares
        want_shares = float(want_shares)

        # Floor a entero. Excepción: si la intención es liquidar todas las
        # shares enteras de la posición, vendemos también el residual
        # fraccional (posiciones legacy de antes del cambio a enteros) para
        # cerrar la posición limpia.
        int_want = int(want_shares)
        int_held = int(pos.shares)
        if int_want < 1:
            return None
        if int_want >= int_held:
            sell_shares = float(pos.shares)  # cierre total + residual
        else:
            sell_shares = float(int_want)  # trim parcial entero

        sell_shares = min(sell_shares, float(pos.shares))
        if sell_shares <= 1e-9:
            return None

        fill_price = slippage_m.adjust_price(side="SELL", price=price)
        gross = sell_shares * fill_price
        commission_paid = commission_m.cost(side="SELL", shares=sell_shares, price=fill_price)
        proceeds = gross - commission_paid
        pos.shares -= sell_shares
        pos.updated_at = utcnow_naive()
        acct.cash += proceeds

        # If fully closed, drop the row.
        if pos.shares <= 1e-9:
            session.delete(pos)

        slippage_cost = sell_shares * (price - fill_price)
        return _stamp_order_filled(
            session,
            acct,
            trade,
            reuse_order,
            fill_price=fill_price,
            fill_shares=sell_shares,
            commission_paid=commission_paid,
            slippage_cost=slippage_cost,
            notes=notes,
        )

    return None


def _stamp_order_filled(
    session,
    acct: PaperAccount,
    trade: TargetTrade,
    reuse_order: PaperOrder | None,
    *,
    fill_price: float,
    fill_shares: float,
    commission_paid: float,
    slippage_cost: float,
    notes: str | None = None,
) -> PaperOrder:
    """Create or update a PaperOrder as 'filled' and return it.

    ``notes`` (V2) solo se aplica a órdenes recién creadas (auto BUY); en el
    path ``reuse_order`` la nota ya fue estampada al crear la pendiente.
    """
    now = utcnow_naive()
    if reuse_order is None:
        order = PaperOrder(
            account_id=acct.id,
            ticker=trade.ticker,
            side=trade.side,
            target_shares=trade.target_shares,
            target_dollars=trade.target_dollars,
            reason=trade.reason,
            source=trade.source,
            signal_score=trade.signal_score,
            status="filled",
            created_at=now,
            filled_at=now,
            fill_price=float(fill_price),
            fill_shares=float(fill_shares),
            commission_paid=float(commission_paid),
            slippage_cost=float(slippage_cost),
            notes=notes,
        )
        session.add(order)
        session.flush()
    else:
        # Idempotency guard: don't double-fill an already-filled order.
        # Without this, a retry of approve_order on a stale view of the DB
        # could double-spend cash. The caller already filters by
        # status == 'pending', but we belt-and-braces here too.
        if reuse_order.status == "filled":
            return reuse_order
        reuse_order.status = "filled"
        reuse_order.filled_at = now
        reuse_order.fill_price = float(fill_price)
        reuse_order.fill_shares = float(fill_shares)
        reuse_order.commission_paid = float(commission_paid)
        reuse_order.slippage_cost = float(slippage_cost)
        order = reuse_order
    return order


# ── Recovery helpers ──────────────────────────────────────────────────────────


def reconcile_account(account_id: int, *, expire_pending_after_hours: int = 24) -> int:
    """
    Sweep stale pending orders for an account.

    Pending orders that were generated before the most recent app crash
    can pile up indefinitely if the user never visits the Paper Trading
    tab again. This helper marks anything older than
    ``expire_pending_after_hours`` as ``expired`` so the engine starts
    each session with a clean slate.

    T7.2: also sweeps orders stuck in ``approved`` — a status that should be
    transient (approve_order rewrites it to ``filled`` or ``expired`` in the
    same transaction). Orders frozen there predate that fix and would sit in
    limbo forever; they never touched cash/positions, so expiring them is
    side-effect-free.

    Returns the number of orders expired.
    """
    from database.models import session_scope

    cutoff = utcnow_naive() - timedelta(hours=max(0, int(expire_pending_after_hours)))
    expired = 0
    try:
        with session_scope() as session:
            stale = (
                session.query(PaperOrder)
                .filter(PaperOrder.account_id == account_id)
                .filter(PaperOrder.status == "pending")
                .filter(PaperOrder.created_at <= cutoff)
                .all()
            )
            for o in stale:
                # Las SALIDAS DE RIESGO (atr_stop/trail/tp, vol_trim) NO se
                # expiran: son un aviso de "vendé esto" que el usuario ejecuta a
                # mano en el broker, y dejarlo caer en silencio es peligroso.
                # Siguen pendientes (y re-avisando) hasta que se ejecuten o se
                # rechacen. Los BUY y los SELL de señal sí expiran normal.
                if o.side == "SELL" and (_is_atr_forced_exit(o.reason) or is_vol_trim_reason(o.reason)):
                    continue
                o.status = "expired"
                o.decided_at = utcnow_naive()
                o.notes = ((o.notes or "") + "\n[reconcile] expired automatically.").strip()
                expired += 1

            # T7.2 — limbo "approved": aprobadas que nunca llegaron a filled
            # (bug pre-fix). El cutoff las cubre de sobra; no hay fill que
            # revertir porque _fill_trade nunca corrió para ellas.
            limbo = (
                session.query(PaperOrder)
                .filter(PaperOrder.account_id == account_id)
                .filter(PaperOrder.status == "approved")
                .filter(PaperOrder.created_at <= cutoff)
                .all()
            )
            for o in limbo:
                o.status = "expired"
                o.decided_at = utcnow_naive()
                o.notes = ((o.notes or "") + "\n[reconcile] approved-limbo (pre-T7.2), expired.").strip()
                expired += 1
        if expired:
            from config.logging_config import get_logger

            get_logger(__name__).info(
                "reconcile_account(%d): expired %d stale pending orders.",
                account_id,
                expired,
            )
    except Exception:
        from config.logging_config import get_logger

        get_logger(__name__).exception("reconcile_account(%d) failed", account_id)
    return expired
