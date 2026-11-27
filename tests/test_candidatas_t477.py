"""Tarea 477 (CANDIDATAS-DE-LA-REJILLA-T170) — tests offline del runner, antes de leer su veredicto.

El pre-registro (`docs/candidatas_rejilla_prereg_t477_2026-11-27.md`, `78d2d60`) congeló tres
cosas que estos tests custodian: la familia son **las 14** celdas y no las cuatro que marcó la 472;
una celda pasa con **las seis** (M1, D1, D2, D3, D5 y C9); y el C9 compara contra **la viva**, no
contra el `s2.0_t2.0` que el `ruin_sweep` de la T37 tiene clavado.
"""

from __future__ import annotations

import io
import math
from types import SimpleNamespace

import pytest

import scripts.run_candidatas_t477 as m
from scripts.run_exit_policy_t170 import D1_MIN_DCAGR_OOS, D2_MIN_FOLDS, D3_TAIL_TOL_PTS, D5_DD_TOL
from scripts.run_stop_value_t37 import arm_name, grid_cells

# ── §3 — la familia ──────────────────────────────────────────────────────────


def test_la_familia_son_las_14_celdas_sin_la_viva():
    assert len(m.FAMILIA) == 14
    assert m.POLICY_CELL not in m.FAMILIA
    assert set(m.FAMILIA) | {m.POLICY_CELL} == set(grid_cells())


def test_los_umbrales_son_los_del_preregistro():
    assert m.M1_ALPHA == 0.05
    assert (m.D1_MIN_DCAGR_OOS, m.D2_MIN_FOLDS, m.D3_TAIL_TOL_PTS, m.D5_DD_TOL) == (
        D1_MIN_DCAGR_OOS,
        D2_MIN_FOLDS,
        D3_TAIL_TOL_PTS,
        D5_DD_TOL,
    )
    assert m.C9_POINTS == ((0.026, 0.50), (0.0047, 0.70))
    assert m.C9_MIN_DCAGR == 0.0
    assert (m.BOOT_BLOCK, m.BOOT_RESAMPLES, m.BOOT_SEED) == (20, 2000, 12345)


# ── §4 — hacen falta las seis ────────────────────────────────────────────────

_BUENA = dict(
    p_adj=0.01,
    dcagr_oos=0.02,
    folds=4,
    d_worst=-1.0,
    d_p1=-1.0,
    ddd_is=0.005,
    ddd_oos=0.0,
    c9_worst=[0.0, 0.001],
)


def test_con_las_seis_pasa():
    v = m.evaluar_celda(**_BUENA)
    assert v["pasa"] is True and v["medible"] is True


@pytest.mark.parametrize(
    ("cambio", "falla"),
    [
        ({"p_adj": 0.05}, "M1"),
        ({"dcagr_oos": 0.0099}, "D1"),
        ({"folds": 3}, "D2"),
        ({"d_worst": -2.01}, "D3"),
        ({"d_p1": -2.01}, "D3"),
        ({"ddd_is": 0.0101}, "D5"),
        ({"ddd_oos": 0.0101}, "D5"),
        ({"c9_worst": [0.001, -0.0001]}, "C9"),
    ],
)
def test_basta_que_UNA_falle_para_no_pasar(cambio, falla):
    v = m.evaluar_celda(**{**_BUENA, **cambio})
    assert v[falla] is False
    assert v["pasa"] is False


def test_sin_p_ajustado_o_sin_los_dos_puntos_de_ruina_no_se_puede_medir():
    assert m.evaluar_celda(**{**_BUENA, "p_adj": math.nan})["medible"] is False
    sin_ruina = m.evaluar_celda(**{**_BUENA, "c9_worst": [0.01]})
    assert sin_ruina["medible"] is False and sin_ruina["pasa"] is False


# ── El cache distingue el marco ──────────────────────────────────────────────


def test_el_tag_cambia_con_el_orden_y_con_el_costo():
    """`arm_fingerprint` no mira ni el orden ni el costo: sin esto, el cache devolvería el marco
    alfabético como si fuera el del vivo (la lección de la 466)."""
    base = SimpleNamespace(
        universe="u.txt", max_positions=10, cap_days=250, capital=50_000.0, orden="vivo", costo="vivo"
    )
    tags = {
        m.run_tag_de("w", 126, 100, SimpleNamespace(**{**vars(base), **cambio}))
        for cambio in ({}, {"orden": "alfabetico"}, {"costo": "harness"})
    }
    assert len(tags) == 3


# ── M1 sobre las 14 a la vez; C9 contra la viva ──────────────────────────────


