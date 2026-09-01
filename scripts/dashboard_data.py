"""
Dashboard data extractor — Sprint 1, pieza 0.

Reads ``finanzias.db`` and prints a single JSON object to stdout with the
payload the live-dashboard HTML artifact needs to render. Designed to be
invoked from inside the artifact via ``window.cowork.callMcpTool``
("mcp__workspace__bash") so the dashboard sees fresh data on every Reload.

Default account: Sim Principal (id=1). Override with ``--account <id>``.

Output schema (top-level keys)::

    {
      "generated_at": "2026-05-26T22:30:00Z",
      "account": {"id": 1, "name": "...", "initial_capital": 50000.0, ...},
      "equity_curve": [{"t": "ISO", "equity": float, "cash": float}, ...],
      "kpis": {
        "period_return": 0.0468, "sharpe": 2.16, "max_dd": -0.0595,
        "win_rate": 0.60, "profit_factor": 1.38, "expectancy_pct": 0.012,
        "n_round_trips": 20, "avg_holding_days": 3.4,
        "fragile": true, "notes": [...]
      },
      "monthly_perf": [{"month": "YYYY-MM", "period_return": ..., "sharpe_annual": ..., ...}],
      "decay_signal": {"status": "stable|improving|decaying|insufficient_data", "slope": ..., ...},
      "positions": [{"ticker": "...", "shares": ..., "avg_cost": ..., "mark": ..., "mtm_pct": ...}],
      "trades_recent": [{"ticker": "...", "side": "BUY", "fill_price": ..., ...}],
      "post_sell": {"per_sell": [...], "monthly": [...], "summary": {...}},
      "hit_rate": {"by_bucket": [...], "by_reason": [...], "by_regime": [...],
                   "sell_reliability": {...}, "notes": [...]},
      "signal_score_hist": {"BUY": [counts per bin], "SELL": [counts per bin], "bins": [edges]},
      "status_counts": {"filled": ..., "approved": ..., "expired": ...},
      "expired_notes_top": [{"note": "...", "count": ...}]
    }

The script reuses metric helpers from ``scripts.baseline_metrics`` so the
dashboard and the baseline frozen JSON agree number-for-number.

Notes:
    * "mark" prices for open positions come from the LAST recorded
      ``price_cache`` snapshot per ticker — best-effort, may be stale.
      Falls back to ``avg_cost`` if unknown (MTM shown as 0%).
    * signal_score histogram uses 10 equal-width bins in [0, 1].
    * monthly_perf / decay_signal added in T06 (alpha decay tracking).
    * post_sell added in T6.2 (opportunity cost post-SELL, roadmap v3):
      forward return close-to-close 5/20 días hábiles después de cada SELL
      filled, usando la fila más fresca de ``historical_data_cache`` (1d).
      fwd > 0 ⇒ el precio siguió subiendo después de vender (upside regalado).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reuse the baseline metric helpers so the dashboard and the frozen baseline
# agree. ``scripts/baseline_metrics.py`` lives next to this file.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from scripts.baseline_metrics import (
    AccountSnapshot,
    _parse_dt,
    equity_metrics,
    fifo_match,
    load_fills,
    load_open_positions,
    load_snapshots,
    monthly_breakdown,
    trade_stats,
)

DEFAULT_DB = "finanzias.db"
DEFAULT_ACCOUNT_ID = 1


# ── Helpers ──────────────────────────────────────────────────────────────────


def _account_row(con: sqlite3.Connection, account_id: int) -> dict | None:
    row = con.execute(
        "SELECT id, name, strategy, mode, allocation_mode, max_positions, "
        "fixed_amount, initial_capital, cash, commission, slippage, is_active, "
        "created_at FROM paper_accounts WHERE id = ?",
        (account_id,),
    ).fetchone()
    if row is None:
        return None
    cols = [
        "id",
        "name",
        "strategy",
        "mode",
        "allocation_mode",
        "max_positions",
        "fixed_amount",
        "initial_capital",
        "cash",
        "commission",
        "slippage",
        "is_active",
        "created_at",
    ]
    return dict(zip(cols, row, strict=True))


def _last_price_for(con: sqlite3.Connection, ticker: str) -> float | None:
    """Best-effort last cached price. Falls back to most recent fill price."""
    row = con.execute(
        "SELECT price FROM price_cache WHERE ticker = ? ORDER BY fetched_at DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if row and row[0] is not None and row[0] > 0:
        return float(row[0])
    # Fallback: most recent filled order for this ticker
    row = con.execute(
        "SELECT fill_price FROM paper_orders WHERE ticker = ? AND status='filled' "
        "AND fill_price IS NOT NULL ORDER BY filled_at DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if row and row[0] is not None and row[0] > 0:
        return float(row[0])
    return None


def _equity_curve(snapshots: list[AccountSnapshot]) -> list[dict]:
    """One row per snapshot, ordered ascending. Light payload for the chart."""
    out: list[dict] = []
    for s in snapshots:
        out.append(
            {
                "t": s.snapshot_at.isoformat(),
                "equity": float(s.total_equity),
                "cash": float(s.cash),
            }
        )
    return out


def _positions_payload(con: sqlite3.Connection, account_id: int) -> list[dict]:
    raw = load_open_positions(con, account_id)
    out: list[dict] = []
    for p in raw:
        mark = _last_price_for(con, p["ticker"])
        if mark is None:
            mark = float(p["avg_cost"])
        avg = float(p["avg_cost"])
        mtm_pct = (mark / avg - 1.0) if avg > 0 else 0.0
        out.append(
            {
                "ticker": p["ticker"],
                "shares": float(p["shares"]),
                "avg_cost": avg,
                "mark": float(mark),
                "value": float(p["shares"]) * float(mark),
                "mtm_pct": mtm_pct,
            }
        )
    out.sort(key=lambda r: r["value"], reverse=True)
    return out


def _trades_recent(con: sqlite3.Connection, account_id: int, limit: int = 50) -> list[dict]:
    rows = con.execute(
        "SELECT ticker, side, fill_price, fill_shares, signal_score, filled_at, "
        "reason, commission_paid, slippage_cost "
        "FROM paper_orders WHERE account_id = ? AND status = 'filled' "
        "AND filled_at IS NOT NULL "
        "ORDER BY filled_at DESC LIMIT ?",
        (account_id, limit),
    ).fetchall()
    out: list[dict] = []
    for ticker, side, px, sh, score, dt, reason, comm, slip in rows:
        out.append(
            {
                "ticker": ticker,
                "side": side,
                "fill_price": float(px) if px else None,
                "fill_shares": float(sh) if sh else None,
                "signal_score": float(score) if score is not None else None,
                "filled_at": dt,
                "reason": reason,
                "notional": (float(px) * float(sh)) if (px and sh) else None,
                "commission": float(comm) if comm is not None else None,
                "slippage_cost": float(slip) if slip is not None else None,
            }
        )
    return out


def _signal_score_hist(con: sqlite3.Connection, account_id: int) -> dict:
    """10-bin histogram on [0, 1] split by BUY/SELL."""
    bins = [i / 10.0 for i in range(11)]  # [0.0, 0.1, ..., 1.0]
    counts_buy = [0] * 10
    counts_sell = [0] * 10
    rows = con.execute(
        "SELECT side, signal_score FROM paper_orders WHERE account_id = ? "
        "AND status = 'filled' AND signal_score IS NOT NULL",
        (account_id,),
    ).fetchall()
    for side, score in rows:
        s = float(score)
        # Bin index 0..9 (clamp top)
        idx = min(int(s * 10), 9)
        if side == "BUY":
            counts_buy[idx] += 1
        elif side == "SELL":
            counts_sell[idx] += 1
    return {"bins": bins, "BUY": counts_buy, "SELL": counts_sell}


def _status_counts(con: sqlite3.Connection, account_id: int) -> dict:
    rows = con.execute(
        "SELECT status, COUNT(*) FROM paper_orders WHERE account_id = ? GROUP BY status",
        (account_id,),
    ).fetchall()
    return {status: int(count) for status, count in rows}


def _expired_notes_top(con: sqlite3.Connection, account_id: int, limit: int = 10) -> list[dict]:
    rows = con.execute(
        "SELECT COALESCE(notes, '(sin nota)') AS n, COUNT(*) AS c "
        "FROM paper_orders WHERE account_id = ? AND status = 'expired' "
        "GROUP BY n ORDER BY c DESC LIMIT ?",
        (account_id, limit),
    ).fetchall()
    return [{"note": n, "count": int(c)} for n, c in rows]


def _monthly_perf(con: sqlite3.Connection, snapshots: list[AccountSnapshot], fills) -> list[dict]:
    """Per-month performance for the alpha decay panel.

    Returns a list of dicts (one per YYYY-MM), ordered chronologically, with:
        month, n_trading_days, period_return, sharpe_annual,
        max_drawdown, n_round_trips, win_rate, profit_factor,
        spy_return, vs_spy   # V1: retorno de SPY del mes y alpha (period_return − SPY)
    """
    trades, _ = fifo_match(fills)
    monthly = monthly_breakdown(snapshots, trades)
    spy = _load_close_series(con, "SPY")  # V1 benchmark (cache diario)
    for row in monthly:
        mo = row.get("month")
        spy_return = None
        if spy and mo:
            in_month = [(d, c) for d, c in spy if d[:7] == mo]
            if len(in_month) >= 2 and in_month[0][1] > 0:
                spy_return = in_month[-1][1] / in_month[0][1] - 1.0
        pr = row.get("period_return")
        row["spy_return"] = spy_return
        row["vs_spy"] = (pr - spy_return) if (pr is not None and spy_return is not None) else None
    return monthly


# Slope threshold for the decay signal (Sharpe units per month).
# |slope| < _DECAY_THRESHOLD → "stable"; slope < −threshold → "decaying"; > threshold → "improving"
_DECAY_THRESHOLD = 0.10


def _decay_signal(monthly: list[dict]) -> dict:
    """Compute alpha decay status from the monthly Sharpe trend.

    Uses the last 4 calendar months that have a non-null sharpe_annual.
    Fits a simple OLS slope; classifies as:

        "improving"          slope  >  +_DECAY_THRESHOLD
        "stable"             |slope| <= _DECAY_THRESHOLD
        "decaying"           slope  <  -_DECAY_THRESHOLD
        "insufficient_data"  fewer than 3 months with valid Sharpe

    Returns dict with keys: status, slope, n_months, recent_sharpes.
    ``recent_sharpes`` is a list of [month_str, sharpe_value] pairs.
    """
    import math

    pairs = [
        (m["month"], m["sharpe_annual"])
        for m in monthly
        if m.get("sharpe_annual") is not None and math.isfinite(m["sharpe_annual"])
    ]
    if len(pairs) < 3:
        return {
            "status": "insufficient_data",
            "slope": None,
            "n_months": len(pairs),
            "recent_sharpes": [[mo, s] for mo, s in pairs],
        }

    recent = pairs[-4:]  # at most last 4 months
    n = len(recent)
    xs = list(range(n))
    ys = [s for _, s in recent]
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    num = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n))
    den = sum((xs[i] - x_mean) ** 2 for i in range(n))
    slope = num / den if den != 0 else 0.0

    if slope < -_DECAY_THRESHOLD:
        status = "decaying"
    elif slope > _DECAY_THRESHOLD:
        status = "improving"
    else:
        status = "stable"

    return {
        "status": status,
        "slope": round(slope, 4),
        "n_months": len(pairs),
        "recent_sharpes": [[mo, s] for mo, s in recent],
    }


# ── T6.2: opportunity cost post-SELL ─────────────────────────────────────────

# Forward horizons en días hábiles. 5/20 = los mismos que usó la auditoría
# de decisiones 2026-06-09 y que usa analysis/catalyst_reaction.py.
_POST_SELL_HORIZONS = (5, 20)


def _load_close_series(con: sqlite3.Connection, ticker: str) -> list[tuple[str, float]] | None:
    """Serie de cierres diarios desde ``historical_data_cache`` (stdlib puro).

    Toma la fila más recientemente fetcheada con interval='1d' para el ticker
    y parsea el ``data_json`` (orient="split" de pandas) sin pandas.
    Devuelve [(date_iso10, close), ...] ordenado ascendente, o None.
    """
    row = con.execute(
        "SELECT data_json FROM historical_data_cache "
        "WHERE ticker = ? AND interval = '1d' "
        "ORDER BY fetched_at DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if not row or not row[0]:
        return None
    try:
        d = json.loads(row[0])
        cols = d["columns"]
        # Columnas pueden venir planas ("Close") o como tuplas serializadas
        # (["Close", "MSFT"]) si el frame era MultiIndex.
        names = [c[0] if isinstance(c, list) else c for c in cols]
        ci = names.index("Close")
        pairs: list[tuple[str, float]] = []
        for ts, vals in zip(d["index"], d["data"], strict=False):
            c = vals[ci]
            if c is not None and float(c) > 0:
                pairs.append((str(ts)[:10], float(c)))
        pairs.sort()
        return pairs or None
    except Exception:
        return None


def _fwd_return_from_series(pairs: list[tuple[str, float]], date_iso10: str, horizon: int) -> float | None:
    """Return close-to-close ``horizon`` días hábiles después de ``date_iso10``.

    Base = cierre del primer día de trading en o después de la fecha (para un
    SELL filled, el mismo día del fill). None si faltan barras futuras todavía
    — el panel se completa solo a medida que pasan los días.
    """
    import bisect

    if not pairs:
        return None
    dates = [p[0] for p in pairs]
    pos = bisect.bisect_left(dates, date_iso10)
    exit_pos = pos + horizon
    if pos >= len(pairs) or exit_pos >= len(pairs):
        return None
    p0 = pairs[pos][1]
    p1 = pairs[exit_pos][1]
    if p0 <= 0:
        return None
    return p1 / p0 - 1.0


def _post_sell_panel(con: sqlite3.Connection, account_id: int) -> dict:
    """Opportunity cost después de cada SELL (T6.2, roadmap v3).

    Para cada SELL filled: forward return del precio 5/20 días hábiles después
    del fill (fwd > 0 ⇒ el precio siguió subiendo ⇒ upside regalado). Es la
    métrica que la auditoría 2026-06-09 calculó a mano, como medición continua.
    Sirve de feedback loop para evaluar T6.1/T6.3/T6.4 en producción.

    Returns::

        {
          "per_sell": [{order_id, ticker, filled_at, fill_price, reason,
                        signal_score, fwd5, fwd20}, ...],   # asc por filled_at
          "monthly": [{month, n_sells, n_fwd5, median_fwd5, pct_positive_fwd5,
                       n_fwd20, median_fwd20}, ...],
          "summary": {n_sells, n_fwd5, median_fwd5, mean_fwd5,
                      pct_positive_fwd5, n_fwd20, median_fwd20, mean_fwd20,
                      pct_positive_fwd20}
        }
    """
    import statistics

    rows = con.execute(
        "SELECT id, ticker, fill_price, filled_at, reason, signal_score "
        "FROM paper_orders WHERE account_id = ? AND side = 'SELL' "
        "AND status = 'filled' AND filled_at IS NOT NULL "
        "ORDER BY filled_at",
        (account_id,),
    ).fetchall()

    series_cache: dict[str, list[tuple[str, float]] | None] = {}
    per_sell: list[dict] = []
    for oid, ticker, px, dt, reason, score in rows:
        if ticker not in series_cache:
            series_cache[ticker] = _load_close_series(con, ticker)
        pairs = series_cache[ticker]
        d10 = str(dt)[:10]
        fwds = {h: (_fwd_return_from_series(pairs, d10, h) if pairs else None) for h in _POST_SELL_HORIZONS}
        per_sell.append(
            {
                "order_id": int(oid),
                "ticker": ticker,
                "filled_at": dt,
                "fill_price": float(px) if px is not None else None,
                "reason": reason,
                "signal_score": float(score) if score is not None else None,
                "fwd5": fwds[5],
                "fwd20": fwds[20],
            }
        )

    def _agg(values: list[float], prefix: str, with_mean: bool = False) -> dict:
        out: dict = {f"n_{prefix}": len(values)}
        if values:
            out[f"median_{prefix}"] = statistics.median(values)
            out[f"pct_positive_{prefix}"] = sum(1 for v in values if v > 0) / len(values)
            if with_mean:
                out[f"mean_{prefix}"] = statistics.fmean(values)
        else:
            out[f"median_{prefix}"] = None
            out[f"pct_positive_{prefix}"] = None
            if with_mean:
                out[f"mean_{prefix}"] = None
        return out

    monthly: list[dict] = []
    months = sorted({s["filled_at"][:7] for s in per_sell if s["filled_at"]})
    for mo in months:
        in_month = [s for s in per_sell if s["filled_at"] and s["filled_at"][:7] == mo]
        f5 = [s["fwd5"] for s in in_month if s["fwd5"] is not None]
        f20 = [s["fwd20"] for s in in_month if s["fwd20"] is not None]
        row = {"month": mo, "n_sells": len(in_month)}
        row.update(_agg(f5, "fwd5"))
        row.update(_agg(f20, "fwd20"))
        monthly.append(row)

    f5_all = [s["fwd5"] for s in per_sell if s["fwd5"] is not None]
    f20_all = [s["fwd20"] for s in per_sell if s["fwd20"] is not None]
    summary: dict = {"n_sells": len(per_sell)}
    summary.update(_agg(f5_all, "fwd5", with_mean=True))
    summary.update(_agg(f20_all, "fwd20", with_mean=True))

    return {"per_sell": per_sell, "monthly": monthly, "summary": summary}


# ── T6.3: hit-rate tracking real (ex-T07) ────────────────────────────────────

# Rango de score donde la auditoría 2026-06-09 sospecha descalibración al
# pesimismo en los SELLs de señal (ejecutan con 0.22-0.47 y el precio sigue
# subiendo después). El resumen "sell_reliability" mide exactamente eso.
_SELL_RELIABILITY_RANGE = (0.20, 0.45)


def _reason_kind(reason: str | None) -> str:
    """Clasifica el reason de una orden en familias estables.

    "signal" = decisión del modelo (analyze BUY/SELL); las demás son exits de
    riesgo mecánicos cuyo signal_score es un sentinel (1.0), no una
    probabilidad — por eso los buckets de score solo usan "signal".
    """
    if not reason:
        return "other"
    r = reason.strip().lower()
    if r.startswith("analyze"):
        return "signal"
    if r.startswith("atr_stop"):
        return "atr_stop"
    if r.startswith("atr_trail"):
        return "atr_trail"
    if r.startswith("vol_trim"):
        return "vol_trim"
    return "other"


def _score_bucket(score: float | None) -> str | None:
    """Bucket de ancho 0.1 en [0,1] como string estable, ej. "0.3-0.4"."""
    if score is None:
        return None
    idx = min(max(int(float(score) * 10), 0), 9)
    return f"{idx / 10:.1f}-{(idx + 1) / 10:.1f}"


def _hit_for(side: str, fwd5: float | None) -> bool | None:
    """Definición de hit direccional a 5 días hábiles (mismo horizonte que el
    label de entrenamiento del modelo):

      BUY  hit ⇔ fwd5 > 0   (compré y subió)
      SELL hit ⇔ fwd5 <= 0  (vendí y no siguió subiendo)
    """
    if fwd5 is None:
        return None
    return fwd5 > 0 if side == "BUY" else fwd5 <= 0


def _hit_group_stats(orders: list[dict]) -> dict:
    """Agregados de un grupo de órdenes ya anotadas con fwd5/fwd20/hit/realized."""
    import statistics

    f5 = [o["fwd5"] for o in orders if o["fwd5"] is not None]
    f20 = [o["fwd20"] for o in orders if o["fwd20"] is not None]
    hits = [o["hit"] for o in orders if o["hit"] is not None]
    scores = [o["signal_score"] for o in orders if o["signal_score"] is not None]
    realized = [o["realized_pct"] for o in orders if o.get("realized_pct") is not None]
    return {
        "n": len(orders),
        "n_fwd5": len(f5),
        "hit_rate_fwd5": (sum(hits) / len(hits)) if hits else None,
        "p_up_fwd5": (sum(1 for v in f5 if v > 0) / len(f5)) if f5 else None,
        "median_fwd5": statistics.median(f5) if f5 else None,
        "median_fwd20": statistics.median(f20) if f20 else None,
        "avg_score": statistics.fmean(scores) if scores else None,
        "median_realized_pct": statistics.median(realized) if realized else None,
    }


def _regime_for_dates(con: sqlite3.Connection, dates_iso10: list[str]) -> dict[str, str] | None:
    """Mapa fecha → régimen de mercado, best-effort (T6.3).

    Proxy equal-weight de los closes cacheados (1d) de todo el universo,
    normalizados a 1.0 en su primera barra, clasificado con
    ``analysis.regime_detector`` (mismas defaults que el harness). Requiere
    pandas; si algo falta devuelve None y el panel omite el corte por régimen.
    """
    if not dates_iso10:
        return None
    try:
        import pandas as pd

        from analysis.regime_detector import detect_regime_series

        tickers = [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT ticker FROM historical_data_cache WHERE interval='1d'"
            ).fetchall()
        ]
        cols: dict[str, dict[str, float]] = {}
        for t in tickers:
            pairs = _load_close_series(con, t)
            if pairs and len(pairs) >= 2:
                base = pairs[0][1]
                cols[t] = {d: px / base for d, px in pairs}
        if len(cols) < 5:
            return None
        frame = pd.DataFrame(cols).sort_index()
        proxy = frame.mean(axis=1, skipna=True).dropna()
        if len(proxy) < 80:  # warmup 60 barras + margen
            return None
        market_df = pd.DataFrame({"Close": proxy})
        series = detect_regime_series(market_df)["regime"]
        out: dict[str, str] = {}
        idx = list(series.index)  # date strings iso10, ordenadas
        import bisect

        for d in dates_iso10:
            pos = bisect.bisect_right(idx, d) - 1  # asof: barra <= fecha
            out[d] = str(series.iloc[pos]) if pos >= 0 else "warmup"
        return out
    except Exception:
        return None


def _hit_rate_panel(con: sqlite3.Connection, account_id: int, fills) -> dict:
    """Hit-rate real por bucket de signal_score, reason y régimen (T6.3/ex-T07).

    Sobre cada orden filled: forward return 5/20d (mismas series y semántica
    que el panel T6.2) + hit direccional (ver ``_hit_for``) + realized return
    FIFO para SELLs. El foco es la reliability del rango SELL 0.2-0.45: si el
    score está calibrado como P(subida), un SELL con score 0.30 debería ver el
    precio subir ~30% de las veces; ``calibration_gap = p_up_real - avg_score``
    > 0 significa SELLs descalibrados al pesimismo (vendemos cosas que suben).

    Returns::

        {
          "horizon_days": 5,
          "by_bucket": [{side, bucket, n, avg_score, p_up_fwd5, hit_rate_fwd5,
                         median_fwd5, median_fwd20, median_realized_pct,
                         calibration_gap}, ...],   # solo reason_kind=="signal"
          "by_reason": [{side, reason_kind, n, ...stats}, ...],
          "by_regime": [{regime, side, n, ...stats}, ...],  # [] si no hay proxy
          "sell_reliability": {range, n, n_fwd5, avg_score, p_up_fwd5,
                               calibration_gap, hit_rate_fwd5, median_fwd5,
                               median_realized_pct} | None,
          "notes": [...]
        }
    """
    rows = con.execute(
        "SELECT id, ticker, side, fill_price, filled_at, reason, signal_score "
        "FROM paper_orders WHERE account_id = ? AND status = 'filled' "
        "AND filled_at IS NOT NULL ORDER BY filled_at",
        (account_id,),
    ).fetchall()

    # Realized return por SELL vía FIFO (un Trade por SELL fill); match por
    # (ticker, filled_at) en orden cronológico.
    realized_by_key: dict[tuple[str, str], list[float]] = {}
    if fills:
        trades, _ = fifo_match(fills)
        for t in trades:
            if t.cost_basis > 0:
                key = (t.ticker, t.close_date.isoformat())
                realized_by_key.setdefault(key, []).append(t.pnl / t.cost_basis)

    series_cache: dict[str, list[tuple[str, float]] | None] = {}
    annotated: list[dict] = []
    for oid, ticker, side, _px, dt, reason, score in rows:
        if ticker not in series_cache:
            series_cache[ticker] = _load_close_series(con, ticker)
        pairs = series_cache[ticker]
        d10 = str(dt)[:10]
        fwd5 = _fwd_return_from_series(pairs, d10, 5) if pairs else None
        fwd20 = _fwd_return_from_series(pairs, d10, 20) if pairs else None
        kind = _reason_kind(reason)
        realized = None
        if side == "SELL":
            # Normalizar el timestamp igual que fifo_match (que parsea con
            # _parse_dt) — el filled_at crudo de la DB usa espacio, no "T".
            try:
                parsed = _parse_dt(str(dt))
                if parsed is None:  # el except de abajo ya lo tomaba igual
                    raise ValueError("timestamp sin parsear")
                key = (ticker, parsed.isoformat())
            except Exception:
                key = (ticker, str(dt))
            lst = realized_by_key.get(key)
            if lst:
                realized = lst.pop(0)
        annotated.append(
            {
                "order_id": int(oid),
                "ticker": ticker,
                "side": side,
                "filled_at": dt,
                "date": d10,
                "reason_kind": kind,
                # score sentinel de exits de riesgo no es probabilidad → None
                "signal_score": float(score) if (score is not None and kind == "signal") else None,
                "fwd5": fwd5,
                "fwd20": fwd20,
                "hit": _hit_for(side, fwd5),
                "realized_pct": realized,
            }
        )

    notes: list[str] = []

    # by_bucket — solo órdenes de señal con score
    by_bucket: list[dict] = []
    sig = [o for o in annotated if o["reason_kind"] == "signal" and o["signal_score"] is not None]
    keys = sorted({(o["side"], _score_bucket(o["signal_score"])) for o in sig})
    for side, bucket in keys:
        grp = [o for o in sig if o["side"] == side and _score_bucket(o["signal_score"]) == bucket]
        stats = _hit_group_stats(grp)
        gap = None
        if stats["p_up_fwd5"] is not None and stats["avg_score"] is not None:
            gap = stats["p_up_fwd5"] - stats["avg_score"]
        by_bucket.append({"side": side, "bucket": bucket, "calibration_gap": gap, **stats})

    # by_reason
    by_reason: list[dict] = []
    for side, kind in sorted({(o["side"], o["reason_kind"]) for o in annotated}):
        grp = [o for o in annotated if o["side"] == side and o["reason_kind"] == kind]
        by_reason.append({"side": side, "reason_kind": kind, **_hit_group_stats(grp)})

    # by_regime — best-effort
    by_regime: list[dict] = []
    regime_map = _regime_for_dates(con, sorted({o["date"] for o in annotated}))
    if regime_map:
        for o in annotated:
            o["regime"] = regime_map.get(o["date"], "warmup")
        for regime, side in sorted({(o["regime"], o["side"]) for o in annotated}):
            grp = [o for o in annotated if o["regime"] == regime and o["side"] == side]
            by_regime.append({"regime": regime, "side": side, **_hit_group_stats(grp)})
    else:
        notes.append("by_regime omitido: no se pudo construir el proxy de mercado")

    # sell_reliability — el número que pidió la auditoría
    lo, hi = _SELL_RELIABILITY_RANGE
    rel_grp = [o for o in sig if o["side"] == "SELL" and lo <= o["signal_score"] <= hi]
    sell_reliability = None
    if rel_grp:
        stats = _hit_group_stats(rel_grp)
        gap = None
        if stats["p_up_fwd5"] is not None and stats["avg_score"] is not None:
            gap = stats["p_up_fwd5"] - stats["avg_score"]
        sell_reliability = {"range": [lo, hi], "calibration_gap": gap, **stats}

    n_no_fwd = sum(1 for o in annotated if o["fwd5"] is None)
    if n_no_fwd:
        notes.append(f"{n_no_fwd} órdenes sin fwd5 todavía (fills recientes o sin cache)")

    return {
        "horizon_days": 5,
        "by_bucket": by_bucket,
        "by_reason": by_reason,
        "by_regime": by_regime,
        "sell_reliability": sell_reliability,
        "notes": notes,
    }


def _kpis(snapshots: list[AccountSnapshot], fills) -> dict:
    """Bundle the headline metrics shown above the equity chart."""
    em = equity_metrics(snapshots)
    trades, _open = fifo_match(fills)
    ts = trade_stats(trades)
    notes: list[str] = []
    fragile = False
    n_days = em.get("n_trading_days", 0) or 0
    n_rt = ts.get("n_round_trips", 0) or 0
    if n_days < 30:
        fragile = True
        notes.append(f"Sharpe fragile: only {n_days} trading days")
    if n_rt < 30:
        fragile = True
        notes.append(f"Trade stats fragile: only {n_rt} round-trips")
    return {
        "period_return": em.get("period_return"),
        "cagr": em.get("cagr"),
        "sharpe": em.get("sharpe_annual"),
        "max_dd": em.get("max_drawdown"),
        "max_dd_date": em.get("max_dd_date"),
        "n_trading_days": n_days,
        "win_rate": ts.get("win_rate"),
        "profit_factor": ts.get("profit_factor"),
        "expectancy_pct": ts.get("expectancy_pct"),
        "expectancy_dollars": ts.get("expectancy_dollars"),
        "n_round_trips": n_rt,
        "n_buys": ts.get("n_buys"),
        "n_sells": ts.get("n_sells"),
        "avg_holding_days": ts.get("avg_holding_days"),
        "fragile": fragile,
        "notes": notes,
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def build_payload(db_path: Path, account_id: int) -> dict:
    con = sqlite3.connect(str(db_path))
    try:
        account = _account_row(con, account_id)
        if account is None:
            return {"error": f"account {account_id} not found in {db_path}"}
        snapshots = load_snapshots(con, account_id)
        fills = load_fills(con, account_id)
        monthly = _monthly_perf(con, snapshots, fills)
        payload: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "db_path": str(db_path),
            "account": account,
            "equity_curve": _equity_curve(snapshots),
            "kpis": _kpis(snapshots, fills),
            "monthly_perf": monthly,
            "decay_signal": _decay_signal(monthly),
            "positions": _positions_payload(con, account_id),
            "trades_recent": _trades_recent(con, account_id, limit=50),
            "post_sell": _post_sell_panel(con, account_id),
            "hit_rate": _hit_rate_panel(con, account_id, fills),
            "signal_score_hist": _signal_score_hist(con, account_id),
            "status_counts": _status_counts(con, account_id),
            "expired_notes_top": _expired_notes_top(con, account_id, limit=10),
        }
        return payload
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Dump dashboard JSON for the live HTML artifact.")
    p.add_argument("--db", default=None, help="Path to finanzias.db (default: repo root)")
    p.add_argument("--account", type=int, default=DEFAULT_ACCOUNT_ID, help="Account id (default: 1)")
    args = p.parse_args(argv)

    if args.db is None:
        db_path = _HERE.parent / DEFAULT_DB
    else:
        db_path = Path(args.db)

    if not db_path.exists():
        print(json.dumps({"error": f"db not found: {db_path}"}))
        return 1

    payload = build_payload(db_path, args.account)
    # NaN-safe serialization: convert any non-finite floats to None.
    print(json.dumps(payload, default=_json_default, ensure_ascii=False))
    return 0


def _json_default(o):
    import math

    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"Unserializable: {type(o).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
