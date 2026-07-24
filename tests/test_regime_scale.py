"""
Tests del cableado de R2b (tarea 20) — escalado de exposición por régimen.

Cubre el helper ``_regime_size_factor`` (detector SPY/SMA200, PIT sobre el último
close, con fail-open) y su integración en ``generate_trades_analyze_single``
(las BUYs nuevas entran a fracción del tamaño en risk-off; nunca las tenidas).
``analyze()`` se monkeypatchea para que los tests sean rápidos y deterministas.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import numpy as np
import pytest

from config.settings_manager import settings
from paper_trading.strategies import (
    _regime_size_factor,
    generate_trades_analyze_single,
)


def _spy_df(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=len(closes), freq="B")
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes}, index=idx)


# 260 barras: declinante ⇒ último close bajo la SMA200 (risk-off); creciente ⇒ risk-on.
_SPY_OFF = _spy_df([300.0 - i * 0.5 for i in range(260)])
_SPY_ON = _spy_df([100.0 + i * 0.5 for i in range(260)])


def _series(daily_vol: float, rows: int = 120, seed: int = 0, start: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, daily_vol, rows)
    close = start * np.exp(np.cumsum(rets))
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=rows, freq="B")
    return pd.DataFrame({"Close": close}, index=idx)


def _account(**overrides):
    base = dict(cash=100_000.0, max_positions=5, allocation_mode="equal_weight",
                fixed_amount=5_000.0, commission=0.0)
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_analyze(monkeypatch, table):
    import analysis.technical as technical

    def fake_analyze(ticker, df, *a, **k):
        if ticker not in table:
            return None
        sig, prob = table[ticker]
        return SimpleNamespace(overall_signal=sig, ml_probability=prob)

    monkeypatch.setattr(technical, "analyze", fake_analyze)


# ── helper _regime_size_factor ───────────────────────────────────────────────
def test_regime_factor_risk_off_returns_configured_factor():
    settings.set("paper_regime_scale_enabled", True)
    settings.set("paper_regime_scale_factor", 0.5)
    assert _regime_size_factor(lambda t: _SPY_OFF if t == "SPY" else None) == pytest.approx(0.5)


def test_regime_factor_risk_on_is_full_size():
    settings.set("paper_regime_scale_enabled", True)
    assert _regime_size_factor(lambda t: _SPY_ON if t == "SPY" else None) == 1.0


def test_regime_factor_disabled_is_full_size():
    settings.set("paper_regime_scale_enabled", False)
    assert _regime_size_factor(lambda t: _SPY_OFF if t == "SPY" else None) == 1.0


def test_regime_factor_failopen_without_spy():
    settings.set("paper_regime_scale_enabled", True)
    assert _regime_size_factor(lambda _t: None) == 1.0


def test_regime_factor_failopen_short_history():
    settings.set("paper_regime_scale_enabled", True)
    short = _spy_df([200.0 - i for i in range(50)])  # < 200 barras → sin SMA
    assert _regime_size_factor(lambda t: short if t == "SPY" else None) == 1.0


# ── integración en generate_trades_analyze_single ────────────────────────────
def test_analyze_single_scales_buys_in_risk_off(monkeypatch):
    settings.set("paper_regime_scale_enabled", True)
    settings.set("paper_regime_scale_factor", 0.5)
    _patch_analyze(monkeypatch, {"AAA": ("BUY", 0.60)})
    buy_df = _series(0.02, seed=1)

    def hp_off(t):
        return {"AAA": buy_df, "SPY": _SPY_OFF}.get(t)

    def hp_on(t):
        return {"AAA": buy_df, "SPY": _SPY_ON}.get(t)

    t_off = generate_trades_analyze_single(_account(), ["AAA"], [], {"AAA": 100.0}, hp_off)
    t_on = generate_trades_analyze_single(_account(), ["AAA"], [], {"AAA": 100.0}, hp_on)
    d_off = next(tr.target_dollars for tr in t_off if tr.ticker == "AAA")
    d_on = next(tr.target_dollars for tr in t_on if tr.ticker == "AAA")
    assert d_off == pytest.approx(0.5 * d_on, rel=1e-6)
    assert "risk-off" in next(tr.reason for tr in t_off if tr.ticker == "AAA")


def test_analyze_single_no_scaling_when_disabled(monkeypatch):
    settings.set("paper_regime_scale_enabled", False)
    _patch_analyze(monkeypatch, {"AAA": ("BUY", 0.60)})
    buy_df = _series(0.004, seed=1)  # vol baja → el vol-overlay (T10) no trimea

    def hp(t):
        return {"AAA": buy_df, "SPY": _SPY_OFF}.get(t)

    trades = generate_trades_analyze_single(_account(), ["AAA"], [], {"AAA": 100.0}, hp)
    tr = next(t for t in trades if t.ticker == "AAA")
    assert tr.target_dollars == pytest.approx(100_000.0)  # equal-weight, 1 pick, sin escalar
    assert "risk-off" not in tr.reason
