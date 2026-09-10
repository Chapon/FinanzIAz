"""
Refresca el cohorte de artefactos Parquet del universo vivo — **tarea 155**.

Existía como operación pero **no como script**: la T30 y la T68 la hicieron a mano, y
por eso el 2026-09-09, haciéndola a mano otra vez, se refrescó **AVB** —que está en
``ARTIFACT_REFRESH_EXCEPTIONS`` precisamente porque refrescarlo es destructivo (tarea
63)— y se perdió su histórico de forma **irreversible**: Yahoo devuelve 27 filas para
cualquier período, así que no se recupera bajándolo de nuevo.

**El invariante que este script existe para sostener:** un ticker declarado como
excepción de refresh **no se refresca**, y la única forma de hacerlo es pedirlo
explícitamente por nombre con ``--force``. Una operación destructiva no puede quedar a
un paso de distancia de la operación normal.

Después de refrescar, el store de señales PIT queda **atrás del cohorte** y hay que
recomputarlo antes de correr cualquier harness (T111/T117), y las constantes de
reproducción quedan **INDETERMINADAS** porque la ventana se movió (T48/T68). El script
lo dice al final en vez de dejarlo para que alguien se acuerde.

Uso:
    python scripts/refresh_cohort.py --dry-run          # qué haría, sin bajar nada
    python scripts/refresh_cohort.py                    # refresca el universo vivo (10y)
    python scripts/refresh_cohort.py --period 2y
    python scripts/refresh_cohort.py --force AVB        # a sabiendas, contra la excepción
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))

from analysis.harness_config import (
    ARTIFACT_REFRESH_EXCEPTIONS,
    LIVE_UNIVERSE_FILE,
)


def universo_vivo(path: Path) -> list[str]:
    """Los tickers del archivo de universo, sin comentarios ni vacíos."""
    return [
        ln.strip()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]


def particionar(tickers: list[str], forzados: set[str]) -> tuple[list[str], list[str]]:
    """``(a_refrescar, exentos)``. La excepción declarada gana salvo ``--force``.

    Es el corazón del script y la razón de que exista: la partición tiene que pasar
    **antes** de cualquier llamada a la red, no adentro del loop de descarga.
    """
    a_refrescar, exentos = [], []
    for t in tickers:
        clave = t.upper()
        if clave in ARTIFACT_REFRESH_EXCEPTIONS and clave not in forzados:
            exentos.append(t)
        else:
            a_refrescar.append(t)
    return a_refrescar, exentos


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Refresca el cohorte Parquet del universo vivo.")
    p.add_argument("--period", default="10y", help="período del cohorte (default 10y)")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--tickers", default="", help="CSV que sobreescribe el universo")
    p.add_argument(
        "--force",
        default="",
        help="CSV de tickers a refrescar A SABIENDAS aunque tengan excepción declarada",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    if args.tickers.strip():
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        ruta = Path(args.universe)
        ruta = ruta if ruta.is_absolute() else _ROOT / ruta
        if not ruta.exists():
            print(f"No existe el universo: {ruta}", file=sys.stderr)
            return 2
        tickers = universo_vivo(ruta)

    forzados = {t.strip().upper() for t in args.force.split(",") if t.strip()}
    a_refrescar, exentos = particionar(tickers, forzados)

    print(f"Universo: {len(tickers)} tickers · período {args.period}")
    for t in exentos:
        print(f"  EXENTO {t}: {ARTIFACT_REFRESH_EXCEPTIONS[t.upper()].splitlines()[0].strip()}")
    for t in sorted(forzados & {x.upper() for x in a_refrescar}):
        if t in ARTIFACT_REFRESH_EXCEPTIONS:
            print(f"  FORZADO {t} — se refresca CONTRA su excepción declarada, a pedido explícito")
    print(f"A refrescar: {len(a_refrescar)}")

    if args.dry_run:
        print("\n[dry-run] no se bajó nada.")
        return 0

    from data.yahoo_finance import get_historical_data_batch

    res = get_historical_data_batch(a_refrescar, period=args.period)
    print(f"\nRefrescados: {len(res)} de {len(a_refrescar)}")

    print(
        "\nDESPUÉS DE ESTO, y antes de correr cualquier harness:\n"
        "  1. El store de señales PIT quedó ATRÁS del cohorte (T111/T117). Correr\n"
        "     `python scripts/precompute_pit_signals.py`.\n"
        "     Desde la tarea 158 el default de ese script ES el universo vivo\n"
        f"     ({LIVE_UNIVERSE_FILE}), así que ya no hace falta el flag — antes\n"
        "     apuntaba a un cohorte de 41 y sin `--universe` dejaba 88 tickers sin\n"
        "     recomputar en silencio. El script imprime sobre qué archivo corre:\n"
        "     esa línea es la que hay que mirar.\n"
        "  2. La ventana se movió, así que las constantes de reproducción quedan\n"
        "     INDETERMINADAS (T48). Hay que re-medirlas y re-anclarlas TODAS en el\n"
        "     mismo commit (T68) — actualizar sólo la de ventana convierte un\n"
        "     INDETERMINADO honesto en un FALLA que acusa a la cañería sin evidencia.\n"
        "  3. Si la última barra es de la sesión de HOY sin asentar (T112), esperar al\n"
        "     cierre firme antes de anclar: un cierre provisional mueve las constantes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
