"""
Earnings surprise track-record — v0 *gratis* (Sprint 5 · T-CAT-5a).

Deterministic, no ML. Builds a per-ticker *directional prior* from the company's
recent EPS surprise history (reported vs. consensus estimate) and exposes it as a
small, interpretable :class:`SurpriseProfile`. This is the signal the exit-veto
(T-CAT-4 / Gate 2c) was missing: T-CAT-6 killed the veto because the only
direction it had was the *symmetric* mean of past earnings reactions (≈ 0), so it
could never tell a likely beat from a likely miss. A ticker's surprise track
record ("MRVL has beaten consensus 7 of the last 8 quarters, mean +9%") is a
genuine directional prior that an imminent-earnings veto can lean on.

What it consumes
----------------
A list of past quarters, each ``(period_label, eps_estimate, eps_reported)``.
The default production loader is ``data.news_sources.collect_yfinance_earnings_history``
(``yfinance.Ticker.get_earnings_dates``), but every function here takes the rows
explicitly so tests run offline with synthetic data.

⚠️  CAVEAT — why this is v0 and explicitly *blocked* from being the final form.
    yfinance's ``get_earnings_dates`` reports, for each past quarter, its
    *current* view of the estimate — NOT the consensus as it stood the trading
    day *before* the report. Estimates get revised, so this carries a
    revision / mild look-ahead bias. It is good enough to bootstrap and backtest
    a surprise signal *today*, without the months-long warm-up the clean path
    needs. The clean, point-in-time path is **T-CAT-5b** (blocked): read the
    consensus from ``analyst_estimate_snapshots`` (the daily snapshots the
    harvester began accumulating 2026-06-06) as of the day before each earnings.
    See ``docs/roadmap_v3_2026-06-09.md`` and ``docs/catalyst_t_cat_0_design.md``.

All functions are pure and fail-soft: a missing / malformed input degrades to a
neutral profile (``directional_score = 0``) and never raises, so the caller never
vetoes on garbage.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Callable, Iterable, Sequence

from config.logging_config import get_logger

log = get_logger(__name__)


# ── tuning constants (explicit so a backtest can move them with evidence) ──────
MIN_QUARTERS: int = 4          # quarters of history for a usable directional call
DEFAULT_BUILD_INTERVAL_DAYS: int = 7  # in-app weekly rebuild cadence (T-CAT-5a)
BEAT_EPS: float = 1e-9         # |surprise| below this counts as an in-line print
STRONG_BEAT_RATE: float = 0.60  # beat_rate above this → clearly positive prior
STRONG_MISS_RATE: float = 0.60  # miss_rate above this → clearly negative prior
SURPRISE_CAP: float = 0.50     # clip a single quarter's surprise to ±50% (outliers)

# A row of past earnings: (period_label, eps_estimate, eps_reported).
# eps_estimate may be None/NaN (quarter dropped); eps_reported None ⇒ not yet out.
EarningsRow = tuple[str | None, "float | None", "float | None"]
EarningsLoader = Callable[[str], "Sequence[EarningsRow] | None"]


@dataclass(frozen=True)
class SurpriseProfile:
    """Per-ticker EPS surprise track record. Pure summary, no I/O."""

    ticker: str
    n_quarters: int            # usable quarters (estimate and reported present)
    beat_rate: float           # fraction with reported > estimate
    miss_rate: float           # fraction with reported < estimate
    mean_surprise: float       # mean signed surprise, fraction (0.09 = +9%)
    median_surprise: float     # median signed surprise, fraction
    last_surprise: float       # most-recent quarter's signed surprise, fraction
    directional_score: float   # [-1, 1]: sign = expected direction, |·| = conviction

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_usable(self) -> bool:
        return self.n_quarters >= MIN_QUARTERS

    @property
    def direction(self) -> int:
        """-1 | 0 | +1 — the discrete expected-surprise direction."""
        if not self.is_usable or self.directional_score == 0.0:
            return 0
        return 1 if self.directional_score > 0 else -1


_NEUTRAL_TEMPLATE = dict(
    n_quarters=0, beat_rate=0.0, miss_rate=0.0, mean_surprise=0.0,
    median_surprise=0.0, last_surprise=0.0, directional_score=0.0,
)


def _neutral(ticker: str) -> SurpriseProfile:
    return SurpriseProfile(ticker=ticker, **_NEUTRAL_TEMPLATE)


def _to_float(x) -> "float | None":
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    # NaN check without importing math: NaN != NaN
    return None if v != v else v


def _median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def surprise_pct(eps_estimate: "float | None", eps_reported: "float | None") -> "float | None":
    """Signed surprise as a fraction: (reported - estimate) / |estimate|.

    Returns None when either side is missing or the estimate is ~0 (the ratio
    would explode / be meaningless). Result is clipped to ±``SURPRISE_CAP`` so a
    single freak quarter can't dominate the average.
    """
    est = _to_float(eps_estimate)
    rep = _to_float(eps_reported)
    if est is None or rep is None:
        return None
    if abs(est) < 1e-6:
        return None
    raw = (rep - est) / abs(est)
    return max(-SURPRISE_CAP, min(SURPRISE_CAP, raw))


def build_surprise_profile(
    ticker: str,
    rows: "Iterable[EarningsRow] | None",
) -> SurpriseProfile:
    """Aggregate a ticker's past-earnings rows into a :class:`SurpriseProfile`.

    ``rows`` is expected most-recent-first (yfinance order); ``last_surprise``
    takes the first usable row regardless, so order only affects that field.
    Pure and fail-soft: any problem → neutral profile.
    """
    if not rows:
        return _neutral(ticker)

    try:
        surprises: list[float] = []
        first_usable: "float | None" = None
        beats = misses = 0
        for row in rows:
            try:
                _, est, rep = row
            except (TypeError, ValueError):
                continue
            s = surprise_pct(est, rep)
            if s is None:
                continue
            surprises.append(s)
            if first_usable is None:
                first_usable = s
            if s > BEAT_EPS:
                beats += 1
            elif s < -BEAT_EPS:
                misses += 1

        n = len(surprises)
        if n == 0:
            return _neutral(ticker)

        beat_rate = beats / n
        miss_rate = misses / n
        mean_s = sum(surprises) / n
        median_s = _median(surprises)
        last_s = first_usable if first_usable is not None else 0.0

        directional = _directional_score(n, beat_rate, miss_rate, mean_s)

        return SurpriseProfile(
            ticker=ticker,
            n_quarters=n,
            beat_rate=round(beat_rate, 4),
            miss_rate=round(miss_rate, 4),
            mean_surprise=round(mean_s, 6),
            median_surprise=round(median_s, 6),
            last_surprise=round(last_s, 6),
            directional_score=round(directional, 4),
        )
    except Exception:  # pragma: no cover — last-resort fail-soft
        log.exception("build_surprise_profile failed for %s", ticker)
        return _neutral(ticker)


def _directional_score(n: int, beat_rate: float, miss_rate: float, mean_s: float) -> float:
    """Combine beat consistency and average magnitude into [-1, 1].

    Below ``MIN_QUARTERS`` we return 0 (not enough evidence → don't bias the
    veto). Otherwise: a *consistency* term (beat_rate - miss_rate, ∈[-1,1]) and a
    *magnitude* term (mean surprise scaled by SURPRISE_CAP). They must agree in
    sign to produce a confident score; a disagreement (beats a lot but mean
    negative from one huge miss) pulls toward 0.
    """
    if n < MIN_QUARTERS:
        return 0.0
    consistency = beat_rate - miss_rate                  # [-1, 1]
    magnitude = max(-1.0, min(1.0, mean_s / SURPRISE_CAP))  # [-1, 1]
    # geometric-style blend that respects sign agreement
    if consistency == 0.0 and magnitude == 0.0:
        return 0.0
    blended = 0.6 * consistency + 0.4 * magnitude
    # if the two terms disagree in sign, damp the result
    if consistency * magnitude < 0:
        blended *= 0.5
    return max(-1.0, min(1.0, blended))


def make_surprise_loader(
    profiles: dict[str, dict] | dict[str, SurpriseProfile] | None,
) -> EarningsLoader:  # noqa: D401 — name kept symmetric with the engine's providers
    """Build a ``ticker -> SurpriseProfile | None`` callable from a prebuilt map.

    Accepts either a map of ``SurpriseProfile`` or of plain dicts (e.g. the JSON
    produced by ``scripts/build_surprise_profiles.py``). Unknown ticker → None,
    so ``imminent_catalyst`` simply falls back to its reaction-mean direction.
    """
    profiles = profiles or {}

    def _load(ticker: str) -> "SurpriseProfile | None":
        v = profiles.get(ticker)
        if v is None:
            return None
        if isinstance(v, SurpriseProfile):
            return v
        try:
            return SurpriseProfile(ticker=ticker, **{
                k: v[k] for k in (
                    "n_quarters", "beat_rate", "miss_rate", "mean_surprise",
                    "median_surprise", "last_surprise", "directional_score",
                ) if k in v
            })
        except Exception:
            log.exception("make_surprise_loader: bad profile dict for %s", ticker)
            return None

    return _load


# ── rebuild cadence (the in-app weekly scheduler reads this) ──────────────────


def build_due(
    last_iso: "str | None",
    now: datetime,
    interval_days: int = DEFAULT_BUILD_INTERVAL_DAYS,
) -> bool:
    """Is a surprise-profile rebuild due?

    ``last_iso`` is the ISO timestamp of the previous successful build (the
    value stored in ``settings['surprise_last_build']``); ``None``/empty/garbage
    → due (never built yet). Otherwise due once ``interval_days`` have elapsed.
    Pure and fail-soft so the scheduler can call it without a try/except.
    """
    if not last_iso:
        return True
    try:
        last = datetime.fromisoformat(last_iso)
    except (TypeError, ValueError):
        return True
    return (now - last) >= timedelta(days=max(0, int(interval_days)))
