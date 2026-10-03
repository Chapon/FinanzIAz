"""Tarea 279 — una revisión de consenso medida a través de un split no mide el split.

El caso real (``docs/auditoria_datos_2026-10-02.md`` [D-2]): KLAC partió 10:1 y su EPS de consenso
cayó de 9,95 a 0,995 el mismo día. Sin ajustar, la revisión da −90%.
"""

from __future__ import annotations

import pytest

from analysis.consenso_pit import ajustar_por_split, revision

KLAC_EPS = [("2026-06-10", 9.90), ("2026-06-11", 9.95), ("2026-06-12", 0.995), ("2026-06-15", 1.0)]
KLAC_SPLIT = [("2026-06-12", 10.0)]


def test_el_split_de_KLAC_no_es_una_revision():
    assert revision(KLAC_EPS, [], "eps") == pytest.approx(1.0 / 9.90 - 1.0), "sin ajustar: el −90% del split"
    assert revision(KLAC_EPS, KLAC_SPLIT, "eps") == pytest.approx(1.0 / 0.990 - 1.0)


def test_un_split_sintetico_SIN_cambio_real_da_revision_cero():
    """El kill-criteria de la tarea: con el consenso quieto, el split no puede mover la revisión."""
    serie = [("2026-06-01", 10.0), ("2026-06-12", 1.0)]
    assert revision(serie, KLAC_SPLIT, "eps") == pytest.approx(0.0)
    assert revision(serie, KLAC_SPLIT, "price_target") == pytest.approx(0.0)


def test_el_snapshot_del_DIA_del_ex_date_ya_esta_en_la_escala_nueva():
    assert ajustar_por_split([("2026-06-12", 0.995)], KLAC_SPLIT, "eps") == [("2026-06-12", 0.995)]


def test_revenue_y_rec_mean_no_se_ajustan():
    serie = [("2026-06-01", 4.0e9), ("2026-06-15", 4.1e9)]
    assert ajustar_por_split(serie, KLAC_SPLIT, "revenue") == serie
    assert ajustar_por_split([("2026-06-01", 2.1)], KLAC_SPLIT, "rec_mean") == [("2026-06-01", 2.1)]


def test_dos_splits_se_encadenan():
    serie = [("2026-01-01", 40.0), ("2026-12-01", 5.0)]
    assert revision(serie, [("2026-03-01", 2.0), ("2026-09-01", 4.0)], "eps") == pytest.approx(0.0)


def test_la_revision_es_relativa_y_cancela_la_moneda():
    """El revenue de TSM viene en TWD: un cociente dentro del ticker no depende de la moneda."""
    en_twd = [("2026-07-01", 3.0e12), ("2026-09-01", 3.3e12)]
    en_usd = [(d, v / 32.0) for d, v in en_twd]
    assert revision(en_twd, [], "revenue") == pytest.approx(revision(en_usd, [], "revenue"))


def test_sin_base_no_hay_revision():
    assert revision([("2026-06-01", 1.0)], [], "eps") is None
    assert revision([("2026-06-01", 0.0), ("2026-06-02", 1.0)], [], "eps") is None
