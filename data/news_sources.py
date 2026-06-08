"""
News + analyst-estimate collectors for the Catalyst Intelligence Engine
(Sprint 5 · T-CAT-0).

This module is the *ingest* layer. It turns raw provider payloads into plain
dataclasses (``NewsItem`` / ``EstimateSnapshot``) plus a stable ``content_hash``
for dedup. It does NOT touch the database — the orchestrator
(``scripts/harvest_catalysts.py``) is responsible for persistence and
idempotency. Keeping it side-effect-free makes the parsers unit-testable
offline with recorded fixtures.

Sources wired today (T-CAT-1: full MVP)
---------------------------------------
- yfinance ``Ticker.news``            → NewsItem  (free, default dep)
- yfinance estimates / recommendations /
  analyst_price_targets               → EstimateSnapshot (snapshotted daily)
- SEC 8-K via EDGAR ``submissions``   → NewsItem  (free, the most reliable
  point-in-time source; ``filingDate`` is the official disclosure date)
- generic RSS (Yahoo per-ticker headline feed by default; PR Newswire /
  Business Wire / GlobeNewswire via ``CATALYST_EXTRA_FEEDS``) → NewsItem,
  parsed with ``feedparser`` if installed; silently skipped if not.

Source selection is by token set: ``{"yfinance"}`` (default), plus ``"sec"``
and/or ``"rss"``. The harvester CLI maps ``--sources yfinance,sec,rss`` here.

SEC etiquette: EDGAR requires a descriptive ``User-Agent`` with a contact
address. Set ``SEC_EDGAR_USER_AGENT`` (e.g. "FinanzIAs you@example.com") or the
default UA is sent — SEC may throttle anonymous-looking agents. Keep the daily
cadence well under EDGAR's 10 req/s ceiling (the harvester is sequential).

Every collector is defensive: a failing source returns [] and logs, it never
raises into the caller (same contract as ``yahoo_finance.get_analyst_data``).
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from config.logging_config import get_logger

log = get_logger(__name__)


# ── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NewsItem:
    ticker: str
    title: str
    source: str
    content: str | None = None
    url: str | None = None
    published_at: datetime | None = None

    def content_hash(self) -> str:
        return content_hash(self.ticker, self.title, self.published_at)


@dataclass(frozen=True)
class EstimateSnapshot:
    ticker: str
    metric: str  # "eps", "revenue", "rec_mean", "price_target"
    period_label: str | None = None  # "0q","+1q","0y","+1y" o "2026-09"
    consensus_value: float | None = None
    num_analysts: int | None = None


@dataclass
class _CollectResult:
    news: list[NewsItem] = field(default_factory=list)
    estimates: list[EstimateSnapshot] = field(default_factory=list)


# ── Dedup hash ───────────────────────────────────────────────────────────────


_WS_RE = re.compile(r"\s+")


def _norm_title(title: str) -> str:
    """Lowercase + collapse whitespace so trivial formatting diffs hash equal."""
    return _WS_RE.sub(" ", (title or "").strip().lower())


def content_hash(ticker: str, title: str, published_at: datetime | None) -> str:
    """
    Stable sha1 over (ticker, normalized title, published hour).

    published_at is rounded to the hour to absorb sub-hour timestamp jitter
    between repeated fetches of the same article. If it's missing we fall back
    to the UTC date so two same-day fetches of an undated headline still
    collide instead of duplicating.
    """
    if published_at is not None:
        stamp = published_at.strftime("%Y-%m-%d-%H")
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw = f"{ticker.upper()}|{_norm_title(title)}|{stamp}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# ── yfinance news ────────────────────────────────────────────────────────────


def _epoch_to_dt(epoch) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


def _parse_iso(value) -> datetime | None:
    if not value:
        return None
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        return None


def parse_yf_news_item(ticker: str, raw: dict) -> NewsItem | None:
    """
    Map one ``yfinance.Ticker.news`` entry to a NewsItem.

    yfinance has shipped two shapes:
      - legacy flat: {title, link, publisher, providerPublishTime (epoch)}
      - newer nested: {id, content: {title, summary, pubDate,
                        canonicalUrl:{url}, provider:{displayName}}}
    Handle both. Returns None if there's no usable title.
    """
    if not isinstance(raw, dict):
        return None

    # newer nested shape
    if "content" in raw and isinstance(raw["content"], dict):
        c = raw["content"]
        title = c.get("title")
        if not title:
            return None
        url = (c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict) else c.get("link")
        published = _parse_iso(c.get("pubDate") or c.get("displayTime"))
        return NewsItem(
            ticker=ticker.upper(),
            title=title,
            source="yfinance",
            content=c.get("summary"),
            url=url,
            published_at=published,
        )

    # legacy flat shape
    title = raw.get("title")
    if not title:
        return None
    return NewsItem(
        ticker=ticker.upper(),
        title=title,
        source="yfinance",
        content=raw.get("summary"),
        url=raw.get("link"),
        published_at=_epoch_to_dt(raw.get("providerPublishTime")),
    )


def collect_yfinance_news(ticker: str) -> list[NewsItem]:
    """Fetch ``Ticker.news`` and map to NewsItems. Never raises."""
    out: list[NewsItem] = []
    try:
        from data.yahoo_finance import _ticker  # reuse the configured session/rate-limit

        raw_list = getattr(_ticker(ticker), "news", None) or []
        for raw in raw_list:
            item = parse_yf_news_item(ticker, raw)
            if item is not None:
                out.append(item)
    except Exception:
        log.exception("yfinance news fetch failed for %s", ticker)
    return out


# ── yfinance analyst estimates (daily snapshot) ──────────────────────────────


def _df_rows_to_estimates(ticker: str, df, metric: str) -> list[EstimateSnapshot]:
    """
    yfinance ``earnings_estimate`` / ``revenue_estimate`` are DataFrames indexed
    by period ("0q","+1q","0y","+1y") with an 'avg' and 'numberOfAnalysts'
    column. Map each row to an EstimateSnapshot. Defensive against shape drift.
    """
    out: list[EstimateSnapshot] = []
    try:
        if df is None or getattr(df, "empty", True):
            return out
        for period, row in df.iterrows():
            avg = _safe_float(row.get("avg") if hasattr(row, "get") else None)
            n = _safe_int(row.get("numberOfAnalysts") if hasattr(row, "get") else None)
            if avg is None and n is None:
                continue
            out.append(
                EstimateSnapshot(
                    ticker=ticker.upper(),
                    metric=metric,
                    period_label=str(period),
                    consensus_value=avg,
                    num_analysts=n,
                )
            )
    except Exception:
        log.exception("estimate dataframe parse failed for %s/%s", ticker, metric)
    return out


def collect_yfinance_estimates(ticker: str) -> list[EstimateSnapshot]:
    """
    Snapshot the *current* consensus for ``ticker``: EPS + revenue estimates,
    recommendation mean, and price target. Never raises. One call per ticker
    per day is the intended cadence (the harvester enforces it).
    """
    out: list[EstimateSnapshot] = []
    try:
        from data.yahoo_finance import _ticker

        t = _ticker(ticker)

        out.extend(_df_rows_to_estimates(ticker, _getattr(t, "earnings_estimate"), "eps"))
        out.extend(_df_rows_to_estimates(ticker, _getattr(t, "revenue_estimate"), "revenue"))

        # recommendation mean (single scalar) — from analyst_price_targets/info
        pt = _getattr(t, "analyst_price_targets")
        if isinstance(pt, dict):
            mean = _safe_float(pt.get("mean"))
            if mean is not None:
                out.append(EstimateSnapshot(ticker.upper(), "price_target", "current", mean, None))

        info = _getattr(t, "info") or {}
        if isinstance(info, dict):
            rec_mean = _safe_float(info.get("recommendationMean"))
            n = _safe_int(info.get("numberOfAnalystOpinions"))
            if rec_mean is not None:
                out.append(EstimateSnapshot(ticker.upper(), "rec_mean", "current", rec_mean, n))
    except Exception:
        log.exception("yfinance estimates fetch failed for %s", ticker)
    return out


# ── Per-ticker RSS (Yahoo by default, others via env) ────────────────────────


def yahoo_rss_url(ticker: str) -> str:
    """Yahoo Finance's free per-symbol headline RSS feed."""
    return f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker.upper()}&region=US&lang=en-US"


