# Arquitectura — FinanzIAs

Mapa del flujo de datos y responsabilidades de cada paquete. Para reglas de trabajo ver `CLAUDE.md` y la skill `finanzias-conventions`.

## Flujo de datos (de Yahoo a la orden)

```
yfinance ──> data/yahoo_finance.py ──> historical_data_cache (SQLite)
                  │  (batch download, 1 crumb/chunk, retry 401, WAL)
                  ▼
            analysis/technical.py  ──>  señal técnica + XGBoost + vol_overlay
                  │
                  ▼
   paper_trading/engine.py :: run_scan(account)
                  │  arma universo (watchlist ∪ posiciones) → warm-up de cache batch
                  │  por ticker: estrategia → propone BUY/SELL
                  ▼
            GATES (paper_trading/gates.py + engine.py)   ← filtran/trimean
                  │
                  ▼
            paper_orders (status: pending → approved → filled)
                  │  auto-fill (mode=auto) o aprobación manual en UI
                  ▼
       paper_positions  +  paper_equity_snapshots
                  │
                  ▼
                ui/ (PyQt6): Portfolio, Analysis, Leads, Noticias, Métricas, ...
```

## Paquetes

### `paper_trading/` — el motor
- `engine.py` — `run_scan` (el corazón: propone órdenes y aplica los gates), `approve_order` (re-aplica Gates 1+6), `reconcile_account` (barre limbo). Ver la cadena de gates en `finanzias-conventions`.
- `gates.py` — helpers de los gates (ADV cap, anti-whipsaw, fill model `model_exit_fill_price`, etc.).
- `strategies.py` — estrategias de señal (`analyze_single`, etc.). `account.py` — operaciones de cuenta/posición. `costs.py` — comisiones IBKR + slippage. `scheduler.py` — scan en background (QTimer). `models.py` — tablas paper_*. `feature_switch.py` — dead-code de switches por régimen.

### `analysis/` — cálculo
- `technical.py` (`analyze`: RSI/MACD/Bollinger/GARCH + XGBoost), `metrics_panel.py` (efectividad del modelo, round-trips FIFO), `leads.py` (ranking SP500 por consenso), `impact_score.py` (Impact Score + exit-veto T-CAT-4), `surprise_score.py` (prior direccional EPS), `exit_replay.py` (infra de backtest de exits), `catalyst_reaction.py` (forward returns por evento).

### `data/` — ingest
- `yahoo_finance.py` — precios (single + `get_historical_data_batch`), `get_company_info`, `get_analyst_data` (price targets + recos), earnings. Cache en SQLite, timeout-guard, retry de 401.
- `news_sources.py` — collectors de noticias (yfinance, SEC 8-K/EDGAR, RSS, Finnhub) para el Catalyst Engine.

### `database/` + esquema
- `database/models.py` (portfolios, caches, news_events, analyst_estimate_snapshots) y `paper_trading/models.py` (paper_*). SQLite con **WAL + busy_timeout**. Migraciones por **alembic** (`init_db` → `_alembic_sync`). Ver `docs/DB_SCHEMA.md` y `docs/schema_management.md`.

### `ui/` — PyQt6
- Tabs en `ui/` con patrón **worker en background + card**: cada tab tiene un `*Worker(BaseWorker)` que hace el fetch y emite `done(...)`, y la tab renderiza. Ejemplo: `ui/analysis/worker.py` + `ui/analysis_tab.py` + `ui/analysis/recommendations_card.py` (card silenciosa cuando faltan datos).

### `scripts/` — tooling
Harness de backtest (`run_exit_replay_t61.py`, `run_catalyst_exit_veto_backtest.py`, `harness_walkforward.py`), harvest de catalysts, builders (`build_surprise_profiles.py`, `build_historical_reaction.py`), mantenimiento. Ver skills `backtest-replay-harness` y `catalyst-pipeline`.

## Subsistemas transversales
- **Catalyst Engine (T-CAT)** — pipeline append-only de noticias → clasificación → señal. Ver skill `catalyst-pipeline`.
- **kill_only** — config activa: `hmm_enabled`/`stacking_enabled` forzados OFF; XGBoost y vol_overlay siempre ON. (Ojo: los *defaults* de SettingSpec dicen otra cosa; kill_only los pisa. Ver `docs/SETTINGS_REFERENCE.md`.)
