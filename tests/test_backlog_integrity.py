"""BACKLOG-TRUNC (tarea 66) — que el backlog no se pueda vaciar en silencio.

El 2026-08-31 el commit de cierre de la tarea 65 fue un diff de **+12 / −767**:
escribió bien su retro arriba y en el mismo commit se llevó puesto todo el archivo
desde el segundo ítem de *Acciones manuales pendientes* hasta el final — las **69**
secciones ``### NN.``, las diez notas de repriorización y cinco secciones ``##``
enteras. De 956 líneas a 201.

**Y fue invisible cuatro commits.** Nada en la suite cubría el archivo,
``git status`` salía limpio, el CI estaba verde, y el resultado **se lee entero
como un backlog válido**: header, contrato y una sección *En curso* con diez
retros. Saltó de casualidad, porque el *"la próxima es la 62"* no tenía a dónde
apuntar.

Este archivo es la mitad que corre en el **CI** (el job de pytest gatea). La otra
mitad —*"este commit le saca N líneas"*— necesita el diff contra el índice, así que
no puede correr acá sola: su cableado operativo es el **paso 3a de ``/ship``**.

**CORREGIDO 2026-09-03 (tarea 97).** Acá decía que esa mitad *"vive en el hook de
``pre-commit``"* y que *"acá se testea su lógica"*. **Las dos cosas eran falsas.**
El hook nunca se instaló —``.git/hooks/`` tiene sólo ``.sample``— así que estuvo
declarado y sin correr desde el 2026-09-01; y de su lógica no había **ningún**
test: uno cubría el fail-open fuera de un repo y el otro una propiedad de la
constante. El parseo del ``--numstat``, la resta y el umbral entraban al CI sin
cubrir. Ahora se ejercitan contra un repo git de verdad
(``test_el_borrado_grande_*``).

El test que más vale sigue siendo el último: el guard se corre contra **el commit
real que rompió el archivo** y tiene que gritar.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from scripts.check_backlog_integrity import (
    MAX_LINES_LOST,
    check_file,
    check_staged_shrink,
    check_text,
    declared_sections,
)

_REPO = Path(__file__).resolve().parent.parent
_BACKLOG = _REPO / "docs" / "BACKLOG.md"

_HEADER = (
    "# Backlog\n\n"
    "**Secciones obligatorias de este archivo (tarea 66):** `En curso` · `Próximo` · `Hecho reciente`.\n\n"
)
_CUERPO = (
    "## En curso (WIP, máx 1)\n\n- algo. La próxima es la **7**.\n\n"
    "## Próximo (priorizado)\n\n### 7. UNA — la que sigue\n- qué hace\n\n"
    "## Hecho reciente\n\n- [x] otra\n"
)


# ── El archivo de verdad ──────────────────────────────────────────────────────


def test_the_real_backlog_is_intact():
    """El guard sobre el archivo vivo. Si esto se pone rojo, el backlog perdió algo
    — y la respuesta es **restaurarlo**, no relajar el test."""
    assert check_file() == []


def test_the_contract_is_the_source_of_truth_not_a_hardcoded_list():
    """La opción (b) del enunciado: el checker lee las secciones obligatorias **del
    header del backlog**. Con una lista hardcodeada, renombrar una sección sería un
    fallo del guard en vez de un cambio de documento."""
    declaradas = declared_sections(_BACKLOG.read_text(encoding="utf-8"))
    assert declaradas, "el header dejó de declarar las secciones obligatorias"
    assert "En curso" in declaradas and "Hecho reciente" in declaradas
    # y están declaradas por prefijo: los títulos reales llevan paréntesis
    txt = _BACKLOG.read_text(encoding="utf-8")
    for nombre in declaradas:
        assert f"\n## {nombre}" in txt


# ── Qué detecta ───────────────────────────────────────────────────────────────


def test_a_healthy_file_says_nothing():
    assert check_text(_HEADER + _CUERPO) == []


def test_a_missing_section_is_caught():
    """El caso literal: una sección ``##`` que estaba y dejó de estar."""
    roto = (_HEADER + _CUERPO).replace("## Hecho reciente\n\n- [x] otra\n", "")
    probs = check_text(roto)
    assert any("FALTA la sección obligatoria '## Hecho reciente'" in p for p in probs)


