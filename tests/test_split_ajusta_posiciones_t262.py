"""Tarea 262 — un split en una posición abierta se ajusta en vez de venderse con pérdida ficticia.

El defecto (``docs/auditoria_cuentas_2026-10-02.md`` [G-1]): el motor dejaba ``shares``,
``avg_cost`` y ``high_water_mark`` en la escala vieja; con el precio post-split la equity caía
(1−1/N) y el trailing vendía. El caso del ``run_scan`` de abajo está elegido para que la
versión con el defecto y la corregida **difieran**: con el máximo sin ajustar el trailing
queda en ~103 y vende a 51,2; ajustado queda en ~51 y no vende.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from database.models import session_scope, utcnow_naive
from paper_trading.splits import ajustes_pendientes, es_split_plausible

HOY = "2026-10-02"


def _pend(fills, eventos, ya=(), posiciones=None, hoy=HOY):
    return ajustes_pendientes(fills, eventos, set(ya), posiciones or {}, hoy)


# ── La función pura ──────────────────────────────────────────────────────────


def test_un_split_2_a_1_sobre_acciones_de_ANTES_las_duplica():
    pend, inc = _pend(
        [("AAA", "BUY", 10, "2026-09-01")], {"AAA": [("2026-09-15", 2.0)]}, posiciones={"AAA": 10}
    )
    assert inc == []
    assert [(p.ticker, p.ex_date, p.acciones_antes, p.acciones_despues) for p in pend] == [
        ("AAA", "2026-09-15", 10, 20)
    ]


def test_comprar_EL_DIA_del_ex_date_ya_es_post_split():
    pend, _ = _pend(
        [("AAA", "BUY", 10, "2026-09-15")], {"AAA": [("2026-09-15", 2.0)]}, posiciones={"AAA": 10}
    )
    assert pend == []


def test_un_split_VIEJO_de_un_ticker_comprado_despues_no_toca_nada():
    pend, _ = _pend(
        [("NVDA", "BUY", 4, "2026-09-23")], {"NVDA": [("2024-06-10", 10.0)]}, posiciones={"NVDA": 4}
    )
    assert pend == []


def test_dos_lotes_se_ajusta_SOLO_el_de_antes():
    fills = [("AAA", "BUY", 5, "2026-09-01"), ("AAA", "BUY", 5, "2026-09-20")]
    pend, _ = _pend(fills, {"AAA": [("2026-09-15", 2.0)]}, posiciones={"AAA": 10})
    assert pend[0].acciones_despues == pytest.approx(15)


def test_un_split_FANTASMA_no_se_aplica():
    pend, _ = _pend(
        [("AVB", "BUY", 10, "2026-07-01")], {"AVB": [("2026-08-17", 2.793)]}, posiciones={"AVB": 10}
    )
    assert pend == []


def test_un_split_ya_aplicado_no_se_aplica_dos_veces():
    pend, inc = _pend(
        [("AAA", "BUY", 10, "2026-09-01")],
        {"AAA": [("2026-09-15", 2.0)]},
        ya={("AAA", "2026-09-15")},
        posiciones={"AAA": 20},
    )
    assert pend == [] and inc == []


def test_un_split_FUTURO_todavia_no_se_aplica():
    pend, _ = _pend(
        [("AAA", "BUY", 10, "2026-09-01")], {"AAA": [("2026-10-10", 2.0)]}, posiciones={"AAA": 10}
    )
    assert pend == []


def test_un_reverse_split_1_a_10_divide():
    pend, _ = _pend(
        [("AAA", "BUY", 100, "2026-09-01")], {"AAA": [("2026-09-15", 0.1)]}, posiciones={"AAA": 100}
    )
    assert pend[0].acciones_despues == pytest.approx(10)


def test_si_la_historia_NO_reproduce_la_posicion_no_se_ajusta_y_se_avisa():
    """Ajustar a ciegas puede duplicar acciones: peor que el defecto que esto arregla."""
    pend, inc = _pend(
        [("AAA", "BUY", 10, "2026-09-01")], {"AAA": [("2026-09-15", 2.0)]}, posiciones={"AAA": 7}
    )
    assert pend == []
    assert [(x.ticker, x.esperadas, x.reales) for x in inc] == [("AAA", 10, 7)]


def test_dos_splits_nuevos_se_encadenan():
    pend, _ = _pend(
        [("AAA", "BUY", 10, "2026-08-01")],
        {"AAA": [("2026-08-15", 2.0), ("2026-09-15", 3.0)]},
        posiciones={"AAA": 10},
    )
    assert [p.acciones_despues for p in pend] == [pytest.approx(20), pytest.approx(60)]


@pytest.mark.parametrize("r", [2.0, 3.0, 1.5, 2.5, 25.0, 0.5, 0.1, 2.793, 1.3, 0.0, -2.0, None, 1.0, 51.0])
def test_el_criterio_de_plausible_es_EL_MISMO_que_el_del_guard_de_precio(r):
    """`paper_trading/` duplica el criterio para no depender de `data/yahoo_finance`."""
    from data.yahoo_finance import is_plausible_split

    esperado = is_plausible_split(r) and r != 1.0
    assert es_split_plausible(r) == esperado


# ── El cable: un run_scan real ───────────────────────────────────────────────


def _historia_post_split(_ticker):
    """60 ruedas alrededor de 51, con ATR ≈ 0,5: la escala nueva."""
    idx = pd.bdate_range(end=datetime(2026, 10, 1), periods=60)
    close = pd.Series(51.0 + 0.05 * np.sin(np.arange(60)), index=idx)
    return pd.DataFrame(
        {"Open": close, "High": close + 0.25, "Low": close - 0.25, "Close": close, "Volume": 1e6}
    )


class _SinEarnings:
    def __call__(self, ticker):
        return None

    def get_next_earnings_date(self, ticker):
        return None


def _montar(test_db):
    from config.settings_manager import settings
    from paper_trading.account import create_account
    from paper_trading.models import PaperOrder, PaperPosition

    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_anti_flap_minutes", 0)
    settings.set("paper_whipsaw_lookback_days", 0)
    settings.set("atr_stops_enabled", True)
    settings.set("atr_hard_stop_enabled", False)
    settings.set("atr_trail_mult", 2.0)
    settings.set("atr_tp_mult", 20.0)
    acct = create_account(name="Split", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(
            PaperOrder(
                account_id=acct.id,
                ticker="AAA",
                side="BUY",
                status="filled",
                fill_shares=10.0,
                fill_price=100.0,
                filled_at=datetime(2026, 9, 1, 15, 0),
            )
        )
        s.add(
            PaperPosition(
                account_id=acct.id,
                ticker="AAA",
                shares=10.0,
                avg_cost=100.0,
                high_water_mark=104.0,
                opened_at=datetime(2026, 9, 1, 15, 0),
            )
        )
    return acct.id


def _scan(acct_id, monkeypatch, eventos):
    from paper_trading import engine

    monkeypatch.setattr(engine, "_split_events_for", lambda tickers: {t: eventos.get(t, []) for t in tickers})
    ayer = (utcnow_naive() - timedelta(days=1)).strftime("%Y-%m-%d")
    return engine.run_scan(
        acct_id,
        prices_provider=lambda _t: {"AAA": 51.2},
        history_provider=_historia_post_split,
        earnings_provider=_SinEarnings(),
    ), ayer


def test_run_scan_AJUSTA_la_posicion_y_NO_vende(test_db, monkeypatch):
    from paper_trading.models import PaperOrder, PaperPosition, PaperSplitAdjustment

    acct_id = _montar(test_db)
    ex = (utcnow_naive() - timedelta(days=1)).strftime("%Y-%m-%d")
    result, _ = _scan(acct_id, monkeypatch, {"AAA": [(ex, 2.0)]})

    with session_scope() as s:
        pos = s.query(PaperPosition).filter(PaperPosition.account_id == acct_id).one()
        ventas = s.query(PaperOrder).filter(PaperOrder.account_id == acct_id, PaperOrder.side == "SELL").all()
        ledger = s.query(PaperSplitAdjustment).filter(PaperSplitAdjustment.account_id == acct_id).all()
        assert pos.shares == pytest.approx(20.0)
        assert pos.avg_cost == pytest.approx(50.0)
        assert pos.high_water_mark == pytest.approx(52.0, abs=0.5)  # 104/2, y el scan puede subirlo
        assert ventas == [], f"vendió con el split: {[v.reason for v in ventas]}"
        assert len(ledger) == 1 and ledger[0].ratio == 2.0
    assert any("split 2:1" in w for w in result.warnings), "el ajuste no se reporta"
    # La equity no salta: caja 10.000 + 20 × 51,2. Sin el ajuste sería 10.000 + 10 × 51,2.
    assert result.equity_before == pytest.approx(10_000.0 + 20 * 51.2, abs=0.01)


def test_SIN_el_ajuste_el_mismo_caso_VENDE_por_trailing(test_db, monkeypatch):
    """La otra mitad del caso: sin eventos de split, el trailing con el máximo viejo vende.

    Si este test pasara a no vender, el de arriba dejaría de probar algo.
    """
    from paper_trading.models import PaperOrder

    acct_id = _montar(test_db)
    _scan(acct_id, monkeypatch, {})
    with session_scope() as s:
        ventas = s.query(PaperOrder).filter(PaperOrder.account_id == acct_id, PaperOrder.side == "SELL").all()
        assert ventas and "atr_trail" in (ventas[0].reason or "")


def test_correr_DOS_scans_no_ajusta_dos_veces(test_db, monkeypatch):
    from paper_trading.models import PaperPosition, PaperSplitAdjustment

    acct_id = _montar(test_db)
    ex = (utcnow_naive() - timedelta(days=1)).strftime("%Y-%m-%d")
    _scan(acct_id, monkeypatch, {"AAA": [(ex, 2.0)]})
    _scan(acct_id, monkeypatch, {"AAA": [(ex, 2.0)]})
    with session_scope() as s:
        assert s.query(PaperPosition).filter(
            PaperPosition.account_id == acct_id
        ).one().shares == pytest.approx(20.0)
        assert s.query(PaperSplitAdjustment).count() == 1


def test_un_split_fantasma_en_run_scan_no_ajusta(test_db, monkeypatch):
    from paper_trading.models import PaperPosition, PaperSplitAdjustment

    acct_id = _montar(test_db)
    ex = (utcnow_naive() - timedelta(days=1)).strftime("%Y-%m-%d")
    _scan(acct_id, monkeypatch, {"AAA": [(ex, 2.793)]})
    with session_scope() as s:
        # Sin ajuste, el caso cae en la conducta de antes (el trailing con el máximo viejo):
        # lo que importa es que un ratio que no es un split NO multiplique acciones.
        assert s.query(PaperSplitAdjustment).count() == 0
        assert not any(
            p.shares > 10.0 for p in s.query(PaperPosition).filter(PaperPosition.account_id == acct_id).all()
        )
