"""Tarea 223 — la cuenta y SPY se anclan igual: mismo capital, mismo close.

El defecto
----------
``_benchmark_panel`` anclaba los dos lados en cosas distintas, y de **dos** formas
independientes:

1. **La cuenta arrancaba en ``rows[0]``, que ya pagó la fricción del primer scan.**
   ``record_equity_snapshot`` corre al final de ``run_scan``, después de los fills, así
   que el primer snapshot es *capital menos comisión y slippage de la entrada del día 1*.
   Verificado sobre la cuenta 2: ``50.000,00 − 49.976,988175 = 23,011825``, y la suma de
   ``commission_paid + slippage_cost`` de los diez fills del 2026-06-20 da **23,011825**
   al centavo. O sea que el costo de entrada **no contaba como pérdida**, mientras el
   benchmark arrancaba sin pagar nada.
2. **SPY se anclaba en ``_close_on_or_after(start_day)``**, o sea en la rueda siguiente,
   mientras el final usaba ``_close_on_or_before``. La asimetría estaba escrita en esas
   dos líneas. Sólo muerde cuando el primer snapshot cae **fuera** de una rueda — y el de
   la cuenta 2 es el **sábado 2026-06-20** (el viernes 19 fue feriado), así que su equity
   está marcada con los closes del **18** y SPY salía del **22**.

Por qué el kill-criteria del backlog NO alcanzaba, y esto es el punto del archivo
---------------------------------------------------------------------------------
El enunciado presentaba las dos como **alternativas**: *«anclar en el capital nominal es
una opción, y anclar SPY en el close del día anterior es otra; no son equivalentes»*. Y
tiene razón en que no son equivalentes — pero no porque haya que elegir: **arreglan
asimetrías distintas**, y medidas sobre la cuenta 2 van en direcciones opuestas.

====================================  ==========  ==========
anclaje                               ``vs_spy``  Δ vs. hoy
====================================  ==========  ==========
hoy (``rows[0]`` vs primera rueda)    −1,0066pp   —
sólo capital nominal                  −1,0538pp   **−0,047pp**
sólo close previo                     −0,6804pp   **+0,326pp**
**los dos**                           −0,7276pp   +0,279pp
====================================  ==========  ==========

Quedarse con una sola deja la otra viva, y la que el enunciado destacaba es la **chica**:
la del ancla de SPY vale **siete veces más**. Es la lección de la 221 otra vez — un
kill-criteria que no distingue el arreglo correcto del que deja la mitad del sesgo — así
que acá el criterio entra **con los dos casos**, y cada uno con su mutación.

Lo que NO se toca, y va dicho
-----------------------------
**SPY entra sin fricción a propósito.** El benchmark es el índice: *«comprar SPY y no
hacer nada»* rinde el retorno del índice, y lo que la cuenta paga por operar tiene que
verse como pérdida contra él. Darle a SPY una comisión de entrada taparía justo el costo
que esta tarea destapa — y el caso 1 de abajo se pondría en verde con el defecto adentro.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime

import pytest

import analysis.metrics_panel as mp

# Ventana sintética. `_RUEDA_1` es un lunes: arrancando en una rueda, las dos anclas de
# SPY coinciden, y eso deja los casos de fricción aislados del ancla de fecha.
_RUEDA_0 = "2026-06-18"  # jueves — el último close antes del arranque de la cuenta 2
_SABADO = "2026-06-20"  # el primer snapshot REAL de la cuenta 2 (19 feriado, 20 sábado)
_RUEDA_1 = "2026-06-22"  # lunes
_FIN = "2026-06-30"

_CAPITAL = 50_000.0


def _con(
    *,
    equity: list[tuple[str, float]],
    capital: float | None = _CAPITAL,
    fills: list[tuple[str, str, float, str]] = (),
) -> sqlite3.Connection:
    """DB en memoria con lo mínimo que mira ``_benchmark_panel``.

    ``capital=None`` construye la DB **sin ``paper_accounts``**, que es el estado de
    cualquier DB sintética vieja y el camino degradado que la 223 deja declarado.
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
    con.execute(
        "CREATE TABLE dividend_calendar_cache (id INTEGER PRIMARY KEY, ticker TEXT, "
        "ex_date TEXT, amount REAL, fetched_at TEXT)"
    )
    if capital is not None:
        con.execute("CREATE TABLE paper_accounts (id INTEGER PRIMARY KEY, name TEXT, initial_capital REAL)")
        con.execute(
            "INSERT INTO paper_accounts (id, name, initial_capital) VALUES (2,'Sintetica',?)",
            (capital,),
        )
    for ticker, side, shares, dia in fills:
        con.execute(
            "INSERT INTO paper_orders (account_id, ticker, side, fill_shares, status, filled_at) "
            "VALUES (2,?,?,?,'filled',?)",
            (ticker, side, shares, f"{dia} 21:08:46"),
        )
        # Centinela: "chequeado, no paga". Mantiene los dividendos fuera del camino para
        # que lo único que mueva el número sea el ancla, que es lo que se mide acá.
        con.execute(
            "INSERT INTO dividend_calendar_cache (ticker, ex_date, amount) VALUES (?,?,0.0)",
            (ticker, mp._SIN_DIVIDENDOS),
        )
    for dia, eq in equity:
        con.execute(
            "INSERT INTO paper_equity_snapshots (account_id, snapshot_at, total_equity) VALUES (2,?,?)",
            (f"{dia} 21:08:46", eq),
        )
    return con


