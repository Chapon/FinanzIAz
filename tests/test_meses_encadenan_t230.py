"""Tarea 230 — la serie mensual encadena al total, y por eso cierra con la tarjeta.

El defecto
----------
El dashboard publicaba **dos alphas del mismo período que no cerraban**: multiplicando
los cuatro meses de la cuenta 2 daba **+4,29pp** y la tarjeta VS SPY **−0,78pp**. 5,07pp
de desacuerdo, con el signo opuesto, entre dos números del mismo panel.

No era un error de cuenta. Cada mes medía **primer→último endpoint suyo**, así que el
tramo entre el último día de un mes y el primero del siguiente **no entraba en ninguno**.
Con scans diarios eso es un fin de semana; con un hueco real —la cuenta 2 estuvo del
**24/07 al 09/08** sin scans— son 16 días. Y como desaparecían del leg de la cuenta y
del de SPY en proporciones distintas, no se cancelaban.

La decisión, y por qué ésta
----------------------------
De las tres salidas que dejó el enunciado —encadenar, declarar el hueco, atribuirlo al
mes donde se realizó— se eligió **encadenar**: mes N desde el cierre del mes N−1. Es la
única bajo la cual la tabla y la tarjeta *pueden* cerrar, y de paso resuelve la tercera
gratis (el hueco cae en el mes donde la equity efectivamente se movió). Es display-only,
así que la convención se elige con el argumento escrito (regla 3).

**Cambia todos los meses a propósito**, y eso contradice el kill-criteria de la **224**
—*«en un mes completo el número no cambia»*—. No es un descuido: aquel criterio existía
para que un arreglo de **ventana** no se llevara puesta la convención, y esta tarea es
justamente el cambio de convención, separado, con su propio criterio.

Las dos cosas que el enunciado no anticipaba
---------------------------------------------
1. **Mover sólo ``period_return`` dejaba la fila partida.** ``sharpe_annual`` y
   ``max_drawdown`` seguirían cubriendo los días de adentro del mes mientras el retorno
   cubre desde el cierre anterior. Eso lo introduciría el arreglo, así que el ancla entra
   como **semilla** en la serie de endpoints y las tres métricas cubren el mismo período.
2. **Los dividendos rompían el encadenamiento igual.** Sumar el devengado **del mes**
   sobre una base sin él hace que ``prod((E_m + D_m)/E_{m-1})`` no dé
   ``(E_N + ΣD)/E_0``. El dividendo es efectivo que la cuenta ya ganó y no cobró, así que
   queda en su valor y tiene que estar también en la **base** del mes siguiente. Se
   acumula desde el arranque. Es el mismo defecto una capa más adentro.

Medido sobre la cuenta 2 el 2026-09-23, el hueco pasa de **+5,067pp a 0,00000000pp**.
"""

from __future__ import annotations

import sqlite3

import pytest

import analysis.metrics_panel as mp
from scripts.baseline_metrics import load_fills, load_snapshots, monthly_breakdown
from scripts.dashboard_data import _monthly_perf

_CAPITAL = 50_000.0


def _con(
    *,
    equity: list[tuple[str, float]],
    capital: float | None = _CAPITAL,
    fills: list[tuple[str, str, float, str]] = (),
    dividendos: list[tuple[str, str, float]] = (),
) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE paper_orders (id INTEGER PRIMARY KEY, account_id INT, ticker TEXT, "
        "side TEXT, fill_shares REAL, fill_price REAL, commission_paid REAL, "
        "slippage_cost REAL, signal_score REAL, reason TEXT, status TEXT, filled_at TEXT)"
    )
    con.execute(
        "CREATE TABLE paper_equity_snapshots (id INTEGER PRIMARY KEY, account_id INT, "
        "snapshot_at TEXT, total_equity REAL, cash REAL, positions_value REAL)"
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
            "INSERT INTO paper_orders (account_id, ticker, side, fill_shares, fill_price, status, filled_at) "
            "VALUES (2,?,?,?,100.0,'filled',?)",
            (ticker, side, shares, f"{dia} 21:00:00"),
        )
    for ticker, ex, monto in dividendos or [(t, mp._SIN_DIVIDENDOS, 0.0) for t, *_ in fills]:
        con.execute(
            "INSERT INTO dividend_calendar_cache (ticker, ex_date, amount) VALUES (?,?,?)",
            (ticker, ex, monto),
        )
    for dia, eq in equity:
        con.execute(
            "INSERT INTO paper_equity_snapshots (account_id, snapshot_at, total_equity, cash, positions_value) "
            "VALUES (2,?,?,0.0,?)",
            (f"{dia} 21:00:00", eq, eq),
        )
    return con