def default_feed_urls(ticker: str) -> list[str]:
    """
    Free per-ticker RSS feed URLs for ``ticker``.

    Yahoo's per-symbol headline feed is the only reliably free *per-ticker* feed
    (PR Newswire / Business Wire / GlobeNewswire don't expose stable per-ticker
    feeds without a key). Extra feeds can be supplied via the
    ``CATALYST_EXTRA_FEEDS`` env var — a comma-separated list of URL templates
    with a ``{ticker}`` placeholder, e.g.
    ``https://www.example.com/rss?symbol={ticker}``.
    """
    urls = [yahoo_rss_url(ticker)]
    extra = os.environ.get("CATALYST_EXTRA_FEEDS", "")
    for tmpl in (s.strip() for s in extra.split(",") if s.strip()):
        try:
            urls.append(tmpl.format(ticker=ticker.upper()))
        except Exception:
            log.warning("bad CATALYST_EXTRA_FEEDS template skipped: %r", tmpl)
    return urls


def _rss_source_label(url: str) -> str:
    """Map a feed URL to a friendly source tag for ``news_events.source``."""
    u = (url or "").lower()
    if "yahoo" in u:
        return "yahoo_rss"
    if "businesswire" in u:
        return "businesswire_rss"
    if "prnewswire" in u:
        return "prnewswire_rss"
    if "globenewswire" in u:
        return "globenewswire_rss"
    return "rss"


