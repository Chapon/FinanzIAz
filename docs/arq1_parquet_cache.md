# ARQ1 — Cache OHLCV histórico: JSON-en-SQLite → Parquet + DuckDB

_2026-07-12 · ref `docs/architecture_review_2026-07-07.md` §1 · severidad ALTA · calidad de datos / infraestructura._

## Qué cambió

El cache OHLCV histórico (`historical_data_cache`) guardaba cada DataFrame como
**JSON de texto** en SQLite (`data_json = df.to_json(orient="split")`), reparseado
con `pd.read_json` en **cada lectura**. Se agregó un backend alternativo **Parquet
por clave `(ticker, period, interval)`** en `data/parquet/`, seleccionable por el
flag `historical_cache_backend` (`sqlite` | `parquet` | `dual`), más una capa
analítica **DuckDB** sobre el directorio de parquets (window functions SQL).

El swap es **drop-in detrás de las firmas existentes** de `data/yahoo_finance.py`
(`_read_historical_cache` / `_write_historical_cache` / `reference_close`): los
callers (`get_historical_data`, `get_historical_data_batch`) no cambian.

## Por qué

1. **Velocidad en el patrón E4/harness** — barridos 10y × 52 tickers repetidos, y
   sobre todo **lectura columnar** de las columnas de feature (ver benchmark).
2. **Menos contención SQLite (OPS1-b)** — los precios dejan de escribir en la DB
   que comparten scan y harvest → menos `database is locked`.
3. **Menos riesgo virtiofs (regla 5)** — Parquet es reemplazo de archivos
   (`os.replace` atómico), no un B-tree mutable que corrompe vía mounts.
4. **Capacidad nueva DuckDB** — `lag`/rolling/agregaciones SQL sobre el histórico
   sin cargar 52 frames a pandas (input del rediseño predictivo, tarea 9).

## Diseño (decisiones)

- **File-per-key**, no "un parquet por ticker con slicing": da equivalencia
  byte-a-byte trivial con el backend viejo y ya acelera E4 (que lee 10y). La
  consolidación por ticker queda como follow-up si el benchmark lo pidiera.
- **`fetched_at` embebido** en la metadata de schema del Parquet (ISO-8601 UTC) →
  el TTL (`HISTORICAL_CACHE_TTL_HOURS`) se evalúa leyendo solo el footer, **sin
  tocar SQLite**. La migración preserva el `fetched_at` original (TTL idéntico).
- **Sin columna `ticker`** en el frame (vive en el nombre de archivo) → el
  DataFrame devuelto es idéntico al del backend viejo. Para queries cross-ticker
  en DuckDB: `read_parquet(glob, filename=true)` y parsear el ticker del filename.
- **Índice canonizado a `"Date"`** si viene sin nombre (los frames de yfinance ya
  lo traen), para que DuckDB tenga una columna de fecha predecible.
- **Escritura atómica** (temp + `os.replace`) → nunca deja un parquet a medias.

## Kill-criteria (gate técnico — regla 3 no aplica, no toca decisiones)

- ✅ **Tests de equivalencia verdes:** `tests/test_parquet_cache.py` (round-trip +
  equivalencia vs el round-trip JSON), `tests/test_historical_cache_backend.py`
  (paridad end-to-end sqlite vs parquet a través de `yahoo_finance`, los 3
  backends, `reference_close`, fallback dual), `tests/test_migrate_historical_cache.py`.
- ✅ **Suite Windows verde** (ver commit).
- ✅ **Benchmark documentado** (abajo).

## Benchmark (`scripts/benchmark_historical_cache.py`, DB viva, 288 claves, 5 pasadas)

| Escenario | JSON-en-SQLite | Parquet | Speedup |
|---|---:|---:|---:|
| Todo el cache, frame completo | 3.71s | 2.24s | **1.66×** |
| Todo el cache, **solo `Close`** (columnar) | 3.66s | 0.90s | **4.05×** |
| Solo 10y (42 claves), frame completo | 1.06s | 0.48s | **2.23×** |
| Solo 10y, **solo `Close`** (columnar) | 1.06s | 0.13s | **8.04×** |
| Footprint en disco (todo el cache) | 22.68 MB | 11.76 MB | **1.93× más chico** |

**Lectura honesta:** el multiplicador "10–100×" del backlog aplica a la **lectura
columnar** (leer solo las columnas de feature), no a "cargar el frame chico
entero" — ahí el costo fijo de abrir el archivo casi cancela el ahorro de parse,
y el frame chico (1y/2y, ~250–500 filas) queda cerca de la paridad. El win crece
con el tamaño del frame (10y: 2.2× entero, 8× columnar) y con la proyección de
columnas. Sumado a menos contención, corrupción y disco, el swap se justifica; la
ganancia grande de E4 se materializa cuando el cómputo de features pase a DuckDB
(tarea 9), no en el read de frame entero.

## Cómo activar / rollback (acción de Chapa, en Windows)

1. Migrar el cache existente (idempotente, no toca la tabla SQLite):
   `python scripts/migrate_historical_cache_to_parquet.py --apply`
   _(ya corrido el 2026-07-12: 288/288 filas → `data/parquet/`, 0 fallidas)._
2. Activar en `~/.finanzias/settings.json`: `"historical_cache_backend": "parquet"`
   (o `"dual"` para transición: escribe a ambos, lee parquet con fallback a SQLite).
3. **Rollback: CADUCADO el 2026-09-02 (tarea 77).** Volver el flag a `"sqlite"` ya **no**
   restaura el estado previo: las 288 filas de `historical_data_cache` (22,7 MB, el 24% del
   archivo de DB) estaban congeladas en el **2026-07-11** —el día anterior a activar Parquet—
   y se borraron en la revisión alembic `0011`. Parquet corre en vivo desde el 2026-07-12 sin
   incidentes, así que lo que ese rollback ofrecía era volver a **julio**, no volver atrás.
   Borrarlas además cierra un agujero: `_read_latest_1d_frame` y `_read_all_1d_frames` no
   tienen TTL y alimentan el guard de sanity E5 y el detector de split de la T63 — con backend
   `sqlite` habrían usado el close del 2026-07-11 como referencia. Ahora devuelven vacío, que
   es fail-open ruidoso en vez de una referencia vieja disfrazada de actual.
   **Si alguna vez hace falta el backend SQLite, se re-puebla desde Parquet**, que es donde
   están los frames vivos. La tabla sigue existiendo; lo que no existe es su contenido viejo.

Default de ship: `"sqlite"` (paridad, cero cambio de comportamiento — mismo patrón
que E1b). `data/parquet/` está gitignoreado (cache regenerable).
