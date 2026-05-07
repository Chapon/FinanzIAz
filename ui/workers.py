"""
Reusable PyQt worker base class.

Existing workers in the codebase (PriceWorker, DividendWorker, SignalWorker,
RsiScanWorker, ReportWorker, AnalysisWorker, …) all follow the same pattern:

  class FooWorker(QThread):
      result_ready = pyqtSignal(...)
      def __init__(self, args): ...
      def run(self): ... emit ...

…with each one re-implementing exception handling, cancellation, and
optional logging slightly differently. ``BaseWorker`` consolidates that.

Usage
-----
    from ui.workers import BaseWorker

    class MyWorker(BaseWorker):
        result_ready = pyqtSignal(dict)

        def __init__(self, tickers):
            super().__init__()
            self.tickers = tickers

        def do_work(self):
            return get_bulk_prices(self.tickers)   # raises ⇒ error signal

        def on_success(self, result):
            self.result_ready.emit(result)

Behaviour
---------
- ``do_work()`` is the only required override. Anything it returns is passed
  to ``on_success(result)`` (default no-op — subclasses emit their own
  typed signal there).
- Exceptions raised inside ``do_work()`` are caught: logged with stack
  trace, then re-broadcast via the ``error`` signal so the UI can display
  a message box / banner without each worker re-implementing try/except.
- ``cancel()`` flips ``is_cancelled()`` so long-running ``do_work`` loops
  can opt-in to early termination by polling it.
- ``started`` / ``finished`` are emitted around every run so callers can
  show / hide spinners centrally.
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from config.logging_config import get_logger

log = get_logger(__name__)


class BaseWorker(QThread):
    """
    Common base class for QThread-based workers.

    Signals
    -------
    started      — emitted just before ``do_work()`` runs.
    finished     — emitted exactly once, after success or failure.
    error        — emitted on any exception in ``do_work()`` with (Exception).
    progress     — generic (int, str) for "65%" style updates if subclass uses it.
    """

    error    = pyqtSignal(object)         # Exception
    progress = pyqtSignal(int, str)       # 0-100, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancelled: bool = False

    # ── Cancellation ──────────────────────────────────────────────────────────
    def cancel(self) -> None:
        """Request cooperative cancellation. ``do_work`` must poll ``is_cancelled``."""
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    # ── Subclass interface ────────────────────────────────────────────────────
    def do_work(self) -> Any:
        """Override this. Return any object; raise on failure."""
        raise NotImplementedError("Subclasses must implement do_work()")

    def on_success(self, result: Any) -> None:
        """
        Called after ``do_work()`` returns. Default is a no-op so subclasses
        that emit their own typed result signals can override and pick the
        shape they want.
        """
        return None

    # ── Run loop ──────────────────────────────────────────────────────────────
    def run(self) -> None:
        cls_name = type(self).__name__
        try:
            log.debug("%s: starting", cls_name)
            result = self.do_work()
        except Exception as exc:
            log.exception("%s: error in do_work()", cls_name)
            try:
                self.error.emit(exc)
            except Exception:
                # Defensive: we never want a signal-emit failure to crash a thread.
                log.exception("%s: failed to emit error signal", cls_name)
            return
        try:
            self.on_success(result)
        except Exception:
            log.exception("%s: error in on_success()", cls_name)
        finally:
            log.debug("%s: finished", cls_name)
