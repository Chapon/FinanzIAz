"""
T-CAT-2 classifier runner — tag accumulated ``news_events`` with
``{event_type, sentiment, classifier_confidence}``.

Sprint 5 · Catalyst Intelligence Engine. Reads rows the harvester (T-CAT-0/1)
already stored and fills the classification columns via an **in-place UPDATE**
— the one sanctioned exception to the table's append-only rule (it adds
metadata, never alters the raw observation).

Idempotent: by default only classifies rows where ``event_type IS NULL``, so
re-running is a no-op. ``--reclassify`` forces a redo (e.g. after swapping
backends or tweaking keywords). The classifier ``backend`` is injectable so
tests run fully offline; the default is the free heuristic.

Usage
-----
    python scripts/classify_catalysts.py                 # classify the unclassified
    python scripts/classify_catalysts.py --limit 200
    python scripts/classify_catalysts.py --source sec_8k
    python scripts/classify_catalysts.py --reclassify    # redo everything
    python scripts/classify_catalysts.py --dry-run       # report only, no writes
    python scripts/classify_catalysts.py --sample 100    # dump labeled sample for manual QA
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.logging_config import get_logger  # noqa: E402
from data.catalyst_classifier import classify  # noqa: E402
from database.models import NewsEvent, session_scope, utcnow_naive  # noqa: E402

log = get_logger(__name__)


@dataclass
class ClassifyReport:
    scanned: int = 0
    classified: int = 0
    failed: int = 0
    by_event: Counter = field(default_factory=Counter)
    by_sentiment: Counter = field(default_factory=Counter)

    def summary(self) -> str:
        top = ", ".join(f"{k}={v}" for k, v in self.by_event.most_common(5))
        return (
            f"Classify: scanned {self.scanned} | classified {self.classified} "
            f"| failed {self.failed} | sentiment {dict(self.by_sentiment)} | top events: {top or '—'}"
        )


def classify_events(
    *,
    classifier=classify,
    limit: int | None = None,
    source: str | None = None,
    reclassify: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
) -> ClassifyReport:
    """
    Classify ``news_events`` rows and persist labels in place (unless dry_run).

    ``classifier(title, content, source)`` is injectable for offline tests.
    """
    now = now or utcnow_naive()
    report = ClassifyReport()
    with session_scope() as session:
        q = session.query(NewsEvent)
        if not reclassify:
            q = q.filter(NewsEvent.event_type.is_(None))
        if source:
            q = q.filter(NewsEvent.source == source)
        q = q.order_by(NewsEvent.id.asc())
        if limit:
            q = q.limit(limit)
        for ev in q.all():
            report.scanned += 1
            try:
                c = classifier(ev.title, ev.content, ev.source)
            except Exception:
                log.exception("classify failed for news id=%s", ev.id)
                report.failed += 1
                continue
            report.by_event[c.event_type] += 1
            report.by_sentiment[c.sentiment] += 1
            report.classified += 1
            if dry_run:
                continue
            ev.event_type = c.event_type
            ev.sentiment = c.sentiment
            ev.classifier_confidence = c.confidence
            ev.classified_at = now
    log.info("%s%s", "[dry-run] " if dry_run else "", report.summary())
    return report


def sample_for_review(n: int = 100, *, seed: int | None = None) -> list[tuple]:
    """
    Return a random sample of classified rows for the manual accuracy check the
    roadmap calls for (N≈100). Each tuple: (ticker, source, event_type,
    sentiment, confidence, title).
    """
    with session_scope() as s:
        rows = s.query(NewsEvent).filter(NewsEvent.event_type.isnot(None)).all()
        data = [
            (r.ticker, r.source, r.event_type, r.sentiment, r.classifier_confidence, r.title)
            for r in rows
        ]
    rng = random.Random(seed)
    rng.shuffle(data)
    return data[:n]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="T-CAT-2 catalyst classifier runner.")
    p.add_argument("--limit", type=int, default=None, help="Max rows to classify this run.")
    p.add_argument("--source", type=str, default=None, help="Only this source (e.g. sec_8k, yfinance).")
    p.add_argument("--reclassify", action="store_true", help="Redo rows even if already classified.")
    p.add_argument("--dry-run", action="store_true", help="Report distribution without writing.")
    p.add_argument("--sample", type=int, default=0, help="Dump N classified rows for manual QA and exit.")
    p.add_argument("--seed", type=int, default=None, help="Seed for --sample shuffling.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.sample:
        rows = sample_for_review(args.sample, seed=args.seed)
        for ticker, src, evt, sent, conf, title in rows:
            c = f"{conf:.2f}" if conf is not None else " -- "
            print(f"{ticker:<6} {src:<14} {evt:<20} {sent:<8} {c}  {title}")
        print(f"\n{len(rows)} sampled — eyeball event_type accuracy here.")
        return 0
    report = classify_events(
        limit=args.limit,
        source=args.source,
        reclassify=args.reclassify,
        dry_run=args.dry_run,
    )
    print(report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
