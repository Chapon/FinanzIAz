"""Tarea 246 — el VS SPY deja de tener fecha de vencimiento.

El panel leía SPY de ``latest_1d``, el frame **más fresco** —el ``2y`` que refresca el scan—,
que es una ventana rodante; el arranque de la cuenta es fijo. El guard de la 225 lo midió (453
días hábiles de colchón al 2026-09-24) y cerró sin tarea: hacia mediados de 2028 el VS SPY de la
cuenta 2 se apagaba para siempre. Lo encontró la auditoría del 2026-09-30 ([M-1]).

El cache ya tenía un ``10y`` de SPY que arranca en 2016; nadie lo leía, y nadie lo refrescaba
(SPY no está en el universo del cohorte). Lo que se fija:

1. ``empalmar`` extiende la serie hacia atrás re-escalando el tramo viejo en la primera fecha en
   común, así la junta no mete un salto falso (``auto_adjust`` re-escala por dividendos en cada
   fetch); sin fechas en común no empalma.
2. Con backend ``sqlite`` no hace nada (un frame por ticker).
3. El kill-criteria: una cuenta que arranca **antes** del ``2y`` igual tiene VS SPY.
4. El frame largo se vuelve a bajar cuando tiene más de 90 días, y el job está cableado. Desde la
   **251** es un frame propio (``max``): el ``10y`` es la serie de régimen del harness y lo
   refresca ``refresh_cohort``.
"""

from __future__ import annotations

import inspect
import sqlite3

import pandas as pd
import pytest

import analysis.metrics_panel as mp
from data import historical_series as hs
from paper_trading import scheduler as sch


def _df(filas: list[tuple[str, float]]) -> pd.DataFrame:
    idx = pd.to_datetime([d for d, _ in filas])
    c = [x for _, x in filas]
    return pd.DataFrame({"Close": c, "High": c, "Low": c}, index=idx)


_DIAS = [f"2026-01-{d:02d}" for d in range(5, 17)]  # 12 ruedas sintéticas


def test_empalma_hacia_atras_sin_salto_en_la_junta():
    # El frame viejo está en otra escala (×0.99, como tras un dividendo ajustado).
    viejo = [(d, 0.99 * (100 + i)) for i, d in enumerate(_DIAS[:8])]
    nuevo = [(d, 100 + i) for i, d in enumerate(_DIAS) if i >= 5]
    out = hs.empalmar(nuevo, "SPY", frames=[_df(nuevo), _df(viejo)])

    assert out[0][0] == _DIAS[0], "arranca donde arranca el frame viejo"
    d = dict(out)
    assert d[_DIAS[5]] == pytest.approx(105.0), "desde la junta manda el frame nuevo, intacto"
    # El retorno de la junta es el del frame viejo, no el salto de escala entre frames.
    assert d[_DIAS[5]] / d[_DIAS[4]] == pytest.approx(105 / 104)
    assert d[_DIAS[1]] / d[_DIAS[0]] == pytest.approx(101 / 100), "los retornos viejos se conservan"


def test_sin_fechas_en_comun_NO_empalma():
    viejo = [(d, 50.0) for d in _DIAS[:3]]
    nuevo = [(d, 100.0) for d in _DIAS[6:]]
    assert hs.empalmar(nuevo, "SPY", frames=[_df(nuevo), _df(viejo)]) == nuevo


def test_con_backend_sqlite_no_hace_nada(monkeypatch):
    monkeypatch.setattr(hs, "backend_activo", lambda: "sqlite")
    base = [(_DIAS[5], 100.0), (_DIAS[6], 101.0)]
    assert hs.empalmar(base, "SPY") is base


