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

from analysis.harness_config import cobertura_de_scan, snapshots_de_scan
from database.readonly import readonly_uri

# Feriados NYSE por año (no hay calendario en el proyecto; ver el docstring de harness_config).
# Tarea 395: un año que no está acá no se mide. Un feriado que falta contaría como un día hábil sin
# scan, en silencio: desde el 1/1/2027 eso pasaba con todos los de 2027. Para medir otro año, se
# cargan sus feriados (de la página de la NYSE, no de memoria).
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
FERIADOS_NYSE: dict[int, frozenset[date]] = {2026: FERIADOS_NYSE_2026}


def feriados_para(desde: str, hasta: str) -> frozenset[date]:
    """Los feriados NYSE del rango; ``ValueError`` si toca un año sin feriados cargados (tarea 395)."""
    anios = range(date.fromisoformat(desde).year, date.fromisoformat(hasta).year + 1)
    faltan = [a for a in anios if a not in FERIADOS_NYSE]
    if faltan:
        raise ValueError(
            f"no hay feriados NYSE cargados para {', '.join(map(str, faltan))}: cada feriado contaría "
            "como un día hábil sin scan. Cargarlos en FERIADOS_NYSE antes de medir."
        )
    return frozenset().union(*(FERIADOS_NYSE[a] for a in anios))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--desde", default="2026-07-01")
    p.add_argument("--hasta", default=date.today().isoformat())
    p.add_argument("--account", type=int, default=None, help="default: la cuenta viva")
    p.add_argument("--db", default=str(_ROOT / "finanzias.db"))
    a = p.parse_args(argv)
    try:
        feriados = feriados_para(a.desde, a.hasta)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    con = sqlite3.connect(readonly_uri(Path(a.db)), uri=True)
    cuenta = (
        a.account
        or con.execute("SELECT id FROM paper_accounts WHERE is_active=1 ORDER BY id LIMIT 1").fetchone()[0]
    )
    snaps, a_costo = snapshots_de_scan(con, cuenta)
    c = cobertura_de_scan(snaps, a.desde, a.hasta, feriados, sin_evaluar=a_costo)
    print(f"cuenta {cuenta} · {a.desde} → {a.hasta}: {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
