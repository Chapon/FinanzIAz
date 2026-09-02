"""¿Cuántos tickers viven al filo de la convergencia? — Tarea 67 (GARCH-FRAGIL).

Por qué existe, y por qué NO decide nada
-----------------------------------------
La 29(c) midió que en **3 de 133** tickers el fit de GARCH **converge o no según el
valor del close parcial** — o sea que de qué lado cae lo decide el precio del
momento. Pero ese 2,3% sale de **un** día simulado sobre **un** frame por ticker,
y el enunciado de la 67 es explícito con el orden: **(1)** declarar el no-fit,
**(2)** medir sobre una **ventana larga**, y **(3)** recién ahí decidir si vale un
fallback. Elegir el remedio antes de saber el tamaño del problema sería el error.

Esto es el paso **(2)**. **No propone ni aplica ningún arreglo.**

Qué mide, exactamente
---------------------
Para cada ticker recorre las últimas ``--ruedas`` sesiones y, en cada una, fitea
GARCH sobre el frame **hasta esa barra** (``df[:i]``), registrando si fiteó y —si
no— **por qué motivo**, usando la telemetría que la parte (1) acaba de cablear.

Con eso separa tres poblaciones que el ``None`` del borde confundía:

* **estables**: fitean en todas las sesiones (o en ninguna, por falta de datos);
* **al filo**: **alternan** fit ↔ no-fit de una sesión a la otra. Son los que
  hacen que la señal GARCH aparezca y desaparezca sin que nada lo declare;
* **rotos**: nunca fitean por un motivo que no es falta de datos.

El número que importa es **cuántos alternan y cuántas veces**, porque un ticker que
alterna una vez en 60 sesiones no es lo mismo que uno que alterna veinte.

Offline: lee el cache parquet. No pega a la red, no toca la DB.

    python scripts/measure_garch_fragil_t67.py --ruedas 60
    python scripts/measure_garch_fragil_t67.py --ruedas 60 --limit 20 --json
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis import garch_signals as G
from data import parquet_cache

PERIODO = "2y"
MIN_BARRAS = 260  # margen sobre GARCH_MIN_ROWS para que la falta de datos no domine


def _tickers(limit: int | None) -> list[str]:
    d = parquet_cache.get_parquet_dir()
    out = sorted({p.name.split("__")[0] for p in d.glob(f"*__{PERIODO}__1d.parquet")})
    return out[:limit] if limit else out


def _serie_de_fits(df, ruedas: int) -> list[tuple[bool, str | None]]:
    """``(fiteó, motivo)`` para cada una de las últimas ``ruedas`` sesiones."""
    out: list[tuple[bool, str | None]] = []
    n = len(df)
    for i in range(max(MIN_BARRAS, n - ruedas), n):
        G._garch_cache.clear()  # cada barra tiene que fitear de verdad
        G.reset_no_fit_counts()
        res = G.fit_garch_forecast(df.iloc[: i + 1])
        if res is not None:
            out.append((True, None))
        else:
            motivos = G.no_fit_counts()
            out.append((False, max(motivos, key=lambda k: motivos[k]) if motivos else "desconocido"))
    return out


def measure(ruedas: int = 60, limit: int | None = None) -> dict:
    t0 = time.perf_counter()
    filas = []
    for ticker in _tickers(limit):
        df = parquet_cache.read(ticker, PERIODO, "1d", ttl_hours=None)
        if df is None or len(df) < MIN_BARRAS + 1 or "Close" not in df:
            continue
        serie = _serie_de_fits(df, ruedas)
        if len(serie) < 2:
            continue
        fits = [ok for ok, _ in serie]
        flips = sum(1 for a, b in itertools.pairwise(fits) if a != b)
        motivos: dict[str, int] = {}
        for ok, m in serie:
            if not ok and m:
                motivos[m] = motivos.get(m, 0) + 1
        filas.append(
            {
                "ticker": ticker,
                "sesiones": len(serie),
                "n_fit": sum(fits),
                "n_no_fit": len(fits) - sum(fits),
                "flips": flips,
                "motivos": motivos,
            }
        )

    al_filo = [f for f in filas if f["flips"] > 0]
    nunca = [f for f in filas if f["n_fit"] == 0]
    siempre = [f for f in filas if f["n_no_fit"] == 0]
    total_motivos: dict[str, int] = {}
    for f in filas:
        for k, v in f["motivos"].items():
            total_motivos[k] = total_motivos.get(k, 0) + v

    return {
        "ruedas_pedidas": ruedas,
        "segundos": time.perf_counter() - t0,
        "n_tickers": len(filas),
        "n_sesiones_evaluadas": sum(f["sesiones"] for f in filas),
        "siempre_fitean": len(siempre),
        "nunca_fitean": len(nunca),
        "al_filo": len(al_filo),
        "flips_totales": sum(f["flips"] for f in filas),
        "motivos": total_motivos,
        "referencia_29c": {"al_filo": 3, "de": 133, "medido_sobre": "un solo día simulado"},
        "peores": sorted(al_filo, key=lambda f: -f["flips"])[:12],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fragilidad del fit de GARCH (tarea 67)")
    ap.add_argument("--ruedas", type=int, default=60)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if not G._ARCH_OK:
        print("arch no está instalado: no hay nada que medir", file=sys.stderr)
        return 2

    m = measure(args.ruedas, args.limit)
    if args.json:
        print(json.dumps(m, indent=2, default=str))
        return 0

    print("=" * 78)
    print("GARCH-FRAGIL (tarea 67) — ¿cuántos tickers alternan fit ↔ no-fit?")
    print("=" * 78)
    print(
        f"\n{m['n_tickers']} tickers × ~{m['ruedas_pedidas']} sesiones = "
        f"{m['n_sesiones_evaluadas']:,} fits · {m['segundos']:.0f}s"
    )
    r = m["referencia_29c"]
    print(f"Referencia de la 29(c): {r['al_filo']} de {r['de']} — pero medido sobre {r['medido_sobre']}.")

    print(f"\n  siempre fitean : {m['siempre_fitean']}")
    print(f"  nunca fitean   : {m['nunca_fitean']}")
    print(f"  AL FILO        : {m['al_filo']}  ({m['flips_totales']} alternancias en total)")
    print(f"\n  motivos del no-fit: {m['motivos'] or '(ninguno)'}")

    if m["peores"]:
        print("\n  Los que más alternan:")
        print(f"     {'ticker':<8} {'sesiones':>9} {'fit':>5} {'no-fit':>7} {'flips':>6}  motivos")
        for f in m["peores"]:
            print(
                f"     {f['ticker']:<8} {f['sesiones']:>9} {f['n_fit']:>5} {f['n_no_fit']:>7} "
                f"{f['flips']:>6}  {f['motivos']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
