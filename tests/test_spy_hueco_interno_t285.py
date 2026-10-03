"""Tarea 285 — el guard de cobertura de SPY de la 251 aceptaba un hueco INTERNO.

``spy_coverage_problems`` miraba la última fecha y un conteo de ruedas previas: con 40 ruedas
faltantes en medio del cohorte daba ``[]`` ([GD-1] de ``docs/auditoria_guards_2026-10-02.md``),
y en esas ruedas el régimen queda congelado igual que en la cola que la 251 tapó.
"""

from __future__ import annotations

from analysis import harness_config as h
from tests.test_spy_regimen_cobertura_t251 import _BARS, _COHORTE, _FIN, _spy


def test_un_hueco_interno_de_40_ruedas_se_acusa():
    hueco = {r[0] for r in _COHORTE[300:340]}
    con_hueco = [r for r in _spy("2019-01-01", _FIN) if r[0] not in hueco]
    probs = h.spy_coverage_problems(con_hueco, _BARS, warmup=250)
    assert len(probs) == 1, probs
    assert "faltan 40 ruedas" in probs[0] and _COHORTE[300][0] in probs[0] and _COHORTE[339][0] in probs[0]


def test_una_rueda_que_sólo_opera_un_ticker_de_otra_bolsa_no_acusa_a_SPY():
    """El calendario es el de la mayoría: con el de la serie más larga, un feriado de EE.UU.
    que una bolsa extranjera sí operó haría rojo a una SPY sana."""
    feriado_de_eeuu = _COHORTE[400][0]
    sin_feriado = [r for r in _COHORTE if r[0] != feriado_de_eeuu]
    extranjera = list(_COHORTE)  # la más larga: opera también el feriado
    bars = {"AAA": sin_feriado, "BBB": sin_feriado, "TW": extranjera}
    spy = [r for r in _spy("2019-01-01", _FIN) if r[0] != feriado_de_eeuu]
    assert h.huecos_de_spy(spy, bars) == []
    assert h.spy_coverage_problems(spy, bars, warmup=250) == []


def test_fuera_del_rango_de_SPY_no_es_un_hueco():
    """Las puntas las miden la cola y la SMA; el hueco interno no las cuenta dos veces."""
    tardia = [r for r in _spy("2019-01-01", _FIN) if r[0] >= _COHORTE[100][0]]
    assert h.huecos_de_spy(tardia, _BARS) == []
    corta = _spy("2019-01-01", _COHORTE[-7][0])
    assert h.huecos_de_spy(corta, _BARS) == []
