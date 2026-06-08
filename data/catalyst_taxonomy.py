"""
Catalyst taxonomy for the Catalyst Intelligence Engine (Sprint 5 · T-CAT-2).

A single source of truth for the **17 event categories** and the 3 sentiment
labels, plus two deterministic lookup tables used by the heuristic classifier:

- ``ITEM_CODE_EVENT`` / ``ITEM_CODE_SENTIMENT`` — map SEC 8-K item codes
  (structured, official data) straight to an event_type / sentiment. This is
  the high-confidence path: a filing tagged "2.02" *is* an earnings result.
- ``EVENT_KEYWORDS`` / ``SENTIMENT_KEYWORDS`` — keyword cues for free-text
  headlines (yfinance / RSS) where there's no structured signal.

Pure data + helpers, no third-party deps, so the classifier stays unit-testable
offline. The LLM backend (T-CAT-2 optional) classifies into the SAME label set.
"""

from __future__ import annotations

import re

# ── The 17 event categories ──────────────────────────────────────────────────
# Ordered by materiality: when several cues match, the classifier keeps the
# earliest one in this list. Keep ``other`` last as the catch-all.
EVENT_TYPES: tuple[str, ...] = (
    "earnings_results",     # quarterly/annual results, EPS/revenue prints
    "guidance_raise",       # forward guidance raised / above-consensus outlook
    "guidance_cut",         # forward guidance lowered / warning
    "mna",                  # merger, acquisition, takeover, change of control
    "clinical_fda",         # drug trial, FDA decision, approval/rejection
    "legal_regulatory",     # lawsuit, investigation, fine, delisting, restatement
    "executive_change",     # CEO/CFO/director departure or appointment
    "analyst_rating",       # upgrade / downgrade / initiation / price target
    "product_launch",       # new product, launch, unveiling
    "partnership_contract", # contract win, partnership, material agreement
    "capital_return",       # buyback, dividend, stock split
    "financing_offering",   # debt/equity offering, capital raise, loan
    "insider_activity",     # insider buy/sell, 10b5-1
    "restructuring",        # layoffs, impairment, exit/disposal, bankruptcy
    "macro_sector",         # macro/sector-wide news hitting the name
    "stock_movement",       # generic price-move / technical commentary (low signal)
    "other",                # everything else
)
EVENT_TYPE_SET = frozenset(EVENT_TYPES)

SENTIMENTS: tuple[str, ...] = ("positive", "neutral", "negative")
SENTIMENT_SET = frozenset(SENTIMENTS)


# ── SEC 8-K item code → event_type (the high-confidence structured path) ─────
# https://www.sec.gov/fast-answers/answersform8khtm.html
ITEM_CODE_EVENT: dict[str, str] = {
    "1.01": "partnership_contract",  # entry into a material definitive agreement
    "1.02": "restructuring",         # termination of a material agreement
    "1.03": "restructuring",         # bankruptcy or receivership
    "2.01": "mna",                   # completion of acquisition/disposition
    "2.02": "earnings_results",      # results of operations & financial condition
    "2.03": "financing_offering",    # creation of a direct financial obligation
    "2.04": "financing_offering",    # triggering events accelerating an obligation
    "2.05": "restructuring",         # costs associated with exit/disposal
    "2.06": "restructuring",         # material impairments
    "3.01": "legal_regulatory",      # notice of delisting
    "3.02": "financing_offering",    # unregistered sales of equity
    "3.03": "other",                 # modification to security holder rights
    "4.01": "other",                 # change in certifying accountant
    "4.02": "legal_regulatory",      # non-reliance on prior financials (restatement)
    "5.01": "mna",                   # changes in control of registrant
    "5.02": "executive_change",      # departure/election of directors or officers
    "5.03": "other",                 # amendments to articles/bylaws
    "5.07": "other",                 # submission of matters to a shareholder vote
    "7.01": "other",                 # Regulation FD disclosure
    "8.01": "other",                 # other events
    "9.01": "other",                 # financial statements & exhibits
}

# Item codes whose sentiment is unambiguous from the filing type alone. Anything
# not listed defaults to neutral (a filing is factual; beat-vs-miss needs text).
ITEM_CODE_SENTIMENT: dict[str, str] = {
    "1.03": "negative",  # bankruptcy
    "2.06": "negative",  # impairment
    "3.01": "negative",  # delisting
    "4.02": "negative",  # restatement
}

# Materiality priority for picking among multiple 8-K item codes (lower = more
# material). Falls back to EVENT_TYPES order for anything unlisted.
_ITEM_PRIORITY = {
    "earnings_results": 0,
    "mna": 1,
    "clinical_fda": 2,
    "executive_change": 3,
    "legal_regulatory": 4,
    "restructuring": 5,
    "financing_offering": 6,
    "partnership_contract": 7,
    "capital_return": 8,
    "other": 99,
}


def event_priority(event_type: str) -> int:
    """Lower = more material. Used to choose among competing cues."""
    if event_type in _ITEM_PRIORITY:
        return _ITEM_PRIORITY[event_type]
    try:
        return 10 + EVENT_TYPES.index(event_type)
    except ValueError:
        return 999


