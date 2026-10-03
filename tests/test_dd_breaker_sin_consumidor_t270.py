"""Tarea 270 — el docstring de ``dd_breaker`` afirmaba un consumidor que no existe.

Decía en presente *«the consuming gate in ``run_scan`` suppresses BUYs only»*, y R1 cerró
NO-SHIP: nada en la app lo importa. Quien leía el módulo creía que la cuenta viva tenía un
freno por drawdown. Ahora el docstring dice que no está cableado, y este guard ata esa frase
a la realidad: si algún módulo de la app empieza a importarlo, el test frena hasta que se
actualice el estado declarado (y se pase por el kill-criteria, regla 2).
"""

from __future__ import annotations

import ast
from pathlib import Path

import paper_trading.dd_breaker as dd

_REPO = Path(__file__).resolve().parent.parent
_APP = ["paper_trading", "ui", "analysis", "data", "database", "alerts", "reports", "config", "main.py"]


def _importadores(raices: list[str]) -> list[str]:
    out = []
    for raiz in raices:
        base = _REPO / raiz
        for f in [base] if base.is_file() else sorted(base.rglob("*.py")):
            if f == Path(dd.__file__).resolve():
                continue
            arbol = ast.parse(f.read_text(encoding="utf-8"))
            for n in ast.walk(arbol):
                nombres = []
                if isinstance(n, ast.Import):
                    nombres = [a.name for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.module:
                    nombres = [n.module] + [f"{n.module}.{a.name}" for a in n.names]
                if any(x == "paper_trading.dd_breaker" for x in nombres):
                    out.append(str(f.relative_to(_REPO)))
                    break
    return out


def test_el_instrumento_ve_al_consumidor_que_si_existe():
    """Validar el instrumento: el harness lo importa, y el barrido tiene que verlo."""
    assert _importadores(["scripts"]) == [str(Path("scripts/run_dd_breaker_validation.py"))]


def test_ningun_modulo_de_la_app_consume_el_breaker_mientras_el_docstring_diga_NO_SHIP():
    assert _importadores(_APP) == [], (
        "un módulo de la app empezó a usar dd_breaker: R1 cerró NO-SHIP —el cableado pide "
        "pasar el kill-criteria (regla 2)— y el docstring del módulo dice que no está cableado"
    )


def test_el_docstring_no_afirma_el_gate_en_presente():
    doc = dd.__doc__ or ""
    assert "NOT wired" in doc.splitlines()[1]
    assert "When armed, the consuming gate" not in doc
