"""Tarea 134 (TRAILMULT-DUP) — ningún script define su propia constante ``LIVE_*``.

``analysis/harness_config.py`` afirma haber eliminado la duplicación por script
(*«estaba repartida en constantes por script —`LIVE_STOP`, `LIVE_TRAIL`, `LIVE_MULT`,
`NO_STOP`— en **cinco** archivos, y cuando Chapa cambió la política en vivo el
2026-08-27 ninguna se enteró»*). No estaba eliminada: quedaban **cinco** constantes
con nombre ``LIVE_*`` repartidas en cuatro runners.

**Y la decisión no era importar el espejo, era renombrarlas.** El precedente lo dejó
la T92 sobre `run_stop_value_t37.py`: ahí el arreglo **no** fue re-apuntar la
constante a la política de hoy, porque ese par era el **baseline de una comparación
congelada** y re-apuntarlo hacía que el runner comparara el candidato **contra sí
mismo** — el veredicto publicado dejaba de reproducir. Se verificó una por una y las
cinco son historia, no configuración: cada una es el brazo base de una rejilla o de
una reproducción anclada (`REPRO_BASE_CAGR = 0.0798`, el 9.17% de la T37 §7.7).

Así que se renombraron a ``BASELINE_*``, con la convención que ya usaba la T37, y
**ningún valor se movió**: sólo el nombre dejó de mentir.

**El caso más claro de por qué el nombre importa:** ``LIVE_MULT = 2.0`` decía ser *el
múltiplo de stop vivo*, y en vivo el stop duro está **APAGADO** desde el 2026-08-27.
El nombre ya era falso, exactamente como el ``LIVE_STOP`` que la T92 encontró.

**Por qué el guard es un predicado y no una lista de cuatro archivos:** la auditoría
encontró **dos** de las cinco, porque su criterio era *«colisiona con el nombre de un
espejo»* y las otras tres se llaman distinto (``LIVE_MULT``, ``LIVE_MIN_EXCESS``). La
propiedad que importa no es el nombre exacto sino *una constante que dice LIVE y que
nadie re-verifica*. Ver [[guard-no-puede-usar-de-verdad-lo-que-chequea]].
"""

from __future__ import annotations

import ast
from pathlib import Path

import analysis.harness_config as hc

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

# El único ``LIVE_*`` que un script puede definir, con su motivo. No es un valor
# espejado de nada: es un **switch de modelado** —si el harness simula o no los gates
# de re-entrada del engine— y su nombre describe qué modela, no qué vale en vivo.
PERMITIDOS: dict[str, str] = {
    "LIVE_GATES": "switch de modelado (¿el harness corre con los gates del engine?), no un valor vivo",
}


def _live_definidos(path: Path) -> list[str]:
    """Los ``LIVE_*`` asignados **a nivel de módulo** en un script, por AST."""
    try:
        arbol = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover — un script roto ya lo caza la suite
        return []
    out = []
    for n in arbol.body:
        if isinstance(n, ast.Assign):
            out += [t.id for t in n.targets if isinstance(t, ast.Name) and t.id.startswith("LIVE_")]
        elif (
            isinstance(n, ast.AnnAssign)
            and isinstance(n.target, ast.Name)
            and n.target.id.startswith("LIVE_")
        ):
            out.append(n.target.id)
    return out


def test_ningun_script_define_una_constante_LIVE_sin_motivo():
    """**El test que importa.** Un ``LIVE_*`` nuevo en un runner obliga a decidir: o
    es un valor vivo y va a ``harness_config`` (donde el guard de la 130 lo compara
    contra el ``settings.json``), o es un baseline congelado y **no puede llamarse
    LIVE**, o es un switch de modelado y va a ``PERMITIDOS`` con su motivo.
    """
    culpables = [
        f"{py.name}: {nombre}"
        for py in sorted(_SCRIPTS.glob("*.py"))
        for nombre in _live_definidos(py)
        if nombre not in PERMITIDOS
    ]
    assert not culpables, (
        "estos scripts definen su propia constante LIVE_*, que es la duplicación que "
        "`harness_config` dice haber eliminado. Si es un valor vivo, va allá; si es un "
        "baseline congelado, renombralo a BASELINE_* (tareas 92 y 134):\n  " + "\n  ".join(culpables)
    )


def test_ninguna_sombrea_ADEMAS_un_espejo_de_harness_config():
    """El eje que sí veía la auditoría, que es un subconjunto del de arriba.

    Se deja explícito porque es el caso más peligroso: dos constantes con el **mismo
    nombre** y valores que pueden divergir, y el lector no tiene forma de saber cuál
    está mirando.
    """
    espejos = {k for k in dir(hc) if k.startswith("LIVE_")}
    colisiones = [
        f"{py.name}: {nombre}"
        for py in sorted(_SCRIPTS.glob("*.py"))
        for nombre in _live_definidos(py)
        if nombre in espejos
    ]
    assert not colisiones, f"sombrean un espejo de harness_config: {colisiones}"


def test_los_cuatro_runners_siguen_declarando_su_baseline():
    """Contraprueba: que los de arriba no pasen porque el barrido **no miró nada**.

    Si un runner pierde su constante de baseline, su comparación congelada perdió el
    brazo base — y los dos tests de arriba pasarían igual de verdes.
    """
    esperados = {
        "measure_trail_arm_t54.py": ("BASELINE_TRAIL_MULT", "BASELINE_MIN_EXCESS"),
        "run_trail_arm_t54.py": ("BASELINE_TRAIL_MULT",),
        "run_stop_loosen_t34.py": ("BASELINE_STOP_MULT",),
        "run_stop_price_replay_t26b.py": ("BASELINE_STOP_MULT",),
    }
    for nombre, constantes in esperados.items():
        txt = (_SCRIPTS / nombre).read_text(encoding="utf-8")
        for c in constantes:
            assert f"{c} = " in txt, f"{nombre} perdió {c}"


def test_el_permitido_esta_justificado_por_escrito():
    """Una excepción sin motivo escrito es una lista disfrazada de predicado."""
    assert all(motivo.strip() for motivo in PERMITIDOS.values())
