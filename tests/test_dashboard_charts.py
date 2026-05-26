"""
Smoke tests for the Fuse-style Home dashboard widgets.

These only check that the widgets construct and accept data without raising —
they do not assert on pixels. Skipped automatically if PyQt6 isn't available
(e.g. a headless CI image without the Qt runtime).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

# Force an offscreen Qt platform before importing anything Qt-backed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")
pytest.importorskip("matplotlib")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from ui.dashboard_charts import AreaChartHero, DonutChart, KpiCard  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@dataclass
class _Snap:
    """Minimal stand-in for PaperEquitySnapshot."""

    snapshot_at: datetime
    total_equity: float


def _curve(n: int = 30) -> list[_Snap]:
    base = datetime(2026, 5, 1)
    return [_Snap(base + timedelta(hours=i), 50_000 + i * 120 + (i % 5) * 60) for i in range(n)]


def test_area_chart_hero_handles_data_and_empty(qapp):
    chart = AreaChartHero()
    chart.set_data(_curve())       # normal series → gradient path
    chart.set_data([])             # empty → "sin datos" path, must not raise
    chart.set_data(_curve(1))      # single point → fallback fill path
    chart.cleanup()


def test_kpi_card_value_and_sparklines(qapp):
    for kind in ("area", "bar", "spike"):
        card = KpiCard("TEST", kind=kind)
        card.set_value("$50,000", delta="+2.5%", delta_positive=True)
        card.set_series([1, 2, 3, 2, 4, 5])
        card.set_series([])        # empty series must not raise
        card.set_value("0", delta="", delta_positive=None)


def test_donut_chart_allocation_and_long_tail(qapp):
    donut = DonutChart("Distribución")
    donut.set_data([("AAPL", 4280), ("MSFT", 3110), ("NVDA", 900)])
    # More than max_legend entries → collapses tail into "Resto"
    donut.set_data([(f"T{i}", 100 - i) for i in range(10)])
    donut.set_data([])             # empty → "sin posiciones" path
    donut.set_data([("X", 0.0)])   # all-zero filtered out → empty path
    donut.cleanup()
