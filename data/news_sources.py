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
- Finnhub ``company-news`` → NewsItem. A free aggregator over dozens of outlets
  (Reuters / CNBC / Bloomberg / …); we keep the originating outlet in the source
  tag as ``finnhub:<Outlet>``. Needs ``FINNHUB_API_KEY``; skipped if unset.

Source selection is by token set: ``{"yfinance"}`` (default), plus ``"sec"``
y/o ``"finnhub"``. The harvester CLI maps ``--sources yfinance,sec,finnhub``
aquí.

**La rama ``rss`` se borró en la tarea 212** (decisión de Chapa 2026-09-21), y no
por prolijidad: ``feedparser`` nunca estuvo instalado ni declarado en
``requirements.txt``, así que ``_rss`` devolvía ``skipped`` **siempre** — era
código que no podía ejecutarse. Medido antes de decidir: sobre 12 tickers del
universo vivo, el feed default de Yahoo trae 211 titulares y **182 (86%) ya
estaban**, traídos por ``yfinance`` + ``finnhub:Yahoo``; y **cero** filas de
``news_events`` usan una fuente rss. Si algún día hacen falta los newswire de
fuente primaria (Business Wire / PR Newswire / GlobeNewswire), se reimplementa
con ese requisito escrito en vez de arrastrar una rama muerta.

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
from datetime import datetime, timedelta, timezone

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
class SourceOutcome:
    """Qué hizo **una** fuente para **un** ticker (tarea 207).

    ``[]`` estaba sobrecargado: significaba a la vez *«respondió y no había nada»*,
    *«falló»* y *«no corrió»*. Cada collector se traga su excepción y devuelve ``[]``
    —correcto y deliberado, una fuente caída no hunde a las otras— así que el reporte
    del harvest no tenía cómo distinguirlas. Las dos corridas de 95 y 82 minutos del
    2026-08-14, con las tres fuentes timeouteando, cerraron con ``failed 0``.

    ``failed`` con ``items > 0`` es un estado real, no una contradicción: una fuente
    puede acumular resultados y **seguir** tras una falla parcial. (El ejemplo que
    tenía escrito acá era ``_rss``, que la tarea 212 borró.)

    ``degraded`` es el cuarto estado y lo agrega la **tarea 210**: la fuente contestó,
    pero **parte** de lo que consulta adentro se cayó. Hasta entonces eso se declaraba
    ``ok`` —``_yf_estimates`` lee cuatro propiedades a través de ``_getattr``, que se
    traga la excepción de cada una— y por eso el 2026-08-14 ``yfinance_news`` registró
    52 fallas de 52 y ``yfinance_estimates`` **ninguna**. El ``detail`` **nombra** qué
    se cayó, que es lo que convierte "algo anda mal" en algo accionable.

    **``degraded`` NO cuenta como falla para la alarma, y esa decisión es deliberada.**
    ``SOURCE_FAILURE_ALARM_RATE`` se calibró en la 207 contra una población donde una
    falla por sub-propiedad era **invisible**, así que esa población no dice nada sobre
    cuántos ``degraded`` tiene un día sano — exactamente el caso de ``cero_resultados``,
    que la 207 dejó como contexto por la misma razón. Meterlo al gate sería inventar un
    umbral en vez de calibrarlo. Se reporta aparte y se decide cuando haya población.
    """

    source: str
    status: str  # "ok" | "degraded" | "failed" | "skipped"
    items: int = 0
    detail: str = ""

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    @property
    def skipped(self) -> bool:
        return self.status == "skipped"

    @property
    def degraded(self) -> bool:
        return self.status == "degraded"


@dataclass
class _CollectResult:
    news: list[NewsItem] = field(default_factory=list)
    estimates: list[EstimateSnapshot] = field(default_factory=list)
    # Una entrada por fuente consultada para este ticker (tarea 207). Vacío = nadie
    # declaró nada, que es distinto de "todas respondieron sin novedades".
    outcomes: list[SourceOutcome] = field(default_factory=list)

    @property
    def sources_failed(self) -> list[str]:
        return [o.source for o in self.outcomes if o.failed]

    @property
    def total_items(self) -> int:
        return len(self.news) + len(self.estimates)


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
        url = (
            (c.get("canonicalUrl") or {}).get("url")
            if isinstance(c.get("canonicalUrl"), dict)
            else c.get("link")
        )
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


