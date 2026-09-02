"""¿El `analyze SELL` está sesgado al pesimismo? — Tarea 31 (SELL-REMEASURE).

Por qué existe
--------------
El diagnóstico vigente —*"los SELL están sesgados al pesimismo"*— viene de la
auditoría **2026-06-09** (post-SELL fwd5 positivo), de la **T6.3** (gap SELL
0.20-0.45 = +23 pts, **n=13**) y de la dosis-respuesta de la **T7**, y **se sigue
citando en tareas nuevas**. Pero el análisis del **2026-08-12** §3.1 midió lo
contrario sobre la cuenta 2: el ticker **cae** −1,30% a 5d, −1,51% a 10d y −5,63%
a 20d después de vender (**n=15**).

Dos muestras chicas que dicen cosas opuestas. Esto no las arbitra por mayoría: las
vuelve a medir con la muestra de hoy **y reporta el poder**, que es lo que ninguna
de las dos reportó — la misma corrección que la tarea 73 le hizo al claim del
`buy_score`.

Qué cuenta como "SELL de señal"
-------------------------------
``paper_orders.reason`` empieza con ``analyze`` para las salidas por señal, y con
``atr_stop`` / ``atr_tp`` / ``atr_trail`` para las barreras. El diagnóstico es
sobre el **``analyze SELL``**, así que las barreras se excluyen: una salida por
stop no es una opinión del modelo sobre el futuro del precio.

Cómo se lee el signo
--------------------
Forward **positivo** = el precio **siguió subiendo** después de vender = la venta
fue prematura = **pesimismo**. Forward negativo = el modelo acertó.

Offline: lee ``finanzias.db`` en **modo lectura** y el cache parquet. No pega a la
red y no escribe nada (regla 5). **Display-only:** no toca sizing ni gates.

    python scripts/measure_sell_bias_t31.py
    python scripts/measure_sell_bias_t31.py --json
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

HORIZONTES = (5, 10, 20)  # ruedas hábiles
PERIODO = "2y"


def forward(ticker: str, fecha: str, precio: float, ruedas: int) -> float | None:
    """Retorno a ``ruedas`` desde ``precio``, o ``None`` si no hay barras."""
    df = parquet_cache.read(ticker, PERIODO, "1d", ttl_hours=None)
    if df is None or "Close" not in df or df.empty or precio <= 0:
        return None
    fechas = [str(d)[:10] for d in df.index]
    cierres = [float(x) for x in df["Close"]]
    posteriores = [i for i, f in enumerate(fechas) if f > fecha[:10]]
    if not posteriores:
        return None
    i = posteriores[0] + ruedas - 1
    if i >= len(cierres):
        return None
    return cierres[i] / precio - 1.0


def _stats(xs: list[float]) -> dict:
    """Media, IC95% y **efecto detectable al 80%** — la cuenta que faltaba."""
    n = len(xs)
    if n < 2:
        return {"n": n, "media": None, "ic95": None, "detectable_80": None, "hit_rate": None}
    media = sum(xs) / n
    var = sum((x - media) ** 2 for x in xs) / (n - 1)
    sd = math.sqrt(var)
    se = sd / math.sqrt(n)
    return {
        "n": n,
        "media": media,
        "sd": sd,
        "ic95": [media - 1.96 * se, media + 1.96 * se],
        # Para una media: 2.80 = z(0.975) + z(0.80). Es el efecto más chico que
        # esta muestra puede distinguir de cero con 80% de potencia.
        "detectable_80": 2.80 * sd / math.sqrt(n),
        "hit_rate": sum(1 for x in xs if x > 0) / n,
    }


def _ventas(db: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        filas = list(
            con.execute(
                """SELECT account_id, ticker, fill_price, COALESCE(filled_at, created_at), reason
                   FROM paper_orders
                   WHERE side='SELL' AND status='filled' AND fill_price IS NOT NULL"""
            )
        )
    finally:
        con.close()
    return [
        {"account_id": a, "ticker": t, "fill": float(p), "fecha": str(d), "reason": str(r or "")}
        for a, t, p, d, r in filas
    ]


def measure(db: Path | None = None) -> dict:
    db = db or (Path(__file__).resolve().parent.parent / "finanzias.db")
    todas = _ventas(db)
    senal = [o for o in todas if o["reason"].strip().lower().startswith("analyze")]
    barreras = len(todas) - len(senal)

    for o in senal:
        for h in HORIZONTES:
            o[f"fwd{h}"] = forward(o["ticker"], o["fecha"], o["fill"], h)

    def bloque(sub: list[dict], nombre: str) -> dict:
        out: dict = {"nombre": nombre, "n_ventas": len(sub)}
        for h in HORIZONTES:
            xs = [o[f"fwd{h}"] for o in sub if o[f"fwd{h}"] is not None]
            out[f"fwd{h}"] = _stats(xs)
        return out

    return {
        "n_sell_total": len(todas),
        "n_sell_senal": len(senal),
        "n_sell_barrera_excluidas": barreras,
        "horizontes": list(HORIZONTES),
        "referencias": {
            "auditoria_2026_06_09": {"hit_rate": 0.57, "fwd5_medio": 0.0392, "n": None},
            "t6_3": {"n": 13},
            "deep_analysis_2026_08_12": {"fwd5": -0.0130, "fwd10": -0.0151, "fwd20": -0.0563, "n": 15},
        },
        "bloques": [
            bloque(senal, "las dos cuentas"),
            bloque([o for o in senal if o["account_id"] == 2], "cuenta 2 (viva)"),
            bloque([o for o in senal if o["account_id"] == 1], "cuenta 1 (pausada)"),
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sesgo del analyze SELL (tarea 31)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    m = measure()
    if args.json:
        print(json.dumps(m, indent=2, default=str))
        return 0

    print("=" * 78)
    print("SELL-REMEASURE (tarea 31) — ¿el `analyze SELL` está sesgado al pesimismo?")
    print("=" * 78)
    print(
        f"\nSELL llenadas: {m['n_sell_total']} · de señal: {m['n_sell_senal']} · "
        f"por barrera (excluidas): {m['n_sell_barrera_excluidas']}"
    )
    print("\nForward POSITIVO = el precio siguió subiendo = la venta fue prematura = pesimismo.")

    for b in m["bloques"]:
        print(f"\n  ── {b['nombre']} ({b['n_ventas']} ventas de señal)")
        print(f"     {'':>6} {'n':>4} {'media':>9} {'IC95%':>20} {'detect.80%':>11} {'sube':>7}")
        for h in m["horizontes"]:
            s = b[f"fwd{h}"]
            if s["media"] is None:
                print(f"     fwd{h:<3} {s['n']:>4}   (sin datos)")
                continue
            ic = f"[{100 * s['ic95'][0]:+.2f}, {100 * s['ic95'][1]:+.2f}]"
            print(
                f"     fwd{h:<3} {s['n']:>4} {100 * s['media']:>+8.2f}% {ic:>20} "
                f"{100 * s['detectable_80']:>10.2f}% {100 * s['hit_rate']:>6.0f}%"
            )

    ref = m["referencias"]
    print(
        f"\n  Referencias que se venían citando: auditoría 2026-06-09 "
        f"(hit rate {100 * ref['auditoria_2026_06_09']['hit_rate']:.0f}%, fwd5 "
        f"{100 * ref['auditoria_2026_06_09']['fwd5_medio']:+.2f}%) · T6.3 n={ref['t6_3']['n']} · "
        f"deep analysis 2026-08-12 (fwd5 {100 * ref['deep_analysis_2026_08_12']['fwd5']:+.2f}%, "
        f"n={ref['deep_analysis_2026_08_12']['n']})"
    )

    principal = m["bloques"][0]["fwd5"]
    if principal["media"] is not None:
        lo, hi = principal["ic95"]
        print("\n  Desenlace (criterio congelado antes de medir):")
        if lo > 0:
            print("    (A) EL DIAGNÓSTICO SIGUE EN PIE — fwd5 medio POSITIVO y distinguible de cero.")
        elif hi < 0:
            print("    (B) SE DIO VUELTA — fwd5 medio NEGATIVO y distinguible de cero.")
        else:
            print(
                f"    (C) NO ALCANZA PARA NINGUNA DE LAS DOS — el IC95% contiene el 0.\n"
                f"        La muestra sólo detecta un efecto de "
                f"±{100 * principal['detectable_80']:.2f}%, así que no distingue\n"
                f"        'sesgado al pesimismo' de 'no se midió'."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
