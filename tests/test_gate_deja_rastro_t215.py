"""Tarea 215 — un gate que evalúa y deja pasar también deja rastro.

**Cómo apareció, y es un síntoma limpio.** La **213** inyectó en seis tests un
``earnings_provider`` que devuelve una fecha **lejana**, para que el Gate 6 *corra* y
deje pasar por un motivo escrito en vez de por el fail-open de *«no sé»* que da ``None``.
Al mutarlo a ``None``, la suite quedó **verde**: desde afuera del engine, *«el gate
evaluó la fecha y no bloqueó»* y *«el gate no tenía dato»* producían **exactamente lo
mismo** — ningún warning, ningún contador, ningún campo en ``ScanResult``.

**La asimetría de evidencia.** ``result.warnings`` se llena cuando un gate **bloquea**,
así que el log y la UI cuentan bien los rechazos y no cuentan **nada** de las
evaluaciones que pasaron. Para el Gate 6 eso significa que no se podía responder
*«¿cuántas BUYs pasaron el blackout con fecha conocida, y cuántas pasaron porque yfinance
no contestó?»* — y la segunda es un **outage disfrazado de vía libre**.

**Lo que NO cambió.** El fail-open del Gate 6 sigue igual: una fecha desconocida no
bloquea, y eso es política deliberada (un gate de datos que bloquea por falta de datos
frena el trading entero cuando Yahoo tose). Lo que dejó de pasar es que fallar abierto y
fallar **en silencio** fueran la misma cosa — la misma frase que la tarea 103 escribió
para el cap de ADV, en este mismo archivo.

**Y por qué un contador y no un warning por trade.** Un warning por evaluación es el spam
que la T25 y la racha de la 63 vinieron a apagar. El contador es agregado por scan, y el
``summary()`` sólo imprime lo que **no** es el camino feliz: si cada scan sano dijera
*«evaluado 8»*, el día que diga *«sin_dato 8»* nadie lo vería.
"""

from __future__ import annotations

import itertools
from datetime import timedelta

from config.settings_manager import settings
from database.models import session_scope, utcnow_naive
from paper_trading.account import create_account
from paper_trading.models import PaperWatchlistItem


def _base_settings():
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_anti_flap_minutes", 0)
    settings.set("paper_whipsaw_lookback_days", 0)
    settings.set("paper_churn_max_cycles", 0)
    settings.set("earnings_blackout_days", 2)


def _buy_strategy(ticker):
    from paper_trading.strategies import TargetTrade

    def strat(*_a, **_k):
        return [
            TargetTrade(
                ticker=ticker,
                side="BUY",
                target_shares=None,
                target_dollars=1_000.0,
                reason="analyze BUY",
                source="analyze_single",
            )
        ]

    return strat


_n = itertools.count()


def _scan(monkeypatch, earnings_provider, ticker="KO", precio=63.0, blackout_days=2):
    """Un scan con una BUY sola y todo lo demas neutralizado salvo el Gate 6.

    El nombre de la cuenta lleva un contador porque `paper_accounts.name` tiene UNIQUE y
    hay tests que corren DOS scans para comparar sus resultados entre si.

    `blackout_days` es parametro y no algo que el test setee antes de llamar: setearlo
    afuera no funciona —`_base_settings()` corre despues y lo pisa—, que es exactamente
    el bug que tenia el test del gate apagado.
    """
    from paper_trading import engine

    a = create_account(name=f"C{next(_n)}", initial_capital=10_000.0)
    _base_settings()
    settings.set("earnings_blackout_days", blackout_days)
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=a.id, ticker=ticker))

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: _buy_strategy(ticker))
    return engine.run_scan(
        a.id,
        prices_provider=lambda _t: {ticker: precio},
        history_provider=lambda _t: None,
        earnings_provider=earnings_provider,
    )


# ── El kill-criteria: los dos casos son distinguibles ────────────────────────


def test_fecha_conocida_fuera_de_la_ventana_deja_rastro(test_db, monkeypatch):
    """El caso que antes no dejaba huella: el gate corrió, tenía la fecha, no aplicó."""
    lejos = utcnow_naive() + timedelta(days=90)
    r = _scan(monkeypatch, lambda _t: lejos)

    assert r is not None
    assert r.earnings_gate.get("evaluado") == 1, r.earnings_gate
    assert not r.earnings_gate.get("sin_dato"), r.earnings_gate
    assert r.filled or r.queued, "y la BUY pasó, que es el punto: el gate no bloqueó"


