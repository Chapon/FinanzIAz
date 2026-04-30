"""
Persistent app settings backed by ~/.finanzias/settings.json.
Import anywhere with: from config.settings_manager import settings
"""
import json
from pathlib import Path

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULTS: dict = {
    # General
    "notif":        True,   # show notifications when alerts fire
    "auto_refresh": True,   # refresh portfolio prices every 60 s
    "default_home": True,   # open Home tab on startup (False → Portfolio)
    "confirm_sell": True,   # show extra confirmation before selling

    # Market data
    "cache":        True,   # use 5-min price cache (disable for real-time)
    "pre_market":   False,  # show pre/post-market label in status bar
    "perf_log":     True,   # save P&L history (future feature)

    # Technical analysis
    "bb":           True,   # show Bollinger Bands on chart
    "sma_cross":    True,   # include Golden/Death Cross signal in analysis
    "rsi_alerts":   False,  # scan portfolio for extreme RSI on toggle-on

    # Reports
    "tx_history":   True,   # include transaction history in reports
    "pdf_dark":     True,   # use dark theme in PDF reports

    # Paper trading scheduler
    "paper_scheduler_enabled":     True,   # master switch for the scheduler
    "paper_scan_interval_minutes": 15,     # background QTimer interval
    "paper_daily_scan_enabled":    True,   # cron-style end-of-day scan
    "paper_daily_scan_time_et":    "16:05",# HH:MM in US/Eastern (~5 min after NYSE close)
    "paper_scan_on_startup":       True,   # scan all active accounts at app launch
    "paper_market_hours_only":     True,   # interval ticks skip outside RTH
}

_CONFIG_PATH = Path.home() / ".finanzias" / "settings.json"


class _SettingsManager:
    """Singleton-like settings manager. Access via module-level `settings`."""

    def __init__(self):
        self._data: dict = {}
        self.load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def load(self) -> dict:
        try:
            if _CONFIG_PATH.exists():
                with open(_CONFIG_PATH, encoding="utf-8") as f:
                    stored = json.load(f)
                self._data = {**DEFAULTS, **stored}
            else:
                self._data = dict(DEFAULTS)
        except Exception as e:
            print(f"[Settings] Load error: {e}")
            self._data = dict(DEFAULTS)
        return dict(self._data)

    def save(self) -> None:
        try:
            _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Settings] Save error: {e}")

    # ── Access ────────────────────────────────────────────────────────────────

    def get(self, key: str, fallback=None):
        return self._data.get(key, DEFAULTS.get(key, fallback))

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self.save()

    def reset(self) -> dict:
        self._data = dict(DEFAULTS)
        self.save()
        return dict(self._data)

    def all(self) -> dict:
        return dict(self._data)

    # Allow dict-style access
    def __getitem__(self, key):
        return self.get(key)

    def __setitem__(self, key, value):
        self.set(key, value)


# Module-level singleton — import this everywhere
settings = _SettingsManager()
