"""
Medición del desvío de ENTRADA harness↔vivo — **Tarea 293 (ENTRADA-INTRADIA-VS-CLOSE)**.

Por qué existe
--------------
El harness decide y entra al **close** de la barra con señal BUY
(``scripts/run_scaleout_replay_t7.py``, ``analysis/scaleout_replay.py``). El scan
vivo corre **en sesión**: decide con la barra del día todavía abierta y llena al
precio de ese momento. ``deviations_keyed()`` no lo declaraba
(``docs/auditoria_tanda_2026-10-03.md`` [C-2]). Este script mide las dos mitades
sobre los BUY reales de la cuenta viva:

1. **Señal.** ¿El BUY que el motor vio con la barra parcial sigue siendo BUY con
   la barra **completa** del mismo día? Se re-corre el mismo ``analyze()`` sobre
   el frame ``2y`` del cache (el período que usa el motor), cortado en el close
   del día y con la ventana viva (``LIVE_HISTORY_BARS``).
2. **Precio.** ``fill / close − 1``, con el fill **sin slippage**
   (``fill_price − slippage_cost / fill_shares``) y el close **crudo**
   (``auto_adjust=False``). Comparar un fill crudo contra un frame ajustado por
   dividendos sesga el número: es el instrumento que el ``verificador`` refutó en
   [C-1]. Por eso el close sale de Yahoo, **con red**.

Validación del instrumento (antes de creerle)
---------------------------------------------
Los BUY llenados **fuera** de sesión son el control: ahí el motor vio barras
completas, así que el mismo ``analyze()`` sobre el mismo frame tiene que
reproducir el BUY. Si el control no reproduce, la diferencia en sesión no se
puede atribuir a la barra parcial.

Kill-criteria (pre-registrado en la tarea 293, commit ``edb8c9a``, antes de medir)
-----------------------------------------------------------------------------------
Si la fracción de BUY en sesión cuya señal **no** sobrevive al close supera el
**10%**, o el |desvío medio de precio| supera el **0,5%**, entra una tarea de
re-evaluar los veredictos vigentes que dependen de la entrada.

Lee ``finanzias.db`` en sólo lectura y el cache Parquet; pide a Yahoo los closes
crudos. No toca el motor.

Uso::

    python scripts/measure_entrada_intradia_t293.py
    python scripts/measure_entrada_intradia_t293.py --json
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import random
import sqlite3
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from database.readonly import readonly_uri  # tarea 191

CUENTA = 2
# Toda la muestra cae en horario de verano de EE.UU. (2026-03-08 → 2026-11-01): la
# sesión regular es 13:30–20:00 UTC. Se verifica abajo en vez de suponerlo.
_DST = (datetime(2026, 3, 8), datetime(2026, 11, 1))
_APERTURA_UTC = time(13, 30)
_CIERRE_UTC = time(20, 0)


def _buys(db: Path) -> list[dict]:
    con = sqlite3.connect(readonly_uri(db), uri=True)
    try:
        filas = list(
            con.execute(
                """SELECT id, ticker, fill_price, fill_shares, slippage_cost, filled_at
                   FROM paper_orders
                   WHERE account_id = ? AND side = 'BUY' AND status = 'filled'
                     AND reason = 'analyze BUY' AND fill_price IS NOT NULL""",
                (CUENTA,),
            )
        )
    finally:
        con.close()
    out = []
    for oid, t, px, sh, slip, ts in filas:
        cuando = datetime.fromisoformat(str(ts))
        if not (_DST[0] <= cuando < _DST[1]):
            raise SystemExit(f"orden {oid} fuera del horario de verano ({cuando}): revisar la sesión UTC")
        sh = float(sh or 0.0)
        crudo = float(px) - (float(slip or 0.0) / sh if sh else 0.0)
        en_sesion = cuando.weekday() < 5 and _APERTURA_UTC <= cuando.time() < _CIERRE_UTC
        out.append({"id": oid, "ticker": t, "cuando": cuando, "fill": crudo, "en_sesion": en_sesion})
    return out


def _ultima_barra_completa(fechas: list, cuando: datetime):
    """La última barra del frame que estaba **cerrada** en ``cuando``."""
    dia = cuando.date()
    if cuando.weekday() < 5 and cuando.time() < _CIERRE_UTC:
        dia = dia - timedelta(days=1)
    previas = [f for f in fechas if f <= dia]
    return previas[-1] if previas else None


def _senal(analyze, ticker: str, df, hasta, ventana: int) -> str | None:
    corte = df[df.index.date <= hasta].tail(ventana)
    try:
        res = analyze(ticker, corte)
    except Exception as exc:  # una barra rota no tumba la medición
        logging.getLogger(__name__).warning("analyze %s %s falló: %s", ticker, hasta, exc)
        return None
    return None if res is None else res.overall_signal


def _closes_crudos(tickers: list[str], desde, hasta) -> dict:
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
            serie = raw[t]["Close"].dropna()
        except KeyError:
            continue
        out[t] = {d.date(): float(v) for d, v in serie.items()}
    return out


def _wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    z = 1.96
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (c - h, c + h)


def _boot_media_por_dia(
    filas: list[dict], clave: str, reps: int = 5000, seed: int = 293
) -> tuple[float, float]:
    """IC95% de la media, remuestreando **días** (los BUY de un mismo scan no son independientes)."""
    por_dia: dict = {}
    for f in filas:
        por_dia.setdefault(f["cuando"].date(), []).append(f[clave])
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


def measure(db: Path | None = None) -> dict:
    from analysis.harness_config import LIVE_HISTORY_BARS, apply_model_toggles
    from analysis.technical import analyze
    from data import parquet_cache

    apply_model_toggles()
    for nombre in ("analysis.ml_signals", "analysis.garch_signals"):
        logging.getLogger(nombre).setLevel(logging.ERROR)

    db = db or (Path(__file__).resolve().parent.parent / "finanzias.db")
    buys = _buys(db)
    frames = {}
    for t in sorted({b["ticker"] for b in buys}):
        df = parquet_cache.read(t, "2y", "1d", None)
        if df is not None and not df.empty:
            frames[t] = df.sort_index()

    for b in buys:
        df = frames.get(b["ticker"])
        b["sin_frame"] = df is None
        if df is None:
            continue
        fechas = sorted(set(df.index.date))
        # Un día hábil sin barra es un feriado (2026-09-07, Labor Day: JNJ se llenó a las
        # 14:05 UTC con el mercado cerrado). Ese fill es de la 292, no de la barra parcial.
        if b["en_sesion"] and b["cuando"].date() not in fechas:
            b["en_sesion"] = False
            b["feriado"] = True
        if b["en_sesion"]:
            dia = b["cuando"].date()
            b["dia"] = dia if dia in fechas else None
            b["senal_close"] = _senal(analyze, b["ticker"], df, dia, LIVE_HISTORY_BARS) if b["dia"] else None
            previa = _ultima_barra_completa(fechas, b["cuando"])
            b["senal_previa"] = (
                _senal(analyze, b["ticker"], df, previa, LIVE_HISTORY_BARS) if previa else None
            )
        else:
            completa = _ultima_barra_completa(fechas, b["cuando"])
            b["dia"] = completa
            b["senal_close"] = (
                _senal(analyze, b["ticker"], df, completa, LIVE_HISTORY_BARS) if completa else None
            )

    en = [b for b in buys if b["en_sesion"] and not b["sin_frame"] and b["dia"]]
    fuera = [b for b in buys if not b["en_sesion"] and not b["sin_frame"] and b["dia"]]

    if en:
        closes = _closes_crudos(
            sorted({b["ticker"] for b in en}), min(b["dia"] for b in en), max(b["dia"] for b in en)
        )
        for b in en:
            c = closes.get(b["ticker"], {}).get(b["dia"])
            b["close_crudo"] = c
            b["desvio"] = (b["fill"] / c - 1.0) if c else None

    def _sobrevive(sub: list[dict]) -> dict:
        val = [b for b in sub if b["senal_close"] is not None]
        k = sum(b["senal_close"] != "BUY" for b in val)
        return {
            "n": len(val),
            "no_buy": k,
            "frac": k / len(val) if val else math.nan,
            "ic95": _wilson(k, len(val)),
        }

    con_precio = [b for b in en if b.get("desvio") is not None]
    # Un desvío de más del 20% no es intradía: es otra escala (un split entre el fill y hoy).
    raros = [b for b in con_precio if abs(b["desvio"]) > 0.20]
    limpios = [b for b in con_precio if abs(b["desvio"]) <= 0.20]
    desvios = sorted(b["desvio"] for b in limpios)
    precio = {
        "n": len(limpios),
        "media": sum(desvios) / len(desvios) if desvios else math.nan,
        "mediana": desvios[len(desvios) // 2] if desvios else math.nan,
        "media_abs": sum(abs(d) for d in desvios) / len(desvios) if desvios else math.nan,
        "ic95_media_por_dia": _boot_media_por_dia(limpios, "desvio"),
        "excluidos_por_escala": [(b["ticker"], str(b["dia"]), round(b["desvio"], 4)) for b in raros],
        "sin_close": [(b["ticker"], str(b["dia"])) for b in en if b.get("desvio") is None],
    }
    senal_en = _sobrevive(en)
    ultimas = sorted(str(df.index[-1].date()) for df in frames.values())
    return {
        # Frescura de los frames `2y` que mantiene la app (no es el cohorte `10y`): cada
        # BUY necesita la barra de su día, y si faltara cae en `sin frame`/`dia=None`.
        "frames_2y_ultima_barra": (ultimas[0], ultimas[-1]) if ultimas else None,
        "total_buys": len(buys),
        "en_sesion": len(en),
        "fuera_de_sesion": len(fuera),
        "sin_frame": [b["ticker"] for b in buys if b["sin_frame"]],
        "fills_en_feriado": [(b["ticker"], str(b["cuando"])) for b in buys if b.get("feriado")],
        "control_fuera_de_sesion": _sobrevive(fuera),
        "senal_en_sesion_al_close": senal_en,
        "senal_en_sesion_dia_previo": _sobrevive([dict(b, senal_close=b.get("senal_previa")) for b in en]),
        "precio_en_sesion": precio,
        "kill_criteria": {
            "frac_no_sobrevive_gt_10pct": senal_en["frac"] > 0.10,
            "abs_media_precio_gt_0_5pct": abs(precio["media"]) > 0.005,
        },
        "detalle": [
            {
                "id": b["id"],
                "ticker": b["ticker"],
                "cuando_utc": str(b["cuando"]),
                "en_sesion": b["en_sesion"],
                "dia": str(b.get("dia")),
                "senal_close": b.get("senal_close"),
                "senal_previa": b.get("senal_previa"),
                "desvio": b.get("desvio"),
                "feriado": b.get("feriado", False),
            }
            for b in buys
        ],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Tarea 293 — entrada intradía vs close")
    p.add_argument("--json", action="store_true", help="el detalle completo")
    args = p.parse_args(argv)
    r = measure()
    if args.json:
        print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
        return 0
    print(f"frames 2y, última barra entre {r['frames_2y_ultima_barra']}")
    print(
        f"BUY de la cuenta {CUENTA}: {r['total_buys']} · en sesión {r['en_sesion']} · fuera {r['fuera_de_sesion']}"
    )
    if r["fills_en_feriado"]:
        print(f"  fills en feriado (mercado cerrado, van con la 292): {r['fills_en_feriado']}")
    for nombre in ("control_fuera_de_sesion", "senal_en_sesion_al_close", "senal_en_sesion_dia_previo"):
        s = r[nombre]
        lo, hi = s["ic95"]
        print(
            f"  {nombre}: {s['no_buy']}/{s['n']} NO son BUY ({100 * s['frac']:.1f}%, IC95 {100 * lo:.1f}–{100 * hi:.1f}%)"
        )
    pr = r["precio_en_sesion"]
    lo, hi = pr["ic95_media_por_dia"]
    print(
        f"  precio en sesión (fill sin slippage / close crudo − 1), n={pr['n']}: media {100 * pr['media']:+.3f}% "
        f"(IC95 por día {100 * lo:+.3f}% a {100 * hi:+.3f}%) · mediana {100 * pr['mediana']:+.3f}% · "
        f"|·| media {100 * pr['media_abs']:.3f}%"
    )
    if pr["excluidos_por_escala"]:
        print(f"  excluidos por escala (>20%): {pr['excluidos_por_escala']}")
    if pr["sin_close"]:
        print(f"  sin close crudo: {pr['sin_close']}")
    print(f"  kill-criteria: {r['kill_criteria']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