def _corre(con, spy, monkeypatch):
    monkeypatch.setattr("data.historical_series.close_series", lambda c, t: list(spy))
    monkeypatch.setattr(mp, "load_close_series", lambda c, t: list(spy))
    return _monthly_perf(con, load_snapshots(con, 2), load_fills(con, 2), 2), mp._benchmark_panel(con, 2)


def _encadenado(filas, clave):
    acumulado = 1.0
    for f in filas:
        if f.get(clave) is not None:
            acumulado *= 1.0 + f[clave]
    return acumulado - 1.0


# ── C1: el invariante, que es el punto entero de la tarea ────────────────────


def test_los_meses_ENCADENAN_al_total_de_la_tarjeta(monkeypatch):
    """Multiplicar los meses tiene que dar **exactamente** lo que dice la tarjeta.

    No se compara contra una constante escrita a mano sino **una implementación contra
    la otra** sobre los mismos datos, que es lo que hace que el test sobreviva a un
    cambio de números. Los dos legs por separado, porque un alpha correcto por
    compensación de dos legs mal medidos seguiría siendo dos números que no cierran.
    """
    spy = [
        ("2026-03-02", 100.0),
        ("2026-03-31", 104.0),
        ("2026-04-01", 104.5),
        ("2026-04-30", 108.0),
        ("2026-05-01", 109.0),
        ("2026-05-29", 112.0),
    ]
    con = _con(
        equity=[
            ("2026-03-02", 49_980.0),
            ("2026-03-31", 51_000.0),
            ("2026-04-01", 51_100.0),
            ("2026-04-30", 52_500.0),
            ("2026-05-01", 52_400.0),
            ("2026-05-29", 53_000.0),
        ]
    )
    filas, tarjeta = _corre(con, spy, monkeypatch)

    assert len(filas) == 3
    assert _encadenado(filas, "account_return_total") == pytest.approx(
        tarjeta["account_return_total"], abs=1e-12
    )
    assert _encadenado(filas, "spy_return") == pytest.approx(tarjeta["spy_return"], abs=1e-12)
    alpha = _encadenado(filas, "account_return_total") - _encadenado(filas, "spy_return")
    assert alpha == pytest.approx(tarjeta["vs_spy"], abs=1e-12)


def test_el_invariante_SOBREVIVE_a_un_hueco_de_scans(monkeypatch):
    """El caso real: la cuenta 2 estuvo 16 días sin scans entre julio y agosto.

    Es el que hacía la diferencia grande —5,07pp— y el que distingue esta convención
    de la vieja: el tramo del hueco **no puede desaparecer**, tiene que caer en el mes
    donde la equity efectivamente se movió.
    """
    spy = [
        ("2026-03-02", 100.0),
        ("2026-03-20", 101.0),  # último día con snapshot de marzo
        ("2026-04-06", 115.0),  # el mercado se movió fuerte durante el hueco
        ("2026-04-30", 116.0),
    ]
    con = _con(
        equity=[
            ("2026-03-02", 50_000.0),
            ("2026-03-20", 50_500.0),
            ("2026-04-06", 48_000.0),  # y la cuenta también, sin que nadie lo registre
            ("2026-04-30", 49_000.0),
        ]
    )
    filas, tarjeta = _corre(con, spy, monkeypatch)

    assert filas[1]["ancla_day"] == "2026-03-20", "abril tiene que arrancar donde terminó marzo"
    # El tramo del hueco cae en abril, en los DOS legs.
    assert filas[1]["spy_return"] == pytest.approx(116.0 / 101.0 - 1.0)
    assert filas[1]["period_return"] == pytest.approx(49_000.0 / 50_500.0 - 1.0)
    assert _encadenado(filas, "account_return_total") == pytest.approx(
        tarjeta["account_return_total"], abs=1e-12
    )
    assert _encadenado(filas, "spy_return") == pytest.approx(tarjeta["spy_return"], abs=1e-12)


