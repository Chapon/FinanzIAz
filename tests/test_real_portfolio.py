"""
Tests for ``ui.paper.real_portfolio``.

These helpers were extracted from ``PaperTradingTab`` because they have no
shared state with the rest of the tab — they only consult the DB,
optionally show a ``QInputDialog`` / ``QMessageBox``, and return a value.
Pulling them out let us test them without spinning up a real Qt event
loop: every dialog call is monkey-patched at the module level.

Covered paths
-------------
``pick_real_portfolio``
    * empty DB → shows a "Sin portafolios" message, returns ``None``
    * single portfolio → auto-resolves to its id, no dialog
    * multiple portfolios → user picks one in the QInputDialog
    * multiple portfolios → user cancels the dialog (ok=False) → ``None``

``find_real_position``
    * ticker not held anywhere → ``None``, no dialog
    * ticker matches case-insensitively (input "aapl" vs stored "AAPL")
    * positions with ``quantity == 0`` are ignored (sold-out positions)
    * single matching position → returned detached (no DetachedInstanceError)
    * multiple matching → user picks one in the QInputDialog
    * multiple matching → user cancels → ``None``
"""

from __future__ import annotations

import pytest

from database.models import Portfolio, Position, session_scope
from ui.paper import real_portfolio as rp


# ─── helpers ─────────────────────────────────────────────────────────────────


def _seed_portfolio(name: str, currency: str = "USD") -> int:
    """Insert a Portfolio and return its id."""
    with session_scope() as s:
        p = Portfolio(name=name, currency=currency)
        s.add(p)
        s.flush()
        return int(p.id)


def _seed_position(portfolio_id: int, ticker: str, qty: float, price: float) -> int:
    """Insert a Position and return its id."""
    with session_scope() as s:
        pos = Position(
            portfolio_id=portfolio_id,
            ticker=ticker,
            quantity=qty,
            avg_buy_price=price,
        )
        s.add(pos)
        s.flush()
        return int(pos.id)


@pytest.fixture
def captured_msgbox(monkeypatch):
    """
    Record any QMessageBox.information call as a tuple
    ``(parent, title, body)`` instead of actually showing it.
    """
    calls: list[tuple[object, str, str]] = []

    def fake_information(parent, title, body, *args, **kwargs):
        calls.append((parent, title, body))
        # The real return value is a StandardButton; tests don't care.
        return None

    monkeypatch.setattr(rp.QMessageBox, "information", fake_information)
    return calls


@pytest.fixture
def fake_input_dialog(monkeypatch):
    """
    Replace ``QInputDialog.getItem`` with a configurable stub.

    Two ways to drive it:
        # 1. Pick a known label by string
        fake_input_dialog.configure(choice="My PF", ok=True)

        # 2. Pick dynamically based on the items the dialog is offered
        fake_input_dialog.configure(picker=lambda items: items[1], ok=True)
    """

    class _Stub:
        def __init__(self) -> None:
            self.calls: list[dict] = []
            self._choice: str | None = None
            self._picker = None  # callable: items -> str
            self._ok: bool = False

        def configure(self, *, choice=None, picker=None, ok: bool) -> None:
            assert (choice is None) ^ (picker is None), (
                "configure() expects exactly one of `choice` or `picker`"
            )
            self._choice = choice
            self._picker = picker
            self._ok = ok

        def __call__(self, parent, title, label, items, current, editable, *a, **kw):
            items = list(items)
            self.calls.append(
                {
                    "parent": parent,
                    "title": title,
                    "label": label,
                    "items": items,
                    "current": current,
                    "editable": editable,
                }
            )
            chosen = self._picker(items) if self._picker is not None else (self._choice or "")
            return (chosen, self._ok)

    stub = _Stub()
    monkeypatch.setattr(rp.QInputDialog, "getItem", stub)
    return stub


# ─── pick_real_portfolio ─────────────────────────────────────────────────────


def test_pick_real_portfolio_empty_db_shows_message_and_returns_none(
    test_db, captured_msgbox, fake_input_dialog
):
    result = rp.pick_real_portfolio(parent=None)
    assert result is None
    # The "no portfolios" message should have been shown exactly once.
    assert len(captured_msgbox) == 1
    _parent, title, body = captured_msgbox[0]
    assert title == "Sin portafolios"
    assert "Portafolio" in body
    # And no chooser was opened, since there's nothing to choose from.
    assert fake_input_dialog.calls == []


def test_pick_real_portfolio_single_auto_resolves(
    test_db, captured_msgbox, fake_input_dialog
):
    pid = _seed_portfolio("Solo")
    result = rp.pick_real_portfolio(parent=None)
    assert result == pid
    # No dialog of either kind needed when there's exactly one option.
    assert captured_msgbox == []
    assert fake_input_dialog.calls == []


