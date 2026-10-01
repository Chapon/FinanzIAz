"""Series 1d del cache OHLCV, leídas por el backend **activo** (tarea 218).

Por qué existe este módulo
--------------------------
``analysis/metrics_panel.py`` y ``scripts/dashboard_data.py`` tenían **cada uno su
copia** del mismo lector: un ``SELECT data_json FROM historical_data_cache WHERE
ticker=? AND interval='1d' ORDER BY fetched_at DESC LIMIT 1`` más un parseo de
``orient="split"``. Las dos copias quedaron leyendo una tabla que **ya no se
escribe**:

* el **2026-07-12** ARQ1 activó el backend **Parquet** y ``yahoo_finance`` dejó de
  escribir ``historical_data_cache`` — la última fila quedó del **2026-07-11**;
* el **2026-09-02** la migración **0011** la **vació** a propósito (288 filas /
  22,7 MB), porque el rollback de ARQ1 había caducado.

Nadie migró a los consumidores. Resultado medido el 2026-09-21:
``_benchmark_panel(con, 2)`` devolvía ``available=False`` / ``vs_spy=None``, o sea
que **la tarjeta VS SPY, MAE/MFE y el fwd-5d estaban apagados** — justo la capa V1,
la que existe para separar sistema de mercado.

**Dos copias es lo que permitió que un arreglo no alcanzara al otro consumidor**, que
es la misma lección que dejaron la 207 (``collect_all`` con dos caminos) y la 212.
Por eso el lector ahora es **uno solo** y los dos módulos lo llaman.

Qué hace y qué NO hace
----------------------
Despacha igual que ``data.yahoo_finance._read_latest_1d_frame``: con backend
``parquet``/``dual`` intenta Parquet primero, y **con ``parquet`` no cae a SQLite**
— devolver una fila de julio disfrazada de actual es peor que no devolver nada, que
es exactamente lo que argumentó la migración 0011 (*«fail-open ruidoso»*).

Devuelve **tipos planos** (listas de tuplas), no DataFrames, y ``pandas`` se importa
**lazy** dentro del camino Parquet: ``dashboard_data`` es un CLI que imprime JSON y
evita pandas en el import de módulo a propósito.

La conexión ``con`` sigue siendo la del **llamador** y se usa sólo en el camino
SQLite. En la suite el autouse ``_disable_settings_persistence`` redirige los
settings a un tmp, así que el backend cae al default ``sqlite`` y los tests que
arman un cache sintético siguen valiendo **sin depender de la máquina** — que es la
lección de la tarea 176.
"""

from __future__ import annotations

import json
import sqlite3

from config.logging_config import get_logger

log = get_logger(__name__)

__all__ = ["backend_activo", "claves_1d", "close_series", "ohlc_series"]

# (dia, close, high|None, low|None). High/Low en None = la fuente no los traia;
# NO se sustituyen por el close, porque MAE/MFE con rango=close subestima la
# excursion en silencio, que es peor que no tener el dato.
_Fila = tuple[str, float, float | None, float | None]


def backend_activo() -> str:
    """``'sqlite'`` | ``'parquet'`` | ``'dual'``. Mismo contrato que ARQ1.

    Default ``sqlite`` y fail-open: si los settings no se pueden leer, se degrada al
    backend legacy en vez de tirar — esto alimenta paneles de display.
    """
    try:
        from config.settings_manager import settings

        val = settings.get("historical_cache_backend", "sqlite")
        return val if val in ("sqlite", "parquet", "dual") else "sqlite"
    except Exception:
        return "sqlite"


def _filas_parquet(ticker: str) -> list[_Fila] | None:
    """``[(YYYY-MM-DD, close, high, low)]`` desde Parquet, o ``None`` si no hay.

    ``pandas``/``pyarrow`` se importan acá adentro, no arriba.
    """
    try:
        from data import parquet_cache

        df = parquet_cache.latest_1d(ticker.upper())
    except Exception:
        log.exception("parquet latest_1d fallo para %s", ticker)
        return None
    return _filas_de_frame(df)


