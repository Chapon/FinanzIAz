"""Tarea 383 — valuación en Analysis: Graham, Buffettology y Lynch sobre los fundamentals de la 382.

Display-only: el último test verifica que nada del motor la importe.
"""

from __future__ import annotations

import ast
import math
import os
from pathlib import Path

import pytest

from analysis.valuation import (
    categoria_lynch,
    crecimiento_anual,
    margen_de_seguridad,
    numero_graham,
    pe_historico,
    valuar,
)
from data.fundamentos_pit import Fundamentos, Registro

_REPO = Path(__file__).resolve().parent.parent


def test_numero_graham_y_margen():
    assert numero_graham(4.0, 25.0) == pytest.approx(math.sqrt(2250))
    assert numero_graham(-1.0, 25.0) is None
    assert numero_graham(4.0, 0.0) is None
    assert margen_de_seguridad(40.0, 50.0) == pytest.approx(0.2)
    assert margen_de_seguridad(60.0, 50.0) == pytest.approx(-0.2)


def test_el_crecimiento_usa_la_ventana_pedida():
    """1, 1, 2, 4: en 3 años crece 58,7% anual; en los últimos 2, 100%."""
    serie = [("2019", 1.0), ("2020", 1.0), ("2021", 2.0), ("2022", 4.0)]
    assert crecimiento_anual(serie, 3) == (pytest.approx(4 ** (1 / 3) - 1), 3)
    assert crecimiento_anual(serie, 2) == (pytest.approx(1.0), 2)


def test_sin_crecimiento_desde_una_perdida_o_con_poca_historia():
    assert crecimiento_anual([("a", -1.0), ("b", 1.0), ("c", 2.0), ("d", 3.0)], 5)[0] is None
    assert crecimiento_anual([("a", 1.0), ("b", 2.0), ("c", 3.0)], 5)[0] is None


def test_pe_historico_usa_el_ultimo_cierre_antes_del_fin_de_anio_y_saltea_perdidas():
    """El 31/12/2021 no hubo rueda: vale el cierre del 30. Pidiendo el día exacto quedarían 2 años."""
    eps = [("2019-12-31", 2.0), ("2020-12-31", -1.0), ("2021-12-31", 4.0), ("2022-12-31", 5.0)]
    cierres = [("2019-12-31", 40.0), ("2020-12-31", 50.0), ("2021-12-30", 60.0), ("2022-12-30", 100.0)]
    assert pe_historico(eps, cierres) == (pytest.approx(20.0), 3)


@pytest.mark.parametrize(
    "eps,esperada",
    [
        ([1.0, -1.0, 2.0, 3.0], "recuperación"),
        ([1.0, 2.0, 1.0, 2.0], "cíclica"),
        ([100.0, 101.0, 102.0, 103.0, 104.0], "crecimiento lento"),
        ([100.0, 108.0, 116.0, 126.0], "firme"),
        ([100.0, 130.0, 170.0, 220.0], "crecimiento rápido"),
        ([1.0, 2.0, 3.0], None),
    ],
)
def test_categoria_lynch(eps, esperada):
    serie = [(f"20{10 + i}-12-31", v) for i, v in enumerate(eps)]
    assert categoria_lynch(serie)[0] == esperada


def _r(concepto, end, filed, val):
    return Registro(concepto, end, filed, val, "10-K", "X")


def _empresa_con_split() -> Fundamentos:
    """Gana 5, 6 y 7 por acción, hace un split de 2 a 1 el 2022-06-01 y gana 8.

    EDGAR guarda los tres primeros en la base de antes (10, 12, 14): sin el ajuste, el EPS cae.
    """
    regs = [
        _r("eps_diluido", "2019-12-31", "2020-02-01", 10.0),
        _r("eps_diluido", "2020-12-31", "2021-02-01", 12.0),
        _r("eps_diluido", "2021-12-31", "2022-02-01", 14.0),
        _r("eps_diluido", "2022-12-31", "2023-02-01", 8.0),
        _r("acciones_diluidas", "2022-12-31", "2023-02-01", 100.0),
        _r("acciones_diluidas", "2021-12-31", "2022-02-01", 50.0),
        _r("patrimonio", "2022-12-31", "2023-02-01", 4000.0),
    ]
    return Fundamentos(ticker="X", registros=regs)


SPLITS = [("2022-06-01", 2.0)]
CIERRES = [("2019-12-31", 100.0), ("2020-12-31", 120.0), ("2021-12-31", 140.0), ("2022-12-30", 160.0)]