def test_a_section_that_survives_EMPTY_is_the_same_loss():
    """Un título sin contenido no es una sección: es el mismo borrado con otra
    forma, y pasaría un chequeo que sólo mire los encabezados."""
    roto = (_HEADER + _CUERPO).replace("## Hecho reciente\n\n- [x] otra\n", "## Hecho reciente\n\n")
    probs = check_text(roto)
    assert any("quedó VACÍA" in p and "Hecho reciente" in p for p in probs)


def test_a_dangling_next_pointer_is_caught():
    """Es EXACTAMENTE lo que se rompió, y es un invariante **estructural**: no pide
    un umbral ni una cuenta mínima que alguien tenga que ir subiendo a mano."""
    roto = (_HEADER + _CUERPO).replace("### 7. UNA — la que sigue\n- qué hace\n", "")
    probs = check_text(roto)
    assert any("'la próxima es la 7' no apunta a ningún lado" in p for p in probs)


def test_a_backlog_with_no_tasks_at_all_is_caught():
    """El caso extremo, que es el que efectivamente pasó: cero ``### NN.``."""
    probs = check_text(
        _HEADER + "## En curso\n\n- nada\n\n## Próximo\n\n- nada\n\n## Hecho reciente\n\n- nada\n"
    )
    assert any("ni una sección de tarea" in p for p in probs)


def test_without_the_declaration_the_guard_says_so_instead_of_passing():
    """Si alguien borra la línea del contrato, el guard **no** puede quedarse
    callado: sin fuente de verdad no chequea nada, y eso es un problema, no un OK."""
    probs = check_text("# Backlog\n\n" + _CUERPO)
    assert len(probs) == 1 and "no declara las secciones obligatorias" in probs[0]


def test_a_grouped_pointer_checks_every_task_in_the_block():
    """El archivo usa las dos formas: «la próxima es la **62**» y
    «la próxima es la **29/30/31**», que es un bloque de tareas chicas que van
    juntas. Si el guard sólo entendiera la primera, la segunda quedaría **sin
    chequear** — y la mitad de la cola inmediata está escrita así."""
    txt = _HEADER + _CUERPO.replace("La próxima es la **7**", "La próxima es la **7/8**")
    probs = check_text(txt)
    assert any("'la próxima es la 8' no apunta a ningún lado" in p for p in probs)
    assert not any("la próxima es la 7'" in p for p in probs)


def test_a_letter_suffixed_task_counts(tmp_path):
    """El backlog tiene tareas como ``### 26b.``: el puntero a la 26 tiene que
    resolver igual, o el guard gritaría por una convención que el archivo usa."""
    txt = _HEADER + _CUERPO.replace("### 7. UNA", "### 7b. UNA")
    assert check_text(txt) == []


# ── El otro eje: el borrado grande, que necesita el diff ─────────────────────


def test_the_shrink_check_is_fail_open_outside_a_repo(tmp_path):
    """Sin git no se puede saber qué se borró, y un guard que rompe commits por no
    poder mirar es peor que el problema que resuelve."""
    assert check_staged_shrink(tmp_path / "no_existe.md") == []


def test_the_shrink_threshold_is_far_below_what_actually_happened():
    """El umbral separa *saqué un ítem viejo* de *me llevé media cola*. El caso real
    fueron **767** líneas; si alguien lo subiera por encima de eso, el guard dejaría
    de cubrir el commit que lo motivó."""
    assert 0 < MAX_LINES_LOST < 767


