# Tests

## Quick start

```powershell
# minimal run (existing FinanzIAs venv)
pip install pytest
pytest tests/

# full dev install (recommended for repeat runs)
pip install -r requirements-dev.txt
pytest tests/ -ra
```

## What's covered

| File                    | Module under test                       |
|-------------------------|-----------------------------------------|
| `test_database.py`      | `database/models.py` (cascades, indexes, `session_scope`) |
| `test_indicators.py`    | `analysis/technical.py` (RSI, MACD, Bollinger, SMA, EMA) |
| `test_data_quality.py`  | `data/quality.py` (NaN, gaps, zero prices) |
| `test_settings.py`      | `config/settings_manager.py` (schema validation) |
| `test_validators.py`    | `ui/validators.py` (ticker validator + locale-aware decimals) |
| `test_backtest.py`      | `analysis/backtest.py` (no-lookahead, cost tracking) |
| `test_costs.py`         | `paper_trading/costs.py` (commission/slippage models) |
| `test_rate_limiter.py`  | `data/market_data_service.py` token-bucket |

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

Tests marked `@pytest.mark.network` hit real Yahoo Finance and are
excluded in CI (`pytest -m "not network"`). None are marked yet — add
the marker to any new tests that go to the network.

## Notes / known issues

- `pytest-qt` is listed in `requirements-dev.txt` for future Qt-event-loop
  tests but the current suite doesn't need it.
- The codebase computes RSI/MACD/Bollinger/SMA/EMA with **pure pandas**
  (no `pandas-ta` dependency) — `analysis/technical.py` uses
  ``Series.ewm`` / ``Series.rolling`` directly. So the test suite has no
  external indicator-library prerequisite beyond ``pandas`` and ``numpy``.
