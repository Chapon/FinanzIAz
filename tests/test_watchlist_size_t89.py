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
    cuenta viva de la DB, en modo lectura. Si no hay DB —CI, checkout limpio— se
    saltea: el test existe para cazar el drift acá, no para romper donde no hay
    con qué compararlo.
    """
    if not _DB.exists():
        pytest.skip("sin finanzias.db en este entorno")
    con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
    try:
        (n,) = con.execute(
            "SELECT COUNT(*) FROM paper_watchlist WHERE account_id = ?", (LIVE_ACCOUNT_ID,)
        ).fetchone()
    finally:
        con.close()
    assert n == LIVE_WATCHLIST_SIZE, (
        f"LIVE_WATCHLIST_SIZE dice {LIVE_WATCHLIST_SIZE} y la watchlist de la cuenta "
        f"{LIVE_ACCOUNT_ID} tiene {n}. Actualizar la constante (y revisar qué corridas "
        "se declararon con el número viejo)."
    )


def test_queda_declarado_lo_que_este_chequeo_NO_puede_ver():
    """Compara tamaños, no conjuntos, y eso tiene que estar escrito al lado del
    código — si no, el próximo lo lee como si comparara el conjunto (que es
    exactamente lo que pasó con `same_universe_as`)."""
    fuente = (_REPO / "analysis" / "harness_config.py").read_text(encoding="utf-8")
    assert "no conjuntos" in fuente
    assert "tickers_fp" in fuente
