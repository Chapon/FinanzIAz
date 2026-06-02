"""
Régime-aware feature switching policy (T-régimen-3, Sprint 2 fase 2).

Pure function module: given a régime label (one of the four buckets emitted by
:mod:`analysis.regime_detector`), return the effective feature toggles to use.

The default policy ``policy_from_attribution_2026_06_01()`` was derived from the
T-régimen-2 attribution run on ``data/harness_walkforward/20260601_155840`` —
4 windows × 4 régimes over 5 years of OHLCV. See ``docs/regime_attribution_v1.md``
for the per-feature decision rationale; the summary is:

  * ``xgb_signal_enabled``  → always ON  (4/4 windows show it helps in
    bull_quiet, 3/4 in lateral; only 1 obs marginal in bear)
  * ``stacking_enabled``    → always OFF (caótico across régimes; consistent
    hurt only in bear)
  * ``hmm_enabled``         → always OFF (3/4 windows show it hurts in the
    dominant bull_quiet régime; marginal help elsewhere)
  * ``vol_overlay_enabled`` → SWITCH:
      - bull_quiet  → ON  (~neutral but slight help on average)
      - bull_volatile → OFF (2/2 windows hurt strongly: +0.57, +0.55)
      - lateral     → OFF (4/4 windows hurt: +0.02, +0.40, +0.17, +0.64)
      - bear        → ON  (2/2 windows help: -0.25, -0.40)

The actual switching surface is therefore only ``vol_overlay_enabled``; the
other three are constants. Future attribution runs may add more switched
features — the policy contract is generic so that adding more conditional
toggles is a one-line change.

Contract: this module has NO side effects, no DB, no settings, no logger.
Callers are responsible for plumbing the result into whatever execution path
needs it (harness vol_overlay_fn hook, production settings, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from analysis.regime_detector import (
    REGIME_BEAR,
    REGIME_BULL_QUIET,
    REGIME_BULL_VOLATILE,
    REGIME_LATERAL,
    REGIME_WARMUP,
    VALID_REGIMES,
)

# The set of feature toggle keys this module knows how to switch. Keep in sync
# with the analysis.harness._HARNESS_TOGGLE_KEYS tuple.
SWITCHABLE_TOGGLES = (
    "hmm_enabled",
    "stacking_enabled",
    "xgb_signal_enabled",
    "vol_overlay_enabled",
)


@dataclass(frozen=True)
class RegimeFeaturePolicy:
    """Maps each régime to the toggle values that should be in effect.

    The dict ``per_regime`` is keyed by régime label. Each value is a partial
    dict of toggle key → bool. Keys not present in a particular régime fall
    back to ``default`` (which itself only needs to specify toggles that are
    constant across régimes; missing toggles are treated as "leave alone" by
    callers, but the harness wiring sets every SWITCHABLE_TOGGLES explicitly
    so the policy must cover them in either ``default`` or ``per_regime``).
    """

    default: Mapping[str, bool]
    per_regime: Mapping[str, Mapping[str, bool]] = field(default_factory=dict)

    def effective(self, regime: str) -> dict[str, bool]:
        """Return the effective toggle dict for ``regime``.

        WARMUP collapses to the same behaviour as ``default`` — before the
        régime detector has classified the current bar, the engine should
        run with the régime-agnostic defaults (typically: every kill is
        applied, every switched toggle is "safe-on").
        """
        out: dict[str, bool] = dict(self.default)
        if regime != REGIME_WARMUP:
            regime_overrides = self.per_regime.get(regime, {})
            out.update(regime_overrides)
        return out


def policy_from_attribution_2026_06_01() -> RegimeFeaturePolicy:
    """Concrete policy derived from the 5y / 4-window attribution.

    Frozen as the canonical default so we can refer to it from tests and
    documentation. Updating the policy should be deliberate: change this
    function (or write a new one) rather than mutating shared state.
    """
    return RegimeFeaturePolicy(
        # default = kills baked in. vol_overlay default ON (safest stance —
        # the only régime where the policy disables it is lateral & bull_volatile;
        # treating bull_quiet/bear/warmup all as "ON" matches both the
        # attribution result and the conservative WARMUP fallback).
        default={
            "hmm_enabled": False,
            "stacking_enabled": False,
            "xgb_signal_enabled": True,
            "vol_overlay_enabled": True,
        },
        per_regime={
            # bull_quiet: defaults are correct, no overrides needed.
            REGIME_BULL_QUIET: {},
            # bull_volatile: vol_overlay HURT here (+0.57, +0.55 in 2/2 obs).
            REGIME_BULL_VOLATILE: {"vol_overlay_enabled": False},
            # lateral: vol_overlay HURT here (4/4 windows positive Δ).
            REGIME_LATERAL: {"vol_overlay_enabled": False},
            # bear: vol_overlay HELPED here (-0.25, -0.40 in 2/2 measurable obs).
            REGIME_BEAR: {"vol_overlay_enabled": True},
        },
    )


# ── Helpers for consumers ───────────────────────────────────────────────────


def is_vol_overlay_active_at(regime: str,
                             policy: Optional[RegimeFeaturePolicy] = None) -> bool:
    """Convenience accessor — equivalent to ``policy.effective(regime)['vol_overlay_enabled']``
    but with a default policy that lets callers skip the import boilerplate.

    Pure function; safe to call inside tight loops (e.g. per-bar in a
    backtester). The default policy is reconstructed on each call so policy
    upgrades in the source propagate immediately to callers."""
    p = policy or policy_from_attribution_2026_06_01()
    return bool(p.effective(regime).get("vol_overlay_enabled", True))


def validate_policy_coverage(policy: RegimeFeaturePolicy) -> list[str]:
    """Return a list of human-readable warnings if the policy fails to assign
    every SWITCHABLE toggle in every non-warmup régime. Empty list → policy
    is fully specified. Useful for catching typos / missing régime entries
    before kicking off a long backtest."""
    warnings: list[str] = []
    for regime in VALID_REGIMES:
        effective = policy.effective(regime)
        for toggle in SWITCHABLE_TOGGLES:
            if toggle not in effective:
                warnings.append(
                    f"policy does not assign {toggle!r} in régime {regime!r}"
                )
    return warnings
