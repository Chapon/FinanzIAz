"""
FinanzIAs — Investment Portfolio Tracker
Entry point.

Usage:
    python main.py

Requirements:
    pip install -r requirements.txt
"""
import sys
import os

# Ensure the project root is on the Python path
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config.logging_config import setup_logging, get_logger
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
    from PyQt6.QtGui import QIcon
    from ui.main_window import MainWindow
    from ui.error_handler import install_global_excepthook

    app = QApplication(sys.argv)
    app.setApplicationName("FinanzIAs")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("FinanzIAs")

    # Surface uncaught exceptions as QMessageBox + log instead of silent crash.
    install_global_excepthook()

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