def test_los_DIVIDENDOS_se_acumulan_o_el_encadenamiento_se_rompe_igual(monkeypatch):
    """El defecto una capa más adentro, y el que no estaba en el enunciado.

    Con el dividendo del mes sumado sobre una base que no lo tiene,
    ``prod((E_m + D_m)/E_{m-1})`` **no** da ``(E_N + ΣD)/E_0``. El dividendo cae en el
    primer mes y tiene que seguir estando en la base del segundo.

    **La equity TIENE que moverse entre los dos meses, y ése es el punto del caso.** La
    primera versión de este test la dejaba plana (E0 = E1 = E2) y con eso las dos formas
    dan exactamente lo mismo: la mutación *«sumar el dividendo del mes sobre una base sin
    él»* salía **verde**. Se descubrió probando por mutación, y es la tercera vez en esta
    serie que un caso de prueba no puede distinguir lo que dice fijar (la fila centinela
    de la 221, la punta del final de la 224). Con E2 ≠ E1 el error es
    ``(E1+D)·E2/(E0·E1)`` contra ``(E2+D)/E0``, y se ve.
    """
    spy = [("2026-03-02", 100.0), ("2026-03-31", 100.0), ("2026-04-30", 100.0)]
    con = _con(
        equity=[
            ("2026-03-02", _CAPITAL),
            ("2026-03-31", _CAPITAL),
            ("2026-04-30", 60_000.0),  # abril se mueve: sin esto el caso es ciego
        ],
        fills=[("MO", "BUY", 100.0, "2026-03-02")],
        dividendos=[("MO", "2026-03-16", 5.0)],
    )
    filas, tarjeta = _corre(con, spy, monkeypatch)

    assert filas[0]["account_dividends"] == pytest.approx(500.0)
    assert filas[1]["account_dividends"] == pytest.approx(0.0), "abril no tiene ex-date propio"
    # Abril arranca con los $500 de marzo YA en su base: (60.000+500)/(50.000+500).
    assert filas[1]["account_return_total"] == pytest.approx(60_500.0 / 50_500.0 - 1.0)
    assert _encadenado(filas, "account_return_total") == pytest.approx(
        tarjeta["account_return_total"], abs=1e-12
    )
    # La firma del defecto que este caso existe para cazar: con el dividendo del mes
    # sobre una base sin él, abril daría 60.000/50.000 = +20,0% en vez de +19,80%.
    assert filas[1]["account_return_total"] < 0.199, "se sumó el dividendo del mes, no el acumulado"


# ── C2: la fila queda internamente consistente ───────────────────────────────


def test_el_retorno_el_sharpe_y_el_drawdown_cubren_EL_MISMO_periodo(monkeypatch):
    """La consecuencia que el arreglo introduciría si se hiciera a medias.

    Si el ancla entrara sólo en ``period_return``, la fila tendría el retorno midiendo
    desde el cierre anterior y el Sharpe/drawdown midiendo desde el primer día del mes.
    Acá la caída ocurre **en el salto** entre meses: si el drawdown no la ve, es porque
    la semilla no entró.
    """
    eps = [
        ("2026-03-02", 50_000.0),
        ("2026-03-31", 50_000.0),
        ("2026-04-01", 45_000.0),  # −10% justo en el salto de mes
        ("2026-04-30", 50_000.0),
    ]
    con = _con(equity=eps)
    filas = monthly_breakdown(load_snapshots(con, 2), [])
    abril = filas[1]

    assert abril["ancla_day"] == "2026-03-31"
    assert abril["period_return"] == pytest.approx(0.0), "50.000 → 50.000 desde el cierre de marzo"
    assert abril["max_drawdown"] == pytest.approx(0.10, abs=1e-9), "el drawdown del salto no se ve"
    assert abril["n_trading_days"] == 2, "la semilla no es un día del mes"


