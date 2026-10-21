"""Tarea 386 — lo que le costó operar a una cuenta paper, visible en Home al lado de su curva."""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from analysis.metrics_panel import costo_de_rotar, costo_de_rotar_de_cuenta


def _o(i, side, precio, acciones, cuando, comision=0.0, slippage=0.0, ticker="A"):
    return {
        "id": i,
        "ticker": ticker,
        "side": side,
        "fill_price": precio,
        "fill_shares": acciones,
        "commission": comision,
        "slippage": slippage,
        "score": None,
        "reason": "",
        "filled_at": cuando,
    }


def test_la_rotacion_cuenta_compras_y_ventas():
    """Comprar el capital y venderlo una vez es rotarlo 2,2 veces acá, no 1,0 (sólo compras)."""
    ordenes = [
        _o(1, "BUY", 10.0, 100, "2026-07-01 15:00:00"),
        _o(2, "SELL", 12.0, 100, "2026-07-11 15:00:00"),
    ]
    r = costo_de_rotar(ordenes, capital=1000.0)
    assert r["volumen"] == pytest.approx(2200.0)
    assert r["rotacion"] == pytest.approx(2.2)


def test_los_costos_incluyen_los_fills_de_posiciones_abiertas():
    """Contar sólo las operaciones cerradas dejaría afuera la compra que sigue abierta."""
    ordenes = [
        _o(1, "BUY", 10.0, 100, "2026-07-01 15:00:00", comision=1.0, slippage=0.5),
        _o(2, "SELL", 12.0, 100, "2026-07-11 15:00:00", comision=1.0, slippage=0.6),
        _o(3, "BUY", 20.0, 10, "2026-07-12 15:00:00", comision=1.0, slippage=0.2, ticker="B"),
    ]
    r = costo_de_rotar(ordenes, capital=1000.0)
    assert r["costos"] == pytest.approx(4.3)
    assert r["n_fills"] == 3 and r["n_cerradas"] == 1


def test_la_tenencia_es_la_media_de_las_cerradas_no_la_mediana():
    """10, 20 y 60 días: la media es 30 y la mediana 20 (con dos operaciones darían lo mismo)."""
    ordenes = [
        _o(1, "BUY", 10.0, 100, "2026-07-01 15:00:00"),
        _o(2, "SELL", 10.0, 100, "2026-07-11 15:00:00"),
        _o(3, "BUY", 10.0, 100, "2026-07-01 15:00:00", ticker="B"),
        _o(4, "SELL", 10.0, 100, "2026-07-21 15:00:00", ticker="B"),
        _o(5, "BUY", 10.0, 100, "2026-07-01 15:00:00", ticker="C"),
        _o(6, "SELL", 10.0, 100, "2026-08-30 15:00:00", ticker="C"),
    ]
    assert costo_de_rotar(ordenes, capital=1000.0)["tenencia_media"] == pytest.approx(30.0)


def test_sin_cerradas_no_hay_tenencia_y_sin_capital_no_hay_rotacion():
    r = costo_de_rotar([_o(1, "BUY", 10.0, 100, "2026-07-01 15:00:00")], capital=0.0)
    assert r["tenencia_media"] is None
    assert r["rotacion"] is None


# ── Home ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def cuenta(test_db):
    from database.models import session_scope
    from paper_trading.models import PaperAccount, PaperEquitySnapshot, PaperOrder

    with session_scope() as s:
        c = PaperAccount(
            name="Sim Segundo", initial_capital=1000.0, is_active=True, created_at=datetime(2026, 7, 1)
        )
        s.add(c)
        s.flush()
        for ts, eq in ((datetime(2026, 7, 2, 18), 1001.0), (datetime(2026, 7, 13, 18), 1010.0)):
            s.add(
                PaperEquitySnapshot(
                    account_id=c.id, snapshot_at=ts, cash=1.0, positions_value=eq - 1, total_equity=eq
                )
            )
        # La rechazada trae fill_price por error de carga: si el filtro de `filled` se cayera, contaría.
        for side, precio, cuando, com, estado in (
            ("BUY", 10.0, datetime(2026, 7, 1, 15), 1.0, "filled"),
            ("SELL", 12.0, datetime(2026, 7, 11, 15), 1.5, "filled"),
            ("BUY", 50.0, datetime(2026, 7, 12, 15), 9.0, "rejected"),
        ):
            s.add(
                PaperOrder(
                    account_id=c.id,
                    ticker="A",
                    side=side,
                    reason="analyze",
                    source="analyze_single",
                    status=estado,
                    created_at=cuando,
                    filled_at=cuando,
                    fill_price=precio,
                    fill_shares=100,
                    commission_paid=com,
                    slippage_cost=0.25,
                )
            )
        return c.id


def test_lee_los_fills_por_la_sesion(cuenta):
    r = costo_de_rotar_de_cuenta(cuenta, 1000.0)
    assert r["costos"] == pytest.approx(3.0)
    assert r["rotacion"] == pytest.approx(2.2)
    assert r["tenencia_media"] == pytest.approx(10.0)


def test_home_muestra_lo_que_costo_operar_en_las_tres_vistas(cuenta):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    global _APP
    _APP = QApplication.instance() or QApplication([])  # referencia viva (la lección de la 323)
    from ui.home_tab import HomeTab

    h = HomeTab()
    try:
        for cb in h.cuenta_checks.values():
            cb.setChecked(False)
        h.cuenta_checks[cuenta].setChecked(True)
        for clave in ("valor", "ganancia", "invertido"):
            h.vista_combo.setCurrentIndex(h.vista_combo.findData(clave))
            texto = h.hero_sub.text()
            assert "Operar le costó $3.00" in texto, (clave, texto)
            assert "rotó 2.2 veces el capital" in texto, (clave, texto)
            assert "10.0 días de tenencia media en 1 operaciones cerradas" in texto, (clave, texto)
    finally:
        h.hero_chart.cleanup()
        h.deleteLater()
