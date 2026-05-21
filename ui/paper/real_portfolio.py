"""
Helpers for crossing from a paper-trading order into the user's *real*
portfolio. Two interactive lookups:

- ``pick_real_portfolio(parent)`` — choose which real Portfolio to record a
  new BUY against (auto-resolves when there's only one).
- ``find_real_position(parent, ticker)`` — locate the open Position to SELL
  against for the given ticker, asking the user when the ticker exists in
  more than one portfolio.

Both functions live here (instead of inside ``PaperTradingTab``) because
they have **no shared state** with the rest of the tab — they only consult
the database, optionally show a QInputDialog, and return a value. Pulling
them out keeps the orchestrator file readable and lets us test them in
isolation.

Notes
-----
- DB access is wrapped in ``session_scope`` so we never hold a session
  while the modal QInputDialog is open (Qt's event loop must not pump
  events while a SQLAlchemy session is alive).
- The returned ``Position`` is detached via ``session.expunge`` so the
  caller can read attributes after the session closes without a
  ``DetachedInstanceError``.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QInputDialog, QMessageBox, QWidget

from database.models import Portfolio, Position, session_scope


def pick_real_portfolio(parent: QWidget) -> int | None:
    """
    Return the id of a real portfolio, or ``None`` if the user cancelled
    or no portfolios exist. When more than one exists, pop a chooser.

    ``parent`` is the QWidget that owns the QInputDialog (typically the
    paper-trading tab itself).
    """
    with session_scope() as session:
        portfolios = session.query(Portfolio).order_by(Portfolio.name.asc()).all()
        if not portfolios:
            QMessageBox.information(
                parent,
                "Sin portafolios",
                "No tenés portafolios reales todavía. Creá uno desde la "
                "pestaña Portafolio antes de registrar operaciones.",
            )
            return None
        if len(portfolios) == 1:
            return int(portfolios[0].id)
        names = [p.name for p in portfolios]
        ids = [int(p.id) for p in portfolios]

    # Open the dialog AFTER the session is closed — Qt's event loop must
    # not pump events while a DB session is held open.
    choice, ok = QInputDialog.getItem(
        parent,
        "Elegir portafolio",
        "¿En qué portafolio real querés registrar la compra?",
        names,
        0,
        False,
    )
    if not ok:
        return None
    try:
        return ids[names.index(choice)]
    except ValueError:
        return None


def find_real_position(parent: QWidget, ticker: str) -> Position | None:
    """
    Find the most relevant open Position for ``ticker`` across real
    portfolios. If multiple portfolios hold the same ticker, let the
    user pick which one to use.

    Returns a detached ``Position`` instance, or ``None`` if the user
    cancelled or no portfolio holds the ticker.
    """
    with session_scope() as session:
        rows = (
            session.query(Position, Portfolio)
            .join(Portfolio, Position.portfolio_id == Portfolio.id)
            .filter(Position.ticker == ticker.upper())
            .filter(Position.quantity > 0)
            .all()
        )
        if not rows:
            return None
        if len(rows) == 1:
            pos, _pf = rows[0]
            session.expunge(pos)
            return pos
        labels = [f"{pf.name}  ·  {pos.quantity:g} shares @ ${pos.avg_buy_price:,.2f}" for pos, pf in rows]
        position_objs = [pos for pos, _pf in rows]
        session.expunge_all()

    # Dialog runs outside the DB session.
    choice, ok = QInputDialog.getItem(
        parent,
        "Elegir portafolio",
        f"Hay {len(rows)} portafolios con {ticker}. ¿Cuál usás?",
        labels,
        0,
        False,
    )
    if not ok:
        return None
    try:
        return position_objs[labels.index(choice)]
    except ValueError:
        return None