def collect_rss(ticker: str, feed_urls: list[str], source: str | None = None) -> list[NewsItem]:
    """
    Generic RSS collector (Yahoo per-ticker / PR Newswire / Business Wire / …).

    Requires ``feedparser`` (optional dep). If it's not installed, logs once and
    returns [] so the MVP keeps running on yfinance + SEC alone. Caller decides
    which feed URLs to pass. When ``source`` is None the source tag is inferred
    from each feed's URL (see ``_rss_source_label``).
    """
    out: list[NewsItem] = []
    try:
        import feedparser  # type: ignore
    except Exception:
        log.info("feedparser not installed — RSS source skipped for %s", ticker)
        return out
    for url in feed_urls or []:
        src = source or _rss_source_label(url)
        try:
            parsed = feedparser.parse(url)
            for entry in getattr(parsed, "entries", []):
                title = entry.get("title")
                if not title:
                    continue
                published = None
                if entry.get("published_parsed"):
                    try:
                        published = datetime(*entry["published_parsed"][:6])
                    except Exception:
                        published = None
                out.append(
                    NewsItem(
                        ticker=ticker.upper(),
                        title=title,
                        source=src,
                        content=entry.get("summary"),
                        url=entry.get("link"),
                        published_at=published,
                    )
                )
        except Exception:
            log.exception("RSS parse failed for %s (%s)", ticker, url)
    return out


# ── SEC 8-K via EDGAR (point-in-time, the most reliable source) ──────────────

SEC_DATA_BASE = "https://data.sec.gov"
SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_DEFAULT_SEC_UA = "FinanzIAs Catalyst Harvester (set SEC_EDGAR_USER_AGENT with a contact email)"

