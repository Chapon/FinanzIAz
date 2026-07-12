#!/usr/bin/env python3
"""
migrate_historical_cache_to_parquet.py — migración one-shot del cache OHLCV
histórico de JSON-en-SQLite (``historical_data_cache``) a Parquet por
``(ticker, period, interval)`` en ``data/parquet/`` (backlog ARQ1).

Qué hace
--------
Lee cada fila de ``historical_data_cache`` (DataFrame serializado como JSON de
texto), la deserializa igual que el backend viejo (``read_json`` orient=split) y
la reescribe como un ``.parquet`` **preservando el ``fetched_at`` original** para
que la semántica de TTL sea idéntica tras el swap. NO toca la tabla SQLite:
el rollback es simplemente volver el flag ``historical_cache_backend`` a
``"sqlite"``. Es **idempotente** (reescribe el mismo archivo por clave).

Uso (Windows — NO correr desde Linux/sandbox: lee la DB viva, regla 5)
---------------------------------------------------------------------
    python scripts/migrate_historical_cache_to_parquet.py            # dry-run
    python scripts/migrate_historical_cache_to_parquet.py --apply     # migra

Después de ``--apply``, activar el backend nuevo seteando en
``~/.finanzias/settings.json``:  ``"historical_cache_backend": "parquet"``
(o ``"dual"`` para transición). Verificar la app; rollback = volver a ``"sqlite"``.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import timezone
from io import StringIO
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DB = ROOT / "finanzias.db"


def _parse_fetched_at(raw):
    """El ``fetched_at`` de SQLAlchemy es un datetime UTC naive (utcnow_naive)."""
    if raw is None:
        return None
    try:
        dt = pd.to_datetime(raw).to_pydatetime()
    except Exception:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def migrate(db_path, *, apply: bool = False, parquet_dir=None, log=print) -> dict:
    """Migra las filas del cache histórico a Parquet.

    Devuelve stats ``{rows, written, failed}``. Con ``apply=False`` solo cuenta
    (dry-run). ``parquet_dir`` (opcional) redirige el destino (tests); si es
    ``None`` usa el default de ``parquet_cache`` (``data/parquet/``).
    """
    from data import parquet_cache

    if parquet_dir is not None:
        parquet_cache.set_parquet_dir(parquet_dir)

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    written = failed = 0
    try:
        rows = con.execute(
            "SELECT ticker, period, interval, data_json, fetched_at "
            "FROM historical_data_cache"
        ).fetchall()
    finally:
        con.close()

    for r in rows:
        key = f"{r['ticker']} {r['period']}/{r['interval']}"
        try:
            df = pd.read_json(StringIO(r["data_json"]), orient="split")
            df.index = pd.to_datetime(df.index)
        except Exception as exc:
            failed += 1
            log(f"  FALLÓ parse {key}: {exc}")
            continue
        if df.empty:
            failed += 1
            log(f"  VACÍO {key} — salteado")
            continue
        if apply:
            parquet_cache.write(
                r["ticker"], r["period"], r["interval"], df,
                fetched_at=_parse_fetched_at(r["fetched_at"]),
            )
        written += 1

    return {"rows": len(rows), "written": written, "failed": failed}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Migra historical_data_cache (JSON-en-SQLite) a Parquet (ARQ1)."
    )
    ap.add_argument("--db", type=str, default=str(DEFAULT_DB), help="Ruta a finanzias.db")
    ap.add_argument("--apply", action="store_true", help="Escribir los parquet (sin esto, dry-run).")
    args = ap.parse_args(argv)

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: no existe {db}", file=sys.stderr)
        return 2

    from data import parquet_cache

    stats = migrate(db, apply=args.apply)
    dest = parquet_cache.get_parquet_dir()
    verb = "Escritas" if args.apply else "A migrar"
    print(f"Filas en cache: {stats['rows']}  |  {verb}: {stats['written']}  |  Fallidas: {stats['failed']}")
    if not args.apply:
        print("\nDry-run. Volvé a correr con --apply para escribir los parquet.")
    else:
        print(f"\nParquet escritos en {dest}")
        print('Activá el backend: "historical_cache_backend": "parquet" en ~/.finanzias/settings.json')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
