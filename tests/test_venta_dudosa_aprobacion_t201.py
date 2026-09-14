"""Tarea 201 — cuando la segunda opinión decide el precio, el scan hace lo que decidió Chapa.

Decisión del 2026-09-13, para una posición cuyo precio de Yahoo vino fuera de banda con
los frames cacheados en disputa:

| la fuente independiente…      | precio del scan | venta por señal         | stop        | compra     |
|-------------------------------|-----------------|-------------------------|-------------|------------|
| respalda el cierre guardado   | el independiente| pendiente + aviso Slack | sale sola   | bloqueada  |
| no coincide con ninguno       | ninguno         | no se evalúa + aviso    | no corre    | —          |
| respalda a Yahoo / no contesta| Yahoo           | como siempre            | como siempre| como siempre|

**Lo que corrigió la decisión, y por qué existe este archivo así:** la primera versión de
la tarea suponía que con el flag prendido la venta «se frena hasta el próximo scan». No:
el fetch descartaba el precio y la posición quedaba **sin evaluar** —ni señal ni stops—.
Por eso el precio independiente reemplaza al de Yahoo en vez de sólo rechazarlo.

Los tests de acá corren ``run_scan`` de verdad sobre la DB en memoria. Lo simulado es la
estrategia (una venta o compra fija), el proveedor de precios (lo que el fetch habría
entregado) y el registro de veredictos, que la capa de fetch ya prueba en
``test_second_opinion_primer_rechazo_t200.py`` y más abajo.
"""

from __future__ import annotations

import pandas as pd
import pytest

from config.settings_manager import settings
from data import yahoo_finance as yfm
from database.models import session_scope, utcnow_naive
from paper_trading import engine
from paper_trading.account import create_account
from paper_trading.models import PaperOrder, PaperPosition, PaperWatchlistItem
from paper_trading.strategies import TargetTrade

YAHOO_CORRUPTO = 1000.0
CIERRE = 100.0
INDEPENDIENTE = 101.0


@pytest.fixture(autouse=True)
def _limpio(monkeypatch):
    yfm._clear_opinion_log()
    yfm._clear_second_opinion_cache()
    engine._disputes_announced.clear()
    # El guard del fill mira el histórico cacheado: en la DB de test no hay, y se fija
    # explícito para que el test no dependa de eso.
    monkeypatch.setattr(yfm, "reference_close", lambda t: CIERRE)
    monkeypatch.setattr(yfm, "scale_drift", lambda t: None)
    yield
    yfm._clear_opinion_log()
    yfm._clear_second_opinion_cache()
    engine._disputes_announced.clear()


def _cuenta(test_db, *, ticker="AAPL", mode="auto", watchlist_extra=()):
    settings.set("atr_stops_enabled", False)
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_min_holding_minutes", 0)
    settings.set("paper_anti_flap_minutes", 0)
    settings.set("earnings_blackout_days", 0)
    settings.set("paper_signal_sell_min_age_bdays", 0)
    settings.set("slack_notifications_enabled", True)
    a = create_account(name="T201", initial_capital=10_000.0, mode=mode)
    with session_scope() as s:
        s.add(
            PaperPosition(
                account_id=a.id,
                ticker=ticker,
                shares=10.0,
                avg_cost=CIERRE,
                opened_at=utcnow_naive(),
                high_water_mark=CIERRE,
            )
        )
        s.add(PaperWatchlistItem(account_id=a.id, ticker=ticker))
        for extra in watchlist_extra:
            s.add(PaperWatchlistItem(account_id=a.id, ticker=extra))
    return a.id


def _estrategia(monkeypatch, side="SELL", ticker="AAPL"):
    def strat(account, watchlist, positions, prices, history_provider):
        return [
            TargetTrade(
                ticker=ticker,
                side=side,
                target_shares=10.0 if side == "SELL" else None,
                target_dollars=None if side == "SELL" else 500.0,
                reason=f"analyze {side} (0.10)",
                source="analyze_single",
                signal_score=0.10,
            )
        ]

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: strat)


def _veredicto(verdict="reference", ticker="AAPL", independiente=INDEPENDIENTE):
    yfm._record_opinion(ticker, YAHOO_CORRUPTO, CIERRE, independiente, verdict)