def _con(equity):
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE paper_equity_snapshots (id INTEGER PRIMARY KEY, account_id INT, "
        "snapshot_at TEXT, total_equity REAL)"
    )
    con.execute("CREATE TABLE paper_accounts (id INTEGER PRIMARY KEY, name TEXT, initial_capital REAL)")
    con.execute("INSERT INTO paper_accounts (id, name, initial_capital) VALUES (2,'Sintetica',50000.0)")
    for dia, eq in equity:
        con.execute(
            "INSERT INTO paper_equity_snapshots (account_id, snapshot_at, total_equity) VALUES (2,?,?)",
            (f"{dia} 21:00:00", eq),
        )
    return con


def test_una_cuenta_que_arranca_ANTES_del_2y_igual_tiene_vs_spy(monkeypatch):
    """El kill-criteria. Sin el empalme este caso es el `serie_corta` de la 225."""
    corta = [("2026-06-01", 100.0), ("2026-09-30", 110.0)]
    larga = [("2025-12-01", 90.0), ("2026-01-05", 92.0), ("2026-06-01", 99.0), ("2026-09-01", 105.0)]
    monkeypatch.setattr(mp, "load_close_series", lambda con, t: corta)
    monkeypatch.setattr(hs, "backend_activo", lambda: "parquet")
    from data import parquet_cache

    monkeypatch.setattr(parquet_cache, "all_1d", lambda t: [_df(corta), _df(larga)])
    con = _con([("2026-01-05", 50_000.0), ("2026-09-30", 55_000.0)])

    b = mp._benchmark_panel(con, 2)
    assert b.get("motivo") != "serie_corta", b
    assert b["vs_spy"] is not None and b["spy_start_day"] <= "2026-01-05", b


def test_el_mismo_caso_SIN_empalme_se_apaga():
    """Contraprueba del de arriba: sin frames viejos es el `serie_corta` de siempre."""
    corta = [("2026-06-01", 100.0), ("2026-09-30", 110.0)]
    assert hs.empalmar(corta, "SPY", frames=[_df(corta)]) == corta


@pytest.mark.parametrize(
    ("ultimo", "vencido"),
    [(None, True), ("2026-09-01", False), ("2026-07-01", False), ("2026-06-30", True), ("basura", True)],
)
def test_el_frame_largo_se_baja_de_nuevo_pasados_90_dias(ultimo, vencido):
    assert hs.benchmark_largo_vencido(ultimo, "2026-09-29") is vencido


def test_refrescar_pide_el_frame_largo_solo_si_esta_vencido(monkeypatch):
    from data import parquet_cache

    pedidos = []

    def _fetch(t, period, interval):
        pedidos.append((t, period, interval))
        return _df([("2026-09-29", 600.0)])

    monkeypatch.setattr(parquet_cache, "labelled_1d", lambda t: [("max", _df([("2026-09-01", 590.0)]))])
    assert hs.refrescar_benchmark_largo(hoy="2026-09-30", fetch=_fetch)["refrescado"] is False
    # Un `10y` fresco no cuenta: es del cohorte del harness, no del benchmark (tarea 251).
    monkeypatch.setattr(parquet_cache, "labelled_1d", lambda t: [("10y", _df([("2026-09-29", 600.0)]))])
    r = hs.refrescar_benchmark_largo(hoy="2026-09-30", fetch=_fetch)
    assert r["refrescado"] is True and pedidos == [("SPY", "max", "1d")]


def test_los_tres_consumidores_usan_la_serie_empalmada():
    """La lección de la 218: dos copias del lector permitieron que arreglar una no alcanzara a la otra."""
    import scripts.dashboard_data as dd
    import ui.paper_tab as pt

    assert "load_benchmark_series(con)" in inspect.getsource(mp._benchmark_panel)
    assert "load_benchmark_series" in inspect.getsource(pt)
    assert "empalmar(" in inspect.getsource(dd)


def test_el_refresh_del_frame_largo_esta_cableado():
    assert "_maybe_refresh_benchmark_largo" in inspect.getsource(sch.PaperScheduler.start)
    assert "_maybe_refresh_benchmark_largo" in inspect.getsource(sch.PaperScheduler._on_daily_tick)
