"""Tarea 179 — la dirección que faltaba, sobre la documentación: *«lo verdadero está escrito»*.

**El guard de la 137 ya cubría una dirección** —*«toda afirmación de la doc coincide con el
código»*, o sea **doc → código**— y con eso caza *«lo escrito es falso»*. Es estructuralmente
incapaz de cazar lo otro: **una perilla viva que no está documentada**. Por esa dirección
faltante, **siete** claves que el camino vivo de decisión lee sobrevivieron a cuatro corridas de
auditoría sin fila en `docs/SETTINGS_REFERENCE.md`.

**Y la más grave no era una olvidada cualquiera:** `vol_target_portfolio_annual` tiene espejo
(`LIVE_VOL_TARGET_ANNUAL`), tiene **desvío declarado** (clave `vol_overlay`, tarea 94), **muerde
todos los días** —escala el libro entero cuando la σ de cartera pasa el techo— y no tenía fila.

**Lo que había en su lugar**, y es peor que nada: una línea de prosa que nombraba cuatro de las
siete y decía *«Ver el código para defaults exactos»*. Mientras `CLAUDE.md` afirmaba que esa doc
tiene *«todos los flags `paper_*`/engine **con defaults**»*. La referencia admitía por escrito
que no cumplía lo que el índice prometía de ella.

**La población es la MISMA que la de la tarea 185** —las claves del `SCHEMA` que el camino vivo
de decisión lee, barridas por AST— y se importa de ahí a propósito: una sola población, dos
preguntas (*¿tiene espejo?* y *¿está documentada?*). Duplicar el barrido sería garantizar que se
separen, que es el defecto de la 161.
"""

from __future__ import annotations

import re
from pathlib import Path

from config.settings_manager import DEFAULTS
from tests.test_espejos_direccion_faltante_t185 import claves_del_camino_vivo

_REPO = Path(__file__).resolve().parent.parent
_REFERENCIA = _REPO / "docs" / "SETTINGS_REFERENCE.md"

# Una fila de la tabla: `| `clave` | ...`. Se matchea sólo el nombre, porque el formato del
# default varía a propósito (`0.0` (OFF)`, `"2y"`, `10_000_000`) y exigirle una forma haría
# frágil al guard — el defecto que la corrida de `claims` del 2026-09-11 cometió midiendo con
# una regex que pedía un `|` pegado al backtick.
_FILA = re.compile(r"^\|\s*`([a-z0-9_]+)`\s*\|", re.M)

# Claves que el camino vivo lee y que **no** necesitan fila, cada una con su motivo. Es un dict
# y no una lista para que agregar una obligue a escribir el porqué (mismo criterio que
# `ARTIFACT_REFRESH_EXCEPTIONS` de la 30 y `_NO_SON_CONSTANTES` de la 72).
SIN_FILA: dict[str, str] = {}


def claves_documentadas() -> set[str]:
    return set(_FILA.findall(_REFERENCIA.read_text(encoding="utf-8")))


# ── La población, y su contraprueba ─────────────────────────────────────────


def test_la_referencia_tiene_filas_para_barrer():
    """Contraprueba: si la tabla cambiara de formato, el test de abajo pasaría **por vacío** y
    "demostraría" que todo está documentado."""
    documentadas = claves_documentadas()
    assert len(documentadas) >= 50, f"sólo {len(documentadas)} filas: ¿cambió el formato?"
    assert documentadas <= set(DEFAULTS), (
        f"la doc tiene filas para claves que no están en el SCHEMA: {sorted(documentadas - set(DEFAULTS))}"
    )


# ── El invariante de la tarea ───────────────────────────────────────────────


def test_TODA_clave_del_camino_vivo_esta_DOCUMENTADA():
    """**La dirección que faltaba.** No *«lo escrito es verdad»* (eso lo cubre la 137) sino
    *«lo verdadero está escrito»*."""
    huerfanas = sorted(set(claves_del_camino_vivo()) - claves_documentadas() - set(SIN_FILA))
    assert not huerfanas, (
        "estas claves las lee el camino vivo de decisión y no tienen fila en "
        "`docs/SETTINGS_REFERENCE.md` (tarea 179). Agregá la fila con su default y qué hace, o "
        "declarala en `SIN_FILA` con el motivo:\n  " + "\n  ".join(huerfanas)
    )


