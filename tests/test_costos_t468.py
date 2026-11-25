"""Tarea 468 — COSTOS-DEL-HARNESS: el harness cobra 0,15% por lado y el vivo ~0,063%.

``CostModel()`` (0,10% de comisión + 0,05% de slippage) se declaraba *«espejo de la cuenta viva»*, y
la auditoría del 2026-09-02 lo dio por *«coinciden exacto»*. Desde el 2026-05-18 el motor cobra con
``get_active_commission_model()``, IBKR Pro Tiered por default: por acción, con mínimo y tasas en la
venta. Sobre las 238 órdenes de la cuenta 2 el modelo reproduce cada comisión exacta, y el porcentaje
efectivo da 0,0118% en compras y 0,0145% en ventas.

Lo que fija este archivo:

1. **Que el vivo cobra IBKR Tiered:** el modelo reproduce la comisión de órdenes reales (abajo, con su
   fecha), elegidas para cubrir precios, tamaños y los dos lados. Es el hecho que la auditoría se
   perdió, y si el motor cambiara de modelo, esto se pone rojo.
2. **Que el modelo del vivo del harness sale de esa medición**, y que el de ``CostModel()`` es el de
   todo lo publicado.
3. **Que el desvío se declara** mientras un runner cobre distinto del vivo, y deja de declararse
   cuando cobra lo mismo.
"""

from __future__ import annotations

import pytest

from analysis.harness_config import (
    HARNESS_DEFAULT_COST_PER_SIDE,
    LIVE_COMMISSION_BUY_PCT,
    LIVE_COMMISSION_PCT,
    LIVE_COMMISSION_SELL_PCT,
    LIVE_COST_PER_SIDE,
    LIVE_MAX_POSITIONS,
    LIVE_SLIPPAGE_PCT,
    LIVE_WATCHLIST_SIZE,
    HarnessConfig,
    announce,
    deviations_keyed,
    live_cost_model,
)
from analysis.scaleout_replay import CostModel
from paper_trading.costs import IBKRProCommission, get_active_commission_model, make_ibkr_pro_tiered

# (ticker, lado, acciones, precio de fill, commission_paid) de `paper_orders` de la cuenta 2, leídos
# de una copia de la DB el 2026-11-24. Del ticket mínimo (1 acción) al más grande, y los dos lados.
_FILLS_REALES = [
    ("KMI", "SELL", 1.0, 31.354315000000003, 0.354072649957),  # 2026-09-04, el notional más chico
    ("VZ", "BUY", 67.0, 44.717347499999995, 0.553345),  # 2026-10-23
    ("AMD", "SELL", 7.0, 599.5600553588868, 0.48908138677283935),  # 2026-10-12
    ("MS", "SELL", 28.0, 207.346275, 0.60102634046),  # 2026-08-20
    ("C", "BUY", 134.0, 137.88890999999998, 0.87569),  # 2026-09-04, el notional más grande
    ("CVS", "SELL", 5.0, 93.70421147883404, 0.37902988539555793),  # 2026-09-09
    ("CSCO", "SELL", 117.0, 106.64665000000001, 1.1308958937900002),  # 2026-09-28
    ("C", "SELL", 134.0, 131.70411500000003, 1.3885581691980002),  # 2026-09-20
    ("META", "BUY", 1.0, 596.51811, 0.353035),  # 2026-11-20, una sola acción cara
    ("GS", "SELL", 1.0, 935.5070125000001, 0.37920809494749996),  # 2026-09-23
]


@pytest.mark.parametrize(
    "ticker,lado,acciones,precio,pagado", _FILLS_REALES, ids=[f[0] + f[1] for f in _FILLS_REALES]
)
def test_el_motor_cobra_IBKR_tiered_en_las_ordenes_reales(ticker, lado, acciones, precio, pagado):
    assert make_ibkr_pro_tiered().cost(side=lado, shares=acciones, price=precio) == pytest.approx(
        pagado, rel=1e-9
    )


def test_y_ese_es_el_modelo_activo_por_default():
    """Sin `ibkr_commission_plan` en el settings (el conftest lo aísla), el motor elige Tiered."""
    m = get_active_commission_model()
    assert isinstance(m, IBKRProCommission)
    assert (m.per_share, m.min_fee, m.exchange_fee_per_share) == (0.0035, 0.35, 0.003)


def test_y_no_es_el_porcentaje_del_harness():
    """La contraprueba de la auditoría: con el 0,10% de `CostModel()`, ninguna orden real cierra."""
    for _t, _lado, acciones, precio, pagado in _FILLS_REALES:
        assert acciones * precio * CostModel().commission != pytest.approx(pagado, rel=0.05)


def test_el_modelo_del_vivo_sale_de_la_medicion():
    assert (
        pytest.approx((LIVE_COMMISSION_BUY_PCT + LIVE_COMMISSION_SELL_PCT) / 2, abs=5e-6)
        == LIVE_COMMISSION_PCT
    )
    cm = live_cost_model()
    assert (cm.commission, cm.slippage) == (LIVE_COMMISSION_PCT, LIVE_SLIPPAGE_PCT)
    assert cm.commission + cm.slippage == pytest.approx(LIVE_COST_PER_SIDE)
    assert 0.0006 < LIVE_COST_PER_SIDE < 0.00065, "~0,063% por lado, medido el 2026-11-24"


def test_el_default_del_harness_es_el_de_CostModel():
    """El literal existe porque `scaleout_replay` importa de `harness_config`; esto lo ata."""
    assert pytest.approx(CostModel().commission + CostModel().slippage) == HARNESS_DEFAULT_COST_PER_SIDE
    assert pytest.approx(2.38, abs=0.01) == HARNESS_DEFAULT_COST_PER_SIDE / LIVE_COST_PER_SIDE


def _claves(**kw) -> dict[str, str]:
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE, **kw)
    return {d.clave: d.texto for d in deviations_keyed(cfg)}


def test_un_runner_que_no_declara_el_costo_declara_el_desvio():
    """Mutación: poner el default de `HarnessConfig.costo_por_lado` en el del vivo → rojo, porque
    todo runner que corre con `CostModel()` dejaría de declararlo."""
    t = _claves()["costos"]
    assert "0.150% por lado" in t and "0.063%" in t and "tarea 468" in t


def test_con_el_costo_del_vivo_no_se_declara():
    assert "costos" not in _claves(costo_por_lado=LIVE_COST_PER_SIDE)
    assert "costos" in _claves(costo_por_lado=0.0), "a costo cero también difiere del vivo"


def test_announce_pasa_el_costo(capsys):
    cfg = announce(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE, costo_por_lado=LIVE_COST_PER_SIDE)
    assert cfg.costo_por_lado == LIVE_COST_PER_SIDE
    assert "IBKR Pro Tiered" not in capsys.readouterr().out
    announce(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE)
    assert "IBKR Pro Tiered" in capsys.readouterr().out
