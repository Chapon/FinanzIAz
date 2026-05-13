"""
Centralized UI error handling.

Goals
-----
1. Convert exceptions raised inside slot callbacks into user-visible
   ``QMessageBox`` warnings instead of silently crashing the event loop.
2. Always log the full traceback so we have a forensic trail (file + stderr
   via ``config.logging_config``).
3. Be a drop-in decorator: most call-sites only need ``@handle_errors``.

Public API
----------
``handle_errors(*, parent=None, title="Error", reraise=False)``
    Decorator factory. Use on slots / signal handlers.

``connect_worker(worker, *, parent=None, title=None)``
    Wires a ``BaseWorker.error`` signal to a uniform ``QMessageBox``.

``show_error(parent, title, exc)``
    Imperative helper for ad-hoc error dialogs.

``install_global_excepthook()``
    Capture stray exceptions on the Python side (uncaught in slots) and
    surface them as ``QMessageBox`` instead of letting Qt swallow them or,
    on some platforms, abort the process.

Usage examples
--------------
    from ui.error_handler import handle_errors, connect_worker

    class FooTab(QWidget):
        @handle_errors(parent=None, title="No se pudo refrescar")
        def _on_refresh_clicked(self):
            do_potentially_failing_thing()

        def _start_worker(self):
            w = MyWorker(...)
            connect_worker(w, parent=self, title="Cálculo de señales")
            w.result_ready.connect(self._render)
            w.start()
"""

from __future__ import annotations

import functools
import sys
import traceback
from collections.abc import Callable
from typing import Any, TypeVar

from PyQt6.QtWidgets import QMessageBox, QWidget

from config.logging_config import get_logger

log = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def show_error(
    parent: QWidget | None,
    title: str,
    exc: BaseException,
    *,
    detail: str | None = None,
) -> None:
    """
    Display a user-facing error dialog and log the traceback.

    The dialog body uses the exception's str() (concise), and the traceback
    goes into the "Show Details…" panel so casual users aren't overwhelmed
    while developers can still see the stack.

    Domain-specific errors from ``config.errors`` get tailored titles:
    - ``ValidationError``: "Datos no válidos" + Information icon
    - ``NetworkError``: "Sin conexión" + Warning icon
    - everything else: the caller-provided ``title`` + Warning icon
    """
    msg = str(exc) or exc.__class__.__name__
    log.exception("UI error '%s': %s", title, msg, exc_info=exc)

    # Pick icon + title based on the exception class — without forcing the
    # caller to know the domain hierarchy.
    icon = QMessageBox.Icon.Warning
    effective_title = title
    try:
        from config.errors import NetworkError, ValidationError

        if isinstance(exc, ValidationError):
            icon = QMessageBox.Icon.Information
            effective_title = "Datos no válidos"
        elif isinstance(exc, NetworkError):
            icon = QMessageBox.Icon.Warning
            effective_title = "Sin conexión"
    except Exception:
        pass

    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(effective_title)
    box.setText(msg)
    if detail:
        box.setInformativeText(detail)
    tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    box.setDetailedText(tb_str)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def handle_errors(
    *,
    parent: QWidget | None = None,
    title: str = "Error",
    reraise: bool = False,
    detail: str | None = None,
) -> Callable[[F], F]:
    """
    Decorator: catch any exception in the wrapped slot, log it, show a
    QMessageBox, and (by default) swallow it so the Qt event loop survives.

    Set ``reraise=True`` if you specifically need the exception to propagate
    (e.g. inside a wrapper that already has its own dialog handling).

    ``parent`` can be ``None`` here and resolved at call time when the slot
    is a bound method on a QWidget — the decorator falls back to ``self``
    automatically in that case.
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                effective_parent = parent
                if effective_parent is None and args and isinstance(args[0], QWidget):
                    effective_parent = args[0]
                show_error(effective_parent, title, exc, detail=detail)
                if reraise:
                    raise
                return None

        return wrapper  # type: ignore[return-value]

    return decorator


def connect_worker(
    worker,
    *,
    parent: QWidget | None = None,
    title: str | None = None,
) -> None:
    """
    Hook a ``BaseWorker.error`` signal to a standard QMessageBox.

    Workers built on ``ui.workers.BaseWorker`` emit ``error(Exception)``
    on any failure inside ``do_work()``; this helper just wires that
    pipeline so each tab doesn't need to re-implement it.
    """
    if not hasattr(worker, "error"):
        return
    effective_title = title or f"Fallo en {type(worker).__name__}"

    def _on_error(exc: BaseException) -> None:
        show_error(parent, effective_title, exc)

    worker.error.connect(_on_error)


def install_global_excepthook() -> None:
    """
    Replace ``sys.excepthook`` so uncaught exceptions on the main thread
    surface as a dialog instead of being printed to a hidden terminal.

    Idempotent — safe to call once at app start. Only handles main-thread
    failures; QThread workers should still use the BaseWorker error signal.
    """
    original = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        # KeyboardInterrupt should still terminate the app cleanly.
        if issubclass(exc_type, KeyboardInterrupt):
            original(exc_type, exc_value, exc_tb)
            return
        log.critical(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_tb),
        )
        try:
            show_error(None, "Error inesperado", exc_value)
        except Exception:
            # Last-ditch fallback — never crash inside the excepthook.
            original(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
