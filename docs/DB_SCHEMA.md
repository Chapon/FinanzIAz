# Diccionario de la DB — FinanzIAs

SQLite (`finanzias.db`), SQLAlchemy. Esquema en `database/models.py` (general) y `paper_trading/models.py` (paper_*). Migraciones por **alembic** (`init_db` → `_alembic_sync`, ver `docs/schema_management.md`).

> **No escribir la DB desde Linux/sandbox** (corrupción intermitente). Leer copiando a /tmp primero. Backups en `backups/`.

## Paper trading (`paper_trading/models.py`)

### `paper_accounts` — cuentas de simulación
`id`, `name` (unique), `description`, `strategy` (def `analyze_single`), `mode` (`auto`/`manual`), `allocation_mode`, `max_positions` (def 5), `fixed_amount` (def 5.000, sólo con `allocation_mode=fixed_amount`), `initial_capital` (50k), `cash`, `commission` (0.001), `slippage` (0.0005), `drift_threshold`, `monthly_rebalance`, `last_monthly_rebalance`, `is_active`, `last_scan_at`, `slack_notify`.
→ La cuenta viva es la de `is_active=1` — consultala en la tabla, no la copies acá. Esta línea la afirmaba escrita a mano, y durante tres meses dijo la cuenta 1 (cerrada desde el 2026-09-13) y un «modo kill_only» que no existe: la config de modelo vive en `~/.finanzias/settings.json` (tareas 181 y 239).

### `paper_watchlist` — tickers por cuenta
`id`, `account_id` (FK), `ticker`, `added_at`.

### `paper_positions` — posiciones abiertas
`id`, `account_id` (FK), `ticker`, `shares`, `avg_cost` (VWAP incl. fees/slippage), `opened_at`, `updated_at`, `entry_reason`, `high_water_mark`.

### `paper_orders` — órdenes (el log de decisiones)
`id`, `account_id` (FK), `ticker`, `side` (BUY/SELL), `target_shares`, `target_dollars`, `reason` ("signal"/"drift"/"monthly"/...), `source` (estrategia), **`signal_score`**, `status` (**pending → approved → filled**; o rejected), `created_at`, `decided_at`, `filled_at`, `fill_price`, `fill_shares`, `commission_paid`, `slippage_cost`, `notes`.
→ Tabla central para auditorías y backtests de exits.

### `paper_equity_snapshots` — curva de equity
`id`, `account_id` (FK), `snapshot_at`, `cash`, `positions_value`, `total_equity`, `portfolio_sigma`.

### `paper_dividend_credits` — el ledger de dividendos acreditados (tarea 222)
`id`, `account_id` (FK), `ticker`, `ex_date` (`YYYY-MM-DD`), `shares`, `amount_per_share`, `cash`, `credited_at`. UNIQUE `ux_paper_divcred_account_ticker_exdate`, migración **0014**.

Desde el 2026-09-25 el motor **acredita a la caja** el efectivo del ex-date (decisión de Chapa entre las tres salidas de la 221, con los costos medidos). Esta tabla registra **qué ya se pagó**: el scan corre varias veces por día y puede correr después de días con la app cerrada, así que sin un registro explícito el mismo ex-date se acreditaría de nuevo en cada pasada — y un doble crédito **no se lee como bug, se lee como rendimiento**. El UNIQUE va en el esquema y no en un `if`, igual que en la 0012 y la 0013.

Las tres columnas de monto se guardan aunque `cash = shares × amount_per_share`: el ledger tiene que poder auditarse sin re-derivar nada desde un calendario que para entonces pudo cambiar de fila. **Sólo hacia adelante**: la tabla arranca vacía y el motor acredita desde el primer ex-date de la ventana `(último scan, hoy]`, así que los $322,77 que la cuenta 2 ya había devengado al shipear la 222 (2026-09-25) **no** se backfillean y ninguna métrica publicada cambia de base.

