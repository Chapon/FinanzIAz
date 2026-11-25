"""Tarea 464 — TAJADA-SECUENCIAL: las compras escaladas del mismo día, del mismo tamaño.

``simulate_portfolio`` le daba a cada candidato ``cash / free_slots`` sobre la caja que dejó el
anterior. Sin escalar, la tajada es la misma para todos. Con un factor < 1 —el régimen a ×0,25—
la caja que una compra no gasta agranda a la siguiente: con 10 lugares libres se invierte el
**54,5%** de la caja. El motor vivo (``generate_trades_analyze_single``, ``equal_weight``) les da
a todas las compras del scan ``available / len(picks)`` por el mismo factor: el **25%**. En la
cuenta 2, las tres compras del 2026-11-20 13:34 UTC (INTC, META, ACN) tienen el mismo
``target_dollars``, 972,40.

``tajada_del_dia=True`` corrige eso sin mover nada publicado:

1. Con 10 lugares y ×0,25 invierte el 25% de la caja, y el default sigue en el 54,5%.
2. **Sin ningún factor < 1, es idéntico bit a bit al default** (costos, salidas y días incluidos).
3. Paridad con el motor vivo sobre un caso fijo: el mismo tamaño por compra.

Los casos se eligieron donde las dos fórmulas **difieren** (varias compras escaladas el mismo
día): con un solo lugar libre coinciden, y un test ahí no fijaría nada.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from analysis.exit_replay import AtrParams
from analysis.harness_config import (
    LIVE_MAX_POSITIONS,
    LIVE_WATCHLIST_SIZE,
    HarnessConfig,
    announce,
    deviations_keyed,
)
from analysis.portfolio_sim import simulate_portfolio
from analysis.scaleout_replay import CostModel, ScaleOutParams
from config.settings_manager import settings
from paper_trading.strategies import generate_trades_analyze_single
from tests.test_regime_scale import _SPY_OFF, _account, _patch_analyze, _series

NO_COST = CostModel(commission=0.0, slippage=0.0)
NO_ATR = AtrParams(stop_mult=1e9, tp_mult=1e9, trail_enabled=False)


def _d(i: int) -> str:
    from datetime import date, timedelta

    return (date(2020, 1, 1) + timedelta(days=i)).isoformat()


def _flat(n: int = 40, close: float = 100.0) -> list:
    return [(_d(i), close, close, close, close) for i in range(n)]


def _sim(entries, bars_by, **kw):
    kw.setdefault("atr_p", NO_ATR)
    kw.setdefault("costs", NO_COST)
    kw.setdefault("so_params", ScaleOutParams())
    kw.setdefault("cap_days", 10)
    return simulate_portfolio(entries, bars_by, {}, **kw)


def _diez_el_mismo_dia(factor: float = 0.25, **kw):
    tickers = [f"T{k}" for k in range(10)]
    return _sim(
        [(t, 0) for t in tickers],
        dict.fromkeys(tickers, _flat()),
        max_positions=10,
        initial_capital=50_000.0,
        entry_filter=lambda _t, _d: factor,
        **kw,
    )


# ── 1. el caso del enunciado ─────────────────────────────────────────────────


def test_con_diez_lugares_y_un_cuarto_invierte_el_25_por_ciento():
    res = _diez_el_mismo_dia(tajada_del_dia=True)
    invertido = [t.invested for t in res.trades]
    assert len(invertido) == 10
    assert invertido == pytest.approx([1_250.0] * 10, rel=1e-12)
    assert sum(invertido) / 50_000.0 == pytest.approx(0.25, abs=1e-9)


def test_el_default_sigue_agrandando_cada_tajada():
    """Lo publicado no se mueve: el default reproduce el 54,5% y las tajadas crecientes."""
    res = _diez_el_mismo_dia()
    invertido = [t.invested for t in res.trades]
    assert all(b > a for a, b in pairwise(invertido))
    esperado = 1.0
    for j in range(1, 11):
        esperado *= 1.0 - 0.25 / j
    assert sum(invertido) / 50_000.0 == pytest.approx(1.0 - esperado, rel=1e-9)
    assert sum(invertido) / 50_000.0 == pytest.approx(0.5453, abs=1e-4)


def test_con_costos_cada_compra_escalada_es_su_tajada_sin_escalar_por_el_factor():
    """Con costos las tajadas sin escalar ya bajan un poco (cada compra paga comisión), y el
    modo nuevo sigue ESE camino —por eso es idéntico bit a bit sin escalar—. El invariante es
    entonces «tajada escalada = tajada sin escalar × factor», no «todas iguales».

    La décima es la excepción: sin escalar, la caja ya no alcanza para la tajada entera más la
    comisión y se topa a lo que se puede pagar (tarea 123); escalada, no le hace falta.
    """
    escalada = [t.invested for t in _diez_el_mismo_dia(tajada_del_dia=True, costs=CostModel()).trades]
    plena = [t.invested for t in _diez_el_mismo_dia(1.0, tajada_del_dia=True, costs=CostModel()).trades]
    assert len(escalada) == len(plena) == 10
    assert [e / p for e, p in zip(escalada[:9], plena[:9], strict=True)] == pytest.approx(
        [0.25] * 9, rel=1e-9
    )
    assert escalada[9] / plena[9] == pytest.approx(0.25, rel=2e-3)
    viejo = [t.invested for t in _diez_el_mismo_dia(costs=CostModel()).trades]
    assert max(viejo) / min(viejo) > 5, "y el default, con costos, sigue agrandando cada tajada"


# ── 2. sin escalar, idéntico bit a bit ───────────────────────────────────────


def _rico(**kw):
    """Varios días, salidas que liberan caja, más candidatos que lugares, y costos."""
    rampa = [(_d(i), 100.0 + i, 101.0 + i, 99.0 + i, 100.0 + i) for i in range(80)]
    baja = [(_d(i), 100.0 - 0.5 * i, 100.5 - 0.5 * i, 99.5 - 0.5 * i, 100.0 - 0.5 * i) for i in range(80)]
    bars_by = {f"R{k}": rampa for k in range(4)} | {f"B{k}": baja for k in range(4)}
    entries = [(t, i) for t in bars_by for i in (0, 12, 25, 40)]
    return _sim(
        entries,
        bars_by,
        max_positions=5,
        initial_capital=50_000.0,
        costs=CostModel(),
        atr_p=AtrParams(),
        cap_days=8,
        **kw,
    )


@pytest.mark.parametrize("filtro", [None, lambda _t, _d: 1.0], ids=["sin_filtro", "filtro_en_1"])
def test_sin_ningun_factor_menor_a_uno_es_identico_bit_a_bit(filtro):
    viejo = _rico(entry_filter=filtro)
    nuevo = _rico(entry_filter=filtro, tajada_del_dia=True)
    assert len(viejo.trades) > 10, "el caso tiene que tener trades para que la igualdad diga algo"
    assert viejo.trades == nuevo.trades
    assert viejo.equity_curve == nuevo.equity_curve
    assert viejo.final_equity == nuevo.final_equity


def test_el_caso_rico_SI_distingue_cuando_se_escala():
    """Contraprueba: si el caso rico no tuviera compras escaladas el mismo día, el test de
    arriba pasaría aunque el modo nuevo no hiciera nada."""
    viejo = _rico(entry_filter=lambda _t, _d: 0.25)
    nuevo = _rico(entry_filter=lambda _t, _d: 0.25, tajada_del_dia=True)
    assert viejo.final_equity != nuevo.final_equity


def test_la_caja_del_dia_arranca_de_nuevo_cada_dia():
    """Dos días con compras escaladas: la del segundo sale de la caja de ESE día."""
    a, b = _flat(), _flat()
    bars_by = {"A1": a, "A2": a, "B1": b, "B2": b}
    entries = [("A1", 0), ("A2", 0), ("B1", 3), ("B2", 3)]
    res = _sim(
        entries,
        bars_by,
        max_positions=4,
        initial_capital=40_000.0,
        entry_filter=lambda _t, _d: 0.5,
        tajada_del_dia=True,
    )
    inv = {t.ticker: t.invested for t in res.trades}
    assert inv["A1"] == pytest.approx(5_000.0) and inv["A2"] == pytest.approx(5_000.0)
    # día 3: caja 30.000, 2 lugares ⇒ 15.000 de tajada, por 0,5.
    assert inv["B1"] == pytest.approx(7_500.0) and inv["B2"] == pytest.approx(7_500.0)


# ── 3. paridad con el motor vivo ─────────────────────────────────────────────


def test_paridad_con_el_motor_vivo_en_risk_off(monkeypatch):
    """Tres compras, tres lugares, ×0,25: el vivo y el modo nuevo dan el mismo tamaño.

    Volatilidad baja para que el overlay de σ (T10) no recorte: así el único factor es el
    del régimen, que es lo que se compara.
    """
    settings.set("paper_regime_scale_enabled", True)
    settings.set("paper_regime_scale_factor", 0.25)
    tickers = ["AAA", "BBB", "CCC"]
    _patch_analyze(monkeypatch, {t: ("BUY", 0.60) for t in tickers})
    series = {t: _series(0.004, seed=k) for k, t in enumerate(tickers)}

    vivo = generate_trades_analyze_single(
        _account(max_positions=3),
        tickers,
        [],
        dict.fromkeys(tickers, 100.0),
        lambda t: _SPY_OFF if t == "SPY" else series.get(t),
    )
    tam_vivo = sorted(tr.target_dollars for tr in vivo if tr.side == "BUY")
    assert len(tam_vivo) == 3 and all("risk-off" in tr.reason for tr in vivo)

    def harness(tajada: bool) -> list[float]:
        res = _sim(
            [(t, 0) for t in tickers],
            dict.fromkeys(tickers, _flat()),
            max_positions=3,
            initial_capital=100_000.0,
            entry_filter=lambda _t, _d: 0.25,
            tajada_del_dia=tajada,
        )
        return sorted(t.invested for t in res.trades)

    assert harness(True) == pytest.approx(tam_vivo, rel=1e-9)
    assert harness(False) != pytest.approx(tam_vivo, rel=1e-3), "el default tiene que diferir"


# ── 4. el desvío ─────────────────────────────────────────────────────────────


def _claves(**kw) -> set[str]:
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE, **kw)
    return {d.clave for d in deviations_keyed(cfg)}


def test_el_desvio_se_declara_si_el_runner_escala_en_secuencial():
    assert "tajada_secuencial" in _claves(models_regime_scale=True)


def test_el_desvio_no_se_declara_con_la_tajada_por_dia_ni_sin_escalar():
    assert "tajada_secuencial" not in _claves(models_regime_scale=True, tajada_del_dia=True)
    assert "tajada_secuencial" not in _claves(), "sin escalar, las dos fórmulas coinciden"
    assert "tajada_secuencial" not in _claves(models_regime_scale=True, per_trade=True), (
        "sin cartera no hay tajada"
    )


def test_announce_pasa_el_modo_al_banner(capsys):
    cfg = announce(
        LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE, models_regime_scale=True, tajada_del_dia=True
    )
    assert cfg.tajada_del_dia is True
    assert "candidato por candidato" not in capsys.readouterr().out
    announce(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE, models_regime_scale=True)
    assert "candidato por candidato" in capsys.readouterr().out
