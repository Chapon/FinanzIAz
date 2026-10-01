"""Tarea 253 — ``refresh_cohort --tickers SPY`` no imprime el checklist de refresh del cohorte.

El checklist (re-precomputar el store PIT, re-anclar las constantes de reproducción) es lo que
mueve un refresh del **universo**. SPY es sustrato fuera del universo (tarea 251): no está en el
store PIT y los runners de régimen no anclan constantes. Se imprimía igual, y mandaba a
re-precomputar y re-anclar por nada (pasó el 2026-10-01, al refrescar SPY).

Los casos se eligen para que el defecto y el arreglo difieran: SPY solo (sin checklist), un
ticker del universo (con checklist) y la mezcla (con checklist — un ``any`` en vez de ``all``
la dejaría sin él).
"""

from __future__ import annotations

import pytest

import data.yahoo_finance as yf_mod
import scripts.refresh_cohort as rc

_CHECKLIST = "DESPUÉS DE ESTO"


@pytest.fixture
def sin_red(monkeypatch):
    monkeypatch.setattr(yf_mod, "get_historical_data_batch", lambda ts, period: {t: object() for t in ts})


def _salida(capsys, tickers: str) -> str:
    assert rc.main(["--tickers", tickers]) == 0
    return capsys.readouterr().out


def test_sólo_SPY_no_imprime_el_checklist(sin_red, capsys):
    out = _salida(capsys, "SPY")
    assert _CHECKLIST not in out
    assert "sustrato fuera del universo (SPY)" in out


def test_un_ticker_del_universo_sí_lo_imprime(sin_red, capsys):
    assert _CHECKLIST in _salida(capsys, "AAA")


def test_SPY_con_un_ticker_del_universo_sí_lo_imprime(sin_red, capsys):
    assert _CHECKLIST in _salida(capsys, "SPY,AAA")


def test_SPY_sigue_declarado_como_sustrato():
    assert "SPY" in rc.SUSTRATO_FUERA_DEL_UNIVERSO
