"""Tarea 392 — la referencia de la 377 se calcula fuera del hilo de la GUI, y una vez por día.

``referencia_de_cuenta`` tarda 1,5-2,5 s (lee los frames ``1d`` de toda la watchlist) y
``HomeTab`` la calculaba **al pintar**, en el hilo de la GUI; ``_llenar_cuentas`` la tiraba en
cada ``load_data`` y ``main_window`` llama ``refresh`` en cada visita a Home. Con una paper
tildada, cada visita trababa la interfaz (`docs/auditoria_tanda_2026-10-23.md` [J-1]).

Acá la referencia es **lenta a propósito** (``_DEMORA_S``) y no toca la DB: lo que se mide es
el hilo de la GUI.
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime

import pytest

_DEMORA_S = 1.0
_TECHO_GUI_S = 0.2
_APP = None


@pytest.fixture
def home(test_db, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    import paper_trading.referencia as pr
    from database.models import session_scope
    from paper_trading.models import PaperAccount, PaperEquitySnapshot

    global _APP
    _APP = QApplication.instance() or QApplication([])
    with session_scope() as s:
        viva = PaperAccount(
            name="Sim Segundo", initial_capital=100.0, is_active=True, created_at=datetime(2026, 1, 29, 18, 0)
        )
        s.add(viva)
        s.flush()
        for ts, eq in ((datetime(2026, 1, 30, 18), 101.0), (datetime(2026, 2, 3, 18), 103.0)):
            s.add(
                PaperEquitySnapshot(
                    account_id=viva.id, snapshot_at=ts, cash=1.0, positions_value=eq - 1, total_equity=eq
                )
            )
        vid = viva.id

    llamadas: list[int] = []

    def lenta(account_id):
        llamadas.append(account_id)
        time.sleep(_DEMORA_S)
        return pr.CurvaReferencia(serie=[(date(2026, 1, 30), 100.0), (date(2026, 2, 3), 102.0)], n=2)

    monkeypatch.setattr(pr, "referencia_de_cuenta", lenta)
    from ui.home_tab import HomeTab

    h = HomeTab()
    h.vid = vid
    h.llamadas = llamadas
    yield h
    _esperar(h)
    h.hero_chart.cleanup()
    h.deleteLater()


def _esperar(home, timeout_s: float = 10.0) -> None:
    """Procesa eventos hasta que no quede ningún cálculo de referencia pendiente."""
    from PyQt6.QtWidgets import QApplication

    from ui import home_tab

    fin = time.monotonic() + timeout_s
    while (home._ref_calculando or home_tab._REFERENCIAS_EN_CURSO) and time.monotonic() < fin:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()
    assert not home._ref_calculando, "la referencia no terminó de calcularse"


def _ref_dibujada(home) -> bool:
    return any(ln.get_label().startswith("Universo de") for ln in home.hero_chart.ax.lines)


def _visitar_home(home) -> None:
    """Lo que hace ``main_window`` en cada visita a Home: ``refresh``. En la app, con la cartera
    «Mis Acciones» presente, ``load_data`` termina repintando el hero; en la DB del test no
    existe y sale antes, así que el repintado se pide acá."""
    home.refresh()
    home._pintar_hero()


def _tildar_solo_la_paper(home) -> float:
    t0 = time.perf_counter()
    for clave, cb in home.cuenta_checks.items():
        cb.setChecked(clave == home.vid)
    return time.perf_counter() - t0


def test_tildar_la_paper_no_traba_la_gui_y_la_referencia_llega_despues(home):
    dt = _tildar_solo_la_paper(home)
    assert dt < _TECHO_GUI_S, f"la GUI quedó trabada {dt:.2f} s (la referencia tarda {_DEMORA_S} s)"
    from ui.home_tab import TEXTO_REFERENCIA_CALCULANDO

    assert TEXTO_REFERENCIA_CALCULANDO in home.hero_sub.text(), "la ausencia se dice, no se pinta como dato"
    assert not _ref_dibujada(home)

    _esperar(home)
    assert _ref_dibujada(home), "al terminar, Home se repinta con la referencia"
    assert TEXTO_REFERENCIA_CALCULANDO not in home.hero_sub.text()


def test_volver_a_home_el_mismo_dia_no_la_recalcula(home):
    _tildar_solo_la_paper(home)
    _esperar(home)
    assert home.llamadas == [home.vid]

    t0 = time.perf_counter()
    _visitar_home(home)
    dt = time.perf_counter() - t0
    assert dt < _TECHO_GUI_S, f"refresh trabó {dt:.2f} s"
    assert home.llamadas == [home.vid], "por día, no por visita"
    assert _ref_dibujada(home), "la referencia del día se pinta en el momento"


def test_otro_dia_la_recalcula(home):
    _tildar_solo_la_paper(home)
    _esperar(home)
    home._ref_dia = date(2000, 1, 1)  # la de ayer
    _visitar_home(home)
    _esperar(home)
    assert home.llamadas == [home.vid, home.vid]


def test_si_el_calculo_falla_se_pinta_sin_referencia_y_no_queda_calculando(home, monkeypatch):
    import paper_trading.referencia as pr

    def rota(_account_id):
        raise RuntimeError("sin frames")

    monkeypatch.setattr(pr, "referencia_de_cuenta", rota)
    _tildar_solo_la_paper(home)
    _esperar(home)
    from ui.home_tab import TEXTO_REFERENCIA_CALCULANDO

    assert not _ref_dibujada(home)
    assert TEXTO_REFERENCIA_CALCULANDO not in home.hero_sub.text()
