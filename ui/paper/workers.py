"""
Background worker(s) used by the paper-trading tab.

Migrated to the shared ``BaseWorker`` so error handling, cancellation, and
logging are consistent with the rest of the UI.
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal

from data.yahoo_finance import get_bulk_prices
from ui.workers import BaseWorker


class PricesWorker(BaseWorker):
    """Fetch current prices for a list of tickers without blocking the UI."""

    prices_ready = pyqtSignal(dict)   # {ticker: price}

    def __init__(self, tickers: list[str]):
        super().__init__()
        self._tickers = [t for t in tickers if t]

    def do_work(self) -> dict[str, float]:
        if not self._tickers:
            return {}
        out = get_bulk_prices(self._tickers)
        prices: dict[str, float] = {}
        for ticker, info in (out or {}).items():
            if isinstance(info, dict):
                px = info.get("price")
            else:
                px = info
            if px is None:
                continue
            try:
                prices[ticker] = float(px)
            except (TypeError, ValueError):
                continue
        return prices

    def on_success(self, result: dict[str, float]) -> None:
        self.prices_ready.emit(result)