# ── La lógica del borrado grande, contra un repo git de verdad (tarea 97) ─────
#
# Hasta el 2026-09-03 esto NO estaba cubierto por nada: el parseo del `--numstat`,
# la resta `borradas - agregadas` y la comparación contra el umbral entraban al CI
# sin un solo test. Los dos que existían cubrían el fail-open fuera de un repo y una
# propiedad de la constante — ninguno ejercitaba la función con un índice cargado.


def _git(repo: Path, *args: str):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)


@pytest.fixture
def repo_con_backlog(tmp_path, monkeypatch):
    """Un repo git real con un backlog de 200 líneas ya commiteado.

    Se re-apunta ``REPO`` del módulo porque la función lo usa para **las dos** cosas:
    el ``cwd`` del ``git diff`` y el ``relative_to`` del path. Sin eso, el test miraría
    el índice del repo de verdad — que es justo lo que no se puede tocar desde un test.
    """
    import scripts.check_backlog_integrity as guard

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@finanzias.local")
    _git(tmp_path, "config", "user.name", "test")
    doc = tmp_path / "docs" / "BACKLOG.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("\n".join(f"linea {i}" for i in range(200)) + "\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    monkeypatch.setattr(guard, "REPO", tmp_path)
    return tmp_path, doc


def test_el_borrado_grande_frena_el_commit(repo_con_backlog):
    """El caso de la 66: se stagea un archivo mutilado y el guard tiene que gritar."""
    repo, doc = repo_con_backlog
    doc.write_text("linea 0\n", encoding="utf-8")  # 200 → 1
    _git(repo, "add", "docs/BACKLOG.md")

    problemas = check_staged_shrink(doc)

    assert len(problemas) == 1
    # El mensaje tiene que llevar los NÚMEROS, no un "algo pasó": es lo que deja
    # decidir si el borrado fue a propósito.
    assert "199" in problemas[0]
    assert "docs/BACKLOG.md" in problemas[0]


def test_el_borrado_chico_pasa(repo_con_backlog):
    """Sacar un ítem viejo es trabajo normal y no puede frenar un commit."""
    repo, doc = repo_con_backlog
    quedan = doc.read_text(encoding="utf-8").split("\n")[: 200 - (MAX_LINES_LOST - 10)]
    doc.write_text("\n".join(quedan) + "\n", encoding="utf-8")
    _git(repo, "add", "docs/BACKLOG.md")

    assert check_staged_shrink(doc) == []


def test_lo_que_cuenta_es_el_NETO_no_las_borradas(repo_con_backlog):
    """Reescribir el archivo entero borra 200 y agrega 200: no perdió nada.

    Si el guard mirara sólo las borradas, un reordenamiento grande —o un cierre que
    reescribe media cola sin perderla— frenaría el commit. La resta es lo que
    distingue *«lo reescribí»* de *«me lo llevé puesto»*.
    """
    repo, doc = repo_con_backlog
    doc.write_text("\n".join(f"otra linea {i}" for i in range(200)) + "\n", encoding="utf-8")
    _git(repo, "add", "docs/BACKLOG.md")

    assert check_staged_shrink(doc) == []


def test_sin_nada_staged_no_dice_nada(repo_con_backlog):
    """El archivo mutilado en el working tree pero NO en el índice: no hay commit
    que frenar todavía, y acusar acá sería ruido en cada edición a medio hacer."""
    _repo, doc = repo_con_backlog
    doc.write_text("linea 0\n", encoding="utf-8")

    assert check_staged_shrink(doc) == []


