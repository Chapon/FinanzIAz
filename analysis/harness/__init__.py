"""
T-harness for experiment management and validation.

Provides ExperimentConfig, runner, and metrics computation for backtesting
different feature combinations against baseline.
"""

from .config import ExperimentConfig
from .runner import HarnessRunner
from .metrics import ComputedMetrics

__all__ = [
    "ExperimentConfig",
    "HarnessRunner",
    "ComputedMetrics",
]
