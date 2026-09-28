"""Tarea 206 — MAYORIA-DE-TRES-NO-EXISTE.

La regla de Chapa (2026-09-13) es de **tres** fuentes —manda la mayoría—, y `arbitrate()`
implementaba la de **dos**. Ahora vota: Yahoo, Finnhub y Tiingo son tres precios, y dos que
difieren menos que la banda coinciden. Las tres salidas que la regla dejaba abiertas las
decidió Chapa el 2026-09-28:

* **sin mayoría** ⇒ igual que hoy (`ninguno`: sin precio ese scan y aviso);
* **ninguna externa contesta** ⇒ como hoy (`sin_opinion`: se acepta Yahoo);
* **las dos externas coinciden lejos de las dos cosas de Yahoo** ⇒ manda la mayoría.

Es una regla pura, y se testea con números a mano (la lección de la 120). La tabla incluye
casos donde la regla de tres y la de dos **dan distinto**: sin ellos, una `arbitrate_votes`
que delegara siempre en la vieja pasaría igual.
"""

from __future__ import annotations

import pytest

from data import providers as pv
from data import yahoo_finance as yfm
from data.providers import MAYORIA, arbitrate, arbitrate_votes, second_opinions, tiingo_quote

BANDA = 0.50
# El caso KLAC: Yahoo ~10× corrupto contra un cierre guardado sano.
KLAC_PX, KLAC_REF = 1942.70, 194.0
# El caso AVB: el cierre guardado es el podrido.
AVB_PX, AVB_REF = 184.06, 68.14


def _votar(price, ref, finnhub, tiingo):
    return arbitrate_votes(price, ref, {"finnhub": finnhub, "tiingo": tiingo}, band=BANDA)


# ── La tabla ────────────────────────────────────────────────────────────────

TABLA = [
    # (caso, precio, referencia, finnhub, tiingo, veredicto, independiente usado)
    ("las dos externas avalan a Yahoo", AVB_PX, AVB_REF, 184.0, 185.0, "price", 184.0),
    ("Yahoo + una externa: mayoría para el precio", AVB_PX, AVB_REF, 184.0, 68.0, "price", 184.0),
    ("Yahoo + la OTRA externa: el orden no decide", AVB_PX, AVB_REF, 68.0, 184.0, "price", 184.0),
    ("las dos externas avalan la referencia (KLAC)", KLAC_PX, KLAC_REF, 195.0, 193.0, "reference", 195.0),
    (
        "las dos externas coinciden lejos de Yahoo Y del cierre",
        AVB_PX,
        AVB_REF,
        500.0,
        510.0,
        "reference",
        500.0,
    ),
    ("tres discrepando: sin mayoría", KLAC_PX, KLAC_REF, 195.0, 9000.0, "ninguno", None),
    ("una externa muda: vuelve la regla de dos", KLAC_PX, KLAC_REF, 195.0, None, "reference", 195.0),
    ("la OTRA externa muda: igual", KLAC_PX, KLAC_REF, None, 195.0, "reference", 195.0),
    ("las dos mudas", KLAC_PX, KLAC_REF, None, None, "sin_opinion", None),
    ("una responde basura (<= 0) y cuenta como muda", KLAC_PX, KLAC_REF, 0.0, 195.0, "reference", 195.0),
]


@pytest.mark.parametrize(
    ("caso", "px", "ref", "fh", "tg", "veredicto", "indep"), TABLA, ids=[t[0] for t in TABLA]
)
def test_la_tabla_de_votos(caso, px, ref, fh, tg, veredicto, indep):
    assert _votar(px, ref, fh, tg) == (veredicto, indep), caso


def test_DONDE_la_regla_de_tres_y_la_de_dos_DIFIEREN():
    """Sin mayoría con una externa avalando la referencia: la regla de dos, con esa sola
    externa, decía `reference`; con tres votos no hay mayoría. Es el caso que impide que la
    tabla pase con `arbitrate_votes` delegando siempre en la vieja."""
    assert arbitrate(KLAC_PX, KLAC_REF, 195.0, band=BANDA) == "reference"
    assert _votar(KLAC_PX, KLAC_REF, 195.0, 9000.0)[0] == "ninguno"


def test_con_una_sola_externa_da_EXACTAMENTE_lo_de_la_regla_de_dos():
    """El degradado a dos fuentes tiene que ser la regla vieja, no una aproximación."""
    for indep in (195.0, 1940.0, 9000.0, 700.0):
        for faltante in ("finnhub", "tiingo"):
            opiniones = {"finnhub": indep, "tiingo": indep, faltante: None}
            assert arbitrate_votes(KLAC_PX, KLAC_REF, opiniones, band=BANDA) == (
                arbitrate(KLAC_PX, KLAC_REF, indep, band=BANDA),
                indep,
            )


def test_la_mayoria_es_DOS_de_tres():
    assert MAYORIA == 2
    assert pv.QUOTE_SOURCES == ("finnhub", "tiingo")


