#!/usr/bin/env python3
"""
refresh_sp500_fallback.py — regenera ``_SP500_FALLBACK`` en ``data/ticker_universe.py``
desde la lista viva de Wikipedia, validando cada símbolo contra Yahoo (backlog UNIV1).

Por qué existe
--------------
El fallback hardcoded es la red de contención cuando Wikipedia no responde, así que
un fallback stale se paga caro: los símbolos que dejaron de existir se consultan
igual en cada run y devuelven 404 — presión de throttle gratis (ver NET1) y ruido
que entierra errores reales en el log. El snapshot 2026-06 acumuló **14 símbolos
muertos**, unos por adquisición (ANSS, CTLT, DFS, HES, JNPR, WBA…) y otros por
*rename* del ticker (MMC→MRSH, BK→BNY, PARA→PSKY, CTRA→EXE), y le faltaban ~40
altas del índice (PLTR, COIN, DASH, APP…).

Validación
----------
"Fuera del índice" ≠ "deslistado": una empresa sacada del S&P 500 sigue cotizando.
Por eso cada símbolo se valida bajando barras recientes en lotes (``yf.download``,
~9 requests para las 503) y solo entran los que devuelven precio. Mismo criterio
que se usó para dar de baja K/Kellanova (commit ``2c9587c``).

Uso (Windows)
-------------
    python scripts/refresh_sp500_fallback.py              # dry-run: muestra el diff
    python scripts/refresh_sp500_fallback.py --apply      # reescribe el módulo
    python scripts/refresh_sp500_fallback.py --apply --no-validate   # sin tocar Yahoo

Requiere ``lxml`` instalado (pandas lo necesita para ``read_html``).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TARGET = ROOT / "data" / "ticker_universe.py"
START_MARKER = "# >>> SP500_FALLBACK_START (generado — no editar a mano)"
END_MARKER = "# <<< SP500_FALLBACK_END"
PER_LINE = 10
BATCH_SIZE = 60


def validate_against_yahoo(symbols: list[str]) -> tuple[list[str], list[str]]:
    """Parte ``symbols`` en (con precio, sin precio) bajando barras en lotes."""
    import logging

    import yfinance as yf

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)

    alive: list[str] = []
    dead: list[str] = []
    for start in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[start : start + BATCH_SIZE]
        data = yf.download(
            batch,
            period="5d",
            progress=False,
            auto_adjust=False,
            group_by="ticker",
            threads=True,
        )
        for symbol in batch:
            try:
                closes = data[symbol]["Close"] if len(batch) > 1 else data["Close"]
                (alive if not closes.dropna().empty else dead).append(symbol)
            except Exception:
                dead.append(symbol)
        print(f"  lote {start // BATCH_SIZE + 1}: vivos={len(alive)} sin datos={len(dead)}")
    return alive, dead


def render_block(symbols: list[str]) -> str:
    """Formatea la tupla literal, 10 símbolos por línea (igual que a mano)."""
    lines = ["_SP500_FALLBACK: tuple[str, ...] = ("]
    for start in range(0, len(symbols), PER_LINE):
        chunk = symbols[start : start + PER_LINE]
        lines.append("    " + " ".join(f'"{s}",' for s in chunk))
    lines.append(")")
    return "\n".join(lines)


def replace_block(source: str, block: str) -> str:
    """Reemplaza lo que hay entre los marcadores. Falla ruidosamente si no están."""
    pattern = re.compile(re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL)
    if not pattern.search(source):
        raise SystemExit(f"No encontré los marcadores en {TARGET}")
    return pattern.sub(f"{START_MARKER}\n{block}\n{END_MARKER}", source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="escribe el módulo (default: dry-run)")
    parser.add_argument("--no-validate", action="store_true", help="no validar contra Yahoo")
    args = parser.parse_args()

    from data.ticker_universe import _fetch_sp500_from_wikipedia, get_sp500_fallback

    print("Bajando la lista viva de Wikipedia…")
    live = _fetch_sp500_from_wikipedia()
    if not live:
        print("ERROR: el fetch de Wikipedia falló — no regenero nada.", file=sys.stderr)
        return 1
    print(f"  {len(live)} símbolos en el índice")

    if args.no_validate:
        symbols = live
    else:
        print("Validando contra Yahoo…")
        symbols, dead = validate_against_yahoo(live)
        if dead:
            print(f"  descartados (sin precio): {dead}")

    current = get_sp500_fallback()
    added = sorted(set(symbols) - set(current))
    removed = sorted(set(current) - set(symbols))
    print(f"\nActual: {len(current)}  →  nuevo: {len(symbols)}")
    print(f"ALTAS ({len(added)}): {added}")
    print(f"BAJAS ({len(removed)}): {removed}")

    if not args.apply:
        print("\n(dry-run — volvé a correr con --apply para escribir)")
        return 0

    source = TARGET.read_text(encoding="utf-8")
    TARGET.write_text(replace_block(source, render_block(symbols)), encoding="utf-8")
    print(f"\n✓ {TARGET} actualizado ({len(symbols)} símbolos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