def _yf_news(ticker: str) -> tuple[list[NewsItem], SourceOutcome]:
    """La implementación real: la lista **y** si la fuente respondió (tarea 207)."""
    out: list[NewsItem] = []
    try:
        from data.yahoo_finance import _ticker  # reuse the configured session/rate-limit

        raw_list = getattr(_ticker(ticker), "news", None) or []
        for raw in raw_list:
            item = parse_yf_news_item(ticker, raw)
            if item is not None:
                out.append(item)
    except Exception as e:
        log.exception("yfinance news fetch failed for %s", ticker)
        return out, SourceOutcome("yfinance_news", "failed", len(out), _brief(e))
    return out, SourceOutcome("yfinance_news", "ok", len(out))


def collect_yfinance_news(ticker: str) -> list[NewsItem]:
    """Fetch ``Ticker.news`` and map to NewsItems. Never raises.

    Accesor de una línea sobre ``_yf_news``, que es la única implementación — así el
    resultado y su veredicto no pueden divergir.
    """
    return _yf_news(ticker)[0]


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


#: Cuantas propiedades de yfinance consulta `_yf_estimates` (tarea 210). Se declara
#: para que el `detail` diga "1/4" y no un numero suelto — y porque el docstring que
#: escribio la 207 decia **cinco** y listaba **cuatro**; el enunciado de la 210 heredo
#: el error en un lado y lo corrigio en el otro ("1 de 4" en su kill-criteria).
_SUBFETCHES_DE_ESTIMATES = 4


def _yf_estimates(ticker: str) -> tuple[list[EstimateSnapshot], SourceOutcome]:
    """
    Snapshot the *current* consensus for ``ticker``: EPS + revenue estimates,
    recommendation mean, and price target. Never raises. One call per ticker
    per day is the intended cadence (the harvester enforces it).

    **Qué ve el veredicto** (tareas 207 y 210). El ``try`` de afuera sólo alcanza a lo
    que *escapa*: en la práctica, que ``_ticker()`` no resuelva — y eso sigue siendo
    ``failed``. Los **cuatro** sub-fetches (earnings, revenue, price targets, info) pasan
    por ``_getattr``, **que se traga cada excepción a propósito**, porque yfinance
    fetchea de verdad al acceder a la propiedad y una caída no debe hundir a las otras.

    Hasta la **210** eso significaba que una fuente que contestaba 2 de 4 se declaraba
    ``ok``, y es exactamente lo que se ve en el log del 2026-08-14: ``yfinance_news``
    falló 52 de 52 y ``yfinance_estimates`` no registró **ninguna**. Ahora ``_getattr``
    **anota** lo que levanta —tolerar y ocultar dejaron de ser la misma cosa— y el
    veredicto sale ``degraded`` nombrando qué se cayó. ``degraded`` es contexto y **no**
    entra al gate de ``SOURCE_FAILURE_ALARM_RATE``: ver ``SourceOutcome``.

    **Corrección de esta misma docstring (210):** decía *«los cinco sub-fetches»* y
    listaba **cuatro**. Son cuatro, y ahora lo dice ``_SUBFETCHES_DE_ESTIMATES``, que un
    test compara contra los ``_getattr`` reales de esta función por AST — un número en un
    mensaje que nadie verifica es un número que se pudre.
    """
    out: list[EstimateSnapshot] = []
    # Las propiedades que LEVANTARON, con su motivo (tarea 210). Las que devuelven
    # `None` sin excepcion no entran: eso es un ticker sin ese dato, no una falla.
    caidas: list[str] = []
    try:
        from data.yahoo_finance import _ticker

        t = _ticker(ticker)

        out.extend(_df_rows_to_estimates(ticker, _getattr(t, "earnings_estimate", caidas), "eps"))
        out.extend(_df_rows_to_estimates(ticker, _getattr(t, "revenue_estimate", caidas), "revenue"))

        # recommendation mean (single scalar) — from analyst_price_targets/info
        pt = _getattr(t, "analyst_price_targets", caidas)
        if isinstance(pt, dict):
            mean = _safe_float(pt.get("mean"))
            if mean is not None:
                out.append(EstimateSnapshot(ticker.upper(), "price_target", "current", mean, None))

        info = _getattr(t, "info", caidas) or {}
        if isinstance(info, dict):
            rec_mean = _safe_float(info.get("recommendationMean"))
            n = _safe_int(info.get("numberOfAnalystOpinions"))
            if rec_mean is not None:
                out.append(EstimateSnapshot(ticker.upper(), "rec_mean", "current", rec_mean, n))
    except Exception as e:
        log.exception("yfinance estimates fetch failed for %s", ticker)
        return out, SourceOutcome("yfinance_estimates", "failed", len(out), _brief(e))
    if caidas:
        return out, SourceOutcome(
            "yfinance_estimates",
            "degraded",
            len(out),
            f"{len(caidas)}/{_SUBFETCHES_DE_ESTIMATES} sub-fetch caidos — " + "; ".join(caidas),
        )
    return out, SourceOutcome("yfinance_estimates", "ok", len(out))


