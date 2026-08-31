#!/usr/bin/env python3
"""
benchmark_historical_cache.py — mide el costo de lectura del cache OHLCV por
backend (JSON-en-SQLite vs Parquet) para justificar ARQ1.

Simula el patrón de acceso de E4/harness: N barridos de lectura sobre todas las
claves cacheadas. Reporta tiempo total por backend, speedup y footprint en disco.
Solo lee (no escribe la DB ni la red) → seguro en Windows.

Uso
---
    python scripts/benchmark_historical_cache.py               # 3 pasadas
    python scripts/benchmark_historical_cache.py --passes 5
    python scripts/benchmark_historical_cache.py --period 10y  # solo ese period
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from io import StringIO
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DB = ROOT / "finanzias.db"


def _read_json_frame(data_json: str) -> pd.DataFrame:
    """Ruta exacta del backend viejo: parseo JSON + índice datetime."""
    df = pd.read_json(StringIO(data_json), orient="split")
    df.index = pd.to_datetime(df.index)
    return df


def _dir_size(path: Path, period: str | None = None) -> int:
    if not path.exists():
        return 0
    pattern = f"*__{period}__*.parquet" if period else "*.parquet"
    return sum(p.stat().st_size for p in path.glob(pattern))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Benchmark lectura cache OHLCV: JSON vs Parquet (ARQ1).")
    ap.add_argument("--db", type=str, default=str(DEFAULT_DB))
    ap.add_argument("--passes", type=int, default=3, help="Barridos de lectura sobre todas las claves.")
    ap.add_argument("--period", type=str, default=None, help="Filtrar por period (ej. 10y).")
    args = ap.parse_args(argv)

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: no existe {db}", file=sys.stderr)
        return 2

    from data import parquet_cache

    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    q = "SELECT ticker, period, interval, data_json FROM historical_data_cache"
    if args.period:
        q += " WHERE period = ?"
        rows = con.execute(q, (args.period,)).fetchall()
    else:
        rows = con.execute(q).fetchall()
    con.close()

    if not rows:
        print("Cache vacío (o filtro sin coincidencias).")
        return 0

    keys = [(r["ticker"], r["period"], r["interval"]) for r in rows]
    json_blobs = [r["data_json"] for r in rows]
    json_bytes = sum(len(b) for b in json_blobs)

    # Sanity de equivalencia sobre una muestra (primera clave).
    sample = _read_json_frame(json_blobs[0])
    p_sample = parquet_cache.read(*keys[0], ttl_hours=None)
    equiv = p_sample is not None and len(p_sample) == len(sample)

    # ── Backend JSON (SQLite) ────────────────────────────────────────────────
    t0 = time.perf_counter()
    n_json = 0
    for _ in range(args.passes):
        for blob in json_blobs:
            _read_json_frame(blob)
            n_json += 1
    t_json = time.perf_counter() - t0

    # ── Backend Parquet ──────────────────────────────────────────────────────
    t0 = time.perf_counter()
    n_pq = 0
    missing = 0
    for _ in range(args.passes):
        for k in keys:
            df = parquet_cache.read(*k, ttl_hours=None)
            missing += df is None
            n_pq += 1
    t_pq = time.perf_counter() - t0

    # ── Proyección columnar: solo la columna Close (patrón de features E4) ────
    import pyarrow.parquet as pq

    t0 = time.perf_counter()
    for _ in range(args.passes):
        for blob in json_blobs:
            _read_json_frame(blob)["Close"]  # JSON debe parsear TODO para sacar 1 col
    t_json_col = time.perf_counter() - t0
    t0 = time.perf_counter()
    for _ in range(args.passes):
        for k in keys:
            pq.read_table(parquet_cache.path_for(*k), columns=["Close"]).column("Close")
    t_pq_col = time.perf_counter() - t0

    pq_bytes = _dir_size(parquet_cache.get_parquet_dir(), args.period)

    print("── Benchmark cache OHLCV (ARQ1) ──────────────────────────────")
    print(f"Claves: {len(keys)}   Pasadas: {args.passes}   Period: {args.period or 'todas'}")
    print(f"Equivalencia muestra (len): {'OK' if equiv else 'MISMATCH'}")
    if missing:
        print(f"⚠ Parquet miss: {missing} lecturas (¿migración incompleta?)")
    print()
    print("Frame completo (patrón get_historical_data):")
    print(f"  JSON-en-SQLite : {t_json:8.3f}s  ({1000 * t_json / n_json:6.2f} ms/lectura)")
    print(f"  Parquet        : {t_pq:8.3f}s  ({1000 * t_pq / n_pq:6.2f} ms/lectura)")
    if t_pq > 0:
        print(f"  Speedup        : {t_json / t_pq:6.2f}×  (chico ≈ paridad; crece con el tamaño del frame)")
    print("Proyección columnar solo Close (patrón de features/E4):")
    print(f"  JSON (parsea todo): {t_json_col:8.3f}s")
    print(f"  Parquet (1 columna): {t_pq_col:8.3f}s")
    if t_pq_col > 0:
        print(f"  Speedup           : {t_json_col / t_pq_col:6.2f}×")
    print()
    print(f"Footprint  JSON (texto en DB): {json_bytes / 1e6:7.2f} MB")
    print(f"Footprint  Parquet (archivos): {pq_bytes / 1e6:7.2f} MB")
    if pq_bytes:
        print(f"Compresión                   : {json_bytes / pq_bytes:6.2f}×")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