# Form 8-K item codes → human-readable labels. Used to build a meaningful
# headline ("AAPL 8-K: Results of Operations and Financial Condition") instead
# of an opaque accession number. Covers the items that actually move prices.
EDGAR_8K_ITEM_LABELS: dict[str, str] = {
    "1.01": "Entry into a Material Definitive Agreement",
    "1.02": "Termination of a Material Definitive Agreement",
    "1.03": "Bankruptcy or Receivership",
    "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.02": "Results of Operations and Financial Condition",
    "2.03": "Creation of a Direct Financial Obligation",
    "2.04": "Triggering Events That Accelerate a Direct Financial Obligation",
    "2.05": "Costs Associated with Exit or Disposal Activities",
    "2.06": "Material Impairments",
    "3.01": "Notice of Delisting or Failure to Satisfy a Listing Rule",
    "3.02": "Unregistered Sales of Equity Securities",
    "3.03": "Material Modification to Rights of Security Holders",
    "4.01": "Changes in Registrant's Certifying Accountant",
    "4.02": "Non-Reliance on Previously Issued Financial Statements",
    "5.01": "Changes in Control of Registrant",
    "5.02": "Departure/Election of Directors or Principal Officers",
    "5.03": "Amendments to Articles of Incorporation or Bylaws",
    "5.07": "Submission of Matters to a Vote of Security Holders",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}

# Module-level cache of the ticker→CIK map (it's ~1 MB, rarely changes; one
# fetch per process is plenty). ``None`` = not loaded yet.
_CIK_MAP_CACHE: dict[str, int] | None = None


def parse_company_tickers(payload) -> dict[str, int]:
    """
    Map EDGAR ``company_tickers.json`` → ``{TICKER: cik_int}``.

    The payload is a dict keyed by stringified row indices, each row being
    ``{"cik_str": int, "ticker": str, "title": str}``. Defensive against shape
    drift (also accepts a plain iterable of such rows).
    """
    out: dict[str, int] = {}
    try:
        rows = payload.values() if isinstance(payload, dict) else payload
        for row in rows:
            if not isinstance(row, dict):
                continue
            t = row.get("ticker")
            cik = row.get("cik_str")
            if t and cik is not None:
                out[str(t).upper()] = int(cik)
    except Exception:
        log.exception("parse_company_tickers failed")
    return out


def _edgar_filing_url(cik: int, accession: str, primary_doc: str | None) -> str:
    """Build the public EDGAR Archives URL for a filing."""
    nodash = (accession or "").replace("-", "")
    if primary_doc:
        return f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{primary_doc}"
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{accession}-index.htm"


def _format_8k_title(ticker: str, item_codes: list[str]) -> str:
    """Human headline from 8-K item codes."""
    if item_codes:
        labels = [EDGAR_8K_ITEM_LABELS.get(code, code) for code in item_codes]
        return f"{ticker} 8-K: " + "; ".join(labels)
    return f"{ticker} 8-K filed"


def parse_edgar_submissions(
    ticker: str,
    payload: dict,
    *,
    cik: int | None = None,
    forms: tuple[str, ...] = ("8-K",),
    max_filings: int | None = 20,
) -> list[NewsItem]:
    """
    Map an EDGAR ``submissions/CIK##########.json`` payload to NewsItems.

    Reads only ``filings.recent`` (the trailing ~1 year / 1000 filings — more
    than enough for daily catalyst harvesting). Keeps filings whose ``form`` is
    in ``forms`` (default 8-K), newest first as EDGAR returns them, capped at
    ``max_filings``. ``published_at`` is the official ``filingDate`` → genuinely
    point-in-time. Pure function: no network, fully unit-testable.
    """
    out: list[NewsItem] = []
    try:
        cik = cik if cik is not None else payload.get("cik")
        recent = (payload.get("filings") or {}).get("recent") or {}
        forms_list = recent.get("form") or []
        dates = recent.get("filingDate") or []
        accns = recent.get("accessionNumber") or []
        items_col = recent.get("items") or []
        primary = recent.get("primaryDocument") or []
        descs = recent.get("primaryDocDescription") or []
        wanted = set(forms)
        kept = 0
        for i, form in enumerate(forms_list):
            if form not in wanted:
                continue
            filing_date = _parse_iso(dates[i]) if i < len(dates) else None
            accession = accns[i] if i < len(accns) else ""
            raw_items = items_col[i] if i < len(items_col) else ""
            item_codes = [s.strip() for s in str(raw_items).split(",") if s.strip()]
            pdoc = primary[i] if i < len(primary) else None
            desc = descs[i] if i < len(descs) else None
            content_parts = []
            if item_codes:
                content_parts.append("Items: " + ", ".join(item_codes))
            if desc:
                content_parts.append(str(desc))
            out.append(
                NewsItem(
                    ticker=ticker.upper(),
                    title=_format_8k_title(ticker.upper(), item_codes),
                    source="sec_8k",
                    content="; ".join(content_parts) or None,
                    url=_edgar_filing_url(int(cik), accession, pdoc) if cik is not None else None,
                    published_at=filing_date,
                )
            )
            kept += 1
            if max_filings and kept >= max_filings:
                break
    except Exception:
        log.exception("parse_edgar_submissions failed for %s", ticker)
    return out


