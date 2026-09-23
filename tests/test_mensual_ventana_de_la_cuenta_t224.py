"""Tarea 224 — el ``vs_spy`` mensual mide a SPY sobre la ventana de la CUENTA.

El defecto
----------
``scripts/dashboard_data._monthly_perf`` armaba el alpha mensual restándole a
``period_return`` —primer→último *endpoint diario de la cuenta* dentro del mes— un
``spy_return`` sacado de ``[(d, c) for d, c in spy if d[:7] == mo]``, o sea **todas**
las ruedas del **mes calendario**. Dos ventanas distintas para la misma resta.

Es el mismo mecanismo que la tarea **22** declaró para el otro lado, y está escrito en
el docstring de ``metrics_panel`` desde entonces: *«comparar la ventana completa contra
un SPY recortado sesga el vs_spy en silencio»*. Acá es al revés —SPY completo contra
una cuenta recortada— y nadie lo guardaba: la tarjeta tiene ``stale``, el dashboard no
tenía nada.

Lo que el enunciado subestimaba, y por qué
-------------------------------------------
El enunciado decía *«+1,62pp en el primer mes»*, como si mordiera sólo donde la cuenta
arranca a mitad. **Muerde en los cuatro**, porque la cuenta 2 tiene huecos reales de
snapshots — no hubo scans entre el **2026-07-24 y el 2026-08-09**, así que julio
termina el 24 y agosto empieza el 9. Medido el 2026-09-23:

=======  ==========  ==========  =========
mes      vs publica  vs alineado  Δ
=======  ==========  ==========  =========
2026-06    +2,407pp    +1,113pp   −1,294
2026-07    +3,213pp    +4,300pp   +1,086
2026-08    −1,553pp    **+0,600pp**  +2,153
2026-09    −2,118pp    −1,731pp   +0,387
=======  ==========  ==========  =========

**Agosto cambia de signo**: el artefacto publicaba que el sistema le perdió 1,55pp al
mercado cuando alineado le **ganó** 0,60pp. Esa serie es la que lee el panel de alpha
decay.

Y además estaba visto hace dos meses, mal dimensionado: el cierre de la **22**
(2026-07-22) lo anotó como *«fuera de alcance: sesgo acotado al mes en curso, framing
distinto»*. No está acotado al mes en curso — el mes en curso es justamente el único
que **no** es parcial.

La causa raíz, que es lo que este archivo fija
-----------------------------------------------
Había **dos implementaciones del mismo número**, y por eso la 22, la 221 y la 223
arreglaron una y dejaron la otra intacta. Es el desenlace que el propio repo ya tenía
anotado un nivel más abajo, en ``dashboard_data._load_close_series``: *«tener dos
copias es lo que permitió que arreglar una no alcanzara a la otra»*. Ahora la
aritmética vive en ``metrics_panel.retorno_de_spy`` y el test de abajo
—``test_la_fila_mensual_y_la_TARJETA_dan_el_mismo_numero``— las ata: sobre una cuenta
de un solo mes tienen que dar exactamente lo mismo. Ése es el que impide que vuelvan a
separarse.

Lo que de acá quedó superado, y va dicho
-----------------------------------------
El kill-criteria de esta tarea pedía que *«en un mes completo el número no cambie»*, y la
**230** lo cambió a propósito: los meses ahora arrancan en el cierre del mes anterior,
que es la única convención con la que la tabla y la tarjeta encadenan. Aquel criterio
existía para que un arreglo de **ventana** no se llevara puesta la convención, no para
congelarla — y el cambio de convención se hizo aparte, con su propio criterio. Los tests
de acá que tocaban esa cláusula se reescribieron señalando qué propiedad siguen fijando.
"""

from __future__ import annotations

import sqlite3

import pytest

import analysis.metrics_panel as mp
from scripts.baseline_metrics import load_fills, load_snapshots
from scripts.dashboard_data import _monthly_perf

_CAPITAL = 50_000.0


