# CLAUDE.md — FinanzIAs

App de escritorio de paper-trading y análisis cuantitativo. **Python + PyQt6 + SQLite + yfinance.** El dueño, Chapa, trabaja en **español rioplatense** — comunicate en español.

## Reglas no-negociables

1. **"Done" = suite verde en Windows.** Entorno real: Windows + Anaconda. Antes de declarar terminado:
   `python -m pytest tests/ -ra -m "not network" --tb=short`
   Los tests `network` pegan a Yahoo de verdad y se saltean. `tests/conftest.py` bloquea red en unit tests.
2. **Kill-criteria upfront.** Toda feature que toque decisiones de trading define umbral de aceptación ANTES de codear y se valida con backtest/replay. Si no pasa, se documenta y NO se shipea. Sin features especulativas.
3. **Display antes que sizing.** Scoring/valuación nuevos entran como display-only, NO cableados a sizing ni gates, hasta backtestear. (`buy_score` no predice el fwd5 — auditoría 2026-06-17.)
4. **`.bat` requieren CRLF** o `cmd.exe` los mata en silencio. Escribir con CRLF binario y verificar.
5. **No escribir `finanzias.db` desde Linux/sandbox** — corrupción intermitente vía mounts. Leer copiando a /tmp primero. Backups en `backups/`.

## Cómo correr

- App: `python main.py`
- Tests: `python -m pytest tests/ -ra -m "not network" --tb=short`
- Harvest de catalysts: `python scripts/harvest_catalysts.py --account-id 1` (ver skill `catalyst-pipeline`)

## Mapa rápido

- `paper_trading/` — motor de decisiones (`engine.py` → `run_scan` con gates), cuentas, estrategias, costos. **Cuenta activa: "Sim Segundo" (id=2)** — `auto`, `equal_weight`, `max_positions=10`. La **cuenta 1 ("Sim Principal") está pausada** (`is_active=0`) desde 2026-07-01: toda verificación en vivo va contra la 2. Flags de modelo en **kill_only** (hmm/stacking OFF).
- `analysis/` — technical, metrics_panel, leads, impact_score, surprise_score, exit_replay.
- `data/` — `yahoo_finance.py` (con cache + batch + retry), `news_sources.py`.
- `database/models.py` + `paper_trading/models.py` — esquema SQLite (alembic).
- `ui/` — PyQt6, tema oscuro. `scripts/` — harness, harvest, mantenimiento. `docs/` — diseño, auditorías, roadmap.

## Backlog

**Al empezar una sesión, leé `docs/BACKLOG.md`** (qué sigue, priorizado). Al cerrar una tarea (suite Windows verde + commit) movela a *Hecho reciente* con el hash. *En curso* máximo 1 ítem.

## Documentación de referencia

- `docs/BACKLOG.md` — tareas operativas (el qué sigue).
- `docs/ARCHITECTURE.md` — flujo de datos y módulos.
- `docs/SETTINGS_REFERENCE.md` — todos los flags `paper_*`/engine con defaults.
- `docs/DB_SCHEMA.md` — dicc