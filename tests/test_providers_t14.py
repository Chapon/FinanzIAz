"""Tarea 14 (ARQ3) — la cadena de proveedores y el cross-check bilateral del precio.

**El hallazgo de la tarea, medido el 2026-09-07 contra los servicios reales:** no hay
hoy un proveedor EOD de fallback sin dar de alta una key nueva. Stooq bloqueó a los
clientes no-browser con una verificación proof-of-work en JavaScript, Tiingo pide una
``TIINGO_API_KEY`` que este entorno no tiene, y las velas diarias de Finnhub son
premium (``/stock/candle`` da 403 con la key que sí existe).

Lo que **sí** es viable es la otra mitad: el ``/quote`` de Finnhub funciona con esa
misma key y sirve como **fuente independiente** para desempatar cuando el precio y la
referencia cacheada discrepan — que es la mitad que mata la clase KLAC (un precio
corrupto que llegó a ejecutar un trade).

Todo offline: la regla de arbitraje es pura y se testea con números a mano.
"""

from __future__ import annotations

import pytest

from data.providers import (
    StooqProvider,
    TiingoProvider,
    arbitrate,
    default_chain,
    second_opinion,
)

BANDA = 0.10


# ── La regla de arbitraje (pura) ─────────────────────────────────────────────


def test_la_fuente_independiente_le_da_la_razon_al_PRECIO():
    """El caso tipo AVB: el precio actual es correcto y la referencia cacheada quedó
    en otra escala. La tercera fuente coincide con el precio ⇒ lo podrido es el cache.
    """
    assert arbitrate(320.0, 68.14, 319.97, band=BANDA) == "price"


def test_la_fuente_independiente_le_da_la_razon_a_la_REFERENCIA():
    """El caso tipo KLAC, que es el que importa: el precio actual vino ~10× corrupto y
    la referencia era la sana. Sin tercera fuente el guard sabe que algo está mal pero
    no cuál; con ella, sabe que **no puede operar con ese precio**."""
    assert arbitrate(1000.0, 100.0, 99.5, band=BANDA) == "reference"


def test_sin_opinion_cuando_la_tercera_fuente_no_llega():
    """Fail-open: el llamador es el guard del precio, así que una segunda opinión que
    no llega tiene que dejar la decisión como estaba, nunca frenar un fill por sí sola.
    """
    assert arbitrate(100.0, 100.0, None, band=BANDA) == "sin_opinion"
    assert arbitrate(100.0, 100.0, 0.0, band=BANDA) == "sin_opinion"
    assert arbitrate(0.0, 100.0, 99.0, band=BANDA) == "sin_opinion"


def test_con_los_dos_cerca_NO_desempata():
    """Contraprueba: si la banda es tan ancha que la tercera fuente respalda a los dos,
    decir que gana uno sería inventar información. Sin este test, devolver siempre
    'price' pasaría los dos primeros."""
    assert arbitrate(100.0, 101.0, 100.5, band=0.50) == "ninguno"


def test_con_NINGUNO_cerca_tampoco_desempata():
    """El otro borde: la tercera fuente discrepa de las dos, así que ninguna tiene
    respaldo y lo honesto es decirlo — no elegir la menos lejana."""
    assert arbitrate(100.0, 200.0, 5.0, band=BANDA) == "ninguno"


def test_la_banda_manda_y_no_un_umbral_escondido():
    """La misma terna cambia de veredicto según la banda; si no, el parámetro sería
    decorativo."""
    assert arbitrate(100.0, 130.0, 112.0, band=0.05) == "ninguno"
    assert arbitrate(100.0, 130.0, 112.0, band=0.20) == "ninguno"
    assert arbitrate(100.0, 130.0, 104.0, band=0.05) == "price"


# ── El estado de los proveedores, que ES el hallazgo ─────────────────────────


def test_stooq_esta_declarado_NO_disponible_con_su_motivo():
    """No se implementó el bypass del proof-of-work a propósito, y eso tiene que estar
    escrito donde alguien lo vaya a leer antes de volver a intentarlo."""
    p = StooqProvider()
    assert p.available() is False
    assert "proof-of-work" in (StooqProvider.__doc__ or "")


def test_tiingo_sin_key_no_esta_disponible_y_no_es_un_error(monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    p = TiingoProvider()
    assert p.available() is False
    assert p.daily("AAPL", "1y") is None  # no levanta: la cadena se acorta


def test_tiingo_con_key_SI_esta_disponible():
    """Contraprueba de la de arriba: si `available()` devolviera siempre False, el
    adaptador sería inalcanzable incluso con key y nadie lo notaría."""
    assert TiingoProvider(api_key="x").available() is True


def test_la_cadena_EOD_esta_vacia_hoy_y_eso_es_el_resultado(monkeypatch):
    """No es un bug: es lo que la tarea 14 midió. Si mañana alguien exporta una
    `TIINGO_API_KEY`, la cadena se arma sola y este test lo dice."""
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    assert default_chain() == []
    monkeypatch.setenv("TIINGO_API_KEY", "una-key")
    assert [p.name for p in default_chain()] == ["tiingo"]


def test_second_opinion_sin_key_devuelve_None_sin_pegar_a_la_red(monkeypatch):
    """El camino que corre en un entorno sin credenciales — y el que la suite ejercita,
    porque `conftest` bloquea la red."""
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.delenv("FINNHUB_TOKEN", raising=False)
    assert second_opinion("AAPL") is None


def test_second_opinion_es_fail_open_si_la_red_falla(monkeypatch):
    """Un guard de precio no puede propagar una excepción de red: frenaría un fill por
    no poder consultar una opinión que es opcional."""
    import requests

    monkeypatch.setenv("FINNHUB_API_KEY", "x")

    def _explota(*a, **k):
        raise requests.RequestException("sin red")

    monkeypatch.setattr(requests, "get", _explota)
    assert second_opinion("AAPL") is None


def test_second_opinion_descarta_un_precio_no_positivo(monkeypatch):
    """Finnhub devuelve `c: 0` para un símbolo que no conoce. Un 0 tomado como precio
    haría que el arbitraje respalde a cualquiera."""
    import requests

    monkeypatch.setenv("FINNHUB_API_KEY", "x")

    class _R:
        def raise_for_status(self):
            return None

        def json(self):
            return {"c": 0}

    monkeypatch.setattr(requests, "get", lambda *a, **k: _R())
    assert second_opinion("XXXX") is None


@pytest.mark.parametrize("periodo", ["1d", "1y", "10y", "max"])
def test_los_periodos_de_yahoo_tienen_traduccion(periodo):
    """Los proveedores de fallback no hablan el vocabulario de Yahoo. Si falta un
    período, el adaptador traería la serie entera sin recortar y el caller recibiría
    otra cosa que la que pidió."""
    from data.providers import _DIAS_POR_PERIODO

    assert _DIAS_POR_PERIODO.get(periodo, 0) > 0