def test_el_PRIMER_mes_no_tiene_ancla_y_no_cambia(monkeypatch):
    """La otra dirección: una cuenta de un solo mes da exactamente lo de antes.

    El primer mes no tiene mes anterior, así que ancla en el capital (tarea 223) y esta
    convención no lo toca. Es lo que hace que el cambio sea acotado y auditable.
    """
    spy = [("2026-03-02", 100.0), ("2026-03-31", 105.0)]
    con = _con(equity=[("2026-03-02", 49_980.0), ("2026-03-31", 52_000.0)])
    filas, tarjeta = _corre(con, spy, monkeypatch)

    assert len(filas) == 1
    assert filas[0]["ancla_day"] is None
    assert filas[0]["period_return"] == pytest.approx(52_000.0 / _CAPITAL - 1.0)
    assert filas[0]["vs_spy"] == pytest.approx(tarjeta["vs_spy"], abs=1e-12)


def test_SPY_ancla_en_el_MISMO_punto_que_la_cuenta(monkeypatch):
    """Si SPY siguiera anclando en el primer día del mes, el desacuerdo se mudaría de lugar.

    La cuenta arranca abril en el cierre de marzo; SPY tiene que hacer lo mismo. Acá el
    mercado se mueve justo en el salto, así que las dos formas dan números distintos.
    """
    spy = [
        ("2026-03-02", 100.0),
        ("2026-03-31", 100.0),
        ("2026-04-01", 110.0),  # el salto: +10% entre el cierre de marzo y el 1 de abril
        ("2026-04-30", 110.0),
    ]
    con = _con(
        equity=[
            ("2026-03-02", _CAPITAL),
            ("2026-03-31", _CAPITAL),
            ("2026-04-01", _CAPITAL),
            ("2026-04-30", _CAPITAL),
        ]
    )
    filas, _ = _corre(con, spy, monkeypatch)

    assert filas[1]["spy_return"] == pytest.approx(0.10), "SPY no ancló en el cierre de marzo"
    # La mutación que esto caza: anclando en `start_day` (01/04) SPY daría 0,00.
    assert filas[1]["spy_return"] > 0.05


# ── Coverage: lo que la 224 dejó no se rompe ─────────────────────────────────


def test_la_cobertura_sigue_midiendose_sobre_la_ventana_DEL_MES(monkeypatch):
    """``start_day``/``end_day`` siguen siendo el mes, aunque el retorno arranque antes.

    Son dos preguntas distintas: desde dónde se **mide** (``ancla_day``) y qué tan lleno
    está el **mes** (``start_day`` → ``end_day``). Mezclarlas haría que `mes_parcial`
    mirara un tramo que incluye el mes anterior.
    """
    spy = [
        ("2026-04-01", 100.0),
        ("2026-04-08", 100.0),
        ("2026-04-15", 100.0),
        ("2026-04-22", 100.0),
        ("2026-04-29", 100.0),
    ]
    con = _con(
        equity=[
            ("2026-03-31", _CAPITAL),
            ("2026-04-15", _CAPITAL),
            ("2026-04-29", _CAPITAL),
        ]
    )
    filas, _ = _corre(con, spy, monkeypatch)
    abril = filas[1]

    assert abril["ancla_day"] == "2026-03-31"
    assert abril["start_day"] == "2026-04-15", "la cobertura no se corre al mes anterior"
    assert abril["ruedas_mes"] == 5
    assert abril["ruedas_ventana"] == 3, "15, 22 y 29 — las del mes anterior NO cuentan"
    assert abril["mes_parcial"] is True
