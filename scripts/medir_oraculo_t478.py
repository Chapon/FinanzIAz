"""Tarea 478 — por qué el sanity del oráculo de la T170 no pasa con el orden de candidatos del vivo.

En la 477, con el orden y el costo del vivo, el oráculo del stop (``_oracle_stop_filter``, montado
sobre ``s2.0_t2.0``) le ganó a su control igualado en tasa (``AZAR_MISMA_TASA``) por +2,37 pp de
CAGR y −3,61 pp de caída, y el §5.2 pide ≤ −5,00. Con el orden alfabético da −6,75 (costo del
harness) y −8,53 (costo del vivo). Antes de fijar o descartar un sanity para el marco del vivo, esto
mide dos cosas que la comparación de la T170 da por sentadas:

1. **Que el control esté igualado en tasa.** ``RANDOM_KEEP_PROB = 0,463`` se fijó una vez (T26)
   para que el azar conserve la misma proporción de stops que el oráculo. Con otro orden de
   candidatos el oráculo puede conservar otra: se cuenta, envolviendo los dos filtros.
2. **Cuánto varía el Δ contra el control entre sorteos.** El sanity compara contra **un** sorteo
   (``RANDOM_KEEP_SEED``); acá se corren ``--semillas`` sorteos y se reporta la distribución del
   ΔCAGR y del ΔmaxDD del oráculo contra cada uno, y en cuántos pasaría el umbral.

Descriptivo: no decide nada, no cambia ningún umbral ni re-corre la 477. Sin red, sin tocar
``finanzias.db``.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.harness_config import (
    COSTO_VIVO,
    COSTOS_DEL_RUNNER,
    LIVE_MAX_POSITIONS,
    LIVE_UNIVERSE_FILE,
    SignalStoreGapError,
    StaleArtifactError,
    announce,
    announce_artifacts,
    announce_signal_store,
    artifact_window,
    costo_del_runner,
)
from analysis.orden_del_dia import ORDEN_ALFABETICO, ORDEN_VIVO, rank_del_orden
from analysis.portfolio_sim import simulate_portfolio
from analysis.scaleout_replay import ScaleOutParams
from analysis.walkforward_power import regime_for_date
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_exit_policy_t170 import CHALLENGER_CELL
from scripts.run_ranking_t21 import load_bars_signals_scores
from scripts.run_stop_cal_replay_t26 import (
    RANDOM_KEEP_PROB,
    RANDOM_KEEP_SEED,
    _oracle_stop_filter,
    random_stop_filter,
    summarise,
)
from scripts.run_stop_value_t37 import (
    CAP_DAYS,
    EVAL_MODE,
    FILL_MODE,
    LIVE_GATES,
    SANITY_ORACLE_VS_RANDOM_CAGR,
    SANITY_ORACLE_VS_RANDOM_DD,
    arm_params,
)
from scripts.run_tp_cal_replay_t23 import buy_entries


class Contador:
    """Envuelve un ``StopFilter`` y cuenta cuántas veces se le preguntó y cuántas dejó disparar."""

    def __init__(self, filtro):
        self.filtro = filtro
        self.llamadas = 0
        self.conserva = 0
        self.__qualname__ = getattr(filtro, "__qualname__", "filtro")

    def __call__(self, bars, i, ticker=""):
        self.llamadas += 1
        ok = self.filtro(bars, i, ticker)
        self.conserva += bool(ok)
        return ok

    @property
    def tasa(self) -> float:
        return self.conserva / self.llamadas if self.llamadas else float("nan")


def medir_orden(
    entries, bars_by, sigs_by, score_by, *, orden: str, costo: str, semillas: list[int], args
) -> dict:
    """Base, oráculo y ``len(semillas)`` controles sobre ``s2.0_t2.0``, con ``orden`` y ``costo``."""
    common: dict[str, Any] = dict(
        max_positions=args.max_positions,
        initial_capital=args.capital,
        cap_days=args.cap_days,
        so_params=ScaleOutParams(),
        costs=costo_del_runner(costo),
        regime_of=regime_for_date,
        allow_reentry_while_open=False,
        rank_score=rank_del_orden(orden, score_by),
    )
    kw = arm_params(*CHALLENGER_CELL)
    base = summarise(simulate_portfolio(entries, bars_by, sigs_by, **kw, **common))
    oraculo_f = Contador(_oracle_stop_filter)
    oraculo = summarise(simulate_portfolio(entries, bars_by, sigs_by, stop_filter=oraculo_f, **kw, **common))
    controles = []
    for sd in semillas:
        f = Contador(random_stop_filter(RANDOM_KEEP_PROB, seed=sd))
        s = summarise(simulate_portfolio(entries, bars_by, sigs_by, stop_filter=f, **kw, **common))
        controles.append(
            {
                "semilla": sd,
                "cagr": s["cagr"],
                "max_dd": s["max_dd"],
                "tasa": f.tasa,
                "llamadas": f.llamadas,
                "stop_share": s["exit_mix"].get("atr_stop", 0.0),
                "d_cagr": oraculo["cagr"] - s["cagr"],
                "d_dd": oraculo["max_dd"] - s["max_dd"],
            }
        )
        print(
            f"    {orden}/{costo} semilla {sd}: ΔCAGR {100 * controles[-1]['d_cagr']:+.2f} ΔDD {100 * controles[-1]['d_dd']:+.2f}",
            flush=True,
        )
    return {
        "base": base,
        "oraculo": oraculo,
        "oraculo_tasa": oraculo_f.tasa,
        "oraculo_llamadas": oraculo_f.llamadas,
        "controles": controles,
    }


def semillas_del_control(n: int) -> list[int]:
    """El sorteo de la T170 primero —el que decidió su sanity y el de la 477— y después ``n`` más."""
    return [RANDOM_KEEP_SEED, *(s for s in range(1, n + 1) if s != RANDOM_KEEP_SEED)]


def _q(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, round(q * (len(s) - 1))))]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Tarea 478 — el sanity del oráculo con cada orden de candidatos")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--costo", choices=COSTOS_DEL_RUNNER, default=COSTO_VIVO)
    p.add_argument("--semillas", type=int, default=20, help="sorteos del control, además del de la T170")
    p.add_argument("--allow-stale-artifacts", action="store_true")
    args = p.parse_args(argv)

    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, score_by, _missing = load_bars_signals_scores(tickers, args.period, args.warmup)
    if not bars_by:
        print("Sin datos PIT.", file=sys.stderr)
        return 1
    entries = buy_entries(bars_by, sigs_by, args.warmup)
    window = artifact_window(bars_by)
    try:
        announce_artifacts(bars_by, strict=not args.allow_stale_artifacts)
        announce_signal_store(bars_by, args.period, args.warmup, strict=not args.allow_stale_artifacts)
    except (StaleArtifactError, SignalStoreGapError) as exc:
        print(f"*** ABORTA — {exc} ***", file=sys.stderr)
        return 3
    cm = costo_del_runner(args.costo)
    announce(
        args.max_positions,
        args.universe,
        len(bars_by),
        window=window,
        eval_mode=EVAL_MODE,
        fill_mode=FILL_MODE,
        live_gates=LIVE_GATES,
        costo_por_lado=cm.commission + cm.slippage,
    )
    print("(Corre los dos órdenes de candidatos: el banner es el del alfabético.)\n")
    semillas = semillas_del_control(args.semillas)
    print(
        f"Tickers {len(bars_by)} · entradas {len(entries)} · costo {args.costo} · {len(semillas)} sorteos del control\n"
    )

    for orden in (ORDEN_ALFABETICO, ORDEN_VIVO):
        m = medir_orden(
            entries, bars_by, sigs_by, score_by, orden=orden, costo=args.costo, semillas=semillas, args=args
        )
        cs = m["controles"]
        dd = [c["d_dd"] for c in cs]
        dc = [c["d_cagr"] for c in cs]
        pasa = sum(
            1
            for c in cs
            if c["d_cagr"] >= SANITY_ORACLE_VS_RANDOM_CAGR and c["d_dd"] <= -SANITY_ORACLE_VS_RANDOM_DD
        )
        print(f"\n== orden {orden}, costo {args.costo} ==")
        print(
            f"  base s2.0_t2.0: CAGR {100 * m['base']['cagr']:.2f}% · caída {100 * m['base']['max_dd']:.1f}% · "
            f"stops {100 * m['base']['exit_mix'].get('atr_stop', 0):.1f}% de los trades"
        )
        print(
            f"  oráculo: CAGR {100 * m['oraculo']['cagr']:.2f}% · caída {100 * m['oraculo']['max_dd']:.1f}% · "
            f"conserva {100 * m['oraculo_tasa']:.1f}% de {m['oraculo_llamadas']} consultas (el control usa {100 * RANDOM_KEEP_PROB:.1f}%)"
        )
        # La tasa como la definió la T26: salidas por stop del brazo sobre las de la base.
        base_s = m["base"]["exit_mix"].get("atr_stop", 0.0)
        orc_s = m["oraculo"]["exit_mix"].get("atr_stop", 0.0)
        ctl_s = statistics.median(c["stop_share"] for c in cs)
        print(
            f"  salidas por stop (la tasa de la T26): base {100 * base_s:.1f}% · oráculo {100 * orc_s:.1f}% "
            f"(razón {orc_s / base_s:.3f}) · control, mediana {100 * ctl_s:.1f}% (razón {ctl_s / base_s:.3f})"
        )
        t170 = cs[0]
        print(
            f"  contra el sorteo de la T170 (semilla {t170['semilla']}): ΔCAGR {100 * t170['d_cagr']:+.2f} pp · "
            f"ΔDD {100 * t170['d_dd']:+.2f} pp · el control conserva {100 * t170['tasa']:.1f}%"
        )
        print(
            f"  contra {len(cs)} sorteos: ΔCAGR mediana {100 * statistics.median(dc):+.2f} "
            f"[p10 {100 * _q(dc, 0.1):+.2f}, p90 {100 * _q(dc, 0.9):+.2f}] · "
            f"ΔDD mediana {100 * statistics.median(dd):+.2f} [p10 {100 * _q(dd, 0.1):+.2f}, p90 {100 * _q(dd, 0.9):+.2f}] · "
            f"el sanity pasaría en {pasa} de {len(cs)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
