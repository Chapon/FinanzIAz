"""Tarea 441 — Claude recibe la caja, el capex, el flujo de caja libre y la ganancia operativa.

Las opiniones de TTWO y MSFT del 2026-11-20 los pidieron (*«para ver si el flujo operativo se
traduce en caja libre»*, *«ganancia operativa … para entender por qué el margen neto saltó»*), y el
almacén de EDGAR no los guardaba. Los tests pasan por el parser real (``parse_registros``) con un
payload falso de ``companyfacts``.
"""

from __future__ import annotations

import pytest

from analysis import opinion_claude as oc
from data import fundamentos_pit as fp


def _flujo(anio: str, val: float) -> dict:
    return {
        "start": f"{int(anio) - 1}-07-01",
        "end": f"{anio}-06-30",
        "filed": f"{anio}-07-30",
        "form": "10-K",
        "fp": "FY",
        "val": val,
    }


def _saldo(anio: str, val: float) -> dict:
    return {"end": f"{anio}-06-30", "filed": f"{anio}-07-30", "form": "10-K", "fp": "FY", "val": val}


def _payload() -> dict:
    gaap = {
        "Revenues": [_flujo("2024", 245_122e6), _flujo("2025", 281_724e6)],
        "NetIncomeLoss": [_flujo("2024", 88_136e6), _flujo("2025", 101_832e6)],
        "NetCashProvidedByUsedInOperatingActivities": [_flujo("2024", 118_548e6), _flujo("2025", 136_162e6)],
        # Capex sólo en 2025: en 2024 no hay flujo libre (no se toma el capex como 0).
        "PaymentsToAcquirePropertyPlantAndEquipment": [_flujo("2025", 64_551e6)],
        "OperatingIncomeLoss": [_flujo("2024", 109_433e6), _flujo("2025", 128_528e6)],
        # La caja: el tag preferido sólo tiene 2025; el alternativo tiene los dos años y en 2025 otro
        # valor (incluye la restringida). Manda el preferido donde tiene dato.
        "CashAndCashEquivalentsAtCarryingValue": [_saldo("2025", 30_242e6)],
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": [
            _saldo("2024", 18_315e6),
            _saldo("2025", 30_300e6),
            # Un saldo con `start` no es un saldo: no entra.
            dict(_flujo("2023", 999e6)),
        ],
    }
    return {"facts": {"us-gaap": {t: {"units": {"USD": e}} for t, e in gaap.items()}}}


def _anuales():
    fund = fp.unir("MSFT", [(789019, _payload())], generado="2026-11-20")
    return {f["fin_anio_fiscal"][:4]: f for f in oc.fundamentales_anuales(fund, "2026-11-12")}


def test_la_caja_toma_el_tag_preferido_con_dato_y_si_no_el_siguiente():
    filas = _anuales()
    assert filas["2025"]["caja_musd"] == 30_242
    assert filas["2024"]["caja_musd"] == 18_315


def test_la_caja_es_un_saldo():
    assert "caja" in fp.INSTANTANEOS
    assert "2023" not in _anuales()  # el registro con `start` no armó un año


def test_el_flujo_libre_es_el_operativo_menos_el_capex():
    u = _anuales()["2025"]
    assert u["capex_musd"] == 64_551
    assert u["flujo_caja_libre_musd"] == 71_611  # 136.162 − 64.551


def test_sin_capex_no_hay_flujo_libre():
    v = _anuales()["2024"]
    assert v["capex_musd"] is None and v["flujo_caja_libre_musd"] is None
    assert v["flujo_operativo_musd"] == 118_548


def test_la_ganancia_y_el_margen_operativos_a_mano():
    u = _anuales()["2025"]
    assert u["ganancia_operativa_musd"] == 128_528
    assert u["margen_operativo_pct"] == pytest.approx(45.6, abs=0.05)  # 128.528 / 281.724


def test_el_prompt_dice_que_no_hay_partidas_no_recurrentes():
    p = oc.SYSTEM_PROMPT
    assert "flujo de caja libre" in p and "partidas no" in p


def test_sube_version_datos():
    assert oc.VERSION_DATOS >= 11
