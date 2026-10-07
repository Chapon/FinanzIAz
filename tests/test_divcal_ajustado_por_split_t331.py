"""Tarea 331 — el calendario de dividendos viene AJUSTADO por splits, y la cartera real lo sabe.

El docstring de ``DividendCalendarCache`` decía «sin ajustar por splits posteriores»; los datos
dicen lo contrario (NVDA, ex 2024-03-05: 0.004, cuando se pagaron $0,04). La 324 guarda NVDA en
acciones de hoy, y eso cobra bien **porque** el monto está ajustado. Este test fija la cuenta con
el caso real: 7 acciones de antes del split × $0,04 = 70 acciones de hoy × $0,004 = $0,28.
"""

from __future__ import annotations

from datetime import date

import pytest

from database.cartera_real import dividendos_cobrados
from database.lotes import Movimiento, armar_posiciones

# El calendario como lo guarda el cache: ajustado al split 10:1 del 2024-06-10.
_NVDA_CAL = [("2024-03-05", 0.004), ("2024-06-11", 0.01)]


def test_las_acciones_ajustadas_por_la_324_cobran_lo_que_se_pago():
    movs = {
        "NVDA": [
            Movimiento(date(2024, 2, 21), "BUY", 7, 681.22, 80.0),
            Movimiento(date(2024, 6, 6), "BUY", 5, 1202.66, 100.0),
            Movimiento(date(2024, 6, 7), "SELL", 12, 1200.0, 0.0, "Stock Split"),
            Movimiento(date(2024, 6, 10), "BUY", 120, 120.0, 0.0, "Stock Split"),
        ]
    }
    (nvda,) = armar_posiciones(movs)
    eventos = [
        (m.fecha.isoformat(), m.cantidad if m.tipo == "BUY" else -m.cantidad) for m in nvda.movimientos
    ]
    cobrado = dividendos_cobrados(eventos, _NVDA_CAL)
    # Marzo: 7 acciones × $0,04 pagados. Junio (post-split): 120 × $0,01.
    assert cobrado == pytest.approx(7 * 0.04 + 120 * 0.01)


def test_el_docstring_dice_AJUSTADO_y_ya_no_lo_contrario():
    """Comparado por la frase completa: un `in` sobre «ajustar» aceptaría las dos versiones."""
    from database.models import DividendCalendarCache

    doc = " ".join((DividendCalendarCache.__doc__ or "").split())
    assert "es en dólares por acción **ajustado por los splits posteriores**" in doc
    assert "**sin ajustar por splits posteriores**" not in doc