def _sec_session():
    """A ``requests.Session`` with the SEC-required descriptive User-Agent."""
    import requests

    s = requests.Session()
    ua = os.environ.get("SEC_EDGAR_USER_AGENT") or _DEFAULT_SEC_UA
    s.headers.update({"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
    return s


def fetch_cik_map(session=None) -> dict[str, int]:
    """
    Fetch + cache the EDGAR ticker→CIK map. Returns {} on failure (never raises).
    """
    global _CIK_MAP_CACHE
    if _CIK_MAP_CACHE is not None:
        return _CIK_MAP_CACHE
    try:
        sess = session or _sec_session()
        r = sess.get(SEC_TICKER_MAP_URL, timeout=20)
        r.raise_for_status()
        _CIK_MAP_CACHE = parse_company_tickers(r.json())
    except Exception:
        log.exception("fetch_cik_map failed")
        _CIK_MAP_CACHE = {}
    return _CIK_MAP_CACHE


def cik_for_ticker(ticker: str, mapping: dict[str, int] | None = None) -> int | None:
    """Resolve ``ticker`` → CIK int, using a provided map or the cached one."""
    m = mapping if mapping is not None else fetch_cik_map()
    return m.get(ticker.upper())


def collect_sec_8k(
    ticker: str,
    *,
    session=None,
    mapping: dict[str, int] | None = None,
    max_filings: int = 20,
) -> list[NewsItem]:
    """
    Fetch recent 8-K filings for ``ticker`` from EDGAR and map to NewsItems.

    The most reliable point-in-time source: ``filingDate`` is the official SEC
    disclosure date. Resolves the CIK via the cached ticker map, then reads
    ``submissions/CIK##########.json``. Never raises — a missing CIK or a failed
    request returns [].
    """
    try:
        cik = cik_for_ticker(ticker, mapping)
        if cik is None:
            log.info("no CIK for %s — SEC 8-K skipped", ticker)
            return []
        sess = session or _sec_session()
        url = f"{SEC_DATA_BASE}/submissions/CIK{cik:010d}.json"
        r = sess.get(url, timeout=20)
        r.raise_for_status()
        return parse_edgar_submissions(ticker, r.json(), cik=cik, max_filings=max_filings)
    except Exception:
        log.exception("collect_sec_8k failed for %s", ticker)
        return []


# ── Default combined collector ───────────────────────────────────────────────


def collect_all(ticker: str, sources: set[str] | None = None) -> _CollectResult:
    """
    Run the enabled sources for one ticker and return combined news + estimates.
    Default sources = {"yfinance"} (news + estimates). Pass e.g.
    {"yfinance", "sec", "rss"} to enable more. Each source is independently
    guarded — one failing source never sinks the others.
    """
    sources = sources or {"yfinance"}
    res = _CollectResult()
    if "yfinance" in sources:
        res.news.extend(collect_yfinance_news(ticker))
        res.estimates.extend(collect_yfinance_estimates(ticker))
    if "sec" in sources:
        res.news.extend(collect_sec_8k(ticker))
    if "rss" in sources:
        res.news.extend(collect_rss(ticker, default_feed_urls(ticker)))
    return res


# ── small helpers ────────────────────────────────────────────────────────────


def _getattr(obj, name):
    try:
        return getattr(obj, name, None)
    except Exception:
        # yfinance lazily fetches some properties on access; tolerate failures.
        return None


def _safe_float(v) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if f == f else None  # drop NaN
    except Exception:
        return None


def _safe_int(v) -> int | None:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None
