"""
T-CAT-0 harvester — daily point-in-time ingest of news + analyst consensus.

Sprint 5 · Catalyst Intelligence Engine · gate cero.

Runs once per day (recommended: ~16:30 ET via Windows Task Scheduler, decoupled
from the trading scans). Idempotent: re-running the same day adds no duplicates.
It only writes the two append-only tables ``news_events`` and
``analyst_estimate_snapshots`` — no alpha, no classification, no scoring. The
whole point is that *tomorrow there is one more day of point-in-time data than
today*.

IMPORTANT: run this on Windows (where ``finanzias.db`` lives). Never run the
write path from the Linux sandbox — see the virtiofs-incoherence note.

Usage
-----
    python scripts/harvest_catalysts.py                 # Sim Principal watchlist
    python scripts/harvest_catalysts.py --account-id 1
    python scripts/harvest_catalysts.py --universe sp500
    python scripts/harvest_catalysts.py --tickers NVDA,PLTR,RKLB
    python scripts/harvest_catalysts.py --sources yfinance,sec,finnhub
    python scripts/harvest_catalysts.py --dry-run       # collect + report, no writes

Finnhub: set a free key once (Windows: ``setx FINNHUB_API_KEY "your-key"``) so
the scheduled harvest sees it. Without the key the finnhub source is skipped.
News rows are deduped both by content_hash and by canonical URL, so enabling
overlapping sources (e.g. finnhub + yfinance) won't double-count a shared story.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Allow ``python scripts/harvest_catalysts.py`` from the repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.logging_config import get_logger
from data.news_sources import collect_all
from database.models import (
    AnalystEstimateSnapshot,
    NewsEvent,
    session_scope,
    utcnow_naive,
)

log = get_logger(__name__)

DEFAULT_ACCOUNT_ID = 1  # "Sim Principal"


@dataclass
class HarvestReport:
    tickers: int = 0
    news_new: int = 0
    news_dup: int = 0
    est_new: int = 0
    est_dup: int = 0
    failed: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"Harvest: {self.tickers} tickers | news +{self.news_new} "
            f"(dup {self.news_dup}) | estimates +{self.est_new} (dup {self.est_dup}) "
            f"| failed {len(self.failed)}"
        )


def _midnight(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


# Tracking query params that don't identify the article — dropped so the same
# story arriving via two sources/feeds with different campaign tags collapses.
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ncid", "cmp", "_ga", "guccounter"}


def canonical_url(url: str | None) -> str | None:
    """
    Normalize a URL into a stable dedup key.

    Forces https, lowercases + de-``www``s the host, strips tracking query
    params, drops the fragment and any trailing slash. Returns None for a falsy
    or scheme-less/host-less string. Best-effort: on any parse error it falls
    back to the lowercased raw string so a weird URL still dedups against itself.
    """
    if not url or not str(url).strip():
        return None
    raw = str(url).strip()
    try:
        s = urlsplit(raw)
        if not s.netloc:
            return None
        host = s.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        q = [
            (k, v)
            for k, v in parse_qsl(s.query, keep_blank_values=False)
            if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_KEYS
        ]
        q.sort()
        path = s.path.rstrip("/")
        return urlunsplit(("https", host, path, urlencode(q), ""))
    except Exception:
        return raw.lower()


def resolve_universe(account_id: int = DEFAULT_ACCOUNT_ID) -> list[str]:
    """Watchlist ∪ open positions for the account (mirrors engine.py)."""
    from paper_trading.models import PaperPosition, PaperWatchlistItem

    with session_scope() as s:
        watch = {
            w.ticker
            for w in s.query(PaperWatchlistItem).filter(PaperWatchlistItem.account_id == account_id).all()
        }
        pos = {
            p.ticker
            for p in s.query(PaperPosition)
            .filter(PaperPosition.account_id == account_id)
            .filter(PaperPosition.shares > 0)
            .all()
        }
    return sorted(watch | pos)


def _insert_news_if_new(session, item, seen: set[str], seen_urls: set[str]) -> bool:
    """
    Insert a NewsItem unless it's a duplicate. Returns True if new.

    Two dedup layers:
      1. URL: the same article URL (canonicalized) from any source collapses —
         catches a story carried by both Finnhub and Yahoo/RSS in the same run,
         where the titles differ so ``content_hash`` would not catch it.
      2. content_hash: (ticker, normalized title, hour) — the original guard for
         items without a URL or with differing URLs but the same headline.
    Both are checked in-run (the sets) and against already-stored rows.
    """
    cu = canonical_url(item.url)
    if cu is not None and cu in seen_urls:
        return False
    h = item.content_hash()
    if h in seen:
        return False
    seen.add(h)
    if cu is not None:
        seen_urls.add(cu)
    exists = session.query(NewsEvent.id).filter(NewsEvent.content_hash == h).first()
    if exists is not None:
        return False
    if item.url is not None:
        url_dup = session.query(NewsEvent.id).filter(NewsEvent.url == item.url).first()
        if url_dup is not None:
            return False
    session.add(
        NewsEvent(
            ticker=item.ticker,
            title=item.title,
            content=item.content,
            source=item.source,
            url=item.url,
            published_at=item.published_at,
            content_hash=h,
        )
    )
    session.flush()  # surface IntegrityError early; keeps the dedup honest
    return True


def _insert_estimate_if_new_today(session, snap, today: datetime) -> bool:
    """Insert one EstimateSnapshot per (ticker, metric, period_label, day). Returns True if new."""
    exists = (
        session.query(AnalystEstimateSnapshot.id)
        .filter(AnalystEstimateSnapshot.ticker == snap.ticker)
        .filter(AnalystEstimateSnapshot.metric == snap.metric)
        .filter(AnalystEstimateSnapshot.period_label == snap.period_label)
        .filter(AnalystEstimateSnapshot.snapshot_date == today)
        .first()
    )
    if exists is not None:
        return False
    session.add(
        AnalystEstimateSnapshot(
            ticker=snap.ticker,
            metric=snap.metric,
            period_label=snap.period_label,
            consensus_value=snap.consensus_value,
            num_analysts=snap.num_analysts,
            snapshot_date=today,
            fetched_at=utcnow_naive(),
        )
    )
    session.flush()
    return True


def harvest(
    tickers: list[str] | None = None,
    *,
    account_id: int = DEFAULT_ACCOUNT_ID,
    sources: set[str] | None = None,
    collector=collect_all,
    now: datetime | None = None,
    dry_run: bool = False,
) -> HarvestReport:
    """
    Collect news + estimate snapshots for ``tickers`` (default = the account's
    watchlist ∪ positions) and persist new rows idempotently.

    ``collector(ticker, sources)`` is injectable so tests can run fully offline.
    """
    universe = tickers if tickers is not None else resolve_universe(account_id)
    now = now or utcnow_naive()
    today = _midnight(now)
    report = HarvestReport(tickers=len(universe))
    seen_hashes: set[str] = set()
    seen_urls: set[str] = set()

    if dry_run:
        for t in universe:
            try:
                res = collector(t, sources)
                report.news_new += len(res.news)
                report.est_new += len(res.estimates)
            except Exception:
                log.exception("collect failed for %s", t)
                report.failed.append(t)
        log.info("[dry-run] %s", report.summary())
        return report

    # Fase 1 — recolectar (RED) FUERA de toda sesión. Tener la conexión tomada
    # durante los fetch de red (yfinance/SEC/RSS, ~90s para 52 tickers) era un
    # lock-holder enorme que chocaba con el scan/bulk-fetch paralelo →
    # "database is locked" + agotamiento del QueuePool. Mismo patrón que
    # classify_events. Idéntico al camino dry_run, que ya recolecta sin sesión.
    collected: list[tuple[str, object]] = []
    for t in universe:
        try:
            res = collector(t, sources)
        except Exception:
            log.exception("collect failed for %s", t)
            report.failed.append(t)
            continue
        collected.append((t, res))

    # Fase 2 — persistir en transacciones CORTAS, una por ticker. Los contadores
    # se vuelcan al report SOLO tras commit exitoso (antes un rollback por un
    # item fallido descartaba en silencio todo lo pendiente del run pero dejaba
    # los contadores inflados). El dedup in-run (seen_hashes) se mantiene global.
    for t, res in collected:
        n_new = n_dup = e_new = e_dup = 0
        try:
            with session_scope() as session:
                for item in res.news:
                    if _insert_news_if_new(session, item, seen_hashes, seen_urls):
                        n_new += 1
                    else:
                        n_dup += 1
                for snap in res.estimates:
                    if _insert_estimate_if_new_today(session, snap, today):
                        e_new += 1
                    else:
                        e_dup += 1
        except Exception:
            log.exception("persist failed for %s", t)
            report.failed.append(t)
            continue
        report.news_new += n_new
        report.news_dup += n_dup
        report.est_new += e_new
        report.est_dup += e_dup

    log.info("%s", report.summary())
    return report


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="T-CAT-0 catalyst harvester (point-in-time ingest).")
    p.add_argument(
        "--account-id", type=int, default=DEFAULT_ACCOUNT_ID, help="Paper account whose watchlist to harvest."
    )
    p.add_argument(
        "--universe",
        choices=["sim", "sp500"],
        default="sim",
        help="sim = account watchlist; sp500 = full index.",
    )
    p.add_argument("--tickers", type=str, default=None, help="Comma-separated override, e.g. NVDA,PLTR,RKLB.")
    p.add_argument(
        "--sources",
        type=str,
        default="yfinance",
        help="Comma-separated: yfinance,sec,rss,finnhub (finnhub needs FINNHUB_API_KEY).",
    )
    p.add_argument("--dry-run", action="store_true", help="Collect and report without writing to the DB.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    sources = {s.strip() for s in args.sources.split(",") if s.strip()}

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    elif args.universe == "sp500":
        from data.ticker_universe import get_sp500_tickers

        tickers = get_sp500_tickers()
    else:
        tickers = None  # resolve from account watchlist

    report = harvest(tickers, account_id=args.account_id, sources=sources, dry_run=args.dry_run)
    print(report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
