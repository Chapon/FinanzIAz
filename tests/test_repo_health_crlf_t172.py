"""Tarea 172 — un archivo versionado con CRLF en el working tree deja de pasar inadvertido.

`.gitattributes` declara `* text=auto eol=lf`: git escribe **LF** en el working tree, y las
únicas excepciones son `.bat`/`.cmd` (que lo **necesitan** — regla 4 de `CLAUDE.md`) y
`data/catalyst/*.json` (que el scheduler re-escribe, y el propio `.gitattributes` lo acepta).
Cualquier otro archivo con CRLF en disco **no vino de un checkout**: lo escribió una
herramienta que ignoró la convención.

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


def test_las_excepciones_son_LAS_QUE_GITATTRIBUTES_DECLARA():
    """**La contraprueba que hace honesto al guard:** las excepciones no las elegí yo, las
    declara `.gitattributes`. Si alguien agrega una acá sin agregarla allá, el guard se
    estaría aflojando por su cuenta — y si la saca de allá, ésta queda huérfana."""
    attrs = (_REPO / ".gitattributes").read_text(encoding="utf-8")
    assert "*.bat text eol=crlf" in attrs
    assert "*.cmd text eol=crlf" in attrs
    assert "data/catalyst/*.json" in attrs
    assert "* text=auto eol=lf" in attrs, "cambió la convención global: revisar este guard"
    # y al revés: nada en el guard que `.gitattributes` no mencione
    for glob in _CRLF_PERMITIDO_GLOBS:
        assert glob in attrs, f"{glob} no está declarado en .gitattributes"
    for ext in _CRLF_PERMITIDO:
        assert f"*{ext} text eol=crlf" in attrs, f"{ext} no está declarado en .gitattributes"


def test_el_json_del_scheduler_esta_exceptuado_de_verdad(tmp_path, monkeypatch):
    """Contraprueba del glob: el builder del scheduler re-escribe ese JSON con CRLF en cada
    corrida, así que un guard que lo acusara sería rojo permanente — el defecto de la 107."""
    import scripts.check_repo_health as g

    d = tmp_path / "data" / "catalyst"
    d.mkdir(parents=True)
    f = d / "historical_reaction.json"
    f.write_bytes(b'{"a": 1}\r\n')
    monkeypatch.setattr(g, "ROOT", tmp_path)
    monkeypatch.setattr(g, "_tracked", lambda: frozenset({"data/catalyst/historical_reaction.json"}))
    assert g.check_crlf_en_working_tree([f]) == []
