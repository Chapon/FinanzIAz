"""Archiva la cinta intradía de ``price_cache`` a Parquet y poda la tabla (tarea 81).

Qué es lo que se archiva, porque el nombre de la tabla miente
------------------------------------------------------------
``price_cache`` nació como cache con TTL de 5 minutos, pero **nunca borró nada**:
por omisión quedó convertida en un **log append-only**. Lo que hay adentro no es
basura —es la **única serie intradía del proyecto**: una marca cada ~6 minutos de
los ~133 tickers del universo, y no de cualquier precio sino **el que la app vio
en cada scan**. El cache Parquet de barras guarda **diarias** (OHLC); esto no
está en ningún otro lado.

Medido el 2026-09-02: **401.659 filas** desde 2026-05-27, ~125k filas/mes, y
**0 de esas 401.659** caen dentro del TTL, o sea que su único consumidor vivo
(``get_current_price``) no puede leer ninguna. Con los índices de la tarea 74
cada fila paga además ~82 bytes de índice.

Por eso archiva en vez de podar: la cinta sobrevive **completa** fuera de la DB
operativa —el mismo camino que ARQ1 usó para las barras diarias— y la tabla queda
chica.

Invariantes de seguridad (el orden importa)
-------------------------------------------
1. **Escribir → verificar → borrar**, nunca al revés. Se releen los ids del
   Parquet recién escrito y sólo se borran los que están ahí.
2. **Escritura atómica** (``.tmp`` + ``os.replace``): un corte no deja un Parquet
   a medias (regla 5).
3. **Idempotente**: re-correrlo no duplica ni borra de más; los meses ya
   archivados se funden por ``id``.
4. Con ``--dry-run`` no escribe ni borra nada.

Uso
---
    python scripts/archive_price_cache.py --dry-run
    python scripts/archive_price_cache.py --days 7
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from database.models import DB_PATH

# Cuánto se queda en SQLite. El TTL del único lector es de 5 minutos, así que 7
# días no es una estimación de nada: es margen para poder mirar la tabla a mano
# después de un incidente sin tener que ir al archivo.
DEFAULT_KEEP_DAYS = 7

TAPE_DIR = _HERE.parent / "data" / "price_tape"
COLUMNS = ("id", "ticker", "price", "change_pct", "volume", "market_cap", "fetched_at")
_COMPRESSION = "zstd"


def tape_path(mes: str) -> Path:
    """``data/price_tape/YYYY-MM.parquet`` — un archivo por mes, todos los tickers."""
    return TAPE_DIR / f"{mes}.parquet"


def _leer_viejas(con: sqlite3.Connection, cutoff: str) -> pd.DataFrame:
    q = f"SELECT {', '.join(COLUMNS)} FROM price_cache WHERE fetched_at < ? ORDER BY id"
    return pd.read_sql_query(q, con, params=(cutoff,))


def _escribir_mes(mes: str, df: pd.DataFrame) -> set[int]:
    """Funde ``df`` con lo que ya haya de ese mes y escribe atómico. Devuelve los ids del archivo."""
    path = tape_path(mes)
    TAPE_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists():
        previo = pq.read_table(path).to_pandas()
        df = pd.concat([previo, df], ignore_index=True)
    df = df.drop_duplicates(subset=["id"]).sort_values("id").reset_index(drop=True)

    tabla = pa.Table.from_pandas(df, preserve_index=False)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        pq.write_table(tabla, tmp, compression=_COMPRESSION)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)

    # Verificación: se relee del disco, no se confía en lo que se creyó escribir.
    return set(pq.read_table(path, columns=["id"]).to_pandas()["id"].tolist())


def _borrar(con: sqlite3.Connection, ids: list[int], lote: int = 5000) -> int:
    borradas = 0
    for i in range(0, len(ids), lote):
        chunk = ids[i : i + lote]
        marcas = ",".join("?" * len(chunk))
        cur = con.execute(f"DELETE FROM price_cache WHERE id IN ({marcas})", chunk)
        borradas += cur.rowcount
        con.commit()
    return borradas


def archivar(db_path: str, keep_days: int, *, dry_run: bool = False) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime("%Y-%m-%d %H:%M:%S")
    con = sqlite3.connect(db_path, timeout=30)
    try:
        total = con.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0]
        df = _leer_viejas(con, cutoff)
        resumen = {"total": total, "candidatas": len(df), "archivadas": 0, "borradas": 0, "meses": {}}
        if df.empty:
            return resumen

        df["_mes"] = df["fetched_at"].str.slice(0, 7)
        for mes, grupo in df.groupby("_mes"):
            grupo = grupo.drop(columns=["_mes"])
            if dry_run:
                resumen["meses"][mes] = len(grupo)
                continue
            en_archivo = _escribir_mes(mes, grupo)
            ids = [int(i) for i in grupo["id"] if int(i) in en_archivo]
            faltan = len(grupo) - len(ids)
            if faltan:
                # No se borra lo que no se pudo verificar. Nunca.
                print(f"  {mes}: {faltan} fila(s) NO quedaron en el archivo — no se borran", file=sys.stderr)
            resumen["meses"][mes] = len(ids)
            resumen["archivadas"] += len(ids)
            resumen["borradas"] += _borrar(con, ids)
        return resumen
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--days", type=int, default=DEFAULT_KEEP_DAYS, help="días a dejar en SQLite")
    p.add_argument("--db", default=DB_PATH)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--vacuum",
        action="store_true",
        help="compacta el archivo después (SQLite no devuelve páginas solo). "
        "OJO: toma lock EXCLUSIVO — con la app abierta puede esperar o fallar",
    )
    args = p.parse_args(argv)

    antes = os.path.getsize(args.db) / 1e6
    r = archivar(args.db, args.days, dry_run=args.dry_run)
    print(f"price_cache: {r['total']:,} filas · candidatas (> {args.days}d): {r['candidatas']:,}")
    for mes, n in sorted(r["meses"].items()):
        print(f"  {mes}: {n:,}")
    if args.dry_run:
        print("DRY-RUN: no se escribió ni se borró nada.")
        return 0
    print(f"archivadas {r['archivadas']:,} · borradas {r['borradas']:,}")
    if args.vacuum:
        # Borrar no achica el archivo: SQLite deja las páginas libres para reusar.
        # El VACUUM lo reescribe entero, y por eso es opt-in y va al final.
        con = sqlite3.connect(args.db, timeout=60)
        try:
            con.execute("VACUUM")
        finally:
            con.close()
    sufijo = "" if args.vacuum else " (sin VACUUM — el archivo no se achica solo)"
    print(f"DB: {antes:.1f} MB → {os.path.getsize(args.db) / 1e6:.1f} MB{sufijo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
