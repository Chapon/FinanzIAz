"""
T-CAT-3 builder — compute the historical-reaction table from classified events.

Sprint 5 · Catalyst Intelligence Engine. Reads classified ``news_events``
(event_type set, published_at present) plus the OHLCV cache, computes forward
returns at 1/5/20 trading days, and aggregates them by event_type and by
(ticker, event_type). Writes a JSON snapshot and prints a summary table.

Read-only on the DB (it only SELECTs news_events and reads the price cache via
MarketDataService). Safe to run anytime; the table strengthens as the harvest
accumulates more point-in-time events with enough forward window.

Usage
-----
    python scripts/build_historical_reaction.py
    python scripts/build_historical_reaction.py --period 5y --min-count 8
    python scripts/build_historical_reaction.py --out data/catalyst/historical_reaction.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.catalyst_reaction import DEFAULT_HORIZONS, build_historical_reaction  # noqa: E402
from config.logging_config import get_logger  # noqa: E402
from database.models import NewsEvent, session_scope  # noqa: E402

log = get_logger(__name__)

DEFAULT_OUT = ROOT / "data" / "catalyst" / "historical_reaction.json"


def _load_classified_events() -> list[tuple[str, str, object]]:
    with session_scope() as s:
        rows = (
            s.query(NewsEvent)
            .filter(NewsEvent.event_type.isnot(None))
            .filter(NewsEvent.published_at.isnot(None))
            .all()
        )
        return [(r.ticker, r.event_type, r.published_at) for r in rows]


def _price_loader(period: str = "2y"):
    from data.market_data_service import MarketDataService

    svc = MarketDataService()

    def _load(ticker: str):
        return svc.get_history(ticker, period=period, interval="1d")

    return _load


def _print_summary(table: dict, horizon: int) -> None:
    h = str(horizon)
    rows = []
    for event_type, per_h in table.get("by_event", {}).items():
        stat = per_h.get(h, {})
        if stat.get("count", 0):
            rows.append((event_type, stat["count"], stat["mean"], stat["hit_rate"]))
    rows.sort(key=lambda r: (r[2] if r[2] is not None else -9), reverse=True)
    print(f"\nForward return @ {horizon}d by event_type (n events with full window):")
    print(f"  {'event_type':<22} {'n':>5} {'mean':>8} {'hit_rate':>9}")
    for et, n, mean, hit in rows:
        print(f"  {et:<22} {n:>5} {mean*100:>7.2f}% {hit*100:>8.1f}%")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="T-CAT-3 historical-reaction table builder.")
    p.add_argument("--period", default="2y", help="OHLCV history period to pull (default 2y).")
    p.add_argument("--horizon", type=int, default=5, help="Horizon (days) for the printed summary.")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="Output JSON path.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    events = _load_classified_events()
    log.info("loaded %d classified events with published_at", len(events))
    table = build_historical_reaction(events, _price_loader(args.period), horizons=DEFAULT_HORIZONS)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(table, indent=2), encoding="utf-8")
    n_event = len(table.get("by_event", {}))
    n_te = len(table.get("by_ticker_event", {}))
    print(f"Wrote {out} — {n_event} event_types, {n_te} (ticker,event) buckets.")
    _print_summary(table, args.horizon)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
