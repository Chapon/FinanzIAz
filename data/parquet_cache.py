"""Backend Parquet + DuckDB para el cache OHLCV histórico (backlog ARQ1).

Reemplaza el ``HistoricalDataCache`` (JSON-de-texto en SQLite, parseado con
``pd.read_json`` en CADA lectura) por un archivo **Parquet por clave**
``(ticker, period, interval)`` en ``data/parquet/`` consultable columnar y, para
lo analítico multi-ticker, con **DuckDB** (window functions SQL) sobre el mismo
directorio.

Por qué (ref ``docs/architecture_review_2026-07-07.md`` §1):
  * **Velocidad:** E4 y todo harness barren 10y × 52 tickers repetidamente;
    leer columnar de Parquet es mucho más rápido que re-parsear JSON de texto.
  * **Menos contención SQLite (OPS1-b):** los precios dejan de escribir en la DB
    que comparten scan y harvest → menos ``database is locked``.
  * **Menos riesgo virtiofs (regla 5):** Parquet es *reemplazo de archivos*
    (``os.replace`` atómico), no un B-tree mutable — no corrompe por mounts.

Diseño (port fiel, drop-in detrás de las firmas de ``data/yahoo_finance.py``):
  * **Un archivo por clave:** ``data/parquet/{TICKER}__{period}__{interval}.parquet``.
    Mismas claves y semántica que la tabla vieja (una entrada por combinación).
  * **``fetched_at`` embebido** en la metadata de schema del Parquet (ISO-8601
    UTC) → el TTL se evalúa leyendo solo el footer, sin tocar SQLite.
  * **Sin columna ``ticker``** en el frame: el ticker vive en el nombre de
    archivo. Así el DataFrame devuelto es idéntico al del backend viejo
    (equivalencia byte-a-byte de datos). Para queries cross-ticker en DuckDB usar
    ``read_parquet(glob, filename=true)`` y parsear el ticker del ``filename``.

Este módulo NO decide nada de trading (regla 3 no aplica); es infraestructura de
datos con gate técnico duro (tests de equivalencia + benchmark).
"""

from __future__ import annotations

import contextlib
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config.logging_config import get_logger

log = get_logger(__name__)

# Clave de metadata donde embebemos el instante de fetch (para el TTL).
_FETCHED_AT_KEY = b"finanzias_fetched_at"

# Compresión: zstd = buen balance velocidad/tamaño y viene con el wheel de pyarrow.
_COMPRESSION = "zstd"

# Directorio por defecto: ``<repo>/data/parquet``. Override por env var
# (``FINANZIAS_PARQUET_DIR``) o por ``set_parquet_dir`` (tests → tmp_path).
_DEFAULT_DIR = Path(__file__).resolve().parent / "parquet"
_parquet_dir_override: Path | None = None


# ── Configuración del directorio ─────────────────────────────────────────────


def get_parquet_dir() -> Path:
    """Directorio donde viven los ``.parquet`` (override > env var > default)."""
    if _parquet_dir_override is not None:
        return _parquet_dir_override
    env = os.environ.get("FINANZIAS_PARQUET_DIR")
    return Path(env) if env else _DEFAULT_DIR


def set_parquet_dir(path: str | os.PathLike | None) -> None:
    """Fija (o resetea con ``None``) el directorio de parquets. Para tests."""
    global _parquet_dir_override
    _parquet_dir_override = Path(path) if path is not None else None


# ── Helpers internos ─────────────────────────────────────────────────────────


def _safe(token: str) -> str:
    """Sanitiza un token para nombre de archivo (tickers tipo ``BRK-B``/``^GSPC``).

    Reemplaza todo lo no-alfanumérico por ``_``. No necesita ser reversible: el
    ticker/period/interval siempre se conocen al leer (nunca se derivan del
    nombre). Colisiones son inviables en el universo de equities US.
    """
    return re.sub(r"[^A-Za-z0-9]", "_", str(token))


def path_for(ticker: str, period: str, interval: str) -> Path:
    """Ruta del parquet para la clave ``(ticker, period, interval)``."""
    fname = f"{_safe(ticker.upper())}__{_safe(period)}__{_safe(interval)}.parquet"
    return get_parquet_dir() / fname


