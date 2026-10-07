"""Completa empresa y sector de una cartera real desde ``company_info_cache`` (tarea 329).

Sin red: usa lo que la app ya guardó. Sólo toca posiciones sin nombre o con un símbolo en lugar
de nombre («ERJ» en EMBJ); un nombre escrito a mano no se pisa.

Por default es **dry-run**. Con ``--aplicar`` escribe, **con la app cerrada** y desde Windows.

    python scripts/completar_nombres_cartera.py
    python scripts/completar_nombres_cartera.py --aplicar
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Completa los nombres de empresa de una cartera real (tarea 329)."
    )
    p.add_argument("--cartera", default="Mis Acciones")
    p.add_argument("--aplicar", action="store_true", help="escribir (sin esto, dry-run)")
    args = p.parse_args(argv)

    from database.cartera_real import completar_nombres
    from database.models import Portfolio, get_session, init_db

    init_db()
    s = get_session()
    try:
        pf = s.query(Portfolio).filter(Portfolio.name == args.cartera).first()
        if pf is None:
            print(f"No existe la cartera '{args.cartera}'.")
            return 1
        cambios = completar_nombres(s, pf.id)
        for t, antes, despues in cambios:
            print(f"{t:6} {antes or '(vacío)'!s:20} -> {despues}")
        if not cambios:
            print("Nada que completar.")
        if args.aplicar and cambios:
            s.commit()
            print(f"\nEscritos {len(cambios)} nombre(s).")
        else:
            s.rollback()
            if cambios:
                print("\nDry-run: no se escribió nada. Con --aplicar se guardan.")
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
