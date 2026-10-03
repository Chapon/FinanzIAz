"""
Look-ahead de los fills FUERA de sesión — **Tarea 292 (ENFORCE-MARKET-HOURS)**.

Por qué existe
--------------
Con ``paper_enforce_market_hours = False`` (decisión de Chapa: deliberado), el scan
llena también con el mercado cerrado: de noche, en fin de semana y en feriados. El
precio es el último cierre regular (``fast_info.last_price``), pero la **decisión** se
toma con información posterior a ese cierre: noticias cosechadas después y, en los scans
de 16:0x, una barra que todavía no asentó. Si eso le da ventaja a la cuenta, se nota en
el gap hasta la apertura siguiente: compró antes de una suba, o vendió antes de una baja,
a un precio que ya no existía.

Medida (pre-registrada en la tarea 292, commit ``a9d00f2``, antes de medir)
---------------------------------------------------------------------------
``s × (Open_siguiente / fill_sin_slippage − 1)``, con ``s = +1`` en BUY y ``−1`` en
SELL, **crudo contra crudo** (``auto_adjust=False``). Positivo = la decisión se benefició
de lo que pasó después del cierre.

* **Población:** los fills fuera de sesión **por calendario de la bolsa** (fin de semana,
  feriado, o fuera de 13:30–20:00 UTC en día hábil), de las dos cuentas, desde el
  2026-05-01 (``d5fa07d``: antes el flag no existía).
* **Primaria:** las órdenes **por señal** (``analyze BUY`` / ``analyze SELL``). Las de
  barrera ATR van aparte: son mecánicas y no usan noticias.
* **IC95:** bootstrap de **días** (los fills de un mismo scan no son independientes).
* **Kill-criteria:** media primaria > **+0,25%** con el IC95 sin cruzar el 0 → tarea de
  corregir el fill fuera de sesión. Si no, se documenta y se declara.

Lee ``finanzias.db`` en sólo lectura y pide a Yahoo las barras crudas (con red). El
calendario sale de las barras de SPY. No toca el motor.

Uso::

    python scripts/measure_lookahead_fuera_sesion_t292.py
    python scripts/measure_lookahead_fuera_sesion_t292.py --json
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from database.readonly import readonly_uri  # tarea 191

DESDE = datetime(2026, 5, 1)  # d5fa07d: antes de esto el flag no existía
# Toda la muestra cae en horario de verano de EE.UU. (2026-03-08 → 2026-11-01): la sesión
# regular es 13:30–20:00 UTC. Se verifica abajo en vez de suponerlo.
_DST = (datetime(2026, 3, 8), datetime(2026, 11, 1))
_APERTURA_UTC = time(13, 30)
_CIERRE_UTC = time(20, 0)
UMBRAL = 0.0025


def _fills(db: Path) -> list[dict]:
    con = sqlite3.connect(readonly_uri(db), uri=True)
    try:
        filas = list(
            con.execute(
                """SELECT id, account_id, ticker, side, reason, fill_price, fill_shares,
                          slippage_cost, COALESCE(filled_at, created_at)
                   FROM paper_orders
                   WHERE status = 'filled' AND fill_price IS NOT NULL"""
            )
        )
    finally:
        con.close()
    out = []
    for oid, acct, t, side, reason, px, sh, slip, ts in filas:
        cuando = datetime.fromisoformat(str(ts))
        if cuando < DESDE:
            continue
        if not (_DST[0] <= cuando < _DST[1]):
            raise SystemExit(f"orden {oid} fuera del horario de verano ({cuando}): revisar la sesión UTC")
        sh = float(sh or 0.0)
        reason = str(reason or "")
        out.append(
            {
                "id": oid,
                "cuenta": acct,
                "ticker": t,
                "side": side,
                "por_senal": reason.startswith("analyze "),
                "reason": reason[:40],
                "cuando": cuando,
                "fill": float(px) - (float(slip or 0.0) / sh if sh else 0.0),
            }
        )
    return out


def en_sesion(cuando: datetime, ruedas: set[date]) -> bool:
    """Por calendario de la bolsa: día con rueda y dentro del horario regular."""
    return cuando.date() in ruedas and _APERTURA_UTC <= cuando.time() < _CIERRE_UTC


def sesion_siguiente(cuando: datetime, ruedas_ordenadas: list[date]) -> date | None:
    """La primera rueda que abre DESPUÉS de ``cuando`` (un fill de madrugada abre ese mismo día)."""
    for d in ruedas_ordenadas:
        if d > cuando.date() or (d == cuando.date() and cuando.time() < _APERTURA_UTC):
            return d
    return None


def _barras_crudas(tickers: list[str], desde: date, hasta: date) -> dict:
    import yfinance as yf

    raw = yf.download(
        tickers,
        start=str(desde),
        end=str(hasta + timedelta(days=1)),
        auto_adjust=False,
        group_by="ticker",
        progress=False,
        threads=True,
    )
    out = {}
    for t in tickers:
        try:
            serie = raw[t]["Open"].dropna()
        except KeyError:
            continue
        out[t] = {d.date(): float(v) for d, v in serie.items()}
    return out


def _boot_media_por_dia(filas: list[dict], reps: int = 5000, seed: int = 292) -> tuple[float, float]:
    por_dia: dict = {}
    for f in filas:
        por_dia.setdefault(f["cuando"].date(), []).append(f["gap"])
    grupos = list(por_dia.values())
    if not grupos:
        return (math.nan, math.nan)
    rng = random.Random(seed)
    medias = []
    for _ in range(reps):
        vals = [v for g in (rng.choice(grupos) for _ in grupos) for v in g]
        medias.append(sum(vals) / len(vals))
    medias.sort()
    return (medias[int(0.025 * reps)], medias[int(0.975 * reps)])


def _bloque(sub: list[dict]) -> dict:
    gaps = sorted(f["gap"] for f in sub)
    n = len(gaps)
    return {
        "n": n,
        "dias": len({f["cuando"].date() for f in sub}),
        "media": sum(gaps) / n if n else math.nan,
        "mediana": gaps[n // 2] if n else math.nan,
        "positivos": sum(g > 0 for g in gaps),
        "ic95_por_dia": _boot_media_por_dia(sub),
        "usd": sum(f["gap_usd"] for f in sub),
    }


def measure(db: Path | None = None) -> dict:
    db = db or (Path(__file__).resolve().parent.parent / "finanzias.db")
    fills = _fills(db)
    hoy = date.today()
    tickers = sorted({f["ticker"] for f in fills} | {"SPY"})
    aperturas = _barras_crudas(tickers, DESDE.date(), hoy)
    ruedas_ordenadas = sorted(aperturas.get("SPY", {}))
    if not ruedas_ordenadas:
        raise SystemExit("sin barras de SPY: no hay calendario")
    ruedas = set(ruedas_ordenadas)

    fuera, sin_apertura = [], []
    for f in fills:
        if en_sesion(f["cuando"], ruedas):
            continue
        d = sesion_siguiente(f["cuando"], ruedas_ordenadas)
        o = aperturas.get(f["ticker"], {}).get(d) if d else None
        if o is None:
            sin_apertura.append((f["ticker"], str(f["cuando"])))
            continue
        s = 1.0 if f["side"] == "BUY" else -1.0
        f["sesion_siguiente"] = d
        f["gap"] = s * (o / f["fill"] - 1.0)
        # En dólares por acción no hay fill_shares acá; se reporta la suma de gaps × fill como proxy.
        f["gap_usd"] = s * (o - f["fill"])
        fuera.append(f)

    raros = [f for f in fuera if abs(f["gap"]) > 0.20]
    limpios = [f for f in fuera if abs(f["gap"]) <= 0.20]
    primaria = [f for f in limpios if f["por_senal"]]
    p = _bloque(primaria)
    lo, _hi = p["ic95_por_dia"]
    return {
        "fills_desde": str(DESDE.date()),
        "fills_total": len(fills),
        "fuera_de_sesion": len(fuera) + len(sin_apertura),
        "sin_apertura_todavia": sin_apertura,
        "excluidos_por_escala": [(f["ticker"], str(f["cuando"]), round(f["gap"], 4)) for f in raros],
        "primaria_por_senal": p,
        "por_senal_BUY": _bloque([f for f in primaria if f["side"] == "BUY"]),
        "por_senal_SELL": _bloque([f for f in primaria if f["side"] == "SELL"]),
        "barreras_y_otras": _bloque([f for f in limpios if not f["por_senal"]]),
        "cuenta_2_por_senal": _bloque([f for f in primaria if f["cuenta"] == 2]),
        "kill_criteria_cumplido": bool(p["media"] > UMBRAL and lo > 0),
        "detalle": [
            {
                "id": f["id"],
                "cuenta": f["cuenta"],
                "ticker": f["ticker"],
                "side": f["side"],
                "reason": f["reason"],
                "cuando_utc": str(f["cuando"]),
                "sesion_siguiente": str(f["sesion_siguiente"]),
                "gap": f["gap"],
            }
            for f in fuera
        ],
    }


def _linea(nombre: str, b: dict) -> str:
    lo, hi = b["ic95_por_dia"]
    return (
        f"  {nombre}: n={b['n']} ({b['dias']} días) · media {100 * b['media']:+.3f}% "
        f"(IC95 por día {100 * lo:+.3f}% a {100 * hi:+.3f}%) · mediana {100 * b['mediana']:+.3f}% · "
        f"{b['positivos']}/{b['n']} a favor"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Tarea 292 — look-ahead de los fills fuera de sesión")
    ap.add_argument("--json", action="store_true", help="el detalle completo")
    args = ap.parse_args(argv)
    r = measure()
    if args.json:
        print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
        return 0
    print(f"fills desde {r['fills_desde']}: {r['fills_total']} · fuera de sesión {r['fuera_de_sesion']}")
    for nombre in (
        "primaria_por_senal",
        "por_senal_BUY",
        "por_senal_SELL",
        "cuenta_2_por_senal",
        "barreras_y_otras",
    ):
        print(_linea(nombre, r[nombre]))
    if r["excluidos_por_escala"]:
        print(f"  excluidos por escala (>20%): {r['excluidos_por_escala']}")
    if r["sin_apertura_todavia"]:
        print(f"  sin apertura siguiente todavía: {r['sin_apertura_todavia']}")
    print(
        f"  kill-criteria (media primaria > +{100 * UMBRAL:.2f}% con IC95 > 0): {r['kill_criteria_cumplido']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
