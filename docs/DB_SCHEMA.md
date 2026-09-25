# Diccionario de la DB — FinanzIAs

SQLite (`finanzias.db`), SQLAlchemy. Esquema en `database/models.py` (general) y `paper_trading/models.py` (paper_*). Migraciones por **alembic** (`init_db` → `_alembic_sync`, ver `docs/schema_management.md`).

> **No escribir la DB desde Linux/sandbox** (corrupción intermitente). Leer copiando a /tmp primero. Backups en `backups/`.

## Paper trading (`paper_trading/models.py`)

### `paper_accounts` — cuentas de simulación
`id`, `name` (unique), `strategy` (def `analyze_single`), `mode` (`auto`/`manual`), `allocation_mode`, `max_positions` (5), `initial_capital` (50k), `cash`, `commission` (0.001), `slippage` (0.0005), `drift_threshold`, `monthly_rebalance`, `is_active`, `last_scan_at`, `slack_notify`.
→ **Cuenta activa: "Sim Principal" (id=1)**, modo kill_only.

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

Las tres columnas de monto se guardan aunque `cash = shares × amount_per_share`: el ledger tiene que poder auditarse sin re-derivar nada desde un calendario que para entonces pudo cambiar de fila. **Sólo hacia adelante**: la tabla arranca vacía y el motor acredita desde el primer ex-date de la ventana `(último scan, hoy]`, así que los $322,77 que la cuenta 2 ya había devengado **no** se backfillean y ninguna métrica publicada cambia de base.

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
| `failed_tickers` | Tickers que fallan en Yahoo (`status`: failing/retry) para saltarlos. |

## Catalyst Engine — append-only point-in-time (`database/models.py`)

### `news_events` — noticias crudas
Append-only: una fila por (noticia, fuente) **observada**. `id`, `ticker`, `title`, `content`, `source` ("yfinance"/"sec_8k"/"finnhub:*"; la rama `rss` se borró en la tarea 212 y **cero** filas la usaban), `url`, `published_at` (declara la fuente), **`fetched_at`** (cuándo LO VIMOS), `content_hash` (sha1 UNIQUE → idempotencia).
Campos de clasificación (NULL hasta T-CAT-2, UPDATE in-place): `event_type`, `sentiment`, `classifier_confidence`, `classified_at`, `classified_by` ("heuristic"/"ollama"/"llm"/"fallback").

### `analyst_estimate_snapshots` — consenso diario
Append-only: ≤1 fila por (ticker, metric, period_label, día). Es lo que permite leer el consenso **tal como estaba el día antes del earnings** (base del surprise score / T-CAT-5b). `id`, `ticker`, `metric` ("eps"/"revenue"/"rec_mean"/"price_target"), `period_label` ("0q"/"+1q"/"0y"/"+1y" o "2026-09"), `consensus_value`, `num_analysts`, `snapshot_date` (medianoche), `fetched_at`.
→ Lo acumula el harvester diario. Aún sin datos suficientes para T-CAT-5b (~fines jul 2026).
