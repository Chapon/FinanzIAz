"""Tarea 161 — el guard del BOM pasa de probar UNA función a barrer el repo por AST.

**El defecto.** Había **siete** copias de ``parse_universe_file`` y el arreglo de la tarea
**41** —leer con ``utf-8-sig``— vivía en **una**: ``scripts/precompute_pit_signals``. Las
otras seis leían con ``utf-8`` pelado (``harness_walkforward``, ``prefetch_harness_cache``,
``run_cross_sectional_validation``, ``run_dd_breaker_validation``,
``run_switcher_validation``, ``run_walkforward_power``).

PowerShell 5.1 —el shell de la máquina de Chapa— escribe UTF-8 **con BOM** por default, y
con ``utf-8`` pelado el BOM se pega al primer ticker (``\\ufeffABBV``), que después no
encuentra su artefacto PIT y **se cae del universo con un simple AVISO**. Ya costó un
ticker una vez: es lo que la 41 vino a arreglar.

**Y el guard de la 41 miraba UNA de las siete.** ``test_universe_file_with_bom_does_not_lose_
the_first_ticker`` importaba de ``precompute_pit_signals``: su población era **una sola
implementación**, así que era estructuralmente ciego a las otras seis — la forma de la 110 y
la 101, y de la familia 133 / 141 / 147 (*«la población del guard es una lista y no un
predicado»*).

**Medido antes de unificar, que es lo que hizo segura la consolidación:** sobre los 5
archivos de universo del repo las siete daban **cero diferencias** (así que no movió ninguna
muestra), y con un BOM sólo la canónica devolvía ``ABBV`` — las otras seis, ``\\ufeffABBV``.

**El cambio de forma que esta tarea shipea** es que el chequeo deja de ser *«esta función
maneja el BOM»* y pasa a ser un **predicado por AST sobre todo el repo**: ninguna lectura de
un archivo de universo puede usar ``utf-8`` pelado. Un lector nuevo no puede nacer invisible.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from analysis.harness_config import parse_universe_file

_REPO = Path(__file__).resolve().parent.parent

# Los siete call sites que tenían su propia copia. Se nombran para que el test de identidad
# sea concreto: no alcanza con que la canónica exista, tienen que estar usándola.
_CONSUMIDORES: tuple[str, ...] = (
    "scripts.precompute_pit_signals",
    "scripts.harness_walkforward",
    "scripts.prefetch_harness_cache",
    "scripts.run_cross_sectional_validation",
    "scripts.run_dd_breaker_validation",
    "scripts.run_switcher_validation",
    "scripts.run_walkforward_power",
)

# Encodings que pierden el BOM al principio del archivo. `utf-8-sig` lo consume; `utf-8`
# lo deja pegado al primer token. `None` (default) es peor: depende del locale.
_ENCODINGS_MALOS = {"utf-8", "utf8", "UTF-8", None}


# ── El comportamiento, sobre la canónica y sobre los siete ───────────────────


def test_un_universo_con_BOM_no_pierde_el_primer_ticker(tmp_path):
    """El caso de la 41, sobre la implementación única."""
    f = tmp_path / "universo.txt"
    f.write_bytes("﻿ABBV\nAAPL\n# comentario\nMSFT\n".encode())
    assert parse_universe_file(f) == ["ABBV", "AAPL", "MSFT"]


def test_sin_BOM_el_comportamiento_es_IDENTICO(tmp_path):
    """Contraprueba: `utf-8-sig` no es un parche que cambie el caso normal."""
    f = tmp_path / "universo.txt"
    f.write_bytes(b"ABBV\nAAPL\n# comentario\nMSFT\n")
    assert parse_universe_file(f) == ["ABBV", "AAPL", "MSFT"]


def test_el_parser_conserva_su_semantica(tmp_path):
    """Lo que las siete copias hacían y que unificar no podía perder: `#` como comentario
    en cualquier posición, comas dentro de una línea, uppercase, y dedupe **preservando el
    orden** (no un `set`, que rompería la reproducibilidad de cualquier barrido)."""
    f = tmp_path / "universo.txt"
    f.write_text("aapl, msft  # dos en una\n\nAAPL\n# toda comentario\nNVDA\n", encoding="utf-8")
    assert parse_universe_file(f) == ["AAPL", "MSFT", "NVDA"]


@pytest.mark.parametrize("modulo", _CONSUMIDORES)
def test_los_siete_usan_LA_MISMA_funcion(modulo):
    """**El test que la 41 no podía escribir**, porque había siete implementaciones. Ahora
    se exige identidad de objeto: no que el resultado coincida —eso coincidía también antes
    sobre archivos sin BOM— sino que sea literalmente la misma función."""
    import importlib

    mod = importlib.import_module(modulo)
    assert mod.parse_universe_file is parse_universe_file, (
        f"{modulo} tiene su propia copia otra vez: el arreglo del BOM vuelve a estar en un "
        "solo lado y las demás pierden el primer ticker en silencio"
    )


# ── El predicado por AST: la población se descubre ──────────────────────────


def _lee_codigo_fuente(fn: ast.AST) -> bool:
    """¿Esta función itera archivos ``.py``? Entonces sus lecturas son de **fuente**, no de
    universos, y ``utf-8`` pelado es lo correcto ahí."""
    for nodo in ast.walk(fn):
        if not isinstance(nodo, ast.Call):
            continue
        nombre = getattr(nodo.func, "attr", None)
        if nombre not in ("glob", "rglob"):
            continue
        for arg in nodo.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.endswith(".py"):
                return True
    return False


def _lecturas_de_universo() -> list[tuple[str, int, str | None]]:
    """``(archivo, línea, encoding)`` de cada ``read_text``/``open`` sobre algo que parece
    un archivo de universo, barrido por **AST** y no por grep.

    Se detecta por el **nombre de la función que la contiene**; un `grep` de ``utf-8``
    daría cientos de falsos positivos (todo el repo lee archivos) y uno de
    ``parse_universe_file`` sólo encontraría las copias con ese nombre exacto — que es el
    defecto que esta tarea cierra. Con este predicado aparecieron **nueve** lectores y el
    enunciado decía siete: los dos extra eran ``ingest_form345._load_universe`` y
    ``refresh_cohort.universo_vivo``, que no se llaman ``parse_universe_file`` y leían con
    ``utf-8`` pelado igual.

    **Se excluyen las funciones que leen código fuente**, y no es una excepción de
    conveniencia: un barrido por AST —como los de las tareas 158, 161 y ésta— tiene
    ``read_text(encoding="utf-8")`` sobre archivos ``.py``, que es **correcto** (el fuente
    del repo es UTF-8 sin BOM y ruff lo garantiza). La señal estructural que las distingue
    es que iteran un ``glob``/``rglob`` de ``*.py``. Sin esto el guard se acusaba **a sí
    mismo** — su propio helper lee los ``.py`` del repo — que es el falso positivo más
    barato de tener y el más fácil de silenciar con un allowlist en vez de con un
    predicado.
    """
    hallazgos: list[tuple[str, int, str | None]] = []
    for py in sorted(_REPO.rglob("*.py")):
        rel = py.relative_to(_REPO).as_posix()
        if any(x in rel.split("/") for x in (".venv", "venv", "__pycache__")):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if "univers" not in fn.name.lower():
                continue
            if _lee_codigo_fuente(fn):
                continue
            for nodo in ast.walk(fn):
                if not isinstance(nodo, ast.Call):
                    continue
                nombre = getattr(nodo.func, "attr", None) or getattr(nodo.func, "id", None)
                if nombre not in ("read_text", "open", "read_bytes"):
                    continue
                enc = next(
                    (
                        k.value.value
                        for k in nodo.keywords
                        if k.arg == "encoding" and isinstance(k.value, ast.Constant)
                    ),
                    None,
                )
                hallazgos.append((rel, nodo.lineno, enc))
    return hallazgos


def test_el_barrido_AST_encuentra_lecturas():
    """Contraprueba de población: sin esto, un cambio de nombre de función dejaría el test
    de abajo pasando **por vacío** y "demostrando" que nadie lee con `utf-8` pelado."""
    lecturas = _lecturas_de_universo()
    assert lecturas, "el barrido AST no encontró ninguna lectura de universo: revisar el predicado"
    assert any("harness_config" in rel for rel, _, _ in lecturas), (
        "el barrido no ve la implementación canónica, que es la que tiene que ver primero"
    )


def test_NINGUNA_lectura_de_universo_usa_utf8_pelado():
    """**El invariante, y el cambio de forma de esta tarea.** Deja de ser *«esta función
    maneja el BOM»* y pasa a ser *«ninguna lectura de universo puede perderlo»*."""
    malas = [
        f"{rel}:{ln} (encoding={enc!r})"
        for rel, ln, enc in _lecturas_de_universo()
        if enc in _ENCODINGS_MALOS
    ]
    assert not malas, (
        "estas lecturas de archivos de universo pierden el BOM y con él el primer ticker "
        "(tareas 41 y 161) — usar `utf-8-sig`:\n  " + "\n  ".join(malas)
    )


def test_ya_no_queda_ninguna_copia_de_la_funcion():
    """El conteo que la tarea existe para bajar de siete a uno, **derivado** y no escrito:
    una sola definición de `parse_universe_file` en todo el repo. El archivo se afirma; la
    línea **no**, que es un literal que caduca con el próximo edit."""
    definiciones = []
    for py in sorted(_REPO.rglob("*.py")):
        rel = py.relative_to(_REPO).as_posix()
        if any(x in rel.split("/") for x in (".venv", "venv", "__pycache__")):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        definiciones += [
            rel for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "parse_universe_file"
        ]
    assert definiciones == ["analysis/harness_config.py"], (
        f"hay {len(definiciones)} definiciones de parse_universe_file: {definiciones}"
    )


# ── La exclusión del guard, con su contraprueba ─────────────────────────────


def test_la_exclusion_de_codigo_fuente_DISPARA_donde_debe():
    """**Contraprueba de la excepción**, para que su motivo esté probado y no sólo escrito.
    Una función que itera `.py` se excluye; una que lee un universo, no. Sin esto, un
    `_lee_codigo_fuente` que devolviera `True` siempre dejaría el guard mudo y todos los
    tests de arriba en verde."""
    lee_fuente = ast.parse(
        "def barrer_universos(root):\n"
        "    for p in root.rglob('*.py'):\n"
        "        p.read_text(encoding='utf-8')\n"
    ).body[0]
    lee_universo = ast.parse(
        "def parse_universe_file(path):\n    return path.read_text(encoding='utf-8')\n"
    ).body[0]

    assert _lee_codigo_fuente(lee_fuente), "no reconoció un barrido de código fuente"
    assert not _lee_codigo_fuente(lee_universo), "excluyó una lectura de universo de verdad"


def test_el_guard_se_pone_rojo_ante_una_lectura_MALA(tmp_path, monkeypatch):
    """Prueba por mutación del predicado mismo, montada en vez de editando el repo: una
    función de universo nueva con `utf-8` pelado tiene que aparecer en el barrido."""
    import tests.test_univparse_bom_t161 as mod

    (tmp_path / "nuevo_lector.py").write_text(
        "from pathlib import Path\n\n\ndef cargar_universo(p: Path):\n"
        '    return p.read_text(encoding="utf-8").splitlines()\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_REPO", tmp_path)
    malas = [(rel, enc) for rel, _, enc in mod._lecturas_de_universo() if enc in _ENCODINGS_MALOS]
    assert malas == [("nuevo_lector.py", "utf-8")], malas
