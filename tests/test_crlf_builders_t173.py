"""Tarea 173 — los dos JSON del scheduler son VERSIONADOS, y sus builders los escribían en CRLF.

**El defecto, y por qué sobrevivió a las dos tareas que pasaron por encima.**

`scripts/build_surprise_profiles.py` y `scripts/build_historical_reaction.py` escriben
`data/catalyst/surprise_profiles.json` y `data/catalyst/historical_reaction.json` con
`Path.write_text()` sin `newline`. En Windows eso traduce cada salto a **CRLF**, y los dos
archivos están **versionados** con un blob en LF: medidos el 2026-09-11, 1283 y 5650 líneas,
**100% CRLF en disco**, contra un `git status` limpio.

Lo taparon dos premisas falsas encadenadas, una por tarea:

1. **La 165** arregló tres regeneradores (`refresh_live_universe`, `refresh_sp500_fallback`,
   `lock_requirements`) y excluyó al resto con este motivo escrito: *«los demás `write_text`
   sin `newline` escriben JSON o artefactos **no versionados**»*. Para estos dos es falso:
   `git ls-files data/catalyst/` los lista.
2. **La 172** le agregó al guard una excepción por glob para `data/catalyst/*.json`, con el
   argumento de que *«`.gitattributes` lo acepta explícitamente»*. También falso: esa línea
   declara `eol=lf` —LF en el working tree, igual que la regla global—, no `eol=crlf`.

**Y el cross-check que tenía que cazar eso matcheaba la ruta, no el valor.** La 172 escribió
`test_las_excepciones_son_LAS_QUE_GITATTRIBUTES_DECLARA` justamente para que el guard no se
aflojara solo, pero para los globs preguntaba `glob in attrs`: una línea que declara lo
**contrario** contiene igual el patrón, así que pasaba en verde. Es la forma de
[[guard-no-puede-usar-de-verdad-lo-que-chequea]] —la referencia no discrimina el defecto—
aplicada a un substring. Ese test ahora compara el `eol=` declarado (ver `t172`).

**El arreglo es el de la 165, no una excepción:** `newline="\\n"` en los dos writers. Con el
que escribe diciendo qué saltos quiere, la excepción por glob sobra y `_CRLF_PERMITIDO_GLOBS`
queda **vacío** — el guard vuelve a ser un predicado sobre todo lo versionado.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CATALYST_JSON = ("data/catalyst/surprise_profiles.json", "data/catalyst/historical_reaction.json")


# ── La premisa que la 165 dio por buena ──────────────────────────────────────


@pytest.mark.parametrize("rel", _CATALYST_JSON)
def test_los_json_del_scheduler_SI_estan_versionados(rel):
    """La 165 los excluyó llamándolos *«artefactos no versionados»*. Este test fija el hecho
    que la refuta, para que la exclusión no se pueda re-argumentar igual."""
    out = subprocess.run(
        ["git", "ls-files", "--error-unmatch", rel], cwd=_REPO, capture_output=True, text=True
    )
    assert out.returncode == 0, f"{rel} no está versionado: la premisa de la 165 volvió a ser cierta"


@pytest.mark.parametrize("rel", _CATALYST_JSON)
def test_los_json_del_scheduler_estan_en_LF_en_disco(rel):
    """El invariante, sobre el repo de verdad. Se pone rojo la próxima vez que un builder
    escriba sin `newline` — que es como estaban los dos hasta esta tarea."""
    data = (_REPO / rel).read_bytes()
    crlf = data.count(b"\r\n")
    assert crlf == 0, f"{rel} tiene {crlf} CRLF en el working tree contra un blob LF"


# ── El comportamiento de los dos writers ─────────────────────────────────────


def test_build_surprise_profiles_escribe_LF(tmp_path, monkeypatch):
    """**Probado por mutación:** sacándole el `newline` a `run_build`, esto se pone rojo en
    Windows (en Linux `write_text` ya escribe LF, así que ahí el guard que muerde es el de
    working tree del t172 corriendo en la máquina de Chapa)."""
    import scripts.build_surprise_profiles as b

    monkeypatch.setattr(b, "resolve_universe", lambda _acct: ["AAA", "BBB"])
    monkeypatch.setattr(b, "build_profiles", lambda _t, limit=16: {"AAA": {"ticker": "AAA", "n_quarters": 8}})
    out = tmp_path / "surprise_profiles.json"
    b.run_build(account_id=None, out=out)

    data = out.read_bytes()
    assert data.count(b"\r\n") == 0, "el builder escribió CRLF"
    assert data.count(b"\n") > 1, "montaje inútil: el JSON salió en una sola línea"
    assert json.loads(data.decode("utf-8"))["profiles"]["AAA"]["ticker"] == "AAA"


def test_build_historical_reaction_escribe_LF(tmp_path, monkeypatch):
    """Igual que el de arriba para el segundo writer. Los dos se mutan por separado: el
    arreglo de uno no prueba nada del otro, que es exactamente cómo la 165 dejó pasar a
    estos dos arreglando otros tres."""
    import scripts.build_historical_reaction as b

    monkeypatch.setattr(b, "_load_classified_events", lambda: [])
    monkeypatch.setattr(b, "_price_loader", lambda period="2y": lambda _t: None)
    monkeypatch.setattr(
        b, "build_historical_reaction", lambda *a, **k: {"by_event": {}, "by_ticker_event": {}}
    )
    out = tmp_path / "historical_reaction.json"
    assert b.main(["--out", str(out)]) == 0

    data = out.read_bytes()
    assert data.count(b"\r\n") == 0, "el builder escribió CRLF"
    assert data.count(b"\n") > 1, "montaje inútil: el JSON salió en una sola línea"


# ── El guard: la excepción que se fue, y la premisa que la sostenía ──────────


def test_el_guard_YA_NO_exceptua_los_json_del_scheduler(tmp_path, monkeypatch):
    """**Es el test de la 172 dado vuelta, a propósito.** Ahí se llamaba
    `test_el_json_del_scheduler_esta_exceptuado_de_verdad` y afirmaba lo contrario, con el
    argumento de que acusarlos sería rojo permanente. Deja de serlo en cuanto el writer
    escribe LF, que es la causa y no el síntoma."""
    import scripts.check_repo_health as g

    d = tmp_path / "data" / "catalyst"
    d.mkdir(parents=True)
    f = d / "historical_reaction.json"
    f.write_bytes(b'{"a": 1}\r\n')
    monkeypatch.setattr(g, "ROOT", tmp_path)
    monkeypatch.setattr(g, "_tracked", lambda: frozenset({"data/catalyst/historical_reaction.json"}))

    (problema,) = g.check_crlf_en_working_tree([f])
    assert "historical_reaction.json" in problema


def test_gitattributes_NO_declara_crlf_para_los_json_del_scheduler():
    """El hecho concreto sobre el que se apoyaba la excepción, fijado en el sentido correcto.
    Si alguien algún día decide de verdad que esos JSON van en CRLF, tiene que cambiar
    `.gitattributes` **y** este test — que es el punto: la decisión deja de poder tomarse
    por descuido desde el comentario de un guard."""
    from tests.test_repo_health_crlf_t172 import declared_eol

    assert declared_eol("data/catalyst/*.json") == "lf"


def test_no_queda_ninguna_excepcion_por_glob():
    """`_CRLF_PERMITIDO_GLOBS` queda **vacío**, y eso se declara en vez de borrarse: el
    mecanismo sigue ahí para cuando haga falta de verdad, pero hoy nada lo usa. Mismo criterio
    con el que la 154 dejó vacía la excepción del guard de la 137."""
    from scripts.check_repo_health import _CRLF_PERMITIDO_GLOBS

    assert _CRLF_PERMITIDO_GLOBS == {}, (
        "volvió a aparecer una excepción por glob: verificá que `.gitattributes` declare "
        "`eol=crlf` para ese patrón, y no `eol=lf` (que fue el error de la 172)"
    )
