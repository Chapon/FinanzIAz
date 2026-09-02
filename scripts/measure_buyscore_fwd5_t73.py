"""¿El `buy_score` predice el fwd5? — Tarea 73 (BUYSCORE-REVERIFY).

Por qué existe
--------------
`CLAUDE.md` justifica la **regla 3 no-negociable** (*"Display antes que sizing"*)
con un paréntesis: *"(``buy_score`` no predice el fwd5 — auditoría 2026-06-17)"*.
Ese número tiene tres meses y **nadie lo re-verificó**; la skill
`fair-value-feature` cuelga de la misma regla su restricción dura.

Qué midió el original, para medir LO MISMO
------------------------------------------
`docs/ops_logic_audit_2026-06-17.md` §4 y `ops_logic_deep_audit_2026-06-17.md` §A3:
**corr(buy_score, fwd5) ≈ 0.00 (n=21)**, donde
``buy_score = _default_strength("BUY", ml_probability)`` = la ``ml_probability``
clampeada a [0,1]. Eso es exactamente lo que persiste ``paper_orders.signal_score``
(``engine.py`` lo copia del ``TargetTrade``), así que la métrica se reproduce sobre
la misma cantidad — con la muestra de hoy, que es 4,5× más grande.

**Ojo con el fallback:** ``_default_strength`` devuelve **1.0** cuando no hay
``ml_probability``. Un ``signal_score`` de exactamente 1.0 puede ser "sin score", no
"máxima convicción", así que se excluye y se reporta cuántos se excluyeron. En la
muestra de hoy son **cero**, pero el guard queda para la próxima corrida.

El poder, que es lo que el original no reportó
-----------------------------------------------
Con ``n``, el |r| detectable al 80% de potencia (α=0.05 bilateral) es
``tanh(2.80 / sqrt(n-3))``. Para **n=21** eso da **0.58**: una correlación que no
existe en finanzas a 5 días. O sea que aquella muestra **no podía distinguir "no
predice" de "no se midió"** — y esa distinción es el objeto de esta tarea.

Offline: lee ``finanzias.db`` en **modo lectura** y el cache parquet. No pega a la
red y no escribe nada (regla 5).

    python scripts/measure_buyscore_fwd5_t73.py
    python scripts/measure_buyscore_fwd5_t73.py --json
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data import parquet_cache

HORIZONTE = 5  # ruedas hábiles, igual que el fwd5 del original
PERIODO = "2y"  # frame con el que se calculan los forwards


def _fwd5(ticker: str, fecha_fill: str, precio_fill: float) -> float | None:
    """Retorno a ``HORIZONTE`` ruedas desde el fill, o ``None`` si no hay barras."""
    df = parquet_cache.read(ticker, PERIODO, "1d", ttl_hours=None)
    if df is None or "Close" not in df or df.empty:
        return None
    fechas = [str(d)[:10] for d in df.index]
    cierres = [float(x) for x in df["Close"]]
    # primera barra ESTRICTAMENTE posterior al fill: el retorno se mide hacia
    # adelante desde el precio al que se compró, no desde el close del mismo día
    posteriores = [i for i, f in enumerate(fechas) if f > fecha_fill[:10]]
    if not posteriores:
        return None
    i = posteriores[0] + HORIZONTE - 1
    if i >= len(cierres) or precio_fill <= 0:
        return None
    return cierres[i] / precio_fill - 1.0


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def _ic95(r: float, n: int) -> tuple[float, float]:
    """IC95% por transformación de Fisher."""
    if n < 4 or abs(r) >= 1:
        return (-1.0, 1.0)
    z = 0.5 * math.log((1 + r) / (1 - r))
    se = 1.0 / math.sqrt(n - 3)
    lo, hi = z - 1.96 * se, z + 1.96 * se
    return (math.tanh(lo), math.tanh(hi))


def detectable_r(n: int) -> float:
    """|r| detectable al 80% de potencia, α=0.05 bilateral."""
    if n < 4:
        return 1.0
    return math.tanh(2.80 / math.sqrt(n - 3))


def _muestra(db: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        filas = list(
            con.execute(
                """SELECT account_id, ticker, signal_score, fill_price,
                          COALESCE(filled_at, created_at)
                   FROM paper_orders
                   WHERE side='BUY' AND status='filled'
                     AND signal_score IS NOT NULL AND fill_price IS NOT NULL"""
            )
        )
    finally:
        con.close()
    return [
        {"account_id": a, "ticker": t, "score": float(s), "fill": float(p), "fecha": str(d)}
        for a, t, s, p, d in filas
    ]


def measure(db: Path | None = None) -> dict:
    db = db or (Path(__file__).resolve().parent.parent / "finanzias.db")
    crudo = _muestra(db)
    # el fallback de `_default_strength`: 1.0 puede ser "sin score", no convicción
    fallback = [o for o in crudo if abs(o["score"] - 1.0) < 1e-9]
    utiles = [o for o in crudo if abs(o["score"] - 1.0) >= 1e-9]

    filas, sin_barras = [], []
    for o in utiles:
        f = _fwd5(o["ticker"], o["fecha"], o["fill"])
        if f is None:
            sin_barras.append(o["ticker"])
        else:
            filas.append({**o, "fwd5": f})

    def bloque(sub: list[dict], nombre: str) -> dict:
        xs = [o["score"] for o in sub]
        ys = [o["fwd5"] for o in sub]
        r = _pearson(xs, ys)
        n = len(sub)
        return {
            "nombre": nombre,
            "n": n,
            "r": r,
            "ic95": list(_ic95(r, n)) if r is not None else None,
            "detectable_80": detectable_r(n),
            "fwd5_medio": (sum(ys) / n) if n else None,
            "score_rango": [min(xs), max(xs)] if xs else None,
        }

    return {
        "horizonte_ruedas": HORIZONTE,
        "n_ordenes_con_score": len(crudo),
        "n_excluidas_fallback_1.0": len(fallback),
        "n_sin_barras": len(sin_barras),
        "tickers_sin_barras": sorted(set(sin_barras)),
        "original_2026_06_17": {"r": 0.00, "n": 21, "detectable_80": detectable_r(21)},
        "bloques": [
            bloque(filas, "las dos cuentas"),
            bloque([o for o in filas if o["account_id"] == 2], "cuenta 2 (viva)"),
            bloque([o for o in filas if o["account_id"] == 1], "cuenta 1 (pausada)"),
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="buy_score vs fwd5 (tarea 73)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    m = measure()
    if args.json:
        print(json.dumps(m, indent=2, default=str))
        return 0

    print("=" * 78)
    print("BUYSCORE-REVERIFY (tarea 73) — ¿el buy_score predice el fwd5?")
    print("=" * 78)
    o = m["original_2026_06_17"]
    print(
        f"\nOriginal 2026-06-17: r ~ {o['r']:.2f} con n={o['n']} "
        f"⇒ |r| detectable al 80%: {o['detectable_80']:.2f}"
    )
    print(
        f"Órdenes BUY llenadas con score: {m['n_ordenes_con_score']} · "
        f"excluidas por el fallback 1.0: {m['n_excluidas_fallback_1.0']} · "
        f"sin barras: {m['n_sin_barras']}"
    )

    print(f"\n  {'muestra':<18} {'n':>4} {'r':>8} {'IC95%':>18} {'detect.80%':>11} {'fwd5 medio':>11}")
    for b in m["bloques"]:
        if b["r"] is None:
            print(f"  {b['nombre']:<18} {b['n']:>4}   (sin datos suficientes)")
            continue
        ic = f"[{b['ic95'][0]:+.2f}, {b['ic95'][1]:+.2f}]"
        print(
            f"  {b['nombre']:<18} {b['n']:>4} {b['r']:>+8.3f} {ic:>18} "
            f"{b['detectable_80']:>11.2f} {100 * b['fwd5_medio']:>10.2f}%"
        )

    principal = m["bloques"][0]
    if principal["r"] is not None:
        lo, hi = principal["ic95"]
        cruza_cero = lo <= 0 <= hi
        con_poder = principal["detectable_80"] <= 0.30
        print("\n  Desenlace (criterio congelado antes de medir):")
        if not cruza_cero:
            print("    (B) EL CLAIM CADUCÓ — el IC95% no contiene el 0.")
        elif con_poder:
            print("    (A) EL CLAIM SE SOSTIENE — indistinguible de cero, y con poder.")
        else:
            print(
                f"    (C) EL CLAIM NUNCA TUVO RESPALDO SUFICIENTE — el IC95% contiene el 0, "
                f"pero la muestra sólo detecta |r| >= {principal['detectable_80']:.2f}.\n"
                f"        No distingue 'no predice' de 'no se midió'."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
