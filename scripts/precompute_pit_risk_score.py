"""
Precómputo point-in-time del ``risk_score`` — enabler del brazo **B2** de la
**Tarea 21** (pre-registro `docs/ranking_prereg_t21_2026-08-12.md` §3).

Por qué existe
--------------
El `buy_score` que rankea los candidatos es
``clip(raw_prob − 0.08·risk_score, 0.05, 0.95)`` (`ml_signals.py:1147`). Los
artefactos de ``data/pit_signals/`` guardan el score **final**, así que para
aislar cuánto de la anti-selección pone la penalidad de volatilidad hace falta
reconstruir ``raw_prob``, y para eso el ``risk_score`` de cada (ticker, fecha).

``risk_score`` **no es un dato de mercado compartido**: sale de
``detect_market_regime(df)`` sobre las barras del **propio ticker** (GARCH/EWMA +
régimen), así que varía entre candidatos del mismo día — que es justamente lo que
lo hace capaz de mover un ranking.

Mismo patrón que ``precompute_pit_signals.py``: un JSON por ticker, resumible,
sin red (lee Parquet), sin tocar ``finanzias.db``. Medido: ~16 ms por fecha.

Uso:
    python scripts/precompute_pit_risk_score.py                     # universo vivo
    python scripts/precompute_pit_risk_score.py --tickers AAPL MSFT
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))

from analysis.harness_config import LIVE_UNIVERSE_FILE  # noqa: E402
from scripts.precompute_pit_signals import parse_universe_file  # noqa: E402

OUT_DIR = _ROOT / "data" / "pit_risk"
SCHEMA_VERSION = 1


def out_path(ticker: str, period: str, warmup: int) -> Path:
    return OUT_DIR / f"{ticker}__{period}__w{warmup}.json"


def load_existing(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(path: Path, ticker: str, period: str, warmup: int,
         rows: dict, n_bars: int, *, done: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "ticker": ticker, "period": period, "warmup": warmup,
        "n_bars": n_bars, "complete": done, "risk": rows,
    }, ensure_ascii=False), encoding="utf-8")


def run_ticker(ticker: str, period: str, warmup: int, *, save_every: int) -> tuple[int, int]:
    """(computadas ahora, total en el artefacto). No lanza: loguea y sigue."""
    from data import parquet_cache
    from analysis.ml_signals import detect_market_regime

    path = out_path(ticker, period, warmup)
    prev = load_existing(path)
    df = parquet_cache.read(ticker, period, "1d", None)
    if df is None or df.empty:
        print(f"  {ticker:<6} SIN CACHE parquet ({period}/1d) — se saltea")
        return 0, 0
    df = df.sort_index()
    n = len(df)
    if n <= warmup:
        print(f"  {ticker:<6} solo {n} barras (<= warmup {warmup}) — se saltea")
        return 0, 0

    rows: dict = dict(prev.get("risk") or {})
    if prev.get("complete") and len(rows) >= n - warmup:
        print(f"  {ticker:<6} ya completo ({len(rows)}) — se saltea")
        return 0, len(rows)

    dates = [d.strftime("%Y-%m-%d") for d in df.index]
    t0 = time.perf_counter()
    computed = 0
    for i in range(warmup, n):
        iso = dates[i]
        if iso in rows:
            continue
        try:
            mc = detect_market_regime(df.iloc[: i + 1])
            rows[iso] = None if mc is None else round(float(mc.risk_score), 6)
        except Exception as exc:  # una barra rota no puede matar el barrido
            print(f"    {ticker} {iso}: detect_market_regime falló ({exc})")
            rows[iso] = None
        computed += 1
        if computed % save_every == 0:
            save(path, ticker, period, warmup, rows, n, done=False)

    save(path, ticker, period, warmup, rows, n, done=True)
    el = time.perf_counter() - t0
    print(f"  {ticker:<6} {computed} nuevas · {len(rows)} totales · {el:.1f}s")
    return computed, len(rows)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Precómputo PIT de risk_score (Tarea 21, brazo B2)")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--save-every", type=int, default=250)
    args = p.parse_args(argv)

    tickers = args.tickers or parse_universe_file(_ROOT / args.universe)
    if not tickers:
        print("Universo vacío.", file=sys.stderr)
        return 1
    print(f"risk_score PIT · {len(tickers)} tickers · period={args.period} · warmup={args.warmup}")
    t0 = time.perf_counter()
    total_new = 0
    for k, t in enumerate(tickers, 1):
        new, _tot = run_ticker(t, args.period, args.warmup, save_every=args.save_every)
        total_new += new
        if k % 10 == 0:
            el = time.perf_counter() - t0
            print(f"  [{k}/{len(tickers)}] {el/60:.1f} min · faltan ~"
                  f"{(el/k)*(len(tickers)-k)/60:.1f} min")
    print(f"Listo: {total_new} evaluaciones nuevas en {(time.perf_counter()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
