# Tests

## Quick start

El *done* del proyecto son **cuatro comandos en verde, en Windows** (ver `CLAUDE.md`, regla 1),
y `/test` los corre con el intérprete correcto (Anaconda):

```powershell
python -m pytest tests/ -ra -m "not network" --tb=short
python -m ruff check .
python -m ruff format --check .
python scripts/run_suite_sin_estado_vivo.py   # la suite en la condición del CI: HOME vacío
```

## What's covered

Casi todo el código de la app, con un archivo de test por módulo o por tarea
(`test_<tema>_t<NNN>.py` cuando nace de una tarea del backlog). Acá había una tabla de ocho
archivos, de mayo de 2026, que había quedado muy corta (tarea 252); para la lista de hoy:

```powershell
python -m pytest tests/ --collect-only -q
```

## Fixtures

- `test_db` — drops in an in-memory SQLite via monkeypatching
  `database.models.{ENGINE, SessionLocal}`. Re-creates all tables (incl.
  `paper_trading.models`) at start, drops them at teardown.
- `mock_yfinance` — replaces `data.yahoo_finance.yf` with a `MagicMock` so
  no network calls happen.
- `ohlcv_factory` — deterministic synthetic OHLCV with seed.
- `_disable_settings_persistence` — autouse; redirects `~/.finanzias/`
  config to `tmp_path` so tests don't pollute the host.

## Marks

`@pytest.mark.network` marca los tests que pegan a la red de verdad; se excluyen con
`-m "not network"`. Al 2026-10-01 hay **uno**, y no pega a nada:
`test_cortafuegos_subproceso_t211.py::test_un_test_MARCADO_no_le_pasa_el_corte_a_su_hijo`, marcado
porque lo que prueba es el escape del marcador — es el `1 deselected` de cada corrida. Acá decía
que no había ninguno (tarea 252). Desde la tarea 209 el autouse `_cortafuegos_de_red` de
`conftest.py` **corta** la red en todo test sin el marcador, así que olvidarse de marcar uno no
sale a internet: falla.

## Notes / known issues

- `pytest-qt` is listed in `requirements-dev.txt` for future Qt-event-loop
  tests but the current suite doesn't need it.
- The codebase computes RSI/MACD/Bollinger/SMA/EMA with **pure pandas**
  (no `pandas-ta` dependency) — `analysis/technical.py` uses
  ``Series.ewm`` / ``Series.rolling`` directly. So the test suite has no
  external indicator-library prerequisite beyond ``pandas`` and ``numpy``.
