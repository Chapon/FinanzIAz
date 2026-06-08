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
    ("mna", ["to acquire", "acquisition", "merger", "to buy", "takeover", "buyout",
            "agrees to acquire", "in talks to buy", "stake in"]),
    ("clinical_fda", ["fda", "phase 1", "phase 2", "phase 3", "clinical trial", "trial data",
                     "approval", "approves", "drug", "therapy", "endpoint"]),
    ("legal_regulatory", ["lawsuit", "sues", "investigation", "probe", "subpoena", "fine",
                        "settlement", "antitrust", "sec charges", "delisting", "restatement",
                        "recall"]),
    ("executive_change", ["ceo", "cfo", "steps down", "resigns", "appoints", "names new",
                        "departure", "to retire", "successor"]),
    ("analyst_rating", ["upgrade", "downgrade", "initiates coverage", "price target",
                      "raised to buy", "cut to sell", "reiterates", "overweight", "underweight"]),
    ("product_launch", ["launches", "unveils", "introduces", "new product", "rolls out",
                      "announces the", "debut"]),
    ("partnership_contract", ["partnership", "contract", "deal with", "agreement with",
                           "wins contract", "awarded", "collaborat", "signs"]),
    ("capital_return", ["buyback", "share repurchase", "dividend", "stock split", "special dividend"]),
    ("financing_offering", ["offering", "raises capital", "convertible notes", "secondary offering",
                         "debt offering", "public offering", "private placement", "files to sell"]),
    ("insider_activity", ["insider", "ceo buys", "ceo sells", "insider buying", "insider selling",
                       "10b5-1", "form 4"]),
    ("restructuring", ["layoffs", "cuts jobs", "restructuring", "impairment", "writedown",
                    "bankruptcy", "chapter 11", "shuts down", "exit"]),
    ("macro_sector", ["fed", "inflation", "tariff", "interest rate", "sector", "market selloff",
                   "rally", "jobs report"]),
    ("stock_movement", ["soars", "plunges", "jumps", "tumbles", "rallies", "slumps",
                     "spikes", "why .* stock", "stock plummeted", "stock popped"]),
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
