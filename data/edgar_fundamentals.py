"""
Hard accounting facts from SEC EDGAR XBRL ``companyfacts`` (E1b — universe
quality screen).

Why EDGAR and not yfinance snapshots
------------------------------------
The universe screen needs to tell a fragile pre-revenue clinical biotech
(MLTX, −89.9 %) apart from a profitable large-cap. yfinance's
``trailingEps`` / financials are moving snapshots that can be stale or missing
per ticker. EDGAR XBRL exposes the *filed* numbers (10-K / 20-F) — point-in-time
hard facts — so ``NetIncomeLoss`` and ``Revenues`` come straight from the audited
statements. Chapa's data-quality rule (2026-06-25) picks the harder-but-better
source here.

This module is the *ingest + parse* layer, mirroring ``data.news_sources``:

- ``fetch_company_facts``    — one HTTP GET to ``data.sec.gov`` (reuses the SEC
  User-Agent session and cached ticker→CIK map already built for the 8-K
  collector). Never raises → returns ``None`` on any failure.
- ``parse_fundamental_facts`` — a pure function turning the raw payload into a
  small ``FundamentalFacts`` dataclass (recent annual net income + revenue).
  No network, fully unit-testable with recorded fixtures.
- ``get_fundamental_facts``  — fetch + parse with a per-process cache (facts
  change quarterly at most; one fetch per ticker per session is plenty).

The screen decision itself lives in ``paper_trading.universe`` — this module
only produces the facts, it does not judge them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from config.logging_config import get_logger

log = get_logger(__name__)

# us-gaap concept for bottom-line profit. Negative across years + no revenue is
# the signature of a cash-burning clinical-stage name.
NET_INCOME_CONCEPT = "NetIncomeLoss"

# Revenue concept names drift across companies / filing eras. Try them in order
# and take the first that yields annual data.
REVENUE_CONCEPTS: tuple[str, ...] = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
)

_ANNUAL_FRAME_RE = re.compile(r"^CY\d{4}$")


@dataclass(frozen=True)
class FundamentalFacts:
    """Recent annual hard facts for one ticker, most-recent-year first.

    Each series is a tuple of ``(period_end_iso, value_usd)``. Empty tuples mean
    "no data" — callers must fail open (never exclude a name on missing facts).
    """

    ticker: str
    net_income_annual: tuple[tuple[str, float], ...] = ()
    revenue_annual: tuple[tuple[str, float], ...] = ()

    @property
    def net_income_recent(self) -> list[float]:
        """Net income values, most-recent-year first (drops period ends)."""
        return [v for _, v in self.net_income_annual]

    @property
    def revenue_latest(self) -> float | None:
        """Most recent annual revenue, or ``None`` when unknown."""
        return self.revenue_annual[0][1] if self.revenue_annual else None

    @property
    def has_data(self) -> bool:
        return bool(self.net_income_annual) or bool(self.revenue_annual)


def _has_frame(entry: dict) -> bool:
    frame = entry.get("frame")
    return isinstance(frame, str) and bool(_ANNUAL_FRAME_RE.match(frame))


def _looks_annual(entry: dict) -> bool:
    """True iff an XBRL fact entry covers a full fiscal year.

    Priority signals (any one suffices):
    * a calendar-year duration ``frame`` like ``CY2023`` (no ``Q`` → annual);
    * ``fp == "FY"`` on a 10-K / 20-F / 40-F filing;
    * a start→end span of ~1 year with ``fp == "FY"`` (frame-less fallback).
    Quarterly (``CY2023Q1``), instant (``CY2023Q4I``) and interim entries are
    rejected so we never mix a quarter into an "annual" series.
    """
    if _has_frame(entry):
        return True
    fp = entry.get("fp")
    if fp != "FY":
        return False
    form = str(entry.get("form") or "")
    if form.startswith("10-K") or form.startswith("20-F") or form.startswith("40-F"):
        return True
    start, end = entry.get("start"), entry.get("end")
    if isinstance(start, str) and isinstance(end, str):
        try:
            span = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days
            if 330 <= span <= 400:
                return True
        except ValueError:
            pass
    return False


def _annual_series(entries, max_years: int) -> tuple[tuple[str, float], ...]:
    """Collapse raw USD unit entries into one annual value per fiscal-year end.

    Dedupes by the ``end`` date (the annual period is uniquely identified by its
    fiscal-year end), preferring the framed value when a period has both a
    framed and an unframed entry (the framed number is the authoritative
    calendar-year figure). Returns ``(end, val)`` sorted most-recent-first,
    truncated to ``max_years``.
    """
    best: dict[str, tuple[float, bool]] = {}
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        val, end = e.get("val"), e.get("end")
        if val is None or not isinstance(end, str):
            continue
        if not _looks_annual(e):
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        framed = _has_frame(e)
        cur = best.get(end)
        if cur is None or (framed and not cur[1]):
            best[end] = (fval, framed)
    ordered = sorted(((end, v) for end, (v, _) in best.items()), reverse=True)
    return tuple(ordered[:max_years])


def parse_fundamental_facts(
    payload: dict | None,
    ticker: str = "",
    *,
    max_years: int = 4,
) -> FundamentalFacts:
    """Pure: raw ``companyfacts`` payload → ``FundamentalFacts``.

    Reads only ``facts.us-gaap.{NetIncomeLoss, <revenue concept>}`` in USD.
    Never raises — any shape drift degrades to empty series (→ fail open).
    """
    try:
        gaap = ((payload or {}).get("facts") or {}).get("us-gaap") or {}
        ni_units = ((gaap.get(NET_INCOME_CONCEPT) or {}).get("units") or {}).get("USD")
        net_income = _annual_series(ni_units, max_years)
        revenue: tuple[tuple[str, float], ...] = ()
        for concept in REVENUE_CONCEPTS:
            node = gaap.get(concept)
            if not node:
                continue
            rev_units = (node.get("units") or {}).get("USD")
            revenue = _annual_series(rev_units, max_years)
            if revenue:
                break
        return FundamentalFacts(
            ticker=ticker or str((payload or {}).get("entityName") or ""),
            net_income_annual=net_income,
            revenue_annual=revenue,
        )
    except Exception:
        log.exception("parse_fundamental_facts failed for %s", ticker)
        return FundamentalFacts(ticker=ticker)


def fetch_company_facts(ticker: str, *, session=None, mapping: dict | None = None) -> dict | None:
    """Fetch the raw ``companyfacts`` JSON for ``ticker`` from EDGAR.

    Reuses the SEC User-Agent session and cached ticker→CIK map from
    ``data.news_sources``. Returns ``None`` (never raises) when the CIK is
    unknown or the request fails.
    """
    try:
        from data.news_sources import SEC_DATA_BASE, _sec_session, cik_for_ticker

        cik = cik_for_ticker(ticker, mapping)
        if cik is None:
            log.info("no CIK for %s — EDGAR fundamentals skipped", ticker)
            return None
        sess = session or _sec_session()
        url = f"{SEC_DATA_BASE}/api/xbrl/companyfacts/CIK{cik:010d}.json"
        r = sess.get(url, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception:
        log.exception("fetch_company_facts failed for %s", ticker)
        return None


# Per-process cache: fundamentals change quarterly at most, so one fetch per
# ticker per app session is plenty. ``None`` values are cached too (a name with
# no CIK / failed fetch stays "unknown" → the screen fails open for it).
_FACTS_CACHE: dict[str, FundamentalFacts] = {}


def get_fundamental_facts(
    ticker: str,
    *,
    session=None,
    mapping: dict | None = None,
    max_years: int = 4,
    use_cache: bool = True,
) -> FundamentalFacts:
    """Fetch + parse the annual fundamentals for ``ticker`` (cached per process).

    Always returns a ``FundamentalFacts`` (possibly empty — never ``None``), so
    the screen never has to guard for missing objects: an empty facts object
    simply carries no exclusion evidence → fail open.
    """
    key = ticker.upper()
    if use_cache and key in _FACTS_CACHE:
        return _FACTS_CACHE[key]
    payload = fetch_company_facts(ticker, session=session, mapping=mapping)
    facts = parse_fundamental_facts(payload, ticker=ticker, max_years=max_years)
    if use_cache:
        _FACTS_CACHE[key] = facts
    return facts


def clear_facts_cache() -> None:
    """Drop the per-process fundamentals cache (tests / long-running refresh)."""
    _FACTS_CACHE.clear()


__all__ = [
    "NET_INCOME_CONCEPT",
    "REVENUE_CONCEPTS",
    "FundamentalFacts",
    "clear_facts_cache",
    "fetch_company_facts",
    "get_fundamental_facts",
    "parse_fundamental_facts",
]
