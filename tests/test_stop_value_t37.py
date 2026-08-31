"""Tests del runner de STOP-VALUE — Tarea 37.

Cubre el §11.4 del pre-registro congelado: **el helper del veredicto aplica el AND
de los nueve criterios y cada caso partido del §8**, y **el desacople ``trail_mult``
no se pisa con ``stop_mult``**. Suma los de la enmienda (``docs/stop_value_enmienda_
t37_2026-08-27.md``): C5′ no puede bloquear por una ventana fea sola, y C5′-bis
escala C9 **sólo** cuando una ventana resuelve un efecto negativo.

Offline puro: nada de red, disco ni ``finanzias.db``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pytest

from analysis.exit_replay import AtrParams, atr_exit
from scripts.run_stop_cal_replay_t26 import NO_STOP
from scripts.run_stop_value_t37 import (
    BASELINE_ARM,
    C9_ESCALATION,
    C9_POINTS,
    FOLDS,
    KILL_MIN_FOLD_AGREEMENT,
    KILL_TAIL_TOL_PTS,
    RUIN_GRID,
    STOP_MULTS,
    TOL_MATERIAL_PTS,
    TRAIL_MULTS,
    _repro_targets,
    arm_name,
    arm_params,
    breakeven_rate,
    evaluate,
    grid_cells,
    is_shippable,
    regime_criterion,
    ruin_dose_response,
    tail_stats,
)

# ── el pre-registro, congelado ───────────────────────────────────────────────


def test_la_rejilla_es_5x3_y_el_baseline_es_la_config_viva():
    assert STOP_MULTS == (2.0, 3.0, 4.0, 6.0, NO_STOP)
    assert TRAIL_MULTS == (2.0, 3.0, NO_STOP)
    assert len(grid_cells()) == 15
    assert BASELINE_ARM == "s2.0_t2.0"


def test_los_umbrales_y_la_rejilla_de_ruina_estan_congelados():
    assert TOL_MATERIAL_PTS == 1.00
    assert KILL_TAIL_TOL_PTS == 2.00
    assert KILL_MIN_FOLD_AGREEMENT == 4
    assert len(FOLDS) == 5
    assert RUIN_GRID == (
        (0.50, (0.0, 0.005, 0.01, 0.026, 0.05, 0.10)),
        (0.70, (0.0, 0.0047, 0.01, 0.02)),
    )
    # C9 usa las tasas MEDIDAS dentro del propio universo (§3).
    assert C9_POINTS == ((0.026, 0.50), (0.0047, 0.70))
    # C5′-bis escala a un escalón que YA está en la rejilla — no inventa un número.
    assert C9_ESCALATION == (0.05, 0.50)
    assert C9_ESCALATION[0] in dict(RUIN_GRID)[C9_ESCALATION[1]]


def test_las_anclas_de_reproduccion_son_las_tres_celdas_publicadas_por_la_t34():
    t = _repro_targets()
    assert t == {"s2.0_t2.0": 0.0201, "soff_t2.0": 0.0917, "soff_toff": 0.0952}
    for name in t:
        assert name in {arm_name(s, tr) for s, tr in grid_cells()}


def test_el_off_del_trailing_no_es_shipeable_pero_el_del_stop_si():
    assert is_shippable(NO_STOP, 2.0) is True
    assert is_shippable(2.0, 2.0) is True
    assert is_shippable(2.0, NO_STOP) is False
    assert is_shippable(NO_STOP, NO_STOP) is False


# ── el desacople: trail_mult NO se pisa con stop_mult ────────────────────────


def test_arm_params_fija_trail_mult_explicito_siempre():
    """Dejarlo en ``None`` haría que el trailing siga al stop — el acople exacto
    que esta tarea existe para romper."""
    for s, t in grid_cells():
        p = arm_params(s, t)["atr_p"]
        assert p.trail_mult is not None
        assert p.stop_mult == s
        assert p.effective_trail_mult == t


def test_el_default_del_dataclass_si_acopla_las_dos_barreras():
    """Control negativo: así corrió la T34, y por eso su rejilla era 1-D."""
    assert AtrParams(stop_mult=3.0).effective_trail_mult == 3.0
    assert AtrParams(stop_mult=3.0, trail_mult=2.0).effective_trail_mult == 2.0


def test_con_el_stop_apagado_la_barrera_que_dispara_es_el_trailing():
    """Espejo de ``gates.atr_exit_decision``: apagar el stop duro no apaga el
    trailing, y el trailing sigue midiendo desde el HWM."""
    p = arm_params(NO_STOP, 2.0)["atr_p"]
    # Precio 90, entrada 100, HWM 120, ATR 10 ⇒ trail_level = 120 − 2×10 = 100.
    assert (
        atr_exit(current_price=90.0, avg_cost=100.0, high_water_mark=120.0, atr_value=10.0, p=p)
        == "atr_trail"
    )
    # El mismo caso con el stop vivo dispara el STOP (100 − 2×10 = 80 … no toca),
    # así que sigue siendo el trailing; el punto es que `off` no lo mató.
    assert (
        atr_exit(
            current_price=70.0,
            avg_cost=100.0,
            high_water_mark=100.0,
            atr_value=10.0,
            p=arm_params(2.0, 2.0)["atr_p"],
        )
        == "atr_stop"
    )
    # …y con el stop apagado ese mismo precio NO dispara nada (HWM = entrada ⇒
    # el trailing está suprimido por `trail_min_excess_atrs`).
    assert atr_exit(current_price=70.0, avg_cost=100.0, high_water_mark=100.0, atr_value=10.0, p=p) is None


def test_con_las_dos_apagadas_no_dispara_ninguna_barrera_de_abajo():
    p = arm_params(NO_STOP, NO_STOP)["atr_p"]
    assert atr_exit(current_price=10.0, avg_cost=100.0, high_water_mark=200.0, atr_value=10.0, p=p) is None


# ── C5′ y C5′-bis ────────────────────────────────────────────────────────────


@dataclass
class _T:
    ret: float
    regime: str


class _R:
    def __init__(self, trades):
        self.trades = trades


def _res(by_regime: dict[str, list[float]]):
    return _R([_T(v / 100.0, r) for r, vs in by_regime.items() for v in vs])


def _pair(base_map, cand_map, n_resamples=400):
    return regime_criterion(_res(base_map), _res(cand_map), n_resamples=n_resamples, seed=12345)


def test_c5_no_bloquea_por_una_ventana_fea_sola():
    """El defecto exacto de la 26b: una ventana chica y fea rechazaba sola.

    ``stress_2018q4`` con n chico y Δ negativo, pero el AGREGADO neutro ⇒ PASA.
    """
    base = {
        "bull_normal": [1.0, -1.0] * 400,
        "stress_2018q4": [2.0, -2.0] * 20,
        "stress_covid_2020": [3.0, -3.0] * 20,
        "stress_bear_2022": [1.0, -1.0] * 100,
    }
    cand = {
        "bull_normal": [1.0, -1.0] * 400,
        "stress_2018q4": [1.0, -3.0] * 20,  # −1.0 pts, ventana chica
        "stress_covid_2020": [3.0, -3.0] * 20,
        "stress_bear_2022": [1.0, -1.0] * 100,
    }
    c5 = _pair(base, cand)
    assert c5["windows"]["stress_2018q4"]["delta_pts"] < 0
    assert c5["passes"] is True, "una ventana individual no puede bloquear (46 §4.3)"


def test_c5_falla_solo_si_el_IC_del_agregado_esta_ENTERO_del_lado_malo():
    base = {
        "bull_normal": [0.0] * 100,
        "stress_2018q4": [10.0] * 60,
        "stress_covid_2020": [10.0] * 60,
        "stress_bear_2022": [10.0] * 60,
    }
    cand = {
        "bull_normal": [0.0] * 100,
        "stress_2018q4": [0.0] * 60,
        "stress_covid_2020": [0.0] * 60,
        "stress_bear_2022": [0.0] * 60,
    }
    c5 = _pair(base, cand)
    assert c5["pooled_delta_pts"] == pytest.approx(-10.0)
    assert c5["pooled_ci_high"] < -c5["tolerance_pts"]
    assert c5["passes"] is False


def test_la_tolerancia_se_computa_y_nunca_baja_de_la_material():
    base = {
        "bull_normal": [1.0, -1.0] * 50,
        "stress_2018q4": [5.0, -5.0] * 10,
        "stress_covid_2020": [5.0, -5.0] * 10,
        "stress_bear_2022": [5.0, -5.0] * 10,
    }
    c5 = _pair(base, base)
    assert c5["tolerance_pts"] >= TOL_MATERIAL_PTS
    assert c5["tolerance_pts"] == max(TOL_MATERIAL_PTS, c5["detectable_pts"])


def test_c5_bis_no_escala_si_el_efecto_no_llega_al_piso_de_resolucion():
    """El caso de la T34: −1.18 pts contra ±1.72 detectable ⇒ NO resuelve."""
    base = {
        "bull_normal": [1.0, -1.0] * 400,
        "stress_2018q4": [5.0, -5.0] * 40,
        "stress_covid_2020": [5.0, -5.0] * 40,
        "stress_bear_2022": [5.0, -5.0] * 40,
    }
    cand = {
        "bull_normal": [1.0, -1.0] * 400,
        "stress_2018q4": [4.9, -5.1] * 40,  # −0.10 pts, mucho bajo el piso
        "stress_covid_2020": [5.0, -5.0] * 40,
        "stress_bear_2022": [5.0, -5.0] * 40,
    }
    c5 = _pair(base, cand)
    w = c5["windows"]["stress_2018q4"]
    assert w["delta_pts"] < 0 and abs(w["delta_pts"]) < w["detectable"]
    assert w["resolves_negative"] is False
    assert c5["escalate_c9"] is False


def test_c5_bis_escala_cuando_la_ventana_SI_resuelve_un_efecto_negativo():
    base = {
        "bull_normal": [1.0, -1.0] * 400,
        "stress_2018q4": [1.0, -1.0] * 200,  # σ chico, n grande ⇒ piso bajo
        "stress_covid_2020": [1.0, -1.0] * 200,
        "stress_bear_2022": [1.0, -1.0] * 200,
    }
    cand = {
        "bull_normal": [1.0, -1.0] * 400,
        "stress_2018q4": [-4.0, -6.0] * 200,  # −5 pts, muy por encima del piso
        "stress_covid_2020": [1.0, -1.0] * 200,
        "stress_bear_2022": [1.0, -1.0] * 200,
    }
    c5 = _pair(base, cand)
    assert c5["windows"]["stress_2018q4"]["resolves_negative"] is True
    assert c5["escalate_c9"] is True
    assert "stress_2018q4" in c5["escalate_windows"]


# ── el barrido de ruina ──────────────────────────────────────────────────────


def _sweep(depth: float, pairs: list[tuple[float, float]], base=None, seeds_by_rate=None):
    """`pairs` = [(rate, dcagr_worst)]. `base` = {rate: base_cagr medio}.
    `seeds_by_rate` = {rate: [base_cagr por semilla]} para el §7.5′."""
    out = {}
    for rate, dworst in pairs:
        seeds = (seeds_by_rate or {}).get(rate)
        if seeds is None:
            seeds = [(base or {}).get(rate, 0.10)]
        out[f"d{depth:.2f}_r{rate:.4f}"] = {
            "rate": rate,
            "depth": depth,
            "shape": "gradual",
            "dcagr_worst": dworst,
            "dcagr_mean": dworst,
            "base_cagr_mean": sum(seeds) / len(seeds),
            "cand_cagr_mean": 0.0,
            "digests_ok": True,
            "per_seed": [
                {"seed": 1000 + i, "base_cagr": v, "cand_cagr": 0.0, "dcagr": dworst, "digest_ok": True}
                for i, v in enumerate(seeds)
            ],
        }
    return out


def test_breakeven_interpola_entre_dos_puntos_de_la_rejilla():
    s = _sweep(0.50, [(0.0, 0.04), (0.026, 0.02), (0.05, -0.02)])
    be = breakeven_rate(s, 0.50)
    # entre 2.6% (+0.02) y 5% (−0.02) ⇒ justo al medio.
    assert be == pytest.approx(0.026 + (0.05 - 0.026) * 0.5)


def test_breakeven_cero_si_ya_pierde_sin_ruina():
    s = _sweep(0.50, [(0.0, -0.01), (0.026, -0.03)])
    assert breakeven_rate(s, 0.50) == 0.0


def test_breakeven_none_si_aguanta_toda_la_rejilla():
    s = _sweep(0.50, [(0.0, 0.04), (0.026, 0.03), (0.10, 0.01)])
    assert breakeven_rate(s, 0.50) is None


# ── §7.5′ — dosis-respuesta con tolerancia computada (enmienda 2) ────────────


def test_7_5_prima_pasa_con_dano_y_dosis_respuesta_limpia():
    r = ruin_dose_response(
        _sweep(
            0.50,
            [(0.0, 0.0), (0.026, 0.0), (0.10, 0.0)],
            seeds_by_rate={0.0: [0.10], 0.026: [0.07, 0.07, 0.07], 0.10: [0.04, 0.04, 0.04]},
        ),
        depth=0.50,
    )
    assert r["damage_ok"] and r["dose_ok"] and r["passes"]
    assert r["damage_pp"] == pytest.approx(0.06)


def test_7_5_prima_no_falla_por_un_ascenso_DENTRO_del_ruido_de_semilla():
    """El caso exacto que invalidó la primera corrida: +0.2 pp de ascenso dentro
    de una banda de dispersión entre semillas de ~3 pp."""
    r = ruin_dose_response(
        _sweep(
            0.50,
            [(0.0, 0.0), (0.005, 0.0), (0.10, 0.0)],
            seeds_by_rate={
                0.0: [0.02013],
                0.005: [0.00440, 0.03494, 0.02754],  # rango 3.05 pp
                0.10: [-0.03471, -0.06205, -0.02529],
            },
        ),
        depth=0.50,
    )
    paso = r["steps"][0]
    assert paso["delta"] > 0, "el ascenso está, y es el que hizo fallar la §7.5"
    assert paso["tol"] > paso["delta"], "pero cae dentro del ruido del instrumento"
    assert r["dose_ok"] and r["passes"]


def test_7_5_prima_SI_falla_si_el_ascenso_SALE_de_la_banda():
    """No es un sello de goma: un ascenso real sigue invalidando la corrida."""
    r = ruin_dose_response(
        _sweep(
            0.50,
            [(0.0, 0.0), (0.026, 0.0), (0.10, 0.0)],
            seeds_by_rate={
                0.0: [0.02],
                0.026: [0.119, 0.120, 0.121],  # +10 pp, sd chico
                0.10: [-0.05, -0.05, -0.05],
            },
        ),
        depth=0.50,
    )
    assert r["steps"][0]["ok"] is False
    assert not r["dose_ok"] and not r["passes"]


def test_7_5_prima_falla_si_la_ruina_no_hace_dano():
    """Si inyectar ruina no lastima, la inyección está mal cableada."""
    r = ruin_dose_response(
        _sweep(0.50, [(0.0, 0.0), (0.10, 0.0)], seeds_by_rate={0.0: [0.10], 0.10: [0.0999, 0.0999, 0.0999]}),
        depth=0.50,
    )
    assert r["dose_ok"] and not r["damage_ok"] and not r["passes"]


def test_7_5_prima_reporta_la_tabla_por_semilla():
    """§7.5′(c): el descriptivo por semilla es obligatorio."""
    r = ruin_dose_response(
        _sweep(
            0.50,
            [(0.0, 0.0), (0.026, 0.0), (0.10, 0.0)],
            seeds_by_rate={0.0: [0.10], 0.026: [0.05, 0.07, 0.09], 0.10: [0.01, 0.02, 0.03]},
        ),
        depth=0.50,
    )
    assert [row["rate"] for row in r["by_seed"]] == [0.0, 0.026, 0.10]
    assert r["by_seed"][1]["spread"] == pytest.approx(0.04)
    assert len(r["by_seed"][1]["seeds"]) == 3


def test_r_cero_es_determinista_y_no_rompe_la_tolerancia():
    """`r=0` tiene n=1 y sd=0 por construcción: la tolerancia sale del otro lado."""
    r = ruin_dose_response(
        _sweep(0.50, [(0.0, 0.0), (0.026, 0.0)], seeds_by_rate={0.0: [0.02], 0.026: [0.01, 0.02, 0.03]}),
        depth=0.50,
    )
    paso = r["steps"][0]
    assert paso["tol"] > 0.0 and math.isfinite(paso["tol"])


# ── cola (C6) ────────────────────────────────────────────────────────────────


def test_tail_stats():
    r = _R([_T(v / 100.0, "bull_normal") for v in [-30.0, -20.0, -10.0] + [1.0] * 97])
    t = tail_stats(r)
    assert t["n"] == 100
    assert t["worst"] == pytest.approx(-30.0)
    assert t["p1"] == pytest.approx(-20.0)
    assert t["p5"] == pytest.approx(1.0)


# ── §8 — el AND de los nueve y cada caso partido ─────────────────────────────


@dataclass
class _Boot:
    observed: float = 0.04
    ci_low: float = 0.01
    ci_high: float = 0.08
    p_value: float = 0.01


def _ctx(
    *,
    star=(NO_STOP, 2.0),
    agreement=5,
    dd_cand=0.30,
    sharpe_cand=0.58,
    cagr_cand=0.0917,
    oos_proc=0.0553,
    oos_base=0.0141,
    dd_proc=0.229,
    dd_base=0.256,
    tail_worst_d=0.0,
    tail_p1_d=0.0,
    boot=None,
    c5=None,
    sens5=0.03,
    sens_close=0.04,
    c9=(0.01, 0.01, 0.01),
):
    cand_arm = arm_name(*star)
    summaries = {
        BASELINE_ARM: {
            "cagr": 0.0201,
            "sharpe": 0.20,
            "max_dd": 0.467,
            "accounting_ok": True,
            "exit_mix": {},
            "n_taken": 2815,
        },
        cand_arm: {
            "cagr": cagr_cand,
            "sharpe": sharpe_cand,
            "max_dd": dd_cand,
            "accounting_ok": True,
            "exit_mix": {},
            "n_taken": 2400,
        },
    }
    tails = {
        BASELINE_ARM: {"worst": -36.2, "p1": -12.1, "p5": -7.0, "n": 2815},
        cand_arm: {"worst": -36.2 + tail_worst_d, "p1": -12.1 + tail_p1_d, "p5": -7.2, "n": 2400},
    }
    wf = {
        "star": star,
        "star_arm": cand_arm,
        "agreement": agreement,
        "picks": [cand_arm] * agreement,
        "per_fold": [],
        "proc": {"cagr": oos_proc, "max_dd": dd_proc, "final_equity": 0.0},
        "base": {"cagr": oos_base, "max_dd": dd_base, "final_equity": 0.0},
    }
    c5 = c5 or {
        "passes": True,
        "escalate_c9": False,
        "escalate_windows": [],
        "tolerance_pts": 1.0,
        "pooled_delta_pts": 0.4,
        "windows": {},
    }
    sweep = {}
    pts = [*list(C9_POINTS), C9_ESCALATION]
    for (rate, depth), d in zip(pts, c9, strict=True):
        sweep[f"d{depth:.2f}_r{rate:.4f}"] = {
            "rate": rate,
            "depth": depth,
            "dcagr_worst": d,
            "dcagr_mean": d,
            "base_cagr_mean": 0.0,
            "cand_cagr_mean": 0.0,
            "per_seed": [],
            "shape": "gradual",
            "digests_ok": True,
        }
    return dict(
        summaries=summaries,
        wf=wf,
        c5=c5,
        boot=(_Boot() if boot is None else boot),
        tails=tails,
        sens5={"dcagr": sens5},
        sens_close={"dcagr": sens_close},
        sweep=sweep,
    )


def test_los_nueve_pasan_y_shipea():
    v = evaluate(**_ctx())
    assert v["ship"] is True
    assert v["outcome"].startswith("SHIP")
    for k in (
        "c1_cagr_oos",
        "c2_maxdd",
        "c3_boot",
        "c4_sharpe",
        "c5_regime",
        "c6_tail",
        "c7_folds",
        "c8_spec",
        "c9_ruin",
    ):
        assert v[k] is True, k


@pytest.mark.parametrize(
    "kw,flag",
    [
        ({"oos_proc": 0.0150, "oos_base": 0.0141}, "c1_cagr_oos"),  # ΔOOS < +1.00 pp
        ({"dd_cand": 0.60}, "c2_maxdd"),  # maxDD in-sample
        ({"dd_proc": 0.40}, "c2_maxdd"),  # maxDD OOS
        ({"boot": _Boot(ci_low=-0.002)}, "c3_boot"),
        ({"sharpe_cand": 0.22}, "c4_sharpe"),  # ΔSharpe < +0.05
        ({"tail_worst_d": -3.0}, "c6_tail"),
        ({"tail_p1_d": -2.5}, "c6_tail"),
        ({"agreement": 3}, "c7_folds"),
        ({"sens5": -0.01}, "c8_spec"),
        ({"sens_close": -0.01}, "c8_spec"),
        ({"c9": (-0.01, 0.01, 0.01)}, "c9_ruin"),
        ({"c9": (0.01, -0.01, 0.01)}, "c9_ruin"),
    ],
)
def test_cualquier_criterio_que_falle_mata_el_ship(kw, flag):
    v = evaluate(**_ctx(**kw))
    assert v[flag] is False
    assert v["ship"] is False


def test_caso_partido_1_todo_menos_c9_es_el_resultado_mas_informativo():
    v = evaluate(**_ctx(c9=(-0.02, 0.01, 0.01)))
    assert v["ship"] is False and v["c9_ruin"] is False
    assert "survivorship" in v["outcome"]


def test_caso_partido_2_c1_pasa_pero_falla_c2_o_c6():
    for kw in ({"dd_cand": 0.60}, {"tail_worst_d": -3.0}):
        v = evaluate(**_ctx(**kw))
        assert v["ship"] is False
        assert "asumir riesgo" in v["outcome"]


def test_caso_partido_3_el_walkforward_elige_el_baseline():
    v = evaluate(**_ctx(star=(2.0, 2.0)))
    assert v["ship"] is False
    assert "POSITIVO" in v["outcome"] and "se gana su lugar" in v["outcome"]


def test_caso_partido_4_el_walkforward_elige_trailing_apagado():
    v = evaluate(**_ctx(star=(NO_STOP, NO_STOP)))
    assert v["ship"] is False
    assert v["shippable"] is False
    assert "POR CONSTRUCCIÓN" in v["outcome"]


def test_c5_bis_agrega_el_escalon_a_c9_y_puede_darlo_vuelta():
    """Sin escalada el candidato pasa C9; con escalada, el punto nuevo lo frena."""
    sin = evaluate(**_ctx(c9=(0.01, 0.01, -0.02)))
    assert sin["c9_ruin"] is True and sin["c9_escalated"] is False
    assert len(sin["c9_detail"]) == len(C9_POINTS)

    c5_esc = {
        "passes": True,
        "escalate_c9": True,
        "escalate_windows": ["stress_bear_2022"],
        "tolerance_pts": 1.0,
        "pooled_delta_pts": -0.2,
        "windows": {},
    }
    con = evaluate(**_ctx(c9=(0.01, 0.01, -0.02), c5=c5_esc))
    assert con["c9_escalated"] is True
    assert len(con["c9_detail"]) == len(C9_POINTS) + 1
    assert con["c9_ruin"] is False and con["ship"] is False
