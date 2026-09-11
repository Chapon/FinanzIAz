"""Tarea 172 — un archivo versionado con CRLF en el working tree deja de pasar inadvertido.

`.gitattributes` declara `* text=auto eol=lf`: git escribe **LF** en el working tree, y las
únicas excepciones son `.bat`/`.cmd`, que lo **necesitan** (regla 4 de `CLAUDE.md`) y que
`.gitattributes` fija en `eol=crlf`. Cualquier otro archivo con CRLF en disco **no vino de un
checkout**: lo escribió una herramienta que ignoró la convención.

**Corregido por la tarea 173.** Este archivo decía además que `data/catalyst/*.json` era una
tercera excepción *«que el propio `.gitattributes` acepta»*. Es **falso**: esa línea declara
`eol=lf`, igual que la global. El defecto estaba en los dos builders, que escribían con
`write_text` sin `newline`; arreglados ellos, la excepción por glob se fue y los dos tests
que la sostenían se dan vuelta acá y en `test_crlf_builders_t173.py`.

**Por qué se acumuló:** git normaliza al comparar, así que `git status` queda **limpio** y el
desvío no aparece en ningún lado. Medido el 2026-09-10: **16** archivos versionados estaban
CRLF contra un blob LF —seis `scripts/*.py`, cuatro docs, `requirements.lock`,
`.claude/settings.json`, `data/sp500_universe.txt`, un test— y el contenido era **idéntico**
(`git diff` vacío en los 15 que se normalizaron). O sea que lo que se rompe no es el
contenido: es cualquier comparación **byte a byte** hecha fuera de git — un hash, un `diff`,
o un guard que lea bytes, que es lo que este chequeo hace.

`check_repo_health.py` ya miraba el eje contrario desde siempre (*«.bat sin CRLF»*). Le
faltaba éste, que es el mismo footgun por el otro lado: **el que escribe tiene que decir qué
saltos quiere**.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_repo_health import (
    _CRLF_PERMITIDO,
    _CRLF_PERMITIDO_GLOBS,
    check_bat_crlf,
    check_crlf_en_working_tree,
)

_REPO = Path(__file__).resolve().parent.parent


# ── El estado real del repo ──────────────────────────────────────────────────


def test_el_repo_NO_tiene_archivos_versionados_con_CRLF():
    """El invariante, sobre el repo de verdad. Si alguien regenera un archivo versionado
    con `Path.write_text()` en Windows, esto se pone rojo (tarea 165: tres scripts lo
    hacían)."""
    from scripts.check_repo_health import _all_files

    problemas = check_crlf_en_working_tree(_all_files())
    assert not problemas, "hay archivos versionados con CRLF en el working tree:\n" + "\n".join(problemas)


def test_los_bat_siguen_necesitando_CRLF_y_el_guard_lo_sigue_pidiendo():
    """**Contraprueba del de arriba, y no es redundante:** los dos chequeos miran el mismo
    byte y piden lo **opuesto**, así que un arreglo mal hecho de uno rompe el otro. Si
    alguien "normalizara" los `.bat` a LF, `cmd.exe` los mata en silencio (regla 4)."""
    from scripts.check_repo_health import _all_files

    assert not check_bat_crlf(_all_files())
    bats = list(_REPO.glob("*.bat")) + list((_REPO / "scripts").glob("*.bat"))
    if not bats:
        pytest.skip("no hay .bat en esta copia")
    # y el chequeo nuevo no puede estar acusándolos
    assert not [p for p in check_crlf_en_working_tree(bats)]


# ── El predicado, caso por caso ──────────────────────────────────────────────


def test_acusa_un_versionado_con_CRLF(tmp_path, monkeypatch):
    """Montaje mínimo: un archivo con CRLF que git «versiona»."""
    import scripts.check_repo_health as g

    f = tmp_path / "algo.md"
    f.write_bytes(b"uno\r\ndos\r\n")
    monkeypatch.setattr(g, "ROOT", tmp_path)
    monkeypatch.setattr(g, "_tracked", lambda: frozenset({"algo.md"}))
    problemas = g.check_crlf_en_working_tree([f])
    assert len(problemas) == 1
    assert "algo.md" in problemas[0] and "2 CRLF" in problemas[0]


def test_un_archivo_MIXTO_se_nombra_como_mixto(tmp_path, monkeypatch):
    """Mezclar los dos saltos en un archivo es peor que cualquiera de los dos puros —
    rompe cualquier parser que cuente líneas—, así que el mensaje lo dice."""
    import scripts.check_repo_health as g

    f = tmp_path / "mixto.py"
    f.write_bytes(b"uno\r\ndos\ntres\r\n")
    monkeypatch.setattr(g, "ROOT", tmp_path)
    monkeypatch.setattr(g, "_tracked", lambda: frozenset({"mixto.py"}))
    (problema,) = g.check_crlf_en_working_tree([f])
    assert "MIXTO" in problema


def test_NO_acusa_lo_que_git_no_versiona(tmp_path, monkeypatch):
    """Un artefacto local con CRLF no le importa a nadie: el invariante es sobre lo que
    está en el repo. Sin esto el guard gritaría por cada log y cada cache."""
    import scripts.check_repo_health as g

    f = tmp_path / "artefacto.json"
    f.write_bytes(b"{}\r\n")
    monkeypatch.setattr(g, "ROOT", tmp_path)
    monkeypatch.setattr(g, "_tracked", lambda: frozenset())
    assert g.check_crlf_en_working_tree([f]) == []


def test_NO_acusa_un_archivo_en_LF(tmp_path, monkeypatch):
    import scripts.check_repo_health as g

    f = tmp_path / "sano.md"
    f.write_bytes(b"uno\ndos\n")
    monkeypatch.setattr(g, "ROOT", tmp_path)
    monkeypatch.setattr(g, "_tracked", lambda: frozenset({"sano.md"}))
    assert g.check_crlf_en_working_tree([f]) == []


def test_NO_acusa_un_BINARIO(tmp_path, monkeypatch):
    """Un `\\r\\n` dentro de un binario es un byte cualquiera. El null-byte lo cubre el otro
    chequeo, que es el que sabe leerlo."""
    import scripts.check_repo_health as g

    f = tmp_path / "cosa.bin"
    f.write_bytes(b"\x00\x01\r\n\x00")
    monkeypatch.setattr(g, "ROOT", tmp_path)
    monkeypatch.setattr(g, "_tracked", lambda: frozenset({"cosa.bin"}))
    assert g.check_crlf_en_working_tree([f]) == []


# ── Las excepciones: declaradas, con motivo, y verificadas contra .gitattributes ──


def test_cada_excepcion_tiene_motivo_escrito():
    """Una excepción sin motivo es una lista de conveniencia disfrazada."""
    for clave, motivo in {**_CRLF_PERMITIDO, **_CRLF_PERMITIDO_GLOBS}.items():
        assert len(motivo) > 40, f"{clave} sin motivo escrito"


def declared_eol(patron: str) -> str | None:
    """El `eol=` que `.gitattributes` declara para ese patrón exacto, o `None`.

    **Tarea 173.** Existe porque la versión anterior de la contraprueba de abajo preguntaba
    `patron in attrs` —o sea, matcheaba la **ruta**— y con eso aceptó como permiso una línea
    que declara `eol=lf`, que es justo lo contrario. Un cross-check tiene que mirar el
    **valor**, no el nombre.
    """
    for linea in (_REPO / ".gitattributes").read_text(encoding="utf-8").splitlines():
        linea = linea.split("#", 1)[0].strip()
        if not linea:
            continue
        campos = linea.split()
        if campos[0] != patron:
            continue
        for c in campos[1:]:
            if c.startswith("eol="):
                return c[4:]
    return None


def test_las_excepciones_son_LAS_QUE_GITATTRIBUTES_DECLARA():
    """**La contraprueba que hace honesto al guard:** las excepciones no las elegí yo, las
    declara `.gitattributes`. Si alguien agrega una acá sin agregarla allá, el guard se
    estaría aflojando por su cuenta — y si la saca de allá, ésta queda huérfana.

    **Tarea 173:** ahora exige `eol=crlf`, no la mera presencia del patrón. Con la versión
    vieja, agregar `data/catalyst/*.json` —una línea `eol=lf`— pasaba en verde.
    """
    attrs = (_REPO / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in attrs, "cambió la convención global: revisar este guard"
    assert declared_eol("*.bat") == "crlf"
    assert declared_eol("*.cmd") == "crlf"
    # y al revés: toda excepción del guard tiene que estar declarada **como crlf** allá.
    for glob in _CRLF_PERMITIDO_GLOBS:
        assert declared_eol(glob) == "crlf", f"{glob} no está declarado `eol=crlf` en .gitattributes"
    for ext in _CRLF_PERMITIDO:
        assert declared_eol(f"*{ext}") == "crlf", f"{ext} no está declarado `eol=crlf`"
