"""Tests para la selección inicial del combo de cuenta en la pestaña Métricas (MET1).

Solo se ejercita la función pura ``pick_initial_account_index`` — importar el
módulo define las clases, no necesita un event loop Qt.
"""

from __future__ import annotations

from ui.metrics_tab import pick_initial_account_index


def test_prefers_current_id():
    # El id preferido está en la lista → devuelve su índice.
    assert pick_initial_account_index([3, 1, 2], 2) == 2


def test_falls_back_to_zero_when_absent():
    # El id preferido ya no existe → índice 0 (primera cuenta).
    assert pick_initial_account_index([3, 1, 2], 99) == 0


def test_none_preferred_falls_back_to_zero():
    assert pick_initial_account_index([3, 1, 2], None) == 0


def test_empty_list():
    assert pick_initial_account_index([], 1) == 0