def _scan(acct_id, precios, avisos=None, history=None):
    return engine.run_scan(
        acct_id,
        prices_provider=lambda _t: dict(precios),
        history_provider=history or (lambda _t: None),
        earnings_provider=lambda _t: None,
        slack_notifier=(avisos.append if avisos is not None else (lambda _m: None)),
    )


def _ordenes(acct_id):
    with session_scope() as s:
        return [
            (o.side, o.status, o.notes or "")
            for o in s.query(PaperOrder).filter(PaperOrder.account_id == acct_id).order_by(PaperOrder.id)
        ]


# ── Fila 1: la fuente independiente respalda el cierre guardado ──────────────


def test_venta_por_senal_sobre_precio_sustituido_queda_PENDIENTE_en_cuenta_auto(test_db, monkeypatch):
    acct = _cuenta(test_db)
    _estrategia(monkeypatch)
    _veredicto()
    avisos: list[str] = []

    r = _scan(acct, {"AAPL": INDEPENDIENTE}, avisos)

    assert r.filled == 0 and r.queued == 1
    [(side, status, notes)] = _ordenes(acct)
    assert (side, status) == ("SELL", "pending")
    assert notes.startswith(engine.DISPUTE_NOTE_TAG)
    with session_scope() as s:
        assert s.query(PaperPosition).filter(PaperPosition.account_id == acct).one().shares == 10.0
    disputa = [m for m in avisos if "precio en disputa" in m]
    assert len(disputa) == 1 and "AAPL" in disputa[0] and "espera aprobación" in disputa[0]


def test_la_compra_sobre_precio_sustituido_se_BLOQUEA(test_db, monkeypatch):
    acct = _cuenta(test_db, ticker="MSFT", watchlist_extra=("AAPL",))
    _estrategia(monkeypatch, side="BUY", ticker="AAPL")
    _veredicto()

    r = _scan(acct, {"AAPL": INDEPENDIENTE, "MSFT": 50.0})

    assert r.filled == 0 and r.queued == 0
    assert _ordenes(acct) == []
    assert any("BUY bloqueado" in w and "segunda opinión" in w for w in r.warnings)


def test_el_STOP_sale_solo_sobre_el_precio_sustituido(test_db, monkeypatch):
    """Decisión de Chapa: los stops no esperan aprobación. Y con el precio sustituido,
    corren — que es justo lo que no pasaba cuando el precio sólo se descartaba."""
    acct = _cuenta(test_db, ticker="KO")
    settings.set("atr_stops_enabled", True)
    settings.set("atr_period", 14)
    settings.set("atr_stop_mult", 2.0)
    settings.set("atr_tp_mult", 50.0)
    settings.set("atr_trail_enabled", False)
    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: lambda *a, **k: [])
    idx = pd.date_range("2026-01-01", periods=60, freq="B")
    df = pd.DataFrame(
        {"Open": CIERRE, "High": CIERRE + 0.5, "Low": CIERRE - 0.5, "Close": CIERRE, "Volume": 1_000_000},
        index=idx,
    )
    _veredicto(ticker="KO", independiente=90.0)  # 90 ≤ stop 99 ⇒ dispara

    r = _scan(acct, {"KO": 90.0}, history=lambda _t: df)

    assert r.filled == 1 and r.queued == 0
    assert [(s, st) for s, st, _ in _ordenes(acct)] == [("SELL", "filled")]


def test_la_venta_pendiente_NO_se_duplica_scan_a_scan(test_db, monkeypatch):
    acct = _cuenta(test_db)
    _estrategia(monkeypatch)
    _veredicto()
    _scan(acct, {"AAPL": INDEPENDIENTE})
    _veredicto()
    r2 = _scan(acct, {"AAPL": INDEPENDIENTE})

    assert r2.queued == 0
    assert [(s, st) for s, st, _ in _ordenes(acct)] == [("SELL", "pending")]


def test_el_aviso_de_Slack_no_se_repite_en_el_mismo_dia(test_db, monkeypatch):
    acct = _cuenta(test_db)
    _estrategia(monkeypatch)
    avisos: list[str] = []
    for _ in range(3):
        _veredicto()
        _scan(acct, {"AAPL": INDEPENDIENTE}, avisos)
    assert len([m for m in avisos if "precio en disputa" in m]) == 1


