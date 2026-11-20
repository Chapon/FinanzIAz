"""Tarea 448 — una compra o venta débil se rotula «(débil)»: la pestaña la pintaba igual que la moderada.

En MARA, el 2026-11-20, la Señal general decía «Comprar» arriba de «2 alcistas · 1 bajistas · 4
neutrales. Consenso neutral 48/100» (`docs/analisis_mara_senal_vs_claude_t443_2026-11-20.md`). La
señal y lo que el motor hace con ella no cambian: sólo el rótulo.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from ui.analysis.labels import SUFIJO_DEBIL, es_debil, rotulo_senal


@pytest.mark.parametrize(
    ("senal", "fuerza", "rotulo"),
    [
        ("BUY", "WEAK", "Comprar (débil)"),
        ("BUY", "MODERATE", "Comprar"),
        ("BUY", "STRONG", "Compra Fuerte"),
        ("SELL", "WEAK", "Vender (débil)"),
        ("SELL", "MODERATE", "Vender"),
        ("SELL", "STRONG", "Venta Fuerte"),
        ("HOLD", "WEAK", "Mantener"),
    ],
)
def test_el_rotulo_dice_la_fuerza_solo_cuando_es_debil(senal, fuerza, rotulo):
    assert rotulo_senal(senal, fuerza) == rotulo


def test_mantener_no_es_debil():
    assert es_debil("BUY", "WEAK") and es_debil("SELL", "WEAK")
    assert not es_debil("HOLD", "WEAK") and not es_debil("BUY", "MODERATE")


def test_el_badge_lleva_el_sufijo(qapp):
    """Con el ``qapp`` de pytest-qt, que vive toda la sesión: un QApplication propio que se destruye
    al terminar el test deja a Qt sin pool de hilos para el que importa la pestaña Cartera después."""
    from ui.widgets import SignalBadge

    debil = SignalBadge("Buy", debil=True)
    assert debil.text() == "● Comprar" + SUFIJO_DEBIL
    b = SignalBadge("Buy")
    assert b.text() == "● Comprar"
    b.set_signal("Underperform", debil=True)
    assert b.text() == "● Vender (débil)"


def _df():
    n = 60
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    c = np.linspace(100.0, 110.0, n)
    return pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1e6}, index=idx)


def _resultado(senal, fuerza):
    from analysis.technical import AnalysisResult

    return AnalysisResult(ticker="MARA", overall_signal=senal, overall_strength=fuerza, confidence_score=20.0)


@pytest.mark.parametrize(("fuerza", "debil"), [("WEAK", True), ("MODERATE", False)])
def test_la_senal_general_de_la_pestana(fuerza, debil):
    """El caso de MARA: BUY débil → el badge de Señal general va con «(débil)»."""
    import ui.analysis_tab as at

    tab = MagicMock()
    tab.ticker_edit.text.return_value = "MARA"
    at.AnalysisTab._on_analysis_done(
        tab, _df(), _resultado("BUY", fuerza), None, {"name": "MARA"}, None, ticker="MARA"
    )
    llamada = tab.overall_badge.set_signal.call_args
    assert llamada.args[0] == "Buy" and llamada.kwargs["debil"] is debil


def test_la_columna_de_la_cartera():
    """La pestaña Cartera guarda el nivel y si es débil, y lo pinta igual que Análisis."""
    from ui.portfolio_tab import nivel_de, rotulo_de_nivel

    r = SimpleNamespace(yahoo_level="Buy", overall_signal="BUY", overall_strength="WEAK")
    assert nivel_de(r) == ("Buy", True)
    assert rotulo_de_nivel(nivel_de(r)) == ("Buy", "Comprar (débil)")
    assert rotulo_de_nivel(("Buy", False)) == ("Buy", "Comprar")
    assert rotulo_de_nivel("Hold") == ("Hold", "Mantener")  # lo guardado antes: un str
    assert rotulo_de_nivel(None) == (None, "")


def test_la_tarjeta_de_cada_indicador(qapp):
    from analysis.technical import TechnicalSignal
    from ui.analysis.signal_card import SignalCard
    from ui.widgets import SignalBadge

    card = SignalCard(TechnicalSignal("RSI", 38.0, "BUY", "WEAK", "RSI cerca de sobreventa"))
    (badge,) = card.findChildren(SignalBadge)
    assert badge.text() == "● Comprar (débil)"
