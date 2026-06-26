#!/usr/bin/env python3
"""
purge_synthetic_cache.py — borra del cache histórico las filas con datos
sintéticos de test que se filtraron a la `finanzias.db` real.

Contexto
--------
`tests/test_historical_batch.py` escribía (vía `get_historical_data_batch` →
`_finalize_historical` → `_write_historical_cache`) frames sintéticos en la
`finanzias.db` de producción porque no aislaba la DB ni mockeaba la escritura.
Resultado: entradas como AAPL/MSFT `1y` con una rampa 100→104 fechada
2026-01-01..05 y volumen ~1.000.000 → la pestaña Análisis mostraba basura y
RSI/Bollinger/SMA quedaban "Sin datos". El fix de raíz ya está en el test; este
script limpia el daño que quedó en la DB para que la app re-baje datos reales.

Firma de pollution detectada (conservadora, para no tocar datos reales):
  - primera fecha del índice == 2026-01-01, **y**
  - primer volumen ∈ [999.999, 1.000.010], **y**
  - ≤ 10 filas.

Uso (Windows — NO correr desde Linux/sandbox; corrompe la DB vía mounts)
-----------------------------------------------------------------------
    python scripts/purge_synthetic_cache.py            # dry-run: solo lista
    python scripts/purge_synthetic_cache.py --apply     # borra de verdad

Tras correr con --apply, reanalizá los tickers afectados: la app verá el cache
vacío y volverá a bajar la serie real de yfinance.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "finanzias.db"

SYNTH_FIRST_DATE = "2026-01-01"
SYNTH_VOL_LO, SYNTH_VOL_HI = 999_999, 1_000_010
MAX_ROWS = 10


def _is_synthetic(data_json: str) -> bool:
    """True si el frame tiene la firma del fixture de test (no datos reales)."""
    try:
        d = json.loads(data_json)
    except Exception:
        return False
    if not isinstance(d, dict) or "index" not in d:
        return False
    idx = d.get("index") or []
    if not idx or len(idx) > MAX_ROWS:
        return False
    if not str(idx[0]).startswith(SYNTH_FIRST_DATE):
        return False
    cols = d.get("columns") or []
    data = d.get("data") or []
    if "Volume" not in cols or not data:
        return False
    v0 = data[0][cols.index("Volume")]
    return SYNTH_VOL_LO <= v0 <= SYNTH_VOL_HI


def find_synthetic(con: sqlite3.Connection) -> list[tuple]:
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, ticker, period, interval, data_json, fetched_at "
        "FROM historical_data_cache"
    ).fetchall()
    return [
        (r["id"], r["ticker"], r["period"], r["interval"], r["fetched_at"])
        for r in rows
        if _is_synthetic(r["data_json"])
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Purga filas sintéticas del cache histórico.")
    ap.add_argument("--db", type=str, default=str(DEFAULT_DB), help="Ruta a finanzias.db")
    ap.add_argument("--apply", action="store_true", help="Borrar de verdad (sin esto, dry-run).")
    args = ap.parse_args(argv)

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: no existe {db}", file=sys.stderr)
        return 2

    con = sqlite3.connect(str(db))
    try:
        bad = find_synthetic(con)
        if not bad:
            print("Cache limpio: no se encontraron filas sintéticas.")
            return 0
        print(f"Filas sintéticas encontradas: {len(bad)}")
        for _id, tk, per, iv, fa in bad:
            print(f"  id={_id}  {tk} {per}/{iv}  (escrita {fa})")
        if not args.apply:
            print("\nDry-run. Volvé a correr con --apply para borrarlas.")
            return 0
        ids = [b[0] for b in bad]
        con.executemany("DELETE FROM historical_data_cache WHERE id=?", [(i,) for i in ids])
        con.commit()
        print(f"\nBorradas {len(ids)} filas. Reanalizá esos tickers para re-bajar datos reales.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
