"""
Regenera el universo de harness a partir de la watchlist de la cuenta viva —
**Tarea 27 (HARNESS-CFG)**.

Mismo patrón que ``scripts/refresh_sp500_fallback.py`` (UNIV1): el archivo se
regenera con un script en vez de envejecer a mano. Escribe
``data/harness_universe_live_acct2.txt`` con los tickers de la watchlist de la
cuenta viva que **ya tienen artefacto PIT** (``data/pit_signals/``), porque un
ticker sin señal precomputada no puede entrar a ningún harness de la serie.

**Lectura pura de la DB** (``mode=ro``): no escribe ``finanzias.db``. Correr en
Windows (regla 5).

Uso:
    python scripts/refresh_live_universe.py                # cuenta viva (id=2)
    python scripts/refresh_live_universe.py --account-id 1 --out otro.txt
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))

from analysis.harness_config import LIVE_ACCOUNT_ID, LIVE_UNIVERSE_FILE  # noqa: E402

PIT_DIR = "data/pit_signals"


def pit_tickers(pit_dir: Path) -> set[str]:
    """Tickers con artefacto PIT (``TICKER__periodo__wNNN.json``)."""
    if not pit_dir.is_dir():
        return set()
    return {p.name.split("__")[0] for p in pit_dir.glob("*.json")}


def watchlist_tickers(db_path: Path, account_id: int) -> list[str]:
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select distinct ticker from paper_watchlist where account_id = ?",
            (account_id,),
        ).fetchall()
    finally:
        con.close()
    return sorted(r[0] for r in rows if r[0])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Regenera el universo de harness desde la watchlist viva")
    p.add_argument("--account-id", type=int, default=LIVE_ACCOUNT_ID)
    p.add_argument("--db", default="finanzias.db")
    p.add_argument("--out", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    db_path = (_ROOT / args.db) if not Path(args.db).is_absolute() else Path(args.db)
    if not db_path.exists():
        print(f"No existe la DB: {db_path}", file=sys.stderr)
        return 1

    wl = watchlist_tickers(db_path, args.account_id)
    if not wl:
        print(f"La watchlist de la cuenta {args.account_id} está vacía.", file=sys.stderr)
        return 1
    pit = pit_tickers(_ROOT / PIT_DIR)
    keep = [t for t in wl if t in pit]
    missing = [t for t in wl if t not in pit]

    print(f"Watchlist cuenta {args.account_id}: {len(wl)} tickers")
    print(f"Con artefacto PIT: {len(keep)} · sin artefacto: {len(missing)}"
          + (f" ({', '.join(missing)})" if missing else ""))
    if missing:
        print(f"  (para sumarlos: python {PIT_DIR and 'scripts/precompute_pit_signals.py'} "
              f"--tickers {' '.join(missing)})")

    header = [
        f"# Universo de harness = watchlist de la cuenta {args.account_id} "
        f"con artefacto PIT disponible.",
        f"# Generado por scripts/refresh_live_universe.py el {date.today().isoformat()}.",
        f"# {len(keep)}/{len(wl)} tickers de la watchlist."
        + (f" Sin PIT: {', '.join(missing)}." if missing else ""),
        "# NO editar a mano: re-generar con el script.",
    ]
    body = "\n".join(header + keep) + "\n"

    out_path = (_ROOT / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    if args.dry_run:
        print(f"\n[dry-run] no se escribió {out_path}")
        return 0
    out_path.write_text(body, encoding="utf-8")
    print(f"\nEscrito: {out_path} ({len(keep)} tickers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
