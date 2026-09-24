"""Tarea 225 — el guard del inicio, que era el espejo faltante del `stale`.

El defecto
----------
``_benchmark_panel`` tenía el guard de la tarea **22** para el **final** —si el último
close de SPY quedaba más de ``BENCHMARK_STALE_BDAYS`` días hábiles atrás del último
snapshot, marcaba ``stale`` y **no computaba el número**— y **nada** para el inicio. Si
la serie empieza *después* del primer snapshot, SPY mide una ventana más corta que la
cuenta por el otro extremo y el ``vs_spy`` sale sesgado exactamente igual de callado.

La **223** dejó ``spy_anclaje="primera_rueda"`` como marca observable de ese fallback, y
eso alcanzaba para verlo pero no para impedirlo: nadie lo leía, no apagaba nada y no
llegaba a la UI. **Declarar no es guardar.**

Por qué es latente y por qué no se queda latente
-------------------------------------------------
El cache es una ventana **rodante** que avanza ~1 rueda por día mientras el arranque de
la cuenta queda **fijo**, así que el colchón se achica monótonamente. Medido el
2026-09-24: la serie cubre desde el **2024-09-24**, la cuenta 2 arranca el 2026-06-20
(**453** días hábiles de colchón) y la cuenta 1 el 2026-04-24 (**413**). Ninguna lo toca
hoy; las dos lo van a tocar.

Las dos decisiones, con el argumento
-------------------------------------
**(1) Se apaga, no se publica.** El calendario de dividendos incompleto sí se publica,
como *piso*, porque el dividendo **sólo puede sumar** y entonces el número tiene una
dirección. Acá el tramo que falta pudo subir o bajar: un número sin dirección no es un
piso, es una adivinanza. Misma política que el ``stale``, del que esto es el espejo.

**(2) Reusa ``BENCHMARK_STALE_BDAYS`` y no un umbral propio.** Es la misma pregunta
espejada —cuánto de la ventana le falta a SPY antes de que la comparación deje de
valer— y **no hay población contra la cual calibrar un segundo umbral**: 0 de 2 cuentas
lo tocan. Inventar una constante sin datos que la respalden sería peor que reusar una ya
declarada, que es la lección de la 214.
"""

from __future__ import annotations

import sqlite3

import pytest

import analysis.metrics_panel as mp

_CAPITAL = 50_000.0


def _con(equity: list[tuple[str, float]]) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE paper_equity_snapshots (id INTEGER PRIMARY KEY, account_id INT, "
        "snapshot_at TEXT, total_equity REAL)"
    )
    con.execute("CREATE TABLE paper_accounts (id INTEGER PRIMARY KEY, name TEXT, initial_capital REAL)")
    con.execute(
        "INSERT INTO paper_accounts (id, name, initial_capital) VALUES (2,'Sintetica',?)", (_CAPITAL,)
    )
    for dia, eq in equity:
        con.execute(
            "INSERT INTO paper_equity_snapshots (account_id, snapshot_at, total_equity) VALUES (2,?,?)",
            (f"{dia} 21:00:00", eq),
        )
    return con


# ── El caso del kill-criteria ────────────────────────────────────────────────


def test_una_serie_que_arranca_MUY_DESPUES_apaga_el_numero(monkeypatch):
    """Lo que el defecto dejaba pasar: un `vs_spy` mudo sobre media ventana.

    La cuenta corre desde enero y la serie empieza en junio. SPY mide **5 meses** de una
    ventana de **9**, y antes el panel publicaba esa resta como si fueran la misma.
    """
    monkeypatch.setattr(
        mp, "load_close_series", lambda con, t: [("2026-06-01", 100.0), ("2026-09-30", 110.0)]
    )
    con = _con([("2026-01-05", _CAPITAL), ("2026-09-30", 55_000.0)])
    b = mp._benchmark_panel(con, 2)

    assert b["available"] is False
    assert b["vs_spy"] is None, "el número sesgado NO se computa"
    assert b["spy_return"] is None
    assert b["motivo"] == "serie_corta"
    assert b["spy_start_day"] == "2026-06-01", "se declara CON QUÉ ventana se quedó"
    # El retorno propio de la cuenta sí se reporta, igual que en el `stale`: lo que no
    # se puede afirmar es la COMPARACIÓN, no lo que hizo la cuenta.
    assert b["account_return"] == pytest.approx(55_000.0 / _CAPITAL - 1.0)


def test_el_umbral_es_el_MISMO_que_el_del_final_y_se_respeta_en_los_dos_bordes(monkeypatch):
    """Adentro de la tolerancia el número sale; pasándola, se apaga.

    Se prueban los dos lados del umbral y no uno solo: un guard verificado de un lado
    puede estar disparando siempre o nunca sin que el test lo note.
    """

    def panel(spy_desde: str):
        monkeypatch.setattr(
            mp, "load_close_series", lambda con, t: [(spy_desde, 100.0), ("2026-06-30", 110.0)]
        )
        return mp._benchmark_panel(_con([("2026-06-01", _CAPITAL), ("2026-06-30", _CAPITAL)]), 2)

    # 2026-06-01 es lunes. Tres días hábiles de hueco = el umbral exacto → pasa.
    assert mp.benchmark_start_gap_bdays("2026-06-04", "2026-06-01") == 3
    assert panel("2026-06-04")["available"] is True

    # Cuatro → se apaga.
    assert mp.benchmark_start_gap_bdays("2026-06-05", "2026-06-01") == 4
    assert panel("2026-06-05")["motivo"] == "serie_corta"


