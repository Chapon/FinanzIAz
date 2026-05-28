"""
ExperimentConfig: declarative experiment specification for harness runs.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional


@dataclass(frozen=True)
class ExperimentConfig:
    """
    Specifies a single backtest experiment: feature toggles + metadata.

    Attributes:
        name: Unique identifier for this experiment (e.g., "baseline", "no_hmm")
        hmm_enabled: Enable Hidden Markov Model state filtering
        stacking_enabled: Enable position stacking (T05)
        xgb_signal_enabled: Enable XGBoost signal weighting
        correlation_gate_enabled: Enable correlation gate (T09)
        vol_overlay_enabled: Enable portfolio volatility overlay (T10)
        description: Optional human-readable description of the experiment
    """
    name: str
    hmm_enabled: bool = True
    stacking_enabled: bool = True
    xgb_signal_enabled: bool = True
    correlation_gate_enabled: bool = True
    vol_overlay_enabled: bool = True
    description: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    def as_settings_dict(self) -> dict:
        """Return feature toggles as a dict to apply to settings manager."""
        return {
            "hmm_enabled": self.hmm_enabled,
            "stacking_enabled": self.stacking_enabled,
            "xgb_signal_enabled": self.xgb_signal_enabled,
            "correlation_gate_enabled": self.correlation_gate_enabled,
            "vol_overlay_enabled": self.vol_overlay_enabled,
        }

    @staticmethod
    def baseline() -> ExperimentConfig:
        """Baseline: all features enabled (current Sim Principal behavior)."""
        return ExperimentConfig(
            name="baseline",
            hmm_enabled=True,
            stacking_enabled=True,
            xgb_signal_enabled=True,
            correlation_gate_enabled=True,
            vol_overlay_enabled=True,
            description="All features enabled (current production settings)",
        )

    @staticmethod
    def ablation_variants() -> list[ExperimentConfig]:
        """
        Generate ablation variants: disable one feature at a time.

        Returns:
            List of 5 ExperimentConfig objects, each with one feature disabled.
        """
        return [
            ExperimentConfig(
                name="no_hmm",
                hmm_enabled=False,
                stacking_enabled=True,
                xgb_signal_enabled=True,
                correlation_gate_enabled=True,
                vol_overlay_enabled=True,
                description="HMM disabled",
            ),
            ExperimentConfig(
                name="no_stacking",
                hmm_enabled=True,
                stacking_enabled=False,
                xgb_signal_enabled=True,
                correlation_gate_enabled=True,
                vol_overlay_enabled=True,
                description="Stacking disabled",
            ),
            ExperimentConfig(
                name="no_xgb",
                hmm_enabled=True,
                stacking_enabled=True,
                xgb_signal_enabled=False,
                correlation_gate_enabled=True,
                vol_overlay_enabled=True,
                description="XGBoost signal weighting disabled",
            ),
            ExperimentConfig(
                name="no_correlation_gate",
                hmm_enabled=True,
                stacking_enabled=True,
                xgb_signal_enabled=True,
                correlation_gate_enabled=False,
                vol_overlay_enabled=True,
                description="Correlation gate disabled",
            ),
            ExperimentConfig(
                name="no_vol_overlay",
                hmm_enabled=True,
                stacking_enabled=True,
                xgb_signal_enabled=True,
                correlation_gate_enabled=True,
                vol_overlay_enabled=False,
                description="Volatility overlay disabled",
            ),
        ]
