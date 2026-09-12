"""Tarea 190 (CROSSPERIOD-TICKER-CON-GUION) — el guard de huecos no veía a BRK-B.

``cross_period_gaps`` cruza cada frame de un ticker contra sus hermanos de otro período, y
para no leer el disco por ticker arma **un** índice del directorio: cuántos frames ``1d``
tiene cada uno. El índice salía del **nombre del archivo** (``archivo.name.split("__")[0]``) y
se consultaba con el **ticker** (``ticker.upper()``). ``parquet_cache`` escribe el nombre
pasando el ticker por ``_safe``, que reemplaza todo lo no alfanumérico por ``_``: el archivo de
``BRK-B`` es ``BRK_B__10y__1d.parquet``. Índice ``BRK_B``, consulta ``BRK-B``, **0 frames**, y
el ticker se salteaba como si no tuviera con qué cruzarse.

**Medido el 2026-09-12 sobre el cohorte real, con contraprueba:** borrando una rueda interior
del ``10y``, AAPL pasaba de 7 a 8 huecos reportados y **BRK-B daba 0 y 0** — ni el interior ni
la cola, que son los dos defectos que la función existe para ver (tareas 110 y 139). Con el
arreglo BRK-B reporta **2** ruedas de cola y **0** interiores: no escondía un hueco, el guard
estaba ciego.

**Por qué ningún test lo vio:** el fixture de la 139 arma los nombres de archivo **con el ticker
crudo** (``f"{ticker}__2y__1d.parquet"``), o sea que escribía los nombres del modo en que el
código defectuoso los buscaba. Es [[guard-no-puede-usar-de-verdad-lo-que-chequea]]: la
referencia del test salía de la misma suposición que chequeaba. Acá los frames los escribe
``parquet_cache.write``, el escritor **real**.

**El barrido que pedía el kill-criteria** clasifica toda ocurrencia de ``.split("__")`` en el
código del repo (fuera de ``tests/``), descubierta por AST. Casi todas son **inocuas por
idempotencia**: el token sanitizado vuelve a entrar a ``parquet_cache``, y ``_safe("BRK_B")`` es
``BRK_B``, así que el archivo se encuentra igual. El defecto necesita las dos mitades —índice por
archivo **y** consulta por ticker crudo— y sólo ``cross_period_gaps`` las tenía.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pandas as pd
import pytest

import analysis.harness_config as hc
from analysis.harness_config import cross_period_gaps
from data import parquet_cache

_REPO = Path(__file__).resolve().parent.parent


def _frame(fechas: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"Close": [10.0] * len(fechas)}, index=pd.to_datetime(fechas))


@pytest.fixture
def disco(tmp_path, monkeypatch):
    """Frames escritos por el escritor REAL en un directorio temporal."""
    monkeypatch.setattr(hc, "ARTIFACT_REFRESH_EXCEPTIONS", {}, raising=False)
    parquet_cache.set_parquet_dir(tmp_path)

    def _escribir(ticker: str, hermano: list[str]) -> None:
        parquet_cache.write(ticker, "2y", "1d", _frame(hermano))
        parquet_cache.write(ticker, "10y", "1d", _frame(hermano))

    yield _escribir
    parquet_cache.set_parquet_dir(None)


_HERMANO = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]


# ── El defecto ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("ticker", ["AAPL", "BRK-B", "BF-B"])
def test_un_hueco_INTERIOR_se_reporta_tambien_con_guion(disco, ticker):
    """**El corazón de la tarea.** Sobre el código de antes, AAPL daba el hueco y los dos con
    guión daban ``()``. ``BF-B`` va porque es el otro que ya rompió un barrido (línea 900 del
    backlog), aunque hoy no esté en el universo."""
    disco(ticker, _HERMANO)
    propias = [(f, 10.0) for f in _HERMANO if f != "2026-09-02"]

    fechas = {(g.ticker, g.date, g.cola) for g in cross_period_gaps({ticker: propias})}
    assert (ticker, "2026-09-02", False) in fechas


@pytest.mark.parametrize("ticker", ["AAPL", "BRK-B"])
def test_la_COLA_se_reporta_tambien_con_guion(disco, ticker):
    """La otra mitad de lo que la función existe para ver (tarea 139): el frame atrasado."""
    disco(ticker, _HERMANO)
    propias = [(f, 10.0) for f in _HERMANO[:-1]]

    assert [(g.date, g.cola) for g in cross_period_gaps({ticker: propias})] == [("2026-09-04", True)]


def test_sin_hueco_no_acusa_nada_con_guion(disco):
    """La contraprueba: ver al ticker no puede convertirse en acusarlo de más."""
    disco("BRK-B", _HERMANO)
    assert cross_period_gaps({"BRK-B": [(f, 10.0) for f in _HERMANO]}) == ()


def test_file_key_es_el_token_que_ESCRIBE_el_cache(tmp_path):
    """El arreglo consulta con ``file_key``; esto ata ``file_key`` al nombre que produce
    ``path_for``, que es el que usa ``write``. Si divergen, el índice vuelve a quedar ciego."""
    for ticker in ["AAPL", "BRK-B", "brk-b", "BRK_B", "^GSPC"]:
        nombre = parquet_cache.path_for(ticker, "10y", "1d").name
        assert nombre.split("__")[0] == parquet_cache.file_key(ticker)
    assert parquet_cache.file_key("BRK_B") == parquet_cache.file_key("BRK-B")  # idempotente
    # Y el valor concreto, porque el loop de arriba es circular (`path_for` usa `file_key`): lo
    # que tiene que coincidir es el nombre que YA está en disco, `BRK_B__10y__1d.parquet`.
    assert parquet_cache.file_key("BRK-B") == "BRK_B"


# ── El caso real ─────────────────────────────────────────────────────────────


def test_BRK_B_real_se_cruza_contra_sus_hermanos():
    """La medición del enunciado, sobre los frames de verdad: borrar una rueda interior del
    ``10y`` de BRK-B tiene que sumar un hueco. Antes daba 0 y 0."""
    if len(parquet_cache.labelled_1d("BRK-B")) < 2:
        pytest.skip("sin dos frames 1d de BRK-B en este entorno")
    bars = hc.cohort_bars(["BRK-B"], hc.ARTIFACT_PERIOD)["BRK-B"]
    base = cross_period_gaps({"BRK-B": list(bars)})
    borrada = bars[len(bars) // 2][0]
    mutado = [b for b in bars if b[0] != borrada]

    gaps = cross_period_gaps({"BRK-B": mutado})
    assert len(gaps) == len(base) + 1
    assert any(g.date == borrada and not g.cola for g in gaps)


# ── El barrido: toda derivación desde el nombre del archivo, clasificada ─────

# (archivo, función que la contiene) → motivo. El prefijo dice de qué tipo es.
SPLITS_CLASIFICADOS: dict[tuple[str, str], str] = {
    ("analysis/harness_config.py", "cross_period_gaps"): (
        "ARREGLADO: el índice queda en tokens de archivo y AHORA se consulta con "
        "`parquet_cache.file_key`, la misma función que escribe (tarea 190)"
    ),
    ("data/parquet_cache.py", "labelled_1d"): (
        "NO_ES_TICKER: extrae el PERÍODO (`parts[1]`) para rotular el frame en un log; el "
        "ticker ya lo conoce el que llama"
    ),
    ("scripts/measure_garch_fragil_t67.py", "_tickers"): (
        "IDEMPOTENTE: el token vuelve a entrar a `parquet_cache` (`read` y `cohort_bars`), que "
        "lo re-sanitiza igual (`BRK_B` → `BRK_B`) y encuentra el archivo; y `cross_period_gaps` "
        "lo consulta con `file_key`, también idempotente. Sólo el rótulo del reporte sale con `_`"
    ),
    ("scripts/measure_garch_intraday_t29.py", "_frames"): (
        "IDEMPOTENTE: `parquet_cache.read(token, …)` re-sanitiza el token y lee el mismo "
        "archivo. Sólo el rótulo del reporte sale con `_`"
    ),
    ("scripts/measure_scale_drift_t64.py", "_pairs"): (
        "IDEMPOTENTE: `labelled_1d(token)` re-sanitiza y devuelve los mismos frames; cruza "
        "archivos contra archivos, sin consultar por ticker crudo"
    ),
    ("scripts/measure_scale_drift_t64.py", "measure"): (
        "IDEMPOTENTE: sólo CUENTA tokens distintos, y el conteo es el mismo con `_` o con `-`"
    ),
    ("scripts/refresh_live_universe.py", "pit_tickers"): (
        "PIT_SIN_SANITIZAR: los JSON PIT se nombran con el ticker CRUDO "
        "(`BRK-B__10y__w250.json`), así que el prefijo es el ticker y se compara bien contra "
        "la watchlist. Lo fija `test_los_PIT_se_nombran_con_el_ticker_crudo`"
    ),
}

_PREFIJOS = ("ARREGLADO:", "NO_ES_TICKER:", "IDEMPOTENTE:", "PIT_SIN_SANITIZAR:")


def _splits_por_doble_guion_bajo() -> set[tuple[str, str]]:
    """Toda llamada ``.split("__")`` (y sus primas) fuera de ``tests/``, con la función que la
    contiene —o ``<modulo>`` si está a nivel de módulo, que en un script es lo común—.
    La población se descubre por AST: un script nuevo nace adentro del barrido."""
    encontrados: set[tuple[str, str]] = set()
    raices = [
        d for d in _REPO.iterdir() if d.is_dir() and not d.name.startswith((".", "_")) and d.name != "tests"
    ]
    archivos = [p for d in raices for p in d.rglob("*.py")] + list(_REPO.glob("*.py"))
    for path in archivos:
        try:
            arbol = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        rel = path.relative_to(_REPO).as_posix()

        def _visitar(nodo: ast.AST, funcion: str) -> None:
            for hijo in ast.iter_child_nodes(nodo):
                if isinstance(hijo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _visitar(hijo, hijo.name)
                    continue
                if (
                    isinstance(hijo, ast.Call)
                    and isinstance(hijo.func, ast.Attribute)
                    and hijo.func.attr in ("split", "rsplit", "partition", "rpartition")
                    and hijo.args
                    and isinstance(hijo.args[0], ast.Constant)
                    and hijo.args[0].value == "__"
                ):
                    encontrados.add((rel, funcion))  # noqa: B023 — se llama dentro de la vuelta
                _visitar(hijo, funcion)

        _visitar(arbol, "<modulo>")
    return encontrados


def test_el_INSTRUMENTO_ve_las_tres_ubicaciones(tmp_path, monkeypatch):
    """Antes de creerle al barrido: a nivel de módulo, en una función y en una anidada. La
    primera versión caminaba sólo funciones y un script con el split suelto le era invisible."""
    (tmp_path / "pkg").mkdir()
    fuente = (
        'X = "a__b".split("__")[0]\n'
        "def f(p):\n"
        '    return p.name.partition("__")[0]\n'
        "def g():\n"
        "    def h(p):\n"
        '        return p.rsplit("__", 1)\n'
        "    return h\n"
    )
    (tmp_path / "pkg" / "m.py").write_text(fuente, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text('Y = "a__b".split("__")\n', encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "_REPO", tmp_path)

    assert _splits_por_doble_guion_bajo() == {("pkg/m.py", "<modulo>"), ("pkg/m.py", "f"), ("pkg/m.py", "h")}


def test_toda_derivacion_desde_el_nombre_esta_CLASIFICADA():
    encontrados = _splits_por_doble_guion_bajo()
    assert encontrados, "el barrido no encontró nada: se rompió el instrumento, no el repo"
    sin_clasificar = encontrados - set(SPLITS_CLASIFICADOS)
    assert not sin_clasificar, (
        f"derivaciones de ticker desde el nombre de archivo sin clasificar: {sorted(sin_clasificar)}. "
        "Si indexa por archivo y consulta por ticker, usá `parquet_cache.file_key`"
    )


def test_la_clasificacion_no_tiene_entradas_FANTASMA():
    fantasmas = set(SPLITS_CLASIFICADOS) - _splits_por_doble_guion_bajo()
    assert not fantasmas, f"clasificadas pero ya no existen: {sorted(fantasmas)}"


@pytest.mark.parametrize("clave", sorted(SPLITS_CLASIFICADOS))
def test_cada_clasificacion_declara_TIPO_y_motivo(clave):
    motivo = SPLITS_CLASIFICADOS[clave]
    assert motivo.startswith(_PREFIJOS), f"{clave}: el motivo no declara su tipo"
    assert len(motivo) > 60, f"{clave}: el motivo es demasiado corto para ser uno"


def test_los_PIT_se_nombran_con_el_ticker_crudo():
    """El supuesto del que depende ``pit_tickers``, fijado sobre el **productor** y no sobre el
    disco: ``precompute_pit_signals._out_path`` sólo reemplaza barras, así que el guión queda. Si
    empezara a sanitizar como ``parquet_cache``, BRK-B se caería del universo con un AVISO."""
    from scripts.precompute_pit_signals import _out_path
    from scripts.refresh_live_universe import pit_tickers

    assert _out_path("BRK-B", "10y", 250).name.split("__")[0] == "BRK-B"
    # Y de punta a punta: lo que escribe el productor lo lee `pit_tickers` como el ticker crudo.
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / _out_path("BRK-B", "10y", 250).name).write_text("{}", encoding="utf-8")
        assert pit_tickers(Path(d)) == {"BRK-B"}