def _con(
    *,
    equity: list[tuple[str, float]],
    capital: float | None = _CAPITAL,
    fills: list[tuple[str, str, float, str]] = (),
) -> sqlite3.Connection:
    """DB en memoria con lo mínimo que miran ``_monthly_perf`` y ``_benchmark_panel``."""
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
        con.execute(
            "INSERT INTO dividend_calendar_cache (ticker, ex_date, amount) VALUES (?,?,0.0)",
            (ticker, mp._SIN_DIVIDENDOS),
        )
    for dia, eq in equity:
        con.execute(
            "INSERT INTO paper_equity_snapshots (account_id, snapshot_at, total_equity, cash, positions_value) "
            "VALUES (2,?,?,0.0,?)",
            (f"{dia} 21:00:00", eq, eq),
        )
    return con


def _mensual(con, spy, monkeypatch):
    """Corre ``_monthly_perf`` con una serie de SPY inyectada."""
    monkeypatch.setattr("data.historical_series.close_series", lambda c, t: list(spy))
    return _monthly_perf(con, load_snapshots(con, 2), load_fills(con, 2), 2)


# ── C1: el mes en el que la cuenta arranca a mitad ───────────────────────────


def test_un_mes_donde_la_cuenta_ARRANCA_A_MITAD_no_cobra_el_rally_que_no_vivio(monkeypatch):
    """El caso del kill-criteria, construido para que la diferencia sea inconfundible.

    SPY sube **+10%** en la primera mitad del mes y queda **plano** en la segunda. La
    cuenta abre recién a mitad de mes y no se mueve. Con la ventana del mes calendario
    el panel publicaba *«la cuenta le perdió 10pp al mercado»*; sobre la ventana que la
    cuenta realmente vivió, el alpha es **0**.
    """
    spy = [
        ("2026-03-02", 100.0),
        ("2026-03-09", 105.0),
        ("2026-03-16", 110.0),  # la cuenta abre acá
        ("2026-03-23", 110.0),
        ("2026-03-30", 110.0),
    ]
    con = _con(equity=[("2026-03-16", _CAPITAL), ("2026-03-30", _CAPITAL)])
    fila = _mensual(con, spy, monkeypatch)[0]

    assert fila["spy_return"] == pytest.approx(0.0)
    assert fila["vs_spy"] == pytest.approx(0.0)
    # La mutación que esto caza: con `d[:7] == mo` SPY da +10% y el alpha −10pp.
    assert fila["vs_spy"] > -0.05, "si esto da ~−0,10 se volvió a la ventana del mes calendario"


def test_un_mes_que_TERMINA_ANTES_tampoco_cobra_lo_que_paso_despues(monkeypatch):
    """La otra mitad del mismo defecto, y la que el enunciado no tenía.

    No hace falta que la cuenta arranque tarde: alcanza con que **deje de haber
    scans**. Es lo que le pasa a julio de la cuenta 2, que termina el 24 porque no hubo
    ningún scan hasta el 9 de agosto. SPY plano mientras la cuenta opera, y un salto
    después de que dejó de haber datos.
    """
    spy = [
        ("2026-03-02", 100.0),
        ("2026-03-09", 100.0),
        ("2026-03-16", 100.0),  # último día con snapshot
        ("2026-03-23", 120.0),  # el salto que la cuenta no vivió
        ("2026-03-30", 120.0),
    ]
    con = _con(equity=[("2026-03-02", _CAPITAL), ("2026-03-16", _CAPITAL)])
    fila = _mensual(con, spy, monkeypatch)[0]

    assert fila["spy_return"] == pytest.approx(0.0)
    assert fila["vs_spy"] == pytest.approx(0.0)


# ── C2: la otra dirección — un mes completo no se mueve ──────────────────────


