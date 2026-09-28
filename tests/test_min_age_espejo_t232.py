"""Tarea 232 — el Gate 2b del harness lee los espejos, no dos literales.

La auditoría de desvíos del 2026-09-27 ([D-2]) encontró que `ScaleOutParams` modelaba el Gate 2b
con `min_age_bdays: int = 3` y `bypass_score: float = 0.25`: dos números **iguales al vivo por
casualidad**. El bypass tenía espejo desde la 219, pero el default no lo leía, así que el guard
de la 130 verificaba un espejo que el harness no usaba. Y la edad mínima figuraba en el guard de
la 185 como «ya declarada por `reentry_gates`», una clave que sólo nombra los Gates 5/5b.

**Por qué por AST y no por igualdad de valores:** hoy el literal y el espejo valen lo mismo, así
que `ScaleOutParams().min_age_bdays == LIVE_...` pasa **igual** con el defecto puesto — el caso
de prueba degenerado. Lo que distingue el arreglo es de DÓNDE sale el default.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from analysis.harness_config import LIVE_SIGNAL_SELL_BYPASS_SCORE, LIVE_SIGNAL_SELL_MIN_AGE_BDAYS
from analysis.scaleout_replay import ScaleOutParams
from tests.test_espejos_direccion_faltante_t185 import SIN_ESPEJO
from tests.test_espejos_vivos_t130 import ESPEJOS

_FUENTE = Path(__file__).resolve().parent.parent / "analysis" / "scaleout_replay.py"


def _default_de(campo: str) -> ast.expr:
    arbol = ast.parse(_FUENTE.read_text(encoding="utf-8"))
    clase = next(n for n in arbol.body if isinstance(n, ast.ClassDef) and n.name == "ScaleOutParams")
    for n in clase.body:
        if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", None) == campo:
            assert n.value is not None
            return n.value
    raise AssertionError(f"ScaleOutParams no tiene el campo {campo}")


@pytest.mark.parametrize(
    "campo,espejo",
    [("min_age_bdays", "LIVE_SIGNAL_SELL_MIN_AGE_BDAYS"), ("bypass_score", "LIVE_SIGNAL_SELL_BYPASS_SCORE")],
)
def test_el_default_de_ScaleOutParams_ES_el_espejo(campo, espejo):
    valor = _default_de(campo)
    assert isinstance(valor, ast.Name) and valor.id == espejo, (
        f"`ScaleOutParams.{campo}` volvió a tener un default propio: tiene que leer `{espejo}`"
    )


def test_y_en_runtime_vale_lo_mismo():
    """El complemento del AST: que el default que se ve en el código es el que corre."""
    campos = {f.name: f.default for f in dataclasses.fields(ScaleOutParams)}
    assert campos["min_age_bdays"] == LIVE_SIGNAL_SELL_MIN_AGE_BDAYS
    assert campos["bypass_score"] == LIVE_SIGNAL_SELL_BYPASS_SCORE


def test_la_edad_minima_tiene_espejo_y_salio_de_la_clasificacion():
    assert ("LIVE_SIGNAL_SELL_MIN_AGE_BDAYS", "paper_signal_sell_min_age_bdays") in ESPEJOS
    assert "paper_signal_sell_min_age_bdays" not in SIN_ESPEJO
