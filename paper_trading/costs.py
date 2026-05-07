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
``PerShareCommission``, ``TieredCommission``.

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

    def cost(self, *, side: str, shares: float, price: float) -> float:  # noqa: ARG002
        return float(max(0.0, self.fee))


@dataclass
class PercentCommission(CommissionModel):
    """% of notional with optional minimum and maximum dollar amounts."""
    rate: float = 0.001      # 0.10 %
    min_fee: float = 0.0
    max_fee: float | None = None

    def cost(self, *, side: str, shares: float, price: float) -> float:  # noqa: ARG002
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
    max_fee_pct: float = 0.01   # cap at 1% of notional

    def cost(self, *, side: str, shares: float, price: float) -> float:  # noqa: ARG002
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
    threshold is taken as +∞.
    """
    bands: list[tuple[float, float]] = None  # type: ignore[assignment]

    def cost(self, *, side: str, shares: float, price: float) -> float:  # noqa: ARG002
        notional = abs(shares * price)
        bands = self.bands or [(float("inf"), 0.0)]
        for up_to, fee in bands:
            if notional <= up_to:
                return float(max(0.0, fee))
        return float(max(0.0, bands[-1][1]))


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

    def adjust_price(self, *, side: str, price: float) -> float:  # noqa: ARG002
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
    "FlatCommission":     FlatCommission,
    "PercentCommission":  PercentCommission,
    "PerShareCommission": PerShareCommission,
    "TieredCommission":   TieredCommission,
}

_SLIPPAGE_REGISTRY: dict[str, type[SlippageModel]] = {
    "ZeroSlippage":    ZeroSlippage,
    "PercentSlippage": PercentSlippage,
    "TickSlippage":    TickSlippage,
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
