"""
¿Por qué no compramos X? — consulta del registro de candidatos del scan (**tarea 256**).

Lee ``paper_scan_candidates`` (lo que cada scan evaluó como compra y cómo terminó) y lo
resume **día por día** para un ticker. Para distinguir *«no fue candidato»* de *«la app no
corrió»*, cuenta los scans del día en ``paper_equity_snapshots``, que el scan escribe en cada
pasada: un día con scans y sin filas del ticker es un día en que **ningún scan lo vio como
compra** (dio HOLD/SELL o ya estaba en cartera).

**Alcance:** el registro existe desde la tarea 256 (2026-10-01) y guarda 90 días. Para fechas
anteriores no hay respuesta acá; lo único que queda es reconstruir con el store PIT, que no
coincide con el score vivo (ver la tarea 256 en el backlog).

Lee la DB en sólo lectura. Por default, la cuenta **viva** (resuelta contra ``is_active``).

**Los días son en UTC**, como guarda todo la app: un scan de la noche de Nueva York cae en el
día UTC siguiente.

Uso:
    python scripts/por_que_no_compramos.py ACN
    python scripts/por_que_no_compramos.py ACN --desde 2026-10-01 --account 2
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from database.readonly import readonly_uri
from scripts.baseline_metrics import resolve_account_id

_ORDEN = ("comprado", "encolado", "bloqueado", "sin_tamano", "sin_lugar", "screen", "sin_datos")


def resumen_por_dia(filas: list[tuple], scans_por_dia: dict[str, int]) -> list[dict]:
    """``filas``: ``(scan_at, outcome, score, rank, detail)`` del ticker. Un registro por día con scans."""
    por_dia: dict[str, list[tuple]] = defaultdict(list)
    for f in filas:
        por_dia[str(f[0])[:10]].append(f)
    out = []
    for dia in sorted(set(scans_por_dia) | set(por_dia)):
        fs = por_dia.get(dia, [])
        conteo = Counter(f[1] for f in fs)
        scores = [f[2] for f in fs if f[2] is not None]
        ranks = [f[3] for f in fs if f[3] is not None]
        detalles = Counter(f[4] for f in fs if f[1] == "bloqueado" and f[4])
        out.append(
            {
                "dia": dia,
                "scans": scans_por_dia.get(dia, 0),
                "apariciones": len(fs),
                "resultados": {k: conteo[k] for k in _ORDEN if conteo[k]},
                "score_max": max(scores) if scores else None,
                "mejor_rank": min(ranks) if ranks else None,
                "bloqueo_mas_comun": detalles.most_common(1)[0][0] if detalles else None,
                "contexto": next((f[4] for f in fs if f[1] == "sin_lugar" and f[4]), None),
            }
        )
    return out


def leyenda(r: dict) -> str:
    if r["scans"] == 0 and r["apariciones"] == 0:
        # Tarea 263 [M-1]: un día sin snapshot es «sin scans COMPLETADOS». Puede ser la app
        # cerrada o scans que fallaron (no dejan snapshot); el log dice cuál.
        return "sin scans completados (app cerrada o scans fallidos: ver el log)"
    if r["apariciones"] == 0:
        return f"{r['scans']} scans: nunca fue candidato a compra (HOLD/SELL o ya en cartera)"
    partes = ", ".join(f"{k} {v}" for k, v in r["resultados"].items())
    txt = f"{r['scans']} scans, candidato en {r['apariciones']}: {partes}"
    if r["score_max"] is not None:
        txt += f" · score máx {r['score_max']:.2f}"
    if r["mejor_rank"] is not None:
        txt += f" · mejor puesto {r['mejor_rank']}"
    if r["contexto"]:
        txt += f" ({r['contexto']})"
    if r["bloqueo_mas_comun"]:
        txt += f"\n             bloqueo: {r['bloqueo_mas_comun']}"
    return txt


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="¿Por qué no compramos X? (registro de la tarea 256)")
    p.add_argument("ticker")
    p.add_argument("--desde", default=None, help="AAAA-MM-DD (default: todo lo registrado)")
    p.add_argument("--hasta", default=None, help="AAAA-MM-DD")
    p.add_argument("--account", type=int, default=None, help="default: la cuenta viva")
    p.add_argument("--db", default=str(_ROOT / "finanzias.db"))
    args = p.parse_args(argv)

    con = sqlite3.connect(readonly_uri(Path(args.db)), uri=True)
    cuenta = resolve_account_id(con, args.account)
    ticker = args.ticker.upper()
    desde = args.desde or "0000-00-00"
    hasta = (args.hasta or "9999-12-31") + " 99"

    hay = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_scan_candidates'"
    ).fetchone()
    if not hay:
        print("La tabla paper_scan_candidates todavía no existe: se crea al abrir la app (tarea 256).")
        return 1
    primero = con.execute(
        "SELECT MIN(scan_at) FROM paper_scan_candidates WHERE account_id=?", (cuenta,)
    ).fetchone()[0]
    filas = con.execute(
        "SELECT scan_at, outcome, signal_score, rank, detail FROM paper_scan_candidates "
        "WHERE account_id=? AND ticker=? AND scan_at>=? AND scan_at<=? ORDER BY scan_at",
        (cuenta, ticker, desde, hasta),
    ).fetchall()
    desde_scans = max(desde, (primero or "9999")[:10])
    scans = dict(
        con.execute(
            "SELECT substr(snapshot_at,1,10), COUNT(*) FROM paper_equity_snapshots "
            "WHERE account_id=? AND snapshot_at>=? AND snapshot_at<=? GROUP BY 1",
            (cuenta, desde_scans, hasta),
        ).fetchall()
    )
    print(f"{ticker} · cuenta {cuenta} · registro desde {primero or '—'}")
    if not primero:
        print("Todavía no hay ningún scan registrado para esta cuenta.")
        return 0
    for r in resumen_por_dia(filas, scans):
        print(f"  {r['dia']}  {leyenda(r)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
