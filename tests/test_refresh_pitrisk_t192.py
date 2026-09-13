"""Tarea 192 (REFRESH-SIN-PITRISK) — el checklist post-refresh nombra a TODOS los productores de stores.

**Qué pasaba.** `scripts/refresh_cohort.py` imprime al terminar lo que hay que hacer antes de
correr cualquier harness, y su paso 1 nombraba `precompute_pit_signals.py`. **No nombraba
`precompute_pit_risk_score.py`**, que produce `data/pit_risk/`. La re-corrida del T21 de la
tarea 183 (2026-09-12) lo avisó: *«risk_score llega hasta 2026-09-01 y la población hasta
2026-09-08 — 197 entrada(s) del final SIN risk_score»*. Y **ya había pasado** en la 42, con
el store al 2026-08-07. Un aviso que se repite en cada refresh es un paso que falta.

**Lo que este archivo fija:**

1. **Todo productor de un store `data/pit_*` aparece como comando en el checklist.** Los
   productores se **descubren** por AST —un módulo de `scripts/` con un `OUT_DIR` que apunta a
   `data/pit_*`—, así que un store nuevo no puede nacer sin su paso.
2. **El store de riesgo está al día con el de señales** sobre el universo de referencia.

**Una corrección a mi propio enunciado, que va escrita porque cambió la decisión:** la tarea
decía que el store de riesgo lo leen *cinco* runners. Lo saqué de un `grep -l` con un patrón
OR que también matcheaba `load_bars_signals_scores`, que lee el store de **señales**. Por
lectura directa, el de riesgo lo lee **sólo el T21**, y lo que cae en la cola es el brazo
**diagnóstico** `B2_no_volpen`, que queda igual al baseline — no `B1_score`.

**Por eso la cola del store de riesgo sigue siendo AVISO y no pasa a gate.** Alimenta un brazo
diagnóstico de un runner, ese runner ya declara la cola aparte del porcentaje (tarea 75) y
tiene su propio umbral de cobertura (`MIN_RISK_COVERAGE`). Lo que se repetía era la causa —el
paso faltante—, y eso es lo que se cierra.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

import analysis.harness_config as hc

_REPO = Path(__file__).resolve().parent.parent
_REFRESH = _REPO / "scripts" / "refresh_cohort.py"


# ── 1. Los productores, descubiertos ────────────────────────────────────────


def productores_de_stores(scripts: Path) -> dict[str, str]:
    """``{módulo: store}`` para cada script con un ``OUT_DIR`` de nivel módulo bajo ``data/pit_*``."""
    out: dict[str, str] = {}
    for path in sorted(scripts.glob("*.py")):
        try:
            arbol = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for nodo in arbol.body:
            if not (
                isinstance(nodo, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "OUT_DIR" for t in nodo.targets)
            ):
                continue
            partes = [
                c.value
                for c in ast.walk(nodo.value)
                if isinstance(c, ast.Constant) and isinstance(c.value, str)
            ]
            store = next((p for p in partes if p.startswith("pit_")), None)
            if "data" in partes and store:
                out[path.stem] = store
    return out


def _checklist(path: Path = _REFRESH) -> str:
    """El texto del bloque *«DESPUÉS DE ESTO»*, armado desde las constantes del ``print``.

    Se lee por AST y no con un substring sobre el archivo entero: el docstring o un
    comentario que nombrara el script dejarían pasar un checklist que no lo nombra.
    """
    arbol = ast.parse(path.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id == "print":
            texto = "".join(
                c.value for c in ast.walk(nodo) if isinstance(c, ast.Constant) and isinstance(c.value, str)
            )
            if "DESPUÉS DE ESTO" in texto:
                return texto
    raise AssertionError("refresh_cohort.py dejó de imprimir el checklist «DESPUÉS DE ESTO»")


def test_el_barrido_encuentra_los_dos_productores_de_hoy():
    """Contraprueba del instrumento contra lo que se sabe que existe."""
    assert productores_de_stores(_REPO / "scripts") == {
        "precompute_pit_signals": "pit_signals",
        "precompute_pit_risk_score": "pit_risk",
    }


def test_el_barrido_ve_un_productor_NUEVO(tmp_path):
    (tmp_path / "precompute_otro.py").write_text(
        'from pathlib import Path\nROOT = Path(".")\nOUT_DIR = ROOT / "data" / "pit_otro"\n', encoding="utf-8"
    )
    (tmp_path / "no_es.py").write_text('OUT_DIR = "reports/pit_x"\n', encoding="utf-8")
    assert productores_de_stores(tmp_path) == {"precompute_otro": "pit_otro"}


def test_todo_productor_esta_en_el_checklist_como_COMANDO():
    checklist = _checklist()
    faltan = [
        m for m in productores_de_stores(_REPO / "scripts") if f"`python scripts/{m}.py`" not in checklist
    ]
    assert not faltan, (
        f"productores de stores que el checklist post-refresh no manda a correr: {faltan}. "
        "Un store que el refresh deja atrás y nadie nombra es el defecto de la 42 y la 192"
    )


def test_el_checklist_se_lee_del_print_y_no_del_archivo(tmp_path):
    """Si el comando estuviera sólo en el docstring o en un comentario, el lector no lo tiene
    que ver — si no, el test de arriba pasaría con un checklist que no lo nombra."""
    falso = tmp_path / "refresh.py"
    lineas = [
        '"""Correr `python scripts/precompute_pit_risk_score.py` después."""',
        "# `python scripts/precompute_pit_risk_score.py`",
        'print("DESPUÉS DE ESTO: 1. `python scripts/precompute_pit_signals.py`")',
    ]
    falso.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    checklist = _checklist(falso)
    assert "precompute_pit_signals" in checklist
    assert "precompute_pit_risk_score" not in checklist


# ── 2. El store de riesgo al día con el de señales ──────────────────────────


def _ultima(path: Path, clave: str) -> str | None:
    try:
        filas = json.loads(path.read_text(encoding="utf-8")).get(clave) or {}
    except (OSError, ValueError):
        return None
    return max(filas) if filas else None


def test_el_store_de_riesgo_llega_hasta_donde_llega_el_de_senales():
    """El de señales es gitignoreado: donde no está (el CI), no hay contra qué comparar."""
    tickers = hc.parse_universe_file(_REPO / hc.LIVE_UNIVERSE_FILE)
    senales = _REPO / "data" / "pit_signals"
    riesgo = _REPO / "data" / "pit_risk"
    if not any(senales.glob("*.json")):
        pytest.skip("sin store de señales en este entorno")

    atrasados = {}
    for t in tickers:
        nombre = f"{t}__{hc.ARTIFACT_PERIOD}__w250.json"
        s, r = _ultima(senales / nombre, "signals"), _ultima(riesgo / nombre, "risk")
        if s is not None and (r is None or r < s):
            atrasados[t] = (r, s)
    assert not atrasados, (
        f"{len(atrasados)} tickers con el store de riesgo atrás del de señales (riesgo, señales): "
        f"{dict(list(atrasados.items())[:5])}. Correr `python scripts/precompute_pit_risk_score.py`"
    )


def test_la_fecha_se_compara_como_fecha_ISO():
    """`max` sobre strings sólo ordena bien si son ISO; si el store cambiara de formato, la
    comparación de arriba mentiría en silencio."""
    riesgo = _REPO / "data" / "pit_risk"
    muestra = next(iter(sorted(riesgo.glob("*.json"))), None)
    if muestra is None:
        pytest.skip("sin store de riesgo")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", _ultima(muestra, "risk") or "")
