"""Tarea 103 — el Gate 3b (cap por ADV) fallaba abierto SIN dejar rastro.

Fallar abierto es la política y no se toca. Lo que estaba mal es que no se notara:
``was_capped=False`` valía **igual** para *«la orden entraba bajo el techo»* que para
*«no pude medir la liquidez, así que no apliqué el gate»*, y después del hecho no
había forma de saber cuál de las dos fue. El caso que importa es el segundo — una
BUY a tamaño completo sobre un nombre cuya liquidez no se pudo medir, o sea justo los
más propensos a ser finos.

El patrón correcto ya estaba escrito **veinte líneas más arriba, en el mismo scan**:
el Gate 6 (earnings) falla abierto y lo loguea. Estos tests fijan que el 3b haga lo
mismo, y —sobre todo— que el rastro **no aparezca cuando no corresponde**: un aviso
que sale siempre no informa nada.
"""

from __future__ import annotations

import logging

import pandas as pd

from config.settings_manager import settings
from database.models import session_scope
from paper_trading.account import create_account
from paper_trading.models import PaperOrder, PaperWatchlistItem

_SIN_CAP = "SIN cap por ADV"
_RECORTADO = "recortado por ADV"


def _history(precio: float, volumen: float, n: int = 30) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "Open": [precio] * n,
            "High": [precio] * n,
            "Low": [precio] * n,
            "Close": [precio] * n,
            "Volume": [volumen] * n,
        },
        index=idx,
    )


def _aislar_otros_gates() -> None:
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_anti_flap_minutes", 0)
    settings.set("paper_whipsaw_lookback_days", 0)
    settings.set("earnings_blackout_days", 0)


def _estrategia_buy(ticker: str, dolares: float):
    from paper_trading.strategies import TargetTrade

    def strat(account, watchlist, positions, prices, history_provider):
        return [
            TargetTrade(
                ticker=ticker,
                side="BUY",
                target_shares=None,
                target_dollars=dolares,
                reason="analyze BUY",
                source="analyze_single",
            )
        ]

    return strat


def _correr(monkeypatch, *, history_provider, dolares=200_000.0, cap_pct=0.05):
    """Un scan con una sola BUY y todos los demás gates apagados."""
    from paper_trading import engine

    a = create_account(name="ADV", initial_capital=1_000_000.0, mode="manual")
    _aislar_otros_gates()
    settings.set("paper_adv_cap_pct", cap_pct)
    settings.set("paper_min_trade_dollars", 250.0)
    settings.set("paper_adv_lookback_days", 20)

    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker="TSLA"))

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _estrategia_buy("TSLA", dolares))
    return engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"TSLA": 100.0},
        history_provider=history_provider,
        earnings_provider=lambda _t: None,
    )


def _orden(result) -> PaperOrder:
    assert result.pending_orders, "se esperaba una orden encolada"
    with session_scope() as s:
        return s.query(PaperOrder).filter(PaperOrder.id == result.pending_orders[0]).first()


# ── El rastro aparece cuando el gate NO se evaluó ───────────────────────────


def test_sin_historial_la_orden_queda_INTACTA_y_ahora_se_dice(test_db, monkeypatch):
    """Las dos mitades juntas: la decisión no cambia (fail-open es la política) **y**
    queda escrito que el gate no se evaluó."""
    result = _correr(monkeypatch, history_provider=lambda _t: None)

    assert _orden(result).target_dollars == 200_000.0, "la decisión NO se toca"
    assert any(_SIN_CAP in w for w in result.warnings), result.warnings
    assert not any(_RECORTADO in w for w in result.warnings)


def test_un_provider_que_LEVANTA_deja_rastro_en_el_log(test_db, monkeypatch, caplog):
    """Espejo exacto de `test_gate_fail_open_when_provider_raises` del Gate 6: el
    `except` que devolvía `None` en silencio ahora loguea, con el mismo texto."""

    def boom(_ticker):
        raise RuntimeError("parquet exploded")

    with caplog.at_level(logging.WARNING):
        result = _correr(monkeypatch, history_provider=boom)

    assert _orden(result).target_dollars == 200_000.0
    assert any("adv gate" in rec.message for rec in caplog.records), [r.message for r in caplog.records]
    assert any(_SIN_CAP in w for w in result.warnings)


def test_un_historial_SIN_volumen_tambien_es_no_evaluado(test_db, monkeypatch):
    """El provider no falla y el frame existe, pero `recent_adv_dollars` no puede
    calcular nada. Para el gate es lo mismo: no se evaluó. Si el rastro colgara del
    `except` en vez de colgar del ADV, este caso quedaría mudo igual."""
    df = _history(100.0, 1_000.0).drop(columns=["Volume"])
    result = _correr(monkeypatch, history_provider=lambda _t: df)

    assert _orden(result).target_dollars == 200_000.0
    assert any(_SIN_CAP in w for w in result.warnings), result.warnings


# ── Y NO aparece cuando sí se evaluó ───────────────────────────────────────


def test_con_liquidez_medible_y_orden_chica_NO_avisa_nada(test_db, monkeypatch):
    """**El control que le da sentido al aviso.** ADV$ = 100 × 100.000 = 10 M, cap 5%
    ⇒ techo 500.000; la orden de 200.000 entra sola. Ese `was_capped=False` es el
    legítimo y **no** tiene que ensuciar la salida — si el aviso saliera también acá,
    no distinguiría nada, que es el defecto que la tarea arregla."""
    result = _correr(monkeypatch, history_provider=lambda _t: _history(100.0, 100_000.0))

    assert _orden(result).target_dollars == 200_000.0
    assert not any(_SIN_CAP in w for w in result.warnings), result.warnings
    assert not any(_RECORTADO in w for w in result.warnings)


def test_cuando_SI_recorta_avisa_el_recorte_y_no_el_otro(test_db, monkeypatch):
    """ADV$ = 100 × 10.000 = 1 M, cap 5% ⇒ techo 50.000: la orden de 200.000 se
    recorta. Los dos avisos son excluyentes."""
    result = _correr(monkeypatch, history_provider=lambda _t: _history(100.0, 10_000.0))

    assert _orden(result).target_dollars == 50_000.0
    assert any(_RECORTADO in w for w in result.warnings), result.warnings
    assert not any(_SIN_CAP in w for w in result.warnings)


def test_con_el_gate_APAGADO_no_avisa_aunque_no_haya_historial(test_db, monkeypatch):
    """Sin gate no hay nada que dejar de evaluar. Un aviso acá sería ruido puro en la
    configuración de quien lo apagó a propósito."""
    result = _correr(monkeypatch, history_provider=lambda _t: None, cap_pct=0.0)

    assert _orden(result).target_dollars == 200_000.0
    assert not any(_SIN_CAP in w for w in result.warnings), result.warnings


def test_el_aviso_dice_el_ticker_el_lookback_y_el_tamano(test_db, monkeypatch):
    """Un rastro que no dice sobre qué orden fue no sirve después del hecho."""
    result = _correr(monkeypatch, history_provider=lambda _t: None)
    aviso = next(w for w in result.warnings if _SIN_CAP in w)
    assert "TSLA" in aviso
    assert "20 ruedas" in aviso
    assert "200,000" in aviso