def test_pick_real_portfolio_multiple_user_picks(
    test_db, captured_msgbox, fake_input_dialog
):
    # Seeded out of alphabetical order to verify the helper sorts by name.
    pid_b = _seed_portfolio("Bravo")
    pid_a = _seed_portfolio("Alpha")
    pid_c = _seed_portfolio("Charlie")

    fake_input_dialog.configure(choice="Bravo", ok=True)
    result = rp.pick_real_portfolio(parent=None)

    assert result == pid_b
    assert pid_a != pid_b != pid_c  # sanity
    # Dialog was opened with names alphabetised.
    assert len(fake_input_dialog.calls) == 1
    assert fake_input_dialog.calls[0]["items"] == ["Alpha", "Bravo", "Charlie"]


def test_pick_real_portfolio_multiple_user_cancels(
    test_db, captured_msgbox, fake_input_dialog
):
    _seed_portfolio("Alpha")
    _seed_portfolio("Bravo")

    # Even with a "choice" set, ok=False simulates the user hitting Cancel.
    fake_input_dialog.configure(choice="Alpha", ok=False)
    result = rp.pick_real_portfolio(parent=None)

    assert result is None
    assert len(fake_input_dialog.calls) == 1


# ─── find_real_position ──────────────────────────────────────────────────────


def test_find_real_position_no_match_returns_none(
    test_db, captured_msgbox, fake_input_dialog
):
    pid = _seed_portfolio("PF")
    _seed_position(pid, "MSFT", qty=5, price=300)

    result = rp.find_real_position(parent=None, ticker="AAPL")

    assert result is None
    # No dialogs of any kind when there's nothing to choose between.
    assert fake_input_dialog.calls == []
    assert captured_msgbox == []


def test_find_real_position_case_insensitive(
    test_db, captured_msgbox, fake_input_dialog
):
    pid = _seed_portfolio("PF")
    _seed_position(pid, "AAPL", qty=10, price=150)

    # Lowercase input should still match the uppercase-stored ticker.
    result = rp.find_real_position(parent=None, ticker="aapl")

    assert result is not None
    assert result.ticker == "AAPL"
    assert fake_input_dialog.calls == []


def test_find_real_position_ignores_zero_quantity(
    test_db, captured_msgbox, fake_input_dialog
):
    """A position that's been fully sold off (qty=0) is not a match."""
    pid = _seed_portfolio("PF")
    _seed_position(pid, "AAPL", qty=0, price=150)

    result = rp.find_real_position(parent=None, ticker="AAPL")
    assert result is None


def test_find_real_position_single_returns_detached_position(
    test_db, captured_msgbox, fake_input_dialog
):
    """
    The returned Position must be usable after the helper returns — i.e.
    no DetachedInstanceError when we read attributes outside any session.
    """
    pid = _seed_portfolio("PF")
    _seed_position(pid, "TSLA", qty=4, price=900)

    result = rp.find_real_position(parent=None, ticker="TSLA")

    assert result is not None
    # Attribute access *outside* a session is the key contract here.
    assert result.ticker == "TSLA"
    assert result.quantity == 4
    assert result.avg_buy_price == 900
    assert result.portfolio_id == pid
    # And no dialog was needed for a single hit.
    assert fake_input_dialog.calls == []


def test_find_real_position_multiple_user_picks(
    test_db, captured_msgbox, fake_input_dialog
):
    pid_a = _seed_portfolio("Alpha")
    pid_b = _seed_portfolio("Bravo")
    _seed_position(pid_a, "AAPL", qty=10, price=150)
    _seed_position(pid_b, "AAPL", qty=20, price=160)

    # Labels look like "<portfolio>  ·  <qty> shares @ $<price>". Instead of
    # hard-coding the exact format, pick whichever item the dialog offers
    # for portfolio "Bravo" — keeps the test resilient to format tweaks.
    fake_input_dialog.configure(
        picker=lambda items: next(it for it in items if "Bravo" in it),
        ok=True,
    )
    result = rp.find_real_position(parent=None, ticker="AAPL")

    assert result is not None
    assert result.portfolio_id == pid_b
    assert result.quantity == 20  # came from Bravo, not Alpha
    # Sanity: dialog was offered two options.
    assert len(fake_input_dialog.calls) == 1
    assert len(fake_input_dialog.calls[0]["items"]) == 2


def test_find_real_position_multiple_user_cancels(
    test_db, captured_msgbox, fake_input_dialog
):
    pid_a = _seed_portfolio("Alpha")
    pid_b = _seed_portfolio("Bravo")
    _seed_position(pid_a, "AAPL", qty=10, price=150)
    _seed_position(pid_b, "AAPL", qty=20, price=160)

    fake_input_dialog.configure(choice="ignored", ok=False)
    result = rp.find_real_position(parent=None, ticker="AAPL")

    assert result is None
    assert len(fake_input_dialog.calls) == 1
