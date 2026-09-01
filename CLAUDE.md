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
6. **Todo hallazgo se anota como tarea.** Cualquier defecto que aparezca durante un análisis, auditoría, backtest o review —bug, desvío harness↔engine, supuesto falso, número que no cierra— entra como **tarea en `docs/BACKLOG.md`** antes de cerrar lo que se estaba haciendo, aunque no sea el tema de la tarea en curso y aunque sea chico. Nada de arreglar en silencio ni de dejarlo sólo en un doc. Ver skill `hallazgo-a-backlog`.

## Cómo correr

- App: `python main.py`
- Tests: `python -m pytest tests/ -ra -m "not network" --tb=short`
- Harvest de catalysts: `python scripts/harvest_catalysts.py` (ver skill `catalyst-pipeline`). **Sin `--account-id`**: desde la tarea 70 el default es la cuenta **viva**, resuelta contra `is_active`. Decía `--account-id 1` y esa cuenta está pausada, así que recolectaba para 52 tickers en vez de 128.

## Mapa rápido

- `paper_trading/` — motor de decisiones (`engine.py` → `run_scan` con gates), cuentas, estrategias, costos. **Cuenta activa: "Sim Segundo" (id=2)** — `auto`, `equal_weight`, `max_positions=10`. La **cuenta 1 ("Sim Principal") está pausada** (`is_active=0`) desde 2026-07-01: toda verificación en vivo va contra la 2. Flags de modelo en **kill_only** (hmm/stacking OFF).
- `analysis/` — technical, metrics_panel, leads, impact_score, surprise_score, exit_replay.
- `data/` — `yahoo_finance.py` (con cache + batch + retry), `news_sources.py`.
- `database/models.py` + `paper_trading/models.py` — esquema SQLite (alembic).
- `ui/` — PyQt6, tema oscuro. `scripts/` — harness, harvest, mantenimiento. `docs/` — diseño, auditorías, roadmap.

## Backlog

**Al empezar una sesión, leé `docs/BACKLOG.md`** (qué sigue, priorizado). Al cerrar una tarea (suite Windows verde + commit) movela a *Hecho reciente* con el hash. *En curso* máximo 1 ítem.

**El backlog tiene un guard (tarea 66): editalo, no lo reescribas.** El 2026-08-31 un commit de cierre le borró **767 líneas** —todas las tareas y cinco secciones— y pasó invisible cuatro commits, porque el archivo truncado se lee entero como un backlog válido. Ahora `scripts/check_backlog_integrity.py` corre en la suite y en `pre-commit`: verifica que estén las secciones que el propio header declara obligatorias, que ninguna quede vacía, que todo *«la próxima es la NN»* apunte a una tarea que existe, y frena un commit que le saque más de 60 líneas netas. **Si se renombra o agrega una sección, se actualiza la lista en el header del backlog.**

## Documentación de referencia

- `docs/BACKLOG.md` — tareas operativas (el qué sigue).
- `docs/ARCHITECTURE.md` — flujo de datos y módulos.
- `docs/SETTINGS_REFERENCE.md` — todos los flags `paper_*`/engine con defaults.
- `docs/DB_SCHEMA.md` — dicc