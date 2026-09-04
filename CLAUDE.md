# CLAUDE.md — FinanzIAs

App de escritorio de paper-trading y análisis cuantitativo. **Python + PyQt6 + SQLite + yfinance.** El dueño, Chapa, trabaja en **español rioplatense** — comunicate en español.

## Reglas no-negociables

1. **"Done" = los TRES comandos en verde, en Windows.** Entorno real: Windows + Anaconda. Antes de declarar terminado:
   `python -m pytest tests/ -ra -m "not network" --tb=short` · `python -m ruff check .` · `python -m ruff format --check .`
   Los tests `network` pegan a Yahoo de verdad y se saltean. `tests/conftest.py` bloquea red en unit tests.
   **Ruff entra el 2026-09-03 (tarea 106):** el done era la suite sola, el job `lint` del CI quedó en rojo el 2026-09-02 y **trece tareas se cerraron declarando "suite verde"** sin enterarse. La suite estaba verde; el criterio estaba incompleto.
2. **Kill-criteria upfront.** Toda feature que toque decisiones de trading define umbral de aceptación ANTES de codear y se valida con backtest/replay. Si no pasa, se documenta y NO se shipea. Sin features especulativas.
3. **Display antes que sizing.** Scoring/valuación nuevos entran como display-only, NO cableados a sizing ni gates, hasta backtestear. **La regla no depende de ningún coeficiente** — su fundamento es no cablear lo que no se backtesteó. La evidencia que se citaba se **re-midió el 2026-09-01** (tarea 73): `corr(buy_score, fwd5) = −0.05`, n=85, IC95% [−0.26, +0.17]. **No se detecta relación, pero eso no alcanza para afirmar que no predice**: la muestra sólo descarta |r| > 0.30, y el claim original lo afirmaba con n=21, que sólo detectaba 0.58. Ver `docs/buyscore_fwd5_t73_2026-09-01.md`.
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

**El backlog tiene un guard (tarea 66): editalo, no lo reescribas.** El 2026-08-31 un commit de cierre le borró **767 líneas** —todas las tareas y cinco secciones— y pasó invisible cuatro commits, porque el archivo truncado se lee entero como un backlog válido. Ahora `scripts/check_backlog_integrity.py` corre en **dos** lugares, y hay que saber cuál es cuál (tarea 97): la mitad que se ve leyendo el archivo —secciones obligatorias declaradas por el propio header, ninguna vacía, todo *«la próxima es la NN»* apuntando a una tarea que existe— corre **sola, en la suite**; la mitad que **necesita el diff** —frena un commit que le saque más de 60 líneas netas— corre con `--staged` en el **paso 3a de `/ship`**, o sea que **depende de que alguien la corra**. Estuvo declarada en `.pre-commit-config.yaml` desde el 2026-09-01 sin ejecutarse ni una vez, porque en este repo **no hay ningún hook de git instalado**. **Si se renombra o agrega una sección, se actualiza la lista en el header del backlog.**

## Documentación de referencia

- `docs/BACKLOG.md` — tareas operativas (el qué sigue).
- `docs/ARCHITECTURE.md` — flujo de datos y módulos.
- `docs/SETTINGS_REFERENCE.md` — todos los flags `paper_*`/engine con defaults.
- `docs/DB_SCHEMA.md` — dicc