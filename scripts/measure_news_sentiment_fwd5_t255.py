"""
¿El sentimiento de una noticia predice el retorno a 5 días? — **tarea 255**.

Mide lo pre-registrado en ``docs/noticias_impacto_t255_2026-10-01.md`` (commit ``be2edf1``),
que fija definiciones y veredicto **antes** de mirar retornos. Display-only: no cablea nada.

- Entrada: la primera apertura **posterior a la publicación** (hora de Nueva York).
- Salida: cierre de la quinta rueda contando la de entrada. Retorno en exceso contra SPY.
- Unidad: ``(ticker, rueda de entrada)`` con sentimiento neto (#positivas − #negativas).
- ``Δ = media(exceso | positiva) − media(exceso | negativa)``, IC por bootstrap de ruedas.

Lee la DB en sólo lectura y los frames del cache Parquet; no pega a la red.

Uso:
    python scripts/measure_news_sentiment_fwd5_t255.py
    python scripts/measure_news_sentiment_fwd5_t255.py --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

HORIZON = 5
DESDE = "2026-06-01"
MIN_DELTA = 0.005
N_BOOT = 5000
SEED = 255
MITAD = "2026-08-01"  # junio–julio | agosto–septiembre
_NY = ZoneInfo("America/New_York")
_APERTURA = time(9, 30)


def entry_index(index: pd.DatetimeIndex, published_utc: datetime) -> int | None:
    """Posición de la primera rueda cuya **apertura** es posterior a la publicación.

    Antes de las 09:30 ET de una rueda → esa rueda; después (o en un día sin rueda) → la
    siguiente. ``None`` si no hay rueda posterior en el frame.
    """
    ny = published_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(_NY)
    dia = pd.Timestamp(ny.date())
    pos = int(index.searchsorted(dia, side="left"))
    if pos < len(index) and index[pos] == dia and ny.time() >= _APERTURA:
        pos += 1
    return pos if pos < len(index) else None


def window_return(df: pd.DataFrame, entry_pos: int, horizon: int = HORIZON) -> float | None:
    """Apertura de ``entry_pos`` → cierre de ``entry_pos + horizon − 1``. ``None`` si no alcanza."""
    exit_pos = entry_pos + horizon - 1
    if exit_pos >= len(df):
        return None
    p0, p1 = float(df["Open"].iloc[entry_pos]), float(df["Close"].iloc[exit_pos])
    if not (np.isfinite(p0) and np.isfinite(p1)) or p0 <= 0:
        return None
    return p1 / p0 - 1.0


def net_label(sentiments: list[str]) -> int:
    """+1 / −1 / 0 según #positivas − #negativas."""
    neto = sum(1 for s in sentiments if s == "positive") - sum(1 for s in sentiments if s == "negative")
    return (neto > 0) - (neto < 0)


def delta(units: list[dict]) -> float | None:
    pos = [u["excess"] for u in units if u["label"] > 0]
    neg = [u["excess"] for u in units if u["label"] < 0]
    if not pos or not neg:
        return None
    return float(np.mean(pos) - np.mean(neg))


def bootstrap_by_day(units: list[dict], n_boot: int = N_BOOT, seed: int = SEED) -> tuple[float, float, float]:
    """IC 95% y error estándar de ``delta`` re-muestreando **ruedas enteras**."""
    por_dia: dict[str, list[dict]] = defaultdict(list)
    for u in units:
        por_dia[u["entry_day"]].append(u)
    dias = list(por_dia)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        muestra = [u for i in rng.integers(0, len(dias), len(dias)) for u in por_dia[dias[i]]]
        d = delta(muestra)
        if d is not None:
            vals.append(d)
    arr = np.asarray(vals)
    return float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5)), float(arr.std(ddof=1))


def build_units(
    rows, frames: dict[str, pd.DataFrame], spy: pd.DataFrame, *, last_day: pd.Timestamp
) -> list[dict]:
    """``rows``: ``(ticker, published_at, sentiment, event_type)``. Una unidad por (ticker, rueda)."""
    agrupado: dict[tuple[str, str], dict] = {}
    for ticker, published, sentiment, etype in rows:
        df = frames.get(ticker)
        if df is None:
            continue
        pub = datetime.fromisoformat(str(published)[:19])
        e = entry_index(df.index, pub)
        if e is None:
            continue
        dia = df.index[e]
        if df.index[min(e + HORIZON - 1, len(df) - 1)] >= last_day:
            continue
        k = (ticker, dia.date().isoformat())
        g = agrupado.setdefault(k, {"pos": e, "sent": [], "types": set()})
        g["sent"].append(sentiment)
        g["types"].add(etype)

    units = []
    for (ticker, dia), g in agrupado.items():
        label = net_label(g["sent"])
        if label == 0:
            continue
        r = window_return(frames[ticker], g["pos"])
        sp = spy.index.searchsorted(pd.Timestamp(dia))
        if r is None or sp >= len(spy) or spy.index[sp] != pd.Timestamp(dia):
            continue
        rs = window_return(spy, int(sp))
        if rs is None:
            continue
        units.append(
            {
                "ticker": ticker,
                "entry_day": dia,
                "label": label,
                "excess": r - rs,
                "earnings": "earnings_results" in g["types"],
            }
        )
    return units


