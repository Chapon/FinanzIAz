"""Tarea 458 — EARNINGS-BLACKOUT-SIN-MEDIR: el Gate 6 como filtro de entrada del simulador.

Lo que se fija:

1. **Paridad con el motor:** ``filtro_de_balances`` da 0 exactamente cuando
   ``is_within_earnings_blackout`` da ``True``, con fechas a −3, −2, 0, +2 y +3 días corridos (el
   borde es lo que distingue ±2 de ±1 o ±3). Un ticker sin fechas no se bloquea, y con 0 días el
   gate está apagado.
2. **El filtro se compone con el del régimen** multiplicando, y un 0 de cualquiera suprime.
3. **En el simulador, el filtro suprime la entrada** (``n_filtered``) y el lugar pasa al siguiente
   candidato (lo que la 471 dice que el vivo no hace).
4. **La cobertura del almacén** cuenta los tickers sin fechas y los que arrancan después del cohorte.
5. **La lectura del gate:** las cinco ⇒ sacar el bloqueo; D1 sin las otras ⇒ resta pero no alcanza;
   sin D1 ⇒ no mover. El D4 se mide sobre la misma muestra que el D1 (los retornos OOS).
6. **El almacén se lee como se escribe.**
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

import scripts.run_blackout_t458 as r
from analysis.earnings_sim import cargar_fechas, componer, filtro_de_balances
from analysis.exit_replay import AtrParams
from analysis.portfolio_sim import PortfolioResult, Trade, simulate_portfolio
from analysis.scaleout_replay import CostModel, ScaleOutParams
from paper_trading.gates import is_within_earnings_blackout
from scripts.bajar_fechas_balance_t458 import cobertura, fechas_de

BALANCE = "2024-05-15"


# ── 1. paridad con el motor ──────────────────────────────────────────────────


@pytest.mark.parametrize("delta", [-4, -3, -2, -1, 0, 1, 2, 3, 4])
@pytest.mark.parametrize("dias", [1, 2, 3])
def test_paridad_con_is_within_earnings_blackout(delta, dias):
    fecha = (date.fromisoformat(BALANCE) + timedelta(days=delta)).isoformat()
    filtro = filtro_de_balances({"KO": ["2024-02-10", BALANCE, "2024-08-20"]}, dias)
    motor = is_within_earnings_blackout(
        datetime.fromisoformat(BALANCE), datetime.fromisoformat(fecha + "T15:30:00"), dias
    )
    assert (filtro("KO", fecha) == 0.0) == motor


def test_sin_fechas_o_con_cero_dias_no_bloquea():
    filtro = filtro_de_balances({"KO": [BALANCE]}, 2)
    assert filtro("PEP", BALANCE) == 1.0  # un ticker sin fechas: fail-open, como en vivo
    assert filtro_de_balances({"KO": [BALANCE]}, 0)("KO", BALANCE) == 1.0


# ── 2. se compone con el régimen ─────────────────────────────────────────────


def test_componer_multiplica_y_un_cero_suprime():
    bloqueo = filtro_de_balances({"KO": [BALANCE]}, 2)
    regimen = lambda _t, _d: 0.25
    f = componer(regimen, bloqueo)
    assert f("KO", BALANCE) == 0.0
    assert f("KO", "2024-06-30") == pytest.approx(0.25)
    assert componer(None, None) is None
    assert componer(None, bloqueo) is bloqueo


# ── 3. en el simulador ───────────────────────────────────────────────────────


def _barras(n=60, inicio="2024-05-01"):
    fechas = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(inicio, periods=n)]
    rng = np.random.default_rng(3)
    c = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, n))
    return [(f, float(x), float(x), float(x), float(x)) for f, x in zip(fechas, c, strict=True)]


def test_el_filtro_suprime_y_el_lugar_pasa_al_siguiente():
    barras = {"KO": _barras(), "PEP": _barras()}
    idx = next(i for i, b in enumerate(barras["KO"]) if b[0] == BALANCE)
    entradas = [("KO", idx), ("PEP", idx)]
    kw = dict(
        max_positions=1,
        atr_p=AtrParams(stop_mult=1e9, tp_mult=1e9, trail_enabled=False),
        costs=CostModel(commission=0.0, slippage=0.0),
        so_params=ScaleOutParams(),
        cap_days=10,
        rank_score=lambda t, _d: 1.0 if t == "KO" else 0.5,  # KO primero
    )
    sin = simulate_portfolio(entradas, barras, {}, **kw)
    con = simulate_portfolio(
        entradas, barras, {}, entry_filter=filtro_de_balances({"KO": [BALANCE]}, 2), **kw
    )
    assert [t.ticker for t in sin.trades] == ["KO"] and sin.n_no_slot == 1
    assert [t.ticker for t in con.trades] == ["PEP"] and con.n_filtered == 1


# ── 4. la cobertura del almacén ──────────────────────────────────────────────


def test_la_cobertura_cuenta_sin_fechas_y_los_que_arrancan_tarde():
    fechas = {"A": ["2014-10-21", "2024-01-01"], "B": ["2018-01-01"], "C": []}
    cob = r.cobertura_del_almacen(fechas, ["A", "B", "C", "D"])
    assert cob["con_fechas"] == 2 and cob["sin_fechas"] == ["C", "D"]
    assert cob["con_fechas_antes"] == 1 and cob["frac_antes"] == pytest.approx(0.5)
    assert not cob["ok"]
    ok = r.cobertura_del_almacen({t: ["2014-10-21"] for t in "ABCDEFGHIJ"}, list("ABCDEFGHIJ"))
    assert ok["ok"]
    assert cobertura(fechas, "2016-09-12")["arrancan_despues_del_cohorte"] == ["B"]


def test_fechas_de_usa_el_dia_de_la_bolsa():
    idx = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-10-27 06:00", tz="America/New_York"),
            pd.Timestamp("2014-10-21 07:00", tz="America/New_York"),
        ]
    )
    assert fechas_de(pd.DataFrame({"x": [1, 2]}, index=idx)) == ["2014-10-21", "2026-10-27"]
    assert fechas_de(None) == [] and fechas_de(pd.DataFrame()) == []


# ── 5. la lectura del gate ───────────────────────────────────────────────────


def _resultado(rets: np.ndarray, trade_rets: list[float]) -> PortfolioResult:
    fechas = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2017-09-01", "2026-08-31")]
    rets = rets[: len(fechas)]
    curva = list(zip(fechas, (50_000.0 * np.cumprod(1.0 + rets)).tolist(), strict=True))
    res = PortfolioResult(initial_capital=50_000.0, final_equity=curva[-1][1], equity_curve=curva)
    res.trades = [
        Trade("X", "2020-01-02", "2020-01-10", 100.0, 100.0 * (1 + x), "", 5, "") for x in trade_rets
    ]
    return res


def _par(delta: float, cola_peor: float = 0.0):
    n = len(pd.bdate_range("2017-09-01", "2026-08-31"))
    base = np.random.default_rng(11).normal(0.0004, 0.01, n)
    tr = list(np.random.default_rng(12).normal(0.01, 0.05, 300))
    vivo = _resultado(base, tr)
    sin = _resultado(base + delta, [*tr[:-1], min(tr) + cola_peor])
    return vivo, sin


def test_las_cinco_dan_sacar_el_bloqueo():
    vivo, sin = _par(+0.0008)
    ev = r.evaluar_gate(vivo, sin, resamples=200)
    assert all(ev["condiciones"].values()) and ev["veredicto"] == r.SACAR
    assert ev["boot"]["observed"] == pytest.approx(ev["dcagr_oos"], abs=0.02)


def test_d1_sin_las_otras_resta_pero_no_alcanza():
    vivo, sin = _par(+0.0008, cola_peor=-0.10)  # el peor trade empeora 10 pp: D3 falla
    ev = r.evaluar_gate(vivo, sin, resamples=200)
    assert ev["condiciones"]["D1"] and not ev["condiciones"]["D3"]
    assert ev["veredicto"] == r.RESTA


def test_sin_d1_no_mover():
    vivo, sin = _par(0.0)
    ev = r.evaluar_gate(vivo, sin, resamples=200)
    assert not ev["condiciones"]["D1"] and ev["veredicto"] == r.NO_MOVER


# ── 6. el almacén ────────────────────────────────────────────────────────────


def test_el_almacen_se_lee_como_se_escribe(tmp_path):
    p = tmp_path / "fechas.json"
    p.write_bytes(
        json.dumps({"capturado": "2026-11-25", "fechas": {"KO": ["2024-05-15", "2014-10-21"]}}).encode()
    )
    fechas, meta = cargar_fechas(p)
    assert fechas == {"KO": ["2014-10-21", "2024-05-15"]} and meta == {"capturado": "2026-11-25"}


def test_el_d4_sale_de_la_muestra_fuera_de_muestra():
    # Δ sólo ANTES de 2021-08: un bootstrap sobre la muestra completa lo vería; el OOS, no.
    fechas = pd.bdate_range("2017-09-01", "2026-08-31")
    base = np.random.default_rng(11).normal(0.0004, 0.01, len(fechas))
    delta = np.where(fechas < "2021-08-01", 0.002, 0.0)
    tr = list(np.random.default_rng(12).normal(0.01, 0.05, 300))
    ev = r.evaluar_gate(_resultado(base, tr), _resultado(base + delta, tr), resamples=200)
    assert ev["boot"]["observed"] == pytest.approx(0.0, abs=1e-9)
    assert ev["dcagr_oos"] == pytest.approx(0.0, abs=1e-9)


def test_la_cobertura_falla_si_los_que_tienen_fechas_arrancan_tarde():
    tickers = list("ABCDEFGHIJ")
    fechas = {t: ["2014-10-21"] if i < 5 else ["2019-01-01"] for i, t in enumerate(tickers)}
    cob = r.cobertura_del_almacen(fechas, tickers)
    assert cob["frac_con"] == 1.0 and cob["frac_antes"] == pytest.approx(0.5)
    assert not cob["ok"]


def test_lo_que_se_pierde_cuenta_los_trades_tocados():
    res = PortfolioResult(initial_capital=1.0, final_equity=1.0)
    res.trades = [
        Trade("KO", BALANCE, "2024-05-30", 100.0, 110.0, "", 5, ""),
        Trade("KO", "2024-06-30", "2024-07-10", 100.0, 95.0, "", 5, ""),
        Trade("PEP", BALANCE, "2024-05-30", 100.0, 101.0, "", 5, ""),
    ]
    p = r.lo_que_se_pierde(res, filtro_de_balances({"KO": [BALANCE]}, 2))
    assert (p["n_tocados"], p["n_otros"]) == (1, 2)
    assert p["ret_medio_tocados"] == pytest.approx(0.10)
    assert p["ret_medio_otros"] == pytest.approx((-0.05 + 0.01) / 2)
