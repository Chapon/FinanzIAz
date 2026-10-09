"""Saca del cache de parquet la última barra 1d que ``clean_ohlcv`` rellenó con la de ayer (tarea 344).

Hasta la 344, cuando Yahoo devolvía la barra de hoy con OHLC vacío y sólo el volumen, el
``ffill`` de ``clean_ohlcv`` le copiaba los precios de la barra anterior y el frame se cacheaba
así: un «cierre de hoy» que es el de ayer. El 2026-10-08 eran 135 frames.

La firma que busca es la de ese defecto y nada más: la **última** fila con Open, High, Low y
Close **idénticos** a la anterior y un volumen **distinto** (el volumen sí venía de Yahoo). Las
filas intermedias con ese patrón no se tocan: medidas el 2026-10-08, son días planos de tickers
ilíquidos (casi todas con volumen 0, ninguna posterior a 2024-07), no este defecto.

Reescribe el archivo sin esa fila y **conserva su metadata** (el ``fetched_at`` del TTL), con un
temporal y ``os.replace`` como ``parquet_cache.write``. **Correrlo con la app cerrada**: la app
escribe el mismo cache, y si corre el código de antes de la 344 vuelve a rellenar la barra.

    python scripts/limpiar_barra_rellenada.py            # lista lo que sacaría, no escribe
    python scripts/limpiar_barra_rellenada.py --aplicar  # reescribe los archivos
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import pyarrow.parquet as pq

from data import parquet_cache

_OHLC = ("Open", "High", "Low", "Close")


def ultima_barra_rellenada(df) -> bool:
    """¿La última fila tiene el OHLC de la anterior y otro volumen? (la firma del defecto)."""
    if df is None or len(df) < 2 or not set(_OHLC) <= set(df.columns) or "Volume" not in df:
        return False
    ult, ant = df.iloc[-1], df.iloc[-2]
    return all(ult[c] == ant[c] for c in _OHLC) and ult["Volume"] != ant["Volume"]


def limpiar(directorio: Path, aplicar: bool) -> list[tuple[str, str]]:
    """Devuelve ``(archivo, fecha de la fila)`` de cada frame afectado; con ``aplicar``, la saca."""
    afectados = []
    for path in sorted(directorio.glob("*__1d.parquet")):
        df = parquet_cache._restore_frame(path)
        if not ultima_barra_rellenada(df):
            continue
        afectados.append((path.name, str(df.index[-1])[:10]))
        if aplicar:
            tabla = pq.read_table(path)
            recortada = tabla.slice(0, tabla.num_rows - 1).replace_schema_metadata(tabla.schema.metadata)
            tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.t344")
            try:
                pq.write_table(recortada, tmp, compression="zstd")
                os.replace(tmp, path)
            finally:
                if tmp.exists():
                    tmp.unlink()
    return afectados


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--aplicar", action="store_true", help="reescribe los archivos (sin esto, sólo lista)")
    args = ap.parse_args(argv)
    directorio = parquet_cache.get_parquet_dir()
    afectados = limpiar(directorio, args.aplicar)
    for nombre, fecha in afectados:
        print(f"{nombre}: última fila {fecha} rellenada con la anterior")
    verbo = "sacadas" if args.aplicar else "a sacar (sin --aplicar no se escribe nada)"
    print(f"{len(afectados)} barra(s) {verbo} en {directorio}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
