"""
¿El puntaje de calidad ordena el retorno que viene? — **tarea 384**, medición (display-only).

Cada primer día hábil del mes, con los fundamentals que se conocían **antes** de esa fecha (tarea
382), calcula el puntaje de ``analysis.calidad`` para el universo de la cuenta 2 y lo cruza con el
exceso sobre SPY de los próximos 60, 120 y 250 días hábiles (cierres del cohorte, ajustados por
dividendos: es retorno total). Publica:

- **IC:** la correlación de Spearman entre puntaje y exceso, mes a mes, y su media;
- **diferencial:** el exceso medio del tercio de mejor puntaje menos el del peor tercio;
- **IC95%** de los dos, por bootstrap de bloques de meses (los meses vecinos comparten ventana).

El número se publica **aunque sea cero**: es insumo de la 385, no una decisión.

**Sesgos declarados:** el universo es la watchlist de hoy (survivorship: las que quebraron o
salieron no están), y son large caps, donde la evidencia de calidad es más débil.

No pega a la red ni toca la DB.

Uso:
    python scripts/measure_calidad_t384.py --allow-stale-artifacts
    python scripts/measure_calidad_t384.py --allow-stale-artifacts --json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

HORIZONTES = (60, 120, 250)
N_BOOT = 5000
SEED = 384


def primeros_dias_de_mes(calendario: list[str]) -> list[str]:
    """La primera rueda de cada mes del calendario. Pura."""
    out, visto = [], set()
    for d in calendario:
        if d[:7] not in visto:
            visto.add(d[:7])
            out.append(d)
    return out


def _rangos(x: np.ndarray) -> np.ndarray:
    orden = np.argsort(x, kind="mergesort")
    r = np.empty(len(x))
    xs = x[orden]
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[j + 1] == xs[i]:
            j += 1
        r[orden[i : j + 1]] = (i + j) / 2
        i = j + 1
    return r


def spearman(a: list[float], b: list[float]) -> float | None:
    """Correlación de rangos. Pura. ``None`` con menos de 10 pares o sin varianza."""
    if len(a) < 10:
        return None
    ra, rb = _rangos(np.asarray(a, float)), _rangos(np.asarray(b, float))
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def diferencial_tercios(puntajes: list[float], excesos: list[float]) -> float | None:
    """Exceso medio del tercio de mejor puntaje menos el del peor. Pura."""
    n = len(puntajes)
    if n < 9:
        return None
    orden = np.argsort(puntajes)
    k = n // 3
    ex = np.asarray(excesos, float)
    return float(ex[orden[-k:]].mean() - ex[orden[:k]].mean())


def ic_bloques(serie: list[float], bloque: int, *, n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """Media de una serie mensual con IC95% por bootstrap de bloques móviles de ``bloque`` meses. Pura."""
    x = np.asarray([v for v in serie if v is not None], float)
    if len(x) < 2 * bloque:
        return {"n": len(x), "media": float(x.mean()) if len(x) else None, "ic95": None}
    rng = np.random.default_rng(seed)
    n_bloques = math.ceil(len(x) / bloque)
    medias = np.empty(n_boot)
    for i in range(n_boot):
        inicios = rng.integers(0, len(x) - bloque + 1, size=n_bloques)
        muestra = np.concatenate([x[s : s + bloque] for s in inicios])[: len(x)]
        medias[i] = muestra.mean()
    return {
        "n": len(x),
        "media": float(x.mean()),
        "ic95": [float(np.percentile(medias, 2.5)), float(np.percentile(medias, 97.5))],
    }


def exceso(
    bars: list, spy: dict[str, float], idx: dict[str, int], cal: list[str], d: str, h: int
) -> float | None:
    if d not in idx or idx[d] + h >= len(cal):
        return None
    fin = cal[idx[d] + h]
    cierres = {b[0]: b[4] for b in bars}
    t0, t1 = cierres.get(d), cierres.get(fin)
    s0, s1 = spy.get(d), spy.get(fin)
    if not (t0 and t1 and s0 and s1):
        return None
    return (t1 / t0 - 1) - (s1 / s0 - 1)


def main(argv: list[str] | None = None) -> int:
    from analysis.calidad import patas_de, puntajes
    from analysis.harness_config import (
        LIVE_UNIVERSE_FILE,
        SignalStoreGapError,
        StaleArtifactError,
        announce_artifacts,
        announce_signal_store,
        artifact_window,
    )
    from data import fundamentos_pit as fp
    from data import parquet_cache
    from scripts.precompute_pit_signals import parse_universe_file
    from scripts.run_tp_cal_replay_t23 import load_bars_signals

    p = argparse.ArgumentParser(description="PUNTAJE-DE-CALIDAD (tarea 384)")
    p.add_argument("--allow-stale-artifacts", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    tickers = parse_universe_file(_ROOT / LIVE_UNIVERSE_FILE)
    bars_by, _sigs, _missing = load_bars_signals(tickers, "10y", 250)
    try:
        announce_artifacts(bars_by, strict=not args.allow_stale_artifacts, file=sys.stderr)
        announce_signal_store(bars_by, "10y", 250, strict=not args.allow_stale_artifacts, file=sys.stderr)
    except (StaleArtifactError, SignalStoreGapError) as exc:
        print(f"*** ABORTA — {exc} ***", file=sys.stderr)
        return 3
    print(f"Ventana del cohorte: {artifact_window(bars_by)}", file=sys.stderr)

    spy_df = parquet_cache.read("SPY", "10y", "1d", None)
    spy = {ts.strftime("%Y-%m-%d"): float(c) for ts, c in spy_df["Close"].items()}
    cal = sorted(set(spy) & {b[0] for bs in bars_by.values() for b in bs})
    idx = {d: i for i, d in enumerate(cal)}
    fund = {t: fp.cargar(t) for t in bars_by}

    filas = {h: {"ic": [], "dif": [], "fechas": []} for h in HORIZONTES}
    for d in primeros_dias_de_mes(cal):
        s = puntajes({t: patas_de(f, d) for t, f in fund.items()})
        for h in HORIZONTES:
            pares = [
                (v["puntaje"], x)
                for t, v in s.items()
                if v["puntaje"] is not None and (x := exceso(bars_by[t], spy, idx, cal, d, h)) is not None
            ]
            if len(pares) < 10:
                continue
            a, b = zip(*pares, strict=True)
            filas[h]["ic"].append(spearman(list(a), list(b)))
            filas[h]["dif"].append(diferencial_tercios(list(a), list(b)))
            filas[h]["fechas"].append(d)

    out = {}
    for h in HORIZONTES:
        bloque = max(1, math.ceil(h / 21))
        f = filas[h]
        out[h] = {
            "meses": len(f["fechas"]),
            "desde": f["fechas"][0] if f["fechas"] else None,
            "hasta": f["fechas"][-1] if f["fechas"] else None,
            "ic": ic_bloques(f["ic"], bloque),
            "diferencial_tercios": ic_bloques(f["dif"], bloque),
        }
    if args.json:
        print(json.dumps(out, indent=2))
        return 0
    print("Puntaje de calidad contra el exceso sobre SPY que viene · universo de la cuenta 2 (survivorship)")
    for h, r in out.items():
        ic, dif = r["ic"], r["diferencial_tercios"]
        fmt = lambda z, pct=False: "—" if z is None else (f"{z * 100:+.2f}%" if pct else f"{z:+.3f}")
        ic95 = "—" if not ic["ic95"] else f"[{fmt(ic['ic95'][0])}, {fmt(ic['ic95'][1])}]"
        d95 = "—" if not dif["ic95"] else f"[{fmt(dif['ic95'][0], True)}, {fmt(dif['ic95'][1], True)}]"
        print(
            f"  +{h:>3} ruedas · {r['meses']} meses ({r['desde']} → {r['hasta']}): "
            f"IC medio {fmt(ic['media'])} {ic95} · tercio alto − bajo {fmt(dif['media'], True)} {d95}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
