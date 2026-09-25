"""
Panel de métricas de funcionamiento del engine (pestaña "Métricas").

Lee ``finanzias.db`` (solo lectura) y calcula, para una cuenta de paper-trading,
un payload con la efectividad real de las compras/ventas. Diseñado como módulo
*puro y testeable*: todas las funciones de cálculo aceptan una conexión sqlite3
o estructuras de datos, sin tocar Qt ni la red.

Dos definiciones complementarias de "compra buena/mala" (elegidas con el usuario):

1. **P/L realizado** — empareja BUY→SELL por FIFO y mide la ganancia neta de
   comisión + slippage de cada *round-trip* cerrado. Es la plata real.
2. **Timing (forward return)** — mide cuánto se movió el precio en los 5/20 días
   hábiles posteriores a cada BUY filled, usando ``historical_data_cache``.
   Evalúa la calidad de la *entrada* aunque la posición siga abierta.

Además: calibración de los SELL de señal, churn, mix de razones de salida, y una
**serie temporal de efectividad** (P/L realizado acumulado + win-rate móvil) lista
para overlayar las fechas de los commits que cambian la lógica del engine.

Schema del payload (``build_metrics``)::

    {
      "generated_at": ISO,
      "account_id": 1,
      "realized": {
        "n_round_trips", "total_pnl", "n_wins", "n_losses", "win_rate",
        "profit_factor", "avg_win", "avg_loss", "payoff_ratio", "expectancy",
        "avg_hold_days", "total_costs",
        "excursion": {"n","median_mae","median_mfe","avg_mae","avg_mfe",
                      "worst_mae","best_mfe"},   # MAE/MFE distribución (V1)
        "by_exit_kind": {kind: {"n", "pnl", "avg"}},
        "per_ticker": [{"ticker","pnl","n"}...],
        "worst_ticker": {"ticker","pnl"}, "pnl_ex_worst": float,
        "top_winners": [...], "top_losers": [...],
        "round_trips": [ {..., "mae", "mfe"} ]   # cronológico por sell_day
      },
      "friction": {   # V1: costo total de operar (todas las órdenes filled)
        "commission","slippage","friction","n_orders","gross_pnl","pct_of_gross"
      },
      "benchmark": {  # V1: retorno de la cuenta vs SPY sobre la misma ventana
        "available","ticker","start_day","end_day",
        "account_return","spy_return","vs_spy",
        "account_dividends","account_return_total",          # tarea 221: total vs total
        "dividendos_completos","dividendos_faltantes",       # calendario incompleto → piso
        "base_equity","base_anclaje","spy_anclaje",          # tarea 223: de dónde sale cada ancla
        "stale","spy_end_day",     # tarea 22: SPY desactualizado → no se compara
        "spy_start_day",           # tarea 225: el espejo — serie más corta que la cuenta
        "motivo"                # tarea 218: por qué NO hay número
      },
      "concentration": {  # V2: concentración del book vivo (display-only)
        "n","total_value","weights":[{"ticker","weight","market_value","sector",
        "unrealized_pnl"}...],"top_ticker","top_weight","hhi","effective_names",
        "sectors":[{"sector","weight"}...],"mean_correlation",
        "total_unrealized_pnl","pnl_ex_best","pnl_ex_worst","best_ticker","worst_ticker"
      },
      "timing": {
        "n5","good5","good5_pct","mean5","median5",
        "n20","good20","good20_pct","mean20","median20",
        "score_fwd5_corr", "score_fwd5_n",
        "per_buy": [{"ticker","score","fwd5","fwd20","day"}...]
      },
      "sell_calibration": {"n","up_after","up_after_pct","mean_fwd5"},
      "sell_timing": {   # calidad de la SALIDA (mirror de timing; venta buena = fwd5≤0)
        "n5","good5","good5_pct","mean5","median5",
        "n20","good20","good20_pct","mean20","median20",
        "by_exit_kind": {kind: {"n","good_pct","mean_fwd5"}},
        "sell_score_fwd5_corr", "sell_score_fwd5_n",
        "top_avoided":[…], "top_regret":[…],
        "per_sell": [{"ticker","score","exit_kind","fwd5","fwd20","day"}...]
      },
      "churn": {"n_le7d", "events":[{"ticker","gap_days","sell_id","buy_id"}...]},
      "timeline": [{"day","cum_pnl","trades","rolling_win_rate"}...],
      "open_positions": [{"ticker","shares","avg_cost","mark","mtm_pct"}...],
      "expired_buys": {"n", "by_ticker": {...}},
      "performance_score": {   # tarea 194: score mensual, 100 = $4.000 realizados en el mes
        "target_monthly_usd","weight_money","weight_quality",
        "months":[{"month","realized_pnl","n_round_trips","n_wins","money_pct",
                   "quality_pct","score","in_progress"}...],
        "current","best","worst","avg_completed"
      }
    }

``commit_markers(repo_dir)`` es aparte (usa git) para no acoplar el cálculo al repo.
"""

from __future__ import annotations

import sqlite3
import subprocess
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from analysis.performance_score import performance_score_panel
from data import historical_series

# Ventana del forward return (días hábiles aproximados por índice de barras 1d).
FWD_SHORT = 5
FWD_LONG = 20
CHURN_DAYS = 7

# Benchmark de mercado (V1). SPY total-return implícito del cache yfinance
# (auto_adjust=True) — sesgo documentado en el BACKLOG: los dividendos ya están
# reinvertidos en el ajuste, así que la comparación es contra el retorno total.
BENCHMARK_TICKER = "SPY"

# Umbral de "SPY desactualizado" (tarea 22, BENCH-STALE). Si el último close de
# SPY queda más de estos días hábiles atrás del último snapshot de equity, el
# benchmark está stale: NO se compara (comparar la cuenta sobre la ventana
# completa contra un SPY recortado sesga el vs_spy en silencio) ni se dibuja la
# línea corta. Tolera el lag normal de 1-2 ruedas (la barra 1d de hoy recién
# aparece tras el cierre, y fines de semana/feriados).
BENCHMARK_STALE_BDAYS = 3


def benchmark_stale_bdays(spy_last_day: str | None, ref_day: str | None) -> int:
    """Días hábiles que el último close de SPY queda ATRÁS de ``ref_day``.

    Positivo = SPY viejo respecto de ``ref_day``; ≤0 = al día o adelante.
    Ambas fechas son ``YYYY-MM-DD`` (se ignora la parte de hora). Devuelve ``0``
    ante fechas inválidas o ausentes — no se marca stale por un parseo fallido.
    Pura y testeable (usa ``np.busday_count``, el idiom del repo).
    """
    if not spy_last_day or not ref_day:
        return 0
    try:
        return int(np.busday_count(spy_last_day[:10], ref_day[:10]))
    except (TypeError, ValueError):
        return 0


def benchmark_start_gap_bdays(spy_first_day: str | None, ref_day: str | None) -> int:
    """Días hábiles que el PRIMER close de SPY arranca DESPUÉS de ``ref_day`` (tarea 225).

    El espejo de ``benchmark_stale_bdays``. Es la misma cuenta de días hábiles con los
    roles dados vuelta, y existe como función aparte **para que el call site diga qué
    mide**: llamar al otro con los argumentos invertidos da el número correcto y un
    lector que confíe en los nombres entiende lo contrario.

    Positivo = la serie empieza tarde, o sea que SPY va a medir una ventana **más corta**
    que la cuenta. ``0`` ante fechas ausentes o inválidas, igual que su espejo: no se
    apaga una tarjeta por un parseo fallido.
    """
    return -benchmark_stale_bdays(spy_first_day, ref_day)


