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

from analysis.surprise_score import MIN_QUARTERS, PROFILES_PATH, build_surprise_profile
from config.logging_config import get_logger
from data.news_sources import collect_yfinance_earnings_history
from scripts.harvest_catalysts import DEFAULT_ACCOUNT_ID, resolve_universe

log = get_logger(__name__)

# La ruta la declara `analysis.surprise_score` (tarea 160): la cadencia del
# scheduler se lee del `_meta.built_at` de ESTE archivo, así que el que lo escribe
# y el que lo lee tienen que hablar del mismo path o la marca no se ve.
DEFAULT_OUT = PROFILES_PATH


def build_profiles(tickers: list[str], limit: int = 16) -> dict[str, dict]:
    profiles: dict[str, dict] = {}
    for t in tickers:
        rows = collect_yfinance_earnings_history(t, limit=limit)
        prof = build_surprise_profile(t, rows)
        profiles[t] = prof.to_dict()
        log.info(
            "surprise %s: n=%d dir=%.3f beat=%.2f mean=%.3f",
            t,
            prof.n_quarters,
            prof.directional_score,
            prof.beat_rate,
            prof.mean_surprise,
        )
    return profiles


def split_by_min_quarters(profiles: dict[str, dict]) -> tuple[dict[str, dict], dict[str, int]]:
    """Separa los perfiles **usables** de los que no llegan al mínimo — Tarea 126.

    El archivo declaraba ``min_quarters`` en su ``_meta`` y escribía igual los que no
    lo alcanzan, **con todos los campos en cero**. Producción no se veía afectada —
    ``SurpriseProfile.is_usable`` y el gate de ``imminent_catalyst`` los descartan y
    caen al ``basis="reaction"``— pero **cualquier lectura ad-hoc del JSON** ve un
    ``directional_score: 0.0`` que es indistinguible de un neutral medido sobre 24
    trimestres. Un archivo que declara un filtro tiene que cumplirlo.

    No se tiran: van a ``_meta.insufficient_history`` con su ``n_quarters``, para no
    perder el *"se intentó y no había datos"* — que es distinto de *"no se intentó"*.
    """
    usables = {t: p for t, p in profiles.items() if p.get("n_quarters", 0) >= MIN_QUARTERS}
    cortos = {t: int(p.get("n_quarters", 0)) for t, p in profiles.items() if t not in usables}
    return usables, cortos


def _payload(profiles: dict[str, dict], n_tickers: int) -> dict:
    usables, cortos = split_by_min_quarters(profiles)
    return {
        "_meta": {
            "built_at": datetime.now(timezone.utc).isoformat(),
            "source": "yfinance.get_earnings_dates",
            "version": "v0-free-T-CAT-5a",
            "caveat": "current-estimate per quarter, not point-in-time (T-CAT-5b replaces this)",
            "min_quarters": MIN_QUARTERS,
            "n_tickers": n_tickers,
            # `n_tickers` es cuántos se INTENTARON; `n_profiles` cuántos entraron.
            # Antes coincidían porque entraban todos, incluidos los que no llegaban
            # al mínimo — que es justo lo que la 126 vino a cerrar.
            "n_profiles": len(usables),
            "insufficient_history": cortos,
        },
        "profiles": usables,
    }


def run_build(
    account_id: int | None = DEFAULT_ACCOUNT_ID,  # T70: None => la cuenta viva
    limit: int = 16,
    out: str | Path = DEFAULT_OUT,
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
    # `newline` explicito (tarea 173): este JSON esta VERSIONADO y el repo lo guarda en LF.
    # Sin esto, `write_text` traduce cada salto a CRLF en Windows y el archivo queda
    # desalineado contra su blob en cada corrida del scheduler. Mismo arreglo que la 165,
    # que a este writer lo habia excluido llamandolo "artefacto no versionado".
    out_path.write_text(
        json.dumps(_payload(profiles, len(tickers)), indent=2), encoding="utf-8", newline="\n"
    )
    n_usable = sum(1 for p in profiles.values() if p.get("n_quarters", 0) >= MIN_QUARTERS)
    return {"out": str(out_path), "n_tickers": len(tickers), "n_usable": n_usable, "profiles": profiles}


def _print_summary(profiles: dict[str, dict]) -> None:
    rows = [(t, p) for t, p in profiles.items() if p.get("n_quarters", 0) >= MIN_QUARTERS]
    rows.sort(key=lambda r: r[1].get("directional_score", 0.0), reverse=True)
    print(f"\nSurprise profiles (n ≥ {MIN_QUARTERS} quarters), by directional score:")
    print(f"  {'ticker':<8} {'n':>3} {'dir':>7} {'beat%':>7} {'meanSurp':>9} {'lastSurp':>9}")
    for t, p in rows:
        print(
            f"  {t:<8} {p['n_quarters']:>3} {p['directional_score']:>7.3f} "
            f"{p['beat_rate'] * 100:>6.1f}% {p['mean_surprise'] * 100:>8.2f}% "
            f"{p['last_surprise'] * 100:>8.2f}%"
        )
    skipped = len(profiles) - len(rows)
    if skipped:
        print(f"  ({skipped} ticker(s) with < {MIN_QUARTERS} usable quarters → neutral, omitted)")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="T-CAT-5a surprise-profile builder (v0 free).")
    p.add_argument(
        "--account-id", type=int, default=DEFAULT_ACCOUNT_ID, help="Account whose universe to use."
    )
    p.add_argument("--limit", type=int, default=16, help="Max past quarters to pull per ticker.")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="Output JSON path.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    res = run_build(account_id=args.account_id, limit=args.limit, out=args.out)
    print(
        f"Wrote {res['out']} — {res['n_tickers']} tickers, "
        f"{res['n_usable']} with ≥ {MIN_QUARTERS} usable quarters."
    )
    _print_summary(res["profiles"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