def collect_yfinance_estimates(ticker: str) -> list[EstimateSnapshot]:
    """Accesor de una línea sobre ``_yf_estimates`` (ver ``collect_yfinance_news``)."""
    return _yf_estimates(ticker)[0]


# ── yfinance earnings history (past surprise track record — T-CAT-5a) ─────────


def collect_yfinance_earnings_history(ticker: str, limit: int = 16) -> list[tuple]:
    """
    Fetch the ticker's *past* EPS surprise history for the v0 surprise score
    (Sprint 5 · T-CAT-5a). Returns rows ``(period_label, eps_estimate,
    eps_reported)`` most-recent-first, only quarters that already reported.

    Source = ``yfinance.Ticker.get_earnings_dates(limit=)`` → DataFrame indexed
    by earnings date with 'EPS Estimate' / 'Reported EPS' columns. Future rows
    (no Reported EPS) are dropped. Never raises.

    ⚠️  The 'EPS Estimate' here is yfinance's *current* view, not the consensus
    as of the day before the print — a known revision/look-ahead caveat. This is
    the v0 free path; T-CAT-5b replaces it with point-in-time snapshots.
    """
    out: list[tuple] = []
    try:
        from data.yahoo_finance import _ticker

        t = _ticker(ticker)
        df = None
        try:
            df = t.get_earnings_dates(limit=limit)
        except Exception:
            df = _getattr(t, "earnings_dates")  # property fallback (older yfinance)

        if df is None or getattr(df, "empty", True):
            return out

        cols = {str(c).strip().lower(): c for c in df.columns}
        est_col = cols.get("eps estimate")
        rep_col = cols.get("reported eps")
        if est_col is None or rep_col is None:
            return out

        for idx, row in df.iterrows():
            est = _safe_float(row.get(est_col) if hasattr(row, "get") else None)
            rep = _safe_float(row.get(rep_col) if hasattr(row, "get") else None)
            if rep is None:  # not reported yet → not part of the track record
                continue
            try:
                period_label = idx.strftime("%Y-%m-%d")
            except Exception:
                period_label = str(idx)
            out.append((period_label, est, rep))
    except Exception:
        log.exception("yfinance earnings history fetch failed for %s", ticker)
    return out


# ── Finnhub company-news (aggregates Reuters / CNBC / Bloomberg / …) ─────────
#
# Finnhub's free tier exposes a per-symbol news endpoint that aggregates dozens
# of outlets and, crucially, names the originating outlet in each item's
# ``source`` field. We preserve that as ``finnhub:<Outlet>`` so downstream code
# can later weight by publisher credibility without a schema change. Requires a
# free API key in ``FINNHUB_API_KEY`` (or ``FINNHUB_TOKEN``); if it's missing
# the source logs once and returns [] so the MVP keeps running on the free
# sources alone — same contract as the SEC/RSS collectors.
#
# Endpoint: GET /company-news?symbol=AAPL&from=YYYY-MM-DD&to=YYYY-MM-DD&token=…
# Item shape: {datetime: epoch-s, headline, summary, url, source: "<Outlet>",
#              related, id, category, image}.

FINNHUB_BASE = "https://finnhub.io/api/v1"


def _finnhub_api_key(api_key: str | None = None) -> str | None:
    return api_key or os.environ.get("FINNHUB_API_KEY") or os.environ.get("FINNHUB_TOKEN")


def _finnhub_source_label(outlet) -> str:
    """
    Map Finnhub's per-item outlet to a ``news_events.source`` tag.

    ``"finnhub:<Outlet>"`` keeps provenance (Reuters/CNBC/…) while staying within
    the column's 50-char limit; falls back to plain ``"finnhub"`` when the outlet
    is missing. The ``finnhub:`` prefix means the classifier (which only special-
    cases ``"sec_8k"``) routes these through its keyword path, as intended.
    """
    o = str(outlet or "").strip()
    if not o:
        return "finnhub"
    return f"finnhub:{o}"[:50]