@pytest.fixture
def spy_plano(monkeypatch):
    """SPY que no se mueve en toda la ventana: cualquier ``vs_spy`` ≠ 0 es de la cuenta."""
    serie = [(_RUEDA_1, 100.0), (_FIN, 100.0)]
    monkeypatch.setattr(mp, "load_close_series", lambda con, t: list(serie))
    return serie


@pytest.fixture
def spy_con_finde(monkeypatch):
    """La forma real del arranque de la cuenta 2: jueves, hueco de 3 días, lunes.

    Los valores son los closes de SPY de esas fechas en el cache vivo (2026-09-23).
    Importa que **baje** de jueves a lunes: así el ancla vieja le daba a SPY una base más
    barata, o sea un retorno más alto, y el ``vs_spy`` salía más negativo de lo real.
    """
    serie = [(_RUEDA_0, 744.8902587890625), (_RUEDA_1, 742.546142578125), (_FIN, 744.9202270507812)]
    monkeypatch.setattr(mp, "load_close_series", lambda con, t: list(serie))
    return serie


# ── C1: la fricción de entrada es pérdida contra el índice, y tiene que verse ──


def test_una_cuenta_que_SOLO_compra_SPY_pierde_exactamente_su_costo_de_entrada(spy_plano):
    """El caso del kill-criteria. ``vs_spy`` = −(costo de entrada / capital), no 0.

    La cuenta pone $50.000, compra SPY pagando $25 entre comisión y slippage, y el índice
    no se mueve. Con el ancla vieja el panel decía **0,00pp** —empate— porque arrancaba a
    contar recién después de pagar. Lo que hizo de verdad fue perderle al índice por
    exactamente lo que le costó entrar.
    """
    costo = 25.0
    con = _con(
        # Equity post-fill: el capital menos la fricción. Es lo que estampa el snapshot.
        equity=[(_RUEDA_1, _CAPITAL - costo), (_FIN, _CAPITAL - costo)],
        fills=[("SPY", "BUY", (_CAPITAL - costo) / 100.0, _RUEDA_1)],
    )
    b = mp._benchmark_panel(con, 2)

    assert b["available"] is True
    assert b["base_anclaje"] == "initial_capital"
    assert b["base_equity"] == pytest.approx(_CAPITAL)
    assert b["spy_return"] == pytest.approx(0.0)
    assert b["vs_spy"] == pytest.approx(-costo / _CAPITAL)  # −0,05pp
    # La mutación que esto caza: volver a anclar en `rows[0]` da exactamente 0.
    assert b["vs_spy"] < -1e-9, "si esto da 0 se volvió a anclar en el primer snapshot"


def test_el_sesgo_NO_depende_de_cuanto_fue_el_costo_sino_de_que_exista(spy_plano):
    """Duplicar la fricción duplica la pérdida contra el índice. Es proporcional y lineal.

    Vale la pena fijarlo aparte: el caso de arriba podría pasar con una constante mal
    puesta que casualmente valga 25. Acá la propiedad es la relación, no el número.
    """

    def vs(costo: float) -> float:
        con = _con(
            equity=[(_RUEDA_1, _CAPITAL - costo), (_FIN, _CAPITAL - costo)],
            fills=[("SPY", "BUY", (_CAPITAL - costo) / 100.0, _RUEDA_1)],
        )
        return mp._benchmark_panel(con, 2)["vs_spy"]

    assert vs(50.0) == pytest.approx(2 * vs(25.0))
    assert vs(25.0) == pytest.approx(-25.0 / _CAPITAL)


# ── C2: la otra dirección — sin costos, el número no se mueve ─────────────────


