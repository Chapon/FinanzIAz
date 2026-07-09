"""Test del hook ``breaker_fn`` de portfolio_backtest (R1 harness hook).

El hook suprime SOLO las entradas nuevas cuando devuelve True; None o un hook
que siempre devuelve False deben reproducir el comportamiento legacy exacto.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.portfolio_backtest import AllocationMode, portfolio_backtest


def _ramp_df(n: int, start: float, slope: float) -> pd.DataFrame:
    """OHLCV sintético que sube linealmente (sin ruido → determinista)."""
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    close = np.array([start + slope * k for k in range(n)], dtype=float)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


def _always_buy(_df: pd.DataFrame) -> str:
    return "BUY"


def _data() -> dict[str, pd.DataFrame]:
    return {
        "AAA": _ramp_df(150, 100.0, 0.5),
        "BBB": _ramp_df(150, 50.0, 0.3),
        "CCC": _ramp_df(150, 20.0, 0.2),
    }


_KW = dict(
    tickers=["AAA", "BBB", "CCC"],
    allocation_mode=AllocationMode.EQUAL_WEIGHT,
    max_positions=2,
    initial_capital=50_000.0,
    warmup=50,
    step=5,
)


def test_breaker_none_matches_always_false():
    """None y un hook que nunca arma dan resultados idénticos (legacy)."""
    r_none = portfolio_backtest(_always_buy, data=_data(), breaker_fn=None, **_KW)
    r_false = portfolio_backtest(
        _always_buy, data=_data(), breaker_fn=lambda *_: False, **_KW
    )
    assert r_none is not None and r_false is not None
    assert r_none.final_equity == r_false.final_equity
    assert r_none.n_trades == r_false.n_trades
    assert r_none.n_slot_fills == r_false.n_slot_fills
    assert r_false.n_breaker_suppressed == 0


def test_breaker_always_on_suppresses_all_entries():
    """Con el breaker siempre armado no se abre ninguna posición nueva."""
    r_on = portfolio_backtest(
        _always_buy, data=_data(), breaker_fn=lambda *_: True, **_KW
    )
    r_off = portfolio_backtest(_always_buy, data=_data(), breaker_fn=None, **_KW)
    assert r_off.n_slot_fills > 0  # sanity: sin breaker sí entra
    assert r_on.n_slot_fills == 0
    assert r_on.n_trades == 0
    assert r_on.n_breaker_suppressed > 0
    # Sin operar, el equity queda plano en el capital inicial.
    assert r_on.final_equity == 50_000.0


def test_breaker_receives_equity_and_date():
    """El hook recibe (date, portfolio_val, equity_so_far) con tipos usables."""
    seen: list[tuple] = []

    def spy(date, val, eq):
        seen.append((date, val, eq))
        return False

    portfolio_backtest(_always_buy, data=_data(), breaker_fn=spy, **_KW)
    assert seen  # se llamó al menos una vez (hubo candidatos)
    date, val, eq = seen[0]
    assert isinstance(date, pd.Timestamp)
    assert isinstance(val, float) and val > 0
    assert isinstance(eq, pd.Series)
