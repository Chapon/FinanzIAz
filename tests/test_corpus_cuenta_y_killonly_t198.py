"""Tarea 198 — el corpus operativo no afirma una cuenta viva equivocada ni un «modo» que no existe.

La **181** demostró que *kill_only* es el **nombre de una configuración** escrita en
`~/.finanzias/settings.json`, no un mecanismo, y corrigió `ARCHITECTURE.md`, `CLAUDE.md` y
`SETTINGS_REFERENCE.md`. Quedaron cuatro lugares diciéndolo como mecanismo, y uno era el
agente `verificador` —el que valida una tarea antes de cerrarla—, que además decía
*«Cuenta activa: "Sim Principal" (id=1)»*: la cuenta pausada desde julio y cerrada por Chapa
el 2026-09-13.

**Por qué no lo vio ningún guard, siendo que el corpus de la 72 y la 137 ya incluye
`.claude/agents/`:** el alcance estaba bien, faltaba el criterio. La 72 busca constantes que
no existen y la 137 números en presente; ninguna compara **qué cuenta** se afirma como viva.

Dos chequeos:

1. **La cuenta, por valor.** Todo *«Cuenta activa: "X" (id=N)»* se parsea y se compara contra
   ``LIVE_ACCOUNT_NAME``/``LIVE_ACCOUNT_ID`` de `analysis/harness_config.py`, que es donde el
   repo declara la cuenta viva (y el guard de la 130 contrasta contra lo vivo). No se busca
   la palabra «Principal»: se compara el valor.
2. **kill_only, por lo que el párrafo declara.** Un párrafo que nombra *kill_only* fuera de
   una cita tiene que decir **dónde vive** esa config (`settings.json`). Es la sustancia de la
   181 —*«es un archivo, no un mecanismo»*— y sirve contra paráfrasis que un patrón como
   *«modo kill_only»* no vería. Las citas «…» se descartan, porque en este corpus las
   correcciones **citan** la frase vieja (la lección de la 97 y la 181: un chequeo por string
   no distingue *«lo afirma»* de *«cuenta que dejó de afirmarlo»*).

**Lo que NO ve, dicho:** una afirmación falsa de mecanismo que además mencione
`settings.json` en el mismo párrafo pasa; y una cuenta viva afirmada con otra forma que
*«Cuenta activa: "X" (id=N)»* no se parsea.
"""

from __future__ import annotations

import re
from pathlib import Path

from analysis.harness_config import LIVE_ACCOUNT_ID, LIVE_ACCOUNT_NAME

_REPO = Path(__file__).resolve().parent.parent

_CORPUS = [
    _REPO / "CLAUDE.md",
    *sorted((_REPO / ".claude").rglob("*.md")),
    _REPO / "docs" / "SETTINGS_REFERENCE.md",
    _REPO / "docs" / "ARCHITECTURE.md",
]

_CITA = re.compile(r"«[^»]*»")
_CUENTA = re.compile(r"[Cc]uenta activa:\**\s*\**\s*\"([^\"]+)\"\s*\(id=(\d+)\)")


def _sin_citas(txt: str) -> str:
    return _CITA.sub("", txt)


def cuentas_afirmadas(txt: str) -> list[tuple[str, int]]:
    return [(nombre, int(i)) for nombre, i in _CUENTA.findall(_sin_citas(txt))]


def cuentas_que_no_son_la_viva(txt: str) -> list[tuple[str, int]]:
    """Las afirmadas como activas cuyo (nombre, id) no es el vivo. Las DOS mitades cuentan."""
    return [c for c in cuentas_afirmadas(txt) if c != (LIVE_ACCOUNT_NAME, LIVE_ACCOUNT_ID)]


def parrafos_killonly_sin_fuente(txt: str) -> list[str]:
    """Párrafos que nombran kill_only fuera de una cita sin decir dónde vive la config."""
    return [
        " ".join(p.split())[:140]
        for p in re.split(r"\n\s*\n", txt)
        if "kill_only" in _sin_citas(p) and "settings.json" not in p
    ]


def _rel(p: Path) -> str:
    return p.relative_to(_REPO).as_posix()


# ── (1) la cuenta ─────────────────────────────────────────────────────────────


