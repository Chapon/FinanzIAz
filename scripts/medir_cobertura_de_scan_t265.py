"""Mide cuántos días hábiles tuvo scan la cuenta viva (tarea 265).

Uso: ``python scripts/medir_cobertura_de_scan_t265.py [--desde AAAA-MM-DD] [--hasta AAAA-MM-DD]``

Lee ``paper_equity_snapshots`` en **solo lectura** (un snapshot = un ``run_scan`` completado) y
cuenta los días hábiles NYSE sin ningún scan y sin ningún scan en sesión. Es lo que alimenta
``SCAN_COBERTURA`` en ``analysis/harness_config.py``, el número del desvío ``barrier_eval``.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.harness_config import cobertura_de_scan
from database.readonly import readonly_uri

# Feriados NYSE 2026 (no hay calendario en el proyecto; ver el docstring de harness_config).
FERIADOS_NYSE_2026 = frozenset(
    date.fromisoformat(d)
    for d in (
        "2026-01-01",
        "2026-01-19",
        "2026-02-16",
        "2026-04-03",
        "2026-05-25",
        "2026-06-19",
        "2026-07-03",
        "2026-09-07",
        "2026-11-26",
        "2026-12-25",
    )
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--desde", default="2026-07-01")
    p.add_argument("--hasta", default=date.today().isoformat())
    p.add_argument("--account", type=int, default=None, help="default: la cuenta viva")
    p.add_argument("--db", default=str(_ROOT / "finanzias.db"))
    a = p.parse_args(argv)
    con = sqlite3.connect(readonly_uri(Path(a.db)), uri=True)
    cuenta = (
        a.account
        or con.execute("SELECT id FROM paper_accounts WHERE is_active=1 ORDER BY id LIMIT 1").fetchone()[0]
    )
    snaps = [
        r[0]
        for r in con.execute("SELECT snapshot_at FROM paper_equity_snapshots WHERE account_id=?", (cuenta,))
    ]
    c = cobertura_de_scan(snaps, a.desde, a.hasta, FERIADOS_NYSE_2026)
    print(f"cuenta {cuenta} · {a.desde} → {a.hasta}: {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
