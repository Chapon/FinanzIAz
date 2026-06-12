"""
T-CAT-5a builder — per-ticker EPS surprise profiles (v0 *gratis*).

Sprint 5 · Catalyst Intelligence Engine. For each ticker in the account's
universe (watchlist ∪ open positions) it fetches the past-earnings surprise
history from yfinance, aggregates it into a :class:`SurpriseProfile`, and writes
a JSON snapshot consumed at runtime by ``imminent_catalyst`` (the exit-veto's
directional prior). Prints a summary ranked by directional score.

Network-bound (yfinance) and read-only on the DB (only resolves the universe).
Safe to run anytime; intended cadence is roughly weekly — surprise track records
move only when a new quarter prints.

⚠️  v0 caveat: yfinance reports its *current* estimate per past quarter, not the
consensus as of the day before the print (revision/look-ahead bias). The clean
point-in-time path is T-CAT-5b (blocked until the daily ``analyst_estimate_snapshots``
accumulate one earnings season). See docs/roadmap_v3_2026-06-09.md.

Usage
-----
    python scripts/build_surprise_profiles.py
    python scripts/build_surprise_profiles.py --account-id 1 --limit 16
    python scripts/build_surprise_profiles.py --out data/catalyst/surprise_profiles.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.surprise_score import MIN_QUARTERS, build_surprise_profile  # noqa: E402
from config.logging_config import get_logger  # noqa: E402
from data.news_sources import collect_yfinance_earnings_history  # noqa: E402
from scripts.harvest_catalysts import DEFAULT_ACCOUNT_ID, resolve_universe  # noqa: E402

log = get_logger(__name__)

DEFAULT_OUT = ROOT / "data" / "catalyst" / "surprise_profiles.json"


def build_profiles(tickers: list[str], limit: int = 16) -> dict[str, dict]:
    profiles: dict[str, dict] = {}
    for t in tickers:
        rows = collect_yfinance_earnings_history(t, limit=limit)
        prof = build_surprise_profile(t, rows)
        profiles[t] = prof.to_dict()
        log.info("surprise %s: n=%d dir=%.3f beat=%.2f mean=%.3f",
                 t, prof.n_quarters, prof.directional_score, prof.beat_rate, prof.mean_surprise)
    return profiles


def _payload(profiles: dict[str, dict], n_tickers: int) -> dict:
    return {
        "_meta": {
            "built_at": datetime.now(timezone.utc).isoformat(),
            "source": "yfinance.get_earnings_dates",
            "version": "v0-free-T-CAT-5a",
            "caveat": "current-estimate per quarter, not point-in-time (T-CAT-5b replaces this)",
            "min_quarters": MIN_QUARTERS,
            "n_tickers": n_tickers,
        },
        "profiles": profiles,
    }


def run_build(
    account_id: int = DEFAULT_ACCOUNT_ID,
    limit: int = 16,
    out: "str | Path" = DEFAULT_OUT,
) -> dict:
    """Resolve the universe, build every profile, write the JSON snapshot.

    Single source of truth shared by the CLI (``main``) and the in-app weekly
    scheduler worker (``paper_trading.scheduler.SurpriseBuildWorker``). Returns a
    small result dict: ``{"out", "n_tickers", "n_usable", "profiles"}``. Network-
    bound (yfinance) and read-only on the DB (only resolves the universe).
    """
    tickers = resolve_universe(account_id)
    log.info("building surprise profiles for %d tickers", len(tickers))
    profiles = build_profiles(tickers, limit=limit)

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(_payload(profiles, len(tickers)), indent=2), encoding="utf-8")
    n_usable = sum(1 for p in profiles.values() if p.get("n_quarters", 0) >= MIN_QUARTERS)
    return {"out": str(out_path), "n_tickers": len(tickers), "n_usable": n_usable, "profiles": profiles}


def _print_summary(profiles: dict[str, dict]) -> None:
    rows = [(t, p) for t, p in profiles.items() if p.get("n_quarters", 0) >= MIN_QUARTERS]
    rows.sort(key=lambda r: r[1].get("directional_score", 0.0), reverse=True)
    print(f"\nSurprise profiles (n ≥ {MIN_QUARTERS} quarters), by directional score:")
    print(f"  {'ticker':<8} {'n':>3} {'dir':>7} {'beat%':>7} {'meanSurp':>9} {'lastSurp':>9}")
    for t, p in rows:
        print(f"  {t:<8} {p['n_quarters']:>3} {p['directional_score']:>7.3f} "
              f"{p['beat_rate']*100:>6.1f}% {p['mean_surprise']*100:>8.2f}% "
              f"{p['last_surprise']*100:>8.2f}%")
    skipped = len(profiles) - len(rows)
    if skipped:
        print(f"  ({skipped} ticker(s) with < {MIN_QUARTERS} usable quarters → neutral, omitted)")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="T-CAT-5a surprise-profile builder (v0 free).")
    p.add_argument("--account-id", type=int, default=DEFAULT_ACCOUNT_ID, help="Account whose universe to use.")
    p.add_argument("--limit", type=int, default=16, help="Max past quarters to pull per ticker.")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="Output JSON path.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    res = run_build(account_id=args.account_id, limit=args.limit, out=args.out)
    print(f"Wrote {res['out']} — {res['n_tickers']} tickers, "
          f"{res['n_usable']} with ≥ {MIN_QUARTERS} usable quarters.")
    _print_summary(res["profiles"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
