"""Tarea 218 — VS SPY, MAE/MFE y el fwd-5d dejan de leer una tabla vacía.

**Lo medido el 2026-09-21, corriendo la función real contra la DB viva:**
``_benchmark_panel(con, 2)`` devolvía ``available=False``, ``spy_return=None``,
``vs_spy=None``. El ``account_return`` sí salía — o sea que la mitad de la tarjeta
funcionaba y la otra mitad, justo la que compara, no.

**La causa, dos pasos, cada uno correcto por separado:**

1. **2026-07-12** — ARQ1 activó el backend **Parquet** y ``yahoo_finance`` dejó de
   escribir ``historical_data_cache``; la última fila quedó del **2026-07-11**.
2. **2026-09-02** — la migración **0011** la **vació** a propósito (288 filas /
   22,7 MB, el 24% del archivo de DB), porque el rollback de ARQ1 había caducado.

Lo que nadie hizo fue migrar a los consumidores. Y eran **dos copias** del mismo
lector —``analysis/metrics_panel.load_close_series`` y
``scripts/dashboard_data._load_close_series``—, que es exactamente lo que permite
que un arreglo no alcance al otro: la misma lección de la 207 y la 212. Ahora el
lector es **uno solo** (``data/historical_series.py``) y los dos lo llaman.

**Qué se apagó, y no es cosmético:** VS SPY es la métrica **V1**, la que existe para
separar sistema de mercado. Sin ella el único número visible es la equity cruda, y
+3,12% a ojo se lee como *«casi cero de ganancia»* cuando en realidad es casi
empatarle al mercado. Así llegó el pedido que destapó esto.

**Y la tarea 22 no cubría este caso, a propósito de su propio diseño:** su
``benchmark_stale_bdays`` detecta la serie **vieja** (fase 1, tabla congelada en
julio). Con la tabla **vacía** no hay serie que comparar, así que el panel no queda
*stale* sino ``available=False`` — que la UI rotulaba *«sin cache de SPY todavía»*.
Ese *«todavía»* afirmaba que el dato venía en camino. No venía.
"""

from __future__ import annotations

import json
import sqlite3

import pandas as pd
import pytest

import analysis.metrics_panel as mp
import scripts.dashboard_data as dd
from data import historical_series as hs
from data import parquet_cache

# ── helpers ──────────────────────────────────────────────────────────────────

_DIAS = ["2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"]


def _con_con_tabla(filas_json: dict[str, str] | None = None) -> sqlite3.Connection:
    """Una DB en memoria con ``historical_data_cache`` (vacía salvo que se pida)."""
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE historical_data_cache (id INTEGER PRIMARY KEY, ticker TEXT, "
        "period TEXT, interval TEXT, data_json TEXT, fetched_at TEXT)"
    )
    for ticker, blob in (filas_json or {}).items():
        con.execute(
            "INSERT INTO historical_data_cache (ticker, period, interval, data_json, fetched_at) "
            "VALUES (?,'1y','1d',?,'2026-07-11')",
            (ticker, blob),
        )
    return con


def _json_split(columns: list, data: list, index: list[str]) -> str:
    return json.dumps({"columns": columns, "index": index, "data": data})


@pytest.fixture
def parquet_tmp(tmp_path, monkeypatch):
    """Apunta el cache Parquet a un tmp y fuerza el backend ``parquet``."""
    parquet_cache.set_parquet_dir(tmp_path / "parquet")
    monkeypatch.setattr(hs, "backend_activo", lambda: "parquet")
    yield tmp_path
    parquet_cache.set_parquet_dir(None)


def _escribir_parquet(ticker: str, closes: list[float]) -> None:
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": [c * 1.02 for c in closes],
            "Low": [c * 0.98 for c in closes],
            "Close": closes,
            "Volume": [1000] * len(closes),
        },
        index=pd.to_datetime(_DIAS[: len(closes)]),
    )
    parquet_cache.write(ticker, "1y", "1d", df)


# ── El kill-criteria, en sus DOS direcciones ─────────────────────────────────


def test_con_parquet_la_serie_VUELVE(parquet_tmp):
    """La dirección que faltaba: con ARQ1 activo tiene que haber serie."""
    _escribir_parquet("SPY", [100.0, 101.0, 102.0, 103.0, 104.0])
    con = _con_con_tabla()  # la tabla vieja EXISTE y está VACÍA, como en producción

    serie = hs.close_series(con, "SPY")
    assert serie is not None, "con Parquet activo tiene que haber serie"
    assert len(serie) == 5
    assert serie[0] == ("2026-06-22", 100.0)
    assert serie[-1] == ("2026-06-26", 104.0)