def _filas_de_frame(df) -> list[_Fila] | None:
    """``[(YYYY-MM-DD, close, high, low)]`` de un frame OHLC, o ``None``."""
    if df is None or getattr(df, "empty", True):
        return None
    out: list[_Fila] = []
    cols = set(df.columns)
    if "Close" not in cols:
        return None
    hay_rango = "High" in cols and "Low" in cols
    for idx, fila in df.iterrows():
        try:
            dia = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
            cl = fila["Close"]
            if cl is None:
                continue
            hi = float(fila["High"]) if hay_rango else None
            lo = float(fila["Low"]) if hay_rango else None
            out.append((dia, float(cl), hi, lo))
        except (TypeError, ValueError, KeyError):
            continue
    return out or None


def _filas_sqlite(con: sqlite3.Connection, ticker: str) -> list[_Fila] | None:
    """Lo mismo desde la tabla vieja, sobre la conexión que pasó el llamador."""
    try:
        row = con.execute(
            "SELECT data_json FROM historical_data_cache "
            "WHERE ticker = ? AND interval = '1d' "
            "ORDER BY fetched_at DESC LIMIT 1",
            (ticker,),
        ).fetchone()
    except sqlite3.Error:
        return None
    if not row or not row[0]:
        return None
    try:
        d = json.loads(row[0])
        # Tolera columnas planas ("High") y serializadas como tupla (["High","MSFT"],
        # que es como sale un frame MultiIndex). Lo hacia `load_ohlc_series` y se
        # conserva: un frame asi es real y perderlo seria una regresion silenciosa.
        cols = [c[0] if isinstance(c, list) else c for c in d["columns"]]
        ic = cols.index("Close")
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    hay_rango = "High" in cols and "Low" in cols
    ih = cols.index("High") if hay_rango else -1
    il = cols.index("Low") if hay_rango else -1
    out: list[_Fila] = []
    # strict=False a proposito: esto parsea un JSON EXTERNO en un path de display, y
    # el try/except de arriba ya cerro. Un largo distinto tiene que degradar.
    for idx, vals in zip(d.get("index", []), d.get("data", []), strict=False):
        try:
            cl = vals[ic]
        except (IndexError, TypeError):
            continue
        if cl is None or not isinstance(idx, str):
            continue
        try:
            hi = float(vals[ih]) if hay_rango and vals[ih] is not None else None
            lo = float(vals[il]) if hay_rango and vals[il] is not None else None
            out.append((idx[:10], float(cl), hi, lo))
        except (IndexError, TypeError, ValueError):
            continue
    return out or None


def _filas_1d(con: sqlite3.Connection, ticker: str) -> list[_Fila] | None:
    """El despacho, y es el punto del módulo. Ver el docstring de arriba."""
    backend = backend_activo()
    filas: list[_Fila] | None = None
    if backend in ("parquet", "dual"):
        filas = _filas_parquet(ticker)
        if filas is None and backend == "parquet":
            # NO se cae a SQLite: con ARQ1 activo esa tabla esta vacia, y si algun dia
            # deja de estarlo serian datos de julio 2026 presentados como actuales.
            return None
    if filas is None:
        filas = _filas_sqlite(con, ticker)
    if not filas:
        return None
    # Un close <= 0 es basura, no un precio: lo filtraba la copia de `dashboard_data`
    # y no la de `metrics_panel`. Al unificar se queda el que protege. El orden se
    # fuerza acá y no en cada lector, que es lo que hacia que dependiera de la fuente.
    filas = sorted((f for f in filas if f[1] > 0), key=lambda f: f[0])
    return filas or None


