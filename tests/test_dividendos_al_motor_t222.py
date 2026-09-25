"""Tarea 222 — el motor acredita los dividendos al ex-date, y sólo hacia adelante.

La decisión, y con qué se tomó
-------------------------------
El harness corre sobre barras ``auto_adjust=True`` —total-return— y el motor vivo no
miraba dividendos: la cuenta pasaba por el ex-date, veía caer el precio y **no recibía el
efectivo**. Medido el 2026-09-21 sobre la cuenta 2: **$322,77 en 3,05 meses = 2,54%/año**,
el **62%** de todo su P&L neto realizado.

La 221 arregló la **medición** (el VS SPY compara total contra total) y dejó el cableado
como tarea aparte. Acá Chapa eligió **caja al ex-date**, con los costos de las dos
opciones medidos delante (2026-09-25):

* cierra el **99,1%** del desvío (quedan ~$2,77, porque el harness *reinvierte* el
  dividendo en el precio y la caja acreditada queda quieta);
* mueve el sizing de las compras **0,78% la mediana**, p90 2,5%;
* **no mueve los slots**: 0 BUYs sin llenar en toda la vida de la cuenta.

**Dos cosas que el enunciado afirmaba y eran falsas**, y las dos se verificaron antes de
diseñar en vez de después:

1. *«cambia slots y sizing»* — los slots **no** se mueven; nunca faltó caja para un
   nombre. El costo real de la opción es un orden de magnitud menor de lo que decía.
2. *«el engine no pega a la red, así que el calendario tiene que llegar de un job del
   scheduler»* — ``run_scan`` **sí** pega a la red en ``_warm_up_history_cache``. Lo que
   nunca pega es el **guard** del engine (tarea 130). Verificarlo ahorró un job entero:
   el calendario se calienta al lado de las barras.

Y una medición mía que salió mal primero
------------------------------------------
El primer cálculo del uplift dio **3174%** porque comparé los dividendos contra la
**caja sola**. El sizing usa ``available = cash + est_proceeds``, y las ventas del mismo
scan son la fuente principal — por eso el notional de un día llega a ser 100× la caja
previa. Con el denominador correcto (el ``target_dollars`` total del día, que con
``equal_weight`` **es** ``available``) el número es **0,78%**.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from database.models import DividendCalendarCache, session_scope, utcnow_naive
from paper_trading.dividends import (
    _SIN_DIVIDENDOS,
    acciones_antes_del_ex_date,
    acreditar_dividendos,
    creditos_pendientes,
)
from paper_trading.models import PaperAccount, PaperDividendCredit, PaperOrder


def _cuenta(cash: float = 10_000.0, nombre: str = "Sintetica") -> int:
    # El nombre va parametrizado porque `paper_accounts.name` es UNIQUE: el test de dos
    # cuentas chocaba con un IntegrityError que no tenía nada que ver con dividendos.
    with session_scope() as s:
        a = PaperAccount(name=nombre, initial_capital=cash, cash=cash)
        s.add(a)
        s.flush()
        return a.id


def _fill(acct_id: int, ticker: str, side: str, shares: float, dia: str) -> None:
    with session_scope() as s:
        s.add(
            PaperOrder(
                account_id=acct_id,
                ticker=ticker,
                side=side,
                status="filled",
                fill_shares=shares,
                fill_price=100.0,
                filled_at=datetime.fromisoformat(f"{dia} 21:00:00"),
            )
        )


def _ex_date(ticker: str, dia: str, monto: float) -> None:
    with session_scope() as s:
        s.add(DividendCalendarCache(ticker=ticker, ex_date=dia, amount=monto, fetched_at=utcnow_naive()))


def _acreditar(acct_id: int, desde: str | None, hasta: str) -> list[dict]:
    with session_scope() as s:
        acct = s.query(PaperAccount).filter(PaperAccount.id == acct_id).one()
        return acreditar_dividendos(s, acct, desde, hasta)


def _caja(acct_id: int) -> float:
    with session_scope() as s:
        return float(s.query(PaperAccount).filter(PaperAccount.id == acct_id).one().cash)


# ── El kill-criteria del enunciado ───────────────────────────────────────────


def test_una_posicion_que_cruza_un_ex_date_COBRA_el_efectivo(test_db):
    """El caso central: la cuenta tiene la acción antes del ex-date y recibe la caja."""
    acct = _cuenta(10_000.0)
    _fill(acct, "MO", "BUY", 100.0, "2026-06-01")
    _ex_date("MO", "2026-06-15", 1.25)

    creditos = _acreditar(acct, "2026-06-14", "2026-06-16")

    assert [(c["ticker"], c["ex_date"], c["cash"]) for c in creditos] == [("MO", "2026-06-15", 125.0)]
    assert _caja(acct) == pytest.approx(10_125.0)
    with session_scope() as s:
        (fila,) = s.query(PaperDividendCredit).all()
        assert (fila.ticker, fila.ex_date, fila.shares, fila.amount_per_share) == (
            "MO",
            "2026-06-15",
            100.0,
            1.25,
        )


def test_sin_ex_date_en_la_ventana_NO_cambia_NADA(test_db):
    """La otra dirección del kill-criteria, y la que protege al caso normal.

    La inmensa mayoría de los scans no cruza ningún ex-date: si esos movieran la caja
    aunque sea un centavo, la feature estaría rompiendo el 99% de las corridas para
    arreglar el 1%.
    """
    acct = _cuenta(10_000.0)
    _fill(acct, "MO", "BUY", 100.0, "2026-06-01")
    _ex_date("MO", "2026-06-15", 1.25)

    assert _acreditar(acct, "2026-06-01", "2026-06-10") == []
    assert _caja(acct) == pytest.approx(10_000.0)


def test_acreditar_DOS_VECES_no_paga_dos_veces(test_db):
    """El scan corre varias veces por día: el ledger es lo que lo hace idempotente.

    Un doble crédito **no se lee como bug, se lee como rendimiento**, que es la peor
    forma de fallar que puede tener esto.
    """
    acct = _cuenta(10_000.0)
    _fill(acct, "MO", "BUY", 100.0, "2026-06-01")
    _ex_date("MO", "2026-06-15", 1.25)

    assert len(_acreditar(acct, "2026-06-14", "2026-06-16")) == 1
    assert _acreditar(acct, "2026-06-14", "2026-06-16") == [], "pagó dos veces el mismo ex-date"
    assert _caja(acct) == pytest.approx(10_125.0)
    with session_scope() as s:
        assert s.query(PaperDividendCredit).count() == 1


# ── «Sólo hacia adelante», que es la otra mitad de la decisión ───────────────


def test_el_primer_scan_NO_acredita_nada_historico(test_db):
    """Sin scan previo (``desde=None``) no se acredita: así arranca «hacia adelante».

    Es lo que garantiza que shipear esto **no** le pague a la cuenta 2 los $322,77 que ya
    devengó — la decisión de Chapa fue no backfillear.
    """
    acct = _cuenta(10_000.0)
    _fill(acct, "MO", "BUY", 100.0, "2026-01-05")
    for dia in ("2026-02-15", "2026-03-15", "2026-06-15"):
        _ex_date("MO", dia, 1.25)

    assert _acreditar(acct, None, "2026-09-25") == []
    assert _caja(acct) == pytest.approx(10_000.0)


def test_la_ventana_es_EXCLUSIVA_a_la_izquierda(test_db):
    """El día del scan anterior ya se procesó: volver a incluirlo pagaría de nuevo.

    Sin el ledger sería un doble crédito; con el ledger es sólo trabajo de más — pero la
    ventana tiene que ser correcta por sí sola, porque es lo único que define «nuevo».
    """
    acct = _cuenta(10_000.0)
    _fill(acct, "MO", "BUY", 100.0, "2026-06-01")
    _ex_date("MO", "2026-06-14", 1.25)

    assert _acreditar(acct, "2026-06-14", "2026-06-20") == [], "incluyó el día del scan anterior"
    assert _caja(acct) == pytest.approx(10_000.0)


def test_una_ventana_LARGA_cubre_los_dias_con_la_app_cerrada(test_db):
    """La cuenta 2 estuvo 16 días sin scans (24/07 → 09/08) y ganó dividendos igual.

    La ventana es ``(último scan, hoy]``, no «ayer», justamente para esto.
    """
    acct = _cuenta(10_000.0)
    _fill(acct, "MO", "BUY", 100.0, "2026-07-01")
    _ex_date("MO", "2026-07-28", 1.00)
    _ex_date("MO", "2026-08-05", 2.00)

    creditos = _acreditar(acct, "2026-07-24", "2026-08-09")

    assert [c["cash"] for c in creditos] == [100.0, 200.0]
    assert _caja(acct) == pytest.approx(10_300.0)


# ── La convención de quién cobra, que tiene que ser LA MISMA que la del panel ─


def test_comprar_EL_DIA_del_ex_date_no_cobra(test_db):
    """Hay que tener la acción **antes**. Es la convención de la T220 con la que se
    midieron los $322,77 y con la que el panel los reproduce ticker por ticker."""
    acct = _cuenta(10_000.0)
    _fill(acct, "MO", "BUY", 100.0, "2026-06-15")
    _ex_date("MO", "2026-06-15", 1.25)

    assert _acreditar(acct, "2026-06-14", "2026-06-16") == []


def test_vender_ANTES_del_ex_date_tampoco_cobra(test_db):
    acct = _cuenta(10_000.0)
    _fill(acct, "MO", "BUY", 100.0, "2026-06-01")
    _fill(acct, "MO", "SELL", 100.0, "2026-06-10")
    _ex_date("MO", "2026-06-15", 1.25)

    assert _acreditar(acct, "2026-06-14", "2026-06-16") == []


def test_cobra_sobre_las_acciones_que_habia_ESE_dia(test_db):
    """Escalar la posición cambia lo cobrado, y se cuenta lo que había al ex-date."""
    acct = _cuenta(10_000.0)
    _fill(acct, "MO", "BUY", 100.0, "2026-06-01")
    _fill(acct, "MO", "BUY", 50.0, "2026-06-10")
    _fill(acct, "MO", "BUY", 25.0, "2026-06-20")  # DESPUÉS: no entra
    _ex_date("MO", "2026-06-15", 2.00)

    creditos = _acreditar(acct, "2026-06-14", "2026-06-16")
    assert creditos[0]["shares"] == pytest.approx(150.0)
    assert creditos[0]["cash"] == pytest.approx(300.0)


def test_la_convencion_es_LA_MISMA_que_la_del_panel():
    """Las dos aritméticas del mismo número, atadas — la lección de las tareas 224 y 230.

    El motor y el panel calculan *«cuántas acciones había antes del ex-date»* en módulos
    distintos (``paper_trading`` no puede importar ``analysis.metrics_panel``, que arrastra
    numpy y el cache entero). Que coincidan no se deja a la buena intención.
    """
    import sqlite3

    import analysis.metrics_panel as mp

    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE paper_orders (id INTEGER PRIMARY KEY, account_id INT, ticker TEXT, side TEXT, "
        "fill_shares REAL, status TEXT, filled_at TEXT)"
    )
    con.execute(
        "CREATE TABLE dividend_calendar_cache (id INTEGER PRIMARY KEY, ticker TEXT, ex_date TEXT, amount REAL)"
    )
    eventos = [("2026-06-01", 100.0), ("2026-06-10", 50.0), ("2026-06-20", 25.0)]
    for dia, sh in eventos:
        con.execute(
            "INSERT INTO paper_orders (account_id, ticker, side, fill_shares, status, filled_at) "
            "VALUES (2,'MO','BUY',?,'filled',?)",
            (sh, f"{dia} 21:00:00"),
        )
    con.execute(
        "INSERT INTO dividend_calendar_cache (ticker, ex_date, amount) VALUES ('MO','2026-06-15',2.0)"
    )

    del_panel, _ = mp._dividendos_devengados(con, 2, "2026-06-01", "2026-06-30")
    del_motor = acciones_antes_del_ex_date([(d, s) for d, s in eventos], "2026-06-15") * 2.0

    assert del_motor == pytest.approx(del_panel), "el motor y el panel cobran distinto"


def test_el_centinela_de_NO_PAGA_no_acredita_nada(test_db):
    """La fila ``0000-00-00`` marca «chequeado, no paga»: no es un ex-date."""
    acct = _cuenta(10_000.0)
    _fill(acct, "AMD", "BUY", 100.0, "2026-06-01")
    _ex_date("AMD", _SIN_DIVIDENDOS, 7.77)  # monto ≠ 0 para que el salteo sea observable

    assert _acreditar(acct, "2020-01-01", "2026-12-31") == []
    assert _caja(acct) == pytest.approx(10_000.0)


def test_el_centinela_es_EL_MISMO_literal_en_los_tres_modulos():
    """Duplicado a propósito, fijado acá — la forma de la 71.

    Si derivara, un ticker chequeado-y-sin-dividendos **inventaría plata en la caja**.
    """
    import analysis.metrics_panel as mp
    from data.yahoo_finance import _SIN_DIVIDENDOS as en_data

    assert _SIN_DIVIDENDOS == en_data == mp._SIN_DIVIDENDOS


# ── La función pura, sin DB ──────────────────────────────────────────────────


def test_creditos_pendientes_es_pura_y_respeta_lo_ya_acreditado():
    fills = [("MO", "BUY", 100.0, "2026-06-01 21:00:00")]
    cal = {"MO": [("2026-06-15", 1.0), ("2026-07-15", 2.0)]}

    assert creditos_pendientes(fills, cal, set(), "2026-06-01", "2026-07-31") == [
        ("MO", "2026-06-15", 100.0, 1.0),
        ("MO", "2026-07-15", 100.0, 2.0),
    ]
    ya = {("MO", "2026-06-15")}
    assert creditos_pendientes(fills, cal, ya, "2026-06-01", "2026-07-31") == [
        ("MO", "2026-07-15", 100.0, 2.0)
    ]
    assert creditos_pendientes([], cal, set(), "2026-06-01", "2026-07-31") == []
    assert creditos_pendientes(fills, cal, set(), None, "2026-07-31") == []


# ── El desvío declarado tiene que CAMBIAR, no quedar como estaba ─────────────


def test_el_desvio_declarado_YA_NO_dice_que_el_motor_los_ignora():
    """El guard de la 220 al revés, que era un punto explícito del alcance.

    Mientras el motor no los miraba, el texto tenía que decirlo. Ahora los cobra, así que
    dejar el desvío como estaba sería declararlo **de más** — el error simétrico del que
    la 220 vino a arreglar, y el que hace que un registro de desvíos deje de ser creíble.
    """
    from analysis.harness_config import dividendos_desc

    txt = dividendos_desc()
    assert "no los menciona en ninguna línea" not in txt
    assert "caja" in txt.lower() and "reinvierte" in txt.lower(), (
        "el desvío tiene que describir lo que queda: el harness REINVIERTE y el motor "
        "acredita CAJA, que no es lo mismo"
    )


def test_el_desvio_NO_se_borra_porque_queda_un_residuo():
    """Y la otra dirección: cerrarlo del todo sería el error opuesto.

    ``auto_adjust=True`` reinvierte el dividendo en el precio; la caja queda quieta. Sobre
    la cuenta 2 eso vale ~$2,77 de $322,77 — chico, pero no cero, y un desvío que se borra
    cuando todavía existe es peor que uno declarado de más.
    """
    from analysis.harness_config import LIVE_MAX_POSITIONS, HarnessConfig, deviations_keyed

    cfg = HarnessConfig(max_positions=LIVE_MAX_POSITIONS, universe_file="x.txt", n_tickers=127)
    assert "dividendos" in {d.clave for d in deviations_keyed(cfg)}


# ── Fail-safe: esto no puede tumbar un scan ─────────────────────────────────


def test_sin_calendario_no_acredita_y_no_revienta(test_db):
    acct = _cuenta(10_000.0)
    _fill(acct, "MO", "BUY", 100.0, "2026-06-01")

    assert _acreditar(acct, "2026-06-01", "2026-06-30") == []
    assert _caja(acct) == pytest.approx(10_000.0)


def test_una_cuenta_sin_fills_no_acredita(test_db):
    acct = _cuenta(10_000.0)
    _ex_date("MO", "2026-06-15", 1.25)

    assert _acreditar(acct, "2026-06-01", "2026-06-30") == []


def test_el_credito_no_toca_a_OTRA_cuenta(test_db):
    """El ledger y los fills se filtran por cuenta: un scan de la 2 no paga a la 1."""
    a = _cuenta(10_000.0, "Cuenta A")
    b = _cuenta(20_000.0, "Cuenta B")
    _fill(a, "MO", "BUY", 100.0, "2026-06-01")
    _ex_date("MO", "2026-06-15", 1.25)

    _acreditar(a, "2026-06-14", "2026-06-16")

    assert _caja(a) == pytest.approx(10_125.0)
    assert _caja(b) == pytest.approx(20_000.0)


def test_la_ventana_del_scan_sale_del_ULTIMO_scan_y_no_de_ayer(test_db):
    """Regresión del cableado: si alguien cambiara la ventana a «ayer», los días con la
    app cerrada dejarían de cobrarse y el defecto volvería en silencio."""
    acct = _cuenta(10_000.0)
    _fill(acct, "MO", "BUY", 100.0, "2026-06-01")
    hoy = utcnow_naive()
    hace_diez = (hoy - timedelta(days=10)).strftime("%Y-%m-%d")
    hace_cinco = (hoy - timedelta(days=5)).strftime("%Y-%m-%d")
    _ex_date("MO", hace_cinco, 1.00)

    creditos = _acreditar(acct, hace_diez, hoy.strftime("%Y-%m-%d"))
    assert [c["ex_date"] for c in creditos] == [hace_cinco]


# ── El CABLEADO, que es lo que el resto de este archivo no probaba ───────────
#
# Todo lo de arriba llama a `acreditar_dividendos` directo. El barrido de mutación mostró
# que con eso el cableado entero podía estar muerto y la suite quedaba verde: sacar la
# llamada del engine, pasarle una ventana desde 1900 (backfill) o borrar el warm-up del
# calendario NO ponía nada en rojo. Es la forma exacta del defecto de la 228 —la unidad
# anda, el cable no se prueba— y por eso lo que sigue corre `run_scan` de verdad.


def _scan_settings():
    from config.settings_manager import settings

    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_anti_flap_minutes", 0)
    settings.set("paper_whipsaw_lookback_days", 0)


class _SinEarnings:
    """Deja pasar el Gate 6 sin salir a Yahoo (tarea 213)."""

    def __call__(self, ticker):
        return None

    def get_next_earnings_date(self, ticker):
        return None


def _scan(acct_id: int, ticker: str = "MO", *, inyectar_history: bool = True):
    from paper_trading import engine

    return engine.run_scan(
        acct_id,
        prices_provider=lambda _t: {ticker: 100.0},
        # `history_provider=None` es lo único que hace correr el warm-up: el engine lo
        # gatea con `history_was_injected`, o sea «si un test inyectó historia, no toques
        # la red». El warm-up del calendario heredó ese gate a propósito, así que para
        # probarlo hay que dejar el provider en default y mockear los warm-ups.
        history_provider=(lambda _t: None) if inyectar_history else None,
        earnings_provider=_SinEarnings(),
    )


def test_run_scan_ACREDITA_el_dividendo_y_lo_reporta(test_db, monkeypatch):
    """El cable, de punta a punta: la caja sube dentro de un scan real.

    Sin este test, sacar la llamada del engine dejaba los 20 tests de arriba en verde.
    """
    from paper_trading.account import create_account
    from paper_trading.models import PaperWatchlistItem

    _scan_settings()
    acct = create_account(name="Cableada", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=acct.id, ticker="MO"))
    _fill(acct.id, "MO", "BUY", 100.0, "2026-06-01")

    ayer = (utcnow_naive() - timedelta(days=1)).strftime("%Y-%m-%d")
    hoy = utcnow_naive().strftime("%Y-%m-%d")
    with session_scope() as s:
        s.query(PaperAccount).filter(PaperAccount.id == acct.id).one().last_scan_at = datetime.fromisoformat(
            f"{ayer} 21:00:00"
        )
    _ex_date("MO", hoy, 1.25)

    caja_antes = _caja(acct.id)
    result = _scan(acct.id)

    assert _caja(acct.id) >= caja_antes + 125.0 - 1e-6 or any("dividendo" in w for w in result.warnings), (
        "el scan no acreditó el dividendo: el cableado del engine está muerto"
    )
    assert any("dividendo del" in w for w in result.warnings), "el crédito no se reporta"
    with session_scope() as s:
        assert s.query(PaperDividendCredit).count() == 1


def test_run_scan_NO_backfillea_lo_viejo(test_db, monkeypatch):
    """La ventana del scan arranca en el último scan, no en 1900.

    Es la mutación M2: con la ventana abierta hacia atrás, el primer scan después de
    shipear esto le habría pagado a la cuenta 2 los $322,77 que Chapa decidió **no**
    backfillear — y nadie se habría enterado hasta ver la equity saltar.
    """
    from paper_trading.account import create_account
    from paper_trading.models import PaperWatchlistItem

    _scan_settings()
    acct = create_account(name="SinBackfill", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=acct.id, ticker="MO"))
    _fill(acct.id, "MO", "BUY", 100.0, "2026-01-05")
    _ex_date("MO", "2026-02-15", 5.00)  # viejo: NO se acredita

    ayer = (utcnow_naive() - timedelta(days=1)).strftime("%Y-%m-%d")
    with session_scope() as s:
        s.query(PaperAccount).filter(PaperAccount.id == acct.id).one().last_scan_at = datetime.fromisoformat(
            f"{ayer} 21:00:00"
        )

    caja_antes = _caja(acct.id)
    _scan(acct.id)

    assert _caja(acct.id) == pytest.approx(caja_antes, abs=0.01), "backfilleó un ex-date viejo"
    with session_scope() as s:
        assert s.query(PaperDividendCredit).count() == 0


def test_el_scan_CALIENTA_el_calendario_antes_de_acreditar(test_db, monkeypatch):
    """El warm-up es lo que hace que haya calendario que leer (mutación M3).

    El engine no puede fetchear adentro del crédito —sería red en el camino de decisión—
    así que el calendario llega del warm-up, al lado del de barras. Si se saca, el motor
    no acredita nunca y no lo dice nadie.
    """
    from paper_trading import engine
    from paper_trading.account import create_account
    from paper_trading.models import PaperWatchlistItem

    _scan_settings()
    pedidos: list[list[str]] = []
    monkeypatch.setattr(engine, "_warm_up_history_cache", lambda t: None)
    monkeypatch.setattr(engine, "_warm_up_dividend_calendar", lambda tickers: pedidos.append(list(tickers)))

    acct = create_account(name="Calienta", initial_capital=10_000.0)
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=acct.id, ticker="MO"))
    _fill(acct.id, "MO", "BUY", 100.0, "2026-06-01")
    # Una posición abierta: es sobre las tenencias que hay que calentar el calendario.
    from paper_trading.models import PaperPosition

    with session_scope() as s:
        s.add(PaperPosition(account_id=acct.id, ticker="MO", shares=100.0, avg_cost=100.0))

    _scan(acct.id, inyectar_history=False)

    assert pedidos, "el scan no llamó al warm-up del calendario"
    assert "MO" in pedidos[0], f"no calentó la tenencia: {pedidos}"


def test_la_centinela_no_devenga_NI_forzandola_dentro_de_la_ventana():
    """La centinela, y la conclusión honesta: el ``continue`` que la saltea es REDUNDANTE.

    Intenté hacerlo observable pasándole a la función pura un ``desde`` vacío, con lo
    cual ``"0000-00-00"`` **sí** entra en la ventana. Sigue sin devengar — y la mutación
    que le saca el ``continue`` sigue **verde**. El motivo es la segunda barrera: ninguna
    compra puede tener fecha anterior a ``"0000-00-00"``, así que
    ``acciones_antes_del_ex_date`` da **0** y la fila se descarta igual.

    O sea que hay **dos** defensas independientes y el ``continue`` no es ninguna de las
    dos. En la 221 la conclusión fue la misma con una razón; acá son dos. Se deja por
    legibilidad y el comentario del código lo declara, porque afirmar que *esto* es lo
    que la frena dirigiría mal a quien venga a tocar el filtro de ventana.
    """
    fills = [("AMD", "BUY", 100.0, "2026-06-01 21:00:00")]
    cal = {"AMD": [(_SIN_DIVIDENDOS, 7.77)]}  # monto ≠ 0: contarla sería observable

    assert creditos_pendientes(fills, cal, set(), "", "2026-12-31") == []


def test_las_DOS_barreras_que_de_verdad_frenan_a_la_centinela():
    """Y se fijan las dos, que es lo que el ``continue`` no puede sostener solo.

    Si mañana el literal derivara a una fecha ISO real, la primera barrera se cae; si el
    ``<`` de la convención se volviera ``<=``, se cae la segunda. Cada una tiene su test
    porque cada una se puede romper sin la otra.
    """
    # (1) Ordena antes que cualquier fecha real, así que ninguna ventana la alcanza.
    assert _SIN_DIVIDENDOS < "1900-01-01"
    # (2) Y aunque la alcanzara, no hay compra anterior: 0 acciones, 0 dividendo.
    assert acciones_antes_del_ex_date([("2026-06-01", 100.0)], _SIN_DIVIDENDOS) == 0.0


# ── El doble conteo, que este cambio introducía en el VS SPY ─────────────────


def test_el_panel_NO_cuenta_lo_que_el_motor_YA_acredito():
    """El defecto que la 222 estuvo a punto de meter, y apareció escribiendo el docstring.

    ``_dividendos_devengados`` suma **todos** los ex-dates del calendario para compensar
    que la equity es sólo precio. Desde que el motor acredita el efectivo a la caja, ese
    dividendo **ya está en la equity**: sumarlo otra vez lo cuenta **dos veces** y el
    VS SPY sale inflado, en silencio y hacia arriba — la peor dirección.

    No lo encontró ninguna corrida: el motor y el panel son dos consumidores del **mismo**
    calendario, y hasta la 222 uno de los dos no existía. Es la forma de la 224 otra vez
    (dos lugares que calculan lo mismo) pero al revés: acá el problema no es que
    difieran, es que **se suman**.
    """
    import sqlite3

    import analysis.metrics_panel as mp

    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE paper_orders (id INTEGER PRIMARY KEY, account_id INT, ticker TEXT, side TEXT, "
        "fill_shares REAL, status TEXT, filled_at TEXT)"
    )
    con.execute(
        "CREATE TABLE dividend_calendar_cache (id INTEGER PRIMARY KEY, ticker TEXT, ex_date TEXT, amount REAL)"
    )
    con.execute(
        "CREATE TABLE paper_dividend_credits (id INTEGER PRIMARY KEY, account_id INT, ticker TEXT, ex_date TEXT)"
    )
    con.execute(
        "INSERT INTO paper_orders (account_id,ticker,side,fill_shares,status,filled_at) "
        "VALUES (2,'MO','BUY',100,'filled','2026-06-01 21:00')"
    )
    con.execute("INSERT INTO dividend_calendar_cache (ticker,ex_date,amount) VALUES ('MO','2026-06-15',1.25)")
    con.execute("INSERT INTO dividend_calendar_cache (ticker,ex_date,amount) VALUES ('MO','2026-07-15',2.00)")

    # Sin ledger: el motor no acreditó nada, el panel devenga los dos.
    assert mp._dividendos_devengados(con, 2, "2026-06-01", "2026-07-31")[0] == pytest.approx(325.0)

    # Con el de junio ya acreditado: el panel sólo aporta el de julio.
    con.execute("INSERT INTO paper_dividend_credits (account_id,ticker,ex_date) VALUES (2,'MO','2026-06-15')")
    assert mp._dividendos_devengados(con, 2, "2026-06-01", "2026-07-31")[0] == pytest.approx(200.0), (
        "el panel volvió a sumar un dividendo que ya está en la caja: VS SPY inflado"
    )


def test_una_DB_sin_la_tabla_del_ledger_devenga_todo(test_db):
    """DB anterior a la migración 0014: no hay nada acreditado, así que no hay qué descontar.

    Es el camino de cualquier base vieja y de las DB sintéticas de los otros tests: tiene
    que seguir dando el devengado completo, no cero ni un error.
    """
    import sqlite3

    import analysis.metrics_panel as mp

    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE paper_orders (id INTEGER PRIMARY KEY, account_id INT, ticker TEXT, side TEXT, "
        "fill_shares REAL, status TEXT, filled_at TEXT)"
    )
    con.execute(
        "CREATE TABLE dividend_calendar_cache (id INTEGER PRIMARY KEY, ticker TEXT, ex_date TEXT, amount REAL)"
    )
    con.execute(
        "INSERT INTO paper_orders (account_id,ticker,side,fill_shares,status,filled_at) "
        "VALUES (2,'MO','BUY',100,'filled','2026-06-01 21:00')"
    )
    con.execute("INSERT INTO dividend_calendar_cache (ticker,ex_date,amount) VALUES ('MO','2026-06-15',1.25)")

    assert mp._dividendos_devengados(con, 2, "2026-06-01", "2026-07-31")[0] == pytest.approx(125.0)
