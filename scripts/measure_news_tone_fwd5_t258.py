"""
¿El tono −3…+3 de la pestaña Noticias ordena el retorno a 5 días? — **tarea 258, parte 2**.

Mide lo pre-registrado en ``docs/noticias_tono_t258_2026-10-01.md`` (commit ``0a5738e``).
Reusa el instrumento de la 255 (``scripts/measure_news_sentiment_fwd5_t255.py``): la entrada en
la primera apertura posterior a la publicación, la ventana de 5 ruedas y el exceso contra SPY.
El nivel es el mismo ``tone_level`` que muestra la pestaña, así que se mide lo que se ve.
Display-only: no cablea nada.

Lee la DB en sólo lectura y los frames del cache Parquet; no pega a la red.

Uso:
    python scripts/measure_news_tone_fwd5_t258.py
    python scripts/measure_news_tone_fwd5_t258.py --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analysis.news_digest import tone_level
from scripts.measure_news_sentiment_fwd5_t255 import HORIZON, entry_index, window_return

DESDE = "2026-07-01"
PERIOD = "2y"
EXTREMO = 1.5
MIN_DELTA = 0.005
N_BOOT = 5000
SEED = 258
MITAD = "2026-08-16"


def _rank(x: np.ndarray) -> np.ndarray:
    """Rangos promedio (empates incluidos), como ``scipy.stats.rankdata``."""
    orden = np.argsort(x, kind="mergesort")
    xs = x[orden]
    r = np.empty(len(x), dtype=float)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[j + 1] == xs[i]:
            j += 1
        r[orden[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return r


def spearman(tone: np.ndarray, excess: np.ndarray) -> float | None:
    if len(tone) < 3 or np.all(tone == tone[0]) or np.all(excess == excess[0]):
        return None
    return float(np.corrcoef(_rank(tone), _rank(excess))[0, 1])


def delta_ext(units: list[dict]) -> float | None:
    alta = [u["excess"] for u in units if u["tone"] >= EXTREMO]
    baja = [u["excess"] for u in units if u["tone"] <= -EXTREMO]
    if not alta or not baja:
        return None
    return float(np.mean(alta) - np.mean(baja))


def _rho(units: list[dict]) -> float | None:
    if not units:
        return None
    return spearman(np.array([u["tone"] for u in units]), np.array([u["excess"] for u in units]))


def build_units(
    rows, frames: dict[str, pd.DataFrame], spy: pd.DataFrame, *, last_day: pd.Timestamp
) -> list[dict]:
    """``rows``: ``(ticker, published_at, sentiment, sentiment_score)``. Tono de la unidad = media de niveles."""
    agrupado: dict[tuple[str, str], dict] = {}
    for ticker, published, sentiment, score in rows:
        df = frames.get(ticker)
        if df is None:
            continue
        e = entry_index(df.index, datetime.fromisoformat(str(published)[:19]))
        if e is None or df.index[min(e + HORIZON - 1, len(df) - 1)] >= last_day:
            continue
        g = agrupado.setdefault((ticker, df.index[e].date().isoformat()), {"pos": e, "levels": []})
        g["levels"].append(tone_level(score, sentiment))

    units = []
    for (ticker, dia), g in agrupado.items():
        r = window_return(frames[ticker], g["pos"])
        sp = spy.index.searchsorted(pd.Timestamp(dia))
        if r is None or sp >= len(spy) or spy.index[sp] != pd.Timestamp(dia):
            continue
        rs = window_return(spy, int(sp))
        if rs is None:
            continue
        units.append(
            {"ticker": ticker, "entry_day": dia, "tone": float(np.mean(g["levels"])), "excess": r - rs}
        )
    return units


def bootstrap_by_day(
    units: list[dict], stat, n_boot: int = N_BOOT, seed: int = SEED
) -> tuple[float, float, float]:
    por_dia: dict[str, list[dict]] = defaultdict(list)
    for u in units:
        por_dia[u["entry_day"]].append(u)
    dias = list(por_dia)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        v = stat([u for i in rng.integers(0, len(dias), len(dias)) for u in por_dia[dias[i]]])
        if v is not None:
            vals.append(v)
    arr = np.asarray(vals)
    return float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5)), float(arr.std(ddof=1))


def por_nivel(units: list[dict]) -> dict[int, dict]:
    out: dict[int, list[float]] = defaultdict(list)
    for u in units:
        out[int(np.floor(abs(u["tone"]) + 0.5) * np.sign(u["tone"]))].append(u["excess"])
    return {k: {"n": len(v), "mean": float(np.mean(v))} for k, v in sorted(out.items())}


def report(units: list[dict]) -> dict:
    lo, hi, se = bootstrap_by_day(units, _rho)
    d3 = [u["excess"] for u in units if u["tone"] >= 2.5]
    d2 = [u["excess"] for u in units if 1.5 <= u["tone"] < 2.5]
    return {
        "n": len(units),
        "n_days": len({u["entry_day"] for u in units}),
        "rho": _rho(units),
        "rho_ci95": [lo, hi],
        "rho_mde": 2.8 * se,
        "delta_ext": delta_ext(units),
        "n_alta": sum(u["tone"] >= EXTREMO for u in units),
        "n_baja": sum(u["tone"] <= -EXTREMO for u in units),
        "rho_h1": _rho([u for u in units if u["entry_day"] < MITAD]),
        "rho_h2": _rho([u for u in units if u["entry_day"] >= MITAD]),
        "por_nivel": por_nivel(units),
        "mas3_vs_mas2": (float(np.mean(d3) - np.mean(d2)) if d3 and d2 else None),
        "n_mas3": len(d3),
        "n_mas2": len(d2),
    }


def verdict(r: dict) -> tuple[bool, list[str]]:
    fallas = []
    if not (r["rho"] is not None and r["rho"] > 0):
        fallas.append("ρ no es > 0")
    if not r["rho_ci95"][0] > 0:
        fallas.append("el IC 95% de ρ incluye el 0")
    if not (r["delta_ext"] is not None and r["delta_ext"] >= MIN_DELTA):
        fallas.append(f"Δ_ext < {MIN_DELTA * 100:.1f} pp")
    if r["rho_h1"] is None or r["rho_h2"] is None or (r["rho_h1"] > 0) != (r["rho_h2"] > 0):
        fallas.append("el signo de ρ no coincide entre las dos mitades")
    return (not fallas), fallas


def _load(db: Path):
    from data import parquet_cache
    from database.readonly import readonly_uri

    con = sqlite3.connect(readonly_uri(db), uri=True)
    rows = con.execute(
        "SELECT ticker, published_at, sentiment, sentiment_score FROM news_events "
        "WHERE sentiment_score IS NOT NULL AND published_at >= ? AND ticker IS NOT NULL",
        (DESDE,),
    ).fetchall()
    frames = {}
    for t in sorted({r[0] for r in rows}):
        df = parquet_cache.read(t, PERIOD, "1d", None)
        if df is not None and {"Open", "Close"} <= set(df.columns) and len(df):
            frames[t] = df.sort_index()
    spy = parquet_cache.read("SPY", "10y", "1d", None).sort_index()
    return rows, frames, spy


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Tarea 258: tono de noticias (−3…+3) vs retorno a 5 días.")
    p.add_argument("--db", default=str(_ROOT / "finanzias.db"))
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    rows, frames, spy = _load(Path(args.db))
    hoy = pd.Timestamp(date.today())  # la barra de hoy no asentó (T112)
    units = build_units(rows, frames, spy, last_day=hoy)
    # El guard del cohorte (T30) no mira estos frames: la frescura se declara acá.
    viejos = sorted(t for t, df in frames.items() if np.busday_count(df.index[-1].date(), hoy.date()) > 3)
    r = report(units)
    ok, fallas = verdict(r)
    out = {
        "filas": len(rows),
        "tickers_con_frame": len(frames),
        "frames_atrasados": viejos,
        **r,
        "veredicto": "PASA" if ok else "NO PASA",
        "fallas": fallas,
    }
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    print(f"Noticias con polaridad desde {DESDE}: {len(rows)} · tickers con frame {PERIOD}: {len(frames)}")
    print(
        f"Frames {PERIOD} con más de 3 ruedas de atraso: {len(viejos)}"
        + (f" ({', '.join(viejos)})" if viejos else "")
    )
    print(f"\nUnidades: {r['n']} en {r['n_days']} ruedas")
    print(
        f"  ρ = {r['rho']:+.4f} · IC95 [{r['rho_ci95'][0]:+.4f}, {r['rho_ci95'][1]:+.4f}] · MDE ≈ {r['rho_mde']:.4f}"
    )
    print(f"  mitades: {r['rho_h1']:+.4f} | {r['rho_h2']:+.4f}")
    print(
        f"  Δ_ext (tono ≥ +1,5: n={r['n_alta']} vs ≤ −1,5: n={r['n_baja']}) = {r['delta_ext'] * 100:+.2f} pp"
    )
    print("  exceso medio por nivel:")
    for k, v in r["por_nivel"].items():
        print(f"    {k:+d}: n={v['n']:5d}  {v['mean'] * 100:+.2f} pp")
    if r["mas3_vs_mas2"] is not None:
        print(f"  +3 vs +2: {r['mas3_vs_mas2'] * 100:+.2f} pp (n={r['n_mas3']} / {r['n_mas2']})")
    print(f"\nVEREDICTO: {out['veredicto']}" + (f" — {'; '.join(fallas)}" if fallas else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
