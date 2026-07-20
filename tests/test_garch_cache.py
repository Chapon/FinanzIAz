import numpy as np
import pandas as pd

from analysis import garch_signals


class _DummyResult:
    def __init__(self):
        self.convergence_flag = 0
        self.conditional_volatility = pd.Series([0.01] * 3, index=pd.RangeIndex(3))
        self.params = {"omega": 0.01, "alpha[1]": 0.1, "beta[1]": 0.2}

    def forecast(self, horizon=1, reindex=False):
        class _Forecast:
            variance = pd.DataFrame([[0.01]], index=[0], columns=[0])

        return _Forecast()


class _DummyModel:
    def __init__(self, returns, **kwargs):
        self.returns = returns

    def fit(self, disp="off", show_warning=False):
        return _DummyResult()


def _make_df() -> pd.DataFrame:
    idx = pd.date_range("2020-01-02", periods=140, freq="B")
    close = 100.0 + np.cumsum(np.linspace(0.01, 0.6, len(idx)))
    return pd.DataFrame({"Close": close}, index=idx)


def test_fit_garch_forecast_reuses_cached_result_for_identical_frame(monkeypatch):
    calls = []

    def fake_arch_model(returns, **kwargs):
        calls.append(returns.shape[0])
        return _DummyModel(returns, **kwargs)

    monkeypatch.setattr(garch_signals, "_ARCH_OK", True)
    monkeypatch.setattr(garch_signals, "arch_model", fake_arch_model)
    monkeypatch.setattr(garch_signals, "_GARCH_FORECAST_CACHE", {})

    df = _make_df()
    first = garch_signals.fit_garch_forecast(df, ticker="AAPL")
    second = garch_signals.fit_garch_forecast(df, ticker="AAPL")

    assert first is not None
    assert second is not None
    assert first is second
    assert len(calls) == 1
