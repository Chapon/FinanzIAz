"""
Universe quality/liquidity screen (E1b — anti-MLTX estructural).

The effectiveness analysis (2026-06-30) showed a single fragile name (MLTX,
clinical-stage biotech, −89.9 %, −$2.554 realized) defined the whole result:
P/L +$278 with it, +$2.920 without. The exposure *cap* (E1a) was NO-SHIP — a
blind size cap trims winners (MU/AAPL were as over-concentrated as MLTX) as much
as losers. The correct defense is on the **universe, not the size**: keep names
like MLTX from entering at all, via

  (a) a minimum recent ADV$ floor (illiquid microcaps), and
  (b) a fundamental-fragility screen (sustained negative net income *and*
      negligible revenue — the signature of a pre-revenue clinical biotech).

This module holds the **pure decision** only. Facts come from
``paper_trading.gates.recent_adv_dollars`` (liquidity) and
``data.edgar_fundamentals`` (EDGAR XBRL). The screen is applied to BUY
*candidates* only — never to names already held, so open positions still get
their SELL/stop evaluation.

Fail-open is the guiding rule: a name is excluded only on **positive evidence**
of illiquidity or fragility. Missing ADV, missing CIK, no filings, too few net-
income years → the name is kept, so a data gap never silently drops a good name
(kill-criteria: "excludes MLTX-type names *without removing good names*"). The
one deliberate exception: once a name shows *sustained losses* (the positive
evidence), an **absent** revenue tag is read as pre-revenue (≈ $0), not as a
gap — that is precisely the clinical-biotech signature and the only way to catch
MLTX (which reports no revenue at all). See ``_fragile_fundamentals``.
"""

from __future__ import annotations

from dataclasses import dataclass

from data.edgar_fundamentals import FundamentalFacts

# Machine-readable exclusion reasons (surfaced in scan warnings / the validation
# report). Empty string = included.
REASON_ADV = "adv_below_floor"
REASON_FRAGILE = "fragile_fundamentals"


@dataclass(frozen=True)
class UniverseThresholds:
    """Tunable knobs for the screen (built from settings; see ``from_settings``).

    ``min_adv_dollars``      — recent ADV$ floor; 0 disables the liquidity leg.
    ``fundamentals_enabled`` — master switch for the EDGAR fragility leg.
    ``min_negative_years``   — require this many *consecutive* recent annual net
                               income points, all < 0, before a name can be
                               called fragile (guards against a one-off loss).
    ``revenue_floor``        — a name with sustained losses is fragile only if
                               its latest annual revenue is below this (i.e.
                               essentially pre-revenue). Revenue-generating but
                               unprofitable growth names are NOT excluded.
    """

    min_adv_dollars: float = 0.0
    fundamentals_enabled: bool = True
    min_negative_years: int = 2
    revenue_floor: float = 10_000_000.0

    @classmethod
    def from_settings(cls) -> UniverseThresholds:
        from config.settings_manager import settings

        return cls(
            min_adv_dollars=float(settings.get("paper_universe_min_adv_dollars")),
            fundamentals_enabled=bool(settings.get("paper_universe_fundamentals_enabled")),
            min_negative_years=int(settings.get("paper_universe_min_negative_years")),
            revenue_floor=float(settings.get("paper_universe_revenue_floor_dollars")),
        )


@dataclass(frozen=True)
class UniverseVerdict:
    """Result of screening one candidate. ``included=False`` carries a reason."""

    ticker: str
    included: bool
    reason: str = ""
    detail: str = ""

    @property
    def excluded(self) -> bool:
        return not self.included


def _fragile_fundamentals(
    facts: FundamentalFacts | None,
    thresholds: UniverseThresholds,
) -> str | None:
    """Return a human detail string iff the fundamentals look pre-revenue-fragile.

    Fragile = the most recent ``min_negative_years`` annual net income figures
    are ALL negative AND the latest annual revenue is below ``revenue_floor`` —
    where **a missing revenue concept counts as below the floor**. A clinical-
    stage biotech (MLTX) reports *no* revenue tag at all in EDGAR, so treating
    "no revenue" as fail-open would let exactly the target name slip through
    (validated 2026-07-02: MLTX net income −227M/−118M with revenue absent). The
    positive evidence here is the sustained-loss series; the missing revenue only
    reinforces it. Fail open only on weak evidence: too few NI points, or a
    profitable year inside the window.
    """
    if facts is None:
        return None
    need = max(1, thresholds.min_negative_years)
    ni = facts.net_income_recent
    if len(ni) < need:
        return None
    if not all(v < 0 for v in ni[:need]):
        return None
    rev = facts.revenue_latest
    if rev is not None and rev >= thresholds.revenue_floor:
        return None
    rev_txt = "sin revenue reportado" if rev is None else f"revenue {rev:,.0f}"
    return (
        f"net income < 0 en los últimos {need} años "
        f"(último {ni[0]:,.0f}) con {rev_txt} (< piso {thresholds.revenue_floor:,.0f})"
    )


def screen_candidate(
    ticker: str,
    adv_dollars: float | None,
    facts: FundamentalFacts | None,
    thresholds: UniverseThresholds,
) -> UniverseVerdict:
    """Pure screen for one BUY candidate. Excludes only on positive evidence.

    Order: liquidity first (cheap, no network), then fundamentals. The first
    failing leg wins the reason.
    """
    if (
        thresholds.min_adv_dollars > 0
        and adv_dollars is not None
        and adv_dollars < thresholds.min_adv_dollars
    ):
        return UniverseVerdict(
            ticker=ticker,
            included=False,
            reason=REASON_ADV,
            detail=f"ADV$ {adv_dollars:,.0f} < piso {thresholds.min_adv_dollars:,.0f}",
        )
    if thresholds.fundamentals_enabled:
        detail = _fragile_fundamentals(facts, thresholds)
        if detail is not None:
            return UniverseVerdict(ticker=ticker, included=False, reason=REASON_FRAGILE, detail=detail)
    return UniverseVerdict(ticker=ticker, included=True)


def screen_enabled() -> bool:
    """Master switch — the whole screen is a no-op unless this is on."""
    from config.settings_manager import settings

    return bool(settings.get("paper_universe_screen_enabled"))


__all__ = [
    "REASON_ADV",
    "REASON_FRAGILE",
    "UniverseThresholds",
    "UniverseVerdict",
    "screen_candidate",
    "screen_enabled",
]
