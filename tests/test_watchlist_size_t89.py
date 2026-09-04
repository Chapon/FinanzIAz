"""Tarea 89 — el desvío de universo, bilateral y con la constante re-verificada.

`deviations()` declaraba el desvío con `cfg.n_tickers < LIVE_WATCHLIST_SIZE`
contra un `128` hardcodeado. Tres problemas en una línea:

* **el 128 no lo re-verificaba nada** contra la DB — envejecía solo;
* la comparación era **unilateral** (`<`), así que un universo de harness *más
  grande* que la watchlist viva no declaraba nada;
* es un **conteo parado en lugar de un conjunto**: un ticker cambiado por otro
  deja el número igual. Ese eje lo cubre `tickers_fp` (tarea 87); acá se cubren
  los dos primeros y **se declara** que el tercero no se puede cubrir desde una
  función pura, porque el conjunto vivo está en la DB.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from analysis.harness_config import (
    LIVE_ACCOUNT_ID,
    LIVE_MAX_POSITIONS,
    LIVE_WATCHLIST_SIZE,
    HarnessConfig,
    deviations,
)

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "finanzias.db"


def watchlist_viva(db: Path, account_id: int = LIVE_ACCOUNT_ID) -> int | None:
    """Cuántos tickers tiene la watchlist de ``account_id``, o ``None`` si **no hay
    con qué comparar**.

    **Por qué esto no es un ``db.exists()`` (tarea 107).** Lo era, y con eso el job
    `pytest` del CI quedó **rojo 12 corridas**, desde la #226: la suite se fabrica un
    ``finanzias.db`` por el camino —el subproceso de la 82, que corre sin el conftest
    (tarea 108)—, así que para cuando este test corría el archivo **existía**, el skip
    no disparaba, y ``mode=ro`` sobre un archivo **vacío de 4096 B conecta sin error**
    y recién muere en el ``SELECT``:

        sqlite3.OperationalError: no such table: paper_watchlist

    O sea: el guard preguntaba por el **archivo** cuando lo que necesita saber es si
    hay **datos**. Las tres formas de "no hay con qué comparar" —sin archivo, sin
    tabla, sin filas— devuelven ``None`` y se saltean; cualquier otra cosa es el
    conteo real y se compara.

    El **cero también se saltea**, y va declarado: una watchlist viva vacía no es
    drift de la constante, es una DB que no es la de la cuenta viva (o una recién
    creada). Que la watchlist real se vacíe es un problema mucho más grande, y no es
    éste el guard que lo mira.
    """
    if not db.exists():
        return None
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tabla = con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'paper_watchlist'"
        ).fetchone()
        if tabla is None:
            return None
        (n,) = con.execute(
            "SELECT COUNT(*) FROM paper_watchlist WHERE account_id = ?", (account_id,)
        ).fetchone()
    finally:
        con.close()
    return n or None


def _dev_universo(n_tickers: int) -> str | None:
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", n_tickers)
    return next((d for d in deviations(cfg) if "universo" in d), None)


def test_un_universo_mas_CHICO_declara_el_desvio():
    d = _dev_universo(LIVE_WATCHLIST_SIZE - 1)
    assert d is not None and "menos" in d


def test_un_universo_mas_GRANDE_tambien_lo_declara():
    """Era `<`, así que este caso pasaba **en silencio**. Un desvío es un desvío
    para los dos lados — mismo criterio que `stale_artifacts` (T30), que mira los
    dos porque un refresh parcial rompe la uniformidad tanto como uno faltante."""
    d = _dev_universo(LIVE_WATCHLIST_SIZE + 1)
    assert d is not None and "MÁS" in d


def test_el_mismo_tamano_no_declara_nada():
    assert _dev_universo(LIVE_WATCHLIST_SIZE) is None


def test_la_constante_sigue_siendo_la_de_la_cuenta_viva():
    """**Lo que impide que el 128 envejezca solo.** Se lee la watchlist de la
    cuenta viva de la DB, en modo lectura. Si no hay con qué comparar —CI, checkout
    limpio, una DB vacía dejada por otro test— se saltea: el test existe para cazar
    el drift acá, no para romper donde no hay contra qué medirlo.
    """
    n = watchlist_viva(_DB)
    if n is None:
        pytest.skip("sin watchlist viva en este entorno")
    assert n == LIVE_WATCHLIST_SIZE, (
        f"LIVE_WATCHLIST_SIZE dice {LIVE_WATCHLIST_SIZE} y la watchlist de la cuenta "
        f"{LIVE_ACCOUNT_ID} tiene {n}. Actualizar la constante (y revisar qué corridas "
        "se declararon con el número viejo)."
    )


# ── El guard del test, que hasta la 107 no lo miraba nadie ───────────────────
#
# El `if` que decide saltear o comparar **no tenía un solo test**, y por eso pudo
# quedar apuntando al archivo en vez de a los datos y dejar el CI rojo 12 corridas
# sin que la suite local se enterara (acá la DB real está, así que el camino roto
# ni se pisa). Estos cuatro cubren las cuatro respuestas posibles.


def _db_con(tmp_path: Path, filas: list[tuple[int, str]] | None) -> Path:
    """Una SQLite de juguete. ``filas is None`` = archivo sin la tabla."""
    db = tmp_path / "finanzias.db"
    con = sqlite3.connect(db)
    try:
        if filas is not None:
            con.execute("CREATE TABLE paper_watchlist (account_id INTEGER, ticker TEXT)")
            con.executemany("INSERT INTO paper_watchlist VALUES (?, ?)", filas)
            con.commit()
    finally:
        con.close()
    return db


def test_sin_archivo_no_hay_con_que_comparar(tmp_path):
    assert watchlist_viva(tmp_path / "no_esta.db") is None


def test_una_db_VACIA_no_es_una_db_con_datos(tmp_path):
    """**El caso exacto que tenía el CI rojo** (tarea 107). El archivo existe —lo dejó
    otro test— pero no tiene la tabla. El guard viejo preguntaba justo lo que este
    assert muestra que no alcanza: que el archivo esté."""
    db = _db_con(tmp_path, filas=None)
    assert db.exists(), "el guard viejo (db.exists()) habría dicho «hay con qué comparar»"
    assert watchlist_viva(db) is None


def test_una_watchlist_VACIA_tampoco(tmp_path):
    """Cero filas para la cuenta viva no es drift de la constante: es una DB que no
    es la de la cuenta viva. Se saltea, y está declarado en el docstring."""
    db = _db_con(tmp_path, filas=[(LIVE_ACCOUNT_ID + 99, "AAPL")])
    assert watchlist_viva(db) is None


def test_con_filas_devuelve_el_conteo_de_ESA_cuenta(tmp_path):
    """Y el control positivo, que es lo que impide que los tres de arriba pasen por
    devolver ``None`` siempre: con datos compara, y sólo cuenta la cuenta viva."""
    db = _db_con(
        tmp_path,
        filas=[(LIVE_ACCOUNT_ID, t) for t in ("AAPL", "MSFT", "NVDA")] + [(LIVE_ACCOUNT_ID + 99, "TSLA")],
    )
    assert watchlist_viva(db) == 3


def test_queda_declarado_lo_que_este_chequeo_NO_puede_ver():
    """Compara tamaños, no conjuntos, y eso tiene que estar escrito al lado del
    código — si no, el próximo lo lee como si comparara el conjunto (que es
    exactamente lo que pasó con `same_universe_as`)."""
    fuente = (_REPO / "analysis" / "harness_config.py").read_text(encoding="utf-8")
    assert "no conjuntos" in fuente
    assert "tickers_fp" in fuente
