"""Tarea 458 — el almacén de fechas de balance para modelar el Gate 6 (blackout de earnings).

La 96 dio el Gate 6 por no modelable (*«no hay fechas de earnings point-in-time a 10 años»*), y Yahoo
devuelve 49 trimestres por ticker desde 2014 con ``get_earnings_dates(limit=48)``. La fecha de un
balance es un dato duro: no se revisa después.

Baja las fechas de los tickers del universo y las guarda, con la fecha de captura, en
``data/earnings_dates/fechas_balance.json``. Imprime la cobertura: cuántos tickers tienen fechas y
desde cuándo, contra el arranque del cohorte del harness.

**Supuesto, declarado:** el harness usa la fecha real como si se conociera antes. Las empresas la
anuncian semanas antes y reprogramar es raro, pero no es punto en el tiempo en sentido estricto.

Comando (pega a la red de Yahoo, ~1 s por ticker)::

    python scripts/bajar_fechas_balance_t458.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from analysis.harness_config import LIVE_UNIVERSE_FILE
from scripts.precompute_pit_signals import parse_universe_file

SALIDA = Path("data") / "earnings_dates" / "fechas_balance.json"
LIMITE = 48
FUENTE = f"yfinance Ticker.get_earnings_dates(limit={LIMITE})"


def fechas_de(df) -> list[str]:
    """Las fechas (``YYYY-MM-DD``, día de la bolsa) de un frame de ``get_earnings_dates``, únicas y
    ordenadas. El índice viene con zona horaria de Nueva York; la fecha es la de ese día local."""
    if df is None or getattr(df, "empty", True):
        return []
    return sorted({ts.strftime("%Y-%m-%d") for ts in df.index})


def cobertura(fechas: dict[str, list[str]], desde: str) -> dict:
    """Cuántos tickers tienen fechas, y cuántos arrancan después de ``desde`` (el cohorte)."""
    con = {t: f for t, f in fechas.items() if f}
    tarde = sorted(t for t, f in con.items() if f[0] > desde)
    return {
        "tickers": len(fechas),
        "con_fechas": len(con),
        "sin_fechas": sorted(t for t, f in fechas.items() if not f),
        "arrancan_despues_del_cohorte": tarde,
        "fechas_totales": sum(len(f) for f in con.values()),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fechas de balance para el Gate 6 (tarea 458)")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--out", default=str(SALIDA))
    p.add_argument("--pausa", type=float, default=1.0, help="segundos entre pedidos")
    p.add_argument("--cohorte-desde", default="2016-09-12")
    args = p.parse_args(argv)

    from data.yahoo_finance import _ticker

    tickers = parse_universe_file(_HERE.parent / args.universe)
    fechas: dict[str, list[str]] = {}
    errores: dict[str, str] = {}
    for i, t in enumerate(tickers, 1):
        for intento in range(3):
            try:
                fechas[t] = fechas_de(_ticker(t).get_earnings_dates(limit=LIMITE))
                break
            except Exception as exc:  # la red: se reintenta y, si no, queda anotado
                errores[t] = f"{type(exc).__name__}: {exc}"[:200]
                time.sleep(args.pausa * (intento + 2))
        else:
            fechas[t] = []
        if fechas[t]:
            errores.pop(t, None)
        print(f"  {i:>3}/{len(tickers)} {t:<8} {len(fechas[t]):>3} fechas", flush=True)
        time.sleep(args.pausa)

    cob = cobertura(fechas, args.cohorte_desde)
    salida = {
        "capturado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": FUENTE,
        "universo": args.universe,
        "cobertura": cob,
        "errores": errores,
        "fechas": fechas,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(salida, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    print(
        f"\n{cob['con_fechas']} de {cob['tickers']} con fechas ({cob['fechas_totales']} en total); "
        f"sin fechas: {cob['sin_fechas']}; arrancan después de {args.cohorte_desde}: "
        f"{cob['arrancan_despues_del_cohorte']}; errores: {len(errores)} → {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
