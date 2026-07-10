"""
Alert manager: checks price alerts and fires callbacks when triggered.
"""

from collections.abc import Callable

from data.yahoo_finance import get_current_price
from database.models import Alert, session_scope, utcnow_naive
from integrations.slack import AlertNotice, default_notifier, format_alert_message


class AlertManager:
    def __init__(
        self,
        on_triggered: Callable | None = None,
        notifier: Callable[[str], bool] | None = None,
    ):
        """
        on_triggered: callback(alert: Alert, current_price: float) called when
            an alert fires (the GUI uses it to pop a QMessageBox).
        notifier: callable(text) -> bool that delivers a *batched* Slack message
            for every alert triggered in one ``check_alerts`` pass. Defaults to
            ``integrations.slack.default_notifier`` (real Slack, fail-open).
            Tests inject a recording mock (same pattern as the engine's
            ``prices_provider`` / ``slack_notifier``).
        """
        self.on_triggered = on_triggered
        self._notifier = notifier

    def check_alerts(self, portfolio_id: int | None = None) -> list[Alert]:
        """
        Check all active alerts (optionally filtered by portfolio).
        Returns list of triggered alerts.
        """
        triggered: list[Alert] = []
        notices: list[AlertNotice] = []
        with session_scope() as session:
            query = session.query(Alert).filter(Alert.is_active.is_(True))
            if portfolio_id is not None:
                query = query.filter(Alert.portfolio_id == portfolio_id)
            alerts = query.all()

            # Group by ticker to minimize API calls
            tickers = list({a.ticker for a in alerts})
            prices: dict[str, float] = {}
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
                    alert.triggered_at = utcnow_naive()
                    triggered.append(alert)
                    # Snapshot to plain values while the ORM is still attached;
                    # the ORM detaches on session close and the Slack POST runs
                    # after commit (see _notify_slack).
                    notices.append(
                        AlertNotice(
                            ticker=alert.ticker,
                            alert_type=alert.alert_type,
                            target_value=alert.target_value,
                            current_price=price,
                            message=alert.message or "",
                        )
                    )
                    if self.on_triggered:
                        self.on_triggered(alert, price)
            # commit happens automatically on context exit

        # POST to Slack *after* the commit: a network failure must never revert
        # the is_active=False / triggered_at marking (fail-open, backlog NOTIF1).
        self._notify_slack(notices)
        return triggered

    def _notify_slack(self, notices: list[AlertNotice]) -> None:
        """Send one batched Slack message for the alerts fired in this check.

        Fully fail-open: gated by ``slack_price_alerts_enabled`` (default True →
        no-op without a token/channel), and a delivery error is swallowed with a
        warning so it never escapes into ``check_alerts``.
        """
        if not notices:
            return
        from config.settings_manager import settings

        if not settings.get("slack_price_alerts_enabled", True):
            return
        text = format_alert_message(notices)
        if not text:
            return
        notifier = self._notifier or default_notifier
        try:
            notifier(text)
        except Exception:
            from config.logging_config import get_logger

            get_logger(__name__).warning(
                "Slack price-alert notify failed (fail-open, DB marking unaffected).",
                exc_info=True,
            )

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
        with session_scope() as session:
            alert = Alert(
                portfolio_id=portfolio_id,
                ticker=ticker.upper(),
                alert_type=alert_type,
                target_value=target_value,
                message=message,
                is_active=True,
            )
            session.add(alert)
            session.flush()  # populate alert.id before commit/expunge
            session.refresh(alert)
            session.expunge(alert)  # detach so caller can use after close
            return alert

    @staticmethod
    def delete_alert(alert_id: int) -> None:
        with session_scope() as session:
            alert = session.query(Alert).filter(Alert.id == alert_id).first()
            if alert:
                session.delete(alert)

    @staticmethod
    def get_alerts(portfolio_id: int | None = None, active_only: bool = False) -> list[Alert]:
        with session_scope() as session:
            query = session.query(Alert)
            if portfolio_id is not None:
                query = query.filter(Alert.portfolio_id == portfolio_id)
            if active_only:
                query = query.filter(Alert.is_active.is_(True))
            alerts = query.order_by(Alert.created_at.desc()).all()
            # Detach from session so they can be used after close
            session.expunge_all()
            return alerts
