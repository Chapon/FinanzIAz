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
    by_classifier: Counter = field(default_factory=Counter)  # T7.4: provenance
    llm_fallbacks: int = 0  # T7.5: filas que esperaban LLM y cayeron al heuristic

    def summary(self) -> str:
        top = ", ".join(f"{k}={v}" for k, v in self.by_event.most_common(5))
        line = (
            f"Classify: scanned {self.scanned} | classified {self.classified} "
            f"| failed {self.failed} | backend {dict(self.by_classifier)} "
            f"| sentiment {dict(self.by_sentiment)} | top events: {top or '—'}"
        )
        if self.llm_fallbacks:
            # Token grep-able desde el log del scheduler (T7.5).
            line += f"\nLLM_FALLBACKS={self.llm_fallbacks} — ¿Ollama caído? Revisar 'backend failed' arriba."
        return line


def classify_events(
    *,
    classifier=classify,
    limit: int | None = None,
    source: str | None = None,
    reclassify: bool = False,
    max_confidence: float | None = None,
    dry_run: bool = False,
    show: bool = False,
    now: datetime | None = None,
    llm_tag: str | None = None,
    llm_exempt_sources: frozenset[str] = frozenset({"sec_8k"}),
) -> ClassifyReport:
    """
    Classify ``news_events`` rows and persist labels in place (unless dry_run).

    ``classifier(title, content, source, ticker)`` is injectable for offline
    tests. Row selection:
      - default: only unclassified rows (``event_type IS NULL``);
      - ``reclassify``: every row (optionally narrowed by ``source``);
      - ``max_confidence``: only rows already labeled with
        ``classifier_confidence <= max_confidence`` — handy to LLM-upgrade just
        the low-confidence ("other") rows cheaply. Takes precedence over
        ``reclassify`` (a warning is logged if both are passed).

    T7.5 — ``llm_tag``: tag de provenance esperado cuando se corre con un
    backend LLM ("ollama" / "llm"). Una fila cuyo ``classifier`` difiere del
    tag esperado cayó al fallback heurístico (backend caído) y se cuenta en
    ``report.llm_fallbacks``. ``llm_exempt_sources`` excluye las fuentes que
    los backends hybrid rutean al heuristic POR DISEÑO (sec_8k) — pasar
    ``frozenset()`` para backends puros (ollama/llm sin hybrid).
    """
    now = now or utcnow_naive()
    report = ClassifyReport()
    if max_confidence is not None and reclassify:
        log.warning(
            "--max-confidence takes precedence over --reclassify: only rows with "
            "classifier_confidence <= %s will be redone (unclassified rows excluded).",
            max_confidence,
        )
    with session_scope() as session:
        q = session.query(NewsEvent)
        if max_confidence is not None:
            q = q.filter(NewsEvent.classifier_confidence <= max_confidence)
        elif not reclassify:
            q = q.filter(NewsEvent.event_type.is_(None))
        if source:
            q = q.filter(NewsEvent.source == source)
        q = q.order_by(NewsEvent.id.asc())
        if limit:
            q = q.limit(limit)
        for ev in q.all():
            report.scanned += 1
            try:
                c = classifier(ev.title, ev.content, ev.source, ev.ticker)
            except Exception:
                log.exception("classify failed for news id=%s", ev.id)
                report.failed += 1
                continue
            report.by_event[c.event_type] += 1
            report.by_sentiment[c.sentiment] += 1
            report.by_classifier[c.classifier] += 1
            if llm_tag and c.classifier != llm_tag and ev.source not in llm_exempt_sources:
                report.llm_fallbacks += 1
            report.classified += 1
            if show:
                print(f"  {ev.ticker:<6} {c.event_type:<20} {c.sentiment:<8} {c.confidence:.2f}  {ev.title[:72]}")
            if dry_run:
                continue
            ev.event_type = c.event_type
            ev.sentiment = c.sentiment
            ev.classifier_confidence = c.confidence
            ev.classified_at = now
            ev.classified_by = c.classifier  # T7.4: provenance persistida
    log.info("%s%s", "[dry-run] " if dry_run else "", report.summary())
    return report