def empalmar(
    base: list[tuple[str, float]] | None, ticker: str, *, frames: list | None = None
) -> list[tuple[str, float]] | None:
    """``base`` extendida hacia ATRÁS con los frames ``1d`` más viejos del ticker (tarea 246).

    **Por qué existe.** ``close_series`` lee ``latest_1d``, el frame **más fresco** —para
    SPY, el ``2y`` que el scan refresca—, y ese frame es una ventana **rodante** mientras el
    arranque de una cuenta queda **fijo**. El guard de la 225 lo midió: el colchón se achica
    ~1 rueda por día, y cuando el inicio del ``2y`` pase al de la cuenta (~mediados de 2028
    para la 2) el VS SPY se apaga para siempre. Pero el cache ya tiene un ``10y`` de SPY que
    arranca en 2016: sólo nadie lo leía.

    **Cómo empalma, y por qué así.** Con ``auto_adjust`` cada fetch re-escala la historia por
    los dividendos que hubo hasta ese día, así que dos frames del mismo ticker bajados en
    fechas distintas difieren por un factor. Pegarlos tal cual mete un salto falso en la
    junta. Se toma la **primera fecha en común** y el tramo viejo se multiplica por la razón
    de los dos cierres ahí: los retornos de cada tramo quedan intactos y la junta, continua.
    Un frame sin fechas en común **no se empalma** — no hay con qué escalarlo.

    Sólo con backend ``parquet``/``dual`` (``frames=None``): con ``sqlite`` hay un solo frame
    por ticker y no hay qué empalmar. ``frames`` se inyecta en los tests.
    """
    if not base:
        return base
    if frames is None:
        if backend_activo() not in ("parquet", "dual"):
            return base
        try:
            from data import parquet_cache

            frames = parquet_cache.all_1d(ticker.upper())
        except Exception:
            log.exception("empalme: no se pudieron leer los frames 1d de %s", ticker)
            return base
    out = dict(base)
    tramos = []
    for df in frames or []:
        filas = _filas_de_frame(df)
        if filas:
            tramos.append({dia: cl for dia, cl, _hi, _lo in filas if cl > 0})
    # Del que empieza más tarde al que empieza más temprano: cada uno extiende lo ya armado.
    for tramo in sorted((t for t in tramos if t), key=min, reverse=True):
        inicio = min(out)
        viejos = {d: c for d, c in tramo.items() if d < inicio}
        comunes = sorted(d for d in tramo if d in out)
        if not viejos or not comunes:
            continue
        factor = out[comunes[0]] / tramo[comunes[0]]
        out.update({d: c * factor for d, c in viejos.items()})
    return sorted(out.items())


# El frame LARGO del benchmark (tarea 246). `empalmar` necesita que se SOLAPE con el `2y`
# rodante; con este umbral se baja de nuevo cada ~3 meses: un fetch, y el solape nunca baja de
# ~21 meses.
#
# **Es un frame PROPIO, `max`, y no el `10y` (tarea 251).** El `10y` de SPY es sustrato del
# harness —la serie de régimen de tres runners— y lo refresca `refresh_cohort` junto con el
# universo. La primera versión de este job reescribía ese `10y` por fuera del cohorte; la
# segunda tanda `/audit` del 2026-09-30 lo vio. `max` además nunca deja de cubrir el arranque
# de la cuenta.
BENCHMARK_LARGO_PERIOD = "max"
BENCHMARK_LARGO_MAX_EDAD_DIAS = 90


def benchmark_largo_vencido(
    ultimo_dia: str | None, hoy: str, max_edad_dias: int = BENCHMARK_LARGO_MAX_EDAD_DIAS
) -> bool:
    """¿Hay que volver a bajar el frame largo? Puro: sin frame, o con el último día viejo."""
    if not ultimo_dia:
        return True
    try:
        from datetime import date

        edad = (date.fromisoformat(hoy[:10]) - date.fromisoformat(ultimo_dia[:10])).days
    except ValueError:
        return True
    return edad > max_edad_dias


