"""
Analysis-tab UI sub-components.

Originally everything lived inside ``ui/analysis_tab.py`` as one ~1.3k line
module. We extracted the catalog/labels/tooltip data, the background
worker, and the per-indicator signal card into their own files so each
piece can be read, tested, and edited independently. The orchestrator
class ``AnalysisTab`` continues to live in ``ui/analysis_tab.py``.
"""

from ui.analysis.catalog import COMPLETION_LIST, PERIODS, TICKER_DB
from ui.analysis.labels import (
    TOOLTIPS,
    YAHOO_COLORS,
    YAHOO_LABELS_ES,
    get_tooltip,
)
from ui.analysis.signal_card import SignalCard
from ui.analysis.worker import AnalysisWorker

__all__ = [
    "COMPLETION_LIST",
    "PERIODS",
    "TICKER_DB",
    "TOOLTIPS",
    "YAHOO_COLORS",
    "YAHOO_LABELS_ES",
    "AnalysisWorker",
    "SignalCard",
    "get_tooltip",
]
