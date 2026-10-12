"""Tarea 350 — el ex-date que Yahoo publica tarde se acredita igual, y una sola vez.

El defecto
----------
La 222 decidía el crédito con la ventana ``(último scan, hoy]``. Yahoo publica el ex-date
en ``.dividends`` **uno o más días tarde** (GE: no estaba en el fetch de las 22:16 UTC de
su propio ex-date y apareció dos días después). Con scans diarios, cuando el ex-date entra
al cache ya quedó a la izquierda de la ventana: el motor **no acreditó ningún dividendo**
desde la 222 (``paper_dividend_credits`` con 0 filas el 2026-10-10, $93,96 devengados).

El oráculo de la 222 sembraba el ex-date **de hoy** con el último scan en ayer: suponía el
calendario al día, que es lo que los datos desmienten. Acá el calendario llega tarde.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from database.models import DividendCalendarCache, session_scope, utcnow_naive
from paper_trading.dividends import DIAS_ATRASO_CALENDARIO, PISO_DIVIDENDOS, creditos_pendientes
from paper_trading.models import PaperAccount, PaperDividendCredit, PaperOrder, PaperWatchlistItem


def _dias(desde: str, n: int) -> list[str]:
    d0 = date.fromisoformat(desde)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _simular(piso_fijo: bool, atraso: int = 2) -> list[tuple[str, str, float, float]]:
    """Scans diarios sobre un calendario que publica el ex-date ``atraso`` días tarde.

    ``piso_fijo=True`` es el motor de la 350; ``False``, el de la 222 (ventana desde el
    último scan). Devuelve todos los créditos de la simulación, con el ledger entre scans.
    """
    fills = [("GE", "BUY", 33.0, "2026-09-20 15:00:00")]
    ex_date = "2026-10-05"
    publicado = (date.fromisoformat(ex_date) + timedelta(days=atraso)).isoformat()
    ya: set[tuple[str, str]] = set()
    creditos = []
    ultimo_scan = "2026-10-01"
    for hoy in _dias("2026-10-02", 10):
        cal = {"GE": [(ex_date, 0.47)]} if hoy >= publicado else {}
        desde = PISO_DIVIDENDOS if piso_fijo else ultimo_scan
        nuevos = creditos_pendientes(fills, cal, ya, desde, hoy)
        ya |= {(t, e) for t, e, _a, _m in nuevos}
        creditos += nuevos
        ultimo_scan = hoy
    return creditos


def test_un_ex_date_publicado_DOS_dias_tarde_se_acredita_UNA_vez():
    """El kill-criteria: calendario dos días tarde, scans diarios ⇒ un crédito, uno solo."""
    assert _simular(piso_fijo=True) == [("GE", "2026-10-05", 33.0, 0.47)]


def test_CONTRAPRUEBA_la_ventana_del_ultimo_scan_no_lo_acredita_nunca():
    """La mitad que hace que el test de arriba distinga: con la ventana de la 222, el mismo
    calendario no paga nada. Si esto empezara a pagar, el escenario ya no reproduce el
    defecto y el test de arriba estaría probando un caso degenerado."""
    assert _simular(piso_fijo=False) == []


def test_publicado_el_mismo_dia_las_dos_versiones_cobran():
    """Y el caso que la 222 sí cubría sigue cubierto: sin atraso cobran las dos."""
    assert _simular(piso_fijo=True, atraso=0) == _simular(piso_fijo=False, atraso=0) != []


def test_el_piso_es_la_vispera_de_la_puesta_en_marcha_de_la_222():
    """``210b940`` es del 2026-09-25: el primer scan de ese día tenía la ventana
    ``(2026-09-24, hoy]``. Un piso posterior se comería ex-dates que la 222 mandaba cobrar;
    uno anterior pagaría el backfill que Chapa descartó."""
    assert PISO_DIVIDENDOS == "2026-09-24"


# ── El cable, con run_scan de verdad ─────────────────────────────────────────


def _scan_settings():
    from config.settings_manager import settings

    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_anti_flap_minutes", 0)
    settings.set("paper_whipsaw_lookback_days", 0)


class _SinEarnings:
    def __call__(self, ticker):
        return None

    def get_next_earnings_date(self, ticker):
        return None


def _scan(acct_id: int, *, inyectar_history: bool = True):
    from paper_trading import engine

    return engine.run_scan(
        acct_id,
        prices_provider=lambda _t: {"GE": 100.0},
        history_provider=(lambda _t: None) if inyectar_history else None,
        earnings_provider=_SinEarnings(),
    )


def _fill(acct_id: int, side: str, shares: float, cuando: datetime) -> None:
    with session_scope() as s:
        s.add(
            PaperOrder(
                account_id=acct_id,
                ticker="GE",
                side=side,
                status="filled",
                fill_shares=shares,
                fill_price=100.0,
                filled_at=cuando,
            )
        )


def _caja(acct_id: int) -> float:
    with session_scope() as s:
        return float(s.query(PaperAccount).filter(PaperAccount.id == acct_id).one().cash)


def test_run_scan_acredita_un_ex_date_que_llego_DESPUES_del_ultimo_scan(test_db):
    """El último scan fue hoy, y el ex-date —de anteayer— recién ahora está en el cache.

    Con la ventana ``(último scan, hoy]`` esto no cobraba; es exactamente lo que le pasó a
    GE, BMY y DHR. Un segundo scan no vuelve a pagar.
    """
    from paper_trading.account import create_account

    _scan_settings()
    acct = create_account(name="Tardia", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=acct.id, ticker="GE"))
    ahora = utcnow_naive()
    _fill(acct.id, "BUY", 33.0, ahora - timedelta(days=20))
    with session_scope() as s:
        s.query(PaperAccount).filter(PaperAccount.id == acct.id).one().last_scan_at = ahora - timedelta(
            minutes=5
        )
        anteayer = (ahora - timedelta(days=2)).strftime("%Y-%m-%d")
        s.add(DividendCalendarCache(ticker="GE", ex_date=anteayer, amount=0.47, fetched_at=ahora))

    caja_antes = _caja(acct.id)
    result = _scan(acct.id)

    assert _caja(acct.id) == pytest.approx(caja_antes + 33 * 0.47), "no acreditó el ex-date tardío"
    assert any("dividendo del" in w for w in result.warnings), "el crédito no se reporta"

    _scan(acct.id)
    assert _caja(acct.id) == pytest.approx(caja_antes + 33 * 0.47), "pagó dos veces"
    with session_scope() as s:
        assert s.query(PaperDividendCredit).count() == 1


def test_el_warm_up_calienta_los_VENDIDOS_hace_poco_y_no_los_de_hace_meses(test_db, monkeypatch):
    """Un ticker vendido entre el ex-date y la publicación ya no es posición abierta: sin
    esto su calendario no se refrescaba y el crédito no llegaba nunca."""
    from paper_trading import engine
    from paper_trading.account import create_account

    _scan_settings()
    pedidos: list[list[str]] = []
    monkeypatch.setattr(engine, "_warm_up_history_cache", lambda t: None)
    monkeypatch.setattr(engine, "_warm_up_split_events", lambda t: None)
    monkeypatch.setattr(engine, "_warm_up_dividend_calendar", lambda tickers: pedidos.append(list(tickers)))

    acct = create_account(name="Vendida", initial_capital=10_000.0)
    ahora = utcnow_naive()
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=acct.id, ticker="GE"))
        for tk, dias in (("BMY", 3), ("DHR", DIAS_ATRASO_CALENDARIO + 30)):
            s.add(
                PaperOrder(
                    account_id=acct.id,
                    ticker=tk,
                    side="SELL",
                    status="filled",
                    fill_shares=10.0,
                    fill_price=100.0,
                    filled_at=ahora - timedelta(days=dias),
                )
            )

    _scan(acct.id, inyectar_history=False)

    assert pedidos, "el scan no llamó al warm-up del calendario"
    assert "BMY" in pedidos[0], f"no calentó el vendido hace 3 días: {pedidos}"
    assert "DHR" not in pedidos[0], f"calentó un vendido hace más de {DIAS_ATRASO_CALENDARIO} días: {pedidos}"


def test_el_desvio_dice_que_la_222_no_acredito_hasta_la_350():
    """El desvío afirmaba que el motor cobraba desde el 2026-09-25 y valía el 0,9%; en ese
    tramo fue el 100%. Quien lea un veredicto de ese tramo tiene que enterarse."""
    from analysis.harness_config import dividendos_desc

    txt = dividendos_desc()
    assert "hasta la tarea 350" in txt and "NO acreditó ninguno" in txt