### `paper_scan_candidates` — qué candidatos a compra evaluó cada scan (tarea 256)
`id`, `account_id` (FK), `scan_at` (UTC, el mismo del scan), `ticker`, `outcome`, `signal_score`, `rank`, `detail`. Índices `ix_paper_scancand_account_scan` y `ix_paper_scancand_ticker`, sin UNIQUE; migración **0015**.

`paper_orders` guarda lo que se **ejecutó**; esta tabla guarda también lo que **no**, para poder contestar *«¿por qué no compramos X?»*. `outcome` es uno de `sin_datos`, `screen`, `sin_lugar`, `sin_tamano`, `comprado`, `encolado` o `bloqueado` (con el texto del gate en `detail`). **No registra** los tickers en cartera ni los que dieron HOLD/SELL: si un ticker no aparece en un scan, ese scan no lo vio como compra. Sólo registro —el motor no la lee—, escrita en sesión propia después del commit del scan y podada a **90 días** por el propio scan. Se consulta con `python scripts/por_que_no_compramos.py <TICKER>`.

### `paper_split_adjustments` — el ledger de splits aplicados a posiciones abiertas (tarea 262)
`id`, `account_id` (FK), `ticker`, `ex_date` (`YYYY-MM-DD`), `ratio`, `shares_before`, `shares_after`, `avg_cost_before`, `avg_cost_after`, `hwm_before`, `hwm_after`, `applied_at`. Índice `ix_paper_splitadj_account` y UNIQUE `ux_paper_splitadj_account_ticker_exdate`; migración **0016**.

Un split N:1 sin ajustar dejaba la posición en la escala vieja y el primer scan con el precio nuevo veía una caída de (1−1/N): el trailing vendía con una pérdida que no existe. Desde la 262 el scan (`paper_trading/splits.py`, antes de la equity y de los stops) multiplica por N las acciones que había **antes** del ex-date, conserva el costo total y divide el máximo por N; esta tabla es lo que impide aplicarlo dos veces. Sólo splits **plausibles** (no el 2,793 fantasma de AVB), y sólo si la historia de órdenes reproduce las acciones de la posición: si no, no ajusta y avisa. El antes y el después se guardan para auditar sin depender del calendario de splits.

### `paper_spinoff_adjustments` — el ledger de spin-offs ajustados a mano (tarea 303)
`id`, `account_id` (FK), `ticker`, `ex_date` (`YYYY-MM-DD`), `child_ticker`, `q`, `r`, `parent_price`, `child_price`, `shares_at_ex`, `share_ratio`, `shares_before`, `shares_after`, `avg_cost_before`, `avg_cost_after`, `hwm_before`, `hwm_after`, `cash`, `applied_at`. Índice `ix_paper_spinoffadj_account` y UNIQUE `ux_paper_spinoffadj_account_ticker_exdate`; migración **0017**.

El scan no ajusta spin-offs (la 298: el factor de Yahoo no alcanza); se ajustan con `python scripts/ajustar_spinoff.py`, dry-run por default, con `q` y `r` del comunicado. La escindida se acredita **como caja** al precio de su primer día (decisión de Chapa, como los dividendos de la 222), las acciones de antes del ex-date pasan a `floor(acciones × q)` con la fracción en caja, el costo total baja en la caja recibida y el máximo se divide por `q + r·P_escindida/P_matriz`. `share_ratio` es el ratio **efectivo** de acciones (`floor(shares_at_ex × q) / shares_at_ex`) y `cash` incluye la fracción. El cuadre (`paper_trading/cuadre.py`) suma `cash` a la caja esperada y reconstruye las acciones con `share_ratio`; el ajuste de splits lo cuenta como evento ya aplicado; y el aviso de la 297 deja de repetirse para ese ex-date.

## Núcleo / caches (`database/models.py`)

