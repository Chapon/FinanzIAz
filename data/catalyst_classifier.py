"""
Catalyst classifier (Sprint 5 · T-CAT-2).

Tags a news item with ``{event_type, sentiment, confidence}`` over the 17
categories in :mod:`data.catalyst_taxonomy`. Two backends share one signature
``classify(title, content, source) -> Classification`` so they're swappable:

- **heuristic** (default, this module): deterministic, free, offline, fully
  unit-testable. For SEC 8-K it reads the structured item codes → high
  confidence; for free-text headlines it falls back to keyword cues.
- **LLM** (optional): :func:`make_llm_backend` returns a callable that asks an
  Anthropic model for the same labels. Lazy-imports ``anthropic`` and is only
  used if you wire it in explicitly — the harvester/CLI default to heuristic so
  nothing breaks without an API key. The LLM must return labels from the SAME
  taxonomy; results are validated and fall back to ``other``/``neutral`` on drift.

Design mirrors the collectors: a backend never raises into the caller, and the
classifier is a pure function of (title, content, source).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from config.logging_config import get_logger
from data.catalyst_taxonomy import (
    EVENT_TYPE_SET,
    EVENT_KEYWORDS,
    ITEM_CODE_EVENT,
    ITEM_CODE_SENTIMENT,
    SENTIMENT_KEYWORDS,
    SENTIMENT_SET,
    event_priority,
    extract_item_codes,
    normalize,
)

log = get_logger(__name__)


@dataclass(frozen=True)
class Classification:
    event_type: str
    sentiment: str
    confidence: float
    classifier: str = "heuristic"  # provenance tag (not persisted; for logs/sampling)


# Backend signature: (title, content, source) -> Classification
Backend = Callable[[str, "str | None", str], Classification]

# Confidence tiers
_CONF_SEC_ITEM = 0.90   # structured 8-K item code → event_type
_CONF_KEYWORD = 0.60    # headline keyword cue
_CONF_NONE = 0.20       # no cue → other/neutral


# ── Heuristic backend ────────────────────────────────────────────────────────


def _classify_sec(content: str | None) -> tuple[str, str, float] | None:
    """If 8-K item codes are present, map the most material one. Else None."""
    codes = extract_item_codes(content)
    mapped = [(ITEM_CODE_EVENT[c], c) for c in codes if c in ITEM_CODE_EVENT]
    if not mapped:
        return None
    event, code = min(mapped, key=lambda pair: event_priority(pair[0]))
    # sentiment: explicit per-item override if any of the codes is unambiguous
    sentiment = "neutral"
    for _evt, c in mapped:
        if c in ITEM_CODE_SENTIMENT:
            sentiment = ITEM_CODE_SENTIMENT[c]
            break
    return event, sentiment, _CONF_SEC_ITEM


def _match_event_keyword(text: str) -> str | None:
    """First event_type (materiality order) whose any cue is in ``text``."""
    for event_type, cues in EVENT_KEYWORDS:
        for cue in cues:
            if cue in text:
                return event_type
    return None


def _score_sentiment(text: str) -> str:
    """Majority of positive/negative cue hits; ties / no hits → neutral."""
    pos = sum(1 for w in SENTIMENT_KEYWORDS["positive"] if w in text)
    neg = sum(1 for w in SENTIMENT_KEYWORDS["negative"] if w in text)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def heuristic_classify(title: str, content: str | None, source: str) -> Classification:
    """
    Deterministic classifier. SEC 8-K → structured item-code mapping (high
    confidence); otherwise keyword cues over the headline+summary text.
    Never raises.
    """
    try:
        # 1) SEC structured path
        if source == "sec_8k":
            sec = _classify_sec(content)
            if sec is not None:
                event, sentiment, conf = sec
                return Classification(event, sentiment, conf, "heuristic")

        text = normalize(f"{title} {content or ''}")
        event = _match_event_keyword(text)
        sentiment = _score_sentiment(text)
        if event is None:
            return Classification("other", sentiment, _CONF_NONE, "heuristic")
        return Classification(event, sentiment, _CONF_KEYWORD, "heuristic")
    except Exception:
        log.exception("heuristic_classify failed for %r", title)
        return Classification("other", "neutral", _CONF_NONE, "heuristic")


# ── Public entry point ───────────────────────────────────────────────────────


def classify(title: str, content: str | None, source: str, *, backend: Backend | None = None) -> Classification:
    """
    Classify one item. ``backend`` defaults to the heuristic; pass an LLM backend
    (see :func:`make_llm_backend`) to swap. A backend that raises or returns an
    off-taxonomy label is coerced to a safe ``other``/``neutral`` result.
    """
    backend = backend or heuristic_classify
    try:
        c = backend(title, content, source)
    except Exception:
        log.exception("classifier backend failed for %r — falling back", title)
        return Classification("other", "neutral", _CONF_NONE, "fallback")
    return _coerce(c)


def _coerce(c: Classification) -> Classification:
    """Guard against backends returning labels outside the taxonomy."""
    event = c.event_type if c.event_type in EVENT_TYPE_SET else "other"
    sentiment = c.sentiment if c.sentiment in SENTIMENT_SET else "neutral"
    try:
        conf = float(c.confidence)
    except (TypeError, ValueError):
        conf = _CONF_NONE
    conf = min(1.0, max(0.0, conf))
    if event == c.event_type and sentiment == c.sentiment and conf == c.confidence:
        return c
    return Classification(event, sentiment, conf, c.classifier)


# ── Optional LLM backend (lazy, off by default) ──────────────────────────────

_LLM_SYSTEM = (
    "You are a financial news classifier. Given a headline and optional summary "
    "for a stock ticker, return ONLY a compact JSON object: "
    '{"event_type": <one of the allowed types>, "sentiment": '
    '"positive"|"neutral"|"negative", "confidence": 0..1}. '
    "Allowed event_type values: %s. Pick the single most material one."
)


def make_llm_backend(client=None, model: str = "claude-haiku-4-5-20251001") -> Backend:
    """
    Build an LLM-backed classifier callable. Lazy-imports ``anthropic`` only when
    first invoked, so importing this module never pulls the dep. If no client/key
    is available it logs and falls back to the heuristic — it never raises.

    Wire it in explicitly, e.g.::

        from data.catalyst_classifier import make_llm_backend, classify
        backend = make_llm_backend()
        c = classify(title, content, source, backend=backend)
    """
    from data.catalyst_taxonomy import EVENT_TYPES

    system = _LLM_SYSTEM % ", ".join(EVENT_TYPES)

    def _backend(title: str, content: str | None, source: str) -> Classification:
        nonlocal client
        try:
            if client is None:
                import anthropic  # type: ignore

                client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
            user = f"Ticker headline: {title}\nSummary: {content or '(none)'}\nSource: {source}"
            resp = client.messages.create(
                model=model,
                max_tokens=120,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(getattr(b, "text", "") for b in resp.content)
            return _parse_llm_json(text)
        except Exception:
            log.exception("LLM backend failed for %r — falling back to heuristic", title)
            return heuristic_classify(title, content, source)

    return _backend


def _parse_llm_json(text: str) -> Classification:
    """Extract the JSON object from a model reply; coercion happens in classify()."""
    import json
    import re

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return Classification("other", "neutral", _CONF_NONE, "llm")
    data = json.loads(m.group(0))
    return Classification(
        str(data.get("event_type", "other")),
        str(data.get("sentiment", "neutral")),
        float(data.get("confidence", 0.5)),
        "llm",
    )