def test_toda_cuenta_afirmada_como_activa_es_la_VIVA():
    malas = [
        f"{_rel(p)}: dice {nombre!r} (id={i})"
        for p in _CORPUS
        for nombre, i in cuentas_que_no_son_la_viva(p.read_text(encoding="utf-8"))
    ]
    assert not malas, (
        f"el corpus operativo afirma como activa una cuenta que no es la viva "
        f"({LIVE_ACCOUNT_NAME!r}, id={LIVE_ACCOUNT_ID}) — tarea 198:\n  " + "\n  ".join(malas)
    )


def test_el_chequeo_de_cuenta_no_pasa_por_VACIO():
    """Contraprueba: si el patrón dejara de matchear, el test de arriba pasaría sin mirar nada.
    Hoy lo afirman `CLAUDE.md`, la skill de convenciones y el agente `verificador`."""
    donde = {_rel(p) for p in _CORPUS if cuentas_afirmadas(p.read_text(encoding="utf-8"))}
    assert {"CLAUDE.md", ".claude/agents/verificador.md"} <= donde


def test_el_parseo_de_cuenta_reconoce_el_caso_real_y_descarta_la_cita():
    assert cuentas_afirmadas('Cuenta activa: "Sim Principal" (id=1), modo kill_only.') == [
        ("Sim Principal", 1)
    ]
    assert cuentas_afirmadas('**Cuenta activa: "Sim Segundo" (id=2)** — `auto`') == [("Sim Segundo", 2)]
    assert cuentas_afirmadas('decía «Cuenta activa: "Sim Principal" (id=1)» y era viejo') == []


def test_el_NOMBRE_vivo_con_el_id_equivocado_tambien_se_acusa():
    """Lo cazó una mutación: comparando sólo el nombre, el guard seguía verde con un id que
    apunta a otra cuenta. Un agente que lee «id=1» consulta la fila equivocada de la DB."""
    vivo = f'Cuenta activa: "{LIVE_ACCOUNT_NAME}" (id={LIVE_ACCOUNT_ID})'
    assert cuentas_que_no_son_la_viva(vivo) == []
    assert cuentas_que_no_son_la_viva(f'Cuenta activa: "{LIVE_ACCOUNT_NAME}" (id={LIVE_ACCOUNT_ID + 1})')
    assert cuentas_que_no_son_la_viva(f'Cuenta activa: "Otra" (id={LIVE_ACCOUNT_ID})')


# ── (2) kill_only ─────────────────────────────────────────────────────────────


def test_ningun_parrafo_presenta_kill_only_sin_decir_donde_vive():
    malos = [
        f"{_rel(p)}: {par}"
        for p in _CORPUS
        for par in parrafos_killonly_sin_fuente(p.read_text(encoding="utf-8"))
    ]
    assert not malos, (
        "estos párrafos nombran kill_only como si fuera un modo o un mecanismo, sin decir que "
        "es la config de `~/.finanzias/settings.json` (tarea 181/198):\n  " + "\n  ".join(malos)
    )


def test_el_chequeo_de_kill_only_reconoce_las_cuatro_frases_que_la_198_corrigio():
    """Contraprueba con los textos reales de antes: los cuatro tienen que disparar."""
    viejas = [
        "Modo **kill_only** (hmm_enabled=False, stacking_enabled=False; XGBoost y vol_overlay siempre ON).",
        'Cuenta activa: "Sim Principal" (id=1), modo kill_only.',
        "el stacking XGBoost no es determinístico entre runs (por eso está en kill_only).",
        "| `xgb_signal_enabled` | `True` | XGBoost en la señal. (ON en kill_only) |",
    ]
    for frase in viejas:
        assert parrafos_killonly_sin_fuente(frase), frase


def test_una_correccion_que_CITA_la_frase_vieja_no_dispara():
    """El falso positivo que hundió a los guards por substring de esta semana."""
    assert parrafos_killonly_sin_fuente("Acá decía «está en modo kill_only» y era falso.") == []
    assert (
        parrafos_killonly_sin_fuente("«kill_only» es el nombre de la config de `~/.finanzias/settings.json`.")
        == []
    )
