"""
Signal → target-trade generators for paper trading.

Each strategy is a function with the uniform signature::

    generate_trades(account, watchlist, positions, prices, history_provider)
        -> list[TargetTrade]

``TargetTrade`` is the intent handed to the engine; the engine decides
whether to fill it immediately (auto mode) or queue it as a pending
``PaperOrder`` (manual mode).

Two strategies are provided:

1. ``analyze_single`` — each ticker evaluated in isolation via
   ``analysis.technical.analyze``. Simple, per-position logic, sized to
   equal-weight slots of cash.

2. ``portfolio_engine`` — replicates one step of the portfolio-backtest
   loop using the account's ``allocation_mode``, ``max_positions``,
   drift threshold and monthly rebalance flag. Fully coherent with the
   historical back-tester.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from analysis.portfolio_backtest import (
    AllocationMode,
    _compute_target_weights,
    _realized_vol,
)
from analysis.portfolio_risk import (
    apply_portfolio_vol_overlay,
    returns_frame,
)
from config.logging_config import get_logger
from config.settings_manager import settings
from database.models import utcnow_naive
from paper_trading.gates import (
    VOL_TRIM_REASON_PREFIX,
    compute_vol_overlay,
)
from paper_trading.models import PaperAccount, PaperPosition

# Allocation modes whose sizing depends on per-name volatility (and, for
# Kelly, a calibrated probability) rather than a flat cash split. T06.
_VOL_SIZED_MODES = {AllocationMode.VOL_TARGET.value, AllocationMode.KELLY_FRACTIONAL.value}


def _sizing_params() -> dict[str, float]:
    """Read the user-tunable T06 sizing knobs from settings."""
    return {
        "kelly_fraction": float(settings.get("kelly_fraction")),
        "vol_target_annual": float(settings.get("vol_target_annual")),
        "max_weight": float(settings.get("max_position_weight")),
    }


def _calibrated_prob(ml_probability: float | None) -> float | None:
    """Return ml_probability only when it is a real, finite calibrated value."""
    if ml_probability is None or not np.isfinite(ml_probability):
        return None
    return float(ml_probability)


# ── Value type ────────────────────────────────────────────────────────────────


@dataclass
class TargetTrade:
    ticker: str
    side: str  # "BUY" | "SELL"
    target_shares: float | None  # for SELL: total shares to close; for BUY: None if using target_dollars
    target_dollars: float | None  # for BUY: dollar amount; for SELL: None or estimated proceeds
    reason: str
    source: str  # strategy name ("analyze_single" | "portfolio_engine")
    signal_score: float | None = None  # conviction in [0,1]; None for rebalance trades
    # Precio de fill modelado para salidas forzadas por nivel (T01). Cuando está
    # seteado, el auto-fill lo usa como precio base en lugar del último precio del
    # scan, para reflejar el gap/touch real del stop (ver gates.model_exit_fill_price).
    fill_price_override: float | None = None

    def __repr__(self) -> str:
        dollars = f"${self.target_dollars:,.2f}" if self.target_dollars is not None else "—"
        shares = f"{self.target_shares:.4f}" if self.target_shares is not None else "—"
        score = f" score={self.signal_score:.2f}" if self.signal_score is not None else ""
        return f"<TargetTrade({self.side} {self.ticker} {shares}sh / {dollars}{score} · {self.reason})>"


HistoryProvider = Callable[[str], pd.DataFrame | None]

# T09 — active de-risking. ``VOL_TRIM_REASON_PREFIX`` / ``is_vol_trim_reason``
# live in ``paper_trading.gates`` (imported above) alongside the ATR reason
# helpers so the engine's min-holding bypass has a single source of truth.

# Hysteresis: only trim when the overlay would scale the held book down by at
# least this fraction. Prevents churning tiny SELLs when σ hovers just over
# target (factor ≈ 0.99). A 0.05 gap ≈ the book σ sitting ~5 % over target.
_TRIM_MIN_GAP = 0.05


# ── Correlation gate (T09) — REMOVED in Sprint 3 ──────────────────────────────
# The wiring (``_corr_threshold``, ``_returns_for``, ``_select_uncorrelated``)
# was removed after attribution showed the gate never rejected a candidate in
# any realistic harness setup. The pure math function
# ``paper_trading.gates.select_uncorrelated_picks`` is preserved (kept import
# above) as vestigial — re-introduce a wrapper here if a future strategy
# generates many simultaneous BUYs. See docs/sprint2_kill_criteria.md
# (Enmienda 2) for the full rationale.


# ── Portfolio volatility overlay (T10) ──────────────────────────────────────────


def _portfolio_vol_target() -> float:
    """Annualised σ ceiling for the whole book (≤ 0 disables the overlay).

    Sprint-1 toggle: when ``vol_overlay_enabled`` is False we return 0.0 so the
    overlay short-circuits (no σ estimation, no scaling). This bypass is honored
    by every call site because both :func:`compute_vol_overlay` and the inline
    overlay in ``generate_trades_portfolio_engine`` gate on ``vt > 0``.
    """
    if not bool(settings.get("vol_overlay_enabled", True)):
        return 0.0
    return float(settings.get("vol_target_portfolio_annual"))


def _apply_vol_overlay_to_buys(
    dollars: dict[str, float],
    picks: list[str],
    positions: list[PaperPosition],
    forced_exits: set[str],
    prices: dict[str, float],
    portfolio_value: float,
    history_provider: HistoryProvider,
    source: str,
) -> dict[str, float]:
    """Scale the new-buy dollar map by the T10 portfolio-vol overlay factor.

    σ is estimated over the post-trade book — currently-held names that are not
    being force-sold *plus* the new picks — but the factor is applied only to
    the picks, because ``analyze_single`` does not trim existing holdings within
    a single scan. When the book is already over target, the new exposure
    shrinks toward zero (the protective intent); existing positions are left for
    their own SELL signals / ATR stops to unwind.

    Delegates the σ→factor computation to
    :func:`paper_trading.gates.compute_vol_overlay`; this wrapper handles the
    dollar→weight conversion, the returns-frame fetch, the logging, and the
    application of the factor back to the picks' dollar map.
    """
    vt = _portfolio_vol_target()
    if vt <= 0 or portfolio_value <= 0 or not dollars:
        return dollars
    held_w = {
        p.ticker: (p.shares * (prices.get(p.ticker, p.avg_cost) or p.avg_cost)) / portfolio_value
        for p in positions
        if p.ticker not in forced_exits
    }
    pick_w = {t: dollars.get(t, 0.0) / portfolio_value for t in picks}
    combined = {**held_w, **pick_w}
    ret_df = returns_frame(list(combined.keys()), history_provider)
    result = compute_vol_overlay(combined, ret_df, vt, apply_fn=apply_portfolio_vol_overlay)
    if result.factor < 1.0:
        get_logger(__name__).info(
            "portfolio vol overlay (%s): σ=%.1f%% > target %.1f%%, scaled new buys ×%.2f",
            source,
            (result.sigma or 0.0) * 100,
            vt * 100,
            result.factor,
        )
        return {t: v * result.factor for t, v in dollars.items()}
    return dollars


def _vol_trim_enabled() -> bool:
    """T09 active de-risking opt-in. Requires the T10 overlay target > 0."""
    return bool(settings.get("vol_overlay_trim_enabled", False)) and _portfolio_vol_target() > 0


def _vol_overlay_trim_sells(
    positions: list[PaperPosition],
    forced_exits: set[str],
    prices: dict[str, float],
    portfolio_value: float,
    history_provider: HistoryProvider,
    source: str,
) -> list["TargetTrade"]:
    """Emit partial-SELL trims so an over-σ *held* book returns toward target (T09).

    Companion to :func:`_apply_vol_overlay_to_buys`, which only shrinks new buys.
    The σ→factor estimate here is computed over the **currently-held** book
    (positions not already being force-sold this scan) so the trim reflects
    pre-existing risk, not risk that new picks would add. When the factor would
    scale the book down by at least :data:`_TRIM_MIN_GAP`, each held position is
    trimmed to ``current_value × factor`` and the difference is sold.

    Returns an empty list when the toggle is off, the overlay is disabled, the
    book is already within target, or there is nothing meaningful to trim.
    Trims smaller than ``paper_min_trade_dollars`` are skipped as dust.
    """
    if not _vol_trim_enabled() or portfolio_value <= 0:
        return []

    held = [
        p
        for p in positions
        if p.ticker not in forced_exits
        and (p.shares or 0) > 1e-9
        and np.isfinite(prices.get(p.ticker, float("nan")))
        and (prices.get(p.ticker, 0.0) or 0.0) > 0
    ]
    if not held:
        return []

    vt = _portfolio_vol_target()
    held_w = {p.ticker: (p.shares * prices[p.ticker]) / portfolio_value for p in held}
    ret_df = returns_frame(list(held_w.keys()), history_provider)
    result = compute_vol_overlay(held_w, ret_df, vt, apply_fn=apply_portfolio_vol_overlay)
    factor = result.factor
    # Hysteresis: leave the book alone unless it is meaningfully over target.
    if factor > 1.0 - _TRIM_MIN_GAP:
        return []

    dust = float(settings.get("paper_min_trade_dollars", 0.0) or 0.0)
    sigma_pct = (result.sigma or 0.0) * 100
    reason = f"{VOL_TRIM_REASON_PREFIX} σ={sigma_pct:.0f}%>{vt * 100:.0f}% ×{factor:.2f}"
    trims: list[TargetTrade] = []
    for p in held:
        px = prices[p.ticker]
        current_value = p.shares * px
        trim_value = current_value * (1.0 - factor)
        if trim_value < dust:
            continue
        trim_shares = min(float(p.shares), trim_value / px)
        if trim_shares <= 1e-9:
            continue
        trims.append(
            TargetTrade(
                ticker=p.ticker,
                side="SELL",
                target_shares=trim_shares,
                target_dollars=float(trim_value),
                reason=reason,
                source=source,
                signal_score=None,  # risk housekeeping, not a conviction trade
            )
        )
    if trims:
        get_logger(__name__).info(
            "vol_overlay trim (%s): σ=%.1f%% > target %.1f%%, trimming %d held position(s) ×%.2f",
            source,
            sigma_pct,
            vt * 100,
            len(trims),
            factor,
        )
    return trims


# ── Strategy 1: analyze_single ────────────────────────────────────────────────


def _default_strength(signal: str, ml_probability: float | None) -> float:
    """Conviction score in [0,1] for ranking BUY candidates."""
    if ml_probability is not None and np.isfinite(ml_probability):
        return float(max(0.0, min(1.0, ml_probability)))
    return {"BUY": 1.0, "HOLD": 0.5, "SELL": 0.0}.get(signal, 0.0)


def _universe_thresholds():
    """E1b thresholds when the screen is on, else ``None`` (screen disabled).

    Returning ``None`` when the master switch is off keeps the BUY loop on its
    exact legacy path (no ADV/EDGAR work, no behavior change).
    """
    from paper_trading.universe import UniverseThresholds, screen_enabled

    if not screen_enabled():
        return None
    return UniverseThresholds.from_settings()


def _screen_out_candidate(ticker: str, df: "pd.DataFrame", thresholds) -> bool:
    """True → drop this BUY candidate (E1b). Logs the reason. Never raises.

    Liquidity (ADV$, from the already-fetched history) is checked first so an
    illiquid microcap is dropped without an EDGAR round-trip. Fundamentals are
    fetched only when the liquidity leg passes and the fundamentals leg is on.
    Fail-open: any error keeps the candidate.
    """
    from paper_trading.gates import recent_adv_dollars
    from paper_trading.universe import screen_candidate

    try:
        lookback = int(settings.get("paper_adv_lookback_days"))
        adv = recent_adv_dollars(df, lookback_days=lookback)
        liquidity_excluded = (
            thresholds.min_adv_dollars > 0
            and adv is not None
            and adv < thresholds.min_adv_dollars
        )
        facts = None
        if thresholds.fundamentals_enabled and not liquidity_excluded:
            from data.edgar_fundamentals import get_fundamental_facts

            facts = get_fundamental_facts(ticker)
        verdict = screen_candidate(ticker, adv, facts, thresholds)
        if verdict.excluded:
            get_logger(__name__).info(
                "E1b: candidato BUY %s excluido (%s) — %s",
                ticker,
                verdict.reason,
                verdict.detail,
            )
            return True
        return False
    except Exception:
        get_logger(__name__).exception("E1b screen falló para %s — se conserva", ticker)
        return False


def generate_trades_analyze_single(
    account: PaperAccount,
    watchlist: list[str],
    positions: list[PaperPosition],
    prices: dict[str, float],
    history_provider: HistoryProvider,
) -> list[TargetTrade]:
    """
    Run ``analyze()`` on every watchlist ticker and every open position.

    Rules:
      * Any open position whose overall_signal is SELL  → full-shares SELL.
      * Any candidate (not yet held) whose overall_signal is BUY
        → enters a ranked list; top (max_positions − held_after_sells)
          candidates are bought with equal slices of remaining cash.
    """
    from analysis.technical import analyze

    source = "analyze_single"
    trades: list[TargetTrade] = []

    held_tickers = {p.ticker for p in positions}
    # Positions with available history get evaluated for SELL; otherwise held.
    forced_exits: set[str] = set()

    for pos in positions:
        df = history_provider(pos.ticker)
        if df is None or df.empty:
            continue
        res = analyze(pos.ticker, df)
        if res is None:
            continue
        if res.overall_signal == "SELL":
            score = _default_strength("SELL", res.ml_probability)
            trades.append(
                TargetTrade(
                    ticker=pos.ticker,
                    side="SELL",
                    target_shares=float(pos.shares),
                    target_dollars=None,
                    reason=f"analyze SELL ({res.ml_probability or 0:.2f})",
                    source=source,
                    signal_score=score,
                )
            )
            forced_exits.add(pos.ticker)

    # ── Active de-risking (T09) — trim the held book toward σ target ──────────
    # Runs BEFORE the BUY pipeline (and its ``if not picks: return`` early exit)
    # so an over-volatile book is de-risked even on scans with no new entries.
    # Opt-in via ``vol_overlay_trim_enabled`` (default off → no behavior change).
    trim_pv = float(
        account.cash
        + sum(p.shares * (prices.get(p.ticker, p.avg_cost) or p.avg_cost) for p in positions)
    )
    trades.extend(
        _vol_overlay_trim_sells(positions, forced_exits, prices, trim_pv, history_provider, source)
    )

    # Candidates for BUY — ranked by conviction. We also stash each candidate's
    # realised vol and calibrated probability so the vol-target / Kelly sizing
    # modes (T06) have what they need without re-running analyze().
    ranked: list[tuple[float, str]] = []
    cand_vol: dict[str, float] = {}
    cand_prob: dict[str, float | None] = {}
    # Sprint 4 / T05 — keep a per-candidate close series so we can compute a
    # cross-sectional momentum percentile when ``cross_sectional_enabled`` is on.
    cand_close: dict[str, pd.Series] = {}
    # E1b — universe quality/liquidity screen. Only built (and only touching
    # EDGAR) when the master switch is on; OFF → screen_thresholds stays None and
    # the loop behaves exactly as before. Applied to BUY *candidates* only, so
    # held positions keep getting their SELL/stop evaluation upstream.
    screen_thresholds = _universe_thresholds()
    for t in watchlist:
        if t in held_tickers and t not in forced_exits:
            continue
        df = history_provider(t)
        if df is None or df.empty:
            continue
        res = analyze(t, df)
        if res is None:
            continue
        if res.overall_signal == "BUY":
            if screen_thresholds is not None and _screen_out_candidate(t, df, screen_thresholds):
                continue
            strength = _default_strength("BUY", res.ml_probability)
            ranked.append((strength, t))
            cand_vol[t] = _realized_vol(df["Close"].astype(float)) if "Close" in df.columns else 0.0
            cand_prob[t] = _calibrated_prob(res.ml_probability)
            if "Close" in df.columns:
                cand_close[t] = df["Close"].astype(float)

    # Sprint 4 / T05 — blend absolute strength with cross-sectional momentum
    # percentile when toggle is on. Toggle OFF preserves the legacy ordering
    # (sort by absolute strength) exactly.
    if ranked and bool(settings.get("cross_sectional_enabled", False)):
        from analysis.ranking import blended_scores
        lookback = max(2, int(settings.get("cross_sectional_lookback", 120)))
        weight = float(settings.get("cross_sectional_weight", 0.5))
        weight = min(1.0, max(0.0, weight))
        absolute = {t: s for s, t in ranked}
        blended = blended_scores(absolute, cand_close, lookback, weight)
        ranked = [(blended.get(t, s), t) for s, t in ranked]

    ranked.sort(reverse=True)
    scores = {t: s for s, t in ranked}

    # Slots available after processing forced exits
    held_after = held_tickers - forced_exits
    free_slots = max(0, account.max_positions - len(held_after))
    # Correlation gate removed in Sprint 3 (2026-05-29). The gate never rejected
    # a candidate in any realistic harness setup because analyze_stacked produces
    # 1-2 BUYs per step. Picks now come straight from the ranked list, truncated
    # to free_slots. See docs/sprint2_kill_criteria.md (Enmienda 2).
    picks = [t for _, t in ranked][:free_slots]

    if not picks:
        return trades

    # Size: equal slices of (cash + proceeds from any forced sells we estimate)
    est_proceeds = 0.0
    for pos in positions:
        if pos.ticker in forced_exits:
            px = prices.get(pos.ticker, pos.avg_cost)
            est_proceeds += pos.shares * (px or pos.avg_cost) * (1 - account.commission)
    available = account.cash + est_proceeds
    if available <= 0:
        return trades

    # ── Per-pick target dollars under the active sizing mode ──────────────────
    # T06 vol-target / Kelly size by per-name vol (and calibrated prob); the
    # other modes use a fixed amount or an equal cash slice. Either way we end
    # up with a {ticker: dollars} map, which the T10 portfolio-vol overlay can
    # then scale down as one book before the trades are emitted.
    portfolio_value = float(
        account.cash
        + sum(p.shares * (prices.get(p.ticker, p.avg_cost) or p.avg_cost) for p in positions)
    )
    if account.allocation_mode in _VOL_SIZED_MODES:
        mode = AllocationMode(account.allocation_mode)
        weights = _compute_target_weights(
            picks,
            {t: scores.get(t, 0.0) for t in picks},
            {t: cand_vol.get(t, 0.0) for t in picks},
            mode,
            probs={t: cand_prob.get(t) for t in picks},
            **_sizing_params(),
        )
        dollars = {t: weights.get(t, 0.0) * portfolio_value for t in picks}
        total = sum(dollars.values())
        if total > available > 0:
            scale = available / total
            dollars = {t: v * scale for t, v in dollars.items()}
        reason = f"analyze BUY ({account.allocation_mode})"
    elif account.allocation_mode == "fixed_amount":
        target_per = float(account.fixed_amount)
        total = target_per * len(picks)
        if total > available:
            target_per = available / len(picks)  # scale down
        dollars = {t: target_per for t in picks}
        reason = "analyze BUY"
    else:
        target_per = available / len(picks)
        dollars = {t: target_per for t in picks}
        reason = "analyze BUY"

    # ── Portfolio volatility overlay (T10) — shared layer, applied after sizing ─
    dollars = _apply_vol_overlay_to_buys(
        dollars, picks, positions, forced_exits, prices, portfolio_value, history_provider, source
    )

    for t in picks:
        d = dollars.get(t, 0.0)
        if d <= 0:  # Kelly may skip a pick; overlay may shrink a tiny slice
            continue
        trades.append(
            TargetTrade(
                ticker=t,
                side="BUY",
                target_shares=None,
                target_dollars=float(d),
                reason=reason,
                source=source,
                signal_score=scores.get(t),
            )
        )

    return trades


# ── Strategy 2: portfolio_engine ──────────────────────────────────────────────


def _signal_for(ticker: str, df: pd.DataFrame) -> tuple[str, float, float | None]:
    """Call analyze() and return (signal, strength, calibrated_prob).

    ``calibrated_prob`` is the raw ml_probability when finite, else None — kept
    separate from ``strength`` (which collapses None to a BUY/HOLD/SELL prior)
    so Kelly sizing can skip names without a real probability.
    """
    from analysis.technical import analyze

    res = analyze(ticker, df)
    if res is None:
        return "HOLD", 0.5, None
    return (
        res.overall_signal,
        _default_strength(res.overall_signal, res.ml_probability),
        _calibrated_prob(res.ml_probability),
    )


def generate_trades_portfolio_engine(
    account: PaperAccount,
    watchlist: list[str],
    positions: list[PaperPosition],
    prices: dict[str, float],
    history_provider: HistoryProvider,
) -> list[TargetTrade]:
    """
    One step of the portfolio-backtest loop, executed against live state.

    Computes signals for every watchlist ticker, determines mandatory exits,
    fills up to ``max_positions`` slots with the top-ranked BUYs, computes
    target weights per the account's allocation mode, then emits trades only
    if at least one trigger fires:

      • signal change (any SELL on position or BUY on free slot)
      • drift > ``account.drift_threshold``
      • monthly safety net (first scan of a new month, if enabled)
    """
    source = "portfolio_engine"
    trades: list[TargetTrade] = []

    # ── Compute signals, strengths & vols for every ticker we care about ─────
    universe = sorted(set(watchlist) | {p.ticker for p in positions})
    signals: dict[str, str] = {}
    strengths: dict[str, float] = {}
    vols: dict[str, float] = {}
    probs: dict[str, float | None] = {}
    dfs: dict[str, pd.DataFrame] = {}

    for t in universe:
        df = history_provider(t)
        if df is None or df.empty or "Close" not in df.columns:
            signals[t] = "HOLD"
            strengths[t] = 0.0
            vols[t] = 0.0
            probs[t] = None
            continue
        dfs[t] = df
        sig, sv, mlp = _signal_for(t, df)
        signals[t] = sig
        strengths[t] = sv
        vols[t] = _realized_vol(df["Close"].astype(float))
        probs[t] = mlp

    # ── Forced exits (positions with SELL) ────────────────────────────────────
    held_tickers = {p.ticker: p for p in positions}
    forced_exits = [t for t, p in held_tickers.items() if signals.get(t) == "SELL"]

    # ── Fill free slots with top-ranked BUY candidates ────────────────────────
    still_held = [t for t in held_tickers if t not in forced_exits]
    free_slots = max(0, account.max_positions - len(still_held))
    candidate_pool = [
        t for t in watchlist
        if signals.get(t) == "BUY" and t not in still_held and t not in forced_exits
    ]
    # Sprint 4 / T05 — blend absolute strength with cross-sectional momentum
    # percentile when the toggle is on; toggle OFF preserves the legacy sort key.
    rank_key = strengths
    if candidate_pool and bool(settings.get("cross_sectional_enabled", False)):
        from analysis.ranking import blended_scores
        lookback = max(2, int(settings.get("cross_sectional_lookback", 120)))
        weight = float(settings.get("cross_sectional_weight", 0.5))
        weight = min(1.0, max(0.0, weight))
        closes_at_bar = {
            t: dfs[t]["Close"].astype(float)
            for t in universe
            if t in dfs and "Close" in dfs[t].columns
        }
        rank_key = blended_scores(
            {t: strengths.get(t, 0.0) for t in candidate_pool},
            closes_at_bar,
            lookback,
            weight,
        )
    candidates = sorted(
        candidate_pool,
        key=lambda t: rank_key.get(t, strengths.get(t, 0.0)),
        reverse=True,
    )
    # Correlation gate removed in Sprint 3 — see strategy_analyze_single above.
    new_entries = candidates[:free_slots]
    active = still_held + new_entries

    # ── Current portfolio value (mark-to-market) ──────────────────────────────
    pos_value = 0.0
    for p in positions:
        px = prices.get(p.ticker, p.avg_cost)
        pos_value += p.shares * (px or p.avg_cost)
    portfolio_val = float(account.cash + pos_value)
    if portfolio_val <= 0:
        return trades

    # ── Target dollars per ticker ─────────────────────────────────────────────
    alloc = AllocationMode(account.allocation_mode)
    if alloc == AllocationMode.FIXED_AMOUNT:
        target_dollars = {t: float(account.fixed_amount) for t in active}
        total = sum(target_dollars.values())
        if total > portfolio_val > 0:
            scale = portfolio_val / total
            target_dollars = {t: v * scale for t, v in target_dollars.items()}
        target_weights = {t: v / portfolio_val for t, v in target_dollars.items()}
    else:
        target_weights = _compute_target_weights(
            active,
            strengths,
            vols,
            alloc,
            probs=probs,
            **_sizing_params(),
        )
        target_dollars = {t: target_weights.get(t, 0.0) * portfolio_val for t in universe}

    # ── Portfolio volatility overlay (T10) ────────────────────────────────────
    # Shared risk layer over whatever the allocation mode produced: if the
    # active book's annualised σ exceeds ``vol_target_portfolio_annual``, scale
    # every active weight down proportionally (long-only, residual → cash).
    vt = _portfolio_vol_target()
    if vt > 0 and active:
        active_w = {t: target_weights.get(t, 0.0) for t in active}
        ret_df = returns_frame(active, history_provider)
        scaled, sigma_port, factor = apply_portfolio_vol_overlay(active_w, ret_df, vt)
        if factor < 1.0:
            get_logger(__name__).info(
                "portfolio vol overlay (%s): σ=%.1f%% > target %.1f%%, scaled book ×%.2f",
                source,
                (sigma_port or 0.0) * 100,
                vt * 100,
                factor,
            )
            for t in active:
                target_weights[t] = scaled.get(t, 0.0)
                target_dollars[t] = target_weights[t] * portfolio_val

    # Tickers to liquidate entirely
    for t in list(held_tickers):
        if t not in active:
            target_dollars[t] = 0.0
            target_weights[t] = 0.0

    # ── Triggers ──────────────────────────────────────────────────────────────
    # Signal-based: any forced exit or new entry counts.
    signal_trigger = bool(forced_exits) or bool(new_entries)

    # Drift: any active position deviates from target by > drift_threshold.
    drift_trigger = False
    for t, w_target in target_weights.items():
        p = held_tickers.get(t)
        px = prices.get(t)
        if p is None or px is None:
            continue
        actual_w = (p.shares * px) / portfolio_val
        if w_target <= 0:
            if actual_w > account.drift_threshold:
                drift_trigger = True
                break
            continue
        rel_drift = abs(actual_w - w_target) / w_target
        if rel_drift > account.drift_threshold:
            drift_trigger = True
            break

    # Monthly: first scan of a new month.
    month_trigger = False
    if account.monthly_rebalance:
        now = utcnow_naive()
        last = account.last_monthly_rebalance
        if last is None or (last.year, last.month) != (now.year, now.month):
            month_trigger = True

    if not (signal_trigger or drift_trigger or month_trigger):
        return trades  # no action this scan

    reason_parts = []
    if signal_trigger:
        reason_parts.append("signal")
    if drift_trigger:
        reason_parts.append("drift")
    if month_trigger:
        reason_parts.append("monthly")
    reason = "+".join(reason_parts)

    # ── Emit rebalance trades ────────────────────────────────────────────────
    all_tickers = set(target_dollars.keys()) | set(held_tickers.keys())
    for t in sorted(all_tickers):
        px = prices.get(t)
        if px is None or not np.isfinite(px) or px <= 0:
            continue
        current = 0.0
        p = held_tickers.get(t)
        if p is not None:
            current = p.shares * px
        target = float(target_dollars.get(t, 0.0))
        diff = target - current
        if abs(diff) < 1e-2:  # under 1¢ — ignore
            continue
        # Rebalance trades may originate from drift/monthly, where there's no
        # active signal driving the trade — leave signal_score=None in that
        # case so analytics can distinguish "conviction trade" from "housekeeping".
        score = strengths.get(t) if signals.get(t) in ("BUY", "SELL") else None
        if diff > 0:
            trades.append(
                TargetTrade(
                    ticker=t,
                    side="BUY",
                    target_shares=None,
                    target_dollars=float(diff),
                    reason=reason,
                    source=source,
                    signal_score=score,
                )
            )
        else:
            # SELL — convert dollar deficit to shares for clarity
            sell_shares = min(p.shares if p else 0.0, (-diff) / px)
            if sell_shares <= 1e-9:
                continue
            trades.append(
                TargetTrade(
                    ticker=t,
                    side="SELL",
                    target_shares=float(sell_shares),
                    target_dollars=float(-diff),
                    reason=reason,
                    source=source,
                    signal_score=score,
                )
            )

    return trades


# ── Dispatch table ────────────────────────────────────────────────────────────

STRATEGY_FNS: dict[str, Callable] = {
    "analyze_single": generate_trades_analyze_single,
    "portfolio_engine": generate_trades_portfolio_engine,
}


def get_strategy_fn(name: str) -> Callable:
    try:
        return STRATEGY_FNS[name]
    except KeyError:
        raise ValueError(f"Estrategia desconocida: {name!r}") from None