# ── La reevaluación en cada scan ─────────────────────────────────────────────


def test_si_el_precio_vuelve_a_ser_coherente_la_pendiente_se_CANCELA_y_decide_la_logica_normal(
    test_db, monkeypatch
):
    acct = _cuenta(test_db)
    _estrategia(monkeypatch)
    _veredicto()
    _scan(acct, {"AAPL": INDEPENDIENTE})
    yfm._clear_opinion_log()  # Yahoo volvió a dar un precio en banda

    r = _scan(acct, {"AAPL": 105.0})

    estados = [(s, st) for s, st, _ in _ordenes(acct)]
    assert ("SELL", "expired") in estados, "la pendiente por segunda opinión se cancela"
    assert ("SELL", "filled") in estados and r.filled == 1, "y la señal vende sola, como siempre"


def test_si_la_senal_ya_no_vende_la_pendiente_se_cancela(test_db, monkeypatch):
    acct = _cuenta(test_db)
    _estrategia(monkeypatch)
    _veredicto()
    _scan(acct, {"AAPL": INDEPENDIENTE})
    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: lambda *a, **k: [])
    _veredicto()

    _scan(acct, {"AAPL": INDEPENDIENTE})

    assert [(s, st) for s, st, _ in _ordenes(acct)] == [("SELL", "expired")]


def test_con_el_mercado_cerrado_la_pendiente_NO_se_cancela(test_db, monkeypatch):
    acct = _cuenta(test_db)
    _estrategia(monkeypatch)
    _veredicto()
    _scan(acct, {"AAPL": INDEPENDIENTE})
    settings.set("paper_enforce_market_hours", True)
    monkeypatch.setattr(engine, "_is_market_open_safe", lambda: False)
    yfm._clear_opinion_log()

    _scan(acct, {"AAPL": 105.0})

    assert [(s, st) for s, st, _ in _ordenes(acct)] == [("SELL", "pending")]


def test_aprobar_la_pendiente_la_llena_con_el_precio_que_haya_al_aprobar(test_db, monkeypatch):
    acct = _cuenta(test_db)
    _estrategia(monkeypatch)
    _veredicto()
    r = _scan(acct, {"AAPL": INDEPENDIENTE})

    o = engine.approve_order(
        r.pending_orders[0],
        prices_provider=lambda _t: {"AAPL": INDEPENDIENTE},
        earnings_provider=lambda _t: None,
    )

    assert o is not None and o.status == "filled" and o.fill_price is not None


# ── Fila 2: la fuente independiente no coincide con ninguno ──────────────────


def test_ninguno_la_posicion_queda_sin_evaluar_y_AVISA_con_los_tres_precios(test_db, monkeypatch):
    acct = _cuenta(test_db)
    _estrategia(monkeypatch)
    _veredicto(verdict="ninguno", independiente=250.0)
    avisos: list[str] = []

    r = _scan(acct, {}, avisos)  # el fetch no entregó precio

    assert r.filled == 0 and r.queued == 0 and _ordenes(acct) == []
    assert [d["kind"] for d in r.price_disputes] == [engine.DISPUTE_NO_PRICE]
    [aviso] = [m for m in avisos if "precio en disputa" in m]
    assert "1000.00" in aviso and "100.00" in aviso and "250.00" in aviso and "NO se evaluó" in aviso


# ── Fila 3 y el flag apagado: nada cambia ────────────────────────────────────


def test_sin_veredicto_registrado_la_venta_por_senal_sale_sola_como_siempre(test_db, monkeypatch):
    """Es el estado con el flag OFF (el registro nunca se escribe) y con Finnhub avalando
    a Yahoo o sin contestar: el camino nuevo no toca nada."""
    acct = _cuenta(test_db)
    _estrategia(monkeypatch)
    avisos: list[str] = []

    r = _scan(acct, {"AAPL": 105.0}, avisos)

    assert r.filled == 1 and r.queued == 0 and r.price_disputes == []
    assert not [m for m in avisos if "precio en disputa" in m]


def test_un_veredicto_viejo_no_sustituye_un_precio_SANO_leido_del_cache(test_db, monkeypatch):
    """El registro puede recordar una sustitución de hace minutos mientras el scan leyó un
    precio sano de Yahoo del cache: sólo cuenta si el precio que llegó ES el independiente."""
    acct = _cuenta(test_db)
    _estrategia(monkeypatch)
    _veredicto()

    r = _scan(acct, {"AAPL": 105.0})

    assert r.filled == 1 and r.price_disputes == []


