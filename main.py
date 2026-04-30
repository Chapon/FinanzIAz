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

from database.models import init_db

def main():
    # Initialize DB (creates tables + default portfolio if needed)
    init_db()

    # Import Qt after path is set up
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon
    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("FinanzIAs")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("FinanzIAs")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
