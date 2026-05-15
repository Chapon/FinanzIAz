"""
Paper-trading UI sub-components.

Originally everything lived inside ``ui/paper_tab.py`` as one ~1.4k line
module. We extracted the self-contained pieces (account dialog, equity-curve
chart widget, the prices worker) into individual files here so each can be
read, tested, and refactored independently. The orchestrator class
``PaperTradingTab`` continues to live in ``ui/paper_tab.py``.
"""

from ui.paper.account_dialog import PaperAccountDialog
from ui.paper.equity_chart import EquityCurveChart
from ui.paper.real_portfolio import find_real_position, pick_real_portfolio
from ui.paper.workers import PricesWorker

__all__ = [
    "EquityCurveChart",
    "PaperAccountDialog",
    "PricesWorker",
    "find_real_position",
    "pick_real_portfolio",
]
