"""DOCDECAY (tarea 72) — el corpus OPERATIVO no puede nombrar una constante muerta.

El problema que este test convierte en guard
--------------------------------------------
Un doc de veredicto (`docs/*_tNN_*.md`) cita **su** muestra y envejece bien porque
está atribuido. Una **skill** afirma en presente y **se lee cada sesión**: cuando
su número o su símbolo deja de valer, **dirige mal**.

El caso real: la tarea **68** partió `WINDOW_REFRESH_2026_08_09` en
`..._2026_09_01_LIVE` / `_LEGACY` **sin dejar alias a propósito**, y puso un test
que prohíbe el nombre viejo en `scripts/run_*.py`. Pero
`.claude/skills/backtest-replay-harness/SKILL.md` —que es *la instrucción de cómo
escribir un runner nuevo*— siguió mandando a usar el nombre borrado, y **ni
siquiera nombraba los nuevos**. Quien la siguiera escribía un `ImportError`.

Por qué "está definido" y no "aparece en algún .py"
--------------------------------------------------
La versión floja de este chequeo —*"el nombre aparece en algún archivo Python"*—
**no habría cazado el caso real**: `WINDOW_REFRESH_2026_08_09` sigue apareciendo en
dos **comentarios** de `harness_config.py`, y ahí tiene que seguir (quien lea el
re-anclaje necesita ver cuál era el nombre viejo). Por eso el test exige que el
símbolo esté **definido** — una asignación o anotación a nivel de módulo.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

# El corpus OPERATIVO: lo que se lee para decidir cómo trabajar, no los veredictos.
_CORPUS = [
    _REPO / "CLAUDE.md",
    *sorted((_REPO / ".claude").rglob("*.md")),
    _REPO / "docs" / "SETTINGS_REFERENCE.md",
]

# `UN_NOMBRE_ASI` entre backticks: mayúsculas con al menos un guion bajo.
_EN_BACKTICKS = re.compile(r"`([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)`")
# Una definición a nivel de módulo: `NOMBRE = ...` o `NOMBRE: tipo = ...`.
_DEFINICION = re.compile(r"^\s*([A-Z][A-Z0-9_]+)\s*[:=]", re.M)

# Nombres en MAYÚSCULA que el corpus cita legítimamente y que **no** son constantes
# de Python. Es un dict y no una lista a propósito: agregar uno obliga a escribir
# por qué (mismo criterio que `ARTIFACT_REFRESH_EXCEPTIONS` de la tarea 30).
_NO_SON_CONSTANTES: dict[str, str] = {
    "FINNHUB_API_KEY": "variable de entorno que lee el harvest; no vive en el código",
    "SLACK_BOT_TOKEN": "variable de entorno del notificador; no vive en el código",
    "SLACK_CHANNEL": "variable de entorno del notificador; no vive en el código",
    "ORACULO_PRIO": "es el VALOR de ORACLE_ARM en run_prio_event_t49, no una constante",
    "ANTI_ORACULO_PRIO": "es el VALOR de ANTI_ORACLE_ARM, no una constante propia",
}


def _constantes_definidas() -> set[str]:
    out: set[str] = set()
    for p in _REPO.rglob("*.py"):
        if ".venv" in str(p) or "site-packages" in str(p):
            continue
        try:
            texto = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        out.update(m.group(1) for m in _DEFINICION.finditer(texto))
    return out


def test_el_corpus_operativo_no_nombra_constantes_muertas():
    """Si esto se pone rojo: o el corpus quedó apuntando a un símbolo que se
    renombró/borró, o el nombre nuevo no está definido. **No lo silencies con el
    allowlist** salvo que de verdad no sea una constante de Python — el caso real
    fue una skill mandando a importar algo que no existe."""
    definidas = _constantes_definidas()
    assert len(definidas) > 300, "el escaneo de constantes no encontró casi nada"

    huerfanas: list[str] = []
    for archivo in _CORPUS:
        if not archivo.exists():
            continue
        for m in _EN_BACKTICKS.finditer(archivo.read_text(encoding="utf-8")):
            nombre = m.group(1)
            if nombre in definidas or nombre in _NO_SON_CONSTANTES:
                continue
            huerfanas.append(f"{archivo.relative_to(_REPO).as_posix()}: `{nombre}`")

    assert not huerfanas, "el corpus operativo nombra constantes que no existen:\n  " + "\n  ".join(
        sorted(set(huerfanas))
    )


def test_el_nombre_que_la_68_borro_no_esta_definido():
    """Contraprueba: sin esto, el test de arriba podría estar pasando por vacío.

    `WINDOW_REFRESH_2026_08_09` **sigue apareciendo** en dos comentarios de
    `harness_config.py` —y tiene que seguir— pero **no está definido**. Ésa es
    exactamente la distinción que hace que el guard funcione.
    """
    definidas = _constantes_definidas()
    assert "WINDOW_REFRESH_2026_08_09" not in definidas
    assert "WINDOW_REFRESH_2026_09_01_LIVE" in definidas
    assert "WINDOW_REFRESH_2026_09_01_LEGACY" in definidas

    fuente = (_REPO / "analysis" / "harness_config.py").read_text(encoding="utf-8")
    assert "WINDOW_REFRESH_2026_08_09" in fuente  # en comentarios, a propósito


def test_el_allowlist_explica_cada_excepcion():
    """Un dict para que agregar una excepción obligue a escribir el porqué."""
    assert all(len(v) > 20 for v in _NO_SON_CONSTANTES.values())
