"""Tarea 127 — la segunda opinión entra al guard del precio, y entra donde no rompe.

El sanity E5 es **unilateral**: compara el precio contra el último close cacheado.
Cuando discrepan sabe que **algo** está podrido pero no cuál, y por defecto **acepta el
precio** — bloquear contra una referencia dudosa deja la posición sin salida.

Con una fuente **independiente** eso deja de ser un default y pasa a ser una decisión.
Lo delicado es **dónde** se inserta: `unreliable_reference` la comparten el guard del
fetch y el del engine, y el invariante de la tarea 63 exige que los dos lleguen al
mismo veredicto — si el fetch rechaza un precio que el engine acepta, el engine se
queda **sin precio para vender**.
"""

from __future__ import annotations

import pytest

from data import yahoo_finance as yfm


@pytest.fixture(autouse=True)
def _memo_limpio():
    yfm._clear_second_opinion_cache()
    yield
    yfm._clear_second_opinion_cache()


@pytest.fixture
def disputa(monkeypatch):
    """Fuerza el caso ambiguo: los frames cacheados discrepan sobre el precio."""
    monkeypatch.setattr(yfm, "scale_is_disputed", lambda *a, **k: True)
    monkeypatch.setattr(yfm, "_price_sanity_band", lambda: 0.50)


def _opinion(valor):
    return lambda ticker, allow_network=True: valor


# ── Con el flag OFF no cambia nada ───────────────────────────────────────────


def test_con_el_flag_OFF_el_comportamiento_es_EXACTAMENTE_el_de_antes(disputa, monkeypatch):
    """La mitad que importa de un default OFF: shipear esto no puede mover el guard.
    Con la referencia en disputa se sigue devolviendo el motivo (⇒ el precio se acepta).
    """
    monkeypatch.setattr(yfm, "_second_opinion_enabled", lambda: False)
    llamadas = []
    monkeypatch.setattr(yfm, "independent_price", lambda *a, **k: llamadas.append(1))
    motivo = yfm.unreliable_reference("KLAC", 1942.70, 194.0, allow_network=True)
    assert motivo is not None and "disputa" in motivo
    assert llamadas == [], "con el flag OFF ni siquiera se consulta la fuente"


# ── Con el flag ON: los dos casos que importan ───────────────────────────────


def test_KLAC_la_fuente_independiente_respalda_la_REFERENCIA_y_el_precio_se_rechaza(disputa, monkeypatch):
    """El caso que motivó ARQ3: un precio ~10× corrupto que llegó a ejecutar un trade.
    La tercera fuente coincide con la referencia ⇒ el podrido es el precio."""
    monkeypatch.setattr(yfm, "_second_opinion_enabled", lambda: True)
    monkeypatch.setattr(yfm, "independent_price", _opinion(195.0))
    assert yfm.unreliable_reference("KLAC", 1942.70, 194.0, allow_network=True) is None


def test_AVB_la_fuente_independiente_respalda_el_PRECIO_y_no_se_toca_nada(disputa, monkeypatch):
    """El caso simétrico y el que impide que esto se vuelva un bloqueador: si la
    tercera fuente respalda al **precio**, la referencia sí era dudosa y el precio se
    sigue aceptando, como antes."""
    monkeypatch.setattr(yfm, "_second_opinion_enabled", lambda: True)
    monkeypatch.setattr(yfm, "independent_price", _opinion(184.0))
    motivo = yfm.unreliable_reference("AVB", 184.06, 68.14, allow_network=True)
    assert motivo is not None, "respaldando el precio, la referencia sigue siendo la dudosa"


def test_sin_segunda_opinion_queda_como_estaba(disputa, monkeypatch):
    """Fail-open: una fuente que no contesta no puede cambiar el veredicto ni tirar."""
    monkeypatch.setattr(yfm, "_second_opinion_enabled", lambda: True)
    monkeypatch.setattr(yfm, "independent_price", _opinion(None))
    assert yfm.unreliable_reference("KLAC", 1942.70, 194.0, allow_network=True) is not None


