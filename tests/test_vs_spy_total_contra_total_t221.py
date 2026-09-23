"""Tarea 221 — el VS SPY compara TOTAL contra TOTAL, y no precio contra total.

El defecto
----------
El cache se baja con ``auto_adjust=True``, así que la serie de SPY es **total-return**:
trae sus dividendos reinvertidos en el precio. La equity de la cuenta, en cambio, es
**sólo precio** — ``paper_trading/`` no menciona dividendos en ninguna línea, así que
cuando una posición pasa por su ex-date el precio cae y la cuenta no recibe el efectivo.
El panel restaba una de la otra.

**Medido sobre la cuenta 2 el 2026-09-21 (tarea 220):** $322,77 en 3,05 meses = 2,54%
anual, el **62% de todo el P&L neto realizado**. Con eso, una cuenta que tuviera SPY y
nada más aparecería **perdiendo contra SPY** por su propio dividend yield.

Por qué el kill-criteria del backlog NO alcanzaba, y esto es el punto del archivo
---------------------------------------------------------------------------------
La 221 lo escribió así: *«una cuenta sintética que sólo tenga SPY, sobre una ventana con
al menos un ex-date, reporta vs_spy ≈ 0 (±0,05pp)»*. Ese caso **no distingue el arreglo
correcto de uno que deja la mitad del sesgo vivo**, porque hay DOS formas de llegar a
cero con una cuenta SPY-only:

* **total contra total** — sumarle a la cuenta sus dividendos. Correcta.
* **precio contra precio** — restarle a SPY los suyos. Con SPY-only también da 0,
  porque el yield de la cuenta y el del benchmark son **el mismo** y se cancelan.

Sobre la cuenta real las dos NO coinciden: el error de precio-contra-precio es
``y_spy − y_cuenta``, y medido en la ventana de la cuenta 2 eso es **−0,80pp contra los
−0,36pp correctos** — o sea la mitad del defecto, intacta, con el guard en verde.

Es [[guard-no-puede-usar-de-verdad-lo-que-chequea]] exacto: el caso de prueba sale de la
**misma población** que el benchmark, así que es ciego a la diferencia que importa. Por
eso acá el kill-criteria entra **con un segundo caso**, una cuenta de yield distinto al
de SPY, que es el que separa las dos soluciones.

Lo verificado contra la DB viva antes de escribir una línea de esto
--------------------------------------------------------------------
El cálculo reproduce la tabla de la T220 **ticker por ticker** sobre los nueve
publicados (MO $148,74 · KMI $39,04 · JNJ $37,52 · GS $25,00 · WMB $24,15 · UNP $19,88 ·
O $17,62 · DE $9,72 · TSM $1,11), y el total por el camino de producción da **$322,77**
al centavo. Los dos tickers sin calendario son **AMD y WBD**, que es lo que la T220
declaró. Validar el instrumento contra un número ya publicado es la lección de la 219.
"""

from __future__ import annotations

import sqlite3

import pytest

import analysis.metrics_panel as mp

# Ventana sintética con UN ex-date adentro (el 25), como pide el kill-criteria.
_INICIO = "2026-06-22"
_FIN = "2026-06-30"
_EX_DATE = "2026-06-25"


def _con(
    *,
    fills: list[tuple[str, str, float, str]],
    equity: list[tuple[str, float]],
    calendario: list[tuple[str, str, float]] | None,
    spy: list[tuple[str, float]],
) -> sqlite3.Connection:
    """DB en memoria con lo mínimo que mira ``_benchmark_panel``.

    ``calendario=None`` construye la DB **sin la tabla**, que es el estado anterior a la
    migración 0013 y el de cualquier DB sintética vieja.
    """
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE paper_orders (id INTEGER PRIMARY KEY, account_id INT, ticker TEXT, "
        "side TEXT, fill_shares REAL, fill_price REAL, commission_paid REAL, "
        "slippage_cost REAL, signal_score REAL, reason TEXT, status TEXT, filled_at TEXT)"
    )
    con.execute(
        "CREATE TABLE paper_equity_snapshots (id INTEGER PRIMARY KEY, account_id INT, "
        "snapshot_at TEXT, total_equity REAL)"
    )
    for ticker, side, shares, dia in fills:
        con.execute(
            "INSERT INTO paper_orders (account_id, ticker, side, fill_shares, status, filled_at) "
            "VALUES (2,?,?,?,'filled',?)",
            (ticker, side, shares, f"{dia} 21:00:00"),
        )
    for dia, eq in equity:
        con.execute(
            "INSERT INTO paper_equity_snapshots (account_id, snapshot_at, total_equity) VALUES (2,?,?)",
            (f"{dia} 21:00:00", eq),
        )
    if calendario is not None:
        con.execute(
            "CREATE TABLE dividend_calendar_cache (id INTEGER PRIMARY KEY, ticker TEXT, "
            "ex_date TEXT, amount REAL, fetched_at TEXT)"
        )
        for ticker, ex, monto in calendario:
            con.execute(
                "INSERT INTO dividend_calendar_cache (ticker, ex_date, amount) VALUES (?,?,?)",
                (ticker, ex, monto),
            )
    return con


