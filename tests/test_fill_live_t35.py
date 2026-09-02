"""FILL-LIVE (tarea 35) — el parseo del que salen los números de la contabilidad.

Todo el veredicto de la tarea sale de leer el `reason` de cada salida ATR, que es
la única constancia de **con qué precio se enteró el engine** (`px`) y **con cuál
se acreditó la cuenta** (el nivel, o el `open` si hubo gap). Si el parseo falla en
silencio —devolviendo `None` sobre una fila válida, o peor, confundiendo `px` con
`nivel`— el número sale al revés y nada lo delata.

La asimetría que hay que no romper: en un **stop/trail** el nivel está **arriba**
del `px` que lo disparó y en un **take-profit** está **abajo**. Por eso el signo de
la ventaja depende del tipo, y por eso el parseo tiene que conservar el orden de
los dos números tal como aparecen.
"""

from __future__ import annotations

import pytest

from scripts.measure_fill_live_t35 import parse_reason

# ── Las tres formas reales que hay en la DB ──────────────────────────────────


def test_stop_con_fill_declarado():
    """El caso moderno: el `reason` trae las tres puntas."""
    r = parse_reason(
        "atr_stop @ 155.19 ≤ 156.32 (entry 164.21 − 2.0×ATR 3.95) | fill≈156.32 (gap +0.00% vs nivel)"
    )
    assert r == {"tipo": "atr_stop", "px": 155.19, "nivel": 156.32, "fill_base": 156.32}


def test_stop_SIN_fill_declarado_es_una_salida_vieja():
    """Las anteriores a la T01 no traen `fill≈` — y se llenaron **al `px`**, no al
    nivel. O sea que la historia de la cuenta mezcla **dos convenciones**, y por eso
    `fill_base` queda en `None` en vez de asumir una."""
    r = parse_reason("atr_stop @ 80.28 ≤ 80.78 (entry 83.94 − 2.0×ATR 1.58)")
    assert r is not None
    assert (r["px"], r["nivel"]) == (80.28, 80.78)
    assert r["fill_base"] is None


def test_take_profit_usa_el_operador_al_reves():
    """Y con él se da vuelta el signo: en un TP el nivel está **abajo** del `px`, así
    que llenar al nivel **perjudica** a la cuenta. Es el mecanismo que hace que la
    convención sea simétrica y no un sesgo."""
    r = parse_reason(
        "atr_tp @ 253.38 ≥ 250.11 (entry 228.50 + 4.0×ATR 5.40) | fill≈250.11 (gap +0.00% vs nivel)"
    )
    assert r is not None
    assert r["tipo"] == "atr_tp"
    assert r["px"] > r["nivel"]  # lo contrario que en un stop


def test_trailing():
    r = parse_reason(
        "atr_trail @ 306.56 ≤ 308.71 (peak 344.45 − 2.0×ATR 17.87) | fill≈308.71 (gap +0.00% vs nivel)"
    )
    assert r is not None and r["tipo"] == "atr_trail"
    assert r["px"] < r["nivel"]


def test_el_gap_deja_un_fill_distinto_del_nivel():
    """Cuando la barra abrió pasada el nivel, el fill es el `open` — que puede ser
    **peor** que el `px`. Es la mitad de la distribución que la premisa de la tarea
    no contemplaba."""
    r = parse_reason(
        "atr_stop @ 84.19 ≤ 84.61 (entry 88.23 − 2.0×ATR 1.81) | fill≈84.18 (gap -0.51% vs nivel)"
    )
    assert r is not None
    assert r["fill_base"] == 84.18
    assert r["fill_base"] < r["px"] < r["nivel"]  # el fill quedó por DEBAJO del px


# ── Lo que NO tiene que parsear ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "reason",
    [
        "analyze SELL — score 0.31",  # salida por señal, no por barrera
        "",
        "atr_stop sin numeros",
        "el atr_stop @ 10 ≤ 20 no empieza con el tipo",  # tiene que anclar al inicio
    ],
)
def test_lo_que_no_es_una_salida_atr_devuelve_None(reason):
    assert parse_reason(reason) is None


def test_el_orden_de_los_dos_numeros_no_se_invierte():
    """El bug que arruinaría el signo del veredicto sin que nada lo delate."""
    r = parse_reason("atr_stop @ 1.00 ≤ 2.00 (…)")
    assert r is not None and (r["px"], r["nivel"]) == (1.00, 2.00)
