"""
Daily news digest — ranked headlines + optional LLM briefing (UI: Noticias tab).

Read-only consumer of the catalyst pipeline that's already running daily:
harvest (T-CAT-1) → classification (T-CAT-2) → impact scoring (T-CAT-4).
This module does NOT touch the trading hot-path; it only composes those
pieces into a glanceable "what mattered today" view:

1. :func:`fetch_news_window` — pure SELECT over ``news_events`` for a window.
2. :func:`rank_news` — scores each row with :func:`analysis.impact_score.score_event`
   and sorts by |impact| (conviction), recency as tie-break. With no reaction
   table / market cap (the UI default) the score degrades gracefully to
   event-type prior × sentiment × confidence — deterministic and instant.
3. Briefing: :func:`make_ollama_briefer` (qwen local, same server the daily
   classifier uses) with :func:`fallback_briefing` as the deterministic,
   offline fallback. The LLM is presentation-layer only — it summarises the
   already-ranked headlines, it never decides the ranking.

Everything is fail-soft and offline-testable (``http_post`` injectable).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable, Sequence

from config.logging_config import get_logger

log = get_logger(__name__)

# Same local model the daily classification scheduler uses
# (scripts/daily_catalyst_harvest.bat → --backend hybrid-ollama --model qwen2.5:14b).
DEFAULT_BRIEFING_MODEL = "qwen2.5:14b"
DEFAULT_TOP_N = 50          # rows shown in the table
BRIEFING_HEADLINES = 12     # top rows fed to the LLM

# Spanish labels for the taxonomy (UI display only; keys = data.catalyst_taxonomy)
EVENT_LABELS_ES: dict[str, str] = {
    "earnings_results": "Resultados",
    "guidance_raise": "Sube guidance",
    "guidance_cut": "Baja guidance",
    "mna": "M&A",
    "clinical_fda": "Clínico/FDA",
    "legal_regulatory": "Legal/Regulatorio",
    "restructuring": "Reestructuración",
    "analyst_rating": "Rating analista",
    "product_launch": "Lanzamiento",
    "capital_return": "Retorno de capital",
    "partnership_contract": "Acuerdo/Contrato",
    "executive_change": "Cambio directivo",
    "financing_offering": "Financiamiento",
    "insider_activity": "Insiders",
    "macro_sector": "Macro/Sector",
    "stock_movement": "Movimiento de precio",
    "other": "Otro",
}

SENTIMENT_LABELS_ES = {"positive": "Positivo", "neutral": "Neutral", "negative": "Negativo"}


@dataclass(frozen=True)
class DigestItem:
    """One ranked headline, ready for the UI table."""

    news_id: int
    ticker: str
    title: str
    source: str
    url: str | None
    published_at: datetime | None
    event_type: str | None
    sentiment: str | None
    classifier_confidence: float | None
    impact: float          # signed score_event().value — sign = expected direction
    direction: int         # -1 | 0 | +1
    basis: str             # "reaction" | "prior"

    @property
    def event_label(self) -> str:
        return EVENT_LABELS_ES.get(self.event_type or "other", self.event_type or "Otro")

    @property
    def sentiment_label(self) -> str:
        return SENTIMENT_LABELS_ES.get(self.sentiment or "neutral", "Neutral")


# ── 1) Window query (read-only) ───────────────────────────────────────────────


def fetch_news_window(
    since: datetime,
    *,
    until: datetime | None = None,
    tickers: Sequence[str] | None = None,
) -> list:
    """
    ``news_events`` rows in the window, newest first. Read-only.

    A row is "in the window" if ``published_at`` falls inside it, or — for rows
    the source didn't date — if we *saw* it inside it (``fetched_at``). Returns
    detached plain rows (the session closes here, mirroring news_feed.py).
    """
    from sqlalchemy import and_, or_

    from database.models import NewsEvent, session_scope

    with session_scope() as s:
        q = s.query(NewsEvent)
        dated = NewsEvent.published_at >= since
        undated = and_(NewsEvent.published_at.is_(None), NewsEvent.fetched_at >= since)
        if until is not None:
            dated = and_(dated, NewsEvent.published_at <= until)
            undated = and_(
                NewsEvent.published_at.is_(None),
                NewsEvent.fetched_at >= since,
                NewsEvent.fetched_at <= until,
            )
        q = q.filter(or_(dated, undated))
        if tickers:
            q = q.filter(NewsEvent.ticker.in_([t.upper() for t in tickers]))
        q = q.order_by(
            NewsEvent.published_at.is_(None),
            NewsEvent.published_at.desc(),
            NewsEvent.id.desc(),
        )
        rows = q.all()
        return [
            _Row(
                id=r.id,
                ticker=r.ticker,
                title=r.title,
                source=r.source,
                url=r.url,
                published_at=r.published_at,
                event_type=r.event_type,
                sentiment=r.sentiment,
                classifier_confidence=r.classifier_confidence,
            )
            for r in rows
        ]


@dataclass(frozen=True)
class _Row:
    """Detached, ORM-free row — what rank_news consumes (easy to fake in tests)."""

    id: int
    ticker: str
    title: str
    source: str
    url: str | None
    published_at: datetime | None
    event_type: str | None
    sentiment: str | None
    classifier_confidence: float | None


# ── 1b) Clasificación provisional (display-only) ──────────────────────────────


def classify_missing(rows: Iterable[_Row]) -> list[_Row]:
    """
    Fill in event_type/sentiment/confidence for rows the daily classifier
    hasn't reached yet, using the **heuristic** backend (instant, offline,
    deterministic). DISPLAY-ONLY: never writes the DB — the daily runner
    (scripts/classify_catalysts.py, qwen) remains the source of truth and will
    overwrite nothing because these rows stay NULL in ``news_events``.

    Without this, a window full of fresh rows renders as Otro/Neutral/impact 0
    whenever the tab is opened before the nightly classification ran.
    """
    from data.catalyst_classifier import heuristic_classify

    out: list[_Row] = []
    for r in rows:
        if r.event_type is not None:
            out.append(r)
            continue
        try:
            c = heuristic_classify(r.title, None, r.source, r.ticker)
            out.append(
                _Row(
                    id=r.id,
                    ticker=r.ticker,
                    title=r.title,
                    source=r.source,
                    url=r.url,
                    published_at=r.published_at,
                    event_type=c.event_type,
                    sentiment=c.sentiment,
                    classifier_confidence=c.confidence,
                )
            )
        except Exception:
            log.exception("news_digest: heuristic fallback failed for id=%s", r.id)
            out.append(r)
    return out


# ── 2) Ranking ────────────────────────────────────────────────────────────────


def rank_news(
    rows: Iterable,
    *,
    reaction_table: dict | None = None,
    market_cap_loader: "Callable[[str], float | None] | None" = None,
    top_n: int | None = DEFAULT_TOP_N,
) -> list[DigestItem]:
    """
    Score each row with ``score_event`` and rank by |impact| desc (recency breaks
    ties). Duplicate headlines (same ticker+title from several feeds) keep only
    the best-scored copy. Never raises; a row that fails to score gets 0.0.

    ``reaction_table`` / ``market_cap_loader`` are optional richness hooks —
    the UI passes None today (prior-based ranking), the same inputs T-CAT-4
    uses are accepted so the panel upgrades for free when we wire them.
    """
    from analysis.impact_score import score_event

    items: list[DigestItem] = []
    for r in rows:
        mcap = None
        if market_cap_loader is not None:
            try:
                mcap = market_cap_loader(r.ticker)
            except Exception:
                log.exception("news_digest: market_cap_loader failed for %s", r.ticker)
        try:
            sc = score_event(
                r.ticker,
                r.event_type,
                r.sentiment,
                r.classifier_confidence,
                reaction_table=reaction_table,
                headline=r.title,
                market_cap=mcap,
            )
            impact, direction, basis = sc.value, sc.direction, sc.basis
        except Exception:
            log.exception("news_digest: score_event failed for news id=%s", getattr(r, "id", "?"))
            impact, direction, basis = 0.0, 0, "prior"
        items.append(
            DigestItem(
                news_id=r.id,
                ticker=r.ticker,
                title=r.title,
                source=r.source,
                url=r.url,
                published_at=r.published_at,
                event_type=r.event_type,
                sentiment=r.sentiment,
                classifier_confidence=r.classifier_confidence,
                impact=float(impact),
                direction=int(direction),
                basis=basis,
            )
        )

    # de-dup (ticker, normalized title) keeping the highest |impact|
    best: dict[tuple[str, str], DigestItem] = {}
    for it in items:
        key = (it.ticker, " ".join(it.title.lower().split()))
        prev = best.get(key)
        if prev is None or abs(it.impact) > abs(prev.impact):
            best[key] = it

    def _sort_key(it: DigestItem):
        # NOTA: nada de datetime.min.timestamp() — en Windows timestamp() de
        # fechas pre-epoch tira OSError 22. Sin fecha → -inf (al final del empate).
        ts = it.published_at.timestamp() if it.published_at else float("-inf")
        return (-abs(it.impact), -ts)

    ranked = sorted(best.values(), key=_sort_key)
    return ranked[:top_n] if top_n else ranked


# ── 3) Briefing ───────────────────────────────────────────────────────────────

_BRIEFING_SYSTEM = (
    "Sos un analista financiero que escribe el briefing matinal de un porfolio. "
    "Recibís los titulares más relevantes del día (ya rankeados por impacto "
    "esperado, con categoría y sentimiento). Escribí UN solo párrafo en español "
    "rioplatense (4-7 oraciones), sobrio y concreto: qué pasó, a qué tickers "
    "afecta y qué conviene mirar hoy. No inventes datos que no estén en los "
    "titulares, no des recomendaciones de compra/venta, no uses listas ni títulos."
)


def briefing_prompt(items: Sequence[DigestItem], max_items: int = BRIEFING_HEADLINES) -> str:
    """User-prompt with the top headlines, one per line. Pure / testable."""
    lines = []
    for it in items[:max_items]:
        when = it.published_at.strftime("%Y-%m-%d") if it.published_at else "s/f"
        sign = "+" if it.impact > 0 else ("-" if it.impact < 0 else "·")
        lines.append(
            f"[{sign}|{abs(it.impact):.2f}] {it.ticker} · {it.event_label} · "
            f"{it.sentiment_label} · {when} · {it.title}"
        )
    return "Titulares del día (impacto esperado entre corchetes):\n" + "\n".join(lines)


# Briefer signature: (items) -> str | None  (None = unavailable, UI falls back)
Briefer = Callable[[Sequence[DigestItem]], "str | None"]


def make_ollama_briefer(
    model: str = DEFAULT_BRIEFING_MODEL,
    host: str | None = None,
    *,
    http_post=None,
    timeout: int = 120,
) -> Briefer:
    """
    Briefer backed by the local Ollama server (same one the daily classifier
    uses — free, unattended, no key). Returns None on ANY failure so the caller
    can show :func:`fallback_briefing` instead. ``http_post`` injectable for
    offline tests, mirroring ``make_ollama_backend``.
    """
    import os

    base = (host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")

    def _briefer(items: Sequence[DigestItem]) -> str | None:
        if not items:
            return None
        try:
            poster = http_post
            if poster is None:
                import requests

                poster = requests.post
            resp = poster(
                f"{base}/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "options": {"temperature": 0.3},
                    "messages": [
                        {"role": "system", "content": _BRIEFING_SYSTEM},
                        {"role": "user", "content": briefing_prompt(items)},
                    ],
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            text = ((data.get("message") or {}).get("content", "") or "").strip()
            return text or None
        except Exception:
            log.exception("news_digest: Ollama briefer failed — UI will use fallback")
            return None

    return _briefer


def fallback_briefing(items: Sequence[DigestItem]) -> str:
    """
    Deterministic, offline one-paragraph summary for when the LLM isn't up.
    Counts + top movers — boring but always correct.
    """
    if not items:
        return "Sin noticias en la ventana seleccionada."
    sents = Counter(it.sentiment or "neutral" for it in items)
    cats = Counter(it.event_label for it in items)
    top = items[0]
    top_cats = ", ".join(f"{name} ({n})" for name, n in cats.most_common(3))
    return (
        f"{len(items)} noticias en la ventana: {sents.get('positive', 0)} positivas, "
        f"{sents.get('negative', 0)} negativas, {sents.get('neutral', 0)} neutrales. "
        f"Categorías principales: {top_cats}. "
        f"Mayor impacto esperado: {top.ticker} — {top.title} "
        f"({top.event_label}, {top.sentiment_label.lower()}, score {top.impact:+.2f}). "
        f"(Briefing IA no disponible — resumen automático.)"
    )


def default_window(days: int = 1, *, now: datetime | None = None) -> tuple[datetime, datetime]:
    """[now - days, now] — helper so the UI and tests agree on the window."""
    now = now or datetime.utcnow()
    return now - timedelta(days=days), now


# ── 4) In-app daily refresh (PaperScheduler trigger) ─────────────────────────
#
# Las noticias dan ventaja DURANTE el día, pero el Task Scheduler de Windows
# corre a las ~18:30 ART. Estos helpers soportan el trigger in-app (mismo
# patrón que el surprise rebuild semanal): la primera vez que la app abre en
# el día, lanza harvest + classify en un worker. Todo idempotente: el
# harvester de-dupea por content_hash y el classifier solo toca filas NULL.

DEFAULT_CLASSIFY_MODEL = DEFAULT_BRIEFING_MODEL  # qwen2.5:14b — mismo del .bat


def harvested_today(*, now: datetime | None = None) -> bool:
    """True si ya hay al menos una fila cosechada hoy (fetched_at, UTC)."""
    from database.models import NewsEvent, session_scope

    now = now or datetime.utcnow()
    start = datetime(now.year, now.month, now.day)
    with session_scope() as s:
        return (
            s.query(NewsEvent.id).filter(NewsEvent.fetched_at >= start).first()
            is not None
        )


def unclassified_count() -> int:
    """Cuántas filas siguen sin clasificar (event_type NULL)."""
    from database.models import NewsEvent, session_scope

    with session_scope() as s:
        return int(
            s.query(NewsEvent.id).filter(NewsEvent.event_type.is_(None)).count()
        )


def refresh_due(*, now: datetime | None = None) -> bool:
    """¿Hace falta correr el pipeline? Sí si hoy no se cosechó o hay backlog."""
    try:
        return (not harvested_today(now=now)) or unclassified_count() > 0
    except Exception:
        log.exception("news_digest: refresh_due check failed")
        return False


def run_catalyst_refresh(
    *,
    model: str = DEFAULT_CLASSIFY_MODEL,
    harvest_main=None,
    classify_main=None,
) -> dict:
    """
    Corre harvest (T-CAT-1) + classify (T-CAT-2) in-process, con los mismos
    argumentos del .bat nocturno. Pensado para un QThread del PaperScheduler.
    ``harvest_main`` / ``classify_main`` inyectables para tests offline.

    Devuelve {"harvest_rc": int, "classify_rc": int}; el harvest que falla NO
    aborta el classify (puede haber backlog previo clasificable igual).
    """
    if harvest_main is None:
        from scripts.harvest_catalysts import main as harvest_main
    if classify_main is None:
        from scripts.classify_catalysts import main as classify_main

    try:
        harvest_rc = int(harvest_main(["--sources", "yfinance,sec"]))
    except Exception:
        log.exception("catalyst refresh: harvest crashed")
        harvest_rc = -1
    try:
        classify_rc = int(classify_main(["--backend", "hybrid-ollama", "--model", model]))
    except Exception:
        log.exception("catalyst refresh: classify crashed")
        classify_rc = -1
    return {"harvest_rc": harvest_rc, "classify_rc": classify_rc}
