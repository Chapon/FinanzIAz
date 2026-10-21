"""Tarea 379 — el instrumento que compara lo vendido por señal en el vivo y en el harness.

Sólo las funciones puras: la corrida entera lee el cohorte y la DB y es la medición, no un test.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from scripts.measure_venta_senal_vivo_vs_harness_t379 import (
    cruce_de_senal,
    exceso,
    giros_a_sell,
    ic_por_bloques,
    rueda_de_sesion,
)

CAL = ["2026-07-01", "2026-07-02", "2026-07-06", "2026-07-07", "2026-07-08"]  # 03/07 feriado, 04-05 finde
NY = ZoneInfo("America/New_York")


def test_exceso_es_ticker_menos_spy_a_h_ruedas_del_calendario():
    t = {"2026-07-01": 100.0, "2026-07-06": 110.0, "2026-07-07": 130.0}
    spy = {"2026-07-01": 200.0, "2026-07-06": 204.0, "2026-07-07": 300.0}
    # +2 ruedas desde el 01/07 es el 06/07 (salta el feriado): +10% contra +2%.
    assert exceso(t, spy, CAL, "2026-07-01", 2) == pytest.approx(0.08)


def test_exceso_sin_dato_da_none():
    t = {"2026-07-01": 100.0}
    spy = {"2026-07-01": 200.0, "2026-07-02": 201.0}
    assert exceso(t, spy, CAL, "2026-07-01", 1) is None  # falta el ticker en la rueda +1
    assert exceso(t, spy, CAL, "2026-07-08", 1) is None  # no hay rueda +1
    assert exceso(t, spy, CAL, "2026-07-03", 1) is None  # la base no es rueda


@pytest.mark.parametrize(
    "utc,esperada",
    [
        ("2026-07-02 18:00:00", "2026-07-02"),  # 14:00 NY, en sesión
        ("2026-07-02 22:45:00", "2026-07-02"),  # 18:45 NY, después del cierre
        ("2026-07-02 12:00:00", "2026-07-01"),  # 08:00 NY, antes de abrir: el cierre de ayer
        ("2026-07-03 01:00:00", "2026-07-02"),  # 21:00 NY del 02, aunque en UTC ya sea 03
        ("2026-07-04 16:00:00", "2026-07-02"),  # sábado: la última rueda (el 03 fue feriado)
    ],
)
def test_rueda_de_sesion(utc, esperada):
    assert rueda_de_sesion(utc, CAL, NY) == esperada


def test_el_ic_remuestrea_bloques_enteros_no_eventos():
    """Diez ventas el mismo día y una sola en otro bloque: dos bloques, no once eventos.

    Remuestreando eventos, el percentil 2,5 queda cerca de la media (−0,9). Por bloques,
    uno de cada cuatro remuestreos son dos veces el bloque de las diez, así que llega a −1,0.
    """
    eventos = [("2026-07-01", -0.01)] * 10 + [("2026-07-08", 0.0)]
    r = ic_por_bloques(eventos, CAL, bloque=2, n_boot=2000, seed=1)
    assert r["n"] == 11 and r["bloques"] == 2
    assert r["media"] == pytest.approx(-0.01 * 10 / 11)
    assert r["ic95"][0] == pytest.approx(-0.01)
    assert r["ic95"][1] == pytest.approx(0.0)


def test_ic_sin_eventos():
    assert ic_por_bloques([], CAL, bloque=5)["media"] is None


def test_giros_a_sell_cuenta_el_giro_no_cada_dia_en_sell():
    """Tres días seguidos en SELL son un giro; volver a SELL después de un BUY es otro."""
    bars = {"A": [(d, 1, 1, 1, 1) for d in CAL]}
    sigs = {
        "A": {
            "2026-07-01": "SELL",
            "2026-07-02": "SELL",
            "2026-07-06": "SELL",
            "2026-07-07": "BUY",
            "2026-07-08": "SELL",
        }
    }
    assert giros_a_sell(bars, sigs) == [("A", "2026-07-01"), ("A", "2026-07-08")]


def test_cruce_distingue_mismo_dia_dia_anterior_y_otra():
    sigs = {
        "A": {"2026-07-02": "SELL"},
        "B": {"2026-07-01": "SELL", "2026-07-02": "BUY"},
        "C": {"2026-07-01": "BUY", "2026-07-02": "BUY"},
    }
    ventas = [
        ("A", "2026-07-02"),
        ("B", "2026-07-02"),
        ("C", "2026-07-02"),
        ("Z", "2026-07-02"),
        ("A", "2026-07-08"),
    ]
    r = cruce_de_senal(ventas, sigs, CAL, hasta="2026-07-07")
    assert r["cuenta"] == {"SELL_mismo_dia": 1, "SELL_dia_anterior": 1, "otra": 1, "sin_senal": 1}
    assert r["otra_detalle"] == [("C", "2026-07-02", "BUY", "BUY")]