def sample_for_review(n: int = 100, *, source: str | None = None, seed: int | None = None) -> list[tuple]:
    """
    Return a random sample of classified rows for the manual accuracy check the
    roadmap calls for (N≈100). Optionally restrict to one ``source`` (e.g.
    "yfinance" to eyeball just the headline path). Each tuple: (ticker, source,
    event_type, sentiment, confidence, classified_by, title) — el backend va
    incluido para poder evaluar accuracy POR BACKEND (T7.4).
    """
    with session_scope() as s:
        q = s.query(NewsEvent).filter(NewsEvent.event_type.isnot(None))
        if source:
            q = q.filter(NewsEvent.source == source)
        rows = q.all()
        data = [
            (r.ticker, r.source, r.event_type, r.sentiment, r.classifier_confidence, r.classified_by, r.title)
            for r in rows
        ]
    rng = random.Random(seed)
    rng.shuffle(data)
    return data[:n]


def _build_classifier(backend_name: str, model: str | None):
    """Return the (title, content, source, ticker) classifier for ``backend_name``."""
    if backend_name == "heuristic":
        return classify  # default heuristic backend
    from functools import partial

    from data.catalyst_classifier import make_hybrid_backend, make_llm_backend, make_ollama_backend

    anthropic_model = model or "claude-haiku-4-5-20251001"
    ollama_model = model or "llama3.1"
    if backend_name == "llm":
        backend = make_llm_backend(model=anthropic_model)
    elif backend_name == "ollama":
        backend = make_ollama_backend(model=ollama_model)
    elif backend_name == "hybrid":
        backend = make_hybrid_backend(model=anthropic_model)
    elif backend_name == "hybrid-ollama":
        backend = make_hybrid_backend(llm_backend=make_ollama_backend(model=ollama_model))
    else:
        raise ValueError(f"unknown backend {backend_name!r}")
    return partial(classify, backend=backend)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="T-CAT-2 catalyst classifier runner.")
    p.add_argument("--limit", type=int, default=None, help="Max rows to classify this run.")
    p.add_argument("--source", type=str, default=None, help="Only this source (e.g. sec_8k, yfinance).")
    p.add_argument("--reclassify", action="store_true", help="Redo rows even if already classified.")
    p.add_argument(
        "--max-confidence",
        type=float,
        default=None,
        help="Only redo already-labeled rows with confidence <= this (e.g. 0.3 to LLM-upgrade the 'other' rows).",
    )
    p.add_argument(
        "--backend",
        choices=["heuristic", "llm", "ollama", "hybrid", "hybrid-ollama"],
        default="heuristic",
        help=(
            "heuristic (free, default) | llm (Anthropic API, paid) | ollama (free local model) "
            "| hybrid (SEC→heuristic, rest→Anthropic) | hybrid-ollama (SEC→heuristic, rest→local Ollama; "
            "free + scheduler-friendly)."
        ),
    )
    p.add_argument(
        "--model",
        default=None,
        help="Model override. Defaults: claude-haiku-4-5-20251001 (llm/hybrid) or llama3.1 (ollama).",
    )
    p.add_argument("--dry-run", action="store_true", help="Report distribution without writing.")
    p.add_argument("--show", action="store_true", help="Print each row as it's classified (eyeball the backend live).")
    p.add_argument("--sample", type=int, default=0, help="Dump N classified rows for manual QA and exit.")
    p.add_argument("--seed", type=int, default=None, help="Seed for --sample shuffling.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.sample:
        rows = sample_for_review(args.sample, source=args.source, seed=args.seed)
        for ticker, src, evt, sent, conf, by, title in rows:
            c = f"{conf:.2f}" if conf is not None else " -- "
            print(f"{ticker:<6} {src:<14} {evt:<20} {sent:<8} {c} {by or '--':<10} {title}")
        print(f"\n{len(rows)} sampled — eyeball event_type accuracy here.")
        return 0
    classifier = _build_classifier(args.backend, args.model)
    if args.backend != "heuristic":
        log.info("classifying with %s backend (model=%s)", args.backend, args.model)
    # T7.5: tag esperado por backend para detectar fallbacks. Los hybrid rutean
    # sec_8k al heuristic por diseño → exento; los puros no exentan nada.
    _LLM_TAGS = {"ollama": "ollama", "hybrid-ollama": "ollama", "llm": "llm", "hybrid": "llm"}
    llm_tag = _LLM_TAGS.get(args.backend)
    exempt = frozenset({"sec_8k"}) if args.backend.startswith("hybrid") else frozenset()
    report = classify_events(
        classifier=classifier,
        limit=args.limit,
        source=args.source,
        reclassify=args.reclassify,
        max_confidence=args.max_confidence,
        dry_run=args.dry_run,
        show=args.show,
        llm_tag=llm_tag,
        llm_exempt_sources=exempt,
    )
    print(report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
