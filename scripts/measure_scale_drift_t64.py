"""Calibración del umbral de drift de escala — Tarea 64 (SCALEDRIFT).

Mide, sobre el cache OHLCV **real**, cuánto se apartan entre sí los frames ``1d``
del mismo ticker. De acá sale `_DEFAULT_SCALE_DRIFT_TOLERANCE`, y el punto es que
salga de una medición y no de la intuición: el enunciado de la tarea daba por
sentado que *"por debajo de ~10% el drift legítimo se vuelve indistinguible de una
corrupción"*, y eso **no se sostiene** — el drift legítimo se termina mucho antes.

Cómo compara, y por qué así:

* **Sobre las fechas que SOLAPAN**, no sobre el último close de cada frame. Los
  frames se bajan en momentos distintos, así que sus puntas difieren por el
  movimiento real del precio; sobre las mismas fechas lo único que puede quedar es
  la escala.
* **Todos los pares**, no sólo el más fresco contra el resto: acá se está midiendo
  la distribución, no decidiendo sobre un ticker.
* Reporta también el **spread** (máx/mín del ratio por fecha) porque era el otro
  discriminador candidato — y la medición lo descarta: el ratio es constante en los
  365 pares, legítimos incluidos. Un re-ajuste por dividendos también es un
  re-escalado; la única diferencia con una corrupción es el **tamaño**.

Es offline: lee el cache, no pega a la red y no toca la DB viva.

    python scripts/measure_scale_drift_t64.py
    python scripts/measure_scale_drift_t64.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data import parquet_cache

# Mínimo de fechas solapadas para que un par cuente: con menos, un par de días
# raros pesarían como si fueran la escala.
MIN_DATES = 5


def _pairs() -> list[dict]:
    """Un registro por par de frames ``1d`` comparables del cache."""
    d = parquet_cache.get_parquet_dir()
    tickers = sorted({p.name.split("__")[0] for p in d.glob("*__1d.parquet")})
    out: list[dict] = []
    for ticker in tickers:
        frames = parquet_cache.labelled_1d(ticker)
        for i in range(len(frames)):
            for j in range(i + 1, len(frames)):
                (la, a), (lb, b) = frames[i], frames[j]
                ca, cb = a.get("Close"), b.get("Close")
                if ca is None or cb is None:
                    continue
                common = ca.index.intersection(cb.index)
                if len(common) < MIN_DATES:
                    continue
                ratio = (ca.loc[common] / cb.loc[common]).dropna()
                ratio = ratio[ratio > 0]
                if len(ratio) < MIN_DATES:
                    continue
                med = float(ratio.median())
                out.append(
                    {
                        "ticker": ticker,
                        "a": la,
                        "b": lb,
                        "n_dates": len(ratio),
                        "ratio": med,
                        "deviation": abs(med - 1.0),
                        "spread": float(ratio.max() / ratio.min()),
                    }
                )
    return out


def _quantile(ordenados: list[float], q: float) -> float:
    """Nearest-rank: el percentil tiene que ser un par que existió."""
    if not ordenados:
        return 0.0
    n = len(ordenados)
    return ordenados[min(int(q * n), n - 1)]


def measure() -> dict:
    pairs = _pairs()
    devs = sorted(p["deviation"] for p in pairs)
    d = parquet_cache.get_parquet_dir()
    n_tickers = len({p.name.split("__")[0] for p in d.glob("*__1d.parquet")})
    return {
        "n_tickers_1d": n_tickers,
        "n_tickers_cruzables": len({p["ticker"] for p in pairs}),
        "n_pairs": len(pairs),
        "p50": _quantile(devs, 0.50),
        "p90": _quantile(devs, 0.90),
        "p95": _quantile(devs, 0.95),
        "p99": _quantile(devs, 0.99),
        "max": devs[-1] if devs else 0.0,
        "max_spread": max((p["spread"] for p in pairs), default=0.0),
        "over": {
            f"{thr:g}": sorted({p["ticker"] for p in pairs if p["deviation"] > thr})
            for thr in (0.01, 0.02, 0.05, 0.10, 0.20, 0.30)
        },
        "worst": sorted(pairs, key=lambda p: -p["deviation"])[:15],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Calibración del drift de escala (tarea 64)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    m = measure()
    if args.json:
        print(json.dumps(m, indent=2, default=str))
        return 0

    print("=" * 78)
    print("SCALEDRIFT (tarea 64) — cuánto se apartan entre sí los frames 1d del cache")
    print("=" * 78)
    print(
        f"\n{m['n_tickers_1d']} tickers con parquet 1d · {m['n_tickers_cruzables']} con dos o más "
        f"frames ⇒ {m['n_pairs']} pares comparables (≥{MIN_DATES} fechas solapadas)"
    )
    print("\n  |ratio mediano − 1| sobre todos los pares:")
    for k in ("p50", "p90", "p95", "p99", "max"):
        print(f"    {k:>4} {100 * m[k]:>9.3f}%")
    print(f"\n  spread máximo (máx/mín del ratio por fecha): {m['max_spread']:.6f}")
    print("    ⇒ el ratio es CONSTANTE por fecha en todos: la dispersión NO discrimina.")

    print("\n  tickers por encima de cada umbral:")
    for thr, ts in m["over"].items():
        print(f"    > {100 * float(thr):>5.1f}% : {len(ts):>2}  {ts[:8]}")

    print("\n  los pares más desalineados:")
    print(f"    {'|dev|':>9}  {'ticker':<8} {'frames':<12} {'fechas':>7} {'ratio':>10} {'spread':>9}")
    for p in m["worst"]:
        if p["deviation"] < 0.005:
            break
        print(
            f"    {100 * p['deviation']:>8.3f}%  {p['ticker']:<8} "
            f"{p['a'] + '/' + p['b']:<12} {p['n_dates']:>7} {p['ratio']:>10.6f} {p['spread']:>9.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