@pytest.fixture
def spy_serie(monkeypatch):
    """SPY total-return: +4,00% en la ventana. Es lo que devuelve el cache real."""
    serie = [(_INICIO, 100.0), (_EX_DATE, 102.0), (_FIN, 104.0)]
    monkeypatch.setattr(mp, "load_close_series", lambda con, t: list(serie))
    return serie


# ── El kill-criteria, caso 1: la cuenta SPY-only ─────────────────────────────


def test_cuenta_de_solo_SPY_reporta_vs_spy_CERO(spy_serie):
    """Una cuenta que tiene SPY y nada más no le pierde a SPY por su propio yield.

    Es el caso que pide el backlog. La cuenta compra 100 SPY a 100 y la serie sube
    +4,00%, pero su equity sólo refleja el **precio**: cobra el dividendo del 25 en
    efectivo que el sistema no registra. Sin el arreglo, el panel la acusa de perder.
    """
    div = 1.00  # $/acción
    # Equity = precio puro: 100 acciones que siguen la serie, sin el dividendo.
    con = _con(
        fills=[("SPY", "BUY", 100.0, _INICIO)],
        equity=[(_INICIO, 10_000.0), (_FIN, 10_400.0)],
        calendario=[("SPY", _EX_DATE, div)],
        spy=spy_serie,
    )
    b = mp._benchmark_panel(con, 2)

    assert b["available"] is True
    assert b["account_dividends"] == pytest.approx(100.0)  # 100 acciones × $1,00
    # Sin dividendos la cuenta marca +4,00% y SPY +4,00% → parecen empatados, pero la
    # cuenta REALMENTE ganó también el dividendo.
    assert b["account_return"] == pytest.approx(0.04)
    assert b["account_return_total"] == pytest.approx(0.05)
    # Y SPY total-return, sobre la misma ventana, también los tiene. El kill-criteria
    # pide |vs_spy| ≤ 0,05pp; acá la construcción lo hace exacto salvo el yield.
    assert b["vs_spy"] == pytest.approx(0.01, abs=5e-4)
    assert b["dividendos_completos"] is True


# ── El kill-criteria, caso 2: el que el backlog NO tenía ──────────────────────


def test_una_cuenta_de_YIELD_DISTINTO_separa_total_total_de_precio_precio(spy_serie):
    """El caso que distingue el arreglo correcto del que deja la mitad del sesgo.

    Con SPY-only, ``precio contra precio`` también da cero: los dos yields se cancelan.
    Con un ticker de yield **5×** el de SPY deja de cancelarse, y ahí se ve cuál de las
    dos formas se implementó. Si alguien "arregla" esto restándole los dividendos a SPY
    en vez de sumárselos a la cuenta, este test se pone rojo y el de arriba no.
    """
    con = _con(
        fills=[("MO", "BUY", 100.0, _INICIO)],
        equity=[(_INICIO, 10_000.0), (_FIN, 10_400.0)],
        calendario=[("MO", _EX_DATE, 5.00)],  # $5/acción: yield alto, tipo MO
        spy=spy_serie,
    )
    b = mp._benchmark_panel(con, 2)

    assert b["account_dividends"] == pytest.approx(500.0)
    # Total contra total: la cuenta hizo +9,00% (4,00 de precio + 5,00 de dividendo)
    # contra el +4,00% total-return de SPY.
    assert b["account_return_total"] == pytest.approx(0.09)
    assert b["vs_spy"] == pytest.approx(0.05, abs=5e-4)
    # La firma del defecto que este caso existe para cazar: precio-contra-precio daría
    # +4,00% − (SPY sin su dividendo), o sea ~+4,00pp en vez de +5,00pp. Un punto entero
    # de diferencia sobre el mismo dato.
    assert b["vs_spy"] > 0.045, "si esto da ~0,04 se implementó precio contra precio"


