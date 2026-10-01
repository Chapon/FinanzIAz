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


# ── Tarea 254: sin preferencia, la primera cuenta ACTIVA ──────────────────────
# La cuenta 1 (cerrada) viene primera en la lista, así que el fallback viejo (índice 0) y el
# nuevo difieren: con el viejo, Métricas abría mostrando el score de la cuenta cerrada.


def test_sin_preferencia_abre_en_la_primera_cuenta_activa():
    assert pick_initial_account_index([1, 2], None, {2}) == 1


def test_preferida_ausente_cae_en_la_activa_y_no_en_la_primera():
    assert pick_initial_account_index([1, 2, 3], 99, {3}) == 2


def test_la_preferida_le_gana_a_la_activa():
    assert pick_initial_account_index([1, 2], 1, {2}) == 0


def test_sin_activas_cae_en_cero():
    assert pick_initial_account_index([1, 2], None, set()) == 0


def test_metrics_tab_no_fija_la_cuenta_1_por_default():
    import inspect

    from ui.metrics_tab import MetricsTab

    assert inspect.signature(MetricsTab.__init__).parameters["account_id"].default is None


def test_paper_tab_usa_la_misma_regla():
    import inspect

    from ui import paper_tab

    assert "pick_initial_account_index(" in inspect.getsource(paper_tab.PaperTradingTab._load_accounts)