def test_el_split_lleva_los_numeros_por_accion_a_la_base_de_hoy():
    f = _empresa_con_split()
    assert [v for _, v in f.serie("eps_diluido", "2024-01-01", SPLITS)] == [5.0, 6.0, 7.0, 8.0]
    assert dict(f.serie("acciones_diluidas", "2024-01-01", SPLITS)) == {
        "2021-12-31": 100.0,
        "2022-12-31": 100.0,
    }
    # Un split anterior al filed no se aplica: ese número ya está en la base de después.
    assert [v for _, v in f.serie("eps_diluido", "2024-01-01", [("2019-01-01", 2.0)])] == [
        10.0,
        12.0,
        14.0,
        8.0,
    ]


def test_valuar_de_punta_a_punta_con_el_split():
    v = valuar(_empresa_con_split(), 160.0, CIERRES, "2024-01-01", SPLITS)
    assert v.eps == 8.0
    assert v.crecimiento == pytest.approx((8 / 5) ** (1 / 3) - 1)  # sin el ajuste daría negativo
    assert v.pe_historico == pytest.approx(20.0)  # 100/5, 120/6, 140/7, 160/8
    # Con PE 20 y precio 160, crecer al tope de 15% da exactamente 15% anual.
    assert v.retorno_anual == pytest.approx(0.15)
    assert v.precio_max_objetivo == pytest.approx(160.0)
    assert "crecimiento topeado en 15%" in v.avisos
    assert v.valor_libro_x_accion == pytest.approx(40.0)
    assert v.numero_graham == pytest.approx(math.sqrt(22.5 * 8 * 40))
    assert v.peg == pytest.approx(20 / (((8 / 5) ** (1 / 3) - 1) * 100))
    assert v.categoria == "crecimiento rápido"


def test_valuar_sin_splits_daria_otra_cosa():
    """Control: sin el ajuste el EPS cae de 14 a 8 y la proyección se desarma."""
    v = valuar(_empresa_con_split(), 160.0, CIERRES, "2024-01-01", None)
    assert v.crecimiento == pytest.approx((8 / 10) ** (1 / 3) - 1)
    assert v.retorno_anual is None or v.retorno_anual < 0.15


def test_no_valua_extranjeras_ni_sin_precio():
    f = _empresa_con_split()
    assert valuar(f, None, CIERRES, "2024-01-01", SPLITS) is None
    f.extranjera = True
    assert valuar(f, 160.0, CIERRES, "2024-01-01", SPLITS) is None


def test_el_worker_no_rompe_el_analisis_si_la_valuacion_falla(monkeypatch):
    from data import fundamentos_pit as fp
    from ui.analysis import worker

    def _explota(_t):
        raise RuntimeError("disco roto")

    monkeypatch.setattr(fp, "cargar", _explota)
    assert worker.valuacion_de("X", 100.0) is None


def test_el_worker_arma_la_valuacion_con_cierres_sin_dividendos_y_splits(monkeypatch):
    from datetime import date

    from data import fundamentos_pit as fp
    from data import yahoo_finance as yf
    from ui.analysis import worker

    f = _empresa_con_split()
    f.generado = date.today().isoformat()  # fresco: no va a la red
    monkeypatch.setattr(fp, "cargar", lambda _t: f)
    monkeypatch.setattr(yf, "get_cierres_sin_ajuste_por_dividendos", lambda _t: CIERRES)
    monkeypatch.setattr(yf, "get_split_events", lambda _t: SPLITS)
    v = worker.valuacion_de("X", None)  # sin precio: usa el último cierre
    assert v.precio == 160.0
    assert v.retorno_anual == pytest.approx(0.15)


def test_la_tarjeta_se_calla_sin_datos_y_muestra_las_tres_miradas():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    global _APP
    _APP = QApplication.instance() or QApplication([])
    from ui.analysis.valuation_card import ValuationCard

    card = ValuationCard()
    card.set_data(valuar(_empresa_con_split(), 160.0, CIERRES, "2024-01-01", SPLITS))
    assert not card.isHidden()
    texto = card.cuerpo.text()
    assert "Graham:" in texto and "margen de seguridad -88.6%" in texto
    assert "+15.0% anual comprando hoy" in texto
    assert "el precio máximo es $160.00" in texto
    assert "Lynch: PEG" in texto and "crecimiento rápido" in texto
    assert "no entra en ninguna decisión" in card.pie.text()
    # Primero se mostró: si None no la ocultara, quedaría la valuación del ticker anterior.
    card.set_data(None)
    assert card.isHidden()
    card.deleteLater()


def test_nada_del_motor_importa_la_valuacion():
    """Regla 3: display-only. Ni el motor, ni las estrategias, ni el screen la pueden leer."""
    culpables = []
    for carpeta in ("paper_trading", "analysis"):
        for p in (_REPO / carpeta).glob("*.py"):
            if p.name == "valuation.py":
                continue
            arbol = ast.parse(p.read_text(encoding="utf-8"))
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.module.endswith("valuation"):
                    culpables.append(p.name)
                if isinstance(nodo, ast.Import) and any(a.name.endswith("valuation") for a in nodo.names):
                    culpables.append(p.name)
    assert culpables == []
