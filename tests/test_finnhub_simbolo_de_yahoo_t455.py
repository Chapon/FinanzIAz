"""Tarea 455 — a Finnhub se le pide su símbolo, no el de Yahoo.

Medido el 2026-11-23 contra la API: ``BRK-B`` → 200 con 0 noticias, ``BRK.B`` → 200 con 132 en la
semana (BRK-B, Berkshire Hathaway, no tenía ninguna fila de Finnhub en ``news_events``), y
``2357.TW`` (ASUSTeK, de la bolsa de Taiwán) → 403 *«You don't have access to this resource»*, que
el harvest contaba como falla de red con traceback y dejaba a Finnhub «sucia» todas las horas, con
un ``fuentes 3/4 limpias`` que no decía cuál.
"""

from __future__ import annotations

from collections import Counter

import pytest

from data import news_sources as ns
from data.news_sources import SourceOutcome, _CollectResult
from scripts.harvest_catalysts import HarvestReport, _anotar_salud

_NOTICIA = {"headline": "Berkshire compra", "source": "Reuters", "url": "https://x", "datetime": 1763900000}


class _Resp:
    def __init__(self, status: int, payload):
        self.status_code = status
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code} Client Error: Forbidden")

    def json(self):
        return self._payload


class _FinnhubFalso:
    """Contesta como la API medida: el símbolo con punto trae noticias, el de guion nada, y una
    bolsa de afuera 403."""

    def __init__(self):
        self.pedidos: list[str] = []

    def get(self, url, params=None, timeout=None, headers=None):
        s = params["symbol"]
        self.pedidos.append(s)
        if s.endswith(".TW"):
            return _Resp(403, {"error": "You don't have access to this resource."})
        if s == "BRK.B":
            return _Resp(200, [_NOTICIA])
        if s == "NVDA":
            return _Resp(200, [_NOTICIA | {"headline": "Nvidia vende"}])
        return _Resp(200, [])


@pytest.mark.parametrize(
    ("yahoo", "finnhub"),
    [
        ("BRK-B", "BRK.B"),
        ("brk-b", "BRK.B"),
        ("BF-B", "BF.B"),
        ("NVDA", "NVDA"),
        ("2357.TW", None),
        ("GGAL.BA", None),
    ],
)
def test_simbolo_finnhub(yahoo, finnhub):
    assert ns.simbolo_finnhub(yahoo) == finnhub


def test_brk_b_se_pide_como_brk_punto_b_y_queda_con_el_ticker_de_la_app():
    sess = _FinnhubFalso()
    items, o = ns._finnhub_news("BRK-B", session=sess, api_key="k")
    assert sess.pedidos == ["BRK.B"]
    assert [i.title for i in items] == ["Berkshire compra"]
    assert {i.ticker for i in items} == {"BRK-B"}  # el de la app: es con el que se lee
    assert (o.status, o.items) == ("ok", 1)


def test_una_bolsa_de_afuera_no_se_pide_y_sale_skipped(caplog):
    sess = _FinnhubFalso()
    caplog.set_level("INFO", logger="data.news_sources")
    items, o = ns._finnhub_news("2357.TW", session=sess, api_key="k")
    assert sess.pedidos == []
    assert items == [] and o.status == "skipped" and o.source == "finnhub"
    assert not [r for r in caplog.records if r.levelname == "ERROR" or r.exc_info]
    assert any("2357.TW" in r.getMessage() for r in caplog.records)


def test_sin_key_sigue_siendo_no_disponible_aunque_sea_de_afuera(monkeypatch):
    # `unavailable` es por fuente (la 217): sin key, el salteo por ticker no lo tapa.
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.delenv("FINNHUB_TOKEN", raising=False)
    _, o = ns._finnhub_news("2357.TW", session=_FinnhubFalso(), api_key=None)
    assert o.status == "unavailable"


def test_un_ticker_comun_sigue_igual():
    sess = _FinnhubFalso()
    items, o = ns._finnhub_news("nvda", session=sess, api_key="k")
    assert sess.pedidos == ["NVDA"] and [i.title for i in items] == ["Nvidia vende"] and o.status == "ok"


def test_el_salteo_no_ensucia_a_finnhub_en_el_reporte():
    rep = HarvestReport()
    sess = _FinnhubFalso()
    for t in ("NVDA", "BRK-B", "2357.TW"):
        _, o = ns._finnhub_news(t, session=sess, api_key="k")
        _anotar_salud(rep, t, _CollectResult(outcomes=[o]))
    assert rep.src_run["finnhub"] == 2 and rep.src_fail["finnhub"] == 0
    assert "fuentes 1/1 limpias" in rep.summary()


def _reporte(fallas: dict[str, int], corridas: int = 141) -> HarvestReport:
    rep = HarvestReport(tickers=corridas, requested=corridas)
    rep.src_run = Counter({s: corridas for s in ("yfinance_news", "sec", "finnhub")})
    rep.src_fail = Counter(fallas)
    rep.src_con_items = Counter({s: corridas for s in ("yfinance_news", "sec", "finnhub")})
    return rep


def test_el_resumen_nombra_la_fuente_con_una_falla_aislada():
    s = _reporte({"finnhub": 1}).summary()
    assert "fuentes 2/3 limpias | con fallas: finnhub 1/141" in s, s


def test_una_fuente_caida_no_se_repite_en_con_fallas():
    s = _reporte({"finnhub": 141, "sec": 2}).summary()
    assert "con fallas: sec 2/141" in s and "finnhub 141/141" in s.split("FUENTES CAIDAS")[1], s
    assert "con fallas: finnhub" not in s and ", finnhub" not in s.split("con fallas:")[1].split("|")[0], s


def test_una_corrida_limpia_no_dice_con_fallas():
    s = _reporte({}).summary()
    assert "fuentes 3/3 limpias" in s and "con fallas" not in s, s


def test_skipped_es_el_estado_de_la_sec_sin_cik():
    # El mismo trato: no entra al denominador (`_anotar_salud`).
    rep = HarvestReport()
    _anotar_salud(rep, "2357.TW", _CollectResult(outcomes=[SourceOutcome("finnhub", "skipped", 0, "x")]))
    assert rep.src_run["finnhub"] == 0
