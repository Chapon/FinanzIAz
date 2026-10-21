"""
¿Lo que vende la señal le pierde a SPY en el harness como en el vivo? — **tarea 379**.

En la cuenta 2, del 20/06 al 20/10, lo vendido con ``analyze SELL`` le perdió a SPY 3,6% a 20
ruedas (``docs/rendimiento_app_vs_cartera_2026-10-20.md`` §3), y el harness de la T7 y la 219 dice
que obedecer a la señal resta. Esto mide **la misma estadística de los dos lados**: el exceso sobre
SPY a 5/10/20 ruedas de lo vendido por señal y de lo comprado, desde el cierre del día de la
operación.

- **Harness:** el brazo ``age3`` de la 219 (la política viva), con su cohorte y sus artefactos tal
  como están. Terminan el 2026-09-09, así que el recorte va del 2026-06-20 a esa fecha.
- **Vivo:** los fills de la cuenta 2, con la DB abierta en sólo lectura (``readonly_uri``).
- **Retornos hacia adelante:** de los frames ``2y`` del cache para los eventos que caen adentro, y
  si no, de los ``10y``. Ticker y SPY siempre del mismo frame, sin empalmar.
- **IC:** bootstrap por **bloques de ``h`` ruedas** de la fecha del evento. Las ventas del mismo
  día, y las de días cercanos con ventanas superpuestas, no son independientes.

También cruza cada venta del vivo contra la señal PIT de su ticker ese día y el anterior: si el
harness ve otra señal, la diferencia es la señal, no la cartera.

Medición: no cablea nada, no escribe la DB y no pega a la red.

Uso:
    python scripts/measure_venta_senal_vivo_vs_harness_t379.py --allow-stale-artifacts
    python scripts/measure_venta_senal_vivo_vs_harness_t379.py --allow-stale-artifacts --json

Sin ``--allow-stale-artifacts``, con el cohorte atrasado contra los frames ``2y`` aborta (exit 3).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Iterable
from datetime import datetime, time, timezone
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

HORIZONTES = (5, 10, 20)
DESDE = "2026-06-20"  # alta de la cuenta 2
CUENTA = 2
N_BOOT = 5000
SEED = 379
_APERTURA_NY = time(9, 30)

Cierres = dict[str, float]


def exceso(
    cierres_t: Cierres, cierres_spy: Cierres, calendario: list[str], base: str, h: int
) -> float | None:
    """Retorno del ticker menos el de SPY, del cierre de ``base`` al de ``h`` ruedas después. Pura.

    ``calendario`` son las ruedas de SPY, ordenadas. ``None`` si falta la base, la rueda ``+h``
    o el cierre del ticker en alguna de las dos.
    """
    try:
        i = calendario.index(base)
    except ValueError:
        return None
    if i + h >= len(calendario):
        return None
    fin = calendario[i + h]
    t0, t1 = cierres_t.get(base), cierres_t.get(fin)
    s0, s1 = cierres_spy.get(base), cierres_spy.get(fin)
    if not (t0 and t1 and s0 and s1):
        return None
    return (t1 / t0 - 1.0) - (s1 / s0 - 1.0)


def rueda_de_sesion(momento_utc: str, calendario: list[str], zona) -> str | None:
    """La rueda cuyo cierre es la base de una operación del vivo. Pura.

    La fecha de NY del fill; si fue antes de la apertura o en un día sin rueda, la última rueda
    anterior (el último cierre que había).
    """
    dt = datetime.fromisoformat(momento_utc).replace(tzinfo=timezone.utc).astimezone(zona)
    dia = dt.date().isoformat()
    if dt.time() < _APERTURA_NY:
        previas = [d for d in calendario if d < dia]
    else:
        previas = [d for d in calendario if d <= dia]
    return previas[-1] if previas else None


def ic_por_bloques(
    eventos: Iterable[tuple[str, float]],
    calendario: list[str],
    bloque: int,
    *,
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> dict:
    """Media de los eventos con IC95% por bootstrap de bloques de ``bloque`` ruedas. Pura.

    Cada evento cae en el bloque ``índice_de_su_fecha // bloque`` y se re-muestrean bloques
    enteros, así que los eventos del mismo día —o de días con ventanas superpuestas— entran o
    salen juntos.
    """
    pos = {d: i for i, d in enumerate(calendario)}
    grupos: dict[int, list[float]] = {}
    for fecha, x in eventos:
        if fecha in pos:
            grupos.setdefault(pos[fecha] // bloque, []).append(x)
    valores = [x for g in grupos.values() for x in g]
    if not valores:
        return {"n": 0, "bloques": 0, "media": None, "ic95": None}
    claves = list(grupos)
    sumas = np.array([sum(grupos[k]) for k in claves])
    cuentas = np.array([len(grupos[k]) for k in claves])
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(claves), size=(n_boot, len(claves)))
    medias = sumas[idx].sum(axis=1) / cuentas[idx].sum(axis=1)
    return {
        "n": len(valores),
        "bloques": len(claves),
        "media": float(np.mean(valores)),
        "ic95": [float(np.percentile(medias, 2.5)), float(np.percentile(medias, 97.5))],
    }


def _cierres(ticker: str, period: str) -> Cierres:
    from data import parquet_cache

    df = parquet_cache.read(ticker, period, "1d", None)
    if df is None or df.empty:
        return {}
    return {ts.strftime("%Y-%m-%d"): float(c) for ts, c in df["Close"].items() if c == c and c > 0}


class Precios:
    """Los cierres de un ticker y de SPY, del frame ``2y`` si el evento cae adentro y si no del ``10y``."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], Cierres] = {}
        self.spy = {p: self._get("SPY", p) for p in ("2y", "10y")}
        self.cal = {p: sorted(self.spy[p]) for p in ("2y", "10y")}
        self.ruedas = sorted(set(self.cal["2y"]) | set(self.cal["10y"]))

    def _get(self, t: str, p: str) -> Cierres:
        if (t, p) not in self._cache:
            self._cache[(t, p)] = _cierres(t, p)
        return self._cache[(t, p)]

    def exceso(self, ticker: str, base: str, h: int) -> float | None:
        for p in ("2y", "10y"):
            cal = self.cal[p]
            if cal and cal[0] <= base:
                x = exceso(self._get(ticker, p), self.spy[p], cal, base, h)
                if x is not None:
                    return x
        return None


