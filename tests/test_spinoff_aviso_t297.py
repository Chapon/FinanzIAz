"""Tarea 297 — un factor de Yahoo que no es un split, en el ex-date de una posición abierta, se avisa.

Yahoo publica el spin-off de HON (2026-06-29) como ``Stock Splits = 0,9535`` (``1907:2000``).
La 262 no lo ajusta, y hace bien: no es una fracción simple. (Ese factor es un spin-off **más un
reverse split 1:2** el mismo día; la 298 lo verificó contra la SEC y explica por qué no se ajusta
solo.) Pero antes pasaba en silencio: una posición que lo atravesó quedaba con un valor falso. Ahora el scan lo
reporta, y el log y Slack lo dicen una vez por evento.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from database.models import session_scope, utcnow_naive
from paper_trading.splits import DIAS_AVISO_FACTOR, factores_sin_tratar

HOY = "2026-07-01"


def _hallados(fills, eventos, posiciones, hoy=HOY):
    return [
        (f.ticker, f.ex_date, f.ratio, f.acciones_al_ex)
        for f in factores_sin_tratar(fills, eventos, posiciones, hoy)
    ]


# ── La función pura ──────────────────────────────────────────────────────────


def test_el_spin_off_de_HON_con_la_posicion_de_ANTES_se_detecta():
    assert _hallados([("HON", "BUY", 8, "2026-06-20")], {"HON": [("2026-06-29", 0.9535)]}, {"HON": 8}) == [
        ("HON", "2026-06-29", 0.9535, 8)
    ]


def test_comprar_EL_DIA_del_ex_date_no_lo_atraviesa():
    """Es el caso real de la cuenta 2: compró HON el 2026-06-29 mismo."""
    assert (
        _hallados([("HON", "BUY", 8, "2026-06-29 14:15:21")], {"HON": [("2026-06-29", 0.9535)]}, {"HON": 8})
        == []
    )


def test_un_split_PLAUSIBLE_no_es_asunto_de_este_aviso():
    """Ese lo ajusta la 262; avisarlo además diría que no se ajustó."""
    assert _hallados([("AAA", "BUY", 10, "2026-06-20")], {"AAA": [("2026-06-29", 2.0)]}, {"AAA": 10}) == []


def test_un_dato_podrido_como_el_de_AVB_tambien_se_avisa():
    assert _hallados([("AVB", "BUY", 5, "2026-06-20")], {"AVB": [("2026-06-29", 2.793)]}, {"AVB": 5}) == [
        ("AVB", "2026-06-29", 2.793, 5)
    ]


def test_fuera_de_la_ventana_no_se_repite():
    """Los spin-offs viejos de HON (1,061 en 2025) no avisan para siempre."""
    viejo = "2026-06-20"
    hoy = (datetime.fromisoformat(viejo) + timedelta(days=DIAS_AVISO_FACTOR + 1)).strftime("%Y-%m-%d")
    assert _hallados([("HON", "BUY", 8, "2026-06-01")], {"HON": [(viejo, 0.9535)]}, {"HON": 8}, hoy=hoy) == []
    # El borde de la ventana todavía avisa: el caso de arriba no es vacío por otra razón.
    hoy_borde = (datetime.fromisoformat(viejo) + timedelta(days=DIAS_AVISO_FACTOR)).strftime("%Y-%m-%d")
    assert (
        len(
            _hallados(
                [("HON", "BUY", 8, "2026-06-01")], {"HON": [(viejo, 0.9535)]}, {"HON": 8}, hoy=hoy_borde
            )
        )
        == 1
    )


def test_un_ex_date_FUTURO_todavia_no_se_avisa():
    assert _hallados([("HON", "BUY", 8, "2026-06-20")], {"HON": [("2026-07-05", 0.9535)]}, {"HON": 8}) == []


def test_si_se_vendio_todo_antes_del_ex_date_no_lo_atravesó():
    fills = [
        ("HON", "BUY", 8, "2026-06-10"),
        ("HON", "SELL", 8, "2026-06-15"),
        ("HON", "BUY", 4, "2026-06-30"),
    ]
    assert _hallados(fills, {"HON": [("2026-06-29", 0.9535)]}, {"HON": 4}) == []


# ── El cable: un run_scan real ───────────────────────────────────────────────


class _SinEarnings:
    def __call__(self, ticker):
        return None

    def get_next_earnings_date(self, ticker):
        return None


def _historia(_ticker):
    import numpy as np
    import pandas as pd

    idx = pd.bdate_range(end=utcnow_naive().date(), periods=60)
    close = pd.Series(100.0 + 0.05 * np.sin(np.arange(60)), index=idx)
    return pd.DataFrame(
        {"Open": close, "High": close + 0.25, "Low": close - 0.25, "Close": close, "Volume": 1e6}
    )


def _montar():
    from config.settings_manager import settings
    from paper_trading.account import create_account
    from paper_trading.models import PaperOrder, PaperPosition

    settings.set("paper_enforce_market_hours", False)
    settings.set("slack_notifications_enabled", True)
    acct = create_account(name="Spinoff", initial_capital=10_000.0)
    abierta = utcnow_naive() - timedelta(days=20)
    with session_scope() as s:
        s.add(
            PaperOrder(
                account_id=acct.id,
                ticker="AAA",
                side="BUY",
                status="filled",
                fill_shares=10.0,
                fill_price=100.0,
                filled_at=abierta,
            )
        )
        s.add(
            PaperPosition(
                account_id=acct.id,
                ticker="AAA",
                shares=10.0,
                avg_cost=100.0,
                high_water_mark=101.0,
                opened_at=abierta,
            )
        )
    return acct.id


def _scan(acct_id, monkeypatch, eventos, avisos):
    from paper_trading import engine

    monkeypatch.setattr(engine, "_split_events_for", lambda tickers: {t: eventos.get(t, []) for t in tickers})
    return engine.run_scan(
        acct_id,
        prices_provider=lambda _t: {"AAA": 100.0},
        history_provider=_historia,
        earnings_provider=_SinEarnings(),
        slack_notifier=avisos.append,
    )


@pytest.fixture
def _sin_avisados(monkeypatch):
    from paper_trading import engine

    monkeypatch.setattr(engine, "_factores_announced", set())


def test_run_scan_AVISA_el_factor_y_no_toca_la_posicion(test_db, monkeypatch, _sin_avisados):
    from paper_trading.models import PaperPosition, PaperSplitAdjustment

    acct_id = _montar()
    ex = (utcnow_naive() - timedelta(days=1)).strftime("%Y-%m-%d")
    avisos: list[str] = []
    result = _scan(acct_id, monkeypatch, {"AAA": [(ex, 0.9535)]}, avisos)

    assert [(f["ticker"], f["ex_date"], f["ratio"]) for f in result.factores_sin_tratar] == [
        ("AAA", ex, 0.9535)
    ]
    assert any("no es un split" in w and "AAA" in w for w in result.warnings)
    assert len(avisos) == 1 and "AAA" in avisos[0] and "0.9535" in avisos[0]
    with session_scope() as s:
        pos = s.query(PaperPosition).filter(PaperPosition.account_id == acct_id).one()
        assert (pos.shares, pos.avg_cost) == (10.0, 100.0)
        assert s.query(PaperSplitAdjustment).count() == 0


def test_SIN_el_evento_el_mismo_scan_no_avisa_nada(test_db, monkeypatch, _sin_avisados):
    """La otra mitad: el aviso de arriba lo produce el evento, no el resto del montaje."""
    acct_id = _montar()
    avisos: list[str] = []
    result = _scan(acct_id, monkeypatch, {}, avisos)
    assert result.factores_sin_tratar == []
    assert not any("no es un split" in w for w in result.warnings)
    assert avisos == []


def test_un_segundo_scan_reporta_pero_NO_repite_el_slack(test_db, monkeypatch, _sin_avisados):
    acct_id = _montar()
    ex = (utcnow_naive() - timedelta(days=1)).strftime("%Y-%m-%d")
    avisos: list[str] = []
    _scan(acct_id, monkeypatch, {"AAA": [(ex, 0.9535)]}, avisos)
    segundo = _scan(acct_id, monkeypatch, {"AAA": [(ex, 0.9535)]}, avisos)
    assert len(avisos) == 1
    assert any("no es un split" in w for w in segundo.warnings), "el scan deja de reportarlo"


def test_el_aviso_nombra_la_ganancia_fantasma_y_las_acciones_que_no_son_las_reales():
    """Tarea 298: el aviso decía sólo «la caída puede figurar como pérdida». Con un split en el
    mismo evento (HON 2026: spin-off + reverse 1:2) pasa lo contrario —una ganancia fantasma— y
    la posición tiene el doble de acciones. Quien revisa a mano tiene que saber qué mirar."""
    from paper_trading.engine import _texto_factor_sin_tratar
    from paper_trading.splits import FactorSinTratar

    texto = _texto_factor_sin_tratar(FactorSinTratar("HON", "2026-06-29", 0.9535, 10.0))
    assert "ganancia" in texto and "pérdida" in texto
    assert "cantidad de acciones no es la real" in texto
