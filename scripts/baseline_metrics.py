"""
Baseline metrics dump — Sprint 0 anchor.

Reads paper-trading state from ``finanzias.db`` (or a supplied path) and
computes a fixed set of performance metrics per paper account, both overall
and broken down by month. Persists the result as a timestamped JSON in
``data/baselines/`` and prints a console-friendly table.

Why this exists
---------------
Sprint 0 of the validation-first roadmap calls for a frozen snapshot of
current paper-trading performance, so subsequent T-feature attribution
(Sprint 2) can be measured against a *real* baseline rather than gut feel.
The same script is meant to be re-runnable at any point to track drift.

Metrics
-------
Equity-based (from ``paper_equity_snapshots``, last per calendar day):
    period_return, cagr, sharpe_annual, max_drawdown, max_dd_date,
    n_trading_days, calendar_days

Trade-based (from ``paper_orders`` where ``status='filled'``, FIFO matched):
    n_buys, n_sells, notional_volume, turnover_annual,
    n_round_trips, win_rate, profit_factor, expectancy_dollars,
    expectancy_pct, avg_holding_days

Monthly breakdown
-----------------
For each ``YYYY-MM`` with data: period_return, sharpe, max_dd, round-trip
stats (closed in that month).

Usage
-----
    python scripts/baseline_metrics.py
    python scripts/baseline_metrics.py --db backups/finanzias_2026-05-26_00-28-50_daily.db
    python scripts/baseline_metrics.py --out data/baselines  --no-write
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Constants ────────────────────────────────────────────────────────────────

TRADING_DAYS_PER_YEAR = 252
CALENDAR_DAYS_PER_YEAR = 365

# Min sample sizes below which the metric is annotated as fragile
MIN_DAYS_FOR_SHARPE = 5
MIN_DAYS_FOR_CAGR = 30


# ── Data containers ──────────────────────────────────────────────────────────


@dataclass
class Fill:
    """One filled ``paper_order`` row."""

    order_id: int
    ticker: str
    side: str  # "BUY" | "SELL"
    shares: float
    price: float
    commission: float
    slippage: float
    filled_at: datetime

    @property
    def notional(self) -> float:
        return self.shares * self.price

    @property
    def gross_cost(self) -> float:
        """Cash paid (BUY) including fees, or proceeds received (SELL) net of fees."""
        if self.side == "BUY":
            return self.notional + self.commission + self.slippage
        return self.notional - self.commission - self.slippage


@dataclass
class Trade:
    """A FIFO-matched round trip closing event (one per SELL fill)."""

    ticker: str
    open_date: datetime  # earliest BUY date among consumed lots
    close_date: datetime
    shares: float
    cost_basis: float  # total cost incl. fees/slippage of consumed BUY lots
    proceeds: float  # net of SELL fees/slippage
    holding_days: float

    @property
    def pnl(self) -> float:
        return self.proceeds - self.cost_basis

    @property
    def pnl_pct(self) -> float:
        return (self.proceeds / self.cost_basis - 1.0) if self.cost_basis > 0 else 0.0

    @property
    def is_win(self) -> bool:
        return self.pnl > 0


@dataclass
class AccountSnapshot:
    """One row from ``paper_equity_snapshots``."""

    snapshot_at: datetime
    total_equity: float
    cash: float
    positions_value: float


@dataclass
class AccountResult:
    account_id: int
    name: str
    initial_capital: float
    overall: dict[str, Any] = field(default_factory=dict)
    monthly: list[dict[str, Any]] = field(default_factory=list)
    open_positions: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ── DB loading ───────────────────────────────────────────────────────────────


def _parse_dt_req(value: str | None) -> datetime:
    """Como ``_parse_dt`` pero **exige** el valor.

    Las queries que lo usan filtran ``IS NOT NULL``, asi que un None ahi seria un
    desvio del SQL —no un dato faltante— y conviene que grite en vez de propagar
    un None a un dataclass que no lo admite.
    """
    dt = _parse_dt(value)
    if dt is None:
        raise ValueError("fecha nula donde el SQL garantiza NOT NULL")
    return dt


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    # SQLite stores naive ISO strings; fromisoformat handles microseconds.
    return datetime.fromisoformat(value)


def load_accounts(con: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = con.cursor()
    cur.execute(
        "SELECT id, name, initial_capital, cash, is_active, allocation_mode, "
        "strategy, created_at FROM paper_accounts ORDER BY id"
    )
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def load_fills(con: sqlite3.Connection, account_id: int) -> list[Fill]:
    cur = con.cursor()
    cur.execute(
        "SELECT id, ticker, side, fill_shares, fill_price, "
        "COALESCE(commission_paid,0), COALESCE(slippage_cost,0), filled_at "
        "FROM paper_orders "
        "WHERE account_id=? AND status='filled' AND fill_shares IS NOT NULL "
        "AND fill_price IS NOT NULL AND filled_at IS NOT NULL "
        "ORDER BY filled_at",
        (account_id,),
    )
    return [
        Fill(
            order_id=row[0],
            ticker=row[1],
            side=row[2],
            shares=float(row[3]),
            price=float(row[4]),
            commission=float(row[5]),
            slippage=float(row[6]),
            filled_at=_parse_dt_req(row[7]),
        )
        for row in cur.fetchall()
    ]


def load_snapshots(con: sqlite3.Connection, account_id: int) -> list[AccountSnapshot]:
    cur = con.cursor()
    cur.execute(
        "SELECT snapshot_at, total_equity, cash, positions_value "
        "FROM paper_equity_snapshots WHERE account_id=? ORDER BY snapshot_at",
        (account_id,),
    )
    return [
        AccountSnapshot(
            snapshot_at=_parse_dt_req(row[0]),
            total_equity=float(row[1]),
            cash=float(row[2]),
            positions_value=float(row[3]),
        )
        for row in cur.fetchall()
    ]


def load_open_positions(con: sqlite3.Connection, account_id: int) -> list[dict[str, Any]]:
    cur = con.cursor()
    cur.execute(
        "SELECT ticker, shares, avg_cost, opened_at, entry_reason "
        "FROM paper_positions WHERE account_id=? AND shares>0 ORDER BY ticker",
        (account_id,),
    )
    return [
        {
            "ticker": row[0],
            "shares": float(row[1]),
            "avg_cost": float(row[2]),
            "cost_basis": float(row[1]) * float(row[2]),
            "opened_at": row[3],
            "entry_reason": row[4],
        }
        for row in cur.fetchall()
    ]


# ── Pure metric functions (no I/O — easy to unit test) ───────────────────────


def daily_endpoints(snapshots: list[AccountSnapshot]) -> list[tuple[datetime, float]]:
    """Return (date, last_total_equity) per calendar day, chronologically.

    A scan can fire many times per day; we keep the last one as the day's
    closing equity. Returns an empty list if ``snapshots`` is empty.
    """
    by_day: dict[str, tuple[datetime, float]] = {}
    for s in snapshots:
        key = s.snapshot_at.strftime("%Y-%m-%d")
        existing = by_day.get(key)
        if existing is None or s.snapshot_at > existing[0]:
            by_day[key] = (s.snapshot_at, s.total_equity)
    return [by_day[k] for k in sorted(by_day)]


def daily_returns(endpoints: list[tuple[datetime, float]]) -> list[float]:
    """Simple daily returns from consecutive equity endpoints."""
    rets: list[float] = []
    for i in range(1, len(endpoints)):
        prev = endpoints[i - 1][1]
        curr = endpoints[i][1]
        if prev <= 0:
            continue
        rets.append(curr / prev - 1.0)
    return rets


def sharpe_annual(returns: list[float]) -> float | None:
    """Annualised Sharpe with Rf=0, daily returns × √252.

    Returns None if fewer than 2 returns or zero stdev.
    """
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    stdev = math.sqrt(var)
    if stdev == 0:
        return None
    return (mean / stdev) * math.sqrt(TRADING_DAYS_PER_YEAR)


def max_drawdown(endpoints: list[tuple[datetime, float]]) -> tuple[float, str | None]:
    """Max peak-to-trough drawdown over the equity curve.

    Returns ``(max_dd_pct, trough_date_iso)``. ``max_dd_pct`` is a positive
    number representing the worst peak-to-trough percentage loss.
    """
    if not endpoints:
        return 0.0, None
    peak = endpoints[0][1]
    max_dd = 0.0
    trough_date: datetime | None = None
    for date, eq in endpoints:
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
                trough_date = date
    return max_dd, (trough_date.strftime("%Y-%m-%d") if trough_date else None)


def cagr(endpoints: list[tuple[datetime, float]]) -> float | None:
    """Compound annual growth rate from first to last endpoint.

    Returns None if fewer than 2 endpoints, calendar_days <= 0, or
    starting equity <= 0.
    """
    if len(endpoints) < 2:
        return None
    start_date, start_eq = endpoints[0]
    end_date, end_eq = endpoints[-1]
    days = (end_date.date() - start_date.date()).days
    if days <= 0 or start_eq <= 0 or end_eq <= 0:
        return None
    return (end_eq / start_eq) ** (CALENDAR_DAYS_PER_YEAR / days) - 1.0


def period_return(endpoints: list[tuple[datetime, float]]) -> float | None:
    if len(endpoints) < 2 or endpoints[0][1] <= 0:
        return None
    return endpoints[-1][1] / endpoints[0][1] - 1.0


def fifo_match(fills: list[Fill]) -> tuple[list[Trade], dict[str, deque]]:
    """Walk ``fills`` chronologically per ticker, FIFO-matching SELLs to BUYs.

    Returns ``(closed_trades, open_lots_by_ticker)``. Each SELL emits one
    Trade record. Lots left over at the end represent open positions and are
    returned in the second dict.

    Notes
    -----
    * Lot cost = ``shares * price + commission + slippage`` (BUY perspective).
    * SELL proceeds = ``shares * price - commission - slippage``.
    * If a SELL exceeds available BUY shares (data inconsistency), we close
      what we can and log nothing here — the caller is responsible for
      noting the discrepancy if it cares.
    * Partial closes carry over the remaining lot at its original
      per-share cost.
    """
    lots_by_ticker: dict[str, deque[dict[str, Any]]] = {}
    trades: list[Trade] = []

    for f in sorted(fills, key=lambda x: x.filled_at):
        lots = lots_by_ticker.setdefault(f.ticker, deque())

        if f.side == "BUY":
            lots.append(
                {
                    "shares": f.shares,
                    "cost_per_share": (f.notional + f.commission + f.slippage) / f.shares,
                    "opened_at": f.filled_at,
                }
            )
            continue

        # SELL — peel oldest lots until we cover ``f.shares`` (or run out).
        remaining = f.shares
        consumed_cost = 0.0
        earliest_open: datetime | None = None
        weighted_open_days = 0.0
        weighted_shares_for_holding = 0.0
        proceeds_total = f.notional - f.commission - f.slippage

        while remaining > 1e-9 and lots:
            lot = lots[0]
            take = min(lot["shares"], remaining)
            consumed_cost += take * lot["cost_per_share"]
            holding = (f.filled_at - lot["opened_at"]).total_seconds() / 86400.0
            weighted_open_days += holding * take
            weighted_shares_for_holding += take
            if earliest_open is None or lot["opened_at"] < earliest_open:
                earliest_open = lot["opened_at"]
            lot["shares"] -= take
            remaining -= take
            if lot["shares"] <= 1e-9:
                lots.popleft()

        # If SELL exceeded inventory, attribute the un-covered portion's
        # proceeds back to the closed shares (treat it like an empty cost).
        # This keeps PnL conservative without breaking the row.
        closed_shares = f.shares - remaining
        if closed_shares <= 0 or earliest_open is None:
            continue

        # Pro-rata proceeds for what we actually closed (in case of overshoot).
        closed_proceeds = proceeds_total * (closed_shares / f.shares)
        avg_holding = (
            weighted_open_days / weighted_shares_for_holding if weighted_shares_for_holding > 0 else 0.0
        )
        trades.append(
            Trade(
                ticker=f.ticker,
                open_date=earliest_open,
                close_date=f.filled_at,
                shares=closed_shares,
                cost_basis=consumed_cost,
                proceeds=closed_proceeds,
                holding_days=avg_holding,
            )
        )

    return trades, lots_by_ticker


def trade_stats(trades: Iterable[Trade]) -> dict[str, Any]:
    trades = list(trades)
    n = len(trades)
    if n == 0:
        return {
            "n_round_trips": 0,
            "win_rate": None,
            "profit_factor": None,
            "expectancy_dollars": None,
            "expectancy_pct": None,
            "avg_holding_days": None,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
        }
    wins = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win]
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = sum(t.pnl for t in losses)  # negative
    profit_factor: float | None
    if gross_loss < 0:
        profit_factor = gross_profit / abs(gross_loss)
    elif gross_profit > 0:
        profit_factor = math.inf
    else:
        profit_factor = None
    return {
        "n_round_trips": n,
        "win_rate": len(wins) / n,
        "profit_factor": profit_factor,
        "expectancy_dollars": sum(t.pnl for t in trades) / n,
        "expectancy_pct": sum(t.pnl_pct for t in trades) / n,
        "avg_holding_days": sum(t.holding_days for t in trades) / n,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
    }


def turnover_metrics(
    fills: list[Fill],
    endpoints: list[tuple[datetime, float]],
) -> dict[str, Any]:
    """Notional volume and annualised turnover.

    Convention: each fill (BUY or SELL) contributes its own notional. This
    matches the "two-sided" turnover convention used by most fund prospectuses
    when reported as ``notional/avg_equity`` without halving.
    """
    notional = sum(f.notional for f in fills)
    if not endpoints:
        return {
            "n_buys": sum(1 for f in fills if f.side == "BUY"),
            "n_sells": sum(1 for f in fills if f.side == "SELL"),
            "notional_volume": notional,
            "avg_equity": None,
            "turnover_period": None,
            "turnover_annual": None,
        }
    avg_eq = sum(eq for _, eq in endpoints) / len(endpoints)
    days = (endpoints[-1][0].date() - endpoints[0][0].date()).days
    turnover_period = (notional / avg_eq) if avg_eq > 0 else None
    if turnover_period is not None and days > 0:
        turnover_annual = turnover_period * (CALENDAR_DAYS_PER_YEAR / days)
    else:
        turnover_annual = None
    return {
        "n_buys": sum(1 for f in fills if f.side == "BUY"),
        "n_sells": sum(1 for f in fills if f.side == "SELL"),
        "notional_volume": notional,
        "avg_equity": avg_eq,
        "turnover_period": turnover_period,
        "turnover_annual": turnover_annual,
    }


def equity_metrics(snapshots: list[AccountSnapshot]) -> dict[str, Any]:
    endpoints = daily_endpoints(snapshots)
    rets = daily_returns(endpoints)
    sharpe = sharpe_annual(rets)
    dd_pct, dd_date = max_drawdown(endpoints)
    return {
        "n_trading_days": len(endpoints),
        "n_daily_returns": len(rets),
        "calendar_days": (
            (endpoints[-1][0].date() - endpoints[0][0].date()).days if len(endpoints) >= 2 else 0
        ),
        "first_snapshot_at": endpoints[0][0].isoformat() if endpoints else None,
        "last_snapshot_at": endpoints[-1][0].isoformat() if endpoints else None,
        "start_equity": endpoints[0][1] if endpoints else None,
        "end_equity": endpoints[-1][1] if endpoints else None,
        "period_return": period_return(endpoints),
        "cagr": cagr(endpoints),
        "sharpe_annual": sharpe,
        "max_drawdown": dd_pct,
        "max_dd_date": dd_date,
    }


def monthly_breakdown(
    snapshots: list[AccountSnapshot],
    trades: list[Trade],
) -> list[dict[str, Any]]:
    """Per-month metrics aligned by calendar month (YYYY-MM)."""
    endpoints = daily_endpoints(snapshots)
    by_month_eps: dict[str, list[tuple[datetime, float]]] = {}
    for d, eq in endpoints:
        by_month_eps.setdefault(d.strftime("%Y-%m"), []).append((d, eq))

    by_month_trades: dict[str, list[Trade]] = {}
    for t in trades:
        by_month_trades.setdefault(t.close_date.strftime("%Y-%m"), []).append(t)

    months = sorted(set(by_month_eps) | set(by_month_trades))
    out: list[dict[str, Any]] = []
    for m in months:
        eps = by_month_eps.get(m, [])
        ts = by_month_trades.get(m, [])
        rets = daily_returns(eps)
        dd_pct, dd_date = max_drawdown(eps)
        ts_stats = trade_stats(ts)
        out.append(
            {
                "month": m,
                "n_trading_days": len(eps),
                "period_return": period_return(eps),
                "sharpe_annual": sharpe_annual(rets),
                "max_drawdown": dd_pct if eps else None,
                "max_dd_date": dd_date,
                "n_round_trips": ts_stats["n_round_trips"],
                "win_rate": ts_stats["win_rate"],
                "profit_factor": ts_stats["profit_factor"],
                "expectancy_dollars": ts_stats["expectancy_dollars"],
            }
        )
    return out


# ── Top-level orchestration ──────────────────────────────────────────────────


def compute_account(
    account: dict[str, Any],
    fills: list[Fill],
    snapshots: list[AccountSnapshot],
    open_positions: list[dict[str, Any]],
) -> AccountResult:
    result = AccountResult(
        account_id=account["id"],
        name=account["name"],
        initial_capital=float(account["initial_capital"]),
    )

    eq = equity_metrics(snapshots)
    to = turnover_metrics(fills, daily_endpoints(snapshots))
    trades, _open_lots = fifo_match(fills)
    ts = trade_stats(trades)

    result.overall = {
        **eq,
        **to,
        **ts,
        "strategy": account.get("strategy"),
        "allocation_mode": account.get("allocation_mode"),
        "is_active": bool(account.get("is_active", True)),
    }

    # Annotations for thin samples
    if eq["n_daily_returns"] is not None and eq["n_daily_returns"] < MIN_DAYS_FOR_SHARPE:
        result.notes.append(f"sharpe based on {eq['n_daily_returns']} daily returns — fragile")
    if eq["calendar_days"] is not None and eq["calendar_days"] < MIN_DAYS_FOR_CAGR:
        result.notes.append(f"cagr extrapolated from {eq['calendar_days']} calendar days — fragile")
    if ts["n_round_trips"] is not None and ts["n_round_trips"] < 10:
        result.notes.append(f"trade stats based on {ts['n_round_trips']} round trips — noisy")

    result.monthly = monthly_breakdown(snapshots, trades)
    result.open_positions = open_positions
    return result


def write_json(results: list[AccountResult], db_path: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    target = out_dir / f"baseline_{ts}.json"
    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": str(db_path),
        "accounts": [
            {
                "account_id": r.account_id,
                "name": r.name,
                "initial_capital": r.initial_capital,
                "notes": r.notes,
                "overall": r.overall,
                "monthly": r.monthly,
                "open_positions": r.open_positions,
            }
            for r in results
        ],
    }
    target.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    return target


def _json_default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    raise TypeError(f"Type {type(o).__name__} not JSON-serialisable")


# ── Console formatting ───────────────────────────────────────────────────────


def _fmt_pct(x: float | None, digits: int = 2) -> str:
    return f"{x * 100:.{digits}f}%" if x is not None else "—"


def _fmt_money(x: float | None) -> str:
    return f"${x:,.2f}" if x is not None else "—"


def _fmt_ratio(x: float | None, digits: int = 2) -> str:
    if x is None:
        return "—"
    if math.isinf(x):
        return "∞"
    return f"{x:.{digits}f}"


def print_account(result: AccountResult) -> None:
    o = result.overall
    print()
    print("═" * 78)
    print(
        f"Cuenta #{result.account_id} — {result.name}   "
        f"(capital inicial {_fmt_money(result.initial_capital)})"
    )
    print("─" * 78)
    if o.get("first_snapshot_at"):
        print(
            f"Periodo: {o['first_snapshot_at'][:10]} → {o['last_snapshot_at'][:10]}  "
            f"({o['calendar_days']} días calendario, {o['n_trading_days']} días con snap)"
        )
        print(f"Equity: {_fmt_money(o['start_equity'])} → {_fmt_money(o['end_equity'])}")
    else:
        print("Sin snapshots de equity — saltea métricas equity-based.")

    print()
    print(f"{'Métrica':<28} {'Valor':>18}")
    print("─" * 48)
    print(f"{'Period return':<28} {_fmt_pct(o.get('period_return')):>18}")
    print(f"{'CAGR (anual)':<28} {_fmt_pct(o.get('cagr')):>18}")
    print(f"{'Sharpe (anual, Rf=0)':<28} {_fmt_ratio(o.get('sharpe_annual')):>18}")
    print(f"{'Max drawdown':<28} {_fmt_pct(o.get('max_drawdown')):>18}")
    if o.get("max_dd_date"):
        print(f"{'  (fecha del trough)':<28} {o['max_dd_date']:>18}")
    print(f"{'Turnover (anual)':<28} {_fmt_ratio(o.get('turnover_annual')):>18}")
    print(f"{'Notional fills':<28} {_fmt_money(o.get('notional_volume')):>18}")
    fills_str = f"{o.get('n_buys', 0)} / {o.get('n_sells', 0)}"
    print(f"{'Fills (BUY / SELL)':<28} {fills_str:>18}")
    print(f"{'Round trips cerrados':<28} {o.get('n_round_trips', 0):>18}")
    print(f"{'Win rate':<28} {_fmt_pct(o.get('win_rate')):>18}")
    print(f"{'Profit factor':<28} {_fmt_ratio(o.get('profit_factor')):>18}")
    print(f"{'Expectancy ($)':<28} {_fmt_money(o.get('expectancy_dollars')):>18}")
    print(f"{'Expectancy (%)':<28} {_fmt_pct(o.get('expectancy_pct')):>18}")
    print(f"{'Holding promedio (días)':<28} {_fmt_ratio(o.get('avg_holding_days'), 1):>18}")

    if result.notes:
        print()
        print("Notas:")
        for n in result.notes:
            print(f"  • {n}")

    if result.monthly:
        print()
        print("Breakdown mensual:")
        hdr = f"{'Mes':<8} {'Ret':>8} {'Sharpe':>8} {'MaxDD':>8} {'Trades':>7} {'Win%':>7} {'PF':>6}"
        print(hdr)
        print("─" * len(hdr))
        for m in result.monthly:
            print(
                f"{m['month']:<8} "
                f"{_fmt_pct(m['period_return'], 1):>8} "
                f"{_fmt_ratio(m['sharpe_annual'], 2):>8} "
                f"{_fmt_pct(m['max_drawdown'], 1):>8} "
                f"{m['n_round_trips']:>7} "
                f"{_fmt_pct(m['win_rate'], 0):>7} "
                f"{_fmt_ratio(m['profit_factor'], 2):>6}"
            )

    if result.open_positions:
        print()
        print(f"Posiciones abiertas: {len(result.open_positions)}")
        for p in result.open_positions:
            print(
                f"  {p['ticker']:<6} {p['shares']:>10.2f} @ "
                f"{_fmt_money(p['avg_cost'])}  (cost {_fmt_money(p['cost_basis'])})"
            )


# ── Entry point ──────────────────────────────────────────────────────────────


def run(db_path: Path, out_dir: Path, write: bool = True) -> dict[str, Any]:
    """Public entry point: returns the payload that gets written to disk."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        accounts = load_accounts(con)
        results: list[AccountResult] = []
        for acct in accounts:
            fills = load_fills(con, acct["id"])
            snaps = load_snapshots(con, acct["id"])
            opens = load_open_positions(con, acct["id"])
            results.append(compute_account(acct, fills, snaps, opens))
    finally:
        con.close()

    for r in results:
        print_account(r)

    if write:
        target = write_json(results, db_path, out_dir)
        print()
        print(f"✓ Baseline persistido en {target}")
    else:
        print()
        print("(--no-write: no se escribió JSON)")

    return {"accounts": [r.__dict__ for r in results]}


def _default_db() -> Path:
    return Path(__file__).resolve().parent.parent / "finanzias.db"


def _default_out() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "baselines"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=_default_db(), help="ruta a la SQLite DB")
    parser.add_argument("--out", type=Path, default=_default_out(), help="directorio para el JSON")
    parser.add_argument("--no-write", action="store_true", help="no escribir el JSON (sólo imprime)")
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"ERROR: DB no encontrada: {args.db}")
        return 1

    run(args.db, args.out, write=not args.no_write)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
