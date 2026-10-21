"""
Arma el almacén de fundamentals point-in-time desde EDGAR — **tarea 382**.

Para cada ticker del universo baja ``companyfacts`` de su CIK actual y de sus predecesores
(``data.fundamentos_pit.CIK_PREDECESORES``), lo guarda en ``data/fundamentals_pit/`` y al final
imprime la **cobertura**: por concepto, cuántos tickers tienen al menos ``--min-anios`` años
anuales conocidos a hoy. Un concepto que cubre menos del 80% se marca, y las tareas que lo usan
lo heredan dicho.

Pega a la red (la SEC, a menos de 10 pedidos por segundo). No toca la DB.

Uso:
    python scripts/build_fundamentals_pit.py
    python scripts/build_fundamentals_pit.py --tickers KO JPM
    python scripts/build_fundamentals_pit.py --solo-cobertura
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

MIN_ANIOS = 8
UMBRAL_COBERTURA = 0.80


def cobertura(fundamentos: dict, fecha: str, min_anios: int = MIN_ANIOS) -> dict[str, tuple[int, list[str]]]:
    """Pura: por concepto, cuántos tickers llegan a ``min_anios`` y cuáles no (con cuántos tienen)."""
    from data.fundamentos_pit import CONCEPTOS, anios_cubiertos

    out = {}
    for c in CONCEPTOS:
        faltan = []
        ok = 0
        for t, f in sorted(fundamentos.items()):
            n = anios_cubiertos(f, c, fecha) if f is not None else 0
            if n >= min_anios:
                ok += 1
            else:
                faltan.append(f"{t}:{n}")
        out[c] = (ok, faltan)
    return out


def main(argv: list[str] | None = None) -> int:
    from analysis.harness_config import LIVE_UNIVERSE_FILE
    from data import fundamentos_pit as fp
    from scripts.precompute_pit_signals import parse_universe_file

    p = argparse.ArgumentParser(description="Fundamentals PIT desde EDGAR (tarea 382)")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--min-anios", type=int, default=MIN_ANIOS)
    p.add_argument("--solo-cobertura", action="store_true", help="no baja nada: lee el almacén")
    args = p.parse_args(argv)

    tickers = (
        [t.upper() for t in args.tickers] if args.tickers else parse_universe_file(_ROOT / args.universe)
    )
    fundamentos = {}
    if args.solo_cobertura:
        fundamentos = {t: fp.cargar(t) for t in tickers}
    else:
        from data.news_sources import _sec_session

        sess = _sec_session()
        for i, t in enumerate(tickers, 1):
            f = fp.construir(t, session=sess)
            fundamentos[t] = f
            if f is not None:
                fp.guardar(f)
            print(f"[{i}/{len(tickers)}] {t}: {len(f.registros) if f else 'SIN DATOS'}", file=sys.stderr)

    manana = (date.today() + timedelta(days=1)).isoformat()
    print(f"Cobertura a hoy: tickers con ≥{args.min_anios} años anuales, sobre {len(tickers)}")
    for c, (ok, faltan) in cobertura(fundamentos, manana, args.min_anios).items():
        marca = "" if ok >= UMBRAL_COBERTURA * len(tickers) else f"  ← DEBAJO DEL {UMBRAL_COBERTURA:.0%}"
        print(f"  {c:<20} {ok:>4}/{len(tickers)}{marca}")
        if faltan:
            print(f"      sin llegar: {', '.join(faltan)}")
    extranjeras = sorted(t for t, f in fundamentos.items() if f is not None and f.extranjera)
    print(f"Extranjeras (sus números por acción no van contra el ADR): {', '.join(extranjeras) or '—'}")
    sin = sorted(t for t, f in fundamentos.items() if f is None)
    print(f"Sin datos: {', '.join(sin) or '—'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
