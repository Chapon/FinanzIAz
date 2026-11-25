"""Tarea 469 — RELECTURA-POR-COSTO: `--costo {harness,vivo}` en los runners de la T219 y la T170.

Los veredictos que compararon brazos de rotación distinta se midieron con `CostModel()` (0,15% por
lado); el vivo paga ~0,063% (468). Para releerlos sin tocar su pre-registro, los dos runners que
deciden la salida viva ganan una opción de costo. Lo que se fija:

1. **Sin la opción, el costo es el del harness**, también para todos los runners que importan
   `_common_kwargs` de la T219 sin saber de ella: nada publicado se mueve.
2. **Un nombre desconocido es un error**, no el costo del harness: un typo publicaría como
   re-lectura una corrida que no lo es.
3. **El ancla de reproducción sigue al costo:** la T170 al del harness, la 468 al del vivo, en los
   dos runners. Con la del harness, una corrida al costo del vivo tiene que salir INVÁLIDA.
4. **Con otro costo, el tag del cache de la T170 cambia** (la lección de la 466): si no, el cache
   devolvería los brazos del harness como si fueran la re-lectura.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import scripts.run_exit_policy_t170 as t170
import scripts.run_signal_exit_delay_t219 as t219
from analysis.harness_config import (
    COSTO_HARNESS,
    COSTO_VIVO,
    HARNESS_DEFAULT_COST_PER_SIDE,
    LIVE_COST_PER_SIDE,
    costo_del_runner,
)
from analysis.scaleout_replay import CostModel


def _args(**kw):
    base = dict(max_positions=10, capital=50_000.0, cap_days=250)
    base.update(kw)
    return SimpleNamespace(**base)


def _por_lado(cm: CostModel) -> float:
    return cm.commission + cm.slippage


# ── 1. sin la opción, el del harness ─────────────────────────────────────────


def test_sin_la_opcion_common_kwargs_cobra_el_del_harness():
    cm = t219._common_kwargs(_args())["costs"]
    assert cm == CostModel()
    assert _por_lado(cm) == pytest.approx(HARNESS_DEFAULT_COST_PER_SIDE)


def test_con_la_opcion_cobra_el_que_se_pide():
    assert t219._common_kwargs(_args(costo=COSTO_HARNESS))["costs"] == CostModel()
    vivo = t219._common_kwargs(_args(costo=COSTO_VIVO))["costs"]
    assert _por_lado(vivo) == pytest.approx(LIVE_COST_PER_SIDE)
    assert vivo != CostModel()


# ── 2. un nombre desconocido es un error ─────────────────────────────────────


@pytest.mark.parametrize("malo", ["Vivo", "live", "", "harnes"])
def test_un_costo_desconocido_no_cae_al_del_harness(malo):
    with pytest.raises(ValueError, match="costo desconocido"):
        costo_del_runner(malo)
    with pytest.raises(ValueError, match="costo desconocido"):
        t219.ancla_del_costo(malo)
    with pytest.raises(ValueError, match="costo desconocido"):
        t170.repro_targets_del_costo(malo)


# ── 3. el ancla sigue al costo ────────────────────────────────────────────────


def _base(cagr: float, sharpe: float, n: int = 2531) -> dict:
    return {"cagr": cagr, "sharpe": sharpe, "n_taken": n}


def test_el_ancla_de_la_t219_sigue_al_costo():
    assert t219.ancla_del_costo(COSTO_HARNESS) == (0.0878, 0.55, 2531)
    assert t219.ancla_del_costo(COSTO_VIVO) == (0.1372, 0.79, 2531)
    vivo = _base(0.1372, 0.79)
    assert t219.reproduce_t170(vivo, t219.ancla_del_costo(COSTO_VIVO))["OK"]
    # Con el ancla del harness, la corrida al costo del vivo NO reproduce: tiene que salir inválida.
    assert not t219.reproduce_t170(vivo)["OK"]
    assert not t219.reproduce_t170(vivo, t219.ancla_del_costo(COSTO_HARNESS))["OK"]
    assert t219.reproduce_t170(_base(0.0878, 0.55))["OK"]


def test_el_ancla_de_la_t170_sigue_al_costo():
    assert t170.repro_targets_del_costo(COSTO_HARNESS) == t170._repro_targets()
    assert t170.repro_targets_del_costo(COSTO_VIVO) == {t170.POLICY_ARM: 0.1372}
    assert t170.POLICY_ARM == "soff_t2.0"


# ── 4. el tag del cache cambia con el costo ──────────────────────────────────


def test_la_opcion_existe_en_los_dos_runners_con_el_harness_por_default():
    import inspect

    for mod in (t219, t170):
        fuente = inspect.getsource(mod.main)
        assert '"--costo"' in fuente and "default=COSTO_HARNESS" in fuente
    # La T170 cachea por tag: con otro costo, el tag lleva el costo; con el del harness, el de siempre.
    fuente = inspect.getsource(t170.main)
    assert 'if args.costo != COSTO_HARNESS:\n        run_tag += f"|costo={args.costo}"' in fuente
    # Y las dos sanity usan el ancla del costo pedido, no la del harness fija.
    assert "repro_targets_del_costo(args.costo)" in fuente and "_repro_targets()" not in fuente
    assert "evaluar_sanity(res, ancla_del_costo(args.costo))" in inspect.getsource(t219.main)