def parse_finnhub_news(ticker: str, payload) -> list[NewsItem]:
    """
    Map a Finnhub ``company-news`` JSON array to NewsItems. Pure / no network.

    ``payload`` is a list of dicts; anything else (None, error dict) yields [].
    Items without a usable ``headline`` are skipped. ``published_at`` comes from
    the ``datetime`` epoch field (seconds, UTC → naive like every other source).
    """
    out: list[NewsItem] = []
    try:
        if not isinstance(payload, list):
            return out
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            title = raw.get("headline")
            if not title:
                continue
            out.append(
                NewsItem(
                    ticker=ticker.upper(),
                    title=title,
                    source=_finnhub_source_label(raw.get("source")),
                    content=raw.get("summary") or None,
                    url=raw.get("url") or None,
                    published_at=_epoch_to_dt(raw.get("datetime")),
                )
            )
    except Exception:
        log.exception("parse_finnhub_news failed for %s", ticker)
    return out


_warned_no_finnhub_key = False


def _finnhub_news(
    ticker: str,
    *,
    session=None,
    api_key: str | None = None,
    days_back: int = 7,
    now: datetime | None = None,
) -> tuple[list[NewsItem], SourceOutcome]:
    """
    Fetch recent company news for ``ticker`` from Finnhub and map to NewsItems.

    Queries the last ``days_back`` days (matches the daily harvest cadence).
    Needs ``FINNHUB_API_KEY`` (or ``FINNHUB_TOKEN``); without it logs once and
    returns []. Never raises — a failed request returns []. ``session`` (any
    object with a ``.get`` like ``requests`` or a ``Session``) is injectable for
    offline tests.
    """
    global _warned_no_finnhub_key
    key = _finnhub_api_key(api_key)
    if not key:
        if not _warned_no_finnhub_key:
            log.info(
                "FINNHUB_API_KEY not set — Finnhub source skipped. Get a free key "
                'at finnhub.io and set it (setx FINNHUB_API_KEY "…" on Windows).'
            )
            _warned_no_finnhub_key = True
        return [], SourceOutcome("finnhub", "skipped", 0, "sin FINNHUB_API_KEY")
    try:
        import requests

        sess = session or requests
        now = now or datetime.now(timezone.utc)
        frm = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
        to = now.strftime("%Y-%m-%d")
        r = sess.get(
            f"{FINNHUB_BASE}/company-news",
            params={"symbol": ticker.upper(), "from": frm, "to": to, "token": key},
            timeout=20,
        )
        r.raise_for_status()
        out = parse_finnhub_news(ticker, r.json())
        return out, SourceOutcome("finnhub", "ok", len(out))
    except Exception as e:
        log.exception("collect_finnhub_news failed for %s", ticker)
        return [], SourceOutcome("finnhub", "failed", 0, _brief(e))


def collect_finnhub_news(
    ticker: str,
    *,
    session=None,
    api_key: str | None = None,
    days_back: int = 7,
    now: datetime | None = None,
) -> list[NewsItem]:
    """Accesor de una línea sobre ``_finnhub_news`` (ver ``collect_yfinance_news``)."""
    return _finnhub_news(ticker, session=session, api_key=api_key, days_back=days_back, now=now)[0]


# ── SEC 8-K via EDGAR (point-in-time, the most reliable source) ──────────────

SEC_DATA_BASE = "https://data.sec.gov"
SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_DEFAULT_SEC_UA = "FinanzIAs/1.0 (set SEC_EDGAR_USER_AGENT=you@example.com)"

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


_warned_default_ua = False


def _sec_session():
    """
    A ``requests.Session`` with the SEC-required descriptive User-Agent.

    EDGAR returns 403 for requests without a proper UA (or the bare
    ``python-requests`` default). Set ``SEC_EDGAR_USER_AGENT`` to a contact
    string, e.g. "FinanzIAs you@example.com". On Windows make it persistent so
    the scheduled harvest sees it too: ``setx SEC_EDGAR_USER_AGENT "..."``
    (a plain ``set`` only lasts the current shell; PowerShell uses ``$env:``).
    """
    global _warned_default_ua
    import requests

    ua = os.environ.get("SEC_EDGAR_USER_AGENT")
    if not ua:
        ua = _DEFAULT_SEC_UA
        if not _warned_default_ua:
            log.warning(
                "SEC_EDGAR_USER_AGENT not set — using a placeholder UA; EDGAR may "
                "return 403. Set it to 'Name you@example.com' (setx on Windows)."
            )
            _warned_default_ua = True
    s = requests.Session()
    s.headers.update({"User-Agent": ua, "Accept": "application/json", "Accept-Encoding": "gzip, deflate"})
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


