"""
Per-ticker catalyst feed — a read-only view over ``news_events``.

Sprint 5 · Catalyst Intelligence Engine · T-CAT-1 (useful output of the news
collector before any classification or scoring exists). This is the "útil solo"
deliverable: a glanceable feed of recent point-in-time headlines per ticker,
straight from what the harvester has accumulated.

It never writes — pure SELECTs against the append-only ``news_events`` table.

Usage
-----
    python scripts/news_feed.py --ticker NVDA            # one ticker
    python scripts/news_feed.py --ticker NVDA --limit 30
    python scripts/news_feed.py --watchlist              # account 1 watchlist∪positions
    python scripts/news_feed.py --source sec_8k          # filter by source
"""

from __future__ import annotations

import argparse
import sys
from collections import namedtuple
from pathlib import Path

# Allow ``python scripts/news_feed.py`` from the repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.models import NewsEvent, session_scope

DEFAULT_ACCOUNT_ID = None  # T70: se resuelve contra `is_active`, no un literal

FeedRow = namedtuple("FeedRow", "ticker published_at source title url event_type")


def recent_news(
    ticker: str | None = None,
    *,
    tickers: list[str] | None = None,
    source: str | None = None,
    limit: int = 20,
) -> list[FeedRow]:
    """
    Return the most recent ``news_events`` rows, newest first.

    Most-recent is by ``published_at`` (NULLs sorted last in a portable way),
    tie-broken by insertion id. Filter by a single ``ticker``, a list of
    ``tickers`` (e.g. a watchlist), and/or a ``source`` tag.
    """
    with session_scope() as s:
        q = s.query(NewsEvent)
        if ticker:
            q = q.filter(NewsEvent.ticker == ticker.upper())
        if tickers:
            q = q.filter(NewsEvent.ticker.in_([t.upper() for t in tickers]))
        if source:
            q = q.filter(NewsEvent.source == source)
        # NULL published_at sorts last (False < True), then newest date, then id.
        q = q.order_by(
            NewsEvent.published_at.is_(None),
            NewsEvent.published_at.desc(),
            NewsEvent.id.desc(),
        ).limit(limit)
        return [FeedRow(r.ticker, r.published_at, r.source, r.title, r.url, r.event_type) for r in q.all()]


def _watchlist_universe(account_id: int | None = None) -> list[str]:
    """Reuse the harvester's universe resolver (watchlist ∪ open positions)."""
    from scripts.harvest_catalysts import resolve_universe

    return resolve_universe(account_id)


def _fmt_row(r: FeedRow) -> str:
    when = r.published_at.strftime("%Y-%m-%d %H:%M") if r.published_at else "----------  ---- "
    tag = f"[{r.source}]"
    evt = f" ({r.event_type})" if r.event_type else ""
    return f"{when}  {r.ticker:<6} {tag:<16}{evt} {r.title}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Per-ticker catalyst feed (read-only).")
    p.add_argument("--ticker", type=str, default=None, help="Single ticker, e.g. NVDA.")
    p.add_argument("--watchlist", action="store_true", help="All tickers in account watchlist ∪ positions.")
    p.add_argument("--account-id", type=int, default=None, help="Account for --watchlist.")
    p.add_argument("--source", type=str, default=None, help="Filter by source tag, e.g. sec_8k, yahoo_rss.")
    p.add_argument("--limit", type=int, default=20, help="Max rows.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    tickers = _watchlist_universe(args.account_id) if args.watchlist else None
    rows = recent_news(ticker=args.ticker, tickers=tickers, source=args.source, limit=args.limit)
    if not rows:
        print("(no news_events match — has the harvester run?)")
        return 0
    for r in rows:
        print(_fmt_row(r))
    print(f"\n{len(rows)} item(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