def test_con_el_flag_OFF_unreliable_reference_no_registra_veredicto(monkeypatch):
    monkeypatch.setattr(yfm, "scale_is_disputed", lambda *a, **k: True)
    monkeypatch.setattr(yfm, "_price_sanity_band", lambda: 0.50)
    monkeypatch.setattr(yfm, "_second_opinion_enabled", lambda: False)
    yfm.unreliable_reference("AAPL", YAHOO_CORRUPTO, CIERRE, allow_network=True)
    assert yfm.price_dispute("AAPL") is None


# ── La capa de fetch ─────────────────────────────────────────────────────────


@pytest.fixture
def fetch_en_disputa(monkeypatch):
    yfm._clear_out_of_band_streak("AAPL")
    monkeypatch.setattr(yfm, "_price_sanity_band", lambda: 0.50)
    monkeypatch.setattr(yfm, "scale_is_disputed", lambda *a, **k: True)
    monkeypatch.setattr(yfm, "_second_opinion_enabled", lambda: True)
    yield
    yfm._clear_out_of_band_streak("AAPL")


def test_fetch_con_NINGUNO_no_entrega_precio(fetch_en_disputa, monkeypatch):
    # 250 no está a menos del 50% ni de 1000 ni de 100. (500 sí lo está de 1000: en el
    # borde de la banda el árbitro lo cuenta como que avala el precio.)
    monkeypatch.setattr("data.providers.second_opinion", lambda t, **k: 250.0)
    assert yfm._reject_if_out_of_band("AAPL", {"price": YAHOO_CORRUPTO}) is None
    assert yfm.price_dispute("AAPL")["verdict"] == "ninguno"


def test_fetch_con_REFERENCIA_entrega_el_precio_independiente_marcado_y_sin_derivados_de_Yahoo(
    fetch_en_disputa, monkeypatch
):
    monkeypatch.setattr("data.providers.second_opinion", lambda t, **k: INDEPENDIENTE)
    info = yfm._reject_if_out_of_band(
        "AAPL", {"price": YAHOO_CORRUPTO, "change_pct": 900.0, "market_cap": 1e12}
    )
    assert info["price"] == INDEPENDIENTE and info["price_source"] == "second_opinion"
    assert info["change_pct"] is None and info["market_cap"] is None


def test_un_precio_en_banda_BORRA_el_veredicto(fetch_en_disputa, monkeypatch):
    monkeypatch.setattr("data.providers.second_opinion", lambda t, **k: INDEPENDIENTE)
    yfm._reject_if_out_of_band("AAPL", {"price": YAHOO_CORRUPTO})
    assert yfm.price_dispute("AAPL") is not None
    yfm._reject_if_out_of_band("AAPL", {"price": 102.0})
    assert yfm.price_dispute("AAPL") is None


def test_el_precio_sustituido_NO_se_escribe_en_el_cache(test_db, fetch_en_disputa, monkeypatch):
    """Si se cacheara, el próximo scan lo leería como si fuera de Yahoo, sin la marca, y la
    venta por señal saldría sola sin pedir aprobación."""
    from database.models import PriceCache

    monkeypatch.setattr("data.providers.second_opinion", lambda t, **k: INDEPENDIENTE)
    monkeypatch.setattr(yfm, "_cache_enabled", lambda: True)
    monkeypatch.setattr(yfm, "get_failing_set", lambda: set())
    monkeypatch.setattr(yfm, "_should_attempt_fetch", lambda: True)
    monkeypatch.setattr(
        yfm, "_fetch_ticker_info", lambda t: {"ticker": t, "price": YAHOO_CORRUPTO if t == "AAPL" else 50.0}
    )
    monkeypatch.setattr(yfm, "reference_close", lambda t: CIERRE if t == "AAPL" else 50.0)

    out = yfm.get_bulk_prices(["AAPL", "MSFT"])

    assert out["AAPL"]["price"] == INDEPENDIENTE
    with session_scope() as s:
        cacheados = {r.ticker for r in s.query(PriceCache).all()}
    assert "AAPL" not in cacheados and "MSFT" in cacheados