# Keywords que marcan commits que cambian la *lógica de trading* (para el overlay
# del gráfico de efectividad). Se filtran del git log por subject.
_BEHAVIOR_COMMIT_KEYWORDS = (
    "gate",
    "exit",
    "stop",
    "atr",
    "churn",
    "hysteresis",
    "vol-overlay",
    "vol overlay",
    "overlay",
    "sizing",
    "t6.",
    "t-cat",
    "t01",
    "t05",
    "t06",
    "t09",
    "t10",
    "anti-churn",
    "anti-whipsaw",
    "regime",
    "regimen",
    "kill",
    "stacking",
    "veto",
    "hit-rate",
    "score-hysteresis",
)
# Prefijos de commits de infraestructura/datos que NO cambian la lógica de
# trading (se excluyen aunque matcheen una keyword por casualidad).
_INFRA_COMMIT_PREFIXES = ("perf(", "chore(", "docs(", "fix(db", "fix(catalyst): eliminar")


# ── helpers de fecha ──────────────────────────────────────────────────────────
def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def _day(ts: str | None) -> str | None:
    return ts[:10] if ts else None


# ── series de cierre desde el cache histórico ─────────────────────────────────
def load_close_series(con: sqlite3.Connection, ticker: str) -> list[tuple[str, float]] | None:
    """Lista ``(YYYY-MM-DD, close)`` ascendente, o ``None`` si no hay serie.

    **Delega en ``data.historical_series`` desde la tarea 218.** Antes hacia el
    ``SELECT ... FROM historical_data_cache`` a mano, y esa tabla no se escribe desde
    que ARQ1 movio el cache a Parquet (2026-07-12) ni tiene filas desde que la
    migracion 0011 la vacio (2026-09-02): devolvia ``None`` para TODO ticker, lo que
    apago la tarjeta VS SPY, MAE/MFE y el fwd-5d sin que nada lo dijera.
    """
    return historical_series.close_series(con, ticker)


def load_ohlc_series(con: sqlite3.Connection, ticker: str) -> list[tuple[str, float, float]] | None:
    """Lista ``(YYYY-MM-DD, high, low)`` ascendente, o ``None`` si no hay serie.

    El rango intradia que un stop/target realmente ve — usado para MAE/MFE. Devuelve
    ``None`` si la fuente no trae High/Low, que es el contrato que ya tenia. Delega
    en ``data.historical_series`` desde la tarea 218 (ver ``load_close_series``).
    """
    return historical_series.ohlc_series(con, ticker)


def excursions(
    series_hl: list[tuple[str, float, float]] | None,
    buy_day: str | None,
    sell_day: str | None,
    buy_price: float | None,
) -> tuple[float | None, float | None]:
    """MAE/MFE de un round-trip long, en fracción sobre el precio de entrada.

    Sobre las barras diarias con ``buy_day <= fecha <= sell_day`` (inclusive):
      * MFE (max favorable excursion) = ``max(High)/buy_price - 1`` — la mejor
        ganancia no realizada que llegó a estar disponible.
      * MAE (max adverse excursion) = ``min(Low)/buy_price - 1`` — la peor pérdida
        no realizada que la posición aguantó (típicamente ≤ 0).

    Devuelve ``(mae, mfe)``. ``(None, None)`` si falta serie, precio o ventana.
    Usa High/Low (no close-to-close): es lo que ve un stop/target intradía.
    """
    if not series_hl or not buy_day or buy_price is None or buy_price <= 0:
        return (None, None)
    end = sell_day or buy_day
    highs: list[float] = []
    lows: list[float] = []
    for d, h, lw in series_hl:
        if d < buy_day:
            continue
        if d > end:
            break
        highs.append(h)
        lows.append(lw)
    if not highs:
        return (None, None)
    mfe = max(highs) / buy_price - 1.0
    mae = min(lows) / buy_price - 1.0
    return (mae, mfe)


def _annotate_excursions(con: sqlite3.Connection, rts: list[dict]) -> None:
    """Agrega ``mae``/``mfe`` a cada round-trip in-place (High/Low del cache 1d)."""
    series_cache: dict[str, list[tuple[str, float, float]] | None] = {}
    for r in rts:
        t = r["ticker"]
        if t not in series_cache:
            series_cache[t] = load_ohlc_series(con, t)
        mae, mfe = excursions(series_cache[t], r.get("buy_day"), r.get("sell_day"), r.get("buy_price"))
        r["mae"] = mae
        r["mfe"] = mfe


def forward_return(series: list[tuple[str, float]] | None, day: str, n: int) -> float | None:
    """Retorno close-to-close ``n`` barras después de la primera barra ≥ ``day``.

    ``None`` si no hay serie, no hay barra base, o no hay ``n`` barras por delante.
    """
    if not series:
        return None
    base_i = None
    for i, (d, _) in enumerate(series):
        if d >= day:
            base_i = i
            break
    if base_i is None or base_i + n >= len(series):
        return None
    p0 = series[base_i][1]
    p1 = series[base_i + n][1]
    if p0 <= 0:
        return None
    return (p1 / p0) - 1.0


# ── lectura de órdenes ────────────────────────────────────────────────────────
def _filled_orders(con: sqlite3.Connection, account_id: int) -> list[dict]:
    rows = con.execute(
        "SELECT id,ticker,side,fill_price,fill_shares,commission_paid,slippage_cost,"
        "signal_score,reason,filled_at FROM paper_orders "
        "WHERE account_id=? AND status='filled' ORDER BY filled_at, id",
        (account_id,),
    ).fetchall()
    cols = (
        "id",
        "ticker",
        "side",
        "fill_price",
        "fill_shares",
        "commission",
        "slippage",
        "score",
        "reason",
        "filled_at",
    )
    # strict=True: `cols` y el SELECT de arriba tienen que coincidir. Si
    # alguien agrega una columna a uno y no al otro, es mejor que grite que
    # devolver dicts truncados en silencio.
    return [dict(zip(cols, r, strict=True)) for r in rows]


def _exit_kind(reason: str | None) -> str:
    r = reason or ""
    if "atr_stop" in r:
        return "atr_stop"
    if "atr_trail" in r:
        return "atr_trail"
    if "atr_tp" in r:
        return "atr_tp"
    if r.startswith("analyze SELL"):
        return "signal_sell"
    return "other"