def test_sin_serie_en_NINGUN_backend_devuelve_None(parquet_tmp):
    """La otra dirección: si de verdad no hay dato, no se inventa uno."""
    con = _con_con_tabla()
    assert hs.close_series(con, "NOEXISTE") is None
    assert hs.ohlc_series(con, "NOEXISTE") is None


def test_el_backend_sqlite_sigue_leyendo_la_conexion_del_llamador(monkeypatch):
    """No es una migración a Parquet: es un **despacho**. El camino viejo sigue.

    Importa porque la suite corre con el default ``sqlite`` (el autouse
    ``_disable_settings_persistence`` redirige los settings a un tmp), así que éste
    es el camino que ejercitan los tests que arman un cache sintético.
    """
    monkeypatch.setattr(hs, "backend_activo", lambda: "sqlite")
    blob = _json_split(["Open", "High", "Low", "Close"], [[1, 2, 0.5, 1.5], [1, 3, 1.0, 2.5]], _DIAS[:2])
    con = _con_con_tabla({"AAA": blob})

    serie = hs.close_series(con, "AAA")
    assert serie == [("2026-06-22", 1.5), ("2026-06-23", 2.5)]


# ── La regla que hereda de la migración 0011 ─────────────────────────────────


def test_con_backend_parquet_NO_se_cae_a_la_tabla_vieja(parquet_tmp):
    """**La propiedad que la 0011 argumentó y que acá se hereda.**

    Con ARQ1 activo, una fila en la tabla vieja es de julio 2026. Devolverla como si
    fuera actual es peor que no devolver nada — *«fail-open ruidoso»*, dijo la
    migración. Así que con backend ``parquet`` y sin parquet del ticker: ``None``,
    aunque la tabla tenga la fila.
    """
    blob = _json_split(["Close"], [[999.0]], ["2026-07-11"])
    con = _con_con_tabla({"SPY": blob})  # fila VIEJA en la tabla vieja

    assert hs.close_series(con, "SPY") is None, "no puede leer la fila de julio"


def test_el_backend_dual_SI_cae_a_la_tabla_vieja(monkeypatch):
    """La contraparte: ``dual`` existe para convivir, así que ahí el fallback vale."""
    monkeypatch.setattr(hs, "backend_activo", lambda: "dual")
    parquet_cache.set_parquet_dir("/noexiste_a_proposito_t218")
    try:
        blob = _json_split(["Close"], [[42.0]], ["2026-06-22"])
        con = _con_con_tabla({"AAA": blob})
        assert hs.close_series(con, "AAA") == [("2026-06-22", 42.0)]
    finally:
        parquet_cache.set_parquet_dir(None)


# ── Lo que NO se puede regresar al unificar las dos copias ───────────────────


def test_ohlc_devuelve_None_si_la_fuente_no_trae_High_Low(monkeypatch):
    """**Reemplazar el rango por el close subestimaría MAE/MFE en silencio.**

    Es el rango intradía que un stop o un target realmente ve. Si no está, la
    respuesta honesta es que no está — contrato que ya tenía ``load_ohlc_series``.
    """
    monkeypatch.setattr(hs, "backend_activo", lambda: "sqlite")
    con = _con_con_tabla({"AAA": _json_split(["Close"], [[10.0]], ["2026-06-22"])})

    assert hs.close_series(con, "AAA") == [("2026-06-22", 10.0)], "el close sí está"
    assert hs.ohlc_series(con, "AAA") is None, "pero el rango no se inventa"


def test_tolera_columnas_MultiIndex_serializadas(monkeypatch):
    """``["Close","MSFT"]`` es como se serializa un frame MultiIndex. Lo toleraba
    ``load_ohlc_series`` y perderlo al unificar sería una regresión silenciosa."""
    monkeypatch.setattr(hs, "backend_activo", lambda: "sqlite")
    cols = [["Open", "MSFT"], ["High", "MSFT"], ["Low", "MSFT"], ["Close", "MSFT"]]
    con = _con_con_tabla({"MSFT": _json_split(cols, [[1, 3, 0.5, 2.0]], ["2026-06-22"])})

    assert hs.close_series(con, "MSFT") == [("2026-06-22", 2.0)]
    assert hs.ohlc_series(con, "MSFT") == [("2026-06-22", 3.0, 0.5)]