def _resumir(eventos: list[tuple[str, str]], precios: Precios, desde: str, hasta: str) -> dict:
    out = {}
    for h in HORIZONTES:
        evs = []
        for t, d in eventos:
            if desde <= d <= hasta:
                x = precios.exceso(t, d, h)
                if x is not None:
                    evs.append((d, x))
        out[h] = ic_por_bloques(evs, precios.ruedas, h)
    return out


def _rueda_anterior(precios: Precios, fecha: str) -> str:
    return [d for d in precios.ruedas if d < fecha][-1]


def _vivo(db: Path, precios: Precios) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    from data.yahoo_finance import market_timezone
    from database.readonly import readonly_uri

    zona = market_timezone()
    cal = precios.cal["2y"]
    con = sqlite3.connect(readonly_uri(db), uri=True)
    try:
        filas = con.execute(
            "SELECT ticker, side, filled_at FROM paper_orders WHERE account_id=? AND status='filled' "
            "AND (reason LIKE 'analyze SELL%' OR reason = 'analyze BUY')",
            (CUENTA,),
        ).fetchall()
    finally:
        con.close()
    ventas, compras = [], []
    for t, side, cuando in filas:
        d = rueda_de_sesion(cuando, cal, zona)
        if d is not None:
            (ventas if side == "SELL" else compras).append((t, d))
    return ventas, compras


def giros_a_sell(bars_by: dict, sigs_by: dict) -> list[tuple[str, str]]:
    """Cada rueda en que la señal PIT de un ticker pasa a SELL, sin cartera de por medio. Pura.

    Es la prueba que no depende de qué tenía cada cartera: si la ventana entera se inclinó contra
    lo que la señal vende, se ve acá también.
    """
    out = []
    for t, sig in sigs_by.items():
        previa = None
        for bar in bars_by.get(t, []):
            v = sig.get(bar[0])
            if v == "SELL" and previa != "SELL":
                out.append((t, bar[0]))
            previa = v
    return out


def _harness(allow_stale: bool) -> tuple[list[tuple[str, str]], list[tuple[str, str]], dict, dict, str]:
    from analysis.harness_config import (
        LIVE_MAX_POSITIONS,
        LIVE_UNIVERSE_FILE,
        announce_artifacts,
        announce_signal_store,
        artifact_window,
    )
    from scripts.precompute_pit_signals import parse_universe_file
    from scripts.run_signal_exit_delay_t219 import BASELINE, _common_kwargs, correr_brazo
    from scripts.run_stop_value_t37 import CAP_DAYS
    from scripts.run_tp_cal_replay_t23 import buy_entries, load_bars_signals

    tickers = parse_universe_file(_ROOT / LIVE_UNIVERSE_FILE)
    bars_by, sigs_by, _missing = load_bars_signals(tickers, "10y", 250)
    # Con el cohorte atrasado (el 2026-10-21 terminaba el 2026-09-09) esto aborta salvo
    # `--allow-stale-artifacts`, y la medición de la 379 corrió así, declarado: el recorte termina
    # donde termina el harness, y los retornos hacia adelante no salen de sus artefactos.
    announce_artifacts(bars_by, strict=not allow_stale, file=sys.stderr)
    announce_signal_store(bars_by, "10y", 250, strict=not allow_stale, file=sys.stderr)
    print(f"Ventana del cohorte: {artifact_window(bars_by)}", file=sys.stderr)
    entries = buy_entries(bars_by, sigs_by, 250)
    args = argparse.Namespace(max_positions=LIVE_MAX_POSITIONS, capital=50_000.0, cap_days=CAP_DAYS)
    res = correr_brazo(BASELINE, entries, bars_by, sigs_by, _common_kwargs(args))
    ventas = [(t.ticker, t.exit_date) for t in res.trades if "signal" in (t.exit_reason or "")]
    compras = [(t.ticker, t.entry_date) for t in res.trades]
    fin = max(b[-1][0] for b in bars_by.values())
    return ventas, compras, bars_by, sigs_by, fin


