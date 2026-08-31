"""
Historical reaction + economic relevance (Sprint 5 · T-CAT-3).

Deterministic, no ML. Two pieces the roadmap calls for:

1. **historical_reaction[ticker][event_type]** — the average forward price move
   after past events of a given type. For each classified ``NewsEvent`` with a
   point-in-time ``published_at`` we look up the price path in the OHLCV cache
   and compute the forward return at 1/5/20 trading days. Aggregating these by
   ``event_type`` (globally) and by ``(ticker, event_type)`` gives the empirical
   "what usually happens after this kind of news" table that T-CAT-4's Impact
   Score multiplies in.

2. **economic relevance** — scale an event by how big it is relative to the
   company: ``relevance = dollar_amount / market_cap`` when a dollar figure is
   extractable from the headline (e.g. "$5 billion contract").

All functions are pure and take a ``price_loader`` callable so tests run offline
with synthetic frames. Forward returns are genuinely point-in-time: entry is the
first trading day on/after the event date, so there's no lookahead.

Caveat: recent events don't have N days of *future* prices yet, so their
forward return is ``None`` and they're simply excluded from the average — the
table strengthens as the harvest accumulates (same warm-up story as T-CAT-0).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from config.logging_config import get_logger

log = get_logger(__name__)

DEFAULT_HORIZONS: tuple[int, ...] = (1, 5, 20)

# price_loader(ticker) -> OHLCV DataFrame (DatetimeIndex, "Close" col) or None
PriceLoader = Callable[[str], "pd.DataFrame | None"]


# ── forward returns ──────────────────────────────────────────────────────────


def _price_series(df: pd.DataFrame | None, col: str = "Close") -> pd.Series | None:
    if df is None or getattr(df, "empty", True) or col not in df.columns:
        return None
    s = df[col].squeeze()
    try:
        s = s.astype(float)
    except Exception:
        return None
    # ensure a sorted DatetimeIndex
    if not isinstance(s.index, pd.DatetimeIndex):
        try:
            s.index = pd.to_datetime(s.index)
        except Exception:
            return None
    return s.sort_index()


def _close_series(df: pd.DataFrame | None) -> pd.Series | None:
    return _price_series(df, "Close")


def forward_return(
    df: pd.DataFrame | None,
    event_date,
    horizon: int,
    *,
    entry: str = "close",
) -> float | None:
    """
    Forward return ``horizon`` trading days after the event.

    ``entry`` controls the entry price (M2 of the 2026-06-09 code review):

    - ``"close"`` (default, what T-CAT-3 measures): close-to-close. Entry =
      Close of the first trading day on/after ``event_date``; exit = Close
      ``horizon`` bars later. Good for *describing* how a name reacted.
    - ``"next_open"``: enter at the **Open of the next session** after that bar
      and exit at the **same** Close[pos+horizon]. A headline released
      after-hours has its gap baked into the event-day Close, so an *actionable*
      signal must enter at the next open — that's the move we could really
      capture. Requires an ``"Open"`` column; returns None if it's missing.

    Both keep the exit bar aligned (Close[pos+horizon]) so the two are directly
    comparable. Returns None if the bar isn't found or there aren't enough
    future bars yet. Point-in-time: never uses prices before entry.
    """
    close = _close_series(df)
    if close is None or len(close) == 0:
        return None
    try:
        ed = pd.Timestamp(event_date).normalize()
    except Exception:
        return None
    pos = int(close.index.searchsorted(ed, side="left"))
    exit_pos = pos + horizon
    if pos >= len(close) or exit_pos >= len(close):
        return None
    p1 = float(close.iloc[exit_pos])

    if entry == "next_open":
        open_s = _price_series(df, "Open")
        if open_s is None:
            return None
        entry_pos = pos + 1
        # next session must exist and precede the (shared) exit bar
        if entry_pos >= len(open_s) or entry_pos > exit_pos:
            return None
        p0 = float(open_s.iloc[entry_pos])
    else:
        p0 = float(close.iloc[pos])

    if not np.isfinite(p0) or not np.isfinite(p1) or p0 <= 0:
        return None
    return p1 / p0 - 1.0


# ── aggregation ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReactionStat:
    count: int
    mean: float | None  # mean forward return
    std: float | None  # sample std
    hit_rate: float | None  # fraction of positive returns

    def to_dict(self) -> dict:
        return asdict(self)


def aggregate(returns: list[float]) -> ReactionStat:
    """Summarise a list of forward returns. Empty → count 0, None stats."""
    vals = [r for r in returns if r is not None and np.isfinite(r)]
    n = len(vals)
    if n == 0:
        return ReactionStat(0, None, None, None)
    arr = np.asarray(vals, dtype=float)
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if n > 1 else 0.0
    hit = float((arr > 0).mean())
    return ReactionStat(n, mean, std, hit)


def build_historical_reaction(
    events: Iterable[tuple[str, str, datetime | None]],
    price_loader: PriceLoader,
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict:
    """
    Build the reaction table from ``(ticker, event_type, published_at)`` events.

    ``price_loader(ticker)`` is called once per ticker (memoized here). Output is
    JSON-serialisable::

        {
          "horizons": [1, 5, 20],
          "by_event":        {event_type: {h: stat_dict}},
          "by_ticker_event": {"TICKER|event_type": {h: stat_dict}},
        }
    """
    cache: dict[str, pd.DataFrame | None] = {}

    def _load(ticker: str):
        if ticker not in cache:
            try:
                cache[ticker] = price_loader(ticker)
            except Exception:
                log.exception("price_loader failed for %s", ticker)
                cache[ticker] = None
        return cache[ticker]

    # collect raw returns
    by_event: dict[str, dict[int, list]] = {}
    by_te: dict[str, dict[int, list]] = {}
    for ticker, event_type, published_at in events:
        if not event_type or published_at is None:
            continue
        df = _load(ticker)
        if df is None:
            continue
        te_key = f"{ticker.upper()}|{event_type}"
        for h in horizons:
            r = forward_return(df, published_at, h)
            if r is None:
                continue
            by_event.setdefault(event_type, {}).setdefault(h, []).append(r)
            by_te.setdefault(te_key, {}).setdefault(h, []).append(r)

    def _finalize(raw: dict[str, dict[int, list]]) -> dict:
        out: dict[str, dict[str, dict]] = {}
        for key, per_h in raw.items():
            out[key] = {str(h): aggregate(per_h.get(h, [])).to_dict() for h in horizons}
        return out

    return {
        "horizons": list(horizons),
        "by_event": _finalize(by_event),
        "by_ticker_event": _finalize(by_te),
    }


def lookup_reaction(
    table: dict,
    ticker: str,
    event_type: str,
    horizon: int = 5,
    *,
    min_count: int = 5,
) -> ReactionStat | None:
    """
    Read the reaction for (ticker, event_type, horizon), falling back to the
    global event_type stat when the per-ticker sample is too thin (< min_count).
    Returns None if neither has data.
    """
    h = str(horizon)
    te = table.get("by_ticker_event", {}).get(f"{ticker.upper()}|{event_type}", {}).get(h)
    if te and te.get("count", 0) >= min_count:
        return ReactionStat(**te)
    glob = table.get("by_event", {}).get(event_type, {}).get(h)
    if glob and glob.get("count", 0) > 0:
        return ReactionStat(**glob)
    if te and te.get("count", 0) > 0:
        return ReactionStat(**te)
    return None


# ── economic relevance ───────────────────────────────────────────────────────

_MULT = {
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "mm": 1e6,
    "mn": 1e6,
    "million": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
    "t": 1e12,
    "tn": 1e12,
    "trillion": 1e12,
}
_DOLLAR_RE = re.compile(
    r"\$\s?([0-9][0-9,]*(?:\.[0-9]+)?)\s?(trillion|billion|million|thousand|tn|bn|mm|mn|t|b|m|k)?\b",
    re.IGNORECASE,
)


def extract_dollar_amount(text: str | None) -> float | None:
    """
    Largest USD figure mentioned in ``text`` (e.g. "$5 billion" → 5e9). Returns
    None if no dollar figure is present. Picks the max so "$5B deal, $10M fee"
    keys off the headline figure.
    """
    if not text:
        return None
    best: float | None = None
    for num, unit in _DOLLAR_RE.findall(text):
        try:
            val = float(num.replace(",", ""))
        except ValueError:
            continue
        val *= _MULT.get(unit.lower(), 1.0) if unit else 1.0
        if best is None or val > best:
            best = val
    return best


def relevance(dollar_amount: float | None, market_cap: float | None) -> float | None:
    """``dollar_amount / market_cap`` (0..1+), or None if either is missing/invalid."""
    if not dollar_amount or not market_cap or market_cap <= 0:
        return None
    return dollar_amount / market_cap