def _to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _from_iso(s: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _read_fetched_at(path: Path) -> datetime | None:
    """Lee ``fetched_at`` de la metadata del parquet (solo footer, barato)."""
    try:
        md = pq.read_schema(path).metadata or {}
        raw = md.get(_FETCHED_AT_KEY)
        return _from_iso(raw.decode()) if raw is not None else None
    except Exception:
        return None


def _restore_frame(path: Path) -> pd.DataFrame | None:
    """Lee el parquet completo → DataFrame con índice datetime (como el backend viejo)."""
    try:
        df = pq.read_table(path).to_pandas()
        df.index = pd.to_datetime(df.index)
        return df
    except Exception:
        log.exception("Parquet cache read failed for %s", path.name)
        return None


# ── API pública (drop-in del cache OHLCV) ────────────────────────────────────


def write(
    ticker: str,
    period: str,
    interval: str,
    df: pd.DataFrame,
    fetched_at: datetime | None = None,
) -> None:
    """Reemplaza (atómico) la entrada de cache para ``(ticker, period, interval)``.

    ``fetched_at`` se embebe en la metadata (default: ahora, UTC). Escribe a un
    temporal y hace ``os.replace`` → nunca deja un parquet a medias (regla 5).
    """
    if df is None or df.empty:
        return
    d = get_parquet_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        when = fetched_at or datetime.now(timezone.utc)
        # yfinance nombra el índice "Date" (1d) / "Datetime" (intradía); si viene
        # sin nombre, pyarrow lo guardaría como ``__index_level_0__`` y DuckDB no
        # tendría columna de fecha. Lo canonizamos a "Date" (no muta al caller).
        if df.index.name is None:
            df = df.rename_axis("Date")
        table = pa.Table.from_pandas(df, preserve_index=True)
        md = dict(table.schema.metadata or {})
        md[_FETCHED_AT_KEY] = _to_iso(when).encode()
        table = table.replace_schema_metadata(md)

        path = path_for(ticker, period, interval)
        tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
        try:
            pq.write_table(table, tmp, compression=_COMPRESSION)
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                with contextlib.suppress(OSError):
                    tmp.unlink()
    except Exception:
        log.exception("Parquet cache write failed for %s", ticker.upper())


def read(ticker: str, period: str, interval: str, ttl_hours: float | None) -> pd.DataFrame | None:
    """Frame cacheado fresco para ``(ticker, period, interval)`` o ``None``.

    Respeta el TTL igual que el backend SQLite: si ``fetched_at`` es más viejo que
    ``ttl_hours`` (o no se puede determinar) → miss. ``ttl_hours=None`` desactiva
    el chequeo de frescura.
    """
    path = path_for(ticker, period, interval)
    if not path.exists():
        return None
    if ttl_hours is not None:
        fetched = _read_fetched_at(path)
        if fetched is None:
            return None  # sin sello de frescura → tratamos como stale (refetch)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
        if fetched < cutoff:
            return None
    return _restore_frame(path)


def _candidates_1d(ticker: str) -> list[Path]:
    """Parquets ``1d`` del ticker (cualquier period), del más fresco al más viejo."""
    d = get_parquet_dir()
    if not d.exists():
        return []
    t = _safe(ticker.upper())
    suffix = _safe("1d")
    candidates = list(d.glob(f"{t}__*__{suffix}.parquet"))

    def _freshness(p: Path) -> datetime:
        f = _read_fetched_at(p)
        if f is not None:
            return f
        try:
            return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return datetime.min.replace(tzinfo=timezone.utc)

    return sorted(candidates, key=_freshness, reverse=True)


def latest_1d(ticker: str) -> pd.DataFrame | None:
    """Frame ``1d`` más fresco del ticker sin importar el ``period`` (ancla de escala).

    Equivalente parquet de ``reference_close``: NO aplica TTL (staleness aceptable
    para anclar la escala del precio). Elige el candidato con el ``fetched_at``
    embebido más nuevo (fallback: mtime del archivo).
    """
    candidates = _candidates_1d(ticker)
    if not candidates:
        return None
    return _restore_frame(candidates[0])


def all_1d(ticker: str) -> list[pd.DataFrame]:
    """**Todos** los frames ``1d`` del ticker, del más fresco al más viejo.

    El par de ``latest_1d``, y existe para lo que aquél no puede hacer: **cruzar**
    los períodos en vez de elegir uno (tarea 63). Dos frames del mismo ticker que
    no coinciden en la escala son la única señal, disponible sin red y sin un
    provider nuevo, de que el cache **no puede arbitrar** — es el sanity bilateral
    de la tarea 14 un nivel más abajo, intra-proveedor.
    """
    out: list[pd.DataFrame] = []
    for p in _candidates_1d(ticker):
        df = _restore_frame(p)
        if df is not None:
            out.append(df)
    return out


def invalidate(ticker: str) -> None:
    """Borra todos los parquets del ticker (cualquier period/interval)."""
    d = get_parquet_dir()
    if not d.exists():
        return
    t = _safe(ticker.upper())
    for p in d.glob(f"{t}__*.parquet"):
        try:
            p.unlink()
        except OSError:
            log.exception("Parquet invalidate failed for %s", p.name)


# ── Capa analítica DuckDB (window functions cross-ticker) ────────────────────


def parquet_glob(interval: str | None = None) -> str:
    """Glob para ``read_parquet`` en DuckDB. Filtra por interval si se pasa."""
    d = get_parquet_dir()
    if interval:
        return str(d / f"*__{_safe(interval)}.parquet")
    return str(d / "*.parquet")


def scan(sql: str, params: list | None = None) -> pd.DataFrame:
    """Corre SQL DuckDB sobre los parquets y devuelve un DataFrame.

    El FROM debe usar ``read_parquet(...)`` con ``parquet_glob(...)`` como
    parámetro. Para saber de qué ticker es cada fila, pasar ``filename=true`` a
    ``read_parquet`` (el ticker vive en el nombre de archivo, no como columna).

    Ejemplo (retorno diario por ticker con LAG):
        scan(
            "SELECT filename, \"Close\" / LAG(\"Close\") OVER "
            "(PARTITION BY filename ORDER BY \"Date\") - 1 AS ret "
            "FROM read_parquet(?, filename=true)",
            [parquet_glob("1d")],
        )
    """
    import duckdb

    con = duckdb.connect()
    try:
        return con.execute(sql, params or []).fetch_df()
    finally:
        con.close()
