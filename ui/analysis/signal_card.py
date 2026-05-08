"""
Single-indicator signal card used in the Analysis tab right panel.

Displays a TechnicalSignal as a labelled card with a Yahoo-Finance-style
SignalBadge and the indicator's description text. The card pulls its
HTML tooltip from ``ui.analysis.labels.get_tooltip``.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from analysis.technical import to_yahoo_level
from ui.analysis.labels import get_tooltip
from ui.widgets import SignalBadge


class SignalCard(QFrame):
    """Displays a single TechnicalSignal using Yahoo Finance's 5-level system."""

    def __init__(self, signal, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        tt = get_tooltip(signal.indicator)
        if tt:
            self.setToolTip(tt)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        top = QHBoxLayout()
        ind_label = QLabel(signal.indicator)
        ind_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        top.addWidget(ind_label)
        top.addStretch()
        yahoo_level = to_yahoo_level(signal.signal, signal.strength)
        top.addWidget(SignalBadge(yahoo_level))
        layout.addLayout(top)

        desc = QLabel(signal.description)
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 12px;")
        layout.addWidget(desc)