def test_sin_fecha_deja_un_rastro_DISTINTO(test_db, monkeypatch):
    """**La mitad que la 213 no podía escribir.**

    Con `None` el resultado del trade es el mismo —pasa— pero el motivo es otro, y ahora
    el `ScanResult` lo dice. Ésta es la aserción que la mutación *«devolver None»* de la
    213 no podía romper porque no existía.
    """
    r = _scan(monkeypatch, lambda _t: None)

    assert r is not None
    assert r.earnings_gate.get("sin_dato") == 1, r.earnings_gate
    assert not r.earnings_gate.get("evaluado"), r.earnings_gate


def test_los_dos_casos_NO_producen_el_mismo_ScanResult(test_db, monkeypatch):
    """El kill-criteria literal: *distinguibles por un consumidor programático*.

    Se compara el contador entero y no una clave suelta, que es lo que un consumidor
    haría de verdad.
    """
    lejos = utcnow_naive() + timedelta(days=90)
    con_fecha = _scan(monkeypatch, lambda _t: lejos)
    sin_fecha = _scan(monkeypatch, lambda _t: None)

    assert con_fecha.earnings_gate != sin_fecha.earnings_gate, (
        "si estos dos son iguales, el defecto de la 215 volvió: el engine no distingue "
        "'evalué y no aplica' de 'no tuve dato'"
    )


# ── El provider caído no es lo mismo que "no hay fecha" ──────────────────────


def test_el_provider_que_revienta_se_cuenta_APARTE(test_db, monkeypatch):
    """Los dos llegan con ``None``, y uno es un outage.

    Es la distinción que la 210 hizo para ``_getattr`` —levantar ≠ devolver vacío—
    aplicada al engine. Sin ella, el día que yfinance se cae entero el scan dice
    exactamente lo mismo que un día con tickers sin earnings agendados.
    """

    def _explota(_t):
        raise RuntimeError("Yahoo timeout")

    r = _scan(monkeypatch, _explota)

    assert r.earnings_gate.get("sin_dato_por_error") == 1, r.earnings_gate
    assert not r.earnings_gate.get("sin_dato"), (
        f"un fetch caído no puede contarse como 'el ticker no tiene fecha': {r.earnings_gate}"
    )
    assert r.filled or r.queued, "y sigue fallando ABIERTO, que es la política"


# ── El bloqueo sigue contándose, y sigue en warnings ─────────────────────────


def test_el_bloqueo_se_cuenta_y_NO_se_pierde_el_warning(test_db, monkeypatch):
    """Contraprueba: el contador nuevo no se comió el camino que ya andaba."""
    cerca = utcnow_naive() + timedelta(days=1)
    r = _scan(monkeypatch, lambda _t: cerca)

    assert r.earnings_gate.get("bloqueo") == 1, r.earnings_gate
    assert r.filled == 0 and r.queued == 0
    assert any("blackout" in w for w in r.warnings), r.warnings


# ── El summary dice lo raro y calla lo normal ────────────────────────────────


def test_el_summary_NO_dice_nada_cuando_todo_se_evaluo(test_db, monkeypatch):
    """Si cada scan sano imprimiera su contador, el día malo no destacaría.

    Es el mismo criterio del nivel de log de la 207: lo raro tiene que sobresalir, y una
    línea que aparece siempre no sobresale nunca.
    """
    lejos = utcnow_naive() + timedelta(days=90)
    r = _scan(monkeypatch, lambda _t: lejos)
    assert "earnings-gate" not in r.summary(), r.summary()


def test_el_summary_SI_dice_el_fail_open(test_db, monkeypatch):
    r = _scan(monkeypatch, lambda _t: None)
    resumen = r.summary()
    assert "earnings-gate fail-open" in resumen, resumen
    assert "1 sin fecha" in resumen, resumen


def test_el_summary_distingue_el_fetch_caido_en_el_TEXTO(test_db, monkeypatch):
    """No alcanza con que el contador los separe: quien lee el log ve el texto."""

    def _explota(_t):
        raise RuntimeError("Yahoo timeout")

    resumen = _scan(monkeypatch, _explota).summary()
    assert "por fetch caído" in resumen, resumen
    assert "sin fecha" not in resumen, resumen


# ── El gate apagado no cuenta nada ───────────────────────────────────────────


def test_con_el_gate_apagado_no_se_cuenta_nada(test_db, monkeypatch):
    """``earnings_blackout_days = 0`` apaga el Gate 6: no hay evaluación que registrar.

    Se fija porque un contador que se llena con el gate apagado diría que se evaluó algo
    que nunca se miró — y sería un rastro **falso**, que es peor que no tenerlo.
    """
    lejos = utcnow_naive() + timedelta(days=90)
    r = _scan(monkeypatch, lambda _t: lejos, blackout_days=0)

    assert r.earnings_gate == {}, r.earnings_gate
    assert "earnings-gate" not in r.summary()
