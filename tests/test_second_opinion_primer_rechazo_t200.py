"""Tarea 200 — la segunda opinión se consulta desde el PRIMER precio fuera de banda.

`_reject_if_out_of_band` llamaba a `unreliable_reference` con una sola llave de red,
``allow_network=(n >= _ESCALATE_AFTER)``, y esa llave gobernaba **dos** consultas: los
splits del proveedor y la segunda opinión de Finnhub. Con los frames en disputa, eso
dejaba a Finnhub **sin consultar** en el primer y segundo precio fuera de banda: el
veredicto era ``sin_opinion``, el precio se aceptaba, y el guard del engine —que corre
sin red y lee el memo— tampoco frenaba la venta. Es exactamente el caso que el flag vino
a tapar: un precio corrupto **puntual** (KLAC), que aparece una o dos veces y no llega a
racha.

**Por qué se separan las llaves y no se abre la red para todo:** la racha tiene sentido
para los splits —consultarlos en cada rechazo aislado es caro, y E5 ya bloquea la
corrupción pasajera—. Para la segunda opinión no: sólo corre con los frames en disputa,
que ya es el camino raro, y queda memoizada 15 minutos para el engine.

Los tests van de punta a punta por las dos funciones que usa un scan de verdad: el guard
del fetch (`_reject_if_out_of_band`) y el del fill (`engine._price_out_of_band`). Lo único
simulado es la red de Finnhub y el estado del cache.
"""

from __future__ import annotations

import pytest

from data import yahoo_finance as yfm
from paper_trading import engine

PRECIO_CORRUPTO = 1942.70  # ~10× — el caso KLAC
CIERRE_GUARDADO = 194.0
FINNHUB_REAL = 195.0


@pytest.fixture
def escenario(monkeypatch):
    """Frames en disputa, un cierre guardado, y una Finnhub que cuenta sus llamadas."""
    yfm._clear_second_opinion_cache()
    yfm._clear_out_of_band_streak("KLAC")
    monkeypatch.setattr(yfm, "_price_sanity_band", lambda: 0.50)
    monkeypatch.setattr(yfm, "reference_close", lambda t: CIERRE_GUARDADO)
    monkeypatch.setattr(yfm, "scale_is_disputed", lambda *a, **k: True)
    llamadas: list[str] = []

    def _finnhub(ticker, **kw):
        llamadas.append(ticker)
        return FINNHUB_REAL

    monkeypatch.setattr("data.providers.second_opinion", _finnhub)
    yield llamadas
    yfm._clear_second_opinion_cache()
    yfm._clear_out_of_band_streak("KLAC")


def _fetch(precio=PRECIO_CORRUPTO):
    return yfm._reject_if_out_of_band("KLAC", {"price": precio})


def test_con_el_flag_ON_el_PRIMER_precio_corrupto_ya_se_rechaza(escenario, monkeypatch):
    """El kill-criteria de la 200. Antes, este fetch devolvía el info (precio aceptado)
    y Finnhub ni se consultaba."""
    monkeypatch.setattr(yfm, "_second_opinion_enabled", lambda: True)
    assert _fetch() is None, "el primer precio ~10× corrupto tiene que rechazarse"
    assert escenario == ["KLAC"], "Finnhub se consulta en el primer rechazo, una sola vez"


def test_la_venta_del_engine_en_el_MISMO_scan_ve_el_veredicto_sin_pegar_a_la_red(escenario, monkeypatch):
    """El scan pide precios (fetch) antes del guard del fill: el engine tiene que llegar al
    mismo veredicto leyendo el memo, sin consultar de nuevo — el invariante de la 63."""
    monkeypatch.setattr(yfm, "_second_opinion_enabled", lambda: True)
    _fetch()
    assert engine._price_out_of_band("KLAC", PRECIO_CORRUPTO, "SELL") is True, "la venta se frena"
    assert escenario == ["KLAC"], "el engine no puede haber consultado a Finnhub"


def test_el_engine_SOLO_nunca_pega_a_la_red(escenario, monkeypatch):
    """Sin un fetch previo, el engine no sabe nada y no consulta: queda como antes (la
    venta no se frena con la referencia en disputa)."""
    monkeypatch.setattr(yfm, "_second_opinion_enabled", lambda: True)
    assert engine._price_out_of_band("KLAC", PRECIO_CORRUPTO, "SELL") is False
    assert escenario == []


def test_dentro_del_TTL_los_rechazos_siguientes_no_reconsultan(escenario, monkeypatch):
    monkeypatch.setattr(yfm, "_second_opinion_enabled", lambda: True)
    for _ in range(4):
        assert _fetch() is None
    assert escenario == ["KLAC"], f"consultó {len(escenario)} veces dentro del TTL"


def test_con_el_flag_OFF_cero_llamadas_y_el_precio_se_acepta_como_antes(escenario, monkeypatch):
    monkeypatch.setattr(yfm, "_second_opinion_enabled", lambda: False)
    for _ in range(4):
        assert _fetch() is not None, "con el flag OFF la disputa sigue aceptando el precio"
    assert escenario == [], "con el flag OFF no se consulta Finnhub nunca"


def test_si_Finnhub_avala_el_PRECIO_se_acepta_desde_el_primer_rechazo(escenario, monkeypatch):
    """El caso AVB: la referencia es la podrida. Consultar antes no puede volverse un
    bloqueador de precios buenos."""
    monkeypatch.setattr(yfm, "_second_opinion_enabled", lambda: True)
    monkeypatch.setattr(
        "data.providers.second_opinion", lambda t, **k: escenario.append(t) or PRECIO_CORRUPTO
    )
    assert _fetch() is not None
    assert escenario == ["KLAC"]


def test_la_consulta_de_SPLITS_sigue_esperando_la_racha(monkeypatch):
    """Lo que la 200 NO cambia: sin disputa, los splits del proveedor se consultan recién
    al tercer rechazo. Abrir la red para todo habría sido el arreglo fácil y el caro."""
    yfm._clear_out_of_band_streak("QQQQ")
    monkeypatch.setattr(yfm, "_price_sanity_band", lambda: 0.50)
    monkeypatch.setattr(yfm, "reference_close", lambda t: 100.0)
    monkeypatch.setattr(yfm, "scale_is_disputed", lambda *a, **k: False)
    redes: list[bool] = []

    def _splits(ticker, *a, allow_network=True, **k):
        redes.append(allow_network)
        return None

    monkeypatch.setattr(yfm, "recent_split_factor", _splits)
    try:
        for _ in range(3):
            yfm._reject_if_out_of_band("QQQQ", {"price": 1000.0})
    finally:
        yfm._clear_out_of_band_streak("QQQQ")
    assert redes == [False, False, True]
