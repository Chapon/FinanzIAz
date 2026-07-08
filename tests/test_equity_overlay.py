"""Tests de la alineación del overlay SPY en la curva de equity (V1).

Solo la función pura ``build_benchmark_overlay`` — no crea widgets Qt.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

import pytest

# Plataforma Qt offscreen antes de importar cualquier cosa Qt-backed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")
pytest.importorskip("matplotlib")

from ui.paper.equity_chart import build_benchmark_overlay  # noqa: E402


@dataclass
class _Snap:
    """Stand-in mínimo de PaperEquitySnapshot."""

    snapshot_at: datetime
    total_equity: float


def test_overlay_normalizes_to_start_equity_within_window():
    snaps = [_Snap(datetime(2026, 1, 1, 16), 50000.0),
             _Snap(datetime(2026, 1, 31, 16), 52000.0)]
    spy = [("2025-12-30", 390.0), ("2026-01-01", 400.0), ("2026-01-15", 410.0),
           ("2026-01-31", 420.0), ("2026-02-02", 430.0)]
    out = build_benchmark_overlay(snaps, spy)
    # Arranca en la equity inicial sobre la base (close del primer día de ventana).
    assert out[0] == (datetime.fromisoformat("2026-01-01"), pytest.approx(50000.0))
    # Escalado: 420/400 * 50000 = 52500 el último día de la ventana.
    assert out[-1][0] == datetime.fromisoformat("2026-01-31")
    assert out[-1][1] == pytest.approx(52500.0)
    # Excluye las barras fuera de [2026-01-01, 2026-01-31].
    assert all(datetime(2026, 1, 1) <= d <= datetime(2026, 1, 31) for d, _ in out)
    assert len(out) == 3


def test_overlay_empty_without_data():
    assert build_benchmark_overlay([], [("2026-01-01", 400.0)]) == []
    snaps = [_Snap(datetime(2026, 1, 1, 16), 50000.0)]
    assert build_benchmark_overlay(snaps, None) == []
    assert build_benchmark_overlay(snaps, []) == []
