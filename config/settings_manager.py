"""
Persistent app settings backed by ~/.finanzias/settings.json.
Import anywhere with: from config.settings_manager import settings

Schema validation
-----------------
Every key has a ``SettingSpec`` describing its expected type, optional value
range / allowed list, and short doc. ``load()`` validates each key against
its spec and silently falls back to the default when a value fails (typo'd
JSON, hand-edits, schema migrations…). ``set()`` validates writes too —
invalid values are rejected with a logged warning and the previous value is
kept, so the app never crashes on bad config.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Use plain ``logging`` instead of get_logger() to avoid an import cycle:
# logging_config imports from this module to read user log-level overrides.
_log = logging.getLogger(__name__)


# ── Schema spec ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SettingSpec:
    """
    Schema entry for a single settings key.

    type         — expected Python type (or tuple of types).
    default      — value used when missing / invalid.
    choices      — optional iterable of allowed values; if set, value must be in it.
    min          — optional inclusive lower bound for numeric values.
    max          — optional inclusive upper bound for numeric values.
    validator    — optional callable returning True iff the value is acceptable.
    doc          — short human description.
    """

    type: Any
    default: Any
    choices: tuple | None = None
    min: float | None = None
    max: float | None = None
    validator: Callable[[Any], bool] | None = None
    doc: str = ""


def _is_hhmm(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return False
    try:
        h = int(value[:2])
        m = int(value[3:])
    except ValueError:
        return False
    return 0 <= h <= 23 and 0 <= m <= 59


# ── Schema (single source of truth — defaults derived from this) ─────────────

SCHEMA: dict[str, SettingSpec] = {
    # General
    "notif": SettingSpec(bool, True, doc="Show notifications when alerts fire"),
    "auto_refresh": SettingSpec(bool, True, doc="Refresh portfolio prices every 60 s"),
    "default_home": SettingSpec(bool, True, doc="Open Home tab on startup (False → Portfolio)"),
    "confirm_sell": SettingSpec(bool, True, doc="Show extra confirmation before selling"),
    # Market data
    "cache": SettingSpec(bool, True, doc="Use 5-min price cache (disable for real-time)"),
    "pre_market": SettingSpec(bool, False, doc="Show pre/post-market label in status bar"),
    "perf_log": SettingSpec(bool, True, doc="Save P&L history"),
    # Technical analysis
    "bb": SettingSpec(bool, True, doc="Show Bollinger Bands on chart"),
    "sma_cross": SettingSpec(bool, True, doc="Include Golden/Death Cross signal in analysis"),
    "rsi_alerts": SettingSpec(bool, False, doc="Scan portfolio for extreme RSI on toggle-on"),
    # Reports
    "tx_history": SettingSpec(bool, True, doc="Include transaction history in reports"),
    "pdf_dark": SettingSpec(bool, True, doc="Use dark theme in PDF reports"),
    # Paper trading scheduler
    "paper_scheduler_enabled": SettingSpec(bool, True, doc="Master switch for the scheduler"),
    "paper_scan_interval_minutes": SettingSpec(
        int, 15, min=1, max=1440, doc="Background QTimer interval (minutes)"
    ),
    "paper_daily_scan_enabled": SettingSpec(bool, True, doc="Cron-style end-of-day scan"),
    "paper_daily_scan_time_et": SettingSpec(str, "16:05", validator=_is_hhmm, doc="HH:MM in US/Eastern"),
    "paper_scan_on_startup": SettingSpec(bool, True, doc="Scan all active accounts at app launch"),
    "paper_market_hours_only": SettingSpec(bool, True, doc="Interval ticks skip outside RTH"),
    # Paper trading guardrails (lite-pro execution gates)
    "paper_enforce_market_hours": SettingSpec(bool, True, doc="Engine refuses to fill when market is closed"),
    "paper_min_holding_minutes": SettingSpec(
        int, 60, min=0, max=10_080, doc="Cannot SELL a position opened within last N min"
    ),
    "paper_anti_flap_minutes": SettingSpec(
        int, 30, min=0, max=10_080, doc="Cannot BUY a ticker we filled-SELL on within last N min"
    ),
    "paper_min_trade_dollars": SettingSpec(
        (int, float), 50.0, min=0.0, doc="Skip BUYs whose target_dollars is below this"
    ),
    "paper_whipsaw_lookback_days": SettingSpec(
        int,
        7,
        min=0,
        max=90,
        doc=(
            "Block re-BUY of a ticker whose last closed cycle ended with a loss "
            "within the last N days. 0 = disable the gate."
        ),
    ),
    "paper_whipsaw_min_loss_pct": SettingSpec(
        (int, float),
        0.0,
        min=0.0,
        max=100.0,
        doc=(
            "Only block when the closed-cycle loss is worse than -X percent. "
            "Default 0.0 = block any loss within the lookback window."
        ),
    ),
    # ATR-based stops (T01 of the engine roadmap)
    # Disabled by default — turn on explicitly with `atr_stops_enabled=True`.
    "atr_stops_enabled": SettingSpec(
        bool,
        False,
        doc=(
            "Master switch for the ATR stop gate. When True, the engine "
            "evaluates each open position against stop-loss / take-profit / "
            "trailing-stop levels sized in ATR units BEFORE running the "
            "strategy, and injects forced SELL trades if any trigger fires."
        ),
    ),
    "atr_period": SettingSpec(
        int,
        14,
        min=2,
        max=200,
        doc="Lookback in bars for the Wilder-smoothed ATR (default 14).",
    ),
    "atr_stop_mult": SettingSpec(
        (int, float),
        2.0,
        min=0.1,
        max=20.0,
        doc=(
            "Stop-loss distance from entry, in ATR units. SELL fires when "
            "price ≤ avg_cost − atr_stop_mult × ATR."
        ),
    ),
    "atr_tp_mult": SettingSpec(
        (int, float),
        4.0,
        min=0.1,
        max=50.0,
        doc=(
            "Take-profit distance from entry, in ATR units. SELL fires when "
            "price ≥ avg_cost + atr_tp_mult × ATR."
        ),
    ),
    "atr_trail_enabled": SettingSpec(
        bool,
        True,
        doc=(
            "Sub-switch for the trailing variant (only meaningful when "
            "`atr_stops_enabled=True`). SELL fires when "
            "price ≤ high_water_mark_since_entry − atr_stop_mult × ATR."
        ),
    ),
    # Paper trading analysis tuning
    "paper_history_period": SettingSpec(
        str,
        "2y",
        choices=("6mo", "1y", "2y", "5y", "10y"),
        doc="Window the scanner passes to analyze()/XGBoost",
    ),
    # Broker commission plan (IBKR Pro). "legacy" falls back to per-account
    # PaperAccount.commission (the historical % rate field), preserving
    # back-compat for accounts/tests that haven't been migrated yet.
    "ibkr_commission_plan": SettingSpec(
        str,
        "tiered",
        choices=("tiered", "fixed", "legacy"),
        doc=(
            "IBKR Pro commission plan applied to new paper-trading fills. "
            "tiered = $0.0035/share + exchange + reg fees; "
            "fixed = $0.0050/share (exchange bundled) + reg fees; "
            "legacy = use PaperAccount.commission as a flat %."
        ),
    ),
    # Logging overrides (free-form: dict[str, str])
    "logging_levels": SettingSpec(dict, {}, doc="Per-module logging overrides {name: LEVEL}"),
}

# DEFAULTS dict mirrors SCHEMA — kept for backward compatibility with code
# that imported it directly (e.g. ``from config.settings_manager import DEFAULTS``).
DEFAULTS: dict[str, Any] = {key: spec.default for key, spec in SCHEMA.items()}

_CONFIG_PATH = Path.home() / ".finanzias" / "settings.json"


def _validate_value(key: str, value: Any) -> tuple[bool, str]:
    """
    Validate ``value`` against ``SCHEMA[key]``. Returns (is_valid, reason).
    Unknown keys are accepted (forward-compat for hand-added settings).
    """
    spec = SCHEMA.get(key)
    if spec is None:
        return True, ""

    # bool is a subclass of int — guard against True being accepted where int expected
    if spec.type is int and isinstance(value, bool):
        return False, "expected int, got bool"
    if spec.type is bool and not isinstance(value, bool):
        return False, "expected bool"

    if not isinstance(value, spec.type):
        return False, f"expected {spec.type}, got {type(value).__name__}"

    if spec.choices is not None and value not in spec.choices:
        return False, f"value {value!r} not in choices {spec.choices}"

    if spec.min is not None and value < spec.min:
        return False, f"value {value} below min {spec.min}"
    if spec.max is not None and value > spec.max:
        return False, f"value {value} above max {spec.max}"

    if spec.validator is not None and not spec.validator(value):
        return False, "custom validator rejected the value"

    return True, ""


class _SettingsManager:
    """Singleton-like settings manager. Access via module-level `settings`."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self.load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def load(self) -> dict:
        """
        Read and validate ``settings.json`` against ``SCHEMA``. Invalid values
        and unparseable files fall back to defaults; the app never crashes on
        bad config. Triggers a re-save when invalid values were found, so the
        bad data gets pruned from disk on startup.
        """
        validated: dict[str, Any] = dict(DEFAULTS)
        had_invalid = False
        try:
            if _CONFIG_PATH.exists():
                with open(_CONFIG_PATH, encoding="utf-8") as f:
                    stored = json.load(f)
                if not isinstance(stored, dict):
                    raise ValueError(f"settings.json root is {type(stored).__name__}, expected dict")

                for key, value in stored.items():
                    ok, reason = _validate_value(key, value)
                    if ok:
                        validated[key] = value
                    else:
                        had_invalid = True
                        _log.warning("settings: discarding %r=%r — %s", key, value, reason)
        except Exception:
            _log.exception("Settings load failed; falling back to defaults")
            had_invalid = True

        self._data = validated
        if had_invalid:
            self.save()
        return dict(self._data)

    def save(self) -> None:
        try:
            _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception:
            _log.exception("Settings save failed")

    # ── Access ────────────────────────────────────────────────────────────────

    def get(self, key: str, fallback: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, fallback))

    def set(self, key: str, value: Any) -> bool:
        """
        Set a setting with validation. Returns True on success, False on
        invalid value (in which case the existing value is preserved).
        """
        ok, reason = _validate_value(key, value)
        if not ok:
            _log.warning("settings.set(%r, %r) rejected: %s", key, value, reason)
            return False
        self._data[key] = value
        self.save()
        return True

    def reset(self) -> dict:
        self._data = dict(DEFAULTS)
        self.save()
        return dict(self._data)

    def all(self) -> dict:
        return dict(self._data)

    # Allow dict-style access
    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        # Dict-style write keeps backward compatibility — invalid values are
        # silently dropped (with a log warning) rather than raising, so legacy
        # call-sites never break.
        self.set(key, value)


# Module-level singleton — import this everywhere.
settings = _SettingsManager()
