"""
Cartera de calidad y valor de largo plazo contra el mismo universo — **tarea 385** (backtest, regla 2).

Implementa el pre-registro congelado ``docs/cartera_calidad_valor_prereg_t385_2026-10-21.md``
(commit ``6c5044d``) y nada más: cinco carteras (Universo, Calidad, Valor, Calidad + valor y Azar),
rebalanceo el primer día hábil de abril, 20 nombres, partes iguales, costo medido de la cuenta 2, y
los cinco criterios contra Universo.

Lee el cohorte de 10 años (con los guards de la 76 y la 86), el almacén point-in-time de la 382 y,
**con red**, los cierres sin ajuste por dividendos y los splits de Yahoo para la cartera de Valor.
No toca la DB ni el motor.

Uso:
    python scripts/run_cartera_calidad_valor_t385.py --allow-stale-artifacts
    python scripts/run_cartera_calidad_valor_t385.py --allow-stale-artifacts --json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── Congelado en el pre-registro ─────────────────────────────────────────────────────
N_NOMBRES = 20
COSTO = 0.00064  # de lo operado: $542,76 / $853.648 de la cuenta 2 al 20/10 (tarea 386)
MES_REBALANCEO = "04"
N_AZAR = 200
SEMILLA = 385
UMBRAL_CAGR = 0.01
UMBRAL_DD = 0.03
PERCENTIL_AZAR = 90
SUBVENTANAS = (("2016-09-01", "2019-12-31"), ("2020-01-01", "2022-12-31"), ("2023-01-01", "2026-09-30"))
CARTERAS_QUE_ELIGEN = ("Calidad", "Valor", "Calidad + valor")


# ── Piezas puras ─────────────────────────────────────────────────────────────────────


def fechas_de_rebalanceo(calendario: list[str], mes: str = MES_REBALANCEO) -> list[str]:
    """El primer día hábil del mes ``mes`` de cada año del calendario."""
    out, visto = [], set()
    for d in calendario:
        if d[5:7] == mes and d[:4] not in visto:
            visto.add(d[:4])
            out.append(d)
    return out


def los_mejores(puntaje: dict[str, float | None], n: int = N_NOMBRES) -> list[str]:
    """Los ``n`` de mayor puntaje (sin los ``None``); los empates, por ticker."""
    validos = [(v, t) for t, v in puntaje.items() if v is not None]
    return [t for _, t in sorted(validos, key=lambda x: (-x[0], x[1]))[:n]]


def calidad_mas_valor(
    calidad: dict[str, float | None], retorno: dict[str, float | None], n: int = N_NOMBRES
) -> list[str]:
    """Entre la mitad de mejor calidad, los ``n`` de mayor retorno esperado.

    La mitad es exacta: los ``ceil(k/2)`` de mejor puntaje entre los ``k`` que tienen. La primera
    versión cortaba en la mediana **de abajo** e incluía de más (con 4, entraban 3).
    """
    con_calidad = los_mejores(calidad, n=len(calidad))
    buena = set(con_calidad[: math.ceil(len(con_calidad) / 2)])
    return los_mejores({t: r for t, r in retorno.items() if t in buena}, n)


def simular(
    precios: np.ndarray,
    tickers: list[str],
    indices_rebalanceo: list[int],
    elecciones: list[list[str]],
    costo: float = COSTO,
) -> np.ndarray:
    """Valor diario de una cartera de partes iguales que se rebalancea en ``indices_rebalanceo``.

    ``precios`` es (días × tickers), con el último cierre arrastrado hacia adelante (un ticker que
    deja de cotizar queda quieto) y ``nan`` antes de su primer cierre. Arranca en 1,0 el día del
    primer rebalanceo. En cada rebalanceo cobra ``costo`` sobre lo operado: la diferencia entre la
    cartera que había (ya movida por los precios) y la nueva. Devuelve el valor desde el primer
    rebalanceo hasta el final.
    """
    col = {t: i for i, t in enumerate(tickers)}
    inicio = indices_rebalanceo[0]
    valores = np.empty(precios.shape[0] - inicio)
    acciones = np.zeros(len(tickers))
    valor = 1.0
    cortes = [*indices_rebalanceo, precios.shape[0]]
    for k, (desde, hasta) in enumerate(pairwise(cortes)):
        p = np.nan_to_num(precios[desde])
        valor = float(acciones @ p) if k else 1.0
        elegidos = [col[t] for t in elecciones[k] if p[col[t]] > 0]
        nuevo = np.zeros(len(tickers))
        if elegidos:
            nuevo[elegidos] = valor / len(elegidos)
        operado = float(np.abs(nuevo - acciones * p).sum()) if k else float(nuevo.sum())
        valor -= operado * costo
        acciones = np.zeros(len(tickers))
        if elegidos:
            acciones[elegidos] = (valor / len(elegidos)) / p[elegidos]
        tramo = np.nan_to_num(precios[desde:hasta]) @ acciones
        valores[desde - inicio : hasta - inicio] = tramo
    return valores


def cagr(valores: np.ndarray, dias_por_anio: int = 252) -> float:
    return float((valores[-1] / valores[0]) ** (dias_por_anio / (len(valores) - 1)) - 1)


def caida_maxima(valores: np.ndarray) -> float:
    picos = np.maximum.accumulate(valores)
    return float((1 - valores / picos).max())


def cagr_en(valores: np.ndarray, fechas: list[str], desde: str, hasta: str) -> float | None:
    idx = [i for i, d in enumerate(fechas) if desde <= d <= hasta]
    if len(idx) < 2:
        return None
    return cagr(valores[idx[0] : idx[-1] + 1])


def criterios(
    cartera: np.ndarray,
    universo: np.ndarray,
    fechas: list[str],
    cagr_azar: list[float],
    bootstrap,
) -> dict:
    """Los cinco criterios del pre-registro, contra Universo. Pura salvo por ``bootstrap``."""
    c, u = cagr(cartera), cagr(universo)
    dd_c, dd_u = caida_maxima(cartera), caida_maxima(universo)
    gana = []
    for desde, hasta in SUBVENTANAS:
        a, b = cagr_en(cartera, fechas, desde, hasta), cagr_en(universo, fechas, desde, hasta)
        gana.append(a is not None and b is not None and a > b)
    rc = np.diff(cartera) / cartera[:-1]
    ru = np.diff(universo) / universo[:-1]
    bs = bootstrap(list(ru), list(rc))
    p90 = float(np.percentile(cagr_azar, PERCENTIL_AZAR)) if cagr_azar else math.inf
    resultado = {
        "cagr": c,
        "cagr_universo": u,
        "caida_maxima": dd_c,
        "caida_maxima_universo": dd_u,
        "subventanas_ganadas": sum(gana),
        "bootstrap": {"observado": bs.observed, "ci_low": bs.ci_low, "ci_high": bs.ci_high},
        "percentil_90_azar": p90,
        "c1_rendimiento": c >= u + UMBRAL_CAGR,
        "c2_no_es_suerte": bs.ci_low > 0,
        "c3_riesgo": dd_c <= dd_u + UMBRAL_DD,
        "c4_estabilidad": sum(gana) >= 2,
        "c5_seleccion": c > p90,
    }
    resultado["pasa"] = all(
        resultado[k]
        for k in ("c1_rendimiento", "c2_no_es_suerte", "c3_riesgo", "c4_estabilidad", "c5_seleccion")
    )
    return resultado


def recortado_a(fund, fecha: str):
    """El mismo ``Fundamentos`` con sólo lo presentado antes de ``fecha``: el control de no mirar el futuro."""
    from data.fundamentos_pit import Fundamentos

    if fund is None:
        return None
    return Fundamentos(
        ticker=fund.ticker,
        registros=[r for r in fund.registros if r.filed < fecha],
        extranjera=fund.extranjera,
        ciks=fund.ciks,
        generado=fund.generado,
    )


# ── La corrida ───────────────────────────────────────────────────────────────────────


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
    from analysis.valuation import valuar
    from analysis.walkforward_power import paired_block_bootstrap
    from data import fundamentos_pit as fp
    from data.yahoo_finance import get_cierres_sin_ajuste_por_dividendos, get_split_events
    from scripts.precompute_pit_signals import parse_universe_file
    from scripts.run_tp_cal_replay_t23 import load_bars_signals

    p = argparse.ArgumentParser(description="CARTERA-CALIDAD-Y-VALOR (tarea 385)")
    p.add_argument("--allow-stale-artifacts", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    log = sys.stderr

    tickers_u = parse_universe_file(_ROOT / LIVE_UNIVERSE_FILE)
    bars_by, _sigs, _missing = load_bars_signals(tickers_u, "10y", 250)
    try:
        announce_artifacts(bars_by, strict=not args.allow_stale_artifacts, file=log)
        announce_signal_store(bars_by, "10y", 250, strict=not args.allow_stale_artifacts, file=log)
    except (StaleArtifactError, SignalStoreGapError) as exc:
        print(f"*** ABORTA — {exc} ***", file=log)
        return 3
    print(f"Ventana del cohorte: {artifact_window(bars_by)}", file=log)

    tickers = sorted(bars_by)
    fechas = sorted({b[0] for bs in bars_by.values() for b in bs})
    pos = {d: i for i, d in enumerate(fechas)}
    precios = np.full((len(fechas), len(tickers)), np.nan)
    for j, t in enumerate(tickers):
        for b in bars_by[t]:
            precios[pos[b[0]], j] = b[4]
    for j in range(len(tickers)):  # arrastrar el último cierre
        ultimo = np.nan
        for i in range(len(fechas)):
            if np.isnan(precios[i, j]):
                precios[i, j] = ultimo
            else:
                ultimo = precios[i, j]

    rebal = fechas_de_rebalanceo(fechas)
    idx_rebal = [pos[d] for d in rebal]
    print(f"Rebalanceos: {', '.join(rebal)}", file=log)

    fund = {t: fp.cargar(t) for t in tickers}
    print("Bajando cierres sin ajuste por dividendos y splits (Yahoo)…", file=log)
    sin_div = {t: get_cierres_sin_ajuste_por_dividendos(t) for t in tickers}
    splits = {t: get_split_events(t) for t in tickers}

    elecciones: dict[str, list[list[str]]] = {c: [] for c in ("Universo", *CARTERAS_QUE_ELIGEN)}
    controles = {"mira_el_futuro": [], "valor_sin_dato": []}
    for d, i in zip(rebal, idx_rebal, strict=True):
        elegibles = [t for j, t in enumerate(tickers) if not np.isnan(precios[i, j])]
        calidad = {t: r["puntaje"] for t, r in puntajes({t: patas_de(fund[t], d) for t in elegibles}).items()}
        retorno: dict[str, float | None] = {}
        for t in elegibles:
            cierres = [(f, c) for f, c in sin_div[t] if f <= d]
            v = valuar(fund[t], cierres[-1][1] if cierres else None, cierres, d, splits[t])
            retorno[t] = v.retorno_anual if v else None
            # Control: con el almacén recortado a lo presentado antes de d, tiene que dar lo mismo.
            v2 = valuar(recortado_a(fund[t], d), cierres[-1][1] if cierres else None, cierres, d, splits[t])
            if (v2.retorno_anual if v2 else None) != retorno[t]:
                controles["mira_el_futuro"].append((d, t))
        calidad_recortada = {
            t: r["puntaje"]
            for t, r in puntajes({t: patas_de(recortado_a(fund[t], d), d) for t in elegibles}).items()
        }
        if calidad_recortada != calidad:
            controles["mira_el_futuro"].append((d, "calidad"))
        controles["valor_sin_dato"].append((d, sum(1 for r in retorno.values() if r is None), len(elegibles)))
        elecciones["Universo"].append(elegibles)
        elecciones["Calidad"].append(los_mejores(calidad))
        elecciones["Valor"].append(los_mejores(retorno))
        elecciones["Calidad + valor"].append(calidad_mas_valor(calidad, retorno))

    if controles["mira_el_futuro"]:
        print(
            f"*** ABORTA — la selección cambia sin los datos futuros: {controles['mira_el_futuro'][:5]} ***",
            file=log,
        )
        return 5

    # Control: Universo sin costos = promedio de los retornos de cada tramo.
    sin_costo = simular(precios, tickers, idx_rebal, elecciones["Universo"], costo=0.0)
    cortes = [*idx_rebal, len(fechas) - 1]
    for k, (a, b) in enumerate(pairwise(cortes)):
        cols = [tickers.index(t) for t in elecciones["Universo"][k]]
        esperado = float(np.mean(precios[b, cols] / precios[a, cols])) * (sin_costo[a - cortes[0]])
        if not math.isclose(sin_costo[b - cortes[0]], esperado, rel_tol=1e-9):
            print(f"*** ABORTA — Universo no reproduce el promedio en el tramo {k} ***", file=log)
            return 5

    fechas_sim = fechas[idx_rebal[0] :]
    curvas = {c: simular(precios, tickers, idx_rebal, e) for c, e in elecciones.items()}
    rng = np.random.default_rng(SEMILLA)
    cagr_azar = []
    for _ in range(N_AZAR):
        eleccion = [
            list(rng.choice(e, size=min(N_NOMBRES, len(e)), replace=False)) for e in elecciones["Universo"]
        ]
        cagr_azar.append(cagr(simular(precios, tickers, idx_rebal, eleccion)))

    def _bootstrap(base, cand):
        return paired_block_bootstrap(base, cand, block=20, n_resamples=2000, seed=SEMILLA)

    resultados = {
        c: criterios(curvas[c], curvas["Universo"], fechas_sim, cagr_azar, _bootstrap)
        for c in CARTERAS_QUE_ELIGEN
    }
    salida = {
        "rebalanceos": rebal,
        "desde": fechas_sim[0],
        "hasta": fechas_sim[-1],
        "universo": {"cagr": cagr(curvas["Universo"]), "caida_maxima": caida_maxima(curvas["Universo"])},
        "azar": {
            "mediana": float(np.median(cagr_azar)),
            "percentil_90": float(np.percentile(cagr_azar, 90)),
        },
        "valor_sin_dato": controles["valor_sin_dato"],
        "carteras": resultados,
        "elecciones_ultimo_rebalanceo": {c: e[-1] for c, e in elecciones.items() if c != "Universo"},
    }
    if args.json:
        print(json.dumps(salida, indent=2, default=str))
        return 0
    print(f"Ventana simulada: {salida['desde']} → {salida['hasta']} · {len(rebal)} rebalanceos")
    print(
        f"Universo: crecimiento anual {salida['universo']['cagr']:+.2%} · caída máxima {salida['universo']['caida_maxima']:.1%}"
    )
    print(
        f"Azar (200 carteras de 20): mediana {salida['azar']['mediana']:+.2%} · percentil 90 {salida['azar']['percentil_90']:+.2%}"
    )
    for c, r in resultados.items():
        bs = r["bootstrap"]
        marcas = " ".join(
            f"{n}={'sí' if r[k] else 'no'}"
            for n, k in (
                ("C1", "c1_rendimiento"),
                ("C2", "c2_no_es_suerte"),
                ("C3", "c3_riesgo"),
                ("C4", "c4_estabilidad"),
                ("C5", "c5_seleccion"),
            )
        )
        print(
            f"{c}: crecimiento anual {r['cagr']:+.2%} · caída máxima {r['caida_maxima']:.1%} · "
            f"gana {r['subventanas_ganadas']}/3 sub-ventanas · diferencia {bs['observado']:+.2%} "
            f"[{bs['ci_low']:+.2%}, {bs['ci_high']:+.2%}] · {marcas} → {'PASA' if r['pasa'] else 'NO PASA'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