def test_el_cableado_operativo_es_ship_y_no_el_yaml():
    """Regresión del cableado **operativo** — tarea 97.

    Este test antes leía ``.pre-commit-config.yaml`` y asserteaba que el string
    estuviera ahí. Eso verifica **la declaración**, no la condición que hace que el
    guard corra: el hook nunca se instaló (``.git/hooks/`` tiene sólo ``.sample``,
    ``core.hooksPath`` vacío en los tres niveles), así que pasaba en verde mientras
    la mitad ``--staged`` no se ejecutaba **ni una vez**. Su propio docstring lo
    decía sin darse cuenta: *"si el instrumento existe y no lo llama nadie, el
    archivo se sigue pudiendo vaciar"*.

    Ahora se fija el camino que **sí** se recorre: el paso 3a de ``/ship``.
    """
    ship = (_REPO / ".claude" / "commands" / "ship.md").read_text(encoding="utf-8")
    assert "check_backlog_integrity.py --staged" in ship, (
        "el guard del backlog salió del paso 3a de /ship — es su único cableado operativo"
    )
    # Y su hermano de la 98, que vive en el mismo paso por la misma razón.
    assert "check_repo_health.py --staged" in ship


def test_ningun_doc_afirma_que_el_hook_corre_solo():
    """El claim que la 97 vino a borrar, fijado para que no vuelva.

    ``CLAUDE.md`` y el header del backlog decían *"corre en la suite y en
    `pre-commit`"* en presente indicativo, sobre un hook no instalado. El costo de
    ese tipo de frase no es cosmético: se lee cada sesión y manda a **no** verificar.

    **Busca la AFIRMACIÓN, no el string** — y esa distinción se pagó escribiéndolo mal
    primero. La versión inicial asserteaba ``"y en `pre-commit`" not in txt`` y se puso
    roja contra los propios retros que **citan** la frase para decir que se corrigió:
    un chequeo que mide el string en vez de lo que el string afirma, que es justo la
    familia de defecto de la auditoría que lo motivó. Por eso se descartan los tramos
    entre ``«»``, que en este corpus son **citas**, no afirmaciones del documento.

    **Lo que este test NO puede ver, dicho acá al lado (criterio de la 89):** una
    paráfrasis. *"El hook de pre-commit lo chequea"* pasa limpio. Cubre la reincidencia
    literal, que es la que ya ocurrió tres veces en tres archivos.
    """
    citas = re.compile(r"«[^»]*»")
    afirmacion = re.compile(r"corre[^.\n]{0,60}en `pre-commit`", re.IGNORECASE)

    for rel in ("CLAUDE.md", "docs/BACKLOG.md"):
        txt = citas.sub("", (_REPO / rel).read_text(encoding="utf-8"))
        m = afirmacion.search(txt)
        assert m is None, (
            f"{rel} vuelve a afirmar que el guard corre en pre-commit "
            f"({m.group(0)!r}); en este repo no hay hooks de git instalados y su "
            "cableado operativo es el paso 3a de /ship (tarea 97)"
        )


# ── La validación que importa: el commit real que rompió el archivo ──────────


def test_the_guard_catches_the_commit_that_actually_broke_it():
    """El guard corrido contra ``86fea6a`` — el cierre de la 65, que dejó el backlog
    en 201 líneas. Se le pega la declaración de hoy (ese commit es anterior al
    contrato) porque la pregunta es si **el guard de hoy** lo habría frenado.

    Si no hay git o el commit no está (checkout superficial), se saltea: es una
    verificación contra la historia, no algo que el código de hoy pueda romper.
    """
    r = subprocess.run(
        ["git", "show", "86fea6a:docs/BACKLOG.md"],
        cwd=_REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if r.returncode != 0 or not r.stdout:
        pytest.skip("sin acceso al commit 86fea6a (checkout superficial o sin git)")

    declaracion = next(
        line
        for line in _BACKLOG.read_text(encoding="utf-8").split("\n")
        if line.startswith("**Secciones obligatorias")
    )
    probs = check_text(r.stdout.replace("---", declaracion + "\n\n---", 1))

    assert any("ni una sección de tarea" in p for p in probs)
    assert any("'la próxima es la 62' no apunta a ningún lado" in p for p in probs)
    assert sum(1 for p in probs if "FALTA la sección obligatoria" in p) >= 5