def test_si_la_fuente_independiente_EXPLOTA_el_guard_sigue(disputa, monkeypatch):
    """El guard corre en el camino de precios: una excepción de red no puede
    propagarse desde acá."""
    monkeypatch.setattr(yfm, "_second_opinion_enabled", lambda: True)

    def _boom(*a, **k):
        raise RuntimeError("sin red")

    monkeypatch.setattr(yfm, "independent_price", _boom)
    # La excepción NO puede subir: el guard tiene que seguir y quedar como estaba.
    assert yfm.unreliable_reference("KLAC", 1942.70, 194.0, allow_network=True) is not None


# ── El memo: el engine no puede pegar a la red ───────────────────────────────


def test_el_engine_NO_pega_a_la_red_pero_usa_lo_memoizado(monkeypatch):
    """El patrón de `recent_split_factor`, y el motivo es el mismo: un fill no puede
    colgarse esperando a una API, pero sí aprovechar lo que el fetch ya aprendió.
    Sin esto, el fetch y el engine llegarían a veredictos distintos sobre el mismo
    precio — que es cómo una posición queda sin poder venderse (invariante de la 63).
    """
    llamadas = []

    def _fuente(ticker, **kw):
        llamadas.append(ticker)
        return 195.0

    monkeypatch.setattr("data.providers.second_opinion", _fuente)

    # Sin memo y sin red: no consulta y no sabe nada.
    assert yfm.independent_price("KLAC", allow_network=False) is None
    assert llamadas == []

    # El fetch (con red) lo aprende y lo memoiza.
    assert yfm.independent_price("KLAC", allow_network=True) == 195.0
    assert llamadas == ["KLAC"]

    # Ahora el engine lo aprovecha SIN red.
    assert yfm.independent_price("KLAC", allow_network=False) == 195.0
    assert llamadas == ["KLAC"], "el engine no puede haber consultado de nuevo"


def test_el_memo_no_reconsulta_dentro_del_TTL(monkeypatch):
    llamadas = []
    monkeypatch.setattr("data.providers.second_opinion", lambda t, **k: (llamadas.append(t), 100.0)[1])
    for _ in range(5):
        assert yfm.independent_price("XXX", allow_network=True) == 100.0
    assert len(llamadas) == 1, f"consultó {len(llamadas)} veces dentro del TTL"


def test_un_fallo_de_la_fuente_tambien_se_memoiza(monkeypatch):
    """Si no se memoizara el None, un ticker sin cobertura consultaría en cada precio
    fuera de banda — que es el defecto que la tarea 19 tuvo que arreglar en el GARCH."""
    llamadas = []

    def _falla(t, **k):
        llamadas.append(t)
        raise RuntimeError("sin red")

    monkeypatch.setattr("data.providers.second_opinion", _falla)
    assert yfm.independent_price("YYY", allow_network=True) is None
    assert yfm.independent_price("YYY", allow_network=True) is None
    assert len(llamadas) == 1, "el None tiene que quedar memoizado"


# ── El invariante que hizo diferir esto en la tarea 14 ───────────────────────


def test_el_fetch_y_el_engine_siguen_coincidiendo_con_el_flag_ON(disputa, monkeypatch):
    """El invariante de la 63, ahora con la segunda opinión encendida. Se sostiene por
    **construcción**: los dos guards llaman a `unreliable_reference`, así que la
    decisión es la misma función. Este test lo fija para que nadie la mueva a
    `_reject_if_out_of_band`, que sólo llama el fetch.
    """
    import inspect

    fuente_fetch = inspect.getsource(yfm._reject_if_out_of_band)
    assert "unreliable_reference" in fuente_fetch
    assert "independent_price" not in fuente_fetch, (
        "la segunda opinión no puede vivir en el guard del fetch: rompería la simetría "
        "con el engine y dejaría posiciones sin poder venderse"
    )