# ── Keyword cues for free-text headlines ─────────────────────────────────────
# Each (event_type, [phrases]) — matched case-insensitively as word-ish
# substrings. Checked in EVENT_TYPES (materiality) order; first hit wins.
EVENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("earnings_results", ["earnings", "q1 results", "q2 results", "q3 results", "q4 results",
                          "quarterly results", "reports eps", "beats on revenue", "misses on revenue",
                          "tops estimates", "misses estimates", "reports earnings"]),
    ("guidance_raise", ["raises guidance", "raises outlook", "boosts forecast", "lifts guidance",
                        "raises full-year", "above consensus", "raises fy"]),
    ("guidance_cut", ["cuts guidance", "lowers guidance", "slashes outlook", "warns on",
                     "profit warning", "cuts forecast", "lowers outlook", "guidance cut"]),
    ("mna", ["to acquire", "acquires", "acquisition of", "merger", "to merge with",
            "agrees to buy", "takeover", "buyout", "agrees to acquire", "in talks to buy"]),
    ("clinical_fda", ["fda", "phase 1", "phase 2", "phase 3", "clinical trial", "trial data",
                     "drug approval", "fda approval", "therapy", "endpoint met", "topline data"]),
    ("legal_regulatory", ["lawsuit", "sues", "investigation", "probe", "subpoena", "antitrust",
                        "sec charges", "delisting", "restatement", "recall", "settlement"]),
    ("executive_change", ["new ceo", "new cfo", "ceo steps down", "cfo steps down", "resigns",
                        "appoints", "names new", "to retire", "ceo departure", "ceo shift"]),
    ("analyst_rating", ["upgrade", "upgraded", "downgrade", "downgraded", "initiates coverage",
                      "price target", "target on", "raises target", "lowers target",
                      "raised to buy", "cut to sell", "buy rating", "sell rating",
                      "overweight", "underweight"]),
    ("product_launch", ["launches", "unveils", "introduces", "new product", "rolls out", "debut"]),
    ("partnership_contract", ["partnership", "wins contract", "awarded contract", "signs deal",
                           "signs agreement", "agreement with", "deal with", "collaborat"]),
    ("capital_return", ["buyback", "share repurchase", "dividend hike", "raises dividend",
                     "stock split", "special dividend"]),
    ("financing_offering", ["stock offering", "share offering", "public offering", "debt offering",
                         "secondary offering", "convertible notes", "private placement",
                         "files to sell", "capital raise", "raises capital"]),
    ("insider_activity", ["insider buying", "insider selling", "insiders sold", "insiders bought",
                       "ceo buys", "ceo sells", "10b5-1", "form 4"]),
    ("restructuring", ["layoffs", "cuts jobs", "restructuring", "impairment", "writedown",
                    "bankruptcy", "chapter 11", "shuts down"]),
    ("macro_sector", ["fed", "inflation", "tariff", "interest rate", "sector update", "market selloff",
                   "sector bloodbath", "jobs report", "rate hike", "rate cut"]),
    ("stock_movement", ["soars", "plunges", "tumbles", "slumps", "spikes", "plummeted",
                     "stock pops", "stock popped", "nosedive", "nosediving"]),
]

SENTIMENT_KEYWORDS: dict[str, list[str]] = {
    "positive": ["beat", "beats", "tops", "surge", "soars", "jumps", "rallies", "spikes",
                "wins", "raises", "boosts", "approval", "approves", "upgrade", "record",
                "strong", "exceeds", "popped", "gains", "rises", "buyback", "dividend hike"],
    "negative": ["miss", "misses", "plunge", "plummet", "tumbles", "slumps", "falls", "drops",
                "lawsuit", "sues", "downgrade", "cuts", "slashes", "warning", "warns", "recall",
                "delay", "bankruptcy", "probe", "investigation", "layoffs", "impairment",
                "weak", "disappoints", "halts"],
}

_WORD_RE = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    """Lowercase + collapse whitespace for stable substring matching."""
    return _WORD_RE.sub(" ", (text or "").strip().lower())


_ITEM_IN_CONTENT = re.compile(r"\b(\d\.\d{2})\b")


def extract_item_codes(content: str | None) -> list[str]:
    """
    Pull 8-K item codes (e.g. '2.02', '9.01') out of a NewsEvent.content string
    such as 'Items: 2.02, 9.01; ...'. Returns [] if none found.
    """
    if not content:
        return []
    return _ITEM_IN_CONTENT.findall(content)


# ── Word-boundary cue matching ───────────────────────────────────────────────
# Substring matching produced false positives ("offering" inside other words,
# "cuts" inside "haircuts"). Match whole phrases with word boundaries instead;
# internal spaces match any run of whitespace.


def _compile_phrase(phrase: str) -> "re.Pattern[str]":
    parts = [re.escape(w) for w in phrase.split()]
    return re.compile(r"\b" + r"\s+".join(parts) + r"\b")


EVENT_KEYWORD_RES: list[tuple[str, list]] = [
    (event_type, [_compile_phrase(c) for c in cues]) for event_type, cues in EVENT_KEYWORDS
]
SENTIMENT_KEYWORD_RES: dict[str, list] = {
    label: [_compile_phrase(w) for w in words] for label, words in SENTIMENT_KEYWORDS.items()
}


def match_event(text: str) -> str | None:
    """First event_type (materiality order) with a word-boundary cue hit in ``text``."""
    for event_type, regexes in EVENT_KEYWORD_RES:
        if any(r.search(text) for r in regexes):
            return event_type
    return None


def score_sentiment(text: str) -> str:
    """Majority of positive/negative cue hits; ties / none → neutral."""
    pos = sum(1 for r in SENTIMENT_KEYWORD_RES["positive"] if r.search(text))
    neg = sum(1 for r in SENTIMENT_KEYWORD_RES["negative"] if r.search(text))
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"