def test_con_costos_en_CERO_el_numero_es_el_MISMO_que_antes(spy_plano):
    """El arreglo no corre el número: sólo deja de tapar la fricción.

    Sin costos el primer snapshot **es** el capital, así que las dos anclas coinciden y
    ``vs_spy`` da 0 igual que antes. Si esto se pusiera rojo, el arreglo estaría metiendo
    un sesgo nuevo en vez de sacar uno.
    """
    con = _con(
        equity=[(_RUEDA_1, _CAPITAL), (_FIN, _CAPITAL)],
        fills=[("SPY", "BUY", _CAPITAL / 100.0, _RUEDA_1)],
    )
    b = mp._benchmark_panel(con, 2)

    assert b["base_equity"] == pytest.approx(_CAPITAL)
    assert b["vs_spy"] == pytest.approx(0.0, abs=1e-12)


# ── C4 (enmienda): el ancla de SPY, que es la grande ──────────────────────────


def test_un_primer_snapshot_de_SABADO_se_ancla_en_el_close_QUE_TIENE_PUESTO(spy_con_finde):
    """El caso real de la cuenta 2, y el que el enunciado subestimaba 7×.

    El scan del sábado marca la equity con los últimos closes disponibles —los del jueves
    18, porque el viernes 19 fue feriado— y el panel anclaba SPY en el lunes 22. Son dos
    fechas distintas para el mismo instante: la cuenta se quedaba con el movimiento del
    fin de semana y SPY no.
    """
    con = _con(equity=[(_SABADO, _CAPITAL), (_FIN, _CAPITAL)])
    b = mp._benchmark_panel(con, 2)

    assert b["start_day"] == _SABADO
    assert b["spy_anclaje"] == "close_previo"
    assert b["spy_return"] == pytest.approx(744.9202270507812 / 744.8902587890625 - 1.0)

    # La mutación que esto caza, con su tamaño: anclar en la rueda siguiente le da a SPY
    # una base 0,31% más barata, o sea ~+0,32pp de retorno regalado contra la cuenta.
    viejo = 744.9202270507812 / 742.546142578125 - 1.0
    assert viejo - b["spy_return"] > 0.003, "si esto se acerca a 0 se volvió al ancla vieja"


def test_arrancando_EN_una_rueda_las_dos_anclas_dan_LO_MISMO(spy_con_finde):
    """La otra dirección: el cambio es angosto y sólo muerde fuera de una rueda.

    Con ``start_day`` en un día de mercado, ``_close_on_or_before`` y
    ``_close_on_or_after`` son el mismo close. Esto es lo que hace que el arreglo no
    reescriba ninguna ventana que arranque normal — y lo que explica por qué el defecto
    pudo vivir sin que nadie lo notara.
    """
    con = _con(equity=[(_RUEDA_1, _CAPITAL), (_FIN, _CAPITAL)])
    b = mp._benchmark_panel(con, 2)

    assert b["spy_anclaje"] == "close_previo"
    assert b["spy_return"] == pytest.approx(744.9202270507812 / 742.546142578125 - 1.0)
    assert mp._close_on_or_before(spy_con_finde, _RUEDA_1) == mp._close_on_or_after(spy_con_finde, _RUEDA_1)


def test_las_DOS_asimetrias_son_independientes_y_van_para_LADOS_DISTINTOS(spy_con_finde):
    """El caso que justifica arreglar las dos, y no la que decía el enunciado.

    Sobre la misma ventana: la fricción corre el número hacia abajo (la cuenta pierde lo
    que le costó entrar) y el ancla de fecha lo corre hacia arriba (SPY deja de cobrar un
    fin de semana que no le tocaba). Si alguien arregla una sola, la otra queda viva — y
    con el signo contrario, o sea tapándose entre ellas.
    """
    costo = 23.011825  # el de la cuenta 2, al centavo
    eq = [(_SABADO, _CAPITAL - costo), (_FIN, _CAPITAL - costo)]

    completo = mp._benchmark_panel(_con(equity=eq), 2)
    sin_capital = mp._benchmark_panel(_con(equity=eq, capital=None), 2)

    # Sin el ancla de capital, la cuenta no paga su entrada → el número sale MAYOR.
    assert sin_capital["base_anclaje"] == "primer_snapshot"
    assert sin_capital["vs_spy"] - completo["vs_spy"] == pytest.approx(costo / _CAPITAL, rel=1e-3)

    # Y el ancla de fecha mueve ~7× eso, para el otro lado.
    ancla_vieja = 744.9202270507812 / 742.546142578125 - 1.0
    delta_fecha = ancla_vieja - completo["spy_return"]
    assert delta_fecha > 6 * (costo / _CAPITAL)


# ── El camino degradado se declara, no se esconde ────────────────────────────


def test_sin_paper_accounts_cae_en_el_primer_snapshot_y_LO_DICE(spy_plano):
    """DB sintética sin la tabla: el comportamiento viejo, pero rotulado.

    Devolverlo en silencio sería dejar el sesgo vivo sin que nada lo diga, que es
    exactamente la forma del defecto que esta tarea arregla.
    """
    con = _con(equity=[(_RUEDA_1, 49_975.0), (_FIN, 49_975.0)], capital=None)
    b = mp._benchmark_panel(con, 2)

    assert b["base_anclaje"] == "primer_snapshot"
    assert b["base_equity"] == pytest.approx(49_975.0)
    assert b["vs_spy"] == pytest.approx(0.0, abs=1e-12)


