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

## Núcleo / caches (`database/models.py`)

| Tabla | Para qué |
|-------|----------|
| `portfolios` | Cartera real del usuario. |
| `positions` | Posiciones de la cartera real. |
| `transactions` | Transacciones (P&L). |
| `alerts` | Alertas de precio. |
| `price_cache` | Cache de precios actuales. |
| `dividend_cache` | Cache de dividendos. |
| `historical_data_cache` | OHLCV histórico cacheado (5y/10y precargados). Lo llena `get_historical_data[_batch]`. |
| `earnings_cache` | Fechas de earnings. |
| `analyst_data_cache` | Recos + price targets cacheados. |
| `failed_tickers` | Tickers que fallan en Yahoo (`status`: failing/retry) para saltarlos. |

## Catalyst Engine — append-only point-in-time (`database/models.py`)

### `news_events` — noticias crudas
Append-only: una fila por (noticia, fuente) **observada**. `id`, `ticker`, `title`, `content`, `source` ("yfinance"/"sec_8k"/"pr_rss"/"finnhub:*"), `url`, `published_at` (declara la fuente), **`fetched_at`** (cuándo LO VIMOS), `content_hash` (sha1 UNIQUE → idempotencia).
Campos de clasificación (NULL hasta T-CAT-2, UPDATE in-place): `event_type`, `sentiment`, `classifier_confidence`, `classified_at`, `classified_by` ("heuristic"/"ollama"/"llm"/"fallback").

### `analyst_estimate_snapshots` — consenso diario
Append-only: ≤1 fila por (ticker, metric, period_label, día). Es lo que permite leer el consenso **tal como estaba el día antes del earnings** (base del surprise score / T-CAT-5b). `id`, `ticker`, `metric` ("eps"/"revenue"/"rec_mean"/"price_target"), `period_label` ("0q"/"+1q"/"0y"/"+1y" o "2026-09"), `consensus_value`, `num_analysts`, `snapshot_date` (medianoche), `fetched_at`.
→ Lo acumula el harvester diario. Aún sin datos suficientes para T-CAT-5b (~fines jul 2026).
