"""Tarea 474 — la curva de Paper son los ÚLTIMOS snapshots, no los primeros.

``get_equity_curve`` ordenaba ascendente y recién ahí cortaba con el ``limit``, así que devolvía
los **primeros**. La pestaña Paper pedía 500: la cuenta 2 pasó los 500 snapshots el 2026-09-02, y
desde ese día la curva no avanzó (terminaba en $51.496 con la tarjeta *«Equity total»* en $49.690).

Los casos están elegidos para que el código de antes dé otra cosa: cada snapshot vale distinto, y
el de la pestaña tiene **más de 500** (con menos, los primeros 500 son todos y el defecto no se ve).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_T0 = datetime(2026, 6, 20, 15, 0)


def _cuenta_con_snapshots(n: int, a_costo: set[int] = frozenset()) -> int:
    """Una cuenta con ``n`` snapshots, uno por hora, cada uno con su equity (50.000 + i)."""
    from database.models import session_scope
    from paper_trading.models import PaperAccount, PaperEquitySnapshot

    with session_scope() as s:
        a = PaperAccount(name="Sim Segundo", initial_capital=50_000.0, is_active=True)
        s.add(a)
        s.flush()
        s.add_all(
            [
                PaperEquitySnapshot(
                    account_id=a.id,
                    snapshot_at=_T0 + timedelta(hours=i),
                    cash=1_000.0,
                    positions_value=49_000.0 + i,
                    total_equity=50_000.0 + i,
                    positions_at_cost=1 if i in a_costo else 0,
                )
                for i in range(n)
            ]
        )
        return a.id


def _equities(snaps) -> list[float]:
    return [s.total_equity for s in snaps]


def test_con_limit_vienen_los_ultimos_en_orden_ascendente(test_db):
    from paper_trading.account import get_equity_curve

    cuenta = _cuenta_con_snapshots(7, a_costo={5})  # el 5 es a costo: no cuenta para el límite
    assert _equities(get_equity_curve(cuenta, limit=3)) == [50_003.0, 50_004.0, 50_006.0]


def test_sin_limit_vienen_todos(test_db):
    from paper_trading.account import get_equity_curve

    cuenta = _cuenta_con_snapshots(7, a_costo={5})
    assert _equities(get_equity_curve(cuenta)) == [50_000.0 + i for i in (0, 1, 2, 3, 4, 6)]


def test_la_pestana_paper_dibuja_la_curva_entera_hasta_el_ultimo_snapshot(test_db):
    """Con 510 snapshots: el código de antes le pasaba al gráfico los primeros 500."""
    pytest.importorskip("PyQt6.QtWidgets")
    from ui.paper_tab import PaperTradingTab

    cuenta = _cuenta_con_snapshots(510)
    dibujado: dict = {}

    falso = SimpleNamespace(
        _current_account_id=cuenta,
        _load_spy_overlay=lambda snaps, account_id: (None, None),
        equity_chart=SimpleNamespace(set_data=lambda snaps, **kw: dibujado.update(snaps=snaps)),
    )
    PaperTradingTab._refresh_equity_curve(falso)

    snaps = dibujado["snaps"]
    assert len(snaps) == 510
    assert snaps[0].total_equity == 50_000.0  # arranca con la cuenta: el overlay de SPY lo supone
    assert snaps[-1].total_equity == 50_509.0  # y termina en el último, no en el 500