# ── La otra dirección ────────────────────────────────────────────────────────


def test_una_serie_que_CUBRE_el_arranque_no_cambia_nada(monkeypatch):
    """El guard no puede morder el caso normal, que es el de las dos cuentas vivas."""
    monkeypatch.setattr(
        mp,
        "load_close_series",
        lambda con, t: [("2024-09-24", 90.0), ("2026-06-01", 100.0), ("2026-06-30", 110.0)],
    )
    con = _con([("2026-06-01", _CAPITAL), ("2026-06-30", 55_000.0)])
    b = mp._benchmark_panel(con, 2)

    assert b["available"] is True
    assert b["motivo"] is None
    assert b["spy_anclaje"] == "close_previo"
    assert b["spy_return"] == pytest.approx(0.10)


def test_el_guard_del_FINAL_sigue_ganando_cuando_pasan_los_dos(monkeypatch):
    """Si la serie está corta por los dos lados, el motivo tiene que ser uno solo.

    El orden importa para el cartel que ve el usuario: ``stale`` va primero porque es el
    caso que se arregla **solo** —basta que corra el warm-up—, mientras que una serie que
    no llega al arranque no se recupera con un fetch.
    """
    monkeypatch.setattr(
        mp, "load_close_series", lambda con, t: [("2026-06-01", 100.0), ("2026-06-10", 110.0)]
    )
    con = _con([("2026-01-05", _CAPITAL), ("2026-09-30", _CAPITAL)])
    b = mp._benchmark_panel(con, 2)

    assert b["stale"] is True
    assert b["motivo"] == "stale"
    assert b["spy_start_day"] == "2026-06-01", "el stale también declara el inicio"


# ── El helper, que es el que puede decir lo contrario sin que se note ────────


def test_el_helper_del_inicio_NO_es_el_del_final_con_los_argumentos_dados_vuelta():
    """Los dos cuentan días hábiles; lo que cambia es qué significa el signo.

    Existen por separado para que el call site diga qué mide. Llamar a
    ``benchmark_stale_bdays`` con los argumentos invertidos da el número correcto y un
    lector que confíe en los nombres —``spy_last_day``, ``ref_day``— entiende lo
    contrario de lo que pasa.
    """
    # SPY empieza 5 días hábiles después que la cuenta.
    assert mp.benchmark_start_gap_bdays("2026-06-08", "2026-06-01") == 5
    # Y al revés: si la serie arranca ANTES, el hueco es negativo (no hay hueco).
    assert mp.benchmark_start_gap_bdays("2026-06-01", "2026-06-08") == -5
    # El del final, sobre las mismas fechas, dice lo simétrico.
    assert mp.benchmark_stale_bdays("2026-06-01", "2026-06-08") == 5


def test_el_helper_degrada_como_su_espejo():
    """Fechas ausentes o basura devuelven 0: no se apaga una tarjeta por un parseo."""
    assert mp.benchmark_start_gap_bdays(None, "2026-06-01") == 0
    assert mp.benchmark_start_gap_bdays("2026-06-01", None) == 0
    assert mp.benchmark_start_gap_bdays("basura", "2026-06-01") == 0


# ── El gráfico: el mismo caso, y el cartel que NO puede compartir ────────────


def test_el_overlay_tambien_lo_guarda_y_con_su_PROPIO_cartel():
    """El espejo en la curva de equity, que el alcance mandaba barrer.

    No es simetría decorativa: con la serie corta por el inicio, el overlay escala la
    línea para que SPY **valga el capital** en una fecha en la que la cuenta ya se había
    movido — el gráfico afirma un empate que no existió, y eso no se ve.

    Y el cartel no puede ser el del ``stale``: *«SPY desactualizado»* dice que el dato es
    **viejo**, y acá el problema es el contrario. Por eso el parámetro del chart pasó de
    un ``bool`` a un texto.
    """
    pytest.importorskip("PyQt6.QtWidgets")
    pytest.importorskip("matplotlib")
    import os
    from dataclasses import dataclass
    from datetime import datetime

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from ui.paper.equity_chart import overlay_empieza_tarde, overlay_is_stale

    @dataclass
    class _Snap:
        snapshot_at: datetime
        total_equity: float

    snaps = [_Snap(datetime(2026, 1, 5, 21), _CAPITAL), _Snap(datetime(2026, 9, 30, 21), _CAPITAL)]
    corta = [("2026-06-01", 100.0), ("2026-09-30", 110.0)]
    cubre = [("2025-01-02", 90.0), ("2026-01-05", 100.0), ("2026-09-30", 110.0)]

    assert overlay_empieza_tarde(snaps, corta) is True
    assert overlay_empieza_tarde(snaps, cubre) is False
    # Y son ejes distintos: la serie corta por el inicio NO está desactualizada.
    assert overlay_is_stale(snaps, corta) is False


def test_el_overlay_degrada_sin_datos():
    pytest.importorskip("PyQt6.QtWidgets")
    pytest.importorskip("matplotlib")
    from ui.paper.equity_chart import overlay_empieza_tarde

    assert overlay_empieza_tarde([], [("2026-01-01", 100.0)]) is False
    assert overlay_empieza_tarde([object()], None) is False