| Tabla | Para qué |
|-------|----------|
| `portfolios` | Cartera real del usuario. |
| `positions` | Posiciones de la cartera real. |
| `transactions` | Transacciones (P&L). |
| `alerts` | Alertas de precio. Estado derivado: `is_active=False` ⇒ "disparada"; `is_active=True` + `is_paused=True` ⇒ "pausada" (no se evalúa en `check_alerts`); resto ⇒ "activa" (ALRT1, col `is_paused` NOT NULL default false, migración 0008). |
| `price_cache` | Cache de precios actuales. |
| `dividend_cache` | Cache del **acumulado** de dividendos: `$/acción desde una fecha hasta hoy`, TTL 6 h. Contesta *«¿cuánto lleva cobrado esta posición abierta?»* y su consumidor es `ui/portfolio_tab.py` (cartera real). **No sirve para un intervalo cerrado** — sacarlo de acá obliga a restar dos filas fetcheadas en momentos distintos, y un ex-date en el medio corrompe la resta sin error. Para eso está la tabla de abajo. |
| `dividend_calendar_cache` | El **calendario** de ex-dates: una fila por `(ticker, ex_date)` con el monto en $/acción sin ajustar por splits (UNIQUE `ux_divcal_ticker_exdate`, migración **0013**, tarea **221**). Lo llena `get_dividend_calendar`/`get_bulk_dividend_calendar` (cache-first, TTL 24 h evaluado sobre el `fetched_at` más nuevo del ticker: un ex-date pasado no cambia, sólo puede aparecer uno nuevo). Un ticker que no paga deja una fila **centinela** `ex_date='0000-00-00'` con monto 0, para que el TTL lo tape en vez de re-fetchearlo en cada refresh. Su consumidor es el **VS SPY** del panel de métricas, que sin esto restaba el retorno de *precio* de la cuenta contra un SPY *total-return*. |
| `historical_data_cache` | **VACÍA y sin escritor desde ARQ1** (2026-07-12): el cache OHLCV vive en `data/parquet/`, y la migración **0011** borró sus 288 filas el 2026-09-02. La tabla se conserva porque el backend `sqlite` sigue siendo un camino válido (`historical_cache_backend`). Leer de acá a mano fue el defecto de la tarea **218** — usá `data/historical_series.py`, que despacha por el backend activo. |
| `earnings_cache` | Fechas de earnings. |
| `analyst_data_cache` | Recos + price targets cacheados. |
| `company_info_cache` | Nombre, sector e industria por ticker (UNIQUE `ticker`), para el panel de concentración del book (V2b, desde el 2026-07-08). Una fila con sector NULL/"N/A" es un resultado negativo cacheado, para no re-scrapear. |
| `failed_tickers` | Tickers que fallan en Yahoo (`status`: failing/retry) para saltarlos. |

## Catalyst Engine — append-only point-in-time (`database/models.py`)

### `news_events` — noticias crudas
Append-only: una fila por (noticia, fuente) **observada**. `id`, `ticker`, `title`, `content`, `source` ("yfinance"/"sec_8k"/"finnhub:*"; la rama `rss` se borró en la tarea 212 y **cero** filas la usaban), `url`, `published_at` (declara la fuente), **`fetched_at`** (cuándo LO VIMOS), `content_hash` (sha1 UNIQUE → idempotencia).
Campos de clasificación (NULL hasta T-CAT-2, UPDATE in-place): `event_type`, `sentiment`, `classifier_confidence`, `classified_at`, `classified_by` ("heuristic"/"ollama"/"llm"/"fallback"; desde la tarea 259, 2026-10-03, "ollama-7n"/"llm-7n" = el LLM calificó el tono en 7 niveles y `sentiment_score` es `nivel/3` — las filas anteriores tienen la polaridad agrupada en 4 valores y quedan así).

### `analyst_estimate_snapshots` — consenso diario
Append-only: ≤1 fila por (ticker, metric, period_label, día). Es lo que permite leer el consenso **tal como estaba el día antes del earnings** (base del surprise score / T-CAT-5b). `id`, `ticker`, `metric` ("eps"/"revenue"/"rec_mean"/"price_target"), `period_label` ("0q"/"+1q"/"0y"/"+1y" o "2026-09"), `consensus_value`, `num_analysts`, `snapshot_date` (medianoche), `fetched_at`.
→ Lo acumula el harvester diario. Aún sin datos suficientes para T-CAT-5b (~fines jul 2026).