def _curva(paso: float, n: int = 40) -> list[tuple[str, float]]:
    from datetime import date, timedelta

    d0 = date(2022, 1, 3)
    return [((d0 + timedelta(days=k)).isoformat(), 1000.0 * (1.0 + paso) ** k) for k in range(n)]


def test_M1_corre_sobre_las_14_a_la_vez_con_la_viva_de_referencia(monkeypatch):
    visto = {}

    def _falso(base, cands, **kw):
        visto["base"], visto["cands"], visto["kw"] = base, cands, kw
        return "rw"

    monkeypatch.setattr(m, "romano_wolf_stepdown", _falso)
    curvas = {arm_name(*c): {"curve": _curva(0.001)} for c in m.FAMILIA}
    curvas[m.POLICY_ARM] = {"curve": _curva(0.0)}
    assert m.m1_romano_wolf(curvas, 1000.0, resamples=7) == "rw"
    assert sorted(visto["cands"]) == sorted(arm_name(*c) for c in m.FAMILIA)
    assert all(r == 0.0 for r in visto["base"])  # la viva es la plana
    assert visto["kw"] == {"block": 20, "n_resamples": 7, "seed": 12345}


def test_C9_compara_contra_la_viva_y_no_contra_el_s2_t2_de_la_T37(monkeypatch):
    llamadas: list[tuple[str, float, float]] = []

    def _sim(tag, entries, bars, sigs, **kw):
        a = kw["atr_p"]
        llamadas.append((tag.split("|")[5], a.stop_mult, a.trail_mult))
        # La viva rinde menos que cualquier celda: todos los Δ quedan positivos.
        paso = 0.0 if tag.split("|")[5] == m.POLICY_ARM else 0.001
        return SimpleNamespace(equity_curve=_curva(paso))

    monkeypatch.setattr(m, "_sim", _sim)
    monkeypatch.setattr(m, "inject_ruin", lambda bars, **kw: (bars, []))
    monkeypatch.setattr(m, "bars_digest", lambda bars: "d")
    out = m.ruina_c9([], {"AAA": []}, {}, {}, tag="t", log=io.StringIO())
    bases = [x for x in llamadas if x[0] == m.POLICY_ARM]
    assert bases and all((s, t) == m.POLICY_CELL for _, s, t in bases)
    assert not any(x[0] == "s2.0_t2.0" and (x[1], x[2]) == m.POLICY_CELL for x in llamadas)
    # Un mundo por (punto, semilla), y lo ven la viva y las 14.
    assert len(llamadas) == len(m.C9_POINTS) * len(m.ruin_seeds()) * 15
    assert out["digests_ok"] is True
    assert all(d["dcagr_worst"] > 0 for celda in out["celdas"].values() for d in celda.values())


# ── §5 — el sanity ───────────────────────────────────────────────────────────


def _summaries(*, orc_cagr=0.12, orc_dd=0.25, viva_cagr=0.0975, tomados=2325):
    s = {
        arm_name(*c): {"cagr": 0.10, "max_dd": 0.3, "n_taken": 2000, "accounting_ok": True, "exit_mix": {}}
        for c in grid_cells()
    }
    s[m.POLICY_ARM] = {**s[m.POLICY_ARM], "cagr": viva_cagr, "n_taken": tomados}
    s[m.ORACLE_ARM] = {"cagr": orc_cagr, "max_dd": orc_dd, "accounting_ok": True}
    s[m.RANDOM_KEEP_ARM] = {"cagr": 0.10, "max_dd": 0.31, "accounting_ok": True}
    return s


def test_el_marco_primario_exige_el_ancla_de_la_473():
    ok = m.evaluar_sanity(_summaries(), orden="vivo", costo="vivo", curvas={}, digests_ok=True)
    assert ok["all_ok"] is True
    otra = m.evaluar_sanity(_summaries(tomados=2531), orden="vivo", costo="vivo", curvas={}, digests_ok=True)
    assert otra["all_ok"] is False and otra["repro"]["viva_tomados"][2] is False


def test_un_oraculo_que_no_baja_la_caida_5_pp_invalida_la_corrida():
    """Es el sanity que falló en el marco primario: +2,37 pp de CAGR pero −3,61 de caída."""
    s = m.evaluar_sanity(_summaries(orc_dd=0.2739), orden="vivo", costo="vivo", curvas={}, digests_ok=True)
    assert s["oraculo_ok"] is False and s["all_ok"] is False


def test_la_barrera_off_que_dispara_invalida_la_corrida():
    s = _summaries()
    s["soff_toff"]["exit_mix"] = {"atr_trail": 0.01}
    out = m.evaluar_sanity(s, orden="vivo", costo="vivo", curvas={}, digests_ok=True)
    assert out["mecanico_ok"] is False and out["all_ok"] is False