def test_un_close_no_positivo_se_filtra(monkeypatch):
    """La copia de ``dashboard_data`` filtraba ``close > 0`` y la de ``metrics_panel``
    no. Al unificar se queda **el que protege**: un cero no es un precio."""
    monkeypatch.setattr(hs, "backend_activo", lambda: "sqlite")
    blob = _json_split(["Close"], [[10.0], [0.0], [-5.0], [12.0]], _DIAS[:4])
    con = _con_con_tabla({"AAA": blob})

    assert hs.close_series(con, "AAA") == [("2026-06-22", 10.0), ("2026-06-25", 12.0)]


# ── El panel, que es el consumidor que se veía roto ──────────────────────────


def _con_cuenta(con: sqlite3.Connection) -> sqlite3.Connection:
    con.execute(
        "CREATE TABLE paper_equity_snapshots (id INTEGER PRIMARY KEY, account_id INT, "
        "snapshot_at TEXT, cash REAL, positions_value REAL, total_equity REAL, portfolio_sigma REAL)"
    )
    for dia, eq in zip(_DIAS, [50000.0, 50500.0, 51000.0, 51500.0, 52000.0], strict=True):
        con.execute(
            "INSERT INTO paper_equity_snapshots (account_id, snapshot_at, cash, positions_value, "
            "total_equity, portfolio_sigma) VALUES (2, ?, 0, 0, ?, 0)",
            (f"{dia} 20:00:00", eq),
        )
    return con


def test_el_panel_VUELVE_a_dar_vs_spy_con_parquet(parquet_tmp, monkeypatch):
    """El kill-criteria de la tarea, en la dirección buena."""
    monkeypatch.setattr(mp.historical_series, "backend_activo", lambda: "parquet")
    _escribir_parquet("SPY", [100.0, 101.0, 102.0, 103.0, 104.0])
    con = _con_cuenta(_con_con_tabla())

    bm = mp._benchmark_panel(con, 2)
    assert bm["available"] is True
    assert bm["motivo"] is None
    assert bm["spy_return"] == pytest.approx(0.04, abs=1e-9)  # 100 -> 104
    assert bm["account_return"] == pytest.approx(0.04, abs=1e-9)  # 50000 -> 52000
    assert bm["vs_spy"] == pytest.approx(0.0, abs=1e-9)


def test_sin_serie_el_panel_DICE_por_que_no_hay_numero(parquet_tmp, monkeypatch):
    """La otra dirección, y el punto (2) del alcance: *no hay dato* tiene que
    distinguirse de *dato viejo*, porque la UI los rotulaba igual."""
    monkeypatch.setattr(mp.historical_series, "backend_activo", lambda: "parquet")
    con = _con_cuenta(_con_con_tabla())  # sin parquet de SPY

    bm = mp._benchmark_panel(con, 2)
    assert bm["available"] is False
    assert bm["vs_spy"] is None
    assert bm["motivo"] == "sin_serie", "y no se confunde con `stale` ni con falta de snapshots"
    assert bm["stale"] is False


def test_sin_snapshots_el_motivo_es_OTRO(parquet_tmp):
    """Tres causas distintas de *no hay número*, tres motivos distintos."""
    con = _con_con_tabla()
    con.execute(
        "CREATE TABLE paper_equity_snapshots (id INTEGER PRIMARY KEY, account_id INT, "
        "snapshot_at TEXT, cash REAL, positions_value REAL, total_equity REAL, portfolio_sigma REAL)"
    )
    bm = mp._benchmark_panel(con, 2)
    assert bm["available"] is False and bm["motivo"] == "sin_snapshots"


# ── Que no vuelva a haber dos copias ─────────────────────────────────────────


def _literales_ejecutables(ruta) -> list[str]:
    """Los strings del módulo que **NO** son docstrings, vía AST.

    Escrito así por una razón concreta: la primera versión de este guard hacía
    ``assert "FROM historical_data_cache" not in codigo`` y salió **roja** — porque
    los docstrings del arreglo **citan** el SELECT viejo para explicar por qué era el
    defecto. Es la lección de las tareas **128**, **135** y **216**: para un guard de
    texto, la prosa que cita un defecto es indistinguible del defecto. Lo que sí se
    puede atar mecánicamente es si la cadena vive en un literal que el módulo
    **ejecuta**, y eso lo contesta el AST, no un ``in``.
    """
    import ast

    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    docstrings = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            cuerpo = getattr(nodo, "body", None)
            if (
                cuerpo
                and isinstance(cuerpo[0], ast.Expr)
                and isinstance(cuerpo[0].value, ast.Constant)
                and isinstance(cuerpo[0].value.value, str)
            ):
                docstrings.add(id(cuerpo[0].value))
    return [
        n.value
        for n in ast.walk(arbol)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    ]


