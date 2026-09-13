"""Tarea 191 (BACKUP-ABIERTO-RW) — los scripts que sólo leen abren sólo para leer, y sin dejar rastro.

**Qué pasaba.** `run_exposure_cap_replay.py` abría por default el backup más nuevo de
`backups/` con `sqlite3.connect(db)` —lectura-escritura— para hacer sólo `SELECT`. Y no era el
único: en `scripts/` había **13** `connect` sin `mode=ro`, de los que **9** sólo leen.

**Lo que la medición cambió del alcance.** La tarea proponía `mode=ro`, y medido **no alcanza**:
sobre una base WAL, una conexión `mode=ro` **crea** `-shm` y `-wal` y **no los borra al cerrar**,
mientras que una read-write sí los limpia. O sea que `mode=ro` a secas cambiaba *«puede
escribir»* por *«deja residuo»* — y ese residuo es exactamente el rastro que la **188** encontró en
dos backups. Por eso el helper `database.readonly.readonly_uri` agrega `immutable=1` cuando la
base vive en `backups/`, y por eso **también** pasaron al helper los nueve scripts que **ya**
abrían con `mode=ro` (entre ellos `baseline_metrics`, cuya ayuda sugiere `--db backups/…`).

**Lo que este archivo fija:**

1. El comportamiento de SQLite del que depende la decisión, medido y no supuesto: `mode=ro`
   deja residuo; `immutable=1` no; y sobre una base viva `immutable=1` **lee un estado viejo** —
   que es por qué no puede ser incondicional.
2. El runner que motivó la tarea, de punta a punta sobre un backup WAL: no deja side files.
3. **Todo** `sqlite3.connect` de `scripts/` —descubierto por AST— pasa por `readonly_uri` o está
   clasificado como escritor con motivo.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from database.readonly import readonly_uri

_REPO = Path(__file__).resolve().parent.parent


def _wal_db(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (x INTEGER)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    return path


def _lados(path: Path) -> list[str]:
    return sorted(p.name for p in path.parent.iterdir() if p.name != path.name)


# ── 1. El helper y el comportamiento de SQLite del que depende ──────────────


def test_la_URI_es_inmutable_SOLO_en_un_backup(tmp_path):
    assert readonly_uri(tmp_path / "backups" / "b.db").endswith("?mode=ro&immutable=1")
    assert readonly_uri(tmp_path / "finanzias.db").endswith("?mode=ro")
    assert "\\" not in readonly_uri(tmp_path / "backups" / "b.db")  # as_posix: URI válida en Windows


def test_mode_ro_a_secas_DEJA_residuo_sobre_WAL(tmp_path):
    """La medición que cambió el alcance. Si SQLite dejara de hacerlo, este test lo dice y el
    `immutable` podría revisarse."""
    db = _wal_db(tmp_path / "x" / "b.db")
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    con.execute("SELECT count(*) FROM t").fetchone()
    con.close()
    assert _lados(db) == ["b.db-shm", "b.db-wal"]


def test_readonly_uri_sobre_un_backup_WAL_no_deja_NADA(tmp_path):
    db = _wal_db(tmp_path / "backups" / "b.db")
    con = sqlite3.connect(readonly_uri(db), uri=True)
    assert con.execute("SELECT count(*) FROM t").fetchone() == (1,)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("INSERT INTO t VALUES (2)")
    con.close()
    assert _lados(db) == []


def test_immutable_sobre_la_base_VIVA_leeria_un_estado_viejo(tmp_path):
    """Por qué el `immutable` no es incondicional: con un escritor vivo y el WAL sin
    checkpointear, la conexión `mode=ro` ve el último commit y la `immutable` no."""
    db = _wal_db(tmp_path / "vivo" / "finanzias.db")
    escritor = sqlite3.connect(db)
    escritor.execute("PRAGMA wal_autocheckpoint=0")
    escritor.execute("INSERT INTO t VALUES (2)")
    escritor.commit()
    try:
        ro = sqlite3.connect(readonly_uri(db), uri=True)
        inm = sqlite3.connect(f"file:{db.as_posix()}?mode=ro&immutable=1", uri=True)
        assert ro.execute("SELECT count(*) FROM t").fetchone() == (2,)
        assert inm.execute("SELECT count(*) FROM t").fetchone() == (1,)
        ro.close()
        inm.close()
    finally:
        escritor.close()


# ── 2. El runner de la tarea, de punta a punta ──────────────────────────────


def test_run_exposure_cap_replay_lee_un_backup_WAL_sin_dejar_rastro(tmp_path):
    from scripts.run_exposure_cap_replay import _load_orders

    db = tmp_path / "backups" / "finanzias_2026-01-01_00-00-00_daily.db"
    db.parent.mkdir()
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        "CREATE TABLE paper_accounts (id INTEGER, name TEXT, initial_capital REAL, cash REAL, "
        "is_active INTEGER, allocation_mode TEXT, strategy TEXT, created_at TEXT)"
    )
    con.execute("INSERT INTO paper_accounts VALUES (2, 'Sim', 50000, 50000, 1, 'equal_weight', 'x', '')")
    con.execute(
        "CREATE TABLE paper_orders (account_id INTEGER, ticker TEXT, side TEXT, fill_price REAL, "
        "fill_shares REAL, filled_at TEXT, status TEXT)"
    )
    con.execute("INSERT INTO paper_orders VALUES (2, 'AAA', 'BUY', 10, 5, '2026-01-02', 'filled')")
    con.commit()
    con.close()
    assert _lados(db) == []

    ordenes, capital, cuenta = _load_orders(str(db), None)

    assert (len(ordenes), capital, cuenta) == (1, 50000.0, 2)
    assert _lados(db) == [], "el runner dejó side files en el backup"


# ── 3. El barrido: todo connect de scripts/, clasificado ─────────────────────

# (archivo, función) → motivo. Sólo escritores: todo lo demás tiene que pasar por readonly_uri.
ESCRITORES: dict[tuple[str, str], str] = {
    ("scripts/archive_price_cache.py", "archivar"): (
        "ESCRIBE: archiva a Parquet y BORRA de `price_cache` las filas viejas, con commit (tareas 81 y 77)"
    ),
    ("scripts/archive_price_cache.py", "main"): (
        "ESCRIBE: `VACUUM` opt-in al final, que reescribe el archivo entero para que se achique"
    ),
    ("scripts/audit_price_contamination.py", "run"): (
        "ESCRIBE: con `--apply --yes` anula los round-trips contaminados, haciendo backup antes (E5)"
    ),
    ("scripts/purge_synthetic_cache.py", "main"): (
        "ESCRIBE: borra del cache las filas sintéticas (`DELETE … WHERE id=?` + commit)"
    ),
}


def _es_readonly(llamada: ast.Call) -> bool:
    if not llamada.args:
        return False
    primero = llamada.args[0]
    return (
        isinstance(primero, ast.Call)
        and isinstance(primero.func, ast.Name)
        and primero.func.id == "readonly_uri"
        and any(
            k.arg == "uri" and isinstance(k.value, ast.Constant) and k.value.value is True
            for k in llamada.keywords
        )
    )


def connects_sin_readonly(raiz: Path) -> set[tuple[str, str]]:
    """``(archivo, función)`` de cada ``sqlite3.connect`` que NO pasa por ``readonly_uri``."""
    encontrados: set[tuple[str, str]] = set()
    for path in sorted((raiz / "scripts").glob("*.py")):
        arbol = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(raiz).as_posix()

        def _visitar(nodo: ast.AST, funcion: str) -> None:
            for hijo in ast.iter_child_nodes(nodo):
                if isinstance(hijo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _visitar(hijo, hijo.name)
                    continue
                if (
                    isinstance(hijo, ast.Call)
                    and isinstance(hijo.func, ast.Attribute)
                    and hijo.func.attr == "connect"
                    and isinstance(hijo.func.value, ast.Name)
                    and hijo.func.value.id == "sqlite3"
                    and not _es_readonly(hijo)
                ):
                    encontrados.add((rel, funcion))  # noqa: B023 — se llama dentro de la vuelta
                _visitar(hijo, funcion)

        _visitar(arbol, "<modulo>")
    return encontrados


def test_todo_connect_de_scripts_es_readonly_o_ESCRITOR_clasificado():
    sin_clasificar = connects_sin_readonly(_REPO) - set(ESCRITORES)
    assert not sin_clasificar, (
        f"`sqlite3.connect` sin `readonly_uri` y sin clasificar como escritor: {sorted(sin_clasificar)}. "
        "Si sólo lee, `sqlite3.connect(readonly_uri(path), uri=True)`"
    )


def test_la_lista_de_escritores_no_tiene_FANTASMAS():
    fantasmas = set(ESCRITORES) - connects_sin_readonly(_REPO)
    assert not fantasmas, f"clasificados como escritores pero ya no abren read-write: {sorted(fantasmas)}"


@pytest.mark.parametrize("clave", sorted(ESCRITORES))
def test_cada_escritor_declara_que_escribe(clave):
    assert ESCRITORES[clave].startswith("ESCRIBE: ") and len(ESCRITORES[clave]) > 50


def test_el_INSTRUMENTO_distingue_las_formas(tmp_path):
    """Antes de creerle al barrido: `mode=ro` a secas NO cuenta como solo-lectura (deja
    residuo), un `connect` a nivel de módulo se ve, y `readonly_uri` sin `uri=True` tampoco
    cuenta — SQLite tomaría la URI como nombre de archivo."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "m.py").write_text(
        "\n".join(
            [
                "import sqlite3",
                "from database.readonly import readonly_uri",
                'A = sqlite3.connect("x.db")',
                "def ro_a_secas(p):",
                '    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)',
                "def bien(p):",
                "    return sqlite3.connect(readonly_uri(p), uri=True)",
                "def sin_uri(p):",
                "    return sqlite3.connect(readonly_uri(p))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert connects_sin_readonly(tmp_path) == {
        ("scripts/m.py", "<modulo>"),
        ("scripts/m.py", "ro_a_secas"),
        ("scripts/m.py", "sin_uri"),
    }
