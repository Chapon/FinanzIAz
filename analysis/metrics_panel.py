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
        "account_return","spy_return","vs_spy"
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
      "expired_buys": {"n", "by_ticker": {...}}
    }

``commit_markers(repo_dir)`` es aparte (usa git) para no acoplar el cálculo al repo.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ventana del forward return (días hábiles aproximados por índice de barras 1d).
FWD_SHORT = 5
FWD_LONG = 20
CHURN_DAYS = 7

# Benchmark de mercado (V1). SPY total-return implícito del cache yfinance
# (auto_adjust=True) — sesgo documentado en el BACKLOG: los dividendos ya están
# reinvertidos en el ajuste, así que la comparación es contra el retorno total.
BENCHMARK_TICKER = "SPY"

# Keywords que marcan commits que cambian la *lógica de trading* (para el overlay
# del gráfico de efectividad). Se filtran del git log por subject.
_BEHAVIOR_COMMIT_KEYWORDS = (
    "gate", "exit", "stop", "atr", "churn", "hysteresis",
    "vol-overlay", "vol overlay", "overlay", "sizing",
    "t6.", "t-cat", "t01", "t05", "t06", "t09", "t10",
    "anti-churn", "anti-whipsaw", "regime", "regimen",
    "kill", "stacking", "veto", "hit-rate", "score-hysteresis",
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
    """Lista ``(YYYY-MM-DD, close)`` ordenada por fecha desde la fila 1d más fresca.

    Devuelve ``None`` si no hay cache para el ticker.
    """
    row = con.execute(
        "SELECT data_json FROM historical_data_cache "
        "WHERE ticker=? AND interval='1d' ORDER BY fetched_at DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if not row or not row[0]:
        return None
    try:
        d = json.loads(row[0])
        ci = d["columns"].index("Close")
    except (ValueError, KeyError, json.JSONDecodeError):
        return None
    out: list[tuple[str, float]] = []
    for idx, vals in zip(d.get("index", []), d.get("data", [])):
        try:
            cl = vals[ci]
        except (IndexError, TypeError):
            continue
        if cl is not None and isinstance(idx, str):
            out.append((idx[:10], float(cl)))
    return out or None


def load_ohlc_series(con: sqlite3.Connection, ticker: str) -> list[tuple[str, float, float]] | None:
    """Lista ``(YYYY-MM-DD, high, low)`` ordenada por fecha desde la fila 1d más fresca.

    Igual que ``load_close_series`` pero devuelve el rango intradía (High/Low) que
    un stop/target realmente ve — usado para MAE/MFE. Tolera columnas planas
    (``"High"``) o serializadas como tupla (``["High","MSFT"]``, frame MultiIndex).
    Devuelve ``None`` si no hay cache, o si faltan las columnas High/Low.
    """
    row = con.execute(
        "SELECT data_json FROM historical_data_cache "
        "WHERE ticker=? AND interval='1d' ORDER BY fetched_at DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if not row or not row[0]:
        return None
    try:
        d = json.loads(row[0])
        names = [c[0] if isinstance(c, list) else c for c in d["columns"]]
        hi = names.index("High")
        lo = names.index("Low")
    except (ValueError, KeyError, json.JSONDecodeError):
        return None
    out: list[tuple[str, float, float]] = []
    for idx, vals in zip(d.get("index", []), d.get("data", [])):
        try:
            h = vals[hi]
            lw = vals[lo]
        except (IndexError, TypeError):
            continue
        if h is not None and lw is not None and isinstance(idx, str):
            out.append((idx[:10], float(h), float(lw)))
    out.sort()
    return out or None


def excursions(series_hl: list[tuple[str, float, float]] | None,
               buy_day: str | None, sell_day: str | None,
               buy_price: float | None) -> tuple[float | None, float | None]:
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
        mae, mfe = excursions(series_cache[t], r.get("buy_day"), r.get("sell_day"),
                              r.get("buy_price"))
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
    cols = ("id", "ticker", "side", "fill_price", "fill_shares", "commission",
            "slippage", "score", "reason", "filled_at")
    return [dict(zip(cols, r)) for r in rows]


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
                dict(shares=sh, price=o["fill_price"], cps=cps, sps=sps,
                     buy_id=o["id"], day=_day(o["filled_at"]), score=o["score"])
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
                rts.append(dict(
                    ticker=o["ticker"], buy_id=lot["buy_id"], sell_id=o["id"],
                    shares=take, buy_price=lot["price"], sell_price=o["fill_price"],
                    pnl=pnl, pnl_pct=(pnl / (take * lot["price"]) if lot["price"] else 0.0),
                    buy_score=lot["score"], sell_score=o["score"],
                    sell_reason=o["reason"], exit_kind=_exit_kind(o["reason"]),
                    buy_day=lot["day"], sell_day=_day(o["filled_at"]),
                    hold_days=hold,
                    costs=(take * lot["cps"] + take * lot["sps"] + take * cps + take * sps),
                ))
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
        return dict(n_round_trips=0, total_pnl=0.0, n_wins=0, n_losses=0,
                    win_rate=0.0, profit_factor=None, avg_win=0.0, avg_loss=0.0,
                    payoff_ratio=None,
                    expectancy=0.0, avg_hold_days=0.0, total_costs=0.0,
                    excursion={"n": 0, "median_mae": None, "median_mfe": None,
                               "avg_mae": None, "avg_mfe": None,
                               "worst_mae": None, "best_mfe": None},
                    by_exit_kind={}, per_ticker=[], worst_ticker=None,
                    pnl_ex_worst=0.0, top_winners=[], top_losers=[], round_trips=[])
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
        d = {k: r[k] for k in ("ticker", "pnl", "pnl_pct", "hold_days",
                               "exit_kind", "sell_reason", "buy_day", "sell_day")}
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
        by_exit_kind={k: {"n": v[0], "pnl": v[1], "avg": v[1] / v[0] if v[0] else 0.0}
                      for k, v in by_kind.items()},
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
        per_buy.append({"ticker": o["ticker"], "score": o["score"],
                        "fwd5": r5, "fwd20": r20, "day": day})
        if r5 is not None:
            f5.append(r5)
            if o["score"] is not None:
                pairs.append((float(o["score"]), r5))
        if r20 is not None:
            f20.append(r20)
    g5 = [x for x in f5 if x > 0]
    g20 = [x for x in f20 if x > 0]
    return dict(
        n5=len(f5), good5=len(g5), good5_pct=(len(g5) / len(f5) if f5 else 0.0),
        mean5=(sum(f5) / len(f5) if f5 else 0.0), median5=_median(f5),
        n20=len(f20), good20=len(g20), good20_pct=(len(g20) / len(f20) if f20 else 0.0),
        mean20=(sum(f20) / len(f20) if f20 else 0.0), median20=_median(f20),
        score_fwd5_corr=_corr(pairs), score_fwd5_n=len(pairs),
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
        r5 = forward_return(series_cache[t], _day(o["filled_at"]), FWD_SHORT)
        if r5 is not None:
            regret.append(r5)
    up = [r for r in regret if r > 0]
    return dict(
        n=len(regret), up_after=len(up),
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
        per_sell.append({"ticker": o["ticker"], "score": o["score"], "exit_kind": kind,
                         "fwd5": r5, "fwd20": r20, "day": day})
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
    g5 = [x for x in f5 if x <= 0]   # venta buena = el precio no subió después
    g20 = [x for x in f20 if x <= 0]
    with_f5 = [p for p in per_sell if p["fwd5"] is not None]
    return dict(
        n5=len(f5), good5=len(g5), good5_pct=(len(g5) / len(f5) if f5 else 0.0),
        mean5=(sum(f5) / len(f5) if f5 else 0.0), median5=_median(f5),
        n20=len(f20), good20=len(g20), good20_pct=(len(g20) / len(f20) if f20 else 0.0),
        mean20=(sum(f20) / len(f20) if f20 else 0.0), median20=_median(f20),
        by_exit_kind={k: {"n": v[0], "good_pct": (v[1] / v[0] if v[0] else 0.0),
                          "mean_fwd5": (v[2] / v[0] if v[0] else 0.0)}
                      for k, v in by_kind.items()},
        sell_score_fwd5_corr=_corr(pairs), sell_score_fwd5_n=len(pairs),
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
                    events.append({"ticker": t, "gap_days": gap,
                                   "sell_id": evs[i][2], "buy_id": evs[i + 1][2]})
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
        out.append({"day": r["sell_day"], "cum_pnl": cum, "trades": i,
                    "rolling_win_rate": wins / i})
    return out


def _open_positions(con: sqlite3.Connection, account_id: int) -> list[dict]:
    rows = con.execute(
        "SELECT ticker,shares,avg_cost FROM paper_positions "
        "WHERE account_id=? AND shares>0 ORDER BY ticker",
        (account_id,),
    ).fetchall()
    out = []
    for tkr, sh, ac in rows:
        s = load_close_series(con, tkr)
        mark = s[-1][1] if s else ac
        mtm = (mark / ac - 1.0) if ac else 0.0
        out.append({"ticker": tkr, "shares": sh, "avg_cost": ac,
                    "mark": mark, "mtm_pct": mtm})
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
            "SELECT sector FROM company_info_cache WHERE ticker=? "
            "ORDER BY fetched_at DESC LIMIT 1",
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
        positions.append({
            "ticker": tkr,
            "market_value": shares * float(mark),
            "unrealized_pnl": (float(mark) - avg) * shares if avg > 0 else 0.0,
        })

    # Frame de retornos desde el cache (para la correlación media). El history
    # provider arma un DataFrame ['Close'] por ticker a partir de load_close_series.
    def _hp(t: str):
        s = load_close_series(con, t)
        if not s:
            return None
        import pandas as pd

        return pd.DataFrame({"Close": [c for _, c in s]},
                            index=[d for d, _ in s])

    rf = None
    tickers = [p["ticker"] for p in positions]
    if len(tickers) >= 2:
        try:
            rf = returns_frame(tickers, _hp)
        except Exception:
            rf = None

    return book_concentration(
        positions, returns=rf, sector_of=lambda t: cached_sector(con, t)
    )


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


def _benchmark_panel(con: sqlite3.Connection, account_id: int) -> dict:
    """Retorno de la cuenta vs SPY sobre la MISMA ventana (V1).

    Toma el primer y último ``paper_equity_snapshots`` de la cuenta como ventana
    y compara el retorno de equity contra el retorno de SPY entre esas fechas
    (cache diario, ``load_close_series``). Permite, por primera vez, separar
    sistema de mercado: ``vs_spy = account_return − spy_return`` (alpha del período).

    Best-effort/display-only: ``available=False`` si faltan snapshots (<2) o el
    cache de SPY. No lanza si la tabla de snapshots no existe (DB sintética).
    """
    empty = {"available": False, "ticker": BENCHMARK_TICKER,
             "start_day": None, "end_day": None,
             "account_return": None, "spy_return": None, "vs_spy": None}
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
    start_eq = float(rows[0][1] or 0.0)
    end_eq = float(rows[-1][1] or 0.0)
    account_return = (end_eq / start_eq - 1.0) if start_eq > 0 else None
    spy = load_close_series(con, BENCHMARK_TICKER)
    if not spy or start_day is None or end_day is None:
        return {**empty, "start_day": start_day, "end_day": end_day,
                "account_return": account_return}
    spy = sorted(spy)
    p0 = _close_on_or_after(spy, start_day)
    p1 = _close_on_or_before(spy, end_day)
    spy_return = (p1 / p0 - 1.0) if (p0 and p1 and p0 > 0) else None
    vs_spy = (account_return - spy_return) if (
        account_return is not None and spy_return is not None) else None
    return {"available": spy_return is not None, "ticker": BENCHMARK_TICKER,
            "start_day": start_day, "end_day": end_day,
            "account_return": account_return, "spy_return": spy_return,
            "vs_spy": vs_spy}


# ── entrypoint ────────────────────────────────────────────────────────────────
def build_metrics(con: sqlite3.Connection, account_id: int = 1,
                  now: datetime | None = None) -> dict[str, Any]:
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
            ["git", "-C", str(repo_dir), "log",
             f"-{limit}", "--date=format:%Y-%m-%d",
             "--pretty=format:%ad|%s"],
            capture_output=True, text=True, timeout=10, check=False,
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
