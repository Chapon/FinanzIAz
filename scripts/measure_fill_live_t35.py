"""¿Cuánto separa el nivel del precio del scan? — Tarea 35 (FILL-LIVE).

Por qué existe
--------------
``engine.py`` detecta una barrera cuando el **precio del scan** (`px`, ~15 min)
cruza el nivel, y después llena con ``gates.model_exit_fill_price``, que devuelve
**el nivel** (o el ``open`` si hubo gap). O sea que la cuenta se acredita un precio
que puede ser **mejor que aquel con el que el engine se enteró**. Es la misma
estructura del look-ahead que la **T33** sacó del harness, acotada por la ventana
de 15 minutos en vez de por un día entero.

**No es automáticamente un bug.** Bajo la lectura *"hay una orden en reposo en el
nivel"* es el modelo realista que eligió la T01, y el ``reason`` deja constancia
honesta (``fill≈X (gap …)``). El problema es que el paper-trading **no coloca esa
orden**: emite un SELL de mercado en el scan. Cuál de las dos ficciones se
contabiliza **no está decidido, está heredado**.

Por eso esto **sólo mide**. Cambiar la contabilidad reescribiría el P/L histórico
de la cuenta, y esa es una decisión de Chapa, no de una tarea técnica.

De dónde salen los números
--------------------------
El ``reason`` de cada salida ATR es parseable y trae las tres puntas::

    atr_stop @ 155.19 ≤ 156.32 (entry 164.21 − 2.0×ATR 3.95) | fill≈156.32 (gap +0.00% vs nivel)
              ^^^^^^   ^^^^^^                                        ^^^^^^
              px       nivel                                         base del fill

y ``fill_price`` trae el precio final (ya con slippage). Con eso se puede separar
**cuánto de la diferencia es la convención** y cuánto es el slippage que ya estaba
modelado.

Offline: lee ``finanzias.db`` en modo lectura. No pega a la red, no escribe nada.

    python scripts/measure_fill_live_t35.py
    python scripts/measure_fill_live_t35.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# `atr_stop @ 155.19 ≤ 156.32 (…)`  ·  el operador es ≤ para stop/trail y ≥ para tp
_DISPARO = re.compile(r"^(atr_\w+)\s*@\s*([\d.]+)\s*[≤≥<>]=?\s*([\d.]+)")
# `| fill≈156.32 (gap +0.00% vs nivel)` — sólo lo traen las salidas posteriores a la T01
_FILL = re.compile(r"fill≈\s*([\d.]+)")


def parse_reason(reason: str) -> dict | None:
    """``{tipo, px, nivel, fill_base}`` de un ``reason`` de salida ATR, o None."""
    m = _DISPARO.match(reason.strip())
    if not m:
        return None
    f = _FILL.search(reason)
    return {
        "tipo": m.group(1),
        "px": float(m.group(2)),
        "nivel": float(m.group(3)),
        "fill_base": float(f.group(1)) if f else None,
    }


def _salidas(db: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        filas = list(
            con.execute(
                """SELECT account_id, ticker, fill_price, fill_shares, reason,
                          COALESCE(filled_at, created_at)
                   FROM paper_orders
                   WHERE side='SELL' AND status='filled' AND reason LIKE 'atr%'
                     AND fill_price IS NOT NULL"""
            )
        )
    finally:
        con.close()
    out = []
    for a, t, precio, shares, reason, fecha in filas:
        p = parse_reason(str(reason))
        if p is None:
            continue
        out.append(
            {
                "account_id": a,
                "ticker": t,
                "fill_price": float(precio),
                "shares": float(shares or 0.0),
                "fecha": str(fecha)[:10],
                **p,
            }
        )
    return out


def measure(db: Path | None = None) -> dict:
    db = db or (Path(__file__).resolve().parent.parent / "finanzias.db")
    salidas = _salidas(db)

    for o in salidas:
        base = o["fill_base"] if o["fill_base"] is not None else o["fill_price"]
        # Cuánto MEJOR es el precio contabilizado que aquel con el que el engine
        # se enteró. Positivo = la cuenta se acreditó de más (para un SELL).
        o["ventaja_pct"] = base / o["px"] - 1.0
        o["ventaja_usd"] = (base - o["px"]) * o["shares"]
        # ¿La salida se contabilizó al NIVEL o al PRECIO DEL SCAN? Se decide contra
        # el fill real, que es lo único que la cuenta efectivamente cobró.
        d_nivel = abs(o["fill_price"] / o["nivel"] - 1.0)
        d_px = abs(o["fill_price"] / o["px"] - 1.0)
        o["convencion"] = "nivel" if d_nivel <= d_px else "px_del_scan"

    def bloque(sub: list[dict], nombre: str) -> dict:
        n = len(sub)
        vs = sorted(o["ventaja_pct"] for o in sub)
        usd = sum(o["ventaja_usd"] for o in sub)
        return {
            "nombre": nombre,
            "n": n,
            "usd_total": usd,
            "pct_medio": (sum(vs) / n) if n else None,
            "pct_max": vs[-1] if vs else None,
            "pct_min": vs[0] if vs else None,
            "n_a_favor": sum(1 for v in vs if v > 1e-9),
            "n_en_contra": sum(1 for v in vs if v < -1e-9),
            "n_iguales": sum(1 for v in vs if abs(v) <= 1e-9),
            "convenciones": {
                c: sum(1 for o in sub if o["convencion"] == c) for c in ("nivel", "px_del_scan")
            },
        }

    return {
        "n_salidas_atr": len(salidas),
        "n_sin_fill_declarado": sum(1 for o in salidas if o["fill_base"] is None),
        "bloques": [
            bloque(salidas, "las dos cuentas"),
            bloque([o for o in salidas if o["account_id"] == 2], "cuenta 2 (viva)"),
            bloque([o for o in salidas if o["account_id"] == 1], "cuenta 1 (pausada)"),
        ],
        # El corte que EXPLICA el número agregado: la convención es simétrica por
        # construcción. En un stop/trail el nivel está ARRIBA del px que lo disparó
        # (favorece a la cuenta); en un take-profit está ABAJO (la perjudica). No es
        # un sesgo: es la misma regla mirada desde los dos lados.
        "por_tipo": {
            tipo: bloque([o for o in salidas if o["tipo"] == tipo], tipo)
            for tipo in sorted({o["tipo"] for o in salidas})
        },
        "peores": sorted(salidas, key=lambda o: -abs(o["ventaja_pct"]))[:8],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fill de las salidas ATR (tarea 35)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    m = measure()
    if args.json:
        print(json.dumps(m, indent=2, default=str))
        return 0

    print("=" * 78)
    print("FILL-LIVE (tarea 35) — ¿cuánto separa el precio contabilizado del que vio el engine?")
    print("=" * 78)
    print(
        f"\nSalidas ATR parseadas: {m['n_salidas_atr']} · "
        f"sin `fill≈` declarado en el reason: {m['n_sin_fill_declarado']}"
    )
    print("\nVentaja POSITIVA = la cuenta se acreditó un precio MEJOR que el del scan.")

    for b in m["bloques"]:
        if not b["n"]:
            continue
        print(f"\n  ── {b['nombre']} (n={b['n']})")
        print(f"     ventaja media {100 * b['pct_medio']:+.3f}%  ·  total ${b['usd_total']:+,.2f}")
        print(
            f"     rango [{100 * b['pct_min']:+.2f}%, {100 * b['pct_max']:+.2f}%]  ·  "
            f"a favor {b['n_a_favor']} · en contra {b['n_en_contra']} · iguales {b['n_iguales']}"
        )
        print(
            f"     contabilizadas al NIVEL: {b['convenciones']['nivel']} · "
            f"al PRECIO DEL SCAN: {b['convenciones']['px_del_scan']}"
        )

    print("\n  Por tipo de salida — la convención es SIMÉTRICA, no un sesgo:")
    print(f"     {'tipo':<11} {'n':>4} {'media':>9} {'total USD':>12}  a favor / en contra")
    for tipo, b in m["por_tipo"].items():
        if not b["n"]:
            continue
        print(
            f"     {tipo:<11} {b['n']:>4} {100 * b['pct_medio']:>+8.3f}% "
            f"{b['usd_total']:>+12,.2f}      {b['n_a_favor']} / {b['n_en_contra']}"
        )

    print("\n  Las que más se apartan:")
    print(f"     {'ticker':<7} {'cuenta':>6} {'fecha':>11} {'px':>9} {'nivel':>9} {'base':>9} {'ventaja':>9}")
    for o in m["peores"]:
        base = o["fill_base"] if o["fill_base"] is not None else o["fill_price"]
        print(
            f"     {o['ticker']:<7} {o['account_id']:>6} {o['fecha']:>11} {o['px']:>9.2f} "
            f"{o['nivel']:>9.2f} {base:>9.2f} {100 * o['ventaja_pct']:>+8.2f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
