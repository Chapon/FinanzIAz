"""Tarea 194 — score mensual de desempeño: 100 = $4.000 realizados en el mes.

Definiciones elegidas por Chapa (2026-09-13): **70% plata + 30% calidad**, entre 0 y 100;
plata = P/L **realizado** del mes ÷ $4.000 recortado a [0, 100]; calidad = % de round-trips
cerrados en el mes con ganancia; serie **mensual**. Display-only.
"""

from __future__ import annotations

from datetime import date

import pytest

from analysis import performance_score as ps


def _rt(sell_day: str, pnl: float, buy_day: str = "2026-01-01") -> dict:
    return {"sell_day": sell_day, "buy_day": buy_day, "pnl": pnl}


# ── La fórmula ──────────────────────────────────────────────────────────────


def test_las_constantes_son_las_elegidas():
    assert ps.TARGET_MONTHLY_USD == 4000.0
    assert (ps.WEIGHT_MONEY, ps.WEIGHT_QUALITY) == (0.70, 0.30)


def test_julio_de_la_cuenta_viva():
    """+$1.277 con 8 de 19 ganadores: 0,7·31,9 + 0,3·42,1 = 35,0."""
    m = ps.score_month(1277.0, 19, 8)
    assert m["money_pct"] == pytest.approx(31.925)
    assert m["quality_pct"] == pytest.approx(800 / 19)
    assert m["score"] == pytest.approx(0.7 * 31.925 + 0.3 * 800 / 19)


def test_llegar_al_objetivo_con_todas_ganadoras_da_100():
    assert ps.score_month(4000.0, 5, 5)["score"] == pytest.approx(100.0)


def test_un_mes_que_PIERDE_da_cero_de_plata_pero_conserva_la_calidad():
    m = ps.score_month(-1692.0, 20, 5)
    assert m["money_pct"] == 0.0
    assert m["score"] == pytest.approx(0.3 * 25.0)


def test_pasar_el_objetivo_no_supera_100():
    m = ps.score_month(9000.0, 10, 10)
    assert m["money_pct"] == 100.0
    assert m["score"] == 100.0


def test_un_mes_sin_operaciones_tiene_calidad_INDEFINIDA_y_score_cero():
    """Sin decisiones no hay aciertos que medir: `None`, no 0%."""
    m = ps.score_month(0.0, 0, 0)
    assert m["quality_pct"] is None
    assert m["score"] == 0.0


def test_un_empate_exacto_no_cuenta_como_ganador():
    assert (
        ps.monthly_scores([_rt("2026-07-10", 0.0)], first_day="2026-07-01", today=date(2026, 7, 31))[0][
            "n_wins"
        ]
        == 0
    )


# ── La serie mensual ─────────────────────────────────────────────────────────


def test_la_serie_va_del_primer_fill_a_hoy_con_los_meses_vacios_en_cero():
    rts = [_rt("2026-06-25", 450.0), _rt("2026-08-10", -100.0)]
    meses = ps.monthly_scores(rts, first_day="2026-06-20", today=date(2026, 9, 13))

    assert [m["month"] for m in meses] == ["2026-06", "2026-07", "2026-08", "2026-09"]
    julio = meses[1]
    assert (julio["n_round_trips"], julio["realized_pnl"], julio["score"]) == (0, 0.0, 0.0)
    assert [m["in_progress"] for m in meses] == [False, False, False, True]


def test_el_round_trip_cae_en_el_mes_de_la_VENTA_y_no_de_la_compra():
    """El P/L se realiza al vender."""
    meses = ps.monthly_scores(
        [_rt("2026-07-02", 300.0, buy_day="2026-06-28")], first_day="2026-06-28", today=date(2026, 7, 31)
    )
    assert (meses[0]["month"], meses[0]["realized_pnl"]) == ("2026-06", 0.0)
    assert (meses[1]["month"], meses[1]["realized_pnl"]) == ("2026-07", 300.0)


def test_el_cambio_de_anio():
    meses = ps.monthly_scores([], first_day="2026-11-15", today=date(2027, 2, 1))
    assert [m["month"] for m in meses] == ["2026-11", "2026-12", "2027-01", "2027-02"]


def test_sin_fills_no_hay_serie():
    assert ps.monthly_scores([], first_day=None, today=date(2026, 9, 13)) == []


def test_el_panel_resume_SOLO_meses_cerrados():
    """El mes en curso no puede ser «el mejor» ni entrar al promedio: está incompleto."""
    rts = [_rt("2026-07-10", 1000.0), _rt("2026-08-10", 200.0), _rt("2026-09-05", 3900.0)]
    orders = [{"filled_at": "2026-07-01 10:00:00"}]
    panel = ps.performance_score_panel(rts, orders, today=date(2026, 9, 13))

    assert panel["current"]["month"] == "2026-09" and panel["current"]["in_progress"]
    assert panel["best"]["month"] == "2026-07"
    assert panel["worst"]["month"] == "2026-08"
    assert panel["avg_completed"] == pytest.approx((panel["best"]["score"] + panel["worst"]["score"]) / 2)


# ── Integración con la pestaña Métricas ─────────────────────────────────────


def test_build_metrics_trae_el_bloque_performance_score():
    pytest.importorskip("PyQt6.QtWidgets")
    from tests.test_metrics_tab_smoke import _payload_with_data

    ps_block = _payload_with_data()["performance_score"]
    assert ps_block["target_monthly_usd"] == 4000.0
    enero = next(m for m in ps_block["months"] if m["month"] == "2026-01")
    assert enero["n_round_trips"] == 1 and enero["n_wins"] == 1
    assert enero["realized_pnl"] > 0


def test_la_pestania_muestra_el_score_y_el_PL_con_signo(qapp_194):
    from tests.test_metrics_tab_smoke import _payload_with_data
    from ui.metrics_tab import MetricsTab

    payload = _payload_with_data()
    # El payload tiene operaciones de enero 2026: se fija «hoy» en enero para que ése sea el mes
    # en curso. Con la fecha real, el mes en curso no tiene operaciones y el panel lo dice así.
    payload["performance_score"] = ps.performance_score_panel(
        payload["realized"]["round_trips"], [{"filled_at": "2026-01-01 10:00:00"}], today=date(2026, 1, 31)
    )
    tab = MetricsTab(account_id=1)
    tab._on_result(payload)
    panel = tab.score_panel
    assert "ENERO 2026 (en curso)" in panel.title_lbl.text()
    assert panel.value_lbl.text() not in ("", "—")
    assert "P/L realizado +$" in panel.detail_lbl.text()
    assert "1 de 1 round-trips ganadores (100%)" in panel.detail_lbl.text()


def test_la_pestania_sin_operaciones_no_rompe(qapp_194):
    from ui.metrics_tab import PerformanceScorePanel

    panel = PerformanceScorePanel()
    panel.update_score({"months": [], "current": None, "target_monthly_usd": 4000.0})
    assert panel.value_lbl.text() == "—"


def test_el_PL_con_signo():
    pytest.importorskip("PyQt6.QtWidgets")
    from ui.metrics_tab import _money_signed

    assert (_money_signed(1277.4), _money_signed(-1692.2), _money_signed(0.2)) == ("+$1,277", "−$1,692", "$0")


@pytest.fixture(scope="module")
def qapp_194():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets")
    pytest.importorskip("matplotlib")
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
