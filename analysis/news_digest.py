"""
Daily news digest — ranked headlines + optional LLM briefing (UI: Noticias tab).

Read-only consumer of the catalyst pipeline that's already running daily:
harvest (T-CAT-1) → classification (T-CAT-2).
This module does NOT touch the trading hot-path; it only composes those
pieces into a glanceable "what mattered today" view:

1. :func:`fetch_news_window` — pure SELECT over ``news_events`` for a window.
2. :func:`rank_news` — gives each row its **tone** (:func:`tone_level`, −3…+3, from
   the classifier's ``sentiment_score``) and sorts by |tone|, recency as tie-break.
   **Tone is what the news says, not a price forecast** (tarea 258): the tarea 255
   measured that the classifier's sign does not predict the 5-day return
   (``docs/noticias_impacto_t255_2026-10-01.md``). Until a level passes its own
   pre-registered test, nothing here is called *expected impact*. It used to rank by
   ``score_event``, which with no reaction table was a lookup (±0.36 for every
   earnings or FDA headline).
3. Briefing: :func:`make_ollama_briefer` (qwen local, same server the daily
   classifier uses) with :func:`fallback_briefing` as the deterministic,
   offline fallback. The LLM is presentation-layer only — it summarises the
   already-ranked headlines, it never decides the ranking.

Everything is fail-soft and offline-testable (``http_post`` injectable).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from config.logging_config import get_logger

log = get_logger(__name__)

# Same local model the daily classification scheduler uses
# (scripts/daily_catalyst_harvest.bat → --backend hybrid-ollama --model qwen2.5:14b).
DEFAULT_BRIEFING_MODEL = "qwen2.5:14b"
DEFAULT_TOP_N = 50  # rows shown in the table
BRIEFING_HEADLINES = 12  # top rows fed to the LLM

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
    sentiment_score: float | None  # polaridad del clasificador, [−1, +1] (OPS1)
    tone: int  # −3…+3, :func:`tone_level` — tono de la noticia, NO pronóstico (tarea 258)

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
                sentiment_score=r.sentiment_score,
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
    sentiment_score: float | None = None


# ── 1b) Clasificación provisional (display-only) ──────────────────────────────


def classify_missing(rows: Iterable[_Row]) -> list[_Row]:
    """
    Fill in event_type/sentiment/confidence for rows the daily classifier
    hasn't reached yet, using the **heuristic** backend (instant, offline,
    deterministic). DISPLAY-ONLY: never writes the DB — the daily runner
    (scripts/classify_catalysts.py, qwen) remains the source of truth and will
    overwrite nothing because these rows stay NULL in ``news_events``.

    Without this, a window full of fresh rows renders as Otro/Neutral/tone 0
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
                    sentiment_score=c.sentiment_score,
                )
            )
        except Exception:
            log.exception("news_digest: heuristic fallback failed for id=%s", r.id)
            out.append(r)
    return out


# ── 2) Ranking ────────────────────────────────────────────────────────────────

TONE_LEVELS = 3  # la escala es −3…+3 (pedido de Chapa, tarea 258)
_SENTIMENT_SIGN = {"positive": 1, "negative": -1}


def tone_level(sentiment_score: float | None, sentiment: str | None) -> int:
    """Tono de la noticia en −3…+3: ``round(3 × sentiment_score)``, redondeando .5 hacia afuera.

    ``sentiment_score`` es la polaridad que devuelve el clasificador desde OPS1 (2026-07-09).
    Las filas clasificadas antes no la tienen: caen a ±1 según ``sentiment`` (0 si neutral o
    sin clasificar), que es lo único que se sabe de ellas.

    **Es el tono, no un pronóstico del precio** (tarea 255: el signo no predice el retorno
    a 5 días). Si un nivel se gana el nombre de impacto, lo dice su propia medición.
    """
    if sentiment_score is not None:
        try:
            x = float(sentiment_score)
        except (TypeError, ValueError):
            x = math.nan
        # NaN se descarta ANTES de recortar: min(1.0, nan) devuelve 1.0 y daba un +3
        if math.isfinite(x) or math.isinf(x):
            x = max(-1.0, min(1.0, x))
            nivel = math.floor(abs(x) * TONE_LEVELS + 0.5)
            return int(math.copysign(nivel, x)) if nivel else 0
    return _SENTIMENT_SIGN.get(sentiment or "", 0)


def rank_news(rows: Iterable, *, top_n: int | None = DEFAULT_TOP_N) -> list[DigestItem]:
    """
    Le da a cada fila su tono y ordena por |tono| descendente (recencia como desempate).
    Los titulares duplicados (mismo ticker + título desde varios feeds) dejan una sola
    copia: la de tono más fuerte y, a igual tono, la de mayor confianza. Nunca levanta.
    """
    items = [
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
            sentiment_score=getattr(r, "sentiment_score", None),
            tone=tone_level(getattr(r, "sentiment_score", None), r.sentiment),
        )
        for r in rows
    ]

    def _fuerza(it: DigestItem) -> tuple[int, float]:
        return abs(it.tone), it.classifier_confidence or 0.0

    best: dict[tuple[str, str], DigestItem] = {}
    for it in items:
        key = (it.ticker, " ".join(it.title.lower().split()))
        prev = best.get(key)
        if prev is None or _fuerza(it) > _fuerza(prev):
            best[key] = it

    def _sort_key(it: DigestItem):
        # NOTA: nada de datetime.min.timestamp() — en Windows timestamp() de
        # fechas pre-epoch tira OSError 22. Sin fecha → -inf (al final del empate).
        ts = it.published_at.timestamp() if it.published_at else float("-inf")
        return (-abs(it.tone), -ts)

    ranked = sorted(best.values(), key=_sort_key)
    return ranked[:top_n] if top_n else ranked


