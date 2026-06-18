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
        "profit_factor", "avg_win", "avg_loss", "expectancy",
        "avg_hold_days", "total_costs",
        "by_exit_kind": {kind: {"n", "pnl", "avg"}},
        "per_ticker": [{"ticker","pnl","n"}...],
        "worst_ticker": {"ticker","pnl"}, "pnl_ex_worst": float,
        "top_winners": [...], "top_losers": [...],
        "round_trips": [ {...} ]   # cronológico por sell_day
      },
      "timing": {
        "n5","good5","good5_pct","mean5","median5",
        "n20","good20","good20_pct","mean20","median20",
        "score_fwd5_corr", "score_fwd5_n",
        "per_buy": [{"ticker","score","fwd5","fwd20","day"}...]
      },
      "sell_calibration": {"n","up_after","up_after_pct","mean_fwd5"},
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
                    expectancy=0.0, avg_hold_days=0.0, total_costs=0.0,
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

    def _slim(r: dict) -> dict:
        return {k: r[k] for k in ("ticker", "pnl", "pnl_pct", "hold_days",
                                  "exit_kind", "sell_reason", "buy_day", "sell_day")}

    return dict(
        n_round_trips=len(rts),
        total_pnl=total,
        n_wins=len(wins),
        n_losses=len(losses),
        win_rate=len(wins) / len(rts),
        profit_factor=(gw / gl if gl else None),
        avg_win=(gw / len(wins) if wins else 0.0),
        avg_loss=(-gl / len(losses) if losses else 0.0),
        expectancy=total / len(rts),
        avg_hold_days=sum(r["hold_days"] for r in rts) / len(rts),
        total_costs=sum(r["costs"] for r in rts),
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


def _expired_buys(con: sqlite3.Connection, account_id: int) -> dict:
    rows = con.execute(
        "SELECT ticker,COUNT(*) FROM paper_orders "
        "WHERE account_id=? AND side='BUY' AND status='expired' GROUP BY ticker",
        (account_id,),
    ).fetchall()
    by = {t: n for t, n in rows}
    return {"n": sum(by.values()), "by_ticker": by}


# ── entrypoint ────────────────────────────────────────────────────────────────
def build_metrics(con: sqlite3.Connection, account_id: int = 1,
                  now: datetime | None = None) -> dict[str, Any]:
    """Calcula el payload completo de métricas para ``account_id``."""
    orders = _filled_orders(con, account_id)
    rts = pair_round_trips(orders)
    return {
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "account_id": account_id,
        "realized": _realized_panel(rts),
        "timing": _timing_panel(con, orders),
        "sell_calibration": _sell_calibration_panel(con, orders),
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