def test_las_SIETE_de_la_179_quedaron_documentadas():
    """Fija el resultado concreto de la tarea, para que un reflow de la doc no las pierda en
    silencio. Si alguna se va, el test de arriba también se pone rojo — éste dice **cuál** era
    el conjunto original y por qué importaba."""
    documentadas = claves_documentadas()
    for clave in (
        "vol_target_portfolio_annual",
        "vol_target_annual",
        "max_position_weight",
        "kelly_fraction",
        "ibkr_commission_plan",
        "cross_sectional_lookback",
        "cross_sectional_weight",
    ):
        assert clave in documentadas, f"{clave} perdió su fila (la agregó la tarea 179)"


def test_cada_fila_del_camino_vivo_TRAE_su_default():
    """**El invariante que la línea de prosa no cumplía.** Lo que había antes de las siete filas
    era *«Sizing (cuando aplique): … Ver el código para defaults exactos»*: nombraba las claves
    y **difería el valor al código**, mientras `CLAUDE.md` prometía *«con defaults»*. Una
    referencia de settings que manda a leer el código para los defaults no es una referencia.

    **Este test se escribió primero como `"Ver el código para defaults exactos" not in txt` y
    estaba mal**: la frase sigue en el doc porque la sección nueva **la cita** como lo que había
    antes. El guard no podía distinguir *«la doc todavía difiere al código»* de *«la doc cuenta
    que dejó de hacerlo»* — el mismo defecto de substring que las tareas 173, 150, 176 y 177.
    Ahora verifica la **sustancia**: que la celda del default tenga un valor.
    """
    filas = re.findall(r"^\|\s*`([a-z0-9_]+)`\s*\|([^|]*)\|", _REFERENCIA.read_text(encoding="utf-8"), re.M)
    defaults = {clave: celda.strip() for clave, celda in filas}
    vivas = set(claves_del_camino_vivo()) & set(defaults)
    sin_default = sorted(c for c in vivas if not defaults[c] or "`" not in defaults[c])
    assert not sin_default, (
        "estas filas nombran la clave pero no traen su default entre backticks, que es "
        "exactamente lo que `CLAUDE.md` promete de esta doc:\n  " + "\n  ".join(sin_default)
    )


def test_CLAUDE_md_sigue_prometiendo_lo_que_la_doc_cumple():
    """La otra mitad, y es la que hace que esto no sea cosmético: el índice de `CLAUDE.md`
    afirma que esta referencia tiene *«todos los flags `paper_*`/engine con defaults»*. Si
    alguien vuelve a diferir defaults al código, la promesa se rompe y hay que cambiar **una de
    las dos**, no dejarlas desalineadas."""
    claude = (_REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert "todos los flags `paper_*`/engine con defaults" in claude, (
        "cambió la promesa de CLAUDE.md sobre SETTINGS_REFERENCE.md: revisar si este guard "
        "sigue verificando lo correcto"
    )
    documentadas = claves_documentadas()
    paper = {c for c in DEFAULTS if c.startswith("paper_")}
    faltan = sorted(paper - documentadas)
    assert not faltan, f"CLAUDE.md promete todos los `paper_*` y faltan: {faltan}"


# ── Las excepciones: vacías hoy, y eso se declara ───────────────────────────


def test_las_excepciones_estan_VACIAS_y_eso_se_dice():
    """`SIN_FILA` está vacío **a propósito**: hoy no hay ninguna clave del camino vivo que
    merezca quedar sin documentar. El mecanismo queda igual para cuando haga falta de verdad —
    mismo criterio con el que la 154 dejó vacía la excepción del guard de la 137 y la 173 la
    del glob de CRLF. Un dict vacío declarado dice *«se pensó y no hizo falta»*; no tenerlo
    dice *«no se pensó»*."""
    assert SIN_FILA == {}, (
        "apareció una excepción: verificá que el motivo diga por qué esa clave del camino vivo "
        f"de decisión no necesita fila. Hoy: {sorted(SIN_FILA)}"
    )


def test_cada_excepcion_declararia_su_motivo():
    """El chequeo de motivos, escrito para que **no se saltee** cuando el dict está vacío.

    La primera versión era un `parametrize` sobre `SIN_FILA` con un `pytest.skip` para el caso
    vacío, y eso deja un **skip permanente** en la suite: exactamente el defecto que la tarea
    **174** cerró hoy —un test que se apaga solo y lo anuncia como si fuera normal—. Un bucle
    sobre un dict vacío pasa **sin saltearse**, que es lo honesto: el chequeo existe y hoy no
    tiene sujeto.
    """
    cortos = [c for c, motivo in SIN_FILA.items() if len(motivo) <= 60]
    assert not cortos, f"estas excepciones tienen un motivo demasiado corto para ser uno: {cortos}"