# ── 3) Briefing ───────────────────────────────────────────────────────────────

_BRIEFING_SYSTEM = (
    "Sos un analista financiero que escribe el briefing matinal de un porfolio. "
    "Recibís los titulares del día ordenados por la intensidad de su tono (de -3, muy "
    "negativa para la empresa, a +3, muy positiva), con categoría y sentimiento. El tono "
    "dice qué cuenta la noticia, no adónde va a ir el precio: no lo presentes como "
    "pronóstico. Escribí UN solo párrafo en español "
    "rioplatense (4-7 oraciones), sobrio y concreto: qué pasó, a qué tickers "
    "afecta y qué conviene mirar hoy. No inventes datos que no estén en los "
    "titulares, no des recomendaciones de compra/venta, no uses listas ni títulos."
)


def briefing_prompt(items: Sequence[DigestItem], max_items: int = BRIEFING_HEADLINES) -> str:
    """User-prompt with the top headlines, one per line. Pure / testable."""
    lines = []
    for it in items[:max_items]:
        when = it.published_at.strftime("%Y-%m-%d") if it.published_at else "s/f"
        lines.append(
            f"[{it.tone:+d}] {it.ticker} · {it.event_label} · {it.sentiment_label} · {when} · {it.title}"
        )
    return "Titulares del día (tono de -3 a +3 entre corchetes):\n" + "\n".join(lines)


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
        f"Tono más fuerte: {top.ticker} — {top.title} "
        f"({top.event_label}, {top.sentiment_label.lower()}, tono {top.tone:+d}). "
        f"(Briefing IA no disponible — resumen automático.)"
    )


def default_window(days: int = 1, *, now: datetime | None = None) -> tuple[datetime, datetime]:
    """[now - days, now] — helper so the UI and tests agree on the window."""
    now = now or datetime.utcnow()
    return now - timedelta(days=days), now


# ── 4) In-app daily refresh (PaperScheduler trigger) ─────────────────────────
#
# Las noticias dan ventaja DURANTE el día. Estos helpers soportan el trigger in-app
# —que desde el 2026-07-12 es el único: no queda ninguna tarea del Task Scheduler
# de Windows (tarea 240)— (mismo
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
        return s.query(NewsEvent.id).filter(NewsEvent.fetched_at >= start).first() is not None


def unclassified_count() -> int:
    """Cuántas filas siguen sin clasificar (event_type NULL)."""
    from database.models import NewsEvent, session_scope

    with session_scope() as s:
        return int(s.query(NewsEvent.id).filter(NewsEvent.event_type.is_(None)).count())


def refresh_due(*, now: datetime | None = None) -> bool:
    """¿Hace falta correr el pipeline? Sí si hoy no se cosechó o hay backlog."""
    try:
        return (not harvested_today(now=now)) or unclassified_count() > 0
    except Exception:
        log.exception("news_digest: refresh_due check failed")
        return False


def run_catalyst_harvest_only(*, harvest_main=None) -> dict:
    """
    Corre SOLO el harvest (T-CAT-1) in-process, sin classify — para el harvest
    horario in-app del PaperScheduler (tarea 10): noticias frescas durante RTH
    sin tocar la GPU cada hora. El classify pesado corre 1x/día, en el refresh
    diario in-app (el Task Scheduler de las 15:00 ya no existe, tarea 240).

    Mismas fuentes que el .bat (yfinance, sec, finnhub — el collector de
    finnhub se saltea solo si falta FINNHUB_API_KEY). ``harvest_main``
    inyectable para tests offline. Devuelve {"harvest_rc": int}; nunca lanza.
    """
    if harvest_main is None:
        from scripts.harvest_catalysts import main as harvest_main

    try:
        harvest_rc = int(harvest_main(["--sources", "yfinance,sec,finnhub"]))
    except Exception:
        log.exception("hourly catalyst harvest: crashed")
        harvest_rc = -1
    return {"harvest_rc": harvest_rc}


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
        # Mismas fuentes que el .bat nocturno / el harvest horario (finnhub
        # incluido; se saltea solo sin API key). Alineado 2026-07-12 al mover
        # todo el scheduling in-app y remover la tarea de Windows.
        harvest_rc = int(harvest_main(["--sources", "yfinance,sec,finnhub"]))
    except Exception:
        log.exception("catalyst refresh: harvest crashed")
        harvest_rc = -1
    try:
        classify_rc = int(classify_main(["--backend", "hybrid-ollama", "--model", model]))
    except Exception:
        log.exception("catalyst refresh: classify crashed")
        classify_rc = -1
    return {"harvest_rc": harvest_rc, "classify_rc": classify_rc}