def test_precio_o_referencia_invalidos_no_votan():
    assert _votar(0.0, KLAC_REF, 195.0, 195.0) == ("sin_opinion", None)
    assert _votar(KLAC_PX, 0.0, 195.0, 195.0) == ("sin_opinion", None)


# ── Cuál contestó qué ───────────────────────────────────────────────────────


def test_second_opinions_declara_cada_fuente_EN_ORDEN(monkeypatch):
    monkeypatch.setattr(pv, "second_opinion", lambda t, **k: 195.0)
    monkeypatch.setattr(pv, "tiingo_quote", lambda t, **k: None)
    assert list(second_opinions("KLAC").items()) == [("finnhub", 195.0), ("tiingo", None)]


def test_una_fuente_que_REVIENTA_queda_muda_y_no_tumba_a_la_otra(monkeypatch):
    def _boom(t, **k):
        raise RuntimeError("sin red")

    monkeypatch.setattr(pv, "second_opinion", _boom)
    monkeypatch.setattr(pv, "tiingo_quote", lambda t, **k: 193.0)
    assert second_opinions("KLAC") == {"finnhub": None, "tiingo": 193.0}


class _Resp:
    def __init__(self, cuerpo):
        self._cuerpo = cuerpo

    def raise_for_status(self):
        pass

    def json(self):
        return self._cuerpo


@pytest.mark.parametrize(
    ("fila", "esperado"),
    [
        ({"tngoLast": 338.4, "last": None, "prevClose": 341.07}, 338.4),
        ({"tngoLast": None, "last": 339.0, "prevClose": 341.07}, 339.0),
        ({"tngoLast": None, "last": None, "prevClose": 341.07}, 341.07),
        ({"tngoLast": None, "last": None, "prevClose": None}, None),
    ],
)
def test_tiingo_toma_tngoLast_y_cae_a_last_y_a_prevClose(monkeypatch, fila, esperado):
    """La forma de la respuesta es la medida en vivo el 2026-09-28 (endpoint IEX, AAPL)."""
    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp([{"ticker": "AAPL", **fila}]))
    assert tiingo_quote("AAPL", api_key="k") == esperado


def test_tiingo_sin_key_no_consulta(monkeypatch):
    import requests

    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    llamadas = []
    monkeypatch.setattr(requests, "get", lambda *a, **k: llamadas.append(1))
    assert tiingo_quote("AAPL") is None and llamadas == []


# ── Punta a punta por el guard ──────────────────────────────────────────────


@pytest.fixture
def disputa(monkeypatch):
    yfm._clear_second_opinion_cache()
    yfm._clear_opinion_log()
    monkeypatch.setattr(yfm, "scale_is_disputed", lambda *a, **k: True)
    monkeypatch.setattr(yfm, "_price_sanity_band", lambda: BANDA)
    monkeypatch.setattr(yfm, "_second_opinion_enabled", lambda: True)
    yield
    yfm._clear_second_opinion_cache()
    yfm._clear_opinion_log()


def _opiniones(fh, tg):
    return lambda ticker, allow_network=True: {"finnhub": fh, "tiingo": tg}


def test_guard_SIN_MAYORIA_deja_sin_precio_y_registra_las_dos_fuentes(disputa, monkeypatch):
    monkeypatch.setattr(yfm, "independent_prices", _opiniones(195.0, 9000.0))
    assert yfm.unreliable_reference("KLAC", KLAC_PX, KLAC_REF, allow_network=True) is None
    d = yfm.price_dispute("KLAC")
    assert d["verdict"] == "ninguno" and d["independent"] is None
    assert d["opiniones"] == {"finnhub": 195.0, "tiingo": 9000.0}


def test_guard_EXTERNAS_coinciden_se_usa_su_precio(disputa, monkeypatch):
    """Las dos cosas de Yahoo mal y las dos externas de acuerdo: el fetch devuelve el
    precio de la mayoría, marcado como de la segunda opinión (camino de la 201)."""
    monkeypatch.setattr(yfm, "independent_prices", _opiniones(500.0, 510.0))
    monkeypatch.setattr(yfm, "reference_close", lambda t: AVB_REF)
    info = yfm._reject_if_out_of_band("AVB", {"price": AVB_PX})
    assert info is not None and info["price"] == 500.0 and info["price_source"] == "second_opinion"


def test_el_aviso_de_Slack_nombra_cada_fuente():
    from paper_trading.engine import DISPUTE_NO_PRICE, _format_price_disputes

    texto = _format_price_disputes(
        "Sim",
        [
            {
                "ticker": "KLAC",
                "price": KLAC_PX,
                "reference": KLAC_REF,
                "independent": None,
                "opiniones": {"finnhub": 195.0, "tiingo": None},
                "kind": DISPUTE_NO_PRICE,
            }
        ],
    )
    assert "finnhub 195.00" in texto and "tiingo —" in texto