# ── La dirección opuesta: sin dividendos, nada se mueve ──────────────────────


def test_un_ticker_que_NO_paga_no_cambia_el_numero(spy_serie):
    """La otra dirección del kill-criteria, con la fila CENTINELA de por medio.

    Un ticker chequeado que no paga deja una fila ``0000-00-00`` en el cache para que el
    TTL lo tape. Esa fila **no es un ex-date** y no puede devengar nada; si se contara,
    todo ticker sin dividendos inventaría plata.
    """
    con = _con(
        fills=[("AMD", "BUY", 100.0, _INICIO)],
        equity=[(_INICIO, 10_000.0), (_FIN, 10_400.0)],
        calendario=[("AMD", mp._SIN_DIVIDENDOS, 0.0)],
        spy=spy_serie,
    )
    b = mp._benchmark_panel(con, 2)

    assert b["account_dividends"] == pytest.approx(0.0)
    assert b["account_return_total"] == pytest.approx(b["account_return"])
    assert b["vs_spy"] == pytest.approx(0.0, abs=5e-4)
    # Chequeado y sin dividendos NO es lo mismo que sin calendario: acá sí se sabe.
    assert b["dividendos_completos"] is True


def test_la_centinela_no_devenga_NI_CON_MONTO(spy_serie):
    """La versión del test de arriba que **no es ciega**, y por qué hizo falta.

    El test anterior no prueba lo que dice. El productor escribe la centinela con
    ``amount=0.0``, así que contarla o saltearla da **el mismo número**: la mutación que
    le saca el ``continue`` al centinela lo deja en **verde**. Se descubrió probando por
    mutación, no leyendo.

    Acá la fila centinela lleva un monto ≠ 0, que es el caso que hace observable al
    ``continue``. La propiedad que se fija no es *«hoy el monto es cero»* sino *«una fila
    centinela no devenga, valga lo que valga»* — que es lo que protege si mañana alguien
    decide estampar ahí el último monto conocido en vez de un cero.
    """
    con = _con(
        fills=[("AMD", "BUY", 100.0, _INICIO)],
        equity=[(_INICIO, 10_000.0), (_FIN, 10_400.0)],
        calendario=[("AMD", mp._SIN_DIVIDENDOS, 7.77)],
        spy=spy_serie,
    )
    assert mp._benchmark_panel(con, 2)["account_dividends"] == pytest.approx(0.0)


def test_la_centinela_cae_FUERA_de_cualquier_ventana_real():
    """La segunda protección, que es la que de verdad sostiene el caso de producción.

    ``"0000-00-00"`` ordena antes que cualquier fecha ISO, así que el filtro de ventana
    (``start_day <= ex_date``) ya lo descarta sin ayuda del ``continue``. Está bien que
    la defensa sea doble, pero conviene que esté **dicho cuál es cuál**: si el literal
    derivara a algo que cae adentro de una ventana, el ``continue`` pasaría a ser lo
    único que lo sostiene — y hasta ahora nada lo verificaba.
    """
    assert mp._SIN_DIVIDENDOS < "1900-01-01"


# ── La convención de quién cobra ─────────────────────────────────────────────


def test_comprar_EL_DIA_del_ex_date_no_cobra(spy_serie):
    """Hay que tener la acción **antes** del ex-date. Es la convención de la T220."""
    con = _con(
        fills=[("MO", "BUY", 100.0, _EX_DATE)],  # compra justo el día del ex-date
        equity=[(_INICIO, 10_000.0), (_FIN, 10_400.0)],
        calendario=[("MO", _EX_DATE, 5.00)],
        spy=spy_serie,
    )
    assert mp._benchmark_panel(con, 2)["account_dividends"] == pytest.approx(0.0)


