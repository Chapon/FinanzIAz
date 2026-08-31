"""
T-harness for experiment management and validation.

Provides ExperimentConfig, runner, and metrics computation for backtesting
different feature combinations against baseline.
"""

from .config import ExperimentConfig
from .metrics import ComputedMetrics
from .runner import HarnessRunner

__all__ = [
    "ComputedMetrics",
    "ExperimentConfig",
    "HarnessRunner",
]