def test_en_un_mes_COMPLETO_el_numero_no_cambia(monkeypatch):
    """Si la ventana de la cuenta ya es la del mes, las dos formas coinciden.

    Es lo que hace que el arreglo no reescriba ningún mes que esté bien, y lo que
    explica por qué el defecto pudo vivir dos meses sin que nadie lo notara.
    """
    spy = [("2026-03-02", 100.0), ("2026-03-16", 105.0), ("2026-03-30", 110.0)]
    con = _con(equity=[("2026-03-02", _CAPITAL), ("2026-03-30", _CAPITAL * 1.10)])
    fila = _mensual(con, spy, monkeypatch)[0]

    de_mes_calendario = 110.0 / 100.0 - 1.0
    assert fila["spy_return"] == pytest.approx(de_mes_calendario)
    assert fila["vs_spy"] == pytest.approx(0.0)
    assert fila["mes_parcial"] is False


def test_la_base_del_mes_sale_del_ULTIMO_snapshot_del_dia_ancla(monkeypatch):
    """``daily_endpoints`` se queda con el **último** snapshot de cada día, y eso se fija.

    **La convención de qué día ancla cambió en la tarea 230** —ahora el mes arranca en el
    cierre del mes anterior, no en su propio primer endpoint—, así que este test se
    reescribió. Lo que sigue valiendo, y es por lo que existe, es la otra mitad: la
    equity del día ancla es la del **último** snapshot de esa fecha. Con dos scans el
    mismo día, tomar el primero daría un número completamente distinto y en silencio.

    Y la dirección que acota el cambio: el **primer** mes no tiene mes anterior, así que
    ancla en el capital (tarea 223) y la 230 no lo toca.
    """
    spy = [("2026-03-02", 100.0), ("2026-03-30", 100.0), ("2026-04-01", 100.0), ("2026-04-30", 100.0)]
    con = _con(
        equity=[
            ("2026-03-02", _CAPITAL),
            ("2026-03-30", 51_000.0),
            ("2026-04-01", 52_000.0),
            ("2026-04-30", 53_000.0),
        ]
    )
    con.execute(
        "INSERT INTO paper_equity_snapshots (account_id, snapshot_at, total_equity, cash, positions_value) "
        "VALUES (2,'2026-03-30 09:00:00', 99999.0, 0.0, 99999.0)"  # MISMO día ancla, más temprano
    )
    filas = {f["month"]: f for f in _mensual(con, spy, monkeypatch)}

    # Abril ancla en el cierre de marzo = el ÚLTIMO snapshot del 30/03 (51.000), no 99.999.
    assert filas["2026-04"]["ancla_day"] == "2026-03-30"
    assert filas["2026-04"]["period_return"] == pytest.approx(53_000.0 / 51_000.0 - 1.0)
    # Y marzo, que es el primero, sigue anclando en el capital (tarea 223).
    assert filas["2026-03"]["ancla_day"] is None
    assert filas["2026-03"]["period_return"] == pytest.approx(51_000.0 / _CAPITAL - 1.0)


# ── C4: el que ata las dos aritméticas, y es el punto del archivo ─────────────


def test_la_fila_mensual_y_la_TARJETA_dan_el_mismo_numero(monkeypatch):
    """Una cuenta de UN mes: ``_monthly_perf`` y ``_benchmark_panel`` tienen que coincidir.

    Es el test que impide que el defecto vuelva. No compara contra una constante sino
    **una implementación contra la otra**, así que cualquier arreglo que se le haga a
    una y no a la otra lo pone en rojo — que es exactamente lo que pasó con la 22, la
    221 y la 223.
    """
    spy = [("2026-03-02", 100.0), ("2026-03-16", 103.0), ("2026-03-30", 106.0)]
    monkeypatch.setattr(mp, "load_close_series", lambda c, t: list(spy))
    con = _con(
        equity=[("2026-03-02", 49_950.0), ("2026-03-30", 52_000.0)],
        fills=[("MO", "BUY", 100.0, "2026-03-02")],
    )

    fila = _mensual(con, spy, monkeypatch)[0]
    tarjeta = mp._benchmark_panel(con, 2)

    assert tarjeta["available"] is True
    assert fila["spy_return"] == pytest.approx(tarjeta["spy_return"])
    assert fila["account_return_total"] == pytest.approx(tarjeta["account_return_total"])
    assert fila["vs_spy"] == pytest.approx(tarjeta["vs_spy"])