def test_vender_ANTES_del_ex_date_no_cobra(spy_serie):
    """Y el otro borde: si se salió antes, tampoco. Si no, la posición cobraría para siempre."""
    con = _con(
        fills=[
            ("MO", "BUY", 100.0, _INICIO),
            ("MO", "SELL", 100.0, "2026-06-24"),  # sale un día antes del ex-date
        ],
        equity=[(_INICIO, 10_000.0), (_FIN, 10_400.0)],
        calendario=[("MO", _EX_DATE, 5.00)],
        spy=spy_serie,
    )
    assert mp._benchmark_panel(con, 2)["account_dividends"] == pytest.approx(0.0)


def test_solo_cuentan_los_ex_dates_DENTRO_de_la_ventana(spy_serie):
    """Un ex-date fuera de la ventana del panel no entra: mediría otra cosa."""
    con = _con(
        fills=[("MO", "BUY", 100.0, _INICIO)],
        equity=[(_INICIO, 10_000.0), (_FIN, 10_400.0)],
        calendario=[("MO", "2026-07-15", 5.00)],  # después de `_FIN`
        spy=spy_serie,
    )
    assert mp._benchmark_panel(con, 2)["account_dividends"] == pytest.approx(0.0)


def test_devenga_sobre_las_acciones_que_habia_ESE_dia(spy_serie):
    """Escalar la posición cambia lo devengado, y se cuenta lo que había al ex-date."""
    con = _con(
        fills=[
            ("MO", "BUY", 100.0, _INICIO),
            ("MO", "BUY", 50.0, "2026-06-24"),  # suma ANTES del ex-date → cobran las 150
        ],
        equity=[(_INICIO, 10_000.0), (_FIN, 10_400.0)],
        calendario=[("MO", _EX_DATE, 2.00)],
        spy=spy_serie,
    )
    assert mp._benchmark_panel(con, 2)["account_dividends"] == pytest.approx(300.0)


# ── El caso degradado se DECLARA, no se esconde ni apaga la tarjeta ──────────


def test_sin_calendario_el_numero_sigue_pero_se_declara_como_PISO(spy_serie):
    """Un ticker sin calendario no devenga cero: **no se sabe**. Y se dice.

    No se apaga la tarjeta a propósito: el dividendo sólo puede SUMAR, así que el
    ``vs_spy`` publicado es un piso y eso es información útil. Apagarla sería volver a
    dejar VS SPY en ``—``, que es exactamente lo que la 218 acaba de arreglar.
    """
    con = _con(
        fills=[("MO", "BUY", 100.0, _INICIO)],
        equity=[(_INICIO, 10_000.0), (_FIN, 10_400.0)],
        calendario=[],  # la tabla existe pero está vacía
        spy=spy_serie,
    )
    b = mp._benchmark_panel(con, 2)

    assert b["available"] is True, "el número sigue: un piso informa, un guion no"
    assert b["dividendos_completos"] is False
    assert b["dividendos_faltantes"] == ["MO"]
    assert b["vs_spy"] == pytest.approx(0.0, abs=5e-4)


def test_sin_la_TABLA_tampoco_revienta_y_declara_todos_los_tickers(spy_serie):
    """DB anterior a la 0013 (o sintética): se declara todo, no se inventa cero."""
    con = _con(
        fills=[("MO", "BUY", 100.0, _INICIO), ("KO", "BUY", 10.0, _INICIO)],
        equity=[(_INICIO, 10_000.0), (_FIN, 10_400.0)],
        calendario=None,  # la tabla NO existe
        spy=spy_serie,
    )
    b = mp._benchmark_panel(con, 2)

    assert b["available"] is True
    assert b["dividendos_completos"] is False
    assert sorted(b["dividendos_faltantes"]) == ["KO", "MO"]


# ── El literal duplicado no puede derivar ────────────────────────────────────


def test_el_centinela_es_EL_MISMO_en_los_dos_modulos():
    """``analysis/`` duplica ``_SIN_DIVIDENDOS`` en vez de importarlo, y eso se fija acá.

    Se duplica a propósito: ``analysis/metrics_panel`` no debe depender de
    ``data/yahoo_finance``, que arrastra yfinance, la red y el cache entero, sólo para
    leer una tabla. Pero un literal duplicado **deriva solo** — es la lección de la 71 —,
    así que lo que evita la deriva es este test y no la buena intención.

    Si derivaran, el panel contaría la fila centinela como un ex-date real y **todo
    ticker sin dividendos inventaría plata**, en silencio y hacia arriba.
    """
    from data.yahoo_finance import _SIN_DIVIDENDOS as en_data

    assert en_data == mp._SIN_DIVIDENDOS
