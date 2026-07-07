"""Tests del harvest horario in-app (tarea 10) — gate puro ``hourly_harvest_due``.

La decisión de Chapa 2026-07-07: el harvest intradía corre SOLO con la app
abierta (rides el tick por minuto del PaperScheduler); Windows Task Scheduler
queda únicamente con el pipeline completo diario de las 15:00.
"""

from datetime import datetime, timedelta

from paper_trading.scheduler import hourly_harvest_due

NOW = datetime(2026, 7, 7, 15, 0, 0)


def _due(**overrides) -> bool:
    """Baseline: todo a favor → True. Cada test pisa un solo gate."""
    kwargs = dict(
        enabled=True,
        now=NOW,
        last=None,
        interval_min=60,
        hourly_worker_running=False,
        daily_worker_running=False,
        market_open=True,
    )
    kwargs.update(overrides)
    return hourly_harvest_due(**kwargs)


def test_baseline_all_clear_fires():
    assert _due() is True


def test_flag_off_blocks():
    assert _due(enabled=False) is False


def test_market_closed_blocks():
    assert _due(market_open=False) is False


def test_interval_not_elapsed_blocks():
    assert _due(last=NOW - timedelta(minutes=59)) is False


def test_interval_elapsed_fires():
    assert _due(last=NOW - timedelta(minutes=60)) is True


def test_first_run_of_the_day_fires_without_last():
    assert _due(last=None) is True


def test_hourly_worker_running_blocks():
    assert _due(hourly_worker_running=True) is False


def test_daily_refresh_running_blocks():
    # No solapar con el refresh diario (mismo pipeline, contención SQLite).
    assert _due(daily_worker_running=True) is False


def test_interval_floor_is_15_minutes():
    # interval_min=1 se eleva al piso de 15: a los 10 min NO dispara...
    assert _due(interval_min=1, last=NOW - timedelta(minutes=10)) is False
    # ...y a los 15 sí.
    assert _due(interval_min=1, last=NOW - timedelta(minutes=15)) is True
