"""Tarea 393 — un frame degenerado más fresco no tapa la historia de un ticker.

``unir_cierres`` (la 336) toma como base la serie que termina más tarde y no pega una vieja
**sin días en común**: no hay con qué reescalarla. Con WBD, el frame más fresco era un ``2y`` de
**una fila** (2026-10-05), posterior a todo el resto (hasta el 09/09): la unión quedaba en un
cierre, posterior al alta de la cuenta, y Home decía *«afuera, sin precio al alta»* de un
ticker que cotizaba (`docs/auditoria_tanda_2026-10-23.md` [F-1]).

Ahora una vieja sin días en común se pega cruda si es **más larga** que lo ya unido. La
regla de la 336 sigue para el caso que la motivó (una vieja corta no se pega): lo fija
``test_una_serie_sin_dias_en_comun_no_se_pega`` en ``test_home_cierres_unidos_t336.py``.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

import database.cartera_real as cr
from database.cartera_real import unir_cierres

D0 = date(2026, 1, 5)


def _serie(desde: int, hasta: int, precio: float) -> pd.Series:
    idx = pd.DatetimeIndex([pd.Timestamp(D0 + timedelta(days=i)) for i in range(desde, hasta)])
    return pd.Series([precio] * len(idx), index=idx)


def _historia_y_una_fila_despues():
    # El caso del kill-criteria: la larga hasta el día d=99, y una de UNA fila en d + 20.
    return [_serie(0, 100, 50.0), _serie(119, 120, 55.0)]


def test_la_union_conserva_la_historia_ante_un_frame_de_una_fila_mas_fresco():
    unida = unir_cierres(_historia_y_una_fila_despues())
    assert len(unida) == 101, "antes de la 393 quedaba UN cierre"
    assert unida[0] == (D0, 50.0)
    assert unida[-1] == (D0 + timedelta(days=119), 55.0)
    # Pegada cruda: no hay día común con qué reescalarla.
    assert [c for _, c in unida[:100]] == pytest.approx([50.0] * 100)


def test_el_orden_de_los_frames_sigue_sin_cambiar_el_resultado():
    a, b = _historia_y_una_fila_despues()
    assert unir_cierres([a, b]) == unir_cierres([b, a])


def test_una_tercera_mas_vieja_se_reescala_contra_la_historia_pegada():
    """Lo pegado crudo pasa a ser la base de lo que viene: una más vieja que se superpone con
    ella se reescala como siempre (la regla de la 336)."""
    mas_vieja = _serie(-30, 10, 49.0)  # se superpone con la larga en los días 0-9
    unida = dict(unir_cierres([*_historia_y_una_fila_despues(), mas_vieja]))
    assert unida[D0 - timedelta(days=30)] == pytest.approx(49.0 * 50.0 / 49.0)


def test_cierres_del_cache_le_devuelve_la_historia_a_wbd(monkeypatch):
    frames = [pd.DataFrame({"Close": s}) for s in _historia_y_una_fila_despues()]
    monkeypatch.setattr("data.parquet_cache.all_1d", lambda t: frames)
    cierres = cr.cierres_del_cache(["WBD"])
    assert len(cierres["WBD"]) == 101
    assert cierres["WBD"][0][0] == D0