def refrescar_benchmark_largo(ticker: str = "SPY", *, hoy: str, fetch=None) -> dict:
    """Baja de nuevo el frame largo (``max``) del benchmark si está vencido (tareas 246/251). Red: sí.

    Lee el último día de ese frame en el parquet; si está vencido o no existe, lo pide a Yahoo
    con ``get_historical_data`` (que escribe el cache). **No toca el ``10y``**, que es del
    cohorte del harness. ``fetch`` se inyecta en los tests.
    """
    ultimo = None
    try:
        from data import parquet_cache

        for etiqueta, df in parquet_cache.labelled_1d(ticker.upper()):
            if etiqueta == BENCHMARK_LARGO_PERIOD:
                filas = _filas_de_frame(df)
                ultimo = filas[-1][0] if filas else None
                break
    except Exception:
        log.exception("benchmark largo: no se pudo leer el frame %s de %s", BENCHMARK_LARGO_PERIOD, ticker)
    if not benchmark_largo_vencido(ultimo, hoy):
        return {"refrescado": False, "ultimo_dia": ultimo}
    if fetch is None:
        from data.yahoo_finance import get_historical_data as fetch
    df = fetch(ticker.upper(), period=BENCHMARK_LARGO_PERIOD, interval="1d")
    filas = _filas_de_frame(df)
    return {
        "refrescado": filas is not None,
        "ultimo_dia_antes": ultimo,
        "ultimo_dia": filas[-1][0] if filas else None,
    }


def close_series(con: sqlite3.Connection, ticker: str) -> list[tuple[str, float]] | None:
    """``[(YYYY-MM-DD, close)]`` ascendente, o ``None`` si no hay serie."""
    filas = _filas_1d(con, ticker)
    if not filas:
        return None
    return [(dia, cl) for dia, cl, _hi, _lo in filas]


def ohlc_series(con: sqlite3.Connection, ticker: str) -> list[tuple[str, float, float]] | None:
    """``[(YYYY-MM-DD, high, low)]`` ascendente, o ``None`` si no hay serie.

    Devuelve ``None`` tambien cuando la fuente **no trae High/Low**, y eso es
    deliberado: es el rango intradia que un stop o un target realmente ve, y
    reemplazarlo por el close daria un MAE/MFE sistematicamente chico sin que nada
    lo diga. Mismo contrato que tenia ``metrics_panel.load_ohlc_series``.
    """
    filas = _filas_1d(con, ticker)
    if not filas:
        return None
    out = [(dia, hi, lo) for dia, _cl, hi, lo in filas if hi is not None and lo is not None]
    return out or None


def claves_1d(con: sqlite3.Connection) -> list[str]:
    """Las claves con serie ``1d`` en el cache activo, para indexar el directorio.

    **Son claves de cache, NO tickers, y la diferencia importa.** En Parquet el
    nombre de archivo pasa por ``parquet_cache.file_key``, que **no es reversible**:
    ``BRK-B`` se guarda como ``BRK_B``. Derivar el ticker del nombre es justo lo que
    dejó a ``BRK-B`` fuera de ``cross_period_gaps`` en la **tarea 190**.

    Sirven acá porque ``file_key`` es **idempotente** —``file_key("BRK_B") ==
    file_key("BRK-B")``—, así que volver a pedirlas por este mismo módulo resuelve al
    mismo archivo. Lo que NO se puede es mostrarlas como si fueran el símbolo real ni
    mandarlas a una fuente externa.

    El consumidor es el proxy de mercado del dashboard, que promedia series
    normalizadas: le da igual el nombre, necesita la canasta.
    """
    backend = backend_activo()
    if backend in ("parquet", "dual"):
        try:
            from data import parquet_cache

            d = parquet_cache.get_parquet_dir()
            claves = sorted({f.name.split("__")[0] for f in d.glob("*__*__1d.parquet")})
        except Exception:
            log.exception("no se pudo listar el cache parquet")
            claves = []
        if claves or backend == "parquet":
            return claves
    try:
        return [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT ticker FROM historical_data_cache WHERE interval = '1d'"
            ).fetchall()
        ]
    except sqlite3.Error:
        return []
