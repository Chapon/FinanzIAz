"""
Background worker for the Analysis tab.

Migrated to ``BaseWorker`` so error/cancellation handling is consistent with
the rest of the UI.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal

from analysis.technical import analyze
from config.settings_manager import settings
from data.yahoo_finance import (
    get_analyst_data,
    get_company_info,
    get_current_price,
    get_historical_data,
)
from ui.workers import BaseWorker


class AnalysisWorker(BaseWorker):
    """
    Fetches OHLCV history + current price + company info + analyst recos for a
    ticker, then runs the full ``analyze`` pipeline. Emits
    ``done(df, result, price_data, company_info, analyst_data)`` on success.
    """

    # df, result, price_data, company_info, analyst_data
    done = pyqtSignal(object, object, object, object, object)

    def __init__(self, ticker: str, period: str):
        super().__init__()
        self.ticker = ticker
        self.period = period

    def do_work(self) -> tuple:
        df = get_historical_data(self.ticker, period=self.period)
        result = (
            analyze(
                self.ticker,
                df,
                enable_sma_cross=settings.get("sma_cross"),
                enable_xgboost=True,
            )
            if df is not None
            else None
        )
        price_data = get_current_price(self.ticker)
        company = get_company_info(self.ticker)
        analyst = get_analyst_data(self.ticker)
        return df, result, price_data, company, analyst

    def on_success(self, result: tuple) -> None:
        df, ar, price_data, company, analyst = result
        self.done.emit(df, ar, price_data, company, analyst)
