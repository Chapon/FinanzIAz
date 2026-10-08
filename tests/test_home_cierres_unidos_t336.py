"""Tarea 336 — Home usaba un solo frame de cierres por ticker y no valuaba lo que no tenía cierre.

El defecto (``docs/auditoria_tanda_2026-10-07.md`` [F-1]): ``cierres_del_cache`` elegía, por
ticker, el frame que termina más tarde —el ``1y``—, aunque el cache tuviera otro de 10 años. La
serie de Home arrancaba en el 2024-10 y, durante el primer año, el valor y la ganancia salían
~$3,5–4,9k por debajo: AAPL, TEAM, EMBJ y MLTX valían cero hasta el comienzo de su ``1y``, y su
entrada se leía como una suba.

Los casos están elegidos para que la versión correcta y la defectuosa **difieran**: el frame
viejo está en otra escala (como los del cache, bajados con ``auto_adjust`` antes de un
dividendo), así que pegarlo crudo deja un escalón; y la compra es anterior al frame corto.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

import database.cartera_real as cr
from database.cartera_real import ganancias_diarias, tenencia_sin_cierre, unir_cierres, valor_diario
from database.lotes import Movimiento

D0 = date(2025, 3, 3)


def _serie(desde: int, hasta: int, precio: float) -> pd.Series:
    idx = pd.DatetimeIndex([pd.Timestamp(D0 + timedelta(days=i)) for i in range(desde, hasta)])
    return pd.Series([precio] * len(idx), index=idx)


def _largo_viejo_y_corto_nuevo():
    # El largo (días 0–7) se bajó antes de un dividendo: está a 98 donde el nuevo dice 100.
    # El corto (días 5–9) es el que termina más tarde, y el único que miraba la versión vieja.
    return [_serie(0, 8, 98.0), _serie(5, 10, 100.0)]


def test_la_union_arranca_en_el_frame_largo_y_sin_escalon_en_la_costura():
    unida = unir_cierres(_largo_viejo_y_corto_nuevo())
    assert [d for d, _ in unida] == [D0 + timedelta(days=i) for i in range(10)]
    # Reescalado al nuevo: 98 × (100 / 98). Pegado crudo daría 98 y un +2 % falso el día 5.
    assert [c for _, c in unida] == pytest.approx([100.0] * 10)


def test_en_la_superposicion_gana_el_que_termina_mas_tarde():
    viejo = _serie(0, 8, 98.0)
    nuevo = _serie(5, 10, 100.0)
    nuevo.iloc[1] = 101.0  # día 6: el viejo dice 98
    unida = dict(unir_cierres([viejo, nuevo]))
    assert unida[D0 + timedelta(days=6)] == 101.0


def test_el_orden_de_los_frames_no_cambia_el_resultado():
    a, b = _largo_viejo_y_corto_nuevo()
    assert unir_cierres([a, b]) == unir_cierres([b, a])


def test_una_serie_sin_dias_en_comun_no_se_pega():
    # Sin superposición no hay con qué escalarla: queda afuera en vez de entrar en otra escala.
    unida = unir_cierres([_serie(0, 3, 50.0), _serie(5, 10, 100.0)])
    assert unida[0][0] == D0 + timedelta(days=5)


def test_cierres_del_cache_une_los_frames_y_home_no_tiene_escalon(monkeypatch):
    """El kill-criteria: frames largo-viejo y corto-nuevo, y una compra anterior al corto."""
    frames = [pd.DataFrame({"Close": s}) for s in _largo_viejo_y_corto_nuevo()]
    monkeypatch.setattr("data.parquet_cache.all_1d", lambda t: frames)
    cierres = cr.cierres_del_cache(["AAA"])
    serie, sin = valor_diario([(D0 + timedelta(days=1), "AAA", 10.0)], cierres)
    assert sin == []
    assert serie[0][0] == D0 + timedelta(days=1)  # desde la compra, no desde el frame corto
    assert [v for _, v in serie] == pytest.approx([1000.0] * 9)  # sin ceros y sin escalón


def test_un_ticker_comprado_antes_de_su_primer_cierre_no_suma_valor_ni_costo():
    # BBB se compra el día 0 y su primer cierre es el 3: esos días no tiene precio.
    movs = {
        "AAA": [Movimiento(D0, "BUY", 10, 100.0)],
        "BBB": [Movimiento(D0, "BUY", 4, 50.0)],
    }
    cierres = {
        "AAA": [(D0 + timedelta(days=i), 100.0) for i in range(6)],
        "BBB": [(D0 + timedelta(days=i), 50.0) for i in range(3, 6)],
    }
    serie, _ = ganancias_diarias(movs, cierres, {})
    assert [x["valor"] for _, x in serie] == pytest.approx([1000.0] * 3 + [1200.0] * 3)
    assert [x["costo"] for _, x in serie] == pytest.approx([1000.0] * 3 + [1200.0] * 3)
    # Antes el costo de BBB sumaba desde el día 0 y la ganancia caía −200 esos tres días.
    assert [x["total"] for _, x in serie] == pytest.approx([0.0] * 6)
    eventos = [(D0, "AAA", 10.0), (D0, "BBB", 4.0)]
    assert tenencia_sin_cierre(eventos, cierres) == {"BBB": (D0, D0 + timedelta(days=3))}


def test_un_ticker_sin_ningun_cierre_va_a_la_otra_lista_y_no_a_tenencia_sin_cierre():
    eventos = [(D0, "AAA", 1.0), (D0, "ZZZ", 1.0)]
    cierres = {"AAA": [(D0, 10.0), (D0 + timedelta(days=1), 10.0)]}
    _, sin = valor_diario(eventos, cierres)
    assert sin == ["ZZZ"]
    assert tenencia_sin_cierre(eventos, cierres) == {}
