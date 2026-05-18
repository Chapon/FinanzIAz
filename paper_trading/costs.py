"""
Configurable commission + slippage models for paper trading and backtests.

Why
---
The current engine bakes a flat percent-of-notional commission and a flat
percent slippage into every fill. Real broker fee schedules look like:

  • Interactive Brokers Pro:  0.005 USD/share, $1 minimum, capped at 1% of trade value.
  • IBKR Lite / Robinhood:    $0 commission, possibly with PFOF spread.
  • Tiered legacy brokers:    $X flat per ticket.
  • Argentine brokers:        % notional + IVA + market fees + transfer fees.

This module exposes a small abstract ``CommissionModel`` / ``SlippageModel``
hierarchy so each paper-trading account (and each backtest config) can pick
the right one without the engine having to special-case anything.

Public API
----------
``CommissionModel`` + concrete ``FlatCommission``, ``PercentCommission``,
``PerShareCommission``, ``TieredCommission``, ``IBKRProCommission``.

``SlippageModel`` + concrete ``ZeroSlippage``, ``PercentSlippage``,
``TickSlippage``.

Each has a ``cost(side, shares, price)`` (commission) or
``adjust_price(side, price)`` (slippage) entry point.

Use ``from_config(dict)`` to instantiate from a serialised settings blob.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any

# ── Commission models ────────────────────────────────────────────────────────


class CommissionModel(abc.ABC):
    """Abstract commission model. Returns dollar cost per fill."""

    @abc.abstractmethod
    def cost(self, *, side: str, shares: float, price: float) -> float:
        """Return the dollar fee for a fill of ``shares`` at ``price``."""

    def to_dict(self) -> dict:
        return {"type": type(self).__name__, **vars(self)}


@dataclass
class FlatCommission(CommissionModel):
    """Fixed dollar fee per ticket (e.g. $5 flat)."""

    fee: float = 0.0

    def cost(self, *, side: str, shares: float, price: float) -> float:
        return float(max(0.0, self.fee))


@dataclass
class PercentCommission(CommissionModel):
    """% of notional with optional minimum and maximum dollar amounts."""

    rate: float = 0.001  # 0.10 %
    min_fee: float = 0.0
    max_fee: float | None = None

    def cost(self, *, side: str, shares: float, price: float) -> float:
        notional = abs(shares * price)
        fee = notional * max(0.0, self.rate)
        fee = max(fee, self.min_fee)
        if self.max_fee is not None:
            fee = min(fee, self.max_fee)
        return float(fee)


@dataclass
class PerShareCommission(CommissionModel):
    """IBKR-style: $/share with min, max-as-%-of-notional cap."""

    per_share: float = 0.005
    min_fee: float = 1.0
    max_fee_pct: float = 0.01  # cap at 1% of notional

    def cost(self, *, side: str, shares: float, price: float) -> float:
        notional = abs(shares * price)
        raw = abs(shares) * max(0.0, self.per_share)
        capped = min(raw, notional * self.max_fee_pct) if self.max_fee_pct > 0 else raw
        return float(max(self.min_fee, capped))


@dataclass
class TieredCommission(CommissionModel):
    """
    Volume-tiered: pick the band whose ``up_to_notional`` is the smallest one
    not less than this trade's notional, return its fee.

    ``bands`` is a list of ``(up_to_notional, fee)`` tuples. The last band's
    threshold is taken as +infinity.
    """

    bands: list[tuple[float, float]] = None  # type: ignore[assignment]

    def cost(self, *, side: str, shares: float, price: float) -> float:
        notional = abs(shares * price)
        bands = self.bands or [(float("inf"), 0.0)]
        for up_to, fee in bands:
            if notional <= up_to:
                return float(max(0.0, fee))
        return float(max(0.0, bands[-1][1]))


# ── IBKR Pro: real-world Tiered / Fixed for US stocks ────────────────────────
#
# Why a dedicated model
# ---------------------
# The generic ``PerShareCommission`` only covers the IBKR base ticket fee.
# Real IBKR fills also pass through regulatory + exchange/clearing fees that
# add up on high-share-count or sell-heavy strategies. This model layers all
# four buckets so paper-trading P&L matches what the real broker would charge.
#
# Schedule references (US stocks, <= 300k shares/month tier, 2024-2025):
#   - Tiered:  USD 0.0035/share, min USD 0.35, cap 1% of trade value
#   - Fixed:   USD 0.0050/share, min USD 1.00, cap 1% of trade value
#   - SEC Section 31 fee: USD 27.80 per USD 1,000,000 sold (sells only)
#   - FINRA TAF: USD 0.000166/share on sells, capped at USD 8.30/trade
#   - FINRA CAT fee: ~USD 0.000035/share (both sides)
#   - Tiered exchange/route fee: ~USD 0.003/share taker (we assume taker --
#     paper trading can't know venue/route; conservative for backtests).
#
# Update the module-level constants if SEC/FINRA publish a new schedule.

SEC_FEE_RATE = 0.0000278        # USD per USD of notional, sells only
FINRA_TAF_PER_SHARE = 0.000166  # USD per share sold
FINRA_TAF_MAX = 8.30            # USD cap per trade
FINRA_CAT_PER_SHARE = 0.000035  # USD per share (both sides)


@dataclass
class IBKRProCommission(CommissionModel):
    """
    Realistic IBKR Pro fee model with regulatory + exchange pass-through.

    Components per fill:
        IBKR     = max(min_fee, min(shares * per_share, notional * max_fee_pct))
        Exchange = shares * exchange_fee_per_share          (both sides)
        CAT      = shares * FINRA_CAT_PER_SHARE             (both sides, if include_regulatory)
        SEC      = notional * SEC_FEE_RATE                  (SELL only, if include_regulatory)
        FINRA    = min(shares * FINRA_TAF_PER_SHARE, $8.30) (SELL only, if include_regulatory)

    Use the factories ``make_ibkr_pro_tiered()`` / ``make_ibkr_pro_fixed()`` for
    the canonical IBKR Pro presets -- they wire the right per_share / min_fee /
    exchange_fee combination for each plan.
    """

    per_share: float = 0.0035
    min_fee: float = 0.35
    max_fee_pct: float = 0.01
    exchange_fee_per_share: float = 0.003  # 0.0 for Fixed (bundled in per_share)
    include_regulatory: bool = True

    def cost(self, *, side: str, shares: float, price: float) -> float:
        n_shares = abs(float(shares))
        notional = n_shares * abs(float(price))

        # IBKR base ticket: per-share with min + 1% cap.
        raw = n_shares * max(0.0, self.per_share)
        capped = min(raw, notional * self.max_fee_pct) if self.max_fee_pct > 0 else raw
        ibkr = max(self.min_fee, capped)

        # Exchange / route fee (Tiered only -- Fixed bundles this in per_share).
        exchange = n_shares * max(0.0, self.exchange_fee_per_share)

        # Regulatory pass-through.
        reg = 0.0
        if self.include_regulatory:
            reg += n_shares * FINRA_CAT_PER_SHARE
            if str(side).upper() == "SELL":
                reg += notional * SEC_FEE_RATE
                reg += min(n_shares * FINRA_TAF_PER_SHARE, FINRA_TAF_MAX)

        return float(ibkr + exchange + reg)

    def breakdown(self, *, side: str, shares: float, price: float) -> dict:
        """
        Return the cost broken into components. Handy for UI tooltips and
        reports that want to show "you paid $X in commission, $Y in fees".
        """
        n_shares = abs(float(shares))
        notional = n_shares * abs(float(price))

        raw = n_shares * max(0.0, self.per_share)
        capped = min(raw, notional * self.max_fee_pct) if self.max_fee_pct > 0 else raw
        ibkr = max(self.min_fee, capped)

        exchange = n_shares * max(0.0, self.exchange_fee_per_share)

        cat = sec = finra = 0.0
        if self.include_regulatory:
            cat = n_shares * FINRA_CAT_PER_SHARE
            if str(side).upper() == "SELL":
                sec = notional * SEC_FEE_RATE
                finra = min(n_shares * FINRA_TAF_PER_SHARE, FINRA_TAF_MAX)

        return {
            "ibkr": float(ibkr),
            "exchange": float(exchange),
            "cat": float(cat),
            "sec": float(sec),
            "finra_taf": float(finra),
            "total": float(ibkr + exchange + cat + sec + finra),
        }


def make_ibkr_pro_tiered() -> IBKRProCommission:
    """IBKR Pro Tiered for US stocks (<= 300k shares/mo)."""
    return IBKRProCommission(
        per_share=0.0035,
        min_fee=0.35,
        max_fee_pct=0.01,
        exchange_fee_per_share=0.003,
        include_regulatory=True,
    )


def make_ibkr_pro_fixed() -> IBKRProCommission:
    """IBKR Pro Fixed for US stocks (exchange/clearing bundled)."""
    return IBKRProCommission(
        per_share=0.005,
        min_fee=1.0,
        max_fee_pct=0.01,
        exchange_fee_per_share=0.0,
        include_regulatory=True,
    )


def get_active_commission_model() -> CommissionModel:
    """
    Return the commission model the user picked in Settings.

    Reads ``ibkr_commission_plan`` from settings.json:
        "tiered" -> IBKRProCommission tuned for IBKR Pro Tiered (default)
        "fixed"  -> IBKRProCommission tuned for IBKR Pro Fixed
        "legacy" -> callers should fall back to the per-account PercentCommission
                    (returned here as a PercentCommission sentinel -- the engine
                    has the real ``acct.commission`` and will rebuild it).

    Imported lazily so config doesn't depend on this module.
    """
    try:
        from config.settings_manager import settings as _settings
        plan = str(_settings.get("ibkr_commission_plan", "tiered")).lower()
    except Exception:
        plan = "tiered"

    if plan == "fixed":
        return make_ibkr_pro_fixed()
    if plan == "legacy":
        return PercentCommission()  # sentinel; engine prefers acct.commission
    return make_ibkr_pro_tiered()


# ── Slippage models ──────────────────────────────────────────────────────────


class SlippageModel(abc.ABC):
    """Abstract slippage model. Returns the realised fill price."""

    @abc.abstractmethod
    def adjust_price(self, *, side: str, price: float) -> float:
        """Return the price the simulated fill actually executes at."""

    def to_dict(self) -> dict:
        return {"type": type(self).__name__, **vars(self)}


@dataclass
class ZeroSlippage(SlippageModel):
    """Fills at the quoted price. Useful for sanity checks."""

    def adjust_price(self, *, side: str, price: float) -> float:
        return float(price)


@dataclass
class PercentSlippage(SlippageModel):
    """% adverse to the trade direction (BUY pays up, SELL pays down)."""

    rate: float = 0.0005

    def adjust_price(self, *, side: str, price: float) -> float:
        s = side.upper()
        if s == "BUY":
            return float(price) * (1.0 + self.rate)
        if s == "SELL":
            return float(price) * (1.0 - self.rate)
        return float(price)


@dataclass
class TickSlippage(SlippageModel):
    """Fixed N-tick slippage (where 1 tick = ``tick_size`` dollars)."""

    ticks: int = 1
    tick_size: float = 0.01

    def adjust_price(self, *, side: str, price: float) -> float:
        delta = self.ticks * self.tick_size
        s = side.upper()
        if s == "BUY":
            return float(price) + delta
        if s == "SELL":
            return float(price) - delta
        return float(price)


# ── Factory / config interop ─────────────────────────────────────────────────

_COMMISSION_REGISTRY: dict[str, type[CommissionModel]] = {
    "FlatCommission": FlatCommission,
    "PercentCommission": PercentCommission,
    "PerShareCommission": PerShareCommission,
    "TieredCommission": TieredCommission,
    "IBKRProCommission": IBKRProCommission,
}

_SLIPPAGE_REGISTRY: dict[str, type[SlippageModel]] = {
    "ZeroSlippage": ZeroSlippage,
    "PercentSlippage": PercentSlippage,
    "TickSlippage": TickSlippage,
}


def commission_from_config(cfg: dict[str, Any]) -> CommissionModel:
    """
    Build a commission model from a JSON-serialisable dict like
    ``{"type": "PercentCommission", "rate": 0.001, "min_fee": 1.0}``.
    Missing/unknown ``type`` falls back to a 0.10% PercentCommission so the
    engine never crashes on a misconfigured account.
    """
    cls = _COMMISSION_REGISTRY.get(cfg.get("type", ""), PercentCommission)
    fields = {k: v for k, v in cfg.items() if k != "type"}
    try:
        return cls(**fields)
    except TypeError:
        return PercentCommission()


def slippage_from_config(cfg: dict[str, Any]) -> SlippageModel:
    cls = _SLIPPAGE_REGISTRY.get(cfg.get("type", ""), PercentSlippage)
    fields = {k: v for k, v in cfg.items() if k != "type"}
    try:
        return cls(**fields)
    except TypeError:
        return PercentSlippage()


def commission_from_legacy(rate: float) -> CommissionModel:
    """Back-compat: turn a single rate into a PercentCommission."""
    return PercentCommission(rate=float(rate))


def slippage_from_legacy(rate: float) -> SlippageModel:
    return PercentSlippage(rate=float(rate))