def test_una_serie_que_EMPIEZA_DESPUES_de_la_cuenta_cae_en_la_primera_rueda_y_LO_DICE(
    monkeypatch,
):
    """El fallback, que **no** es una equivalencia: es el desvío de la tarea 225.

    Si el cache rodante ya no cubre el arranque de la cuenta, ``_close_on_or_before``
    devuelve ``None`` y hay que usar la primera rueda disponible — pero entonces SPY mide
    una ventana **más corta** que la cuenta, que es el espejo del ``stale`` de la tarea 22
    y hoy no lo guarda nadie. Por eso sale rotulado.
    """
    monkeypatch.setattr(mp, "load_close_series", lambda con, t: [(_RUEDA_1, 100.0), (_FIN, 110.0)])
    con = _con(equity=[("2026-01-05", _CAPITAL), (_FIN, _CAPITAL)])
    b = mp._benchmark_panel(con, 2)

    assert b["spy_anclaje"] == "primera_rueda"
    assert b["spy_return"] == pytest.approx(0.10)


def test_el_caso_sin_serie_tambien_declara_su_ancla_de_base(monkeypatch):
    """Los caminos de salida temprana no pierden la declaración.

    ``sin_serie`` y ``stale`` devuelven el retorno propio de la cuenta, así que tienen que
    decir contra qué base lo calcularon — si no, el único número que sobrevive al caso
    degradado queda sin historia.
    """
    monkeypatch.setattr(mp, "load_close_series", lambda con, t: None)
    con = _con(equity=[(_RUEDA_1, 49_975.0), (_FIN, 50_975.0)])
    b = mp._benchmark_panel(con, 2)

    assert b["available"] is False and b["motivo"] == "sin_serie"
    assert b["base_anclaje"] == "initial_capital"
    assert b["account_return"] == pytest.approx(50_975.0 / _CAPITAL - 1.0)


# ── C5: la tarjeta y la curva de equity anclan IGUAL ──────────────────────────

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@dataclass
class _Snap:
    snapshot_at: datetime
    total_equity: float


def test_la_curva_de_equity_ancla_IGUAL_que_la_tarjeta():
    """Mismo número dibujado en dos lugares: si anclan distinto, uno de los dos miente.

    ``build_benchmark_overlay`` tenía las dos asimetrías copiadas. Que el gráfico y la
    tarjeta discrepen es peor que cualquiera de las dos por separado, porque el lector no
    tiene forma de saber cuál está leyendo.
    """
    pytest.importorskip("PyQt6.QtWidgets")
    pytest.importorskip("matplotlib")
    from ui.paper.equity_chart import build_benchmark_overlay

    costo = 23.011825
    snaps = [
        _Snap(datetime(2026, 6, 20, 21, 8), _CAPITAL - costo),
        _Snap(datetime(2026, 6, 30, 21, 8), _CAPITAL - costo),
    ]
    spy = [(_RUEDA_0, 744.8902587890625), (_RUEDA_1, 742.546142578125), (_FIN, 744.9202270507812)]

    out = build_benchmark_overlay(snaps, spy, _CAPITAL)

    # La base es el close del jueves (el que tiene puesto la equity), no el del lunes, y
    # la escala sale del CAPITAL, no del snapshot post-fricción.
    escala = _CAPITAL / 744.8902587890625
    assert out[-1][0] == datetime.fromisoformat(_FIN)
    assert out[-1][1] == pytest.approx(744.9202270507812 * escala)
    # Y el hueco del arranque ES el costo de entrada: SPY parte del capital y la equity
    # de la cuenta arranca $23 más abajo. Verlo es el punto.
    assert _CAPITAL - snaps[0].total_equity == pytest.approx(costo)


def test_el_overlay_SIN_capital_mantiene_el_comportamiento_viejo():
    """Los llamadores que no tengan el capital a mano no se rompen."""
    pytest.importorskip("PyQt6.QtWidgets")
    pytest.importorskip("matplotlib")
    from ui.paper.equity_chart import build_benchmark_overlay

    snaps = [
        _Snap(datetime(2026, 6, 22, 21, 8), 49_975.0),
        _Snap(datetime(2026, 6, 30, 21, 8), 49_975.0),
    ]
    spy = [(_RUEDA_1, 100.0), (_FIN, 100.0)]

    assert build_benchmark_overlay(snaps, spy)[0][1] == pytest.approx(49_975.0)
