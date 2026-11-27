"""Tarea 475 — la curva de Paper marca los días hábiles en que la app no corrió.

Entre dos scans la curva dibuja una recta, y se lee como si la cuenta hubiera operado. Chapa
pidió marcar esos días con bandas rojas traslúcidas. Los datos de estos tests están elegidos
para que la versión ingenua dé otra cosa: el feriado del Labor Day (lunes 2026-09-07) en el
medio de un tramo, un snapshot a las 22:40 ET (que en UTC ya es el día siguiente), un fin de
semana con la app abierta, y un día cuyo único scan dejó posiciones a costo.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.paper.equity_chart import etiqueta_sin_scan, tramos_sin_scan

FERIADO = date(2026, 9, 7)  # Labor Day: NYSE cerrada


def _ruedas(desde: date, hasta: date, feriados=(FERIADO,)) -> list[str]:
    """Las ruedas como las da la serie de SPY: ``AAAA-MM-DD``, sin fines de semana ni feriados."""
    out, d = [], desde
    while d <= hasta:
        if d.weekday() < 5 and d not in feriados:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


RUEDAS = _ruedas(date(2026, 8, 31), date(2026, 9, 18))


def test_el_feriado_no_cuenta_ni_corta_la_banda():
    # Scans el jueves 3/9 y el jueves 10/9. Sin scan: vie 4, (sáb, dom, lun feriado), mar 8, mié 9.
    snaps = [datetime(2026, 9, 3, 15), datetime(2026, 9, 10, 15)]
    # Una banda, de la medianoche de Nueva York del 4/9 (04:00 UTC, horario de verano) a la del 10/9;
    # 3 ruedas: con lunes a viernes como calendario serían 4.
    assert tramos_sin_scan(snaps, RUEDAS) == [(datetime(2026, 9, 4, 4), datetime(2026, 9, 10, 4), 3)]


def test_un_fin_de_semana_con_la_app_abierta_corta_la_banda():
    # Lo mismo, pero la app se abrió el sábado 5/9: entre el viernes y el martes sí corrió.
    snaps = [datetime(2026, 9, 3, 15), datetime(2026, 9, 5, 15), datetime(2026, 9, 10, 15)]
    assert tramos_sin_scan(snaps, RUEDAS) == [
        (datetime(2026, 9, 4, 4), datetime(2026, 9, 5, 4), 1),
        (datetime(2026, 9, 8, 4), datetime(2026, 9, 10, 4), 2),
    ]


def test_el_dia_es_el_de_nueva_york_y_no_el_de_utc():
    # El viernes 4/9 la app se abrió a las 22:40 ET, que en UTC es el sábado 5/9 a las 02:40:
    # el viernes tuvo scan. Con la fecha UTC quedaría marcado.
    snaps = ["2026-09-03 15:00:00.000000", "2026-09-05 02:40:00.123456", "2026-09-10 15:00:00"]
    assert tramos_sin_scan(snaps, RUEDAS) == [(datetime(2026, 9, 8, 4), datetime(2026, 9, 10, 4), 2)]


def test_en_horario_de_invierno_la_medianoche_de_nueva_york_son_las_5_utc():
    # Después del 1/11 Nueva York está en UTC−5. El 11/11 (Veterans Day) la NYSE abre.
    ruedas = _ruedas(date(2026, 11, 2), date(2026, 11, 13), feriados=())
    snaps = [datetime(2026, 11, 9, 20), datetime(2026, 11, 12, 20)]
    assert tramos_sin_scan(snaps, ruedas) == [(datetime(2026, 11, 10, 5), datetime(2026, 11, 12, 5), 2)]


def test_solo_entre_el_primer_y_el_ultimo_scan_y_hasta_el_ultimo_cierre_de_spy():
    # SPY termina el martes 8/9: del 9 en adelante no se sabe si hubo rueda, y no se marca.
    # El 1 y el 2/9, antes del primer scan, la cuenta no existía.
    ruedas = [r for r in RUEDAS if r <= "2026-09-08"]
    snaps = [datetime(2026, 9, 3, 15), datetime(2026, 9, 10, 15)]
    assert tramos_sin_scan(snaps, ruedas) == [(datetime(2026, 9, 4, 4), datetime(2026, 9, 9, 4), 2)]


def test_sin_snapshots_o_sin_ruedas_no_hay_tramos():
    assert tramos_sin_scan([], RUEDAS) == []
    assert tramos_sin_scan([None], RUEDAS) == []
    assert tramos_sin_scan([datetime(2026, 9, 3, 15), datetime(2026, 9, 10, 15)], []) == []


def test_el_rotulo_dice_cuantos_dias_habiles():
    assert etiqueta_sin_scan(1) == "App cerrada (1 día hábil sin scan)"
    assert etiqueta_sin_scan(36) == "App cerrada (36 días hábiles sin scan)"


# ── El gráfico ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@dataclass
class _Snap:
    snapshot_at: datetime
    total_equity: float


SNAPS = [_Snap(datetime(2026, 9, 3, 15), 50_000.0), _Snap(datetime(2026, 9, 10, 15), 50_500.0)]


def test_el_grafico_pinta_una_banda_por_tramo_con_un_solo_rotulo(qapp):
    from ui.paper.equity_chart import EquityCurveChart
    from ui.styles import PALETTE

    chart = EquityCurveChart()
    tramos = [
        (datetime(2026, 9, 4, 4), datetime(2026, 9, 5, 4), 1),
        (datetime(2026, 9, 8, 4), datetime(2026, 9, 10, 4), 2),
    ]
    chart.set_data(SNAPS, sin_scan=tramos)
    bandas = chart.ax.patches
    assert len(bandas) == 2
    assert all(b.get_facecolor()[:3] == pytest.approx(_rgb(PALETTE["red"])) for b in bandas)
    rotulos = [t.get_text() for t in chart.ax.get_legend().get_texts()]
    assert rotulos == ["App cerrada (3 días hábiles sin scan)", "Equity"]
    chart.cleanup()


def test_sin_tramos_no_hay_bandas_ni_leyenda_nueva(qapp):
    from ui.paper.equity_chart import EquityCurveChart

    chart = EquityCurveChart()
    chart.set_data(SNAPS, sin_scan=[])
    assert len(chart.ax.patches) == 0 and chart.ax.get_legend() is None
    chart.cleanup()


def test_con_spy_suprimido_la_leyenda_de_las_bandas_no_pisa_el_aviso(qapp):
    from ui.paper.equity_chart import EquityCurveChart

    chart = EquityCurveChart()
    chart.set_data(
        SNAPS,
        benchmark_aviso="SPY desactualizado",
        sin_scan=[(datetime(2026, 9, 4, 4), datetime(2026, 9, 5, 4), 1)],
    )
    assert any("desactualizado" in t.get_text() for t in chart.ax.texts)
    leyenda = chart.ax.get_legend()
    assert leyenda is not None and leyenda._loc == 1  # «upper right»: arriba a la izquierda va el aviso
    chart.cleanup()


def _rgb(hexa: str) -> tuple[float, float, float]:
    h = hexa.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))


# ── La pestaña: una lectura, y todos los snapshots ───────────────────────────


def test_la_pestana_cuenta_como_scan_el_snapshot_a_costo_y_lee_spy_una_vez(tmp_path, monkeypatch):
    """El viernes 4/9 el único scan dejó posiciones a costo: la curva lo saca (tarea 376), pero
    la app corrió, y el viernes no va marcado. SPY se lee una sola vez para el overlay y el
    calendario: tarda ~0,25–0,55 s en el hilo de la interfaz."""
    pytest.importorskip("PyQt6.QtWidgets")
    from ui.paper_tab import PaperTradingTab

    db = tmp_path / "curva.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE paper_accounts (id INTEGER PRIMARY KEY, initial_capital REAL)")
    con.execute(
        "CREATE TABLE paper_equity_snapshots (id INTEGER PRIMARY KEY, account_id INTEGER, "
        "snapshot_at TEXT, total_equity REAL, positions_at_cost INTEGER)"
    )
    con.execute("INSERT INTO paper_accounts VALUES (7, 50000.0)")
    filas = [
        ("2026-09-03 15:00:00.000000", 50_000.0, 0),
        ("2026-09-04 15:00:00.000000", 50_100.0, 2),  # a costo
        ("2026-09-10 15:00:00.000000", 50_500.0, 0),
    ]
    con.executemany(
        "INSERT INTO paper_equity_snapshots (account_id, snapshot_at, total_equity, positions_at_cost) "
        "VALUES (7, ?, ?, ?)",
        filas,
    )
    con.commit()
    con.close()

    lecturas = []

    def _spy(_con):
        lecturas.append(1)
        return [(r, 400.0 + i) for i, r in enumerate(_ruedas(date(2026, 8, 3), date(2026, 9, 18)))]

    monkeypatch.setattr("database.models.DB_PATH", str(db))
    monkeypatch.setattr("analysis.metrics_panel.load_benchmark_series", _spy)
    curva = [_Snap(datetime(2026, 9, 3, 15), 50_000.0), _Snap(datetime(2026, 9, 10, 15), 50_500.0)]

    overlay, aviso, sin_scan = PaperTradingTab._load_contexto_de_la_curva(curva, 7)

    assert sin_scan == [(datetime(2026, 9, 8, 4), datetime(2026, 9, 10, 4), 2)]
    assert overlay and aviso is None
    assert len(lecturas) == 1
