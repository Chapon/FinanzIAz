"""
Impact Score heurístico v1 (Sprint 5 · T-CAT-4).

Deterministic, no ML. Composes the catalyst pieces already in the repo into a
single interpretable scalar per event and exposes a forward-looking "imminent
catalyst" signal that the exit-veto consumes.

Design: ``docs/catalyst_t_cat_4_design.md``. Inputs:
- T-CAT-2 ``classify`` → ``event_type / sentiment / classifier_confidence``.
- T-CAT-3 ``build_historical_reaction`` / ``lookup_reaction`` → empirical
  forward-return ``ReactionStat`` (mean / std / hit_rate / count) per horizon.
- T-CAT-3 ``relevance`` (= $amount / market_cap) for economic size.

Two surfaces, deliberately separate (opposite horizons):

1. :func:`score_event` — retrospective magnitude+direction of an event already
   published. Feeds panels / the T-CAT-6 backtest. NOT on the trading hot-path.
2. :func:`imminent_catalyst` — forward-looking: is there a *known future*
   catalyst (next earnings within K business days) whose expected reaction is
   positive? This is what the exit-veto (Gate 2c) reads. v1: earnings only.

Everything is pure and fail-soft: a missing input (no market cap, empty reaction
table, off-taxonomy event) degrades the relevant factor to neutral and never
raises. ``price_loader`` / ``earnings_loader`` are injected so tests run offline.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime

import numpy as np

from config.logging_config import get_logger

log = get_logger(__name__)


# ── Calibration constants (explicit so a backtest can move them with evidence) ─
SCALE: float = 0.05  # magnitude saturation: a 5% mean move → tanh(1) ≈ 0.76
MIN_SAMPLE: int = 8  # reaction count for full confidence weight
R: float = 0.5  # max relevance boost (relevance_weight ∈ [1, 1+R])
REL_SCALE: float = 0.10  # relevance saturation ($amount/mcap of 0.10 → tanh(1))
CONF_FLOOR: float = 0.4  # confidence_weight floor (don't zero a material event)
DEFAULT_HORIZON: int = 5  # operative horizon — the model predicts at 5d

# Prior magnitude per event_type for the cold start (no reaction history yet).
# Magnitude only (sign comes from sentiment in that case). Hypotheses, not
# truth — they fade as the harvest accumulates reaction data (T-CAT-0).
EVENT_PRIORS: dict[str, float] = {
    "earnings_results": 0.90,
    "clinical_fda": 0.90,
    "mna": 0.85,
    "guidance_raise": 0.80,
    "guidance_cut": 0.80,
    "legal_regulatory": 0.65,
    "restructuring": 0.60,
    "analyst_rating": 0.55,
    "product_launch": 0.50,
    "capital_return": 0.45,
    "partnership_contract": 0.45,
    "executive_change": 0.40,
    "financing_offering": 0.40,
    "insider_activity": 0.30,
    "macro_sector": 0.30,
    "stock_movement": 0.15,
    "other": 0.10,
}
_PRIOR_DEFAULT = 0.10

_SENTIMENT_SIGN = {"positive": 1, "negative": -1, "neutral": 0}

# earnings_loader(ticker) -> next earnings datetime (or None). Same contract as
# the engine's earnings_provider (Gate 6 blackout).
EarningsLoader = Callable[[str], "datetime | None"]


# ── Retrospective event score ─────────────────────────────────────────────────


@dataclass(frozen=True)
class ImpactScore:
    value: float  # ≈ [-1.5, 1.5]; sign = direction, |·| = conviction
    direction: int  # -1 | 0 | +1
    magnitude: float  # [0, 1]
    confidence_weight: float  # [CONF_FLOOR, 1]
    relevance_weight: float  # [1, 1+R]
    horizon: int
    basis: str  # "reaction" | "prior" — where magnitude came from

    def to_dict(self) -> dict:
        return asdict(self)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def score_event(
    ticker: str,
    event_type: str | None,
    sentiment: str | None,
    classifier_confidence: float | None,
    *,
    reaction_table: dict | None,
    headline: str | None = None,
    market_cap: float | None = None,
    horizon: int = DEFAULT_HORIZON,
) -> ImpactScore:
    """
    Compose the Impact Score for one event. Pure, fail-soft, never raises.

        value = direction × magnitude × confidence_weight × relevance_weight

    See module docstring / design doc for each factor. When the reaction table
    has a usable stat for (ticker, event_type), ``direction`` follows the *sign
    of the measured reaction* (the market's actual move beats a keyword guess)
    and ``magnitude`` saturates ``|mean|``; otherwise it falls back to the
    classifier ``sentiment`` for direction and an event-type prior for magnitude.
    """
    try:
        from analysis.catalyst_reaction import extract_dollar_amount, lookup_reaction, relevance
    except Exception:  # pragma: no cover - import guard
        log.exception("impact_score: catalyst_reaction import failed")
        lookup_reaction = extract_dollar_amount = relevance = None  # type: ignore

    etype = event_type or "other"
    stat = None
    if reaction_table and lookup_reaction is not None:
        try:
            stat = lookup_reaction(reaction_table, ticker, etype, horizon)
        except Exception:
            log.exception("impact_score: lookup_reaction failed for %s/%s", ticker, etype)
            stat = None

    sent_sign = _SENTIMENT_SIGN.get(sentiment or "neutral", 0)

    if stat is not None and stat.mean is not None and stat.count and stat.count > 0:
        basis = "reaction"
        mean = float(stat.mean)
        # direction from the measured move; sentiment breaks an exact-zero mean
        direction = 1 if mean > 0 else (-1 if mean < 0 else sent_sign)
        magnitude = math.tanh(abs(mean) / SCALE)
        sample_factor = min(1.0, stat.count / MIN_SAMPLE)
    else:
        basis = "prior"
        direction = sent_sign
        magnitude = EVENT_PRIORS.get(etype, _PRIOR_DEFAULT)
        sample_factor = 0.0  # no measured history → lean on the floor

    try:
        conf = float(classifier_confidence) if classifier_confidence is not None else 0.0
    except (TypeError, ValueError):
        conf = 0.0
    conf = _clamp(conf, 0.0, 1.0)
    confidence_weight = _clamp(CONF_FLOOR + (1.0 - CONF_FLOOR) * conf * sample_factor, CONF_FLOOR, 1.0)

    relevance_weight = 1.0
    if extract_dollar_amount is not None and relevance is not None and market_cap:
        try:
            dollars = extract_dollar_amount(headline)
            rel = relevance(dollars, market_cap)
            if rel is not None:
                relevance_weight = 1.0 + R * math.tanh(rel / REL_SCALE)
        except Exception:
            log.exception("impact_score: relevance computation failed for %s", ticker)

    value = direction * magnitude * confidence_weight * relevance_weight
    return ImpactScore(
        value=float(value),
        direction=int(direction),
        magnitude=float(magnitude),
        confidence_weight=float(confidence_weight),
        relevance_weight=float(relevance_weight),
        horizon=int(horizon),
        basis=basis,
    )


# ── Forward-looking imminent catalyst (what the exit-veto reads) ──────────────


@dataclass(frozen=True)
class CatalystSignal:
    kind: str  # "earnings" (v1)
    days_until: int  # business days until the event
    expected_direction: int  # -1 | 0 | +1
    expected_magnitude: float  # [0, 1]
    score: float  # direction × magnitude × confidence_weight
    basis: str = "reaction"  # "reaction" (mean move) | "surprise" (T-CAT-5a track record)

    def to_dict(self) -> dict:
        return asdict(self)


# surprise_loader(ticker) -> SurpriseProfile | None  (T-CAT-5a, injected/offline)
SurpriseLoader = Callable[[str], "object | None"]


def _busday_delta(asof: datetime, target: datetime) -> int:
    """Business days from ``asof`` to ``target`` (negative if in the past)."""
    return int(np.busday_count(asof.date(), target.date()))


def imminent_catalyst(
    ticker: str,
    asof_date: datetime,
    *,
    reaction_table: dict | None,
    earnings_loader: EarningsLoader,
    surprise_loader: SurpriseLoader | None = None,
    horizon_bdays: int = 3,
    score_horizon: int = DEFAULT_HORIZON,
) -> CatalystSignal | None:
    """
    Return a :class:`CatalystSignal` iff ``ticker`` has a *known future* catalyst
    within ``horizon_bdays`` business days. v1 source = next earnings date (the
    only freely-datable future event; same loader Gate 6 blackout uses).

    Direction precedence:
      1. **Surprise track record (T-CAT-5a)** — if ``surprise_loader`` yields a
         *usable* :class:`~analysis.surprise_score.SurpriseProfile` (≥ MIN_QUARTERS
         and a non-zero ``directional_score``), its sign drives the expected
         direction and its conviction sets the magnitude. This is the directional
         prior T-CAT-6 lacked: a ticker that consistently beats consensus gets a
         positive earnings prior instead of the (symmetric, ≈0) reaction mean.
      2. **Historical reaction mean** — the prior behaviour, used when there's no
         usable surprise profile.

    No usable signal in either path → ``expected_direction = 0`` so the caller
    does NOT veto. Fail-soft: a loader that raises or returns None is ignored.
    """
    try:
        edt = earnings_loader(ticker)
    except Exception:
        log.exception("imminent_catalyst: earnings_loader failed for %s", ticker)
        return None
    if edt is None:
        return None

    days_until = _busday_delta(asof_date, edt)
    # future (or today) and within the imminence window
    if days_until < 0 or days_until > horizon_bdays:
        return None

    score = score_event(
        ticker,
        "earnings_results",
        sentiment="neutral",
        classifier_confidence=1.0,  # the earnings date itself is certain
        reaction_table=reaction_table,
        horizon=score_horizon,
    )

    # ── direction precedence: surprise track record beats the neutral mean ────
    profile = None
    if surprise_loader is not None:
        try:
            profile = surprise_loader(ticker)
        except Exception:
            log.exception("imminent_catalyst: surprise_loader failed for %s", ticker)
            profile = None

    if profile is not None and getattr(profile, "is_usable", False) and getattr(profile, "direction", 0) != 0:
        direction = int(profile.direction)
        # conviction from the track record; keep the reaction magnitude as a floor
        # so a known catalyst still carries weight even with a mild surprise edge.
        magnitude = max(float(score.magnitude), abs(float(profile.directional_score)))
        basis = "surprise"
        sig_score = direction * magnitude * float(score.confidence_weight)
    else:
        direction = int(score.direction)
        magnitude = float(score.magnitude)
        basis = "reaction"
        sig_score = direction * magnitude * float(score.confidence_weight)

    return CatalystSignal(
        kind="earnings",
        days_until=int(days_until),
        expected_direction=int(direction),
        expected_magnitude=float(magnitude),
        # drop relevance_weight here: imminence has no headline dollar figure
        score=float(sig_score),
        basis=basis,
    )


# ── Exit-veto helper (Gate 2c) — the engine calls this ────────────────────────


def exit_veto_block(
    *,
    reason: str | None,
    signal_score: float | None,
    ticker: str,
    scan_at: datetime,
    signal: CatalystSignal | None,
    enabled: bool,
    gray_low: float,
    gray_high: float,
    veto_min_score: float,
) -> str | None:
    """T-CAT-4 exit-veto. Return a warning string if a gray-zone signal SELL
    should be postponed because a positive catalyst is imminent; else None.

    Blocks only when ALL hold (symmetric to Gate 6 earnings-blackout for BUYs):
      * ``enabled`` (flag default OFF until T-CAT-6 validates),
      * the reason is a *signal* SELL, not a risk exit (atr_* / vol_trim never
        vetoed — a risk stop outranks any catalyst),
      * there IS a ``signal_score`` and it sits in the gray zone
        ``[gray_low, gray_high]`` (the same low-conviction band T6.4 governs);
        high-conviction sells (score > gray_high) execute regardless,
      * ``signal`` is a positive imminent catalyst with ``score >= veto_min_score``.

    Same contract as the other gates: caller logs the returned string and skips.
    """
    if not enabled or signal is None:
        return None
    # never veto a risk exit
    try:
        from paper_trading.gates import is_atr_forced_exit_reason, is_vol_trim_reason

        if is_atr_forced_exit_reason(reason) or is_vol_trim_reason(reason):
            return None
    except Exception:  # pragma: no cover - import guard
        log.exception("exit_veto_block: gates import failed — failing open")
        return None
    if signal_score is None:
        return None
    if not (gray_low <= signal_score <= gray_high):
        return None
    if signal.expected_direction != 1 or signal.score < veto_min_score:
        return None
    return (
        f"SELL de señal pospuesto (T-CAT-4 exit-veto): catalyst {signal.kind} "
        f"inminente en {signal.days_until} días hábiles, dirección esperada + "
        f"(score {signal.score:.2f} ≥ {veto_min_score:.2f}); score de venta "
        f"{signal_score:.2f} en zona gris [{gray_low:.2f}, {gray_high:.2f}]."
    )


# T-CAT-5a: surprise track record wired into imminent_catalyst (see surprise_score.py)
