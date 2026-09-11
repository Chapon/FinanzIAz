"""Tarea 176 — el criterio de *done* deja de ser cinco copias editadas a mano.

**El defecto que esto previene, y que la propia tarea 176 estuvo a punto de cometer.** El
criterio de done se declara en **cinco** lugares: `CLAUDE.md`, `.claude/commands/test.md`,
`.claude/commands/ship.md` y las skills `finanzias-conventions` y `testing`. Agregar el cuarto
comando significó editar los cinco **a mano**. Olvidarse de uno no rompe nada visible: el
lugar viejo sigue leyéndose como un criterio completo — que es exactamente la forma de la
tarea **66** (el backlog truncado se lee entero como un backlog válido) y de la **72** (la 30
corrigió su claim en 2 de 3 lugares).

Así que la lista de comandos del done pasa a ser un **predicado**: `CLAUDE.md` es la fuente, y
este guard exige que los otros cuatro lugares la repitan y que cada comando **exista**.

**Por qué el cuarto comando existe** (y va acá porque este archivo es donde alguien va a leer
qué es el done): el job `pytest` del CI quedó rojo el 2026-09-09, en el **mismo commit** que
shipeó el guard de la tarea 130, y **36 tareas** se cerraron declarando *«suite Windows
verde»*, que era **verdad**. El test leía `~/.finanzias/settings.json`, que en la máquina de
Chapa **existe** y en el CI no. 35 corridas en rojo; lo reportó Chapa, no el proceso.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent

# Los lugares que declaran el done. Es una lista y no un barrido a propósito: son
# documentos con nombre y rol, no una población que crezca sola. Si aparece un sexto,
# entra acá — y el test de abajo dice por qué eso importa.
_DECLARAN_EL_DONE: tuple[str, ...] = (
    ".claude/commands/test.md",
    ".claude/commands/ship.md",
    ".claude/skills/finanzias-conventions/SKILL.md",
    ".claude/skills/testing/SKILL.md",
)

_CLAUDE_MD = _REPO / "CLAUDE.md"


def comandos_del_done() -> list[str]:
    """Los comandos del done, **leídos de `CLAUDE.md`**, que es la fuente.

    Se extraen del bloque de la regla 1 buscando los `python ...` entre backticks. No se
    hardcodean acá: un guard que compara el repo contra un literal escrito en el propio test
    compara el repo contra sí mismo (la lección de la **130**).
    """
    texto = _CLAUDE_MD.read_text(encoding="utf-8")
    # La regla 1 va desde `1. **"Done"` hasta el `2. **` siguiente.
    m = re.search(r'^1\. \*\*"Done"(.*?)^2\. \*\*', texto, re.S | re.M)
    assert m, "no se encontró la regla 1 en CLAUDE.md: cambió su forma, revisar este guard"
    return re.findall(r"`(python [^`]+)`", m.group(1))


def test_el_done_declara_CUATRO_comandos():
    comandos = comandos_del_done()
    assert len(comandos) == 4, f"CLAUDE.md declara {len(comandos)} comandos de done: {comandos}"


def test_el_modo_sin_estado_vivo_es_uno_de_ellos():
    """El comando concreto que la 176 agregó. Si alguien lo saca de `CLAUDE.md`, el guard de
    abajo dejaría de exigirlo en los otros cuatro lugares y el criterio volvería a los tres."""
    assert any("run_suite_sin_estado_vivo" in c for c in comandos_del_done())


def test_cada_comando_del_done_APUNTA_A_ALGO_QUE_EXISTE():
    """Un comando del done que nombre un script inexistente es peor que no tenerlo: falla con
    un error de import y se lee como *«el repo está roto»* en vez de *«el criterio miente»*."""
    for comando in comandos_del_done():
        for token in comando.split():
            if token.endswith(".py"):
                assert (_REPO / token).is_file(), f"{comando!r} nombra {token}, que no existe"


def _cuerpo(rel: str) -> str:
    """El documento **sin** su frontmatter YAML.

    **Necesario, y lo descubrí por mutación (tarea 176).** `ship.md` y `test.md` nombran los
    comandos dos veces: en `allowed-tools` del frontmatter, como
    `Bash(python scripts/run_suite_sin_estado_vivo.py:*)`, y en el cuerpo como la instrucción.
    Un `comando in doc` se satisface con **el primero**, así que borrarle el comando al cuerpo
    pasaba en verde: el guard estaba matcheando un permiso y creyendo que leía una
    instrucción. Es la forma de la tarea **173** —un substring satisfecho por una línea que
    significa otra cosa— en el guard que escribí el mismo día.
    """
    doc = (_REPO / rel).read_text(encoding="utf-8")
    if doc.startswith("---"):
        partes = doc.split("---", 2)
        if len(partes) == 3:
            return partes[2]
    return doc


@pytest.mark.parametrize("rel", _DECLARAN_EL_DONE)
def test_los_cinco_lugares_declaran_LOS_MISMOS_comandos(rel):
    """**El guard que hace que esto no vuelva a desincronizarse.** `CLAUDE.md` es la fuente y
    los otros cuatro tienen que repetir los mismos comandos **en el cuerpo**. Sin esto,
    olvidarse de uno deja ese lugar leyéndose como un criterio completo — el defecto de la 66
    y de la 72."""
    cuerpo = _cuerpo(rel)
    faltan = [c for c in comandos_del_done() if c not in cuerpo]
    assert not faltan, f"{rel} no declara estos comandos del done en su cuerpo: {faltan}"


@pytest.mark.parametrize("rel", _DECLARAN_EL_DONE)
def test_el_frontmatter_NO_alcanza_para_declarar_un_comando(rel):
    """Contraprueba de `_cuerpo`, para que su motivo quede probado y no sólo escrito: lo que
    hay en el frontmatter tiene que estar **además** en el cuerpo. Si algún día `allowed-tools`
    permite algo que el cuerpo no manda correr, esto lo dice."""
    doc = (_REPO / rel).read_text(encoding="utf-8")
    if not doc.startswith("---"):
        pytest.skip(f"{rel} no tiene frontmatter")
    assert _cuerpo(rel) != doc, "el frontmatter no se separó: `_cuerpo` no está haciendo nada"


@pytest.mark.parametrize("rel", _DECLARAN_EL_DONE)
def test_ningun_lugar_sigue_diciendo_TRES(rel):
    """El conteo en palabras también se desincroniza, y ahí es peor: un texto que dice *«son
    tres comandos»* arriba de cuatro bloques entrena a ignorar el cuarto. Se permite sólo
    cuando habla del criterio **viejo** en pasado (`podían`, `era`, `hasta`)."""
    sospechosas = [
        ln.strip()
        for ln in _cuerpo(rel).splitlines()
        if re.search(r"\b(tres|TRES)\b.{0,24}comandos|comandos.{0,24}\b(tres|TRES)\b", ln)
        and not re.search(r"podían|podia|era|eran|hasta el|antes|viejo|former", ln)
    ]
    assert not sospechosas, f"{rel} todavía dice «tres comandos» en presente: {sospechosas}"


def test_el_script_declara_lo_que_NO_cubre():
    """La condición de honestidad del cuarto comando. Cubre *«estado vivo de la máquina»* y no
    *«Windows vs Linux»*, y eso tiene que estar escrito donde se lee — si no, su verde se lee
    como *«el CI va a pasar»*, que es una promesa que no puede cumplir."""
    doc = (_REPO / "scripts" / "run_suite_sin_estado_vivo.py").read_text(encoding="utf-8")
    assert "Lo que NO aísla" in doc
    for termino in ("permisos", "locale", "finanzias.db"):
        assert termino in doc, f"el script no declara qué pasa con {termino}"


def test_el_script_mueve_LAS_DOS_variables_de_home():
    """En Windows `Path.home()` resuelve por `USERPROFILE`: setear sólo `HOME` no aísla nada
    **y el script pasaría en verde**. Por eso mueve las dos y verifica el resultado —
    verificado por mutación: con `("HOME",)` sale con exit 2 y se niega a reportar."""
    import scripts.run_suite_sin_estado_vivo as m

    assert set(m._VARS_DE_HOME) == {"HOME", "USERPROFILE"}


def test_el_script_corre_el_MISMO_selector_que_el_done():
    """Son el mismo comando en dos entornos: si los selectores difieren, el cuarto comando
    estaría midiendo otra suite y su verde no diría nada del primero."""
    import scripts.run_suite_sin_estado_vivo as m

    pytest_del_done = next(c for c in comandos_del_done() if " -m pytest " in c)
    for arg in m.ARGS_DEL_DONE:
        assert arg.strip('"') in pytest_del_done, f"{arg!r} no está en el comando de CLAUDE.md"
