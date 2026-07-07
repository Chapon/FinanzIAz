# Revisión de arquitectura — 2026-07-07

Revisión profunda pedida por Chapa: oportunidades de mejora, tecnologías nuevas, lo que haga mejor a la app. Basada en exploración del repo real (58.5k LOC: ui 12.7k, analysis 8.9k, scripts 7.8k, paper_trading 5.1k, data 4.2k, tests 16.5k en 80 archivos) + la DB viva (47 MB).

## Veredicto general

La arquitectura es **sana y por encima del estándar** para un proyecto personal: separación limpia de capas (data/analysis/paper_trading/ui), 1062 tests con guard de red y de DB real en conftest, alembic, ruff+mypy+pre-commit+CI configurados, funciones puras para decisiones (gates, `hourly_harvest_due`), workers QThread correctos, cache XGB in-memory, WAL+retry en SQLite. Las oportunidades no son de "arreglar lo roto" sino de **quitar los tres cuellos de botella estructurales**: el data layer analítico, la dependencia única de yfinance, y el ciclo de vida del modelo ML.

---

## 1. Data layer analítico: JSON-en-SQLite → Parquet + DuckDB  ·  impacto ALTO · el que más paga

**Hoy:** `historical_data_cache` guarda cada DataFrame como **JSON de texto dentro de SQLite** (283 filas, 22.5 MB de JSON; `models.py:271`, `to_json(orient="split")`) y cada lectura hace `pd.read_json` por ticker. Para el scan (52 lecturas puntuales) alcanza; para **E4/backtests/harness** que barren 10 años × 52 tickers una y otra vez, es el peor formato posible: parseo de texto fila por fila, sin lectura columnar, sin predicados.

