"""
Prefetch OHLCV data for the harness universe into ``historical_data_cache``.

Why this exists: the harness fetches via ``data.yahoo_finance.get_historical_data``
which silently drops tickers that fail to download (logs a warning and continues
with a shorter universe). For a 70-minute run that's a bad failure mode — better
to discover ticker fetch problems in 5 minutes before kicking off the suite.

Usage:
    python scripts/prefetch_harness_cache.py data/harness_universe_42.txt -p 2y

Output: a table showing which tickers came from cache, which were downloaded
fresh, and which failed. Exits non-zero if any ticker failed so you can stop
before launching the harness.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

from data.yahoo_finance import get_historical_data_batch


def parse_universe_file(path: Path) -> list[str]:
    """Parse one ticker per line, with ``#`` introducing a comment (inline or
    full-line). Commas inside a non-comment line are still allowed as
    separators. Splitting must happen per-line so that commas inside comments
    don't bleed into ticker tokens (the previous version produced bogus
    "REQUIEREN PREFETCH ---" entries from comma-containing comments)."""
    raw = path.read_text(encoding="utf-8")
    tickers: list[str] = []
    for line in raw.splitlines():
        # Strip inline comments first so commas inside comments are ignored.
        if "#" in line:
            line = line.split("#", 1)[0]
        line = line.strip()
        if not line:
            continue
        for tok in line.split(","):
            t = tok.strip().upper()
            if t:
                tickers.append(t)
    # De-dup preserving order
    seen, out = set(), []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "universe_file",
        type=Path,
        help="Path to a file with one ticker per line (comments with # OK).",
    )
    parser.add_argument(
        "-p", "--period",
        default="2y",
        help="Data period to fetch (default: 2y, matches the harness default).",
    )
    parser.add_argument(
        "-i", "--interval",
        default="1d",
        help="Bar interval (default: 1d).",
    )
    parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=20,
        help="Tickers por descarga agrupada (default: 20). Agrupar reutiliza un "
             "único crumb de Yahoo y reduce los 401 'Invalid Crumb'.",
    )
    args = parser.parse_args()

    if not args.universe_file.exists():
        print(f"Error: universe file not found at {args.universe_file}")
        sys.exit(2)

    tickers = parse_universe_file(args.universe_file)
    print(f"Prefetching {len(tickers)} tickers for period={args.period}, interval={args.interval}")
    print("-" * 60)

    rows_per_ticker = {}
    failures: list[str] = []
    started = time.time()

    # Descarga agrupada: los cache-misses se piden en lotes que comparten un
    # único crumb de Yahoo (menos 401). El dict resultante cubre TODOS los
    # tickers pedidos, con None para los que fallaron.
    results = get_historical_data_batch(
        tickers,
        period=args.period,
        interval=args.interval,
        batch_size=args.batch_size,
    )
    for i, t in enumerate(tickers, start=1):
        df = results.get(t.upper())
        if df is None or df.empty:
            print(f"  [{i:>2}/{len(tickers)}] FAIL  {t:<8}")
            failures.append(t)
        else:
            rows_per_ticker[t] = len(df)
            print(f"  [{i:>2}/{len(tickers)}] OK    {t:<8}  rows={len(df):>4}")

    total = time.time() - started
    print("-" * 60)
    print(f"Done in {total:.1f}s")
    print(f"  OK:   {len(rows_per_ticker)}")
    print(f"  FAIL: {len(failures)}")

    if rows_per_ticker:
        min_rows = min(rows_per_ticker.values())
        max_rows = max(rows_per_ticker.values())
        print(f"  Rows range: {min_rows} - {max_rows}")
        if min_rows < 200:
            short = [t for t, n in rows_per_ticker.items() if n < 200]
            print(f"  WARNING: tickers with <200 rows (insufficient for stacking meta-learner): {', '.join(short)}")

    if failures:
        print(f"\nFAILED tickers: {', '.join(failures)}")
        print("These will be silently dropped by the harness. Remove them from")
        print("the universe file or investigate before running the suite.")
        sys.exit(1)

    print("\nAll tickers ready. Safe to launch the harness.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