def test_ningun_consumidor_hace_el_SELECT_a_mano():
    """**El ancla de la mutación.** Volver a leer la tabla directo desde cualquiera
    de los dos consumidores reintroduce el defecto — y lo reintroduce *en uno solo*,
    que es como sobrevivió hasta ahora.

    Los scripts que SÍ deben leer la tabla vieja (la migración a Parquet, el
    benchmark del backend legacy y el purgador) no están acá a propósito: su trabajo
    **es** esa tabla.
    """
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    for rel in ("analysis/metrics_panel.py", "scripts/dashboard_data.py"):
        sql = [s for s in _literales_ejecutables(raiz / rel) if "historical_data_cache" in s]
        assert not sql, f"{rel} volvió a leer la tabla a mano: {sql}"


def test_el_guard_de_arriba_NO_se_satisface_con_prosa():
    """La contraprueba del instrumento, que es lo que lo hace un guard y no un grep.

    Si mirara el archivo entero, los docstrings que citan el SELECT viejo lo pondrían
    rojo para siempre (pasó) y habría que borrar la explicación para que pase — o sea
    que el guard estaría peleado con documentar el defecto.
    """
    import ast
    import tempfile
    from pathlib import Path

    comillas = '"' * 3
    fuente = "\n".join(
        [
            comillas + "Un docstring que CITA: SELECT x FROM historical_data_cache WHERE y." + comillas,
            "def f(con):",
            "    return con.execute('SELECT 1')",
            "",
        ]
    )
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "m.py"
        f.write_text(fuente, encoding="utf-8")
        ast.parse(fuente)  # que sea python valido
        assert "historical_data_cache" in fuente, "la prosa SI menciona la tabla"
        assert not [s for s in _literales_ejecutables(f) if "historical_data_cache" in s], (
            "pero el guard no la cuenta, porque no es un literal que el modulo ejecute"
        )


def test_los_dos_consumidores_usan_EL_MISMO_lector(parquet_tmp, monkeypatch):
    """Dos copias divergen: es lo que dejó a ``dashboard_data`` roto cuando se miró
    ``metrics_panel``. Un test por identidad de resultado, no por lectura."""
    monkeypatch.setattr(hs, "backend_activo", lambda: "parquet")
    _escribir_parquet("SPY", [100.0, 101.0, 102.0])
    con = _con_con_tabla()

    assert mp.load_close_series(con, "SPY") == dd._load_close_series(con, "SPY")
    assert mp.load_close_series(con, "SPY") is not None


# ── `claves_1d`: el otro lector que la tabla vacía dejó mudo ─────────────────


def test_claves_1d_lista_el_cache_activo(parquet_tmp):
    """El proxy de mercado del dashboard listaba la tabla vieja: con 0 filas devolvía
    ``[]``, y el ``len(cols) < 5` de abajo lo convertía en *«no hay datos»*."""
    for t in ("AAA", "BBB", "CCC"):
        _escribir_parquet(t, [10.0, 11.0, 12.0])
    con = _con_con_tabla()

    assert hs.claves_1d(con) == ["AAA", "BBB", "CCC"]


def test_las_claves_del_cache_NO_son_tickers_pero_resuelven(parquet_tmp):
    """**La trampa de la tarea 190, declarada acá.** ``file_key`` no es reversible:
    ``BRK-B`` se guarda como ``BRK_B``. La clave que sale del listado **no** es el
    símbolo — pero como ``file_key`` es idempotente, volver a pedirla por este mismo
    módulo cae en el mismo archivo, que es lo único que el proxy necesita."""
    _escribir_parquet("BRK-B", [10.0, 11.0, 12.0])
    con = _con_con_tabla()

    claves = hs.claves_1d(con)
    assert claves == ["BRK_B"], "la clave está sanitizada, no es el ticker"
    assert hs.close_series(con, claves[0]) is not None, "y aun así resuelve al archivo"
    assert hs.close_series(con, "BRK-B") == hs.close_series(con, "BRK_B")


def test_claves_1d_sin_cache_devuelve_lista_vacia(parquet_tmp):
    assert hs.claves_1d(_con_con_tabla()) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
