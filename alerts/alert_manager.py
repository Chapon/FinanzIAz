"""
Alert manager: checks price alerts and fires callbacks when triggered.
"""
from datetime import datetime
from typing import Callable, Optional
from database.models import get_session, Alert
from data.yahoo_finance import get_current_price


class AlertManager:
    def __init__(self, on_triggered: Optional[Callable] = None):
        """
        on_triggered: callback(alert: Alert, current_price: float) called when alert fires.
        """
        self.on_triggered = on_triggered

    def check_alerts(self, portfolio_id: Optional[int] = None) -> list[Alert]:
        """
        Check all active alerts (optionally filtered by portfolio).
        Returns list of triggered alerts.
        """
        session = get_session()
        triggered = []
        try:
            query = session.query(Alert).filter(Alert.is_active == True)
            if portfolio_id is not None:
                query = query.filter(Alert.portfolio_id == portfolio_id)
            alerts = query.all()

            # Group by ticker to minimize API calls
            tickers = list(set(a.ticker for a in alerts))
            prices = {}
            for ticker in tickers:
                data = get_current_price(ticker)
                if data:
                    prices[ticker] = data["price"]

            for alert in alerts:
                price = prices.get(alert.ticker)
                if price is None:
                    continue
                if self._is_triggered(alert, price):
                    alert.is_active = False
                    alert.triggered_at = datetime.utcnow()
                    triggered.append(alert)
                    if self.on_triggered:
                        self.on_triggered(alert, price)

            session.commit()
        finally:
            session.close()

        return triggered

    @staticmethod
    def _is_triggered(alert: Alert, current_price: float) -> bool:
        if alert.alert_type == "ABOVE":
            return current_price >= alert.target_value
        elif alert.alert_type == "BELOW":
            return current_price <= alert.target_value
        return False

    @staticmethod
    def create_alert(
        portfolio_id: int,
        ticker: str,
        alert_type: str,
        target_value: float,
        message: str = "",
    ) -> Alert:
        """Create and persist a new price alert."""
        session = get_session()
        try:
            alert = Alert(
                portfolio_id=portfolio_id,
                ticker=ticker.upper(),
                alert_type=alert_type,
                target_value=target_value,
                message=message,
                is_active=True,
            )
            session.add(alert)
            session.commit()
            session.refresh(alert)
            return alert
        finally:
            session.close()

    @staticmethod
    def delete_alert(alert_id: int):
        session = get_session()
        try:
            alert = session.query(Alert).filter(Alert.id == alert_id).first()
            if alert:
                session.delete(alert)
                session.commit()
        finally:
            session.close()

    @staticmethod
    def get_alerts(portfolio_id: Optional[int] = None, active_only: bool = False) -> list[Alert]:
        session = get_session()
        try:
            query = session.query(Alert)
            if portfolio_id is not None:
                query = query.filter(Alert.portfolio_id == portfolio_id)
            if active_only:
                query = query.filter(Alert.is_active == True)
            alerts = query.order_by(Alert.created_at.desc()).all()
            # Detach from session so they can be used after close
            session.expunge_all()
            return alerts
        finally:
            session.close()