def test_el_mensual_suma_los_DIVIDENDOS_devengados(monkeypatch):
    """La 221 llegaba a la tarjeta y no acá: restaba precio contra total-return.

    Sobre la cuenta 2 eso vale +0,055pp (jun), 0 (jul), +0,112pp (ago) y +0,387pp
    (sep) — chico, pero siempre en la misma dirección y acumulándose.
    """
    spy = [("2026-03-02", 100.0), ("2026-03-30", 100.0)]
    monkeypatch.setattr(mp, "load_close_series", lambda c, t: list(spy))
    con = _con(
        equity=[("2026-03-02", _CAPITAL), ("2026-03-30", _CAPITAL)],
        fills=[("MO", "BUY", 100.0, "2026-03-02")],
    )
    con.execute("DELETE FROM dividend_calendar_cache")
    con.execute(
        "INSERT INTO dividend_calendar_cache (ticker, ex_date, amount) VALUES ('MO','2026-03-16',5.0)"
    )

    fila = _mensual(con, spy, monkeypatch)[0]

    assert fila["account_dividends"] == pytest.approx(500.0)
    assert fila["dividendos_completos"] is True
    assert fila["period_return"] == pytest.approx(0.0)
    assert fila["account_return_total"] == pytest.approx(500.0 / _CAPITAL)
    assert fila["vs_spy"] == pytest.approx(500.0 / _CAPITAL)


# ── C5: la cobertura se declara, y distingue dos cosas distintas ─────────────


def test_un_scan_salteado_NO_es_lo_mismo_que_un_tramo_sin_cubrir(monkeypatch):
    """``mes_parcial`` separa las dos, y no necesita ningún umbral calibrado.

    Un flag que mezclara las dos daba ``False`` en los cuatro meses de la cuenta 2, o
    sea que no distinguía nada. La diferencia que importa es si la **ventana** cubre el
    mes (comparable con los otros meses) o no; que adentro de la ventana falte un scan
    suelto se declara aparte, en ``ruedas_cubiertas``.
    """
    spy = [
        ("2026-03-02", 100.0),
        ("2026-03-09", 100.0),
        ("2026-03-16", 100.0),
        ("2026-03-23", 100.0),
        ("2026-03-30", 100.0),
    ]
    # La ventana cubre el mes entero pero le falta un scan en el medio (el 16).
    con = _con(
        equity=[
            ("2026-03-02", _CAPITAL),
            ("2026-03-09", _CAPITAL),
            ("2026-03-23", _CAPITAL),
            ("2026-03-30", _CAPITAL),
        ]
    )
    fila = _mensual(con, spy, monkeypatch)[0]

    assert fila["ruedas_mes"] == 5
    assert fila["ruedas_ventana"] == 5
    assert fila["ruedas_cubiertas"] == 4, "el 16 no tiene snapshot"
    assert fila["mes_parcial"] is False, "la ventana SÍ cubre el mes: es comparable"


def test_un_mes_cuya_VENTANA_no_cubre_el_mes_se_declara_parcial(monkeypatch):
    """El caso de agosto de la cuenta 2: arranca el 9 porque no hubo scans antes."""
    spy = [("2026-03-02", 100.0), ("2026-03-09", 100.0), ("2026-03-16", 100.0), ("2026-03-30", 100.0)]
    con = _con(equity=[("2026-03-16", _CAPITAL), ("2026-03-30", _CAPITAL)])
    fila = _mensual(con, spy, monkeypatch)[0]

    assert fila["ruedas_mes"] == 4
    assert fila["ruedas_ventana"] == 2
    assert fila["mes_parcial"] is True


