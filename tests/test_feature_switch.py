"""
Tests for ``paper_trading.feature_switch`` — régime-aware feature switching
policy used by T-régimen-3 (Sprint 2 fase 2).

What's pinned down:

1. The canonical attribution-derived policy matches the design table exactly
   in every régime (this is the headline check — if the encoding drifts from
   the design, the switcher does the wrong thing).
2. The policy resolution falls back correctly: WARMUP behaves as default,
   missing per-régime keys inherit from default, explicit overrides win.
3. ``validate_policy_coverage`` catches a policy that forgets a régime.
4. Custom policies work — the module is generic, not hard-coded to the
   attribution result.
"""

from __future__ import annotations

from analysis.regime_detector import (
    REGIME_BEAR,
    REGIME_BULL_QUIET,
    REGIME_BULL_VOLATILE,
    REGIME_LATERAL,
    REGIME_WARMUP,
)
from paper_trading.feature_switch import (
    RegimeFeaturePolicy,
    is_vol_overlay_active_at,
    policy_from_attribution_2026_06_01,
    validate_policy_coverage,
)

# ── Default policy (the headline contract) ──────────────────────────────────


class TestDefaultPolicy:
    """Pin down the attribution-derived policy in every régime.

    These tests act as a contract: if a future analyst updates the policy,
    these tests must be updated too — making the change visible in code
    review."""

    def setup_method(self):
        self.policy = policy_from_attribution_2026_06_01()

    def test_bull_quiet(self):
        eff = self.policy.effective(REGIME_BULL_QUIET)
        assert eff["hmm_enabled"] is False
        assert eff["stacking_enabled"] is False
        assert eff["xgb_signal_enabled"] is True
        assert eff["vol_overlay_enabled"] is True

    def test_bull_volatile_disables_vol_overlay(self):
        eff = self.policy.effective(REGIME_BULL_VOLATILE)
        assert eff["vol_overlay_enabled"] is False
        # other toggles still follow default
        assert eff["hmm_enabled"] is False
        assert eff["stacking_enabled"] is False
        assert eff["xgb_signal_enabled"] is True

    def test_lateral_disables_vol_overlay(self):
        eff = self.policy.effective(REGIME_LATERAL)
        assert eff["vol_overlay_enabled"] is False

    def test_bear_enables_vol_overlay(self):
        eff = self.policy.effective(REGIME_BEAR)
        assert eff["vol_overlay_enabled"] is True

    def test_warmup_falls_back_to_default(self):
        eff = self.policy.effective(REGIME_WARMUP)
        # default = kills + vol_overlay ON (safe stance)
        assert eff["hmm_enabled"] is False
        assert eff["stacking_enabled"] is False
        assert eff["xgb_signal_enabled"] is True
        assert eff["vol_overlay_enabled"] is True

    def test_unknown_regime_falls_back_to_default(self):
        # Defensive: passing a typo'd régime label shouldn't crash, just use
        # defaults.
        eff = self.policy.effective("definitely_not_a_regime")
        assert eff == self.policy.default


# ── Policy semantics (resolution rules) ─────────────────────────────────────


class TestPolicyResolution:
    def test_per_regime_override_wins(self):
        p = RegimeFeaturePolicy(
            default={"foo": True, "bar": False},
            per_regime={REGIME_BEAR: {"foo": False}},
        )
        # In bear, the per-régime entry overrides default.foo
        assert p.effective(REGIME_BEAR)["foo"] is False
        # And bar still comes from default
        assert p.effective(REGIME_BEAR)["bar"] is False

    def test_missing_per_regime_inherits_default(self):
        p = RegimeFeaturePolicy(
            default={"foo": True, "bar": False},
            per_regime={REGIME_BEAR: {"foo": False}},
        )
        # Bull_quiet has no entry → both come from default
        assert p.effective(REGIME_BULL_QUIET) == {"foo": True, "bar": False}

    def test_empty_per_regime_dict_is_same_as_missing(self):
        p_missing = RegimeFeaturePolicy(default={"foo": True}, per_regime={})
        p_empty = RegimeFeaturePolicy(
            default={"foo": True},
            per_regime={REGIME_BEAR: {}},
        )
        assert p_missing.effective(REGIME_BEAR) == p_empty.effective(REGIME_BEAR)

    def test_effective_returns_a_copy(self):
        """Mutating the returned dict must not poison the policy."""
        p = RegimeFeaturePolicy(default={"foo": True})
        eff = p.effective(REGIME_BULL_QUIET)
        eff["foo"] = False
        # Re-querying gives the unmodified policy back
        assert p.effective(REGIME_BULL_QUIET)["foo"] is True


# ── is_vol_overlay_active_at convenience ────────────────────────────────────


class TestIsVolOverlayActiveAt:
    def test_matches_canonical_policy_in_each_regime(self):
        assert is_vol_overlay_active_at(REGIME_BULL_QUIET) is True
        assert is_vol_overlay_active_at(REGIME_BULL_VOLATILE) is False
        assert is_vol_overlay_active_at(REGIME_LATERAL) is False
        assert is_vol_overlay_active_at(REGIME_BEAR) is True

    def test_warmup_keeps_vol_overlay_active(self):
        # During warmup we don't yet have a régime classification; the safe
        # behaviour is to run with the default (vol_overlay ON), matching
        # what production has been doing for months.
        assert is_vol_overlay_active_at(REGIME_WARMUP) is True

    def test_accepts_custom_policy(self):
        custom = RegimeFeaturePolicy(
            default={"vol_overlay_enabled": False},
            per_regime={REGIME_BULL_QUIET: {"vol_overlay_enabled": True}},
        )
        assert is_vol_overlay_active_at(REGIME_BULL_QUIET, custom) is True
        assert is_vol_overlay_active_at(REGIME_BEAR, custom) is False


# ── validate_policy_coverage ────────────────────────────────────────────────


class TestValidatePolicyCoverage:
    def test_canonical_policy_is_fully_covered(self):
        assert validate_policy_coverage(policy_from_attribution_2026_06_01()) == []

    def test_missing_toggle_in_default_flagged(self):
        # default lacks a SWITCHABLE_TOGGLE; per_regime doesn't provide it
        # → every régime lacks it → 4 warnings, one per régime.
        p = RegimeFeaturePolicy(
            default={
                "hmm_enabled": False,
                "stacking_enabled": False,
                "xgb_signal_enabled": True,
            },  # missing vol_overlay_enabled
            per_regime={},
        )
        warnings = validate_policy_coverage(p)
        assert len(warnings) == 4  # one per non-warmup régime
        assert all("vol_overlay_enabled" in w for w in warnings)

    def test_per_regime_completion_silences_warning(self):
        # Same gap as above, but every régime fills it in.
        p = RegimeFeaturePolicy(
            default={"hmm_enabled": False, "stacking_enabled": False, "xgb_signal_enabled": True},
            per_regime={
                REGIME_BULL_QUIET: {"vol_overlay_enabled": True},
                REGIME_BULL_VOLATILE: {"vol_overlay_enabled": False},
                REGIME_LATERAL: {"vol_overlay_enabled": False},
                REGIME_BEAR: {"vol_overlay_enabled": True},
            },
        )
        assert validate_policy_coverage(p) == []
