"""
Tests del detector de régimen de mercado — Tarea 8 (R2).

Pre-registro: docs/market_regime_gate_r2_2026-07-20.md §3 (definición congelada).
Todo sintético/offline.

Cubre:
  build_regime_series — SMA200, fail-open antes del warmup, rachas
  is_risk_off        — point-in-time en D−1 (NO mira el close de D), confirm_days
  make_entry_filter  — los 4 modos pre-registrados + modo desconocido
  datos rotos        — NaN/cero no rompen la serie
"""

from __future__ import annotations

import pytest

from analysis.market_regime import (
    SMA_WINDOW,
    build_regime_series,
    make_entry_filter,
)


def _d(i: int) -> str:
    """Calendario sintético ordenable: 2020-01-01 + i días (sin pretender ser hábil)."""
    from datetime import date, timedelta

    return (date(2020, 1, 1) + timedelta(days=i)).isoformat()


def _bars(closes: list[float]) -> list:
    return [(_d(i), c, c, c, c) for i, c in enumerate(closes)]


# ── build_regime_series ──────────────────────────────────────────────────────


def test_fail_open_before_sma_is_available():
    """Sin 200 closes no hay SMA → risk-on (nunca bloquea por falta de datos)."""
    s = build_regime_series(_bars([100.0] * 50))
    assert all(x is False for x in s.risk_off)


def test_price_above_sma_is_risk_on():
    # rampa creciente: el precio siempre queda por encima de su media móvil
    s = build_regime_series(_bars([100.0 + i for i in range(SMA_WINDOW + 50)]))
    assert s.risk_off[-1] is False


def test_price_below_sma_is_risk_off():
    # 250 días planos y después un desplome: queda debajo de la SMA200
    closes = [100.0] * SMA_WINDOW + [50.0] * 20
    s = build_regime_series(_bars(closes))
    assert s.risk_off[-1] is True


def test_streak_counts_consecutive_risk_off_days():
    closes = [100.0] * SMA_WINDOW + [50.0] * 7
    s = build_regime_series(_bars(closes))
    assert s.streak[-1] == 7
    assert s.streak[-3] == 5


def test_streak_resets_when_back_above():
    closes = [100.0] * SMA_WINDOW + [50.0] * 5 + [300.0]
    s = build_regime_series(_bars(closes))
    assert s.risk_off[-1] is False
    assert s.streak[-1] == 0


def test_broken_close_does_not_break_the_series():
    closes = [100.0] * SMA_WINDOW + [50.0] * 3
    bars = _bars(closes)
    bars.insert(len(bars) - 1, (_d(999), 0.0, 0.0, 0.0, 0.0))  # close cero
    s = build_regime_series(bars)
    assert len(s.dates) == len(bars)  # no se pierde ninguna fecha


# ── is_risk_off: point-in-time ───────────────────────────────────────────────


def test_is_risk_off_uses_previous_day_not_the_entry_day():
    """PIT: la consulta para el día D mira el cierre de D−1, nunca el de D.

    Se arma una serie que está risk-ON hasta cierto día y risk-OFF a partir del
    siguiente; consultar el primer día risk-off debe devolver False (porque D−1
    todavía era risk-on).
    """
    closes = [100.0] * SMA_WINDOW + [300.0] + [10.0] * 5
    s = build_regime_series(_bars(closes))
    first_off_idx = next(i for i, x in enumerate(s.risk_off) if x and i > SMA_WINDOW)
    date_first_off = s.dates[first_off_idx]
    # consultado EN el día del flip: D−1 aún era risk-on ⇒ False
    assert s.is_risk_off(date_first_off) is False
    # consultado al día siguiente: ahora sí
    assert s.is_risk_off(s.dates[first_off_idx + 1]) is True


def test_is_risk_off_fails_open_before_history():
    s = build_regime_series(_bars([100.0] * (SMA_WINDOW + 5)))
    assert s.is_risk_off("1990-01-01") is False


def test_confirm_days_requires_a_streak():
    closes = [100.0] * SMA_WINDOW + [50.0] * 10
    s = build_regime_series(_bars(closes))
    # 3 días después del flip, consultando el 4º
    idx = next(i for i, x in enumerate(s.risk_off) if x and i > SMA_WINDOW)
    d3 = s.dates[idx + 3]
    assert s.is_risk_off(d3, confirm_days=1) is True
    assert s.is_risk_off(d3, confirm_days=3) is True
    assert s.is_risk_off(d3, confirm_days=9) is False


# ── make_entry_filter ────────────────────────────────────────────────────────


@pytest.fixture
def series_off():
    """Serie que está en risk-off sostenido al final."""
    return build_regime_series(_bars([100.0] * SMA_WINDOW + [50.0] * 10))


def test_filter_off_never_blocks(series_off):
    f = make_entry_filter(series_off, mode="off")
    assert f("AAPL", series_off.dates[-1]) == 1.0


def test_filter_hard_blocks_in_risk_off(series_off):
    f = make_entry_filter(series_off, mode="hard")
    assert f("AAPL", series_off.dates[-1]) == 0.0
    assert f("AAPL", series_off.dates[10]) == 1.0  # antes del warmup: fail-open


def test_filter_half_halves_size_in_risk_off(series_off):
    f = make_entry_filter(series_off, mode="half")
    assert f("AAPL", series_off.dates[-1]) == 0.5


def test_filter_confirm_waits_for_the_streak(series_off):
    f = make_entry_filter(series_off, mode="confirm", confirm_days=5)
    idx = next(i for i, x in enumerate(series_off.risk_off) if x and i > SMA_WINDOW)
    assert f("AAPL", series_off.dates[idx + 1]) == 1.0  # racha corta todavía
    assert f("AAPL", series_off.dates[-1]) == 0.0  # racha larga


def test_unknown_mode_raises():
    s = build_regime_series(_bars([100.0] * 10))
    with pytest.raises(ValueError, match="desconocido"):
        make_entry_filter(s, mode="inventado")


def test_sma_window_is_the_preregistered_one():
    """La definición está congelada en el pre-registro: 200 ruedas, sin sweep."""
    assert SMA_WINDOW == 200