# ── FIFO round-trip pairing ───────────────────────────────────────────────────
def pair_round_trips(orders: list[dict]) -> list[dict]:
    """Empareja BUY→SELL por FIFO. Devuelve round-trips cerrados, en orden de venta.

    Cada round-trip: ticker, buy_id, sell_id, shares, buy_price, sell_price,
    pnl (neto de comisión+slippage prorrateados), pnl_pct, buy_score, sell_score,
    sell_reason, exit_kind, buy_day, sell_day, hold_days, costs.
    """
    lots: dict[str, deque] = defaultdict(deque)
    buy_time: dict[int, datetime | None] = {}
    rts: list[dict] = []
    for o in orders:
        sh = o["fill_shares"] or 0.0
        if sh <= 0 or o["fill_price"] is None:
            continue
        cps = (o["commission"] or 0.0) / sh
        sps = (o["slippage"] or 0.0) / sh
        if o["side"] == "BUY":
            lots[o["ticker"]].append(
                dict(
                    shares=sh,
                    price=o["fill_price"],
                    cps=cps,
                    sps=sps,
                    buy_id=o["id"],
                    day=_day(o["filled_at"]),
                    score=o["score"],
                )
            )
            buy_time[o["id"]] = _parse(o["filled_at"])
        else:  # SELL
            remaining = sh
            sell_dt = _parse(o["filled_at"])
            q = lots[o["ticker"]]
            while remaining > 1e-9 and q:
                lot = q[0]
                take = min(remaining, lot["shares"])
                buy_cost = take * lot["price"] + take * lot["cps"] + take * lot["sps"]
                sell_proc = take * o["fill_price"] - take * cps - take * sps
                pnl = sell_proc - buy_cost
                bt = buy_time.get(lot["buy_id"])
                hold = (sell_dt - bt).days if (sell_dt and bt) else 0
                rts.append(
                    dict(
                        ticker=o["ticker"],
                        buy_id=lot["buy_id"],
                        sell_id=o["id"],
                        shares=take,
                        buy_price=lot["price"],
                        sell_price=o["fill_price"],
                        pnl=pnl,
                        pnl_pct=(pnl / (take * lot["price"]) if lot["price"] else 0.0),
                        buy_score=lot["score"],
                        sell_score=o["score"],
                        sell_reason=o["reason"],
                        exit_kind=_exit_kind(o["reason"]),
                        buy_day=lot["day"],
                        sell_day=_day(o["filled_at"]),
                        hold_days=hold,
                        costs=(take * lot["cps"] + take * lot["sps"] + take * cps + take * sps),
                    )
                )
                lot["shares"] -= take
                remaining -= take
                if lot["shares"] <= 1e-9:
                    q.popleft()
    return rts


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _corr(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 4:
        return None
    xs = [a for a, _ in pairs]
    ys = [b for _, b in pairs]
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    cov = sum((a - mx) * (b - my) for a, b in pairs) / len(pairs)
    vx = sum((a - mx) ** 2 for a in xs) / len(xs)
    vy = sum((b - my) ** 2 for b in ys) / len(ys)
    den = (vx * vy) ** 0.5
    return cov / den if den else None


# ── paneles ───────────────────────────────────────────────────────────────────
def _realized_panel(rts: list[dict]) -> dict:
    if not rts:
        return dict(
            n_round_trips=0,
            total_pnl=0.0,
            n_wins=0,
            n_losses=0,
            win_rate=0.0,
            profit_factor=None,
            avg_win=0.0,
            avg_loss=0.0,
            payoff_ratio=None,
            expectancy=0.0,
            avg_hold_days=0.0,
            total_costs=0.0,
            excursion={
                "n": 0,
                "median_mae": None,
                "median_mfe": None,
                "avg_mae": None,
                "avg_mfe": None,
                "worst_mae": None,
                "best_mfe": None,
            },
            by_exit_kind={},
            per_ticker=[],
            worst_ticker=None,
            pnl_ex_worst=0.0,
            top_winners=[],
            top_losers=[],
            round_trips=[],
        )
    wins = [r for r in rts if r["pnl"] > 0]
    losses = [r for r in rts if r["pnl"] <= 0]
    gw = sum(r["pnl"] for r in wins)
    gl = -sum(r["pnl"] for r in losses)
    total = sum(r["pnl"] for r in rts)
    by_kind: dict[str, list] = defaultdict(lambda: [0, 0.0])
    for r in rts:
        by_kind[r["exit_kind"]][0] += 1
        by_kind[r["exit_kind"]][1] += r["pnl"]
    per_ticker_map: dict[str, list] = defaultdict(lambda: [0.0, 0])
    for r in rts:
        per_ticker_map[r["ticker"]][0] += r["pnl"]
        per_ticker_map[r["ticker"]][1] += 1
    per_ticker = sorted(
        ({"ticker": t, "pnl": p, "n": n} for t, (p, n) in per_ticker_map.items()),
        key=lambda x: x["pnl"],
    )
    worst = per_ticker[0] if per_ticker else None
    pnl_ex_worst = total - (worst["pnl"] if worst else 0.0)
    avg_win = gw / len(wins) if wins else 0.0
    avg_loss = -gl / len(losses) if losses else 0.0
    # payoff ratio = ganancia media / |pérdida media|. Para un sistema asimétrico
    # es el verdadero veredicto (un win-rate < 50% es viable si payoff > 1).
    payoff_ratio = (avg_win / abs(avg_loss)) if avg_loss else None

    # Distribución de MAE/MFE (excursión intradía). Alimenta la calibración de
    # stops/targets con TODOS los round-trips (no solo los 6 exits ATR de A1).
    maes = [r["mae"] for r in rts if r.get("mae") is not None]
    mfes = [r["mfe"] for r in rts if r.get("mfe") is not None]
    excursion = {
        "n": len(maes),
        "median_mae": _median(maes) if maes else None,
        "median_mfe": _median(mfes) if mfes else None,
        "avg_mae": (sum(maes) / len(maes)) if maes else None,
        "avg_mfe": (sum(mfes) / len(mfes)) if mfes else None,
        "worst_mae": min(maes) if maes else None,
        "best_mfe": max(mfes) if mfes else None,
    }

    def _slim(r: dict) -> dict:
        d = {
            k: r[k]
            for k in (
                "ticker",
                "pnl",
                "pnl_pct",
                "hold_days",
                "exit_kind",
                "sell_reason",
                "buy_day",
                "sell_day",
            )
        }
        d["mae"] = r.get("mae")
        d["mfe"] = r.get("mfe")
        return d

    return dict(
        n_round_trips=len(rts),
        total_pnl=total,
        n_wins=len(wins),
        n_losses=len(losses),
        win_rate=len(wins) / len(rts),
        profit_factor=(gw / gl if gl else None),
        avg_win=avg_win,
        avg_loss=avg_loss,
        payoff_ratio=payoff_ratio,
        expectancy=total / len(rts),
        avg_hold_days=sum(r["hold_days"] for r in rts) / len(rts),
        total_costs=sum(r["costs"] for r in rts),
        excursion=excursion,
        by_exit_kind={
            k: {"n": v[0], "pnl": v[1], "avg": v[1] / v[0] if v[0] else 0.0} for k, v in by_kind.items()
        },
        per_ticker=per_ticker,
        worst_ticker=worst,
        pnl_ex_worst=pnl_ex_worst,
        top_winners=[_slim(r) for r in sorted(rts, key=lambda x: -x["pnl"])[:5]],
        top_losers=[_slim(r) for r in sorted(rts, key=lambda x: x["pnl"])[:5]],
        round_trips=[_slim(r) for r in rts],
    )


def _timing_panel(con: sqlite3.Connection, orders: list[dict]) -> dict:
    series_cache: dict[str, list | None] = {}

    def series(t: str):
        if t not in series_cache:
            series_cache[t] = load_close_series(con, t)
        return series_cache[t]

    f5: list[float] = []
    f20: list[float] = []
    pairs: list[tuple[float, float]] = []
    per_buy: list[dict] = []
    for o in orders:
        if o["side"] != "BUY":
            continue
        day = _day(o["filled_at"])
        if not day:
            continue
        s = series(o["ticker"])
        r5 = forward_return(s, day, FWD_SHORT)
        r20 = forward_return(s, day, FWD_LONG)
        per_buy.append({"ticker": o["ticker"], "score": o["score"], "fwd5": r5, "fwd20": r20, "day": day})
        if r5 is not None:
            f5.append(r5)
            if o["score"] is not None:
                pairs.append((float(o["score"]), r5))
        if r20 is not None:
            f20.append(r20)
    g5 = [x for x in f5 if x > 0]
    g20 = [x for x in f20 if x > 0]
    return dict(
        n5=len(f5),
        good5=len(g5),
        good5_pct=(len(g5) / len(f5) if f5 else 0.0),
        mean5=(sum(f5) / len(f5) if f5 else 0.0),
        median5=_median(f5),
        n20=len(f20),
        good20=len(g20),
        good20_pct=(len(g20) / len(f20) if f20 else 0.0),
        mean20=(sum(f20) / len(f20) if f20 else 0.0),
        median20=_median(f20),
        score_fwd5_corr=_corr(pairs),
        score_fwd5_n=len(pairs),
        per_buy=per_buy,
    )


def _sell_calibration_panel(con: sqlite3.Connection, orders: list[dict]) -> dict:
    series_cache: dict[str, list | None] = {}
    regret: list[float] = []
    for o in orders:
        if o["side"] != "SELL":
            continue
        if not (o["reason"] or "").startswith("analyze SELL"):
            continue
        t = o["ticker"]
        if t not in series_cache:
            series_cache[t] = load_close_series(con, t)
        dia = _day(o["filled_at"])
        if dia is None:  # sin fecha de fill no hay ventana forward
            continue
        r5 = forward_return(series_cache[t], dia, FWD_SHORT)
        if r5 is not None:
            regret.append(r5)
    up = [r for r in regret if r > 0]
    return dict(
        n=len(regret),
        up_after=len(up),
        up_after_pct=(len(up) / len(regret) if regret else 0.0),
        mean_fwd5=(sum(regret) / len(regret) if regret else 0.0),
    )


def _sell_timing_panel(con: sqlite3.Connection, orders: list[dict]) -> dict:
    """Calidad de la SALIDA por forward-return post-SELL (mirror de _timing_panel).

    Convención **invertida** respecto de las compras: una venta es BUENA si el
    precio NO subió después (evitó una caída / preservó ganancia → ``fwd5 ≤ 0``)
    y MALA si siguió subiendo (vendiste temprano → ``fwd5 > 0``, "regret").
    Recorre TODAS las SELL filled (no solo signal_sell) y segmenta por exit_kind.
    """
    series_cache: dict[str, list | None] = {}

    def series(t: str):
        if t not in series_cache:
            series_cache[t] = load_close_series(con, t)
        return series_cache[t]

    f5: list[float] = []
    f20: list[float] = []
    pairs: list[tuple[float, float]] = []
    per_sell: list[dict] = []
    by_kind: dict[str, list] = defaultdict(lambda: [0, 0, 0.0])  # kind -> [n, n_good, sum_fwd5]
    for o in orders:
        if o["side"] != "SELL":
            continue
        day = _day(o["filled_at"])
        if not day:
            continue
        r5 = forward_return(series(o["ticker"]), day, FWD_SHORT)
        r20 = forward_return(series(o["ticker"]), day, FWD_LONG)
        kind = _exit_kind(o["reason"])
        per_sell.append(
            {
                "ticker": o["ticker"],
                "score": o["score"],
                "exit_kind": kind,
                "fwd5": r5,
                "fwd20": r20,
                "day": day,
            }
        )
        if r5 is not None:
            f5.append(r5)
            by_kind[kind][0] += 1
            if r5 <= 0:
                by_kind[kind][1] += 1
            by_kind[kind][2] += r5
            if o["score"] is not None:
                pairs.append((float(o["score"]), r5))
        if r20 is not None:
            f20.append(r20)
    g5 = [x for x in f5 if x <= 0]  # venta buena = el precio no subió después
    g20 = [x for x in f20 if x <= 0]
    with_f5 = [p for p in per_sell if p["fwd5"] is not None]
    return dict(
        n5=len(f5),
        good5=len(g5),
        good5_pct=(len(g5) / len(f5) if f5 else 0.0),
        mean5=(sum(f5) / len(f5) if f5 else 0.0),
        median5=_median(f5),
        n20=len(f20),
        good20=len(g20),
        good20_pct=(len(g20) / len(f20) if f20 else 0.0),
        mean20=(sum(f20) / len(f20) if f20 else 0.0),
        median20=_median(f20),
        by_exit_kind={
            k: {
                "n": v[0],
                "good_pct": (v[1] / v[0] if v[0] else 0.0),
                "mean_fwd5": (v[2] / v[0] if v[0] else 0.0),
            }
            for k, v in by_kind.items()
        },
        sell_score_fwd5_corr=_corr(pairs),
        sell_score_fwd5_n=len(pairs),
        # mejores ventas = más caída evitada (fwd5 más negativo); peores = regret.
        top_avoided=sorted(with_f5, key=lambda x: x["fwd5"])[:5],
        top_regret=sorted(with_f5, key=lambda x: -x["fwd5"])[:5],
        per_sell=per_sell,
    )


def _churn_panel(orders: list[dict]) -> dict:
    ev: dict[str, list] = defaultdict(list)
    for o in orders:
        dt = _parse(o["filled_at"])
        if dt:
            ev[o["ticker"]].append((dt, o["side"], o["id"]))
    events: list[dict] = []
    for t, evs in ev.items():
        evs.sort()
        for i in range(len(evs) - 1):
            if evs[i][1] == "SELL" and evs[i + 1][1] == "BUY":
                gap = (evs[i + 1][0] - evs[i][0]).days
                if gap <= CHURN_DAYS:
                    events.append(
                        {"ticker": t, "gap_days": gap, "sell_id": evs[i][2], "buy_id": evs[i + 1][2]}
                    )
    events.sort(key=lambda x: x["gap_days"])
    return dict(n_le7d=len(events), events=events)


def _timeline(rts: list[dict]) -> list[dict]:
    """P/L realizado acumulado + win-rate móvil, por fecha de venta (cronológico)."""
    ordered = sorted(rts, key=lambda r: (r["sell_day"] or "", r["sell_id"]))
    cum = 0.0
    wins = 0
    out: list[dict] = []
    for i, r in enumerate(ordered, start=1):
        cum += r["pnl"]
        if r["pnl"] > 0:
            wins += 1
        out.append({"day": r["sell_day"], "cum_pnl": cum, "trades": i, "rolling_win_rate": wins / i})
    return out


def _open_positions(con: sqlite3.Connection, account_id: int) -> list[dict]:
    rows = con.execute(
        "SELECT ticker,shares,avg_cost FROM paper_positions WHERE account_id=? AND shares>0 ORDER BY ticker",
        (account_id,),
    ).fetchall()
    out = []
    for tkr, sh, ac in rows:
        s = load_close_series(con, tkr)
        mark = s[-1][1] if s else ac
        mtm = (mark / ac - 1.0) if ac else 0.0
        out.append({"ticker": tkr, "shares": sh, "avg_cost": ac, "mark": mark, "mtm_pct": mtm})
    return out


def _friction_panel(con: sqlite3.Connection, account_id: int, realized: dict) -> dict:
    """Fricción total pagada (comisión + slippage) y su peso sobre el P/L bruto.

    Suma ``commission_paid + slippage_cost`` sobre **todas** las órdenes filled
    (BUY y SELL, incluidas las compras de posiciones aún abiertas) — el dato ya
    vive en ``paper_orders`` pero nadie lo agregaba. Distinto de
    ``realized.total_costs``, que solo cuenta los costos de los round-trips ya
    cerrados (BUY emparejado con su SELL).

    ``pct_of_gross`` = fricción / P/L **bruto** realizado (neto + costos de los
    round-trips), para ver cuánto del margen bruto se lo comió el costo de operar.
    ``None`` si el bruto no es positivo (ratio sin sentido).
    """
    row = con.execute(
        "SELECT COALESCE(SUM(commission_paid),0), COALESCE(SUM(slippage_cost),0), COUNT(*) "
        "FROM paper_orders WHERE account_id=? AND status='filled'",
        (account_id,),
    ).fetchone()
    commission = float(row[0] or 0.0)
    slippage = float(row[1] or 0.0)
    n_orders = int(row[2] or 0)
    friction = commission + slippage
    gross_pnl = realized["total_pnl"] + realized["total_costs"]
    pct_of_gross = (friction / gross_pnl) if gross_pnl > 0 else None
    return {
        "commission": commission,
        "slippage": slippage,
        "friction": friction,
        "n_orders": n_orders,
        "gross_pnl": gross_pnl,
        "pct_of_gross": pct_of_gross,
    }


def cached_sector(con: sqlite3.Connection, ticker: str) -> str | None:
    """Sector cacheado de un ticker (``company_info_cache``), o ``None``.

    Read-only y fail-open: si la tabla no existe (DB vieja/sintética) o el sector
    es NULL/"N/A", devuelve ``None`` → el panel lo agrupa como "Sin dato". La
    población del cache la hace ``data.yahoo_finance.get_company_info`` (con red),
    fuera de este módulo.
    """
    try:
        row = con.execute(
            "SELECT sector FROM company_info_cache WHERE ticker=? ORDER BY fetched_at DESC LIMIT 1",
            (ticker.upper(),),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row or not row[0] or str(row[0]).strip() in ("", "N/A"):
        return None
    return str(row[0])


def _concentration_panel(con: sqlite3.Connection, account_id: int) -> dict:
    """Concentración del book vivo (V2): pesos, sector, correlación, P/L sin mejor/peor.

    Read-only: arma las posiciones abiertas con su market value (marcado al último
    close cacheado), la correlación media desde el cache histórico y el sector
    desde ``company_info_cache``; delega el cálculo puro en
    ``analysis.portfolio_risk.book_concentration``. Fail-open ante datos faltantes.
    """
    from analysis.portfolio_risk import book_concentration, returns_frame

    rows = con.execute(
        "SELECT ticker, shares, avg_cost FROM paper_positions "
        "WHERE account_id=? AND shares>0 ORDER BY ticker",
        (account_id,),
    ).fetchall()
    positions: list[dict] = []
    for tkr, sh, ac in rows:
        s = load_close_series(con, tkr)
        mark = s[-1][1] if s else (ac or 0.0)
        shares = float(sh or 0.0)
        avg = float(ac or 0.0)
        positions.append(
            {
                "ticker": tkr,
                "market_value": shares * float(mark),
                "unrealized_pnl": (float(mark) - avg) * shares if avg > 0 else 0.0,
            }
        )

    # Frame de retornos desde el cache (para la correlación media). El history
    # provider arma un DataFrame ['Close'] por ticker a partir de load_close_series.
    def _hp(t: str):
        s = load_close_series(con, t)
        if not s:
            return None
        import pandas as pd

        return pd.DataFrame({"Close": [c for _, c in s]}, index=[d for d, _ in s])

    rf = None
    tickers = [p["ticker"] for p in positions]
    if len(tickers) >= 2:
        try:
            rf = returns_frame(tickers, _hp)
        except Exception:
            rf = None

    return book_concentration(positions, returns=rf, sector_of=lambda t: cached_sector(con, t))


def _expired_buys(con: sqlite3.Connection, account_id: int) -> dict:
    rows = con.execute(
        "SELECT ticker,COUNT(*) FROM paper_orders "
        "WHERE account_id=? AND side='BUY' AND status='expired' GROUP BY ticker",
        (account_id,),
    ).fetchall()
    by = {t: n for t, n in rows}
    return {"n": sum(by.values()), "by_ticker": by}


def _close_on_or_after(series: list[tuple[str, float]], day: str) -> float | None:
    """Primer close en o después de ``day`` (serie ascendente)."""
    for d, c in series:
        if d >= day:
            return c
    return None


def _close_on_or_before(series: list[tuple[str, float]], day: str) -> float | None:
    """Último close en o antes de ``day`` (serie ascendente)."""
    out: float | None = None
    for d, c in series:
        if d <= day:
            out = c
        else:
            break
    return out


def _ancla_de_la_cuenta(con: sqlite3.Connection, account_id: int, rows: list) -> tuple[float, str]:
    """``(equity base, de dónde salió)`` para el retorno de la cuenta (tarea 223).

    **El primer snapshot NO es el capital: es el capital menos la primera tanda de
    costos.** ``record_equity_snapshot`` corre al FINAL de ``run_scan``, después de los
    fills, así que ``rows[0]`` ya trae descontados comisión y slippage de la entrada del
    día 1 — en la cuenta 2, **$23,01 exactos** (50.000,00 − 49.976,99, y la suma de
    ``commission_paid + slippage_cost`` de los diez fills del 2026-06-20 da ese número al
    centavo). Anclar ahí hacía que **el costo de entrada no contara como pérdida**,
    mientras SPY arrancaba sin pagar nada. El sesgo es chico (0,047pp hoy) pero
    **sistemático y siempre a favor de la cuenta**: no depende de cuánto fue el costo,
    sino de que exista.

    Por eso la base es ``initial_capital``, que es la plata que de verdad se puso. Que
    eso sea también *«la equity justo antes del primer scan»* no es una suposición
    cómoda: los snapshots **sólo** los escribe ``run_scan``, y ``acct.cash`` **sólo** lo
    mueven los fills (``engine.py`` es el único que lo toca, en dos líneas) — no hay
    depósitos ni retiros en ningún lado del proyecto.

    **El caso degradado se declara, no se esconde.** Una DB sintética sin
    ``paper_accounts`` cae en ``rows[0]``, que es el comportamiento viejo; devolverlo en
    silencio sería dejar el sesgo vivo sin que nada lo diga, así que sale rotulado.
    """
    try:
        fila = con.execute("SELECT initial_capital FROM paper_accounts WHERE id=?", (account_id,)).fetchone()
    except sqlite3.OperationalError:
        fila = None
    if fila and fila[0] is not None and float(fila[0]) > 0:
        return float(fila[0]), "initial_capital"
    return float(rows[0][1] or 0.0), "primer_snapshot"


def _ancla_de_spy(series: list[tuple[str, float]], start_day: str) -> tuple[float | None, str]:
    """``(close base de SPY, de dónde salió)`` para el retorno del benchmark (tarea 223).

    **El ancla va en el close que la equity de la cuenta tiene puesto, que es el
    PREVIO.** El panel usaba ``_close_on_or_after`` en el inicio y ``_close_on_or_before``
    en el final — la asimetría estaba escrita ahí mismo. Cuando el primer snapshot cae en
    una rueda, las dos dan lo mismo y no se nota; cuando cae **fuera** de una rueda, no:
    el primer snapshot de la cuenta 2 es el **sábado 2026-06-20** (el viernes 19 fue
    feriado), así que su equity está marcada con los closes del **18** y SPY se anclaba en
    el **22**. Medido: vale **+0,33pp**, siete veces el sesgo de fricción que esta misma
    tarea arregla, y en la dirección contraria.

    ``_close_on_or_after`` queda de fallback para el caso en que la serie **empiece
    después** del primer snapshot (la ventana del cache es rodante). Eso no es una
    equivalencia sino un desvío distinto —SPY midiendo una ventana más corta que la
    cuenta, el espejo del ``stale`` de la tarea 22, que hoy nadie guarda— así que sale
    rotulado y está anotado como tarea **225**.
    """
    p0 = _close_on_or_before(series, start_day)
    if p0 is not None:
        return p0, "close_previo"
    return _close_on_or_after(series, start_day), "primera_rueda"


def retorno_de_spy(
    series: list[tuple[str, float]] | None, start_day: str | None, end_day: str | None
) -> tuple[float | None, str | None]:
    """``(retorno de SPY en [start_day, end_day], de dónde salió el ancla)``.

    **La aritmética del benchmark, en UN solo lugar (tarea 224).** Había dos copias:
    ésta y la de ``scripts/dashboard_data._monthly_perf``, que además usaba **otra**
    ventana — todas las ruedas del mes calendario en vez de la ventana de la cuenta.
    Que hubiera dos es lo que permitió que la 22, la 221 y la 223 arreglaran una y
    dejaran la otra intacta; es el mismo desenlace que ya tenía documentado el lector
    de series (``dashboard_data._load_close_series``: *«tener dos copias es lo que
    permitió que arreglar una no alcanzara a la otra»*), repetido un nivel más arriba.

    El inicio se ancla con ``_ancla_de_spy`` y el final con ``_close_on_or_before``:
    las dos puntas, con la misma regla. Devuelve ``(None, None)`` si falta la serie o
    alguna de las dos fechas, y ``(None, anclaje)`` si la ventana no da un retorno
    computable — el llamador decide si eso apaga el número o sólo lo declara.
    """
    if not series or start_day is None or end_day is None:
        return None, None
    ordenada = sorted(series)
    p0, anclaje = _ancla_de_spy(ordenada, start_day)
    p1 = _close_on_or_before(ordenada, end_day)
    if not p0 or not p1 or p0 <= 0:
        return None, anclaje
    return p1 / p0 - 1.0, anclaje


def ruedas_en_ventana(
    series: list[tuple[str, float]] | None, start_day: str | None, end_day: str | None
) -> int:
    """Cuántas ruedas de la serie caen dentro de ``[start_day, end_day]`` (tarea 224).

    Se publica al lado de los días con snapshot de la cuenta para que un período con
    **cobertura incompleta** se pueda ver. La cuenta 2 no tiene scans entre el
    2026-07-24 y el 2026-08-09, así que julio cubre 18 de 22 ruedas y agosto 15 de 21
    — y hasta ahora nada lo decía.
    """
    if not series or start_day is None or end_day is None:
        return 0
    return sum(1 for d, _ in series if start_day <= d <= end_day)


# Fecha centinela de `data/yahoo_finance._SIN_DIVIDENDOS`: marca "este ticker ya se
# chequeó y no paga". Se duplica el literal a propósito y NO se importa: `analysis/` no
# depende de `data/yahoo_finance` (que arrastra yfinance, red y el cache entero) sólo
# para leer una tabla. Un test fija que los dos literales coincidan, que es lo que evita
# que la duplicación derive — la misma forma con que la 71 resolvió los literales de
# reproducción.
_SIN_DIVIDENDOS = "0000-00-00"


def _dividendos_devengados(
    con: sqlite3.Connection, account_id: int, start_day: str, end_day: str
) -> tuple[float, list[str]]:
    """``(dólares devengados, tickers sin calendario)`` en ``[start_day, end_day]``.

    **Qué mide y por qué existe (tareas 220 → 221).** El harness corre sobre barras
    bajadas con ``auto_adjust=True``, o sea total-return: cobra dividendos en el
    precio. ``paper_trading/`` no los menciona en ninguna línea, así que la cuenta
    pasa por el ex-date, ve caer el precio y no recibe el efectivo. Este número es
    exactamente ese efectivo, y sirve para que el VS SPY compare total contra total
    en vez de restar el retorno de PRECIO de la cuenta contra un SPY TOTAL-RETURN.

    **La convención de quién cobra: hay que tener la acción ANTES del ex-date.** Un
    fill del mismo día del ex-date no cobra, así que la posición se evalúa con los
    fills estrictamente anteriores (``filled_at`` < ``ex_date``). Es la convención con
    la que la T220 midió los $322,77, y este cálculo **reproduce esa tabla ticker por
    ticker** — verificado antes de escribirlo, sobre los nueve tickers publicados.

    **El segundo elemento no es decoración.** Un ticker que la cuenta tuvo y del que
    no hay ninguna fila de calendario **no devenga cero: no se sabe**. Confundir las
    dos cosas haría que el VS SPY volviera a estar sesgado en silencio, que es el
    defecto que esta tarea arregla. Por eso se devuelven aparte y el panel lo declara.
    Un ticker que no paga SÍ devenga cero, y se distingue por la fila centinela.
    """
    try:
        fills = con.execute(
            "SELECT ticker, side, fill_shares, filled_at FROM paper_orders "
            "WHERE account_id=? AND status='filled' AND fill_shares IS NOT NULL "
            "ORDER BY filled_at ASC",
            (account_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return 0.0, []
    if not fills:
        return 0.0, []

    por_ticker: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for ticker, side, shares, filled_at in fills:
        dia = _day(filled_at)
        if dia is None or not shares:
            continue
        signo = 1.0 if str(side).upper() == "BUY" else -1.0
        por_ticker[str(ticker).upper()].append((dia, signo * float(shares)))

    # tarea 222: lo que el MOTOR ya acreditó a la caja está en la equity, así que
    # sumarlo acá lo contaría DOS veces y el VS SPY saldría inflado — en silencio y
    # hacia arriba, que es la peor dirección. Se descubrió escribiendo el docstring del
    # panel al cerrar la 222, no corriendo nada: el cableado del motor y este cálculo son
    # dos consumidores del MISMO calendario, y hasta la 222 uno de los dos no existía.
    try:
        ya_en_caja = {
            (str(t).upper(), ex)
            for t, ex in con.execute(
                "SELECT ticker, ex_date FROM paper_dividend_credits WHERE account_id=?",
                (account_id,),
            ).fetchall()
        }
    except sqlite3.OperationalError:
        # DB anterior a la migración 0014: el motor no acreditaba nada, así que no hay
        # nada que descontar y el devengado completo es el correcto.
        ya_en_caja = set()

    total = 0.0
    sin_calendario: list[str] = []
    for ticker, eventos in sorted(por_ticker.items()):
        try:
            filas = con.execute(
                "SELECT ex_date, amount FROM dividend_calendar_cache WHERE ticker=? ORDER BY ex_date ASC",
                (ticker,),
            ).fetchall()
        except sqlite3.OperationalError:
            # La tabla no existe (DB sintética, o anterior a la migración 0013). No hay
            # calendario para NINGÚN ticker, así que todos quedan sin declarar.
            return 0.0, sorted(por_ticker)
        if not filas:
            sin_calendario.append(ticker)
            continue
        for ex_date, monto in filas:
            if ex_date == _SIN_DIVIDENDOS:
                # La fila centinela marca "chequeado, no paga" para que el TTL lo tape.
                # **Es redundante y va dicho:** probando por mutación, sacarle este
                # `continue` NO pone nada en rojo, porque `"0000-00-00"` ordena antes que
                # cualquier fecha ISO y el filtro de ventana de abajo ya lo descarta. Se
                # deja por legibilidad —la fila necesita nombre donde se lee—, pero lo que
                # de verdad lo sostiene es el rango, y un comentario que dijera lo
                # contrario dirigiría mal a quien venga a tocar el filtro. Los dos hechos
                # están fijados por tests (el literal y su orden).
                continue
            if not (start_day <= ex_date <= end_day):
                continue
            if (ticker, ex_date) in ya_en_caja:
                continue  # ya lo cobró el motor (tarea 222): está en la equity
            # Shares en cartera ANTES del ex-date. `< ex_date` y no `<=`: comprar el
            # día del ex-date no cobra.
            shares = sum(q for dia, q in eventos if dia < ex_date)
            if shares > 0:
                total += shares * float(monto)

    return total, sin_calendario


def _benchmark_panel(con: sqlite3.Connection, account_id: int) -> dict:
    """Retorno de la cuenta vs SPY sobre la MISMA ventana (V1).

    Toma el primer y último ``paper_equity_snapshots`` de la cuenta como ventana
    y compara el retorno de equity contra el retorno de SPY entre esas fechas
    (cache diario, ``load_close_series``). Permite, por primera vez, separar
    sistema de mercado: ``vs_spy = account_return − spy_return`` (alpha del período).

    **Compara TOTAL contra TOTAL (tarea 221), y antes no.** El cache se baja con
    ``auto_adjust=True``, así que la serie de SPY es total-return: trae sus dividendos
    reinvertidos. La equity de la cuenta, en cambio, es sólo precio de las posiciones.
    Restar una de la otra es restar peras de manzanas, y en la
    cuenta 2 valía **0,65pp sobre 3 meses** (medido el 2026-09-21: −1,05pp contra −0,40pp
    comparando honesto), o sea que el **62% de la brecha contra SPY era un artefacto de
    medición**. Ahora el devengado de la cuenta se suma a su retorno
    (``account_return_total``) y el ``vs_spy`` sale de ahí. Los dos números de esa medición
    quedaron viejos al día siguiente, con la 223: son de antes de arreglar los anclajes.

    **Desde la 222 el motor acredita el dividendo a la caja**, así que lo devengado que se
    suma acá es cada vez menos: lo que el motor ya cobró entra en la equity por sí solo y
    ``_dividendos_devengados`` sólo aporta los ex-dates **anteriores** al cableado (la 222
    corre sólo hacia adelante y no backfillea). Los dos caminos usan la **misma**
    convención de quién cobra —tener la acción antes del ex-date— y un test lo fija.

    **La dirección del sesgo importa para leer el caso degradado:** el dividendo sólo
    puede sumar, así que si el calendario está incompleto el ``vs_spy`` publicado es un
    **piso** — el real es ése o mejor. Por eso un calendario parcial no apaga el número
    (apagarlo sería la regresión que la 218 acaba de arreglar): lo declara en
    ``dividendos_completos`` y ``dividendos_faltantes``.

    **Y los dos lados se anclan IGUAL (tarea 223), que antes tampoco.** La cuenta
    arrancaba en ``rows[0]`` —o sea *después* de pagar la fricción del primer scan— y SPY
    en la rueda siguiente al primer snapshot, sin pagar nada y sobre otra fecha. Son dos
    asimetrías distintas, no una: valen **−0,047pp** y **+0,33pp** sobre la cuenta 2, en
    direcciones opuestas, así que arreglar sólo la que decía el enunciado habría dejado la
    otra —la grande— intacta. El detalle de cada una vive en ``_ancla_de_la_cuenta`` y
    ``_ancla_de_spy``, y cuál se usó sale en ``base_anclaje`` / ``spy_anclaje``.

    **SPY entra sin fricción a propósito, y eso es lo que hace legible al número.** El
    benchmark es el índice: *«comprar SPY y no hacer nada»* rinde el retorno del índice, y
    todo lo que la cuenta paga por operar —empezando por la entrada del día 1— tiene que
    verse como pérdida contra él. Darle a SPY una comisión de entrada taparía justo el
    costo que esta tarea destapa.

    Best-effort/display-only: ``available=False`` si faltan snapshots (<2) o el
    cache de SPY. No lanza si la tabla de snapshots no existe (DB sintética).
    """
    empty = {
        "available": False,
        "ticker": BENCHMARK_TICKER,
        "start_day": None,
        "end_day": None,
        "account_return": None,
        "account_dividends": None,
        "account_return_total": None,
        "dividendos_completos": False,
        "dividendos_faltantes": [],
        "spy_return": None,
        "vs_spy": None,
        "stale": False,
        "spy_end_day": None,
        # Dónde EMPIEZA la serie (tarea 225). El espejo de `spy_end_day`: sin esto, el
        # caso `serie_corta` diría que no hay número y no con qué ventana se quedó.
        "spy_start_day": None,
        # De dónde salió cada ancla (tarea 223). No los pinta nadie: están para que el
        # caso degradado —DB sin `paper_accounts`, serie que empieza después de la
        # cuenta— se pueda ver en vez de quedar como un número sin historia.
        "base_equity": None,
        "base_anclaje": None,
        "spy_anclaje": None,
        # Por que NO hay numero (tarea 218). `stale` ya separaba "dato viejo", pero
        # "sin serie" y "faltan snapshots" se veian igual — y la UI los rotulaba a los
        # dos como "sin cache de SPY todavia", que ademas afirmaba un "todavia" falso:
        # el lector estaba roto, no esperando datos.
        "motivo": "sin_snapshots",
    }
    try:
        rows = con.execute(
            "SELECT snapshot_at, total_equity FROM paper_equity_snapshots "
            "WHERE account_id=? ORDER BY snapshot_at ASC",
            (account_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return empty
    if len(rows) < 2:
        return empty
    start_day = _day(rows[0][0])
    end_day = _day(rows[-1][0])
    # tarea 223: la base es el capital ANTES de la fricción del primer scan, no el
    # primer snapshot — que ya la pagó. Ver `_ancla_de_la_cuenta`.
    start_eq, base_anclaje = _ancla_de_la_cuenta(con, account_id, rows)
    end_eq = float(rows[-1][1] or 0.0)
    account_return = (end_eq / start_eq - 1.0) if start_eq > 0 else None
    anclas = {
        "base_equity": start_eq if start_eq > 0 else None,
        "base_anclaje": base_anclaje,
    }
    spy = load_close_series(con, BENCHMARK_TICKER)
    if not spy or start_day is None or end_day is None:
        return {
            **empty,
            **anclas,
            "start_day": start_day,
            "end_day": end_day,
            "account_return": account_return,
            "motivo": "sin_serie",
        }
    spy = sorted(spy)
    spy_end_day = spy[-1][0] if spy else None
    spy_start_day = spy[0][0] if spy else None
    # tarea 22: si el cache de SPY quedó > K días hábiles atrás del último
    # snapshot, comparar la cuenta (ventana completa) contra un SPY recortado
    # sesga el vs_spy en silencio → se marca stale y NO se computa el número.
    if benchmark_stale_bdays(spy_end_day, end_day) > BENCHMARK_STALE_BDAYS:
        return {
            **empty,
            **anclas,
            "start_day": start_day,
            "end_day": end_day,
            "account_return": account_return,
            "stale": True,
            "spy_end_day": spy_end_day,
            "spy_start_day": spy_start_day,
            "motivo": "stale",
        }
    # tarea 225: **el espejo del de arriba, que faltaba.** Si la serie EMPIEZA después
    # del primer snapshot, SPY mide una ventana más corta que la cuenta por el otro
    # extremo, y el sesgo es igual de silencioso. Pasa solo: el cache es una ventana
    # **rodante** que avanza ~1 rueda por día mientras el arranque de la cuenta queda
    # fijo, así que el colchón se achica monótonamente (al 2026-09-24 la cuenta 2 tiene
    # 453 días hábiles y la 1, 413).
    #
    # **Se apaga en vez de publicarse, igual que `stale`, y el motivo es el signo.** El
    # dividendo incompleto se puede publicar como *piso* porque sólo puede sumar; acá el
    # tramo que falta puede haber subido o bajado, así que no hay dirección que declarar
    # y un número sin dirección no es un piso, es una adivinanza.
    #
    # **Reusa `BENCHMARK_STALE_BDAYS` y no un umbral propio, y eso va dicho:** es la
    # misma pregunta espejada —cuánto de la ventana le falta a SPY antes de que la
    # comparación deje de valer— y **no hay población contra la cual calibrar un segundo
    # umbral** (0 de 2 cuentas lo tocan hoy). Inventar una constante nueva sin datos
    # sería peor que reusar una ya declarada.
    if benchmark_start_gap_bdays(spy_start_day, start_day) > BENCHMARK_STALE_BDAYS:
        return {
            **empty,
            **anclas,
            "start_day": start_day,
            "end_day": end_day,
            "account_return": account_return,
            "spy_start_day": spy_start_day,
            "spy_end_day": spy_end_day,
            "motivo": "serie_corta",
        }
    # tarea 223: el inicio se ancla con la MISMA regla que el final (`_close_on_or_before`),
    # que es el close con el que está marcada la equity del primer snapshot. Desde la 224
    # la aritmética entera vive en `retorno_de_spy`, compartida con el mensual del
    # dashboard — tener dos copias fue lo que dejó a una sin los arreglos de la otra.
    spy_return, spy_anclaje = retorno_de_spy(spy, start_day, end_day)

    # Total contra total (tarea 221): la equity de la cuenta es sólo precio, así que se
    # le suma el efectivo que devengó y no cobró. SPY ya viene total-return del cache.
    dividendos, faltantes = _dividendos_devengados(con, account_id, start_day, end_day)
    account_return_total = ((end_eq + dividendos) / start_eq - 1.0) if start_eq > 0 else None
    vs_spy = (
        (account_return_total - spy_return)
        if (account_return_total is not None and spy_return is not None)
        else None
    )
    return {
        "available": spy_return is not None,
        "ticker": BENCHMARK_TICKER,
        "start_day": start_day,
        "end_day": end_day,
        # `account_return` sigue siendo el de PRECIO —lo que la cuenta hizo en equity— y
        # el de la comparación es el total. Los dos sobre la misma base: el capital, que
        # desde la 223 ya no es el primer snapshot (ver `_ancla_de_la_cuenta`).
        "account_return": account_return,
        "account_dividends": dividendos,
        "account_return_total": account_return_total,
        "dividendos_completos": not faltantes,
        "dividendos_faltantes": faltantes,
        "spy_return": spy_return,
        "vs_spy": vs_spy,
        "stale": False,
        "spy_end_day": spy_end_day,
        "spy_start_day": spy_start_day,
        **anclas,
        "spy_anclaje": spy_anclaje,
        "motivo": None if spy_return is not None else "sin_serie",
    }


# ── entrypoint ────────────────────────────────────────────────────────────────
def build_metrics(
    con: sqlite3.Connection, account_id: int = 1, now: datetime | None = None
) -> dict[str, Any]:
    """Calcula el payload completo de métricas para ``account_id``."""
    orders = _filled_orders(con, account_id)
    rts = pair_round_trips(orders)
    _annotate_excursions(con, rts)  # agrega mae/mfe a cada round-trip (V1)
    realized = _realized_panel(rts)
    return {
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "account_id": account_id,
        "realized": realized,
        "timing": _timing_panel(con, orders),
        "sell_calibration": _sell_calibration_panel(con, orders),
        "sell_timing": _sell_timing_panel(con, orders),
        "friction": _friction_panel(con, account_id, realized),
        "benchmark": _benchmark_panel(con, account_id),
        "concentration": _concentration_panel(con, account_id),
        "churn": _churn_panel(orders),
        "timeline": _timeline(rts),
        "open_positions": _open_positions(con, account_id),
        "expired_buys": _expired_buys(con, account_id),
        # Tarea 194 — display-only: no alimenta ninguna decisión.
        "performance_score": performance_score_panel(rts, orders, today=(now or datetime.now()).date()),
    }


def build_metrics_from_path(db_path: str | Path, account_id: int = 1) -> dict[str, Any]:
    """Conveniencia: abre la DB en modo read-only y calcula las métricas."""
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        return build_metrics(con, account_id)
    finally:
        con.close()


def commit_markers(repo_dir: str | Path, *, limit: int = 60) -> list[dict]:
    """Fechas + subject de los commits que tocan la *lógica de trading*.

    Filtra el ``git log`` por keywords de comportamiento. Devuelve ``[]`` si git
    no está disponible o el dir no es un repo (best-effort, nunca lanza).
    """
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(repo_dir),
                "log",
                f"-{limit}",
                "--date=format:%Y-%m-%d",
                "--pretty=format:%ad|%s",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    markers: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for line in out.stdout.splitlines():
        if "|" not in line:
            continue
        day, subject = line.split("|", 1)
        low = subject.lower()
        if low.startswith(_INFRA_COMMIT_PREFIXES):
            continue
        if not any(k in low for k in _BEHAVIOR_COMMIT_KEYWORDS):
            continue
        key = (day, subject[:40])
        if key in seen:
            continue
        seen.add(key)
        markers.append({"day": day.strip(), "subject": subject.strip()})
    return markers


# (módulo puro: sin efectos secundarios al importar)
