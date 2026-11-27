"""Tarea 476 — el eje X de la curva de Paper rotula en la hora local, y no en UTC.

La DB guarda ``snapshot_at`` en UTC sin zona, y matplotlib rotula los datetimes sin zona en
UTC: la marca «01/07 00:00» era el 30/06 a las 21:00 en Buenos Aires. Los datos de estos
tests están elegidos para que la versión vieja dé otra cosa: la medianoche UTC y la local
caen en días distintos, y el cierre de SPY del 1/7 a medianoche UTC es, en Buenos Aires, la
noche del 30/6. La zona va inyectada, porque el CI corre en UTC y ahí las dos coinciden.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BUENOS_AIRES = ZoneInfo("America/Argentina/Buenos_Aires")


@dataclass
class _Snap:
    snapshot_at: datetime
    total_equity: float


@pytest.fixture
def qapp():
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def _rotulos(chart) -> dict[datetime, str]:
    """``{instante UTC sin zona: rótulo}`` de cada marca del eje X, después de dibujar."""
    import matplotlib.dates as mdates

    chart.canvas.draw()
    marcas = chart.ax.get_xticks()
    textos = [t.get_text() for t in chart.ax.get_xticklabels()]
    return {
        mdates.num2date(m, tz=timezone.utc).replace(tzinfo=None): t
        for m, t in zip(marcas, textos, strict=True)
    }


def _curva(chart, desde: datetime, paso: timedelta, n: int) -> None:
    chart.set_data([_Snap(desde + k * paso, 50_000.0 + k) for k in range(n)])


def test_la_marca_de_la_medianoche_es_la_local_y_no_la_utc(qapp):
    from ui.paper.equity_chart import EquityCurveChart

    chart = EquityCurveChart(zona=BUENOS_AIRES)
    # Una cuenta de un día: un snapshot por hora, del 30/06 a las 12:00 UTC al 1/7 a las 12:00.
    _curva(chart, datetime(2026, 6, 30, 12), timedelta(hours=1), 25)
    rotulos = _rotulos(chart)
    # El cambio de día va en la medianoche de Buenos Aires, que son las 03:00 UTC. El código
    # viejo lo ponía en la medianoche UTC, rotulado «01/07 00:00».
    assert rotulos.get(datetime(2026, 7, 1, 3)) == "01/07"
    # Y la medianoche UTC es el 30/06 a las 21:00 en la hora de Chapa.
    assert rotulos.get(datetime(2026, 7, 1, 0)) == "21:00"
    assert rotulos.get(datetime(2026, 6, 30, 15)) == "12:00"
    # El día de las marcas de hora va en el desplazamiento del eje.
    assert chart.ax.xaxis.get_major_formatter().get_offset() == "01/07/2026"


def test_con_meses_el_rotulo_no_lleva_hora(qapp):
    from ui.paper.equity_chart import EquityCurveChart

    chart = EquityCurveChart(zona=BUENOS_AIRES)
    # Cinco meses, un snapshot por día: en una curva así la hora no se lee.
    _curva(chart, datetime(2026, 7, 1, 21, 5), timedelta(days=1), 150)
    rotulos = _rotulos(chart)
    assert rotulos and not any(":" in t for t in rotulos.values())
    # Las marcas de mes caen en la medianoche local del día 1.
    assert rotulos.get(datetime(2026, 8, 1, 3)) == "08/2026"


def test_con_una_semana_el_rotulo_es_el_dia(qapp):
    from ui.paper.equity_chart import EquityCurveChart

    chart = EquityCurveChart(zona=BUENOS_AIRES)
    _curva(chart, datetime(2026, 11, 20, 15), timedelta(hours=6), 28)
    rotulos = _rotulos(chart)
    assert rotulos.get(datetime(2026, 11, 24, 3)) == "24/11"
    assert not any(":" in t for t in rotulos.values())


def test_por_defecto_la_zona_es_la_del_sistema_como_en_fmt_local(qapp):
    """La misma convención que ``ui.time_utils.fmt_local``: ``astimezone()`` sin argumento."""
    from ui.paper.equity_chart import EquityCurveChart

    chart = EquityCurveChart()
    for instante in (
        datetime(2026, 1, 15, 2, tzinfo=timezone.utc),
        datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    ):
        assert instante.astimezone(chart.zona).replace(tzinfo=None) == instante.astimezone().replace(
            tzinfo=None
        )


def test_el_punto_de_spy_es_su_cierre_en_nueva_york():
    from ui.paper.equity_chart import build_benchmark_overlay

    snaps = [_Snap(datetime(2026, 6, 30, 20, 5), 50_000.0), _Snap(datetime(2026, 12, 1, 21, 5), 50_500.0)]
    spy = [("2026-06-29", 600.0), ("2026-06-30", 600.0), ("2026-07-01", 606.0), ("2026-12-01", 612.0)]
    out = dict(build_benchmark_overlay(snaps, spy, 50_000.0))
    # 16:00 de Nueva York: 20:00 UTC con horario de verano, 21:00 sin. A la medianoche UTC, el
    # cierre del 1/7 quedaba en la noche del 30/6 de Buenos Aires, antes de la rueda que cierra.
    assert set(out) == {datetime(2026, 6, 30, 20), datetime(2026, 7, 1, 20), datetime(2026, 12, 1, 21)}
    assert out[datetime(2026, 7, 1, 20)] == pytest.approx(50_500.0)
    assert datetime(2026, 7, 1, 20, tzinfo=timezone.utc).astimezone(BUENOS_AIRES).day == 1
