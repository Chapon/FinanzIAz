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
    # T6.4 score-hysteresis (validado en T6.1, docs/exit_replay_t61_2026-06-10.md):
    # los SELLs por señal a 1-3 días regalan el rally del horizonte 5d del label.
    "paper_signal_sell_min_age_bdays": SettingSpec(
        int, 3, min=0, max=30,
        doc=(
            "T6.4: SELLs de señal (con signal_score) esperan esta edad mínima en "
            "días hábiles. 0 = off. Exits atr_*/vol_trim no aplican."
        ),
    ),
    "paper_signal_sell_bypass_score": SettingSpec(
        (int, float), 0.25, min=0.0, max=1.0,
        doc=(
            "T6.4: SELLs de señal con score < este umbral ejecutan directo sin "
            "esperar la edad mínima (convicción alta de venta). 0 = sin bypass."
        ),
    ),
    "paper_anti_flap_minutes": SettingSpec(
        int, 30, min=0, max=10_080, doc="Cannot BUY a ticker we filled-SELL on within last N min"
    ),
    "paper_min_trade_dollars": SettingSpec(
        (int, float),
        250.0,
        min=0.0,
        doc=(
            "Skip BUYs whose target_dollars is below this. Default raised from "
            "$50 to $250 (Sprint 0 / T11) because IBKR Pro's per-order minimum "
            "(~$1) plus slippage already pushes round-trip cost to ~1% at $250 "
            "of notional — below that, fees dominate any plausible edge."
        ),
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
    # Anti-churn v2 (T6.5): frequency-based cooldown, independiente del P/L.
    # El anti-whipsaw (Gate 5) solo mira ciclos perdedores y por eso no frenó
    # el churn de KO (3 ciclos en 7 días, el primero ganador).
    "paper_churn_max_cycles": SettingSpec(
        int,
        3,
        min=0,
        max=20,
        doc=(
            "T6.5: block re-BUY when the ticker already closed >= N cycles "
            "within paper_churn_lookback_days, regardless of P/L. Solo cuentan "
            "SELLs que dejan la posición en cero (trims parciales no). "
            "0 = disable the gate."
        ),
    ),
    "paper_churn_lookback_days": SettingSpec(
        int,
        10,
        min=0,
        max=90,
        doc=(
            "T6.5: rolling window (calendar days) para contar ciclos cerrados "
            "del gate anti-churn. El cooldown expira solo: los ciclos viejos "
            "salen de la ventana. 0 = disable the gate."
        ),
    ),
    # ADV liquidity cap (T10 of the validation roadmap)
    # Disabled by default (0.0) — turning it on changes live BUY sizing, which
    # would contaminate the kill_only baseline mid-monitoring. Opt-in.
    "paper_adv_cap_pct": SettingSpec(
        (int, float),
        0.0,
        min=0.0,
        max=1.0,
        doc=(
            "Cap each BUY notional at this fraction of the ticker's recent "
            "average daily dollar volume (ADV$). 0.0 = disable. e.g. 0.05 = "
            "never open more than 5% of ADV in one order. The order is trimmed "
            "down (not blocked); if the trim lands below paper_min_trade_dollars "
            "the dust gate then skips it. Fails open when history is too thin to "
            "estimate ADV."
        ),
    ),
    "paper_adv_lookback_days": SettingSpec(
        int,
        20,
        min=1,
        max=252,
        doc=(
            "Trailing sessions used to estimate ADV$ (mean of Close × Volume). "
            "Default 20 ≈ one trading month. Consulted by the ADV cap (T10) and "
            "the E1b universe liquidity floor."
        ),
    ),
    # E1b universe quality/liquidity screen (anti-MLTX). Filters BUY *candidates*
    # before they enter — never touches held positions. Master switch OFF by
    # default: turning it on changes which names can enter live, a trading
    # decision that must clear its kill-criteria (excludes MLTX-type names
    # without removing good ones) against the real watchlist first. Fail-open:
    # a name is dropped only on positive evidence of illiquidity / fragility.
    "paper_universe_screen_enabled": SettingSpec(
        bool,
        False,
        doc=(
            "E1b master switch. When True, each BUY candidate is screened by "
            "recent ADV$ (liquidity floor) and EDGAR XBRL fundamentals "
            "(sustained losses + negligible revenue → fragile). Candidates that "
            "fail are skipped before ranking/sizing. Held positions are never "
            "screened. OFF = no behavior change."
        ),
    ),
    "paper_universe_min_adv_dollars": SettingSpec(
        (int, float),
        0.0,
        min=0.0,
        doc=(
            "E1b liquidity floor: exclude a BUY candidate whose recent average "
            "daily dollar volume (Close×Volume, paper_adv_lookback_days window) "
            "is below this. 0.0 = disable the liquidity leg. Fails open when "
            "history is too thin to estimate ADV$."
        ),
    ),
    "paper_universe_fundamentals_enabled": SettingSpec(
        bool,
        True,
        doc=(
            "E1b fundamentals leg. When True (and the screen is on), a candidate "
            "with sustained negative annual net income AND revenue below "
            "paper_universe_revenue_floor_dollars is excluded (pre-revenue "
            "clinical-biotech signature). Fails open on missing EDGAR facts."
        ),
    ),
    "paper_universe_min_negative_years": SettingSpec(
        int,
        2,
        min=1,
        max=10,
        doc=(
            "E1b: require this many consecutive most-recent annual net-income "
            "figures, all < 0, before a name counts as fragile. Guards against "
            "excluding a name over a single one-off loss year."
        ),
    ),
    "paper_universe_revenue_floor_dollars": SettingSpec(
        (int, float),
        10_000_000.0,
        min=0.0,
        doc=(
            "E1b: a name with sustained losses is fragile only if its latest "
            "annual revenue is below this floor (≈ pre-revenue). Revenue-"
            "generating but unprofitable growth names are NOT excluded."
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
    # Conviction × volatility sizing (T06 of the engine roadmap)
    # Only consulted by the VOL_TARGET / KELLY_FRACTIONAL allocation modes;
    # the heuristic modes (equal/signal/inverse_vol/fixed) ignore these.
    "kelly_fraction": SettingSpec(
        (int, float),
        0.25,
        min=0.0,
        max=1.0,
        doc=(
            "Fraction of full Kelly used by AllocationMode.KELLY_FRACTIONAL. "
            "0.25 = quarter-Kelly (conservative). target_w = "
            "kelly_fraction × edge / variance, edge = 2·prob_up − 1."
        ),
    ),
    "vol_target_annual": SettingSpec(
        (int, float),
        0.20,
        min=0.01,
        max=2.0,
        doc=(
            "Per-name annualised volatility target for "
            "AllocationMode.VOL_TARGET. target_w = (vol_target_annual / σ) / N "
            "— higher σ ⇒ less exposure. 0.20 = 20%."
        ),
    ),
    "max_position_weight": SettingSpec(
        (int, float),
        0.25,
        min=0.01,
        max=1.0,
        doc=(
            "Hard cap on any single ticker's weight for the VOL_TARGET / "
            "KELLY_FRACTIONAL modes. After capping, if the book sums to > 1.0 "
            "it is scaled down proportionally (long-only, no leverage)."
        ),
    ),
    # Earnings blackout gate (T08 of the engine roadmap)
    "earnings_blackout_days": SettingSpec(
        int,
        2,
        min=0,
        max=30,
        doc=(
            "Gate 6: block BUY (and optionally SELL — see "
            "earnings_blackout_block_sells) when the ticker has scheduled "
            "earnings within ±N calendar days of the scan. ATR-forced stop-loss "
            "SELLs (T01) bypass this regardless. 0 = disable the gate. Earnings "
            "dates come from yfinance.Ticker.calendar (24h cache); "
            "unknown/failed lookups fail-open (no block)."
        ),
    ),
    "earnings_blackout_block_sells": SettingSpec(
        bool,
        False,
        doc=(
            "When True, Gate 6 also blocks strategy-signaled SELLs during the "
            "earnings window (legacy pre-T08-fix behavior). Default False "
            "(Sprint 0 / T08): a SELL signal arriving right before earnings is "
            "exactly when you want to exit — keeping the position trapped "
            "creates more whipsaws than it prevents. BUYs are still blocked, "
            "and ATR-forced exits always bypass the gate regardless of this "
            "setting."
        ),
    ),
    # NOTE: ``max_avg_correlation`` and ``correlation_gate_enabled`` were removed
    # in Sprint 3 (2026-05-29) after attribution showed the gate never rejected
    # a candidate in any realistic harness setup. ``analyze_stacked`` with a
    # 0.55 buy threshold produces 1-2 BUYs per step, never reaching the
    # "candidates > slots" condition the gate was designed for. The pure
    # math function ``paper_trading.gates.select_uncorrelated_picks`` is kept
    # as vestigial — re-introduce these settings + a wrapper if a future
    # strategy generates many simultaneous BUYs and wants the gate back.
    # See ``docs/sprint2_kill_criteria.md`` Enmienda 2.
    # Portfolio volatility targeting overlay (T10 of the engine roadmap)
    "vol_target_portfolio_annual": SettingSpec(
        (int, float),
        0.12,
        min=0.0,
        max=2.0,
        doc=(
            "Annualised volatility ceiling for the whole book. After the "
            "allocation mode produces target weights, a shared overlay scales "
            "every position down proportionally (toward cash, long-only) if the "
            "book's estimated σ = sqrt(wᵀΣw)·sqrt(252) exceeds this. Never "
            "scales up (no leverage). 0 disables the overlay — no separate flag. "
            "0.12 = 12%."
        ),
    ),
    # T09 (engine roadmap) — active de-risking of the *existing* book. The T10
    # overlay above only scales NEW buys; without this, an already-overvolatile
    # book in analyze_single never trims and only unwinds via its own SELL
    # signals / ATR stops. When enabled, analyze_single emits partial SELL trims
    # on held positions so the book σ returns toward vol_target_portfolio_annual,
    # independent of whether there are new buys this scan. Default False — opt-in
    # so it can be validated against baseline before shipping live.
    "vol_overlay_trim_enabled": SettingSpec(
        bool,
        False,
        doc=(
            "Active de-risking (T09): when the held book's estimated σ exceeds "
            "vol_target_portfolio_annual, analyze_single emits partial SELL trims "
            "to bring existing positions back toward target — not just scale new "
            "buys. Requires vol_target_portfolio_annual > 0. Default False."
        ),
    ),
    # Feature toggles for research stack validation (Sprint 1 / roadmap)
    # Each T-feature can be toggled independently. Defaults preserve current behavior.
    "hmm_enabled": SettingSpec(
        bool,
        True,
        doc=(
            "Enable Hidden Markov Model state filtering in analyze_single. "
            "When disabled, HMM regime assignment is skipped (all states treated as neutral)."
        ),
    ),
    "stacking_enabled": SettingSpec(
        bool,
        True,
        doc=(
            "Enable position stacking (T05): allow multiple fills per ticker "
            "on the same scan. When disabled, max 1 position per name per scan."
        ),
    ),
    "xgb_signal_enabled": SettingSpec(
        bool,
        True,
        doc=(
            "Enable XGBoost signal weighting in allocation. When disabled, "
            "uses equal weighting across signal_score bins."
        ),
    ),
    "vol_overlay_enabled": SettingSpec(
        bool,
        True,
        doc=(
            "Enable portfolio volatility overlay (T10): scale positions down if "
            "estimated book σ exceeds vol_target_portfolio_annual. When disabled, "
            "no scaling (full allocation)."
        ),
    ),
    # Sprint 4 / T05 — cross-sectional momentum ranking. When enabled, BUY
    # candidates are ranked by a blend of the absolute ml_probability strength
    # and a cross-sectional percentile of the last ``cross_sectional_lookback``-
    # day return against the rest of the universe. Pure-function math lives in
    # ``analysis/ranking.py``. Default OFF — shipping decision pending harness
    # validation. Full spec: docs/sprint4_t05_cross_sectional_spec.md.
    "cross_sectional_enabled": SettingSpec(
        bool,
        False,
        doc=(
            "Enable cross-sectional ranking (T05): blend absolute strength with "
            "cross-sectional momentum percentile when choosing BUY candidates. "
            "When disabled, ranking is purely absolute (legacy behaviour)."
        ),
    ),
    "cross_sectional_lookback": SettingSpec(
        int,
        120,
        min=2,
        max=504,
        doc=(
            "Lookback in trading days for the cross-sectional momentum return. "
            "120 ≈ 6 months — Jegadeesh-Titman / Asness sweet-spot. Tickers with "
            "fewer than lookback+1 closes get the neutral percentile (0.5)."
        ),
    ),
    "cross_sectional_weight": SettingSpec(
        float,
        0.5,
        min=0.0,
        max=1.0,
        doc=(
            "Blend factor in [0, 1] for the cross-sectional percentile vs "
            "absolute strength. 0.0 = pure absolute (legacy), 1.0 = pure "
            "cross-sectional, 0.5 = equal blend."
        ),
    ),
    # Slack notifications on new BUY/SELL orders (T12 of the engine roadmap)
    # Master switch OFF by default. The bot token is NEVER stored here — the
    # engine reads it from the SLACK_BOT_TOKEN env var. Only the non-secret
    # channel id lives in settings (or the SLACK_CHANNEL env var).
    "slack_notifications_enabled": SettingSpec(
        bool,
        False,
        doc=(
            "Master switch for Slack notifications. When True, run_scan sends a "
            "per-scan summary of new orders to Slack via chat.postMessage. The "
            "bot token comes from the SLACK_BOT_TOKEN env var (never settings)."
        ),
    ),
    "slack_notify_on": SettingSpec(
        str,
        "both",
        choices=("pending", "filled", "both"),
        doc=(
            "Which new orders trigger a Slack message: 'pending' (queued in "
            "manual mode), 'filled' (executed in auto mode / approved), or "
            "'both'. One summary message per scan listing the matching orders."
        ),
    ),
    "slack_channel": SettingSpec(
        str,
        "",
        doc=(
            "Slack channel id/name the bot posts to (e.g. '#trading' or a "
            "channel id). Non-secret. Overridable via the SLACK_CHANNEL env "
            "var. Empty + no env var ⇒ notifications are skipped (fail-open)."
        ),
    ),
    "slack_data_outage_enabled": SettingSpec(
        bool,
        True,
        doc=(
            "Send a Slack alert when Yahoo stops responding for a sustained "
            "period (NET1 breaker escalates to level ≥2): one message when the "
            "outage persists and one on recovery. Independent of "
            "slack_notifications_enabled. No-op without a token/channel "
            "(fail-open); reuses the same SLACK_BOT_TOKEN / channel."
        ),
    ),
    "slack_price_alerts_enabled": SettingSpec(
        bool,
        True,
        doc=(
            "Send a Slack message when a price alert fires "
            "(AlertManager.check_alerts), batched to one message per check, on "
            "top of the in-app popup. Independent of slack_notifications_enabled "
            "(that governs engine orders). Default True: no-op without a "
            "token/channel (fail-open); reuses the same SLACK_BOT_TOKEN / channel."
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