def test_la_ventana_del_mes_sale_declarada_en_monthly_breakdown(monkeypatch):
    """``start_day``/``end_day`` son lo que permite alinear cualquier cosa contra la fila.

    Sin ellos, un consumidor no tiene con qué recortar su propia serie — que es
    exactamente por qué ``_monthly_perf`` terminó usando el mes calendario.
    """
    spy = [("2026-03-02", 100.0), ("2026-03-30", 100.0)]
    con = _con(equity=[("2026-03-09", _CAPITAL), ("2026-03-23", _CAPITAL)])
    fila = _mensual(con, spy, monkeypatch)[0]

    assert fila["start_day"] == "2026-03-09"
    assert fila["end_day"] == "2026-03-23"


# ── Las DOS puntas del helper compartido ─────────────────────────────────────


def test_las_dos_puntas_de_retorno_de_spy_usan_la_MISMA_regla():
    """Inicio **y** final anclan con ``_close_on_or_before``, y eso hay que fijarlo.

    Apareció probando por mutación: cambiar la punta del **final** a
    ``_close_on_or_after`` dejaba los once tests de este archivo en **verde**, porque
    todas las ventanas sintéticas terminaban en un día de rueda y las dos formas dan lo
    mismo. Es el mismo falso negativo que la 221 encontró con la fila centinela —un
    caso de prueba que no puede distinguir lo que dice fijar—, así que acá las dos
    fechas caen **fuera** de rueda: un sábado al inicio y un domingo al final.

    Si el final anclara *on-or-after*, SPY se llevaría el lunes siguiente — una rueda
    que la cuenta no vivió, y con el signo siempre a favor o en contra según el mercado,
    no según la cuenta.
    """
    serie = [
        ("2026-03-06", 100.0),  # viernes
        ("2026-03-09", 101.0),  # lunes
        ("2026-03-13", 110.0),  # viernes
        ("2026-03-16", 999.0),  # lunes siguiente: NO debe entrar por ninguna punta
    ]
    # Ventana sábado → domingo: ninguna de las dos fechas es rueda.
    r, anclaje = mp.retorno_de_spy(serie, "2026-03-07", "2026-03-15")

    assert anclaje == "close_previo"
    assert r == pytest.approx(110.0 / 100.0 - 1.0), "alguna punta se corrió de rueda"


def test_retorno_de_spy_degrada_sin_serie_ni_fechas():
    assert mp.retorno_de_spy(None, "2026-03-02", "2026-03-30") == (None, None)
    assert mp.retorno_de_spy([("2026-03-02", 100.0)], None, "2026-03-30") == (None, None)


# ── El camino degradado ──────────────────────────────────────────────────────


def test_sin_serie_de_SPY_la_fila_sale_sin_numero_y_no_revienta(monkeypatch):
    con = _con(equity=[("2026-03-02", _CAPITAL), ("2026-03-30", _CAPITAL)])
    monkeypatch.setattr("data.historical_series.close_series", lambda c, t: None)
    fila = _monthly_perf(con, load_snapshots(con, 2), load_fills(con, 2), 2)[0]

    assert fila["spy_return"] is None
    assert fila["vs_spy"] is None
    assert fila["ruedas_ventana"] == 0


def test_sin_account_id_no_hay_dividendos_ni_ancla_de_capital_pero_sigue(monkeypatch):
    """El llamador viejo (sin ``account_id``) no se rompe: degrada a lo de antes."""
    spy = [("2026-03-02", 100.0), ("2026-03-30", 100.0)]
    monkeypatch.setattr("data.historical_series.close_series", lambda c, t: list(spy))
    con = _con(equity=[("2026-03-02", 49_950.0), ("2026-03-30", 49_950.0)])

    fila = _monthly_perf(con, load_snapshots(con, 2), load_fills(con, 2))[0]

    assert fila["account_dividends"] == 0.0
    assert fila["period_return"] == pytest.approx(0.0)  # base = primer endpoint, no capital
    assert fila["vs_spy"] == pytest.approx(0.0)
