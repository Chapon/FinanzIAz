"""Tests for the ACC1 pause/resume toggle decision logic in ``ui.paper_tab``.

Only the pure decision helper ``needs_pause_confirmation`` is exercised here —
no Qt event loop is needed (importing the module just defines the widget
classes; the function itself has no Qt dependency).
"""

from __future__ import annotations

from ui.paper_tab import needs_pause_confirmation


def test_needs_pause_confirmation_empty_account():
    # Sin posiciones abiertas ni órdenes pendientes → pausar sin confirmar.
    assert needs_pause_confirmation([], []) is False


def test_needs_pause_confirmation_with_open_positions():
    # Hay posiciones abiertas que se quedan sin stops → confirmar.
    assert needs_pause_confirmation([object()], []) is True


def test_needs_pause_confirmation_with_pending_orders():
    # Hay órdenes pendientes que no se van a llenar → confirmar.
    assert needs_pause_confirmation([], [object()]) is True


def test_needs_pause_confirmation_with_both():
    assert needs_pause_confirmation([object()], [object()]) is True