**Propuesta:** cache histórico en **Parquet por ticker** (`data/parquet/{ticker}.parquet`) + **DuckDB** para consultas analíticas. Evidencia pública: 10-100× vs SQLite en agregaciones, lectura columnar directa de Parquet sin importar, window functions SQL (lag/lead/rolling) ideales para features ([DuckDB vs SQLite](https://betterstack.com/community/guides/scaling-python/duckdb-vs-sqlite/), [pipeline con Parquet](https://www.kdnuggets.com/building-your-modern-data-analytics-stack-with-python-parquet-and-duckdb)). Además:
- **Reduce la contención de SQLite** (el lock scan-vs-harvest documentado): los precios dejan de escribir en la DB transaccional; SQLite queda solo para orders/positions/news — su caso de uso correcto.
- **Mitiga el riesgo virtiofs** (regla 5): Parquet es append/replace de archivos, no B-tree mutable.
- E4 (en curso) es el consumidor inmediato: el generador CPCV leería Parquet directo.
- Migración incremental de bajo riesgo: `get_historical_data(_batch)` es la única puerta (yahoo_finance.py) — cambiar el backend del cache detrás de la misma firma, con dual-write transitorio y tests comparando outputs.

## 2. Provider de datos: abstraer yfinance con fallback  ·  impacto ALTO · resiliencia

**Hoy:** yfinance es punto único de fallo, y su historial lo prueba: 401 crumb (mitigado con retry/batch), throttle que envenenó el failing set (B3), precio ~10× corrupto que ejecutó un trade (E5/KLAC), snapshots móviles sin point-in-time. Cada incidente costó una sesión de debugging.

**Propuesta:** interfaz `PriceProvider` con cadena de fallback y cross-check:
- **Tiingo** (free tier: EOD limpio, 50 símbolos/hora — alcanza para 52 tickers 1×/día), **Stooq** (EOD sin API key, CSV directo) como segunda fuente EOD; **Finnhub** (ya integrado para news, 60 calls/min free) para quotes intradía.
- El **sanity check E5 se vuelve bilateral**: ante discrepancia >X% entre dos fuentes, descartar y loguear — mata la clase entera de bugs KLAC en vez del parche de banda.
- Bajo esfuerzo inicial: solo EOD-daily como fallback (el caso que rompe backtests); quotes después.

## 3. Ciclo de vida del modelo ML: de "entrenar en el scan" a "servir un artefacto"  ·  impacto ALTO · habilita la tarea 7

**Hoy:** `train_xgboost_signal` entrena **por ticker, dentro del scan**, con cache solo in-memory (se pierde al cerrar la app) → cada arranque re-entrena 52 modelos, cada uno con val set de ~40 (el overfitting estructural ya diagnosticado). El entrenamiento y la inferencia están acoplados al hot-path.

**Propuesta** (prerequisito práctico del meta-modelo pooled de la tarea 7):
- **Entrenamiento offline** programado (nightly/semanal, como el surprise rebuild que ya existe como patrón): entrena el modelo pooled, lo **persiste versionado** (joblib + fingerprint de datos + fecha + métricas de validación en un `model_registry.json`).
- El scan solo hace **inferencia** sobre el artefacto cargado → arranque más rápido, scans deterministas (hoy el modelo puede cambiar entre scans si el cache expiró — no-determinismo ya visto en T05), y auditoría honesta ("qué modelo decidió esta orden" queda trazable en la orden).
- Infra mínima: un script + un directorio `models/` + campo `model_version` en `paper_orders.notes`.

## 4. Concurrencia y robustez de datos  ·  impacto MEDIO

- **Upsert en earnings_cache** (ya en Bugs): reemplazar delete+insert por `INSERT ... ON CONFLICT DO UPDATE` + retry transitorio. Con el harvest horario nuevo, sube la frecuencia de oportunidades de lock — subió de prioridad.
- **Una sola cola de escritura**: si tras #1 el lock persiste, serializar las escrituras SQLite de workers por una cola simple (un solo escritor) en vez de confiar en busy_timeout.
- **Telemetría de scan**: no hay timing (grep `perf_counter|elapsed` en engine: 0). Agregar duración por fase (fetch/analyze/gates/fill) al `ScanResult` — para saber si el scan de 15 min aguantaría bajar a 5, y detectar degradación de Yahoo antes de que muerda.

## 5. UI: matplotlib embebido → pyqtgraph donde duela  ·  impacto BAJO-MEDIO · opcional

7 archivos de UI embeben matplotlib (canvas Agg dentro de Qt): funciona, pero es la fuente del warning `tight_layout` (chart_widget.py:190) y de redraws lentos con datos largos. **pyqtgraph** es Qt nativo (GPU, pan/zoom fluido, crosshair) y es el estándar de apps de trading en PyQt. Migración por widget (empezar por el chart de Analysis, el más interactivo); matplotlib puede quedarse para los estáticos (metrics). No urgente — es UX, no decisiones.

## 6. Calidad de código y testing  ·  impacto BAJO · deuda menor

- **Los 4 archivos >1.4k LOC** (engine.py 1640, ml_signals.py 1499, yahoo_finance.py 1473, paper_tab.py 1414) concentran el riesgo de merge/regresión. Split natural cuando se los toque (p.ej. engine: gates ya está separado; extraer fills y reconcile). No refactorizar por deporte.
- **Property-based testing (hypothesis)** para las funciones puras de decisión (gates, `hourly_harvest_due`, `screen_candidate`, `is_price_out_of_band`): los invariantes ("un BUY nunca supera el cash", "el stop nunca sube") son exactamente lo que hypothesis encuentra gratis. Dev-dep, cero riesgo runtime.
- **Upgrade de stack** ya en backlog (numpy 2.x, sklearn 1.8 FrozenEstimator, PyQt6 6.8) — sin cambios de prioridad; DuckDB/pyarrow (#1) conviene sumarlo en el mismo salto de deps.

## 7. LLM local: exprimir el qwen que ya corre  ·  impacto MEDIO · costo mínimo

- **Structured outputs**: Ollama soporta salida con JSON schema — el classify se vuelve más robusto que parsear texto, y en el mismo prompt se agrega la **polaridad** (idea G12, costo ~cero) y una **relevancia 0-1**. Un solo cambio de prompt+parser acumula histórico point-in-time de sentiment desde ya.
- **Modelo**: qwen2.5:14b sigue siendo razonable; evaluar qwen3 (misma familia, mejor instruction-following) cuando el classify tenga eval (`--sample 100` de T-CAT-2 sigue pendiente — hacerla ANTES de cambiar de modelo, para tener baseline).

## 8. Lo que NO cambiaría

- **PyQt6 + QThread + QTimer**: el modelo de concurrencia es correcto y está testeado; no hay razón para asyncio/APScheduler.
- **SQLite para lo transaccional**: orders/positions/news están bien donde están (con WAL). El problema es solo el cache analítico (#1).
- **Alembic, settings_manager, estructura de capas, suite de tests**: por encima del estándar; no tocar.
- **No microservicios, no web, no docker**: app de escritorio personal — la simplicidad ES la feature.

---

## Priorización integrada

| # | Mejora | Impacto | Esfuerzo | Cuándo |
|---|---|---|---|---|
| 1 | Parquet+DuckDB para el cache histórico | ALTO (E4 más rápido, menos locks, menos virtiofs) | Medio | Idealmente durante/después de E4 (su consumidor) |
| 2 | Model lifecycle offline (train nightly + artefacto versionado) | ALTO | Medio | Prerequisito práctico de la tarea 7 |
| 3 | Provider fallback EOD (Tiingo/Stooq) + sanity bilateral | ALTO (resiliencia) | Medio | Independiente; tras #1 |
| 4 | Upsert earnings_cache + telemetría de scan | MEDIO | Bajo | Ya en Bugs; subió con harvest horario |
| 5 | Structured outputs + polaridad en el classify | MEDIO | Bajo | Ya (acumula histórico para G12/tarea 7) |
| 6 | hypothesis en gates puros | BAJO | Bajo | Oportunista |
| 7 | pyqtgraph en Analysis chart | BAJO (UX) | Medio | Cuando moleste |

**Regla transversal:** nada de esto toca decisiones de trading → no requiere kill-criteria (regla 2), pero #1 y #3 requieren tests de equivalencia (mismo input → mismo DataFrame) antes de swap.

---

*Método: exploración del repo (LOC, archivos grandes, grep de patrones), DB viva copiada read-only, evidencia externa en `docs/research_mejoras_2026-07-07.md` §E y las fuentes DuckDB citadas arriba.*
