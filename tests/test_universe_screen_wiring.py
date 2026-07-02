"""
Tests de integración del screen E1b dentro de ``generate_trades_analyze_single``.

Verifican que:
  * con el master switch OFF (default) el loop de BUY no cambia y NO se toca EDGAR;
  * con el switch ON, un candidato con fundamentals frágiles queda fuera y uno
    sano entra (EDGAR mockeado — la suite bloquea red);
  * con el switch ON, la pata de liquidez descarta un ilíquido sin pegar a EDGAR.

Solo se filtran CANDIDATOS de BUY; las posiciones tenidas nunca pasan por acá.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from config.settings_manager import settings
from data.edgar_fundamentals import FundamentalFacts


def _df(close: float = 100.0, volume: float = 1_000_000, rows: int = 60, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, 0.01, rows)
    c = close * np.exp(np.cumsum(rets))
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=rows, freq="B")
    return pd.DataFrame({"Close": c, "Volume": np.full(rows, float(volume))}, index=idx)


def _account(**ov):
    base = dict(
        cash=100_000.0,
        max_positions=5,
        allocation_mode="signal_weighted",
        fixed_amount=5_000.0,
        commission=0.0,
        drift_threshold=0.25,
        monthly_rebalance=False,
        last_monthly_rebalance=None,
    )
    base.update(ov)
    return SimpleNamespace(**base)


def _patch_analyze(monkeypatch, buys: set[str]):
    import analysis.technical as technical

    def fake_analyze(ticker, df, *a, **k):
        if ticker in buys:
            return SimpleNamespace(overall_signal="BUY", ml_probability=0.6)
        return None

    monkeypatch.setattr(technical, "analyze", fake_analyze)


def _fragile(ticker="FRAG") -> FundamentalFacts:
    return FundamentalFacts(
        ticker=ticker,
        net_income_annual=(("2023-12-31", -5e7), ("2022-12-31", -4e7)),
        revenue_annual=(("2023-12-31", 2e6),),
    )


def _healthy(ticker="GOOD") -> FundamentalFacts:
    return FundamentalFacts(
        ticker=ticker,
        net_income_annual=(("2023-12-31", 1e8), ("2022-12-31", 9e7)),
        revenue_annual=(("2023-12-31", 5e8),),
    )


def _buys(trades) -> set[str]:
    return {tr.ticker for tr in trades if tr.side == "BUY"}


def test_screen_off_is_noop_and_never_hits_edgar(monkeypatch):
    from paper_trading.strategies import generate_trades_analyze_single

    # Master switch OFF (default). Si el screen se invocara, get_fundamental_facts
    # pegaría a la red y la suite lo bloquearía → el test fallaría. Que pase
    # prueba que OFF es no-op sin red.
    _patch_analyze(monkeypatch, {"FRAG", "GOOD"})
    dfs = {"FRAG": _df(seed=1), "GOOD": _df(seed=2)}

    trades = generate_trades_analyze_single(
        account=_account(),
        watchlist=["FRAG", "GOOD"],
        positions=[],
        prices={"FRAG": 100.0, "GOOD": 100.0},
        history_provider=lambda t: dfs.get(t),
    )
    assert _buys(trades) == {"FRAG", "GOOD"}


def test_screen_on_excludes_fragile_keeps_healthy(monkeypatch):
    from paper_trading.strategies import generate_trades_analyze_single

    settings.set("paper_universe_screen_enabled", True)  # fundamentals leg on by default

    _patch_analyze(monkeypatch, {"FRAG", "GOOD"})
    facts = {"FRAG": _fragile(), "GOOD": _healthy()}
    import data.edgar_fundamentals as ef

    monkeypatch.setattr(ef, "get_fundamental_facts", lambda t, **k: facts[t])

    dfs = {"FRAG": _df(seed=1), "GOOD": _df(seed=2)}
    trades = generate_trades_analyze_single(
        account=_account(),
        watchlist=["FRAG", "GOOD"],
        positions=[],
        prices={"FRAG": 100.0, "GOOD": 100.0},
        history_provider=lambda t: dfs.get(t),
    )
    assert _buys(trades) == {"GOOD"}


def test_screen_on_adv_floor_excludes_illiquid(monkeypatch):
    from paper_trading.strategies import generate_trades_analyze_single

    settings.set("paper_universe_screen_enabled", True)
    settings.set("paper_universe_min_adv_dollars", 50_000_000.0)
    settings.set("paper_universe_fundamentals_enabled", False)  # aísla la pata de liquidez (sin EDGAR)

    _patch_analyze(monkeypatch, {"ILLQ", "LIQ"})
    # ILLQ: ~100 acciones/día × $100 ≈ $10k ADV$ < piso. LIQ: 1M × $100 = $100M > piso.
    dfs = {"ILLQ": _df(volume=100, seed=3), "LIQ": _df(volume=1_000_000, seed=4)}

    trades = generate_trades_analyze_single(
        account=_account(),
        watchlist=["ILLQ", "LIQ"],
        positions=[],
        prices={"ILLQ": 100.0, "LIQ": 100.0},
        history_provider=lambda t: dfs.get(t),
    )
    assert _buys(trades) == {"LIQ"}