def _sec_8k(
    ticker: str,
    *,
    session=None,
    mapping: dict[str, int] | None = None,
    max_filings: int = 20,
) -> tuple[list[NewsItem], SourceOutcome]:
    """
    Fetch recent 8-K filings for ``ticker`` from EDGAR and map to NewsItems.

    The most reliable point-in-time source: ``filingDate`` is the official SEC
    disclosure date. Resolves the CIK via the cached ticker map, then reads
    ``submissions/CIK##########.json``. Never raises — a missing CIK or a failed
    request returns [].

    **«Sin CIK» es `skipped`, no `failed`** (tarea 207): el ticker no cotiza en EDGAR
    y eso no dice nada sobre la salud de la fuente. Contarlo como falla haría que
    cualquier universo con un ADR o un ETF pareciera roto todos los días.
    """
    try:
        cik = cik_for_ticker(ticker, mapping)
        if cik is None:
            log.info("no CIK for %s — SEC 8-K skipped", ticker)
            return [], SourceOutcome("sec", "skipped", 0, "sin CIK")
        sess = session or _sec_session()
        url = f"{SEC_DATA_BASE}/submissions/CIK{cik:010d}.json"
        r = sess.get(url, timeout=20)
        r.raise_for_status()
        out = parse_edgar_submissions(ticker, r.json(), cik=cik, max_filings=max_filings)
        return out, SourceOutcome("sec", "ok", len(out))
    except Exception as e:
        log.exception("collect_sec_8k failed for %s", ticker)
        return [], SourceOutcome("sec", "failed", 0, _brief(e))


def collect_sec_8k(
    ticker: str,
    *,
    session=None,
    mapping: dict[str, int] | None = None,
    max_filings: int = 20,
) -> list[NewsItem]:
    """Accesor de una línea sobre ``_sec_8k`` (ver ``collect_yfinance_news``)."""
    return _sec_8k(ticker, session=session, mapping=mapping, max_filings=max_filings)[0]


# ── Default combined collector ───────────────────────────────────────────────


def collect_all(ticker: str, sources: set[str] | None = None) -> _CollectResult:
    """
    Run the enabled sources for one ticker and return combined news + estimates.
    Default sources = {"yfinance"} (news + estimates). Pass e.g.
    {"yfinance", "sec", "finnhub"} to enable more. Each source is
    independently guarded — one failing source never sinks the others.

    Cada fuente deja además su ``SourceOutcome`` en ``res.outcomes`` (tarea 207): el
    guardado sigue siendo el mismo, pero ahora se puede saber si el ``[]`` fue porque
    no había nada o porque la fuente se cayó. Se llaman las implementaciones
    ``_yf_news``/``_sec_8k``/… y no los accesores públicos, que son las mismas
    funciones sin el veredicto.
    """
    sources = sources or {"yfinance"}
    res = _CollectResult()

    def _correr(fn, *args):
        items, outcome = fn(*args)
        res.outcomes.append(outcome)
        return items

    if "yfinance" in sources:
        res.news.extend(_correr(_yf_news, ticker))
        res.estimates.extend(_correr(_yf_estimates, ticker))
    if "sec" in sources:
        res.news.extend(_correr(_sec_8k, ticker))
    if "finnhub" in sources:
        res.news.extend(_correr(_finnhub_news, ticker))
    return res


# ── small helpers ────────────────────────────────────────────────────────────


def _brief(e: BaseException, limite: int = 120) -> str:
    """El tipo + el mensaje, acotado. El traceback ya fue al log por ``log.exception``;
    esto viaja adentro del reporte, que se lee de un vistazo."""
    msg = " ".join(str(e).split())
    return f"{type(e).__name__}: {msg[:limite]}" if msg else type(e).__name__


def _getattr(obj, name, caidas: list[str] | None = None):
    """Lee ``obj.name`` tolerando que reviente, y **anota** si revienta (tarea 210).

    El ``try`` es deliberado y no se toca: yfinance fetchea de verdad al acceder a la
    propiedad, y una que falle no debe hundir a las otras. Lo que faltaba era que el
    veredicto de la fuente se enterara — hasta la 210, tolerar y **ocultar** eran la
    misma cosa, y por eso el 2026-08-14 ``yfinance_estimates`` no registró ni una falla
    mientras ``yfinance_news`` fallaba 52 de 52.

    ``caidas`` es opcional a propósito: los llamadores que no arman veredicto (el
    fallback de ``earnings_dates``) siguen llamando con dos argumentos.

    **Sólo cuenta lo que LEVANTA.** Una propiedad que devuelve ``None`` sin excepción no
    es una falla: es un ticker sin ese dato, que es normal y frecuente. Confundir las dos
    sería el mismo error que la 207 arregló un nivel más arriba, donde ``[]`` significaba
    a la vez *«no había nada»* y *«se cayó»*.
    """
    try:
        return getattr(obj, name, None)
    except Exception as e:
        if caidas is not None:
            caidas.append(f"{name}: {_brief(e, 60)}")
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
