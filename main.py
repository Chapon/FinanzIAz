"""
FinanzIAs — Investment Portfolio Tracker
Entry point.

Usage:
    python main.py

Requirements:
    pip install -r requirements.txt
"""

import os

# Silence the benign KMeans/MKL memory-leak warning on Windows. Must be set
# BEFORE numpy/scikit-learn (and thus MKL) are imported anywhere, so it lives
# at the very top of the entry point.
os.environ.setdefault("OMP_NUM_THREADS", "2")

import sys

# Ensure the project root is on the Python path
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config.logging_config import get_logger, setup_logging
from database.models import init_db


def main():
    # Set up centralized logging (rotating file + stderr) BEFORE any other
    # subsystem imports, so module-level loggers all attach correctly.
    setup_logging()
    log = get_logger(__name__)
    log.info("Iniciando FinanzIAs")

    # Initialize DB (creates tables + default portfolio if needed)
    init_db()

    # Daily snapshot (no-op if today's already exists). Best-effort — never
    # blocks startup; failures are logged.
    try:
        from database.backup import maybe_rotate_daily

        maybe_rotate_daily(keep=7)
    except Exception:
        log.exception("Daily backup rotation failed")

    # Import Qt after path is set up
    from PyQt6.QtWidgets import QApplication

    from ui.error_handler import install_global_excepthook
    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("FinanzIAs")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("FinanzIAs")

    # Surface uncaught exceptions as QMessageBox + log instead of silent crash.
    install_global_excepthook()

    window = MainWindow()
    window.show()

    code = app.exec()

    # Los fetch de tooltip corren run-and-forget en el QThreadPool global. Cerrar
    # con uno en vuelo mata el proceso (medido: exit 127, 3 de 3 — tarea 82), así
    # que se drenan acá, después del event loop y antes de salir. Fail-open: un
    # problema drenando no puede cambiar el código de salida de la app.
    try:
        from ui.ticker_tooltip import shutdown as _tooltip_shutdown

        _tooltip_shutdown()
    except Exception:
        log.exception("Tooltip shutdown failed")

    sys.exit(code)


if __name__ == "__main__":
    main()
