"""Tarea 241 — la regla de tres fuentes deja de degradarse EN SILENCIO.

La auditoría del 2026-09-30 ([G-2] de `docs/auditoria_guards_2026-09-30.md`) lo reprodujo:
sin keys, el caso KLAC (Yahoo ×10) daba ``sin_opinion`` —el precio se acepta— con **cero**
líneas de log. Con una sola key la regla caía a la de dos fuentes, también sin decirlo. Y
``_arbitrate_price`` convertía cualquier excepción de la regla en ``sin_opinion`` con un
``except`` mudo.

Lo que se fija acá es que las tres cosas **se digan**, no que cambie la conducta: sin key la
fuente sigue sin votar, y una regla rota sigue sin veredicto. La conducta es de Chapa
(2026-09-28: *«que se caigan dos APIs no dispara ventas»*); el silencio no lo era.
"""

from __future__ import annotations

import logging

import pytest

from data import providers
from data import yahoo_finance as yf_mod
from paper_trading.engine import _dispute_note


@pytest.fixture(autouse=True)
def _sin_avisos_previos(monkeypatch):
    """El aviso es una vez por PROCESO: cada test arranca como un proceso nuevo."""
    monkeypatch.setattr(providers, "_sin_key_avisadas", set())
    for claves in providers.QUOTE_SOURCE_KEYS.values():
        for v in claves:
            monkeypatch.delenv(v, raising=False)


def _avisos(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "FUENTE NO DISPONIBLE" in r.getMessage()]


def test_sin_la_key_de_tiingo_se_avisa_UNA_vez_y_se_nombra_a_tiingo(monkeypatch, caplog):
    monkeypatch.setenv("FINNHUB_API_KEY", "x")
    monkeypatch.setattr(providers, "second_opinion", lambda t, timeout=10.0: 400.0)
    caplog.set_level(logging.WARNING, logger=providers.log.name)

    providers.second_opinions("KLAC")
    providers.second_opinions("KLAC")

    avisos = _avisos(caplog)
    assert len(avisos) == 1, avisos
    assert "tiingo" in avisos[0] and "TIINGO_API_KEY" in avisos[0]
    assert "finnhub" not in avisos[0].split(".")[0], "finnhub tiene key: no se acusa"
    assert "DOS" in avisos[0], "el aviso tiene que decir a qué regla cae"


def test_sin_ninguna_key_se_dice_que_el_precio_de_yahoo_se_acepta(caplog):
    """El caso de la auditoría: KLAC ×10, sin keys, daba `sin_opinion` sin una línea."""
    caplog.set_level(logging.WARNING, logger=providers.log.name)

    op = providers.second_opinions("KLAC")

    assert op == {"finnhub": None, "tiingo": None}
    assert providers.arbitrate_votes(4000.0, 400.0, op, band=0.5) == ("sin_opinion", None)
    avisos = _avisos(caplog)
    assert len(avisos) == 1 and "finnhub" in avisos[0] and "tiingo" in avisos[0]
    assert "se acepta" in avisos[0]


def test_con_las_dos_keys_no_hay_aviso(monkeypatch, caplog):
    monkeypatch.setenv("FINNHUB_API_KEY", "x")
    monkeypatch.setenv("TIINGO_API_KEY", "y")
    monkeypatch.setattr(providers, "second_opinion", lambda t, timeout=10.0: 400.0)
    monkeypatch.setattr(providers, "tiingo_quote", lambda t, timeout=10.0: 401.0)
    caplog.set_level(logging.WARNING, logger=providers.log.name)

    assert providers.second_opinions("KLAC") == {"finnhub": 400.0, "tiingo": 401.0}
    assert _avisos(caplog) == []


def test_FINNHUB_TOKEN_tambien_cuenta_como_key(monkeypatch):
    """`second_opinion` acepta las dos variables: el aviso no puede acusar a una fuente que anda."""
    monkeypatch.setenv("FINNHUB_TOKEN", "x")
    assert providers.fuentes_sin_key() == ["tiingo"]


def test_una_regla_que_revienta_deja_rastro_y_no_cambia_la_conducta(monkeypatch, caplog):
    def _rota(*a, **k):
        raise ZeroDivisionError("banda en cero")

    monkeypatch.setattr(providers, "arbitrate_votes", _rota)
    caplog.set_level(logging.ERROR, logger=yf_mod.log.name)

    assert yf_mod._arbitrate_price(4000.0, 400.0, {"finnhub": 400.0}) == ("sin_opinion", None)
    assert any("regla de mayoría falló" in r.getMessage() and r.exc_info for r in caplog.records)


def test_la_nota_de_la_orden_nombra_a_CADA_fuente():
    """Con tres fuentes, «la fuente independiente dice X» ya no dice quién votó qué."""
    nota = _dispute_note(
        {
            "price": 4000.0,
            "reference": 400.0,
            "independent": 400.5,
            "opiniones": {"finnhub": 400.5, "tiingo": None},
        }
    )
    assert "finnhub 400.50" in nota and "tiingo sin respuesta" in nota
    assert "se usa 400.50" in nota


def test_la_nota_de_un_registro_viejo_sin_opiniones_sigue_andando():
    nota = _dispute_note({"price": 4000.0, "reference": 400.0, "independent": 400.5})
    assert "la fuente independiente dice 400.50" in nota
