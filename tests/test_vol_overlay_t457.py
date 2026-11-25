"""Tarea 457 — VOL-OVERLAY-SIN-VALIDAR: el overlay de σ de cartera, modelado en el simulador.

En vivo, ``_apply_vol_overlay_to_buys`` achica todas las compras de un scan cuando la σ del libro
que va a quedar pasa del 12% anual. ``simulate_portfolio(vol_overlay=...)`` lo modela con un
factor por día, y ``analysis.overlay_sim.OverlayDeVolatilidad`` lo calcula con las funciones del
motor. Lo que se fija acá:

1. **Sin hook, o con un hook que devuelve 1, el simulador es idéntico bit a bit** al de siempre.
2. **El simulador le pasa al hook el libro del motor:** lo tenido a mercado (sin lo que sale ese
   día), las compras del día antes del régimen y la caja más todo lo abierto.
3. **El factor achica todas las compras del día por igual**, y se compone con el del régimen.
4. **Paridad con el motor:** con el mismo libro, el factor de ``OverlayDeVolatilidad`` es el que
   aplica ``_apply_vol_overlay_to_buys``, en un caso donde el overlay muerde (factor < 1).
5. **Punto en el tiempo:** un cierre posterior a la fecha no cambia el factor.
6. **Las compras previstas son las que se toman** (``n_overlay_desalineado == 0``), también con
   más candidatos que lugares y con el régimen escalando.
7. El ΔSharpe del bootstrap pareado (``stat=sharpe_compuesto``) es el de ``sharpe_annual``, y sin
   ``stat`` el bootstrap da lo mismo que antes.

Los precios son caminatas al azar con semilla y no constantes: con precios planos la marca a
mercado es igual al costo, la σ es 0 y el factor es 1, y un test ahí no distingue nada.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from analysis.exit_replay import AtrParams
from analysis.overlay_sim import OverlayDeVolatilidad, factor_overlay_del_dia
from analysis.portfolio_sim import simulate_portfolio
from analysis.risk_sizing import sharpe_annual
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import _compound_cagr, paired_block_bootstrap, sharpe_compuesto
from config.settings_manager import settings

NO_COST = CostModel(commission=0.0, slippage=0.0)
NO_ATR = AtrParams(stop_mult=1e9, tp_mult=1e9, trail_enabled=False)
N_BARRAS = 120


def _d(i: int) -> str:
    return (pd.Timestamp("2021-01-04") + pd.offsets.BDay(i)).strftime("%Y-%m-%d")


def _barras(seed: int, sigma_anual: float = 0.90, n: int = N_BARRAS) -> list:
    rng = np.random.default_rng(seed)
    cierres = 100.0 * np.exp(np.cumsum(rng.normal(0.0, sigma_anual / np.sqrt(252), n)))
    return [(_d(i), float(c), float(c), float(c), float(c)) for i, c in enumerate(cierres)]


TICKERS = ["A", "B", "C", "D", "E", "F"]
BARRAS = {t: _barras(seed=k + 1) for k, t in enumerate(TICKERS)}


def _sim(entries, **kw):
    kw.setdefault("atr_p", NO_ATR)
    kw.setdefault("costs", NO_COST)
    kw.setdefault("so_params", ScaleOutParams())
    kw.setdefault("cap_days", 30)
    kw.setdefault("max_positions", 10)
    kw.setdefault("initial_capital", 50_000.0)
    kw.setdefault("tajada_del_dia", True)
    return simulate_portfolio(entries, BARRAS, {}, **kw)


# Día 70: A y B. Día 75: C (A y B siguen abiertas). Día 80: D, E y F.
ENTRADAS = [("A", 70), ("B", 70), ("C", 75), ("D", 80), ("E", 80), ("F", 80)]


def _firma(res) -> list:
    return [(t.ticker, t.entry_date, t.exit_date, t.invested, t.proceeds, t.size_factor) for t in res.trades]


class _Grabador:
    """Hook que devuelve un factor fijo y guarda lo que recibió."""

    def __init__(self, factor: float):
        self.factor = factor
        self.llamadas: list[tuple[str, dict, dict, float]] = []

    def __call__(self, fecha, tenidas, compras, valor):
        self.llamadas.append((fecha, dict(tenidas), dict(compras), valor))
        return self.factor


# ── 1. sin hook, o con un hook neutro: idéntico ─────────────────────────────


@pytest.mark.parametrize("regimen", [None, 0.25])
def test_un_hook_que_devuelve_uno_no_cambia_nada(regimen):
    filtro = None if regimen is None else (lambda _t, _d: regimen)
    sin = _sim(ENTRADAS, entry_filter=filtro)
    con = _sim(ENTRADAS, entry_filter=filtro, vol_overlay=_Grabador(1.0))
    assert _firma(con) == _firma(sin)
    assert con.equity_curve == sin.equity_curve
    assert sin.overlay_por_dia is None and con.overlay_por_dia is not None


def test_el_hook_exige_tajada_sin_reentrada_y_equal_weight():
    with pytest.raises(ValueError, match="tajada_del_dia"):
        _sim(ENTRADAS, tajada_del_dia=False, vol_overlay=_Grabador(1.0))
    with pytest.raises(ValueError, match="allow_reentry_while_open"):
        _sim(ENTRADAS, allow_reentry_while_open=True, vol_overlay=_Grabador(1.0))
    with pytest.raises(ValueError, match="size_weight"):
        _sim(ENTRADAS, size_weight=lambda _t, _d: 1.0, vol_overlay=_Grabador(1.0))


@pytest.mark.parametrize("malo", [0.0, -0.1, 1.5, float("nan")])
def test_un_factor_fuera_de_rango_corta_la_corrida(malo):
    with pytest.raises(ValueError, match="tiene que estar en"):
        _sim(ENTRADAS, vol_overlay=_Grabador(malo))


# ── 2. el libro que recibe el hook ───────────────────────────────────────────


def test_el_hook_recibe_lo_tenido_a_mercado_las_compras_y_el_valor():
    g = _Grabador(0.5)
    res = _sim(ENTRADAS, vol_overlay=g)
    assert [c[0] for c in g.llamadas] == [_d(70), _d(75), _d(80)]

    # Día 70: nada tenido; dos compras con la tajada por día, antes del factor.
    _fecha, tenidas, compras, valor = g.llamadas[0]
    assert tenidas == {} and valor == pytest.approx(50_000.0)
    assert compras == pytest.approx({"A": 5_000.0, "B": 5_000.0})

    # Día 75: A y B a mercado (invertido × cierre / cierre de entrada), y C sobre la caja del día.
    _fecha, tenidas, compras, valor = g.llamadas[1]
    inv = {t.ticker: t.invested for t in res.trades}
    cierre = {t: {b[0]: b[4] for b in BARRAS[t]} for t in TICKERS}
    esperado = {t: inv[t] * cierre[t][_d(75)] / cierre[t][_d(70)] for t in ("A", "B")}
    assert inv["A"] == pytest.approx(2_500.0)  # el factor achicó la compra…
    assert tenidas == pytest.approx(esperado)  # …y lo tenido es lo que se compró, a mercado
    assert esperado["A"] != pytest.approx(inv["A"])  # el caso distingue marcar a mercado de a costo
    caja = 50_000.0 - inv["A"] - inv["B"]
    assert compras == pytest.approx({"C": caja / 8})
    assert valor == pytest.approx(caja + sum(esperado.values()))


def test_las_compras_le_llegan_al_hook_antes_del_regimen():
    # En vivo el overlay corre ANTES del régimen: sus pesos son los de la tajada sin escalar.
    g = _Grabador(0.5)
    res = _sim(ENTRADAS, entry_filter=lambda _t, _d: 0.25, vol_overlay=g)
    assert g.llamadas[0][2] == pytest.approx({"A": 5_000.0, "B": 5_000.0})
    assert next(t.invested for t in res.trades if t.ticker == "A") == pytest.approx(5_000.0 * 0.5 * 0.25)


def test_lo_que_sale_el_dia_cuenta_en_el_valor_pero_no_en_la_sigma():
    # Con tope de 5 ruedas, A y B (día 70) salen el día 75, cuando entra C.
    g = _Grabador(0.5)
    res = _sim(ENTRADAS, cap_days=5, vol_overlay=g)
    salida = {t.ticker: t.exit_date for t in res.trades}
    assert salida["A"] == salida["B"] == _d(75)
    fecha, tenidas, _compras, valor = g.llamadas[1]
    assert fecha == _d(75) and tenidas == {}
    caja = 50_000.0 - sum(t.invested for t in res.trades if t.entry_date == _d(70))
    assert valor > caja  # A y B siguen sumando al valor de la cartera


# ── 3. el factor achica las compras del día, y se compone con el régimen ────


@pytest.mark.parametrize("regimen", [1.0, 0.25])
def test_el_factor_achica_todas_las_compras_del_dia_por_igual(regimen):
    filtro = lambda _t, _d: regimen
    sin = {t.ticker: t for t in _sim(ENTRADAS, entry_filter=filtro).trades}
    con = {t.ticker: t for t in _sim(ENTRADAS, entry_filter=filtro, vol_overlay=_Grabador(0.4)).trades}
    for tk in ("A", "B"):  # el primer día la caja es la misma en los dos
        assert con[tk].invested == pytest.approx(0.4 * sin[tk].invested)
        assert con[tk].size_factor == pytest.approx(0.4 * regimen)
    d, e, f = (con[t].invested for t in ("D", "E", "F"))
    assert d == pytest.approx(e) and e == pytest.approx(f)  # la misma tajada para las tres


# ── 4. paridad con el motor ──────────────────────────────────────────────────


@pytest.fixture
def _overlay_vivo():
    claves = ("vol_overlay_enabled", "vol_target_portfolio_annual")
    antes = {k: settings.get(k) for k in claves}
    settings.set("vol_overlay_enabled", True)
    settings.set("vol_target_portfolio_annual", 0.12)
    yield
    for k, v in antes.items():
        settings.set(k, v)


def _historia_del_motor(fecha: str):
    """Lo que le da al motor su history_provider: frames con índice de fechas, hasta ``fecha``."""

    def proveedor(t: str):
        filas = [b for b in BARRAS.get(t, []) if b[0] <= fecha]
        if not filas:
            return None
        return pd.DataFrame({"Close": [b[4] for b in filas]}, index=pd.to_datetime([b[0] for b in filas]))

    return proveedor


def test_paridad_con_apply_vol_overlay_to_buys(_overlay_vivo):
    from paper_trading.strategies import _apply_vol_overlay_to_buys

    ov = OverlayDeVolatilidad(BARRAS, objetivo=0.12)
    g = _Grabador(1.0)
    _sim(ENTRADAS, vol_overlay=g)
    fecha, tenidas, compras, valor = g.llamadas[2]  # día 80: A, B y C tenidas; D, E y F compras
    assert set(tenidas) == {"A", "B", "C"} and set(compras) == {"D", "E", "F"}

    precios = {t: next(b[4] for b in BARRAS[t] if b[0] == fecha) for t in TICKERS}
    posiciones = [SimpleNamespace(ticker=t, shares=v / precios[t], avg_cost=1.0) for t, v in tenidas.items()]
    salida = _apply_vol_overlay_to_buys(
        dict(compras), list(compras), posiciones, set(), precios, valor, _historia_del_motor(fecha), "t457"
    )
    factor_motor = salida["D"] / compras["D"]
    factor_sim = ov(fecha, tenidas, compras, valor)

    assert factor_motor < 0.9  # el overlay muerde: un caso con factor 1 no fijaría nada
    assert factor_sim == pytest.approx(factor_motor, rel=1e-12)
    assert ov.sigmas[fecha] == pytest.approx(0.12 / factor_motor, rel=1e-12)


def test_los_cortes_son_los_del_motor():
    historia = OverlayDeVolatilidad(BARRAS).historia_hasta(_d(80))
    assert factor_overlay_del_dia({"A": 1.0}, {}, 10.0, historia, 0.12).factor == 1.0
    assert factor_overlay_del_dia({}, {"A": 1.0}, 0.0, historia, 0.12).factor == 1.0
    assert factor_overlay_del_dia({}, {"A": 1.0}, 10.0, historia, 0.0).factor == 1.0
    assert factor_overlay_del_dia({}, {"A": 9.0}, 10.0, historia, 0.12).factor < 1.0


# ── 5. punto en el tiempo ─────────────────────────────────────────────────────


def test_un_cierre_posterior_no_cambia_el_factor():
    fecha = _d(80)
    compras = {"D": 5_000.0, "E": 5_000.0}
    base = OverlayDeVolatilidad(BARRAS)(fecha, {}, compras, 20_000.0)
    futuro = {t: list(b) for t, b in BARRAS.items()}
    futuro["D"][81] = (_d(81), 1.0, 1.0, 1.0, 1.0)  # un derrumbe al día siguiente
    assert OverlayDeVolatilidad(futuro)(fecha, {}, compras, 20_000.0) == base
    futuro["D"][80] = (_d(80), 1.0, 1.0, 1.0, 1.0)  # el mismo derrumbe EL día sí lo cambia
    assert OverlayDeVolatilidad(futuro)(fecha, {}, compras, 20_000.0) != base


# ── 6. las previstas son las que se toman ─────────────────────────────────────


@pytest.mark.parametrize("regimen", [1.0, 0.25])
def test_las_compras_previstas_son_las_tomadas(regimen):
    # Más candidatos que lugares, todos los días, con reentradas y el tope de tenencia corto.
    entradas = [(t, i) for i in range(65, 110, 3) for t in TICKERS]
    res = _sim(
        entradas,
        max_positions=4,
        cap_days=4,
        live_gates=True,
        entry_filter=lambda _t, _d: regimen,
        vol_overlay=OverlayDeVolatilidad(BARRAS),
    )
    assert res.n_no_slot > 0 and res.n_already_open > 0  # el caso tiene competencia de verdad
    assert min(res.overlay_por_dia.values()) < 1.0  # y el overlay muerde
    assert res.n_overlay_desalineado == 0


def test_la_prevision_descarta_lo_que_replay_cycle_no_abre():
    # «A» en la última barra: replay_cycle da None y no se compra; la previsión no la cuenta.
    g = _Grabador(0.5)
    res = _sim([("A", N_BARRAS - 1), ("B", N_BARRAS - 1)], vol_overlay=g)
    assert res.trades == [] and res.n_overlay_desalineado == 0
    assert g.llamadas == []  # sin compras previstas, el hook ni se llama


# ── 7. el ΔSharpe del bootstrap ───────────────────────────────────────────────


def _curva(seed: int, n: int = 400) -> list[tuple[str, float]]:
    rng = np.random.default_rng(seed)
    v = 100.0 * np.cumprod(1.0 + rng.normal(0.0004, 0.01, n))
    return [(_d(i), float(x)) for i, x in enumerate(v)]


def _rets(curva):
    return [curva[i][1] / curva[i - 1][1] - 1.0 for i in range(1, len(curva))]


def test_sharpe_compuesto_es_el_de_sharpe_annual():
    curva = _curva(7)
    assert sharpe_compuesto(np.asarray(_rets(curva))) == pytest.approx(sharpe_annual(curva), rel=1e-12)


def test_el_bootstrap_sin_stat_es_el_de_siempre_y_con_sharpe_difiere_el_sharpe():
    a, b = _rets(_curva(7)), _rets(_curva(8))
    sin = paired_block_bootstrap(a, b, n_resamples=200)
    assert sin.observed == pytest.approx(
        _compound_cagr(np.asarray(b)) - _compound_cagr(np.asarray(a)), rel=1e-12
    )
    con = paired_block_bootstrap(a, b, n_resamples=200, stat=sharpe_compuesto)
    assert con.observed == pytest.approx(sharpe_annual(_curva(8)) - sharpe_annual(_curva(7)), rel=1e-12)
    assert con.observed != pytest.approx(sin.observed)


def test_el_intervalo_es_del_estadistico_pedido():
    # Retornos duplicados: el Sharpe es el mismo en CADA remuestreo y el CAGR no, así que el IC
    # del ΔSharpe es exactamente cero y el del ΔCAGR no. Mira la distribución, no sólo el punto.
    a = _rets(_curva(7))
    b = [2.0 * x for x in a]
    sh = paired_block_bootstrap(a, b, n_resamples=200, stat=sharpe_compuesto)
    cg = paired_block_bootstrap(a, b, n_resamples=200)
    assert sh.ci_low == pytest.approx(0.0, abs=1e-9) and sh.ci_high == pytest.approx(0.0, abs=1e-9)
    assert cg.ci_high - cg.ci_low > 0.01


# ── 8. las piezas del runner ─────────────────────────────────────────────────


def _diaria(rets: np.ndarray, fechas: list[str]) -> list[tuple[str, float]]:
    return list(zip(fechas, (50_000.0 * np.cumprod(1.0 + rets)).tolist(), strict=True))


def _tres_curvas(delta_diario: float):
    from scripts.run_activo_pasivo_t456 import mezcla_constante

    fechas = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2021-01-04", "2026-08-31")]
    base = np.random.default_rng(3).normal(0.0004, 0.012, len(fechas))
    sin = _diaria(base, fechas)
    con = _diaria(base + delta_diario, fechas)
    caja = mezcla_constante(fechas, dict(sin), 0.6, costo=0.0, capital=50_000.0)
    return con, sin, caja


@pytest.mark.parametrize(
    ("delta", "esperado"),
    [(+0.0008, "SE_QUEDA"), (-0.0008, "RESTA"), (0.0, "NO_SE_DISTINGUE")],
)
def test_la_lectura_del_gate(delta, esperado):
    import scripts.run_vol_overlay_t457 as r

    con, sin, caja = _tres_curvas(delta)
    ev = r.evaluar_gate(con, sin, caja, resamples=200)
    assert ev["veredicto"] == getattr(r, esperado)
    assert ev["cobertura"] == 1.0
    if esperado == "SE_QUEDA":
        assert all(ev["condiciones"].values())


def test_sin_la_vara_de_la_caja_no_se_queda():
    import scripts.run_vol_overlay_t457 as r

    con, sin, _caja = _tres_curvas(+0.0008)
    ev = r.evaluar_gate(con, sin, con, resamples=200)  # una «caja» tan buena como el candidato
    assert ev["condiciones"]["C1"] and ev["condiciones"]["C2"] and not ev["condiciones"]["C3"]
    assert ev["veredicto"] == r.NO_SE_DISTINGUE


def test_w_alinear_y_resumen_del_factor():
    import scripts.run_vol_overlay_t457 as r

    assert r.w_caja_equivalente(0.45, 0.60) == pytest.approx(0.75)
    assert r.w_caja_equivalente(0.45, 0.0) is None
    a = [("2021-01-04", 1.0), ("2021-01-05", 2.0), ("2021-01-06", 3.0), ("2021-01-07", 4.0)]
    b = [("2021-01-05", 5.0), ("2021-01-06", 6.0), ("2021-01-07", 7.0)]
    aa, bb, cob = r.alinear(a, b)
    assert [d for d, _ in aa] == [d for d, _ in bb] == ["2021-01-05", "2021-01-06", "2021-01-07"]
    assert cob == pytest.approx(0.75)
    fac = r.resumen_factor({"2020-01-02": 1.0, "2020-06-01": 0.5, "2021-03-01": 0.8})
    assert fac["n_dias"] == 3 and fac["media"] == pytest.approx(2.3 / 3)
    assert fac["frac_menor_1"] == pytest.approx(2 / 3) and fac["minimo"] == 0.5
    assert fac["por_anio"] == pytest.approx({"2020": 0.75, "2021": 0.8})
    assert r.resumen_factor(None) == {"n_dias": 0}
