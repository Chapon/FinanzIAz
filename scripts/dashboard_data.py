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
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Reuse the baseline metric helpers so the dashboard and the frozen baseline
# agree. ``scripts/baseline_metrics.py`` lives next to this file.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from scripts.baseline_metrics import (  # noqa: E402
    AccountSnapshot,
    daily_endpoints,
    daily_returns,
    equity_metrics,
    fifo_match,
    load_fills,
    load_snapshots,
    load_open_positions,
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
        "id", "name", "strategy", "mode", "allocation_mode", "max_positions",
        "fixed_amount", "initial_capital", "cash", "commission", "slippage",
        "is_active", "created_at",
    ]
    return dict(zip(cols, row))


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
        out.append({
            "t": s.snapshot_at.isoformat(),
            "equity": float(s.total_equity),
            "cash": float(s.cash),
        })
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
        out.append({
            "ticker": p["ticker"],
            "shares": float(p["shares"]),
            "avg_cost": avg,
            "mark": float(mark),
            "value": float(p["shares"]) * float(mark),
            "mtm_pct": mtm_pct,
        })
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
        out.append({
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
        })
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


def _monthly_perf(snapshots: list[AccountSnapshot], fills) -> list[dict]:
    """Per-month performance for the alpha decay panel.

    Returns a list of dicts (one per YYYY-MM), ordered chronologically, with:
        month, n_trading_days, period_return, sharpe_annual,
        max_drawdown, n_round_trips, win_rate, profit_factor
    """
    trades, _ = fifo_match(fills)
    return monthly_breakdown(snapshots, trades)


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
        monthly = _monthly_perf(snapshots, fills)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "db_path": str(db_path),
            "account": account,
            "equity_curve": _equity_curve(snapshots),
            "kpis": _kpis(snapshots, fills),
            "monthly_perf": monthly,
            "decay_signal": _decay_signal(monthly),
            "positions": _positions_payload(con, account_id),
            "trades_recent": _trades_recent(con, account_id, limit=50),
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
tancy_pct": ts.get("expectancy_pct"),
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
        monthly = _monthly_perf(snapshots, fills)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "db_path": str(db_path),
            "account": account,
            "equity_curve": _equity_curve(snapshots),
            "kpis": _kpis(snapshots, fills),
            "monthly_perf": monthly,
            "decay_signal": _decay_signal(monthly),
            "positions": _positions_payload(con, account_id),
            "trades_recent": _trades_recent(con, account_id, limit=50),
            "signal_score_hist": _signal_score_hist(con, account_id),
            "status_counts": _status_counts(con, account_id),
            "expired_notes_top": _expired_notes_top(con, account_id, limit=10),
        }
        return payload
    finally:
        con.close()


def main(argv=None):
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
__ == "__main__":
    raise SystemExit(main())