def report(units: list[dict]) -> dict:
    d = delta(units)
    lo, hi, se = bootstrap_by_day(units)
    h1 = delta([u for u in units if u["entry_day"] < MITAD])
    h2 = delta([u for u in units if u["entry_day"] >= MITAD])
    return {
        "n_pos": sum(u["label"] > 0 for u in units),
        "n_neg": sum(u["label"] < 0 for u in units),
        "n_days": len({u["entry_day"] for u in units}),
        "mean_pos": float(np.mean([u["excess"] for u in units if u["label"] > 0])),
        "mean_neg": float(np.mean([u["excess"] for u in units if u["label"] < 0])),
        "delta": d,
        "ci95": [lo, hi],
        "se": se,
        "mde": 2.8 * se,
        "delta_h1": h1,
        "delta_h2": h2,
    }


def verdict(r: dict) -> tuple[bool, list[str]]:
    fallas = []
    if not (r["delta"] is not None and r["delta"] > 0):
        fallas.append("Δ no es > 0")
    if not r["ci95"][0] > 0:
        fallas.append("el IC 95% incluye el 0")
    if not (r["delta"] is not None and r["delta"] >= MIN_DELTA):
        fallas.append(f"Δ < {MIN_DELTA * 100:.1f} pp")
    if r["delta_h1"] is None or r["delta_h2"] is None or (r["delta_h1"] > 0) != (r["delta_h2"] > 0):
        fallas.append("el signo no coincide entre las dos mitades")
    return (not fallas), fallas


def _load(db: Path, period: str):
    from data import parquet_cache
    from database.readonly import readonly_uri

    con = sqlite3.connect(readonly_uri(db), uri=True)
    rows = con.execute(
        "SELECT ticker, published_at, sentiment, event_type FROM news_events "
        "WHERE sentiment IN ('positive','negative') AND published_at >= ? AND ticker IS NOT NULL",
        (DESDE,),
    ).fetchall()
    frames = {}
    for t in sorted({r[0] for r in rows}):
        df = parquet_cache.read(t, period, "1d", None)
        if df is not None and {"Open", "Close"} <= set(df.columns) and len(df):
            frames[t] = df.sort_index()
    spy = parquet_cache.read("SPY", "10y", "1d", None).sort_index()
    return rows, frames, spy


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Tarea 255: sentimiento de noticias vs retorno a 5 días.")
    p.add_argument("--db", default=str(_ROOT / "finanzias.db"))
    p.add_argument(
        "--period",
        default="1y",
        help="frames de precio: 1y es lo pre-registrado; 2y es el que la app mantiene al día (desvío declarado)",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    rows, frames, spy = _load(Path(args.db), args.period)
    hoy = pd.Timestamp(date.today())  # la barra de hoy no asentó (T112): ninguna salida la usa
    units = build_units(rows, frames, spy, last_day=hoy)
    # El guard del cohorte (T30) no mira estos frames: la frescura se declara acá.
    viejos = sorted(t for t, df in frames.items() if np.busday_count(df.index[-1].date(), hoy.date()) > 3)
    out = {
        "filas_no_neutrales": len(rows),
        "period": args.period,
        "tickers_con_frame": len(frames),
        "frames_atrasados": viejos,
        "primaria": report(units),
        "earnings_results": report([u for u in units if u["earnings"]]),
    }
    ok, fallas = verdict(out["primaria"])
    out["veredicto"] = "PASA" if ok else "NO PASA"
    out["fallas"] = fallas
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    print(
        f"Noticias no neutrales desde {DESDE}: {len(rows)} · tickers con frame {args.period}: {len(frames)}"
    )
    print(
        f"Frames {args.period} con más de 3 ruedas de atraso: {len(viejos)}"
        + (f" ({', '.join(viejos)})" if viejos else "")
    )
    for nombre in ("primaria", "earnings_results"):
        r = out[nombre]
        print(
            f"\n[{nombre}] n+={r['n_pos']} n-={r['n_neg']} ruedas={r['n_days']}\n"
            f"  exceso medio +: {r['mean_pos'] * 100:+.2f} pp · −: {r['mean_neg'] * 100:+.2f} pp\n"
            f"  Δ = {r['delta'] * 100:+.2f} pp · IC95 [{r['ci95'][0] * 100:+.2f}, {r['ci95'][1] * 100:+.2f}] "
            f"· MDE ≈ {r['mde'] * 100:.2f} pp\n"
            f"  jun–jul: {r['delta_h1'] * 100:+.2f} pp · ago–sep: {r['delta_h2'] * 100:+.2f} pp"
        )
    print(f"\nVEREDICTO (primaria): {out['veredicto']}" + (f" — {'; '.join(fallas)}" if fallas else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