def cruce_de_senal(ventas_vivo: list[tuple[str, str]], sigs_by: dict, cal: list[str], hasta: str) -> dict:
    """Qué decía la señal PIT del harness el día de cada venta del vivo, y el anterior."""
    cuenta = {"SELL_mismo_dia": 0, "SELL_dia_anterior": 0, "otra": 0, "sin_senal": 0}
    detalle = []
    for t, d in ventas_vivo:
        if d > hasta:
            continue
        sig = sigs_by.get(t)
        if sig is None:
            cuenta["sin_senal"] += 1
            continue
        i = cal.index(d) if d in cal else None
        ant = cal[i - 1] if i else None
        hoy, ayer = sig.get(d), sig.get(ant) if ant else None
        if hoy == "SELL":
            cuenta["SELL_mismo_dia"] += 1
        elif ayer == "SELL":
            cuenta["SELL_dia_anterior"] += 1
        else:
            cuenta["otra"] += 1
            detalle.append((t, d, hoy, ayer))
    return {"cuenta": cuenta, "otra_detalle": detalle}


def _fmt(r: dict) -> str:
    if not r["n"]:
        return "      —"
    lo, hi = r["ic95"]
    return (
        f"{r['media'] * 100:+6.2f}% [{lo * 100:+6.2f}, {hi * 100:+6.2f}] n={r['n']:<4} bloques={r['bloques']}"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="VENTA-POR-SENAL-VIVO-VS-HARNESS (tarea 379)")
    p.add_argument("--db", type=Path, default=_ROOT / "finanzias.db", help="se abre en sólo lectura")
    p.add_argument("--allow-stale-artifacts", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    from analysis.harness_config import SignalStoreGapError, StaleArtifactError

    precios = Precios()
    try:
        ventas_h, compras_h, bars_by, sigs_by, fin_h = _harness(args.allow_stale_artifacts)
    except (StaleArtifactError, SignalStoreGapError) as exc:
        print(f"*** ABORTA — {exc} ***", file=sys.stderr)
        return 3
    giros = giros_a_sell(bars_by, sigs_by)
    ventas_v, compras_v = _vivo(args.db, precios)

    hoy = precios.cal["2y"][-1]
    primera = min(d for _t, d in ventas_h) if ventas_h else DESDE
    filas = {
        "harness · cohorte entero · ventas": _resumir(ventas_h, precios, primera, fin_h),
        "harness · cohorte entero · compras": _resumir(compras_h, precios, primera, fin_h),
        f"harness · recorte {DESDE}→{fin_h} · ventas": _resumir(ventas_h, precios, DESDE, fin_h),
        f"harness · recorte {DESDE}→{fin_h} · compras": _resumir(compras_h, precios, DESDE, fin_h),
        "universo · giros a SELL · 10 años sin el recorte": _resumir(
            giros, precios, min(d for _t, d in giros), _rueda_anterior(precios, DESDE)
        ),
        f"universo · giros a SELL · recorte {DESDE}→{fin_h}": _resumir(giros, precios, DESDE, fin_h),
        f"vivo · {DESDE}→{fin_h} · ventas": _resumir(ventas_v, precios, DESDE, fin_h),
        f"vivo · {DESDE}→{fin_h} · compras": _resumir(compras_v, precios, DESDE, fin_h),
        f"vivo · {DESDE}→{hoy} (referencia) · ventas": _resumir(ventas_v, precios, DESDE, hoy),
        f"vivo · {DESDE}→{hoy} (referencia) · compras": _resumir(compras_v, precios, DESDE, hoy),
    }
    cruce = cruce_de_senal(ventas_v, sigs_by, precios.cal["2y"], fin_h)

    if args.json:
        print(json.dumps({"filas": filas, "cruce": cruce, "fin_harness": fin_h}, indent=2, default=str))
        return 0
    print(
        f"Exceso sobre SPY desde el cierre del día de la operación · IC95% por bloques de h ruedas · harness hasta {fin_h}\n"
    )
    for nombre, por_h in filas.items():
        print(nombre)
        for h, r in por_h.items():
            print(f"   +{h:>2} ruedas  {_fmt(r)}")
    print(f"\nCruce de las ventas del vivo hasta {fin_h} contra la señal PIT del harness: {cruce['cuenta']}")
    for fila in cruce["otra_detalle"]:
        print("   ", fila)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
