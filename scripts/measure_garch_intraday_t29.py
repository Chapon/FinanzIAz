"""¿Cuánto se mueve el fit de GARCH DENTRO de la rueda? — Tarea 29(c).

Por qué se mide antes de tocar nada
-----------------------------------
La huella del cache de GARCH incluye ``close[-5:]``, así que el último close —que
se mueve toda la rueda— la cambia en cada scan: **miss garantizado**, ~8,3 ms de
fit × 128 tickers ≈ **1,1 s por scan**, ~26 refits por hora y por ticker que
devuelven casi lo mismo. La solución obvia es la de la T24: keyear a granularidad
**diaria** y fitear una vez.

Pero la T24 podía hacerlo con un argumento que **acá no vale**. El XGBoost descarta
las últimas ``PREDICTION_HORIZON`` filas por no tener label, así que la barra
parcial es *demostrablemente* irrelevante para lo que entrena. El fit de GARCH
**sí** usa el último retorno, y su salida alimenta una señal (`train_garch_signal`)
que entra en la mezcla de BUY/SELL. Congelarla al primer scan del día sería servir
una decisión vieja durante toda la rueda.

Criterio de aceptación, declarado ANTES de correr
-------------------------------------------------
Se keyea a granularidad diaria **sólo si la SEÑAL EMITIDA (dirección + fuerza) es
idéntica entre el primer y el último scan del día en el 100% de los tickers.** Es
la única pregunta que importa —el Δ en puntos de vol es descriptivo— y no necesita
un umbral inventado: si aunque sea un ticker cambia de señal, la variación
intradía **es** relevante para la decisión y la clave se queda como está, con su
costo documentado y aceptado.

Cómo se simula la rueda, sin datos intradía
-------------------------------------------
La barra diaria **ya trae** el recorrido: al primer scan del día el close parcial
vale ≈ el **Open**, y al último vale el **Close**; el **High** y el **Low** son los
extremos que efectivamente tocó. Así que se refitea el mismo frame con el close de
la última barra reemplazado por cada uno de los cuatro, y eso **acota** lo que
cualquier scan del día pudo haber visto. No es una aproximación optimista: es el
envolvente real.

El resultado (2026-09-01): **3 de 133 tickers cambian** ⇒ el criterio falla y la
clave **NO se toca**. Y el detalle es más incómodo que el veredicto: los tres no
son flips de dirección sino el **fit que converge o no** según el close parcial —
un 2,3% del universo está al filo. Eso refuerza el NO: con clave diaria, *si* CRM
emite señal GARCH toda la rueda lo decidiría el precio arbitrario de las 9:30, y
quedaría estable e invisible en vez de oscilar. Detalle en
``docs/garch_intraday_t29_2026-09-01.md``; la fragilidad del fit queda como tarea
**67 (GARCH-FRAGIL)**.

Offline: lee el cache parquet, no pega a la red, no toca la DB viva.

    python scripts/measure_garch_intraday_t29.py
    python scripts/measure_garch_intraday_t29.py --limit 40 --json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from analysis import garch_signals as G
from analysis.harness_config import announce_artifacts, artifact_window
from data import parquet_cache

PERIOD = "2y"  # el frame que pide el engine (`paper_history_period`)


def _frames(limit: int | None) -> list[tuple[str, pd.DataFrame]]:
    d = parquet_cache.get_parquet_dir()
    out: list[tuple[str, pd.DataFrame]] = []
    for path in sorted(d.glob(f"*__{PERIOD}__1d.parquet")):
        ticker = path.name.split("__")[0]
        df = parquet_cache.read(ticker, PERIOD, "1d", ttl_hours=None)
        if df is None or len(df) < 260 or "Close" not in df:
            continue
        out.append((ticker, df))
        if limit and len(out) >= limit:
            break
    return out


def _variant(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """El mismo frame con el close de la ÚLTIMA barra puesto en ``col``."""
    d = df.copy()
    d.iloc[-1, d.columns.get_loc("Close")] = float(d[col].iloc[-1])
    return d


def _signal_of(df: pd.DataFrame) -> tuple[str, str] | None:
    """``(dirección, fuerza)`` de la señal GARCH, o None si no emite."""
    G._garch_cache.clear()  # cada variante tiene que fitear de verdad
    sig = G.train_garch_signal(df)
    if sig is None:
        return None
    return (str(sig.signal), str(sig.strength))


def _forecast_of(df: pd.DataFrame):
    G._garch_cache.clear()
    return G.fit_garch_forecast(df)


def measure(limit: int | None = None, *, strict_artifacts: bool = True) -> dict:
    # Frescura del cohorte ANTES de pagar los fits (tarea 101). El `bars_by` sale de
    # los frames que `_frames` ya cargó —incluido su filtro de <260 barras—, así que
    # el guard mira **exactamente** la muestra que se va a medir y no re-lee el disco.
    frames = _frames(limit)
    bars_by = {
        t: [(str(ts)[:10], float(c)) for ts, c in zip(df.index, df["Close"], strict=True)] for t, df in frames
    }
    announce_artifacts(bars_by, strict=strict_artifacts)
    ventana = artifact_window(bars_by)

    filas: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for ticker, df in frames:
        try:
            primero = _variant(df, "Open")  # primer scan del día
            ultimo = df  # último scan: el close real
            s_ini, s_fin = _signal_of(primero), _signal_of(ultimo)
            f_ini, f_fin = _forecast_of(primero), _forecast_of(ultimo)
            extremos = []
            for col in ("High", "Low"):
                if col in df.columns:
                    f = _forecast_of(_variant(df, col))
                    if f is not None:
                        extremos.append(f.forecast_vol)
            vols = [f.forecast_vol for f in (f_ini, f_fin) if f is not None] + extremos
            filas.append(
                {
                    "ticker": ticker,
                    "signal_primero": s_ini,
                    "signal_ultimo": s_fin,
                    "cambia_signal": s_ini != s_fin,
                    "vol_primero": None if f_ini is None else f_ini.forecast_vol,
                    "vol_ultimo": None if f_fin is None else f_fin.forecast_vol,
                    "delta_vol": (
                        None
                        if (f_ini is None or f_fin is None)
                        else abs(f_fin.forecast_vol - f_ini.forecast_vol)
                    ),
                    "spread_dia": (max(vols) - min(vols)) if len(vols) >= 2 else None,
                    "regimen_primero": None if f_ini is None else f_ini.vol_regime,
                    "regimen_ultimo": None if f_fin is None else f_fin.vol_regime,
                }
            )
        except Exception as exc:
            filas.append({"ticker": ticker, "error": str(exc)})

    ok = [f for f in filas if "error" not in f]
    cambian = [f for f in ok if f["cambia_signal"]]
    regimen = [f for f in ok if f["regimen_primero"] != f["regimen_ultimo"]]
    deltas: list[float] = sorted(float(f["delta_vol"]) for f in ok if f["delta_vol"] is not None)
    spreads: list[float] = sorted(float(f["spread_dia"]) for f in ok if f["spread_dia"] is not None)

    def q(xs: list[float], p: float) -> float:
        return xs[min(int(p * len(xs)), len(xs) - 1)] if xs else 0.0

    return {
        "ventana_artefactos": str(ventana) if ventana else None,
        "n_tickers": len(ok),
        "n_errores": len(filas) - len(ok),
        "segundos": time.perf_counter() - t0,
        "cambian_signal": [f["ticker"] for f in cambian],
        "cambian_regimen": [f["ticker"] for f in regimen],
        "delta_vol": {"p50": q(deltas, 0.5), "p90": q(deltas, 0.9), "max": deltas[-1] if deltas else 0.0},
        "spread_dia": {
            "p50": q(spreads, 0.5),
            "p90": q(spreads, 0.9),
            "max": spreads[-1] if spreads else 0.0,
        },
        "peores": sorted((f for f in ok if f["delta_vol"] is not None), key=lambda f: -float(f["delta_vol"]))[
            :10
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GARCH intradía (tarea 29c)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--allow-stale-artifacts",
        action="store_true",
        help="Sigue aunque el cohorte esté desalineado (hay que declararlo en el pre-registro).",
    )
    args = ap.parse_args(argv)

    if not G._ARCH_OK:
        print("arch no está instalado: no hay nada que medir", file=sys.stderr)
        return 2

    m = measure(args.limit, strict_artifacts=not args.allow_stale_artifacts)
    if args.json:
        print(json.dumps(m, indent=2, default=str))
        return 0

    print("=" * 78)
    print("GARCH intradía (tarea 29c) — ¿cambia la SEÑAL entre el primer y el último scan?")
    print("=" * 78)
    print(f"\n{m['n_tickers']} tickers · {m['n_errores']} errores · {m['segundos']:.1f}s")

    n_cambian = len(m["cambian_signal"])
    print("\n  CRITERIO: la señal emitida tiene que ser IDÉNTICA en el 100% de los tickers.")
    print(f"    señales que cambian: {n_cambian}/{m['n_tickers']}  {m['cambian_signal'][:10]}")
    print(f"    regímenes que cambian: {len(m['cambian_regimen'])}  {m['cambian_regimen'][:10]}")
    print(f"\n  ⇒ {'SE PUEDE keyear a día' if n_cambian == 0 else 'NO se toca la clave'}")

    print("\n  |Δ forecast_vol| primer → último scan (puntos de vol anual):")
    for k in ("p50", "p90", "max"):
        print(f"    {k:>4} {m['delta_vol'][k]:>8.3f}")
    print("\n  spread del día completo (O/H/L/C):")
    for k in ("p50", "p90", "max"):
        print(f"    {k:>4} {m['spread_dia'][k]:>8.3f}")

    print("\n  los que más se mueven:")
    print(f"    {'ticker':<8} {'Δvol':>8} {'spread':>8}  {'primero':<22} {'último':<22}")
    for f in m["peores"]:
        print(
            f"    {f['ticker']:<8} {f['delta_vol']:>8.3f} {(f['spread_dia'] or 0):>8.3f}  "
            f"{f['signal_primero']!s:<22} {f['signal_ultimo']!s:<22}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
