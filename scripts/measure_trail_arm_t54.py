"""
Medición descriptiva del ARMADO del trailing — **Tarea 54 (TRAIL-ARM)**, paso previo
al pre-registro.

Por qué existe
--------------
La 37 midió que en el candidato que hoy corre en vivo (``soff_t2.0``: stop duro
apagado, trailing en 2.0×ATR) el **36,5%** de los trades tiene un HWM que nunca
supera ``entrada + 1×ATR``, así que **el trailing nunca se arma** y esas posiciones
quedan con una sola barrera. La pregunta de la 54 es si bajar ese umbral
(``trail_min_excess_atrs``) cierra el agujero o sólo adelanta salidas.

Y la **58 (GRIDPOP)** dice qué hay que hacer **antes** de congelar esa grilla: medir
la distribución de la magnitud que el umbral corta, y elegir los valores de ahí. Eso
es exactamente lo que hace este script — no decide nada, no corre brazos, no
compara: publica la distribución del **excedente máximo en ATRs** de cada trade,

    excedente = (HWM del ciclo − close de la barra de entrada) / ATR(entrada)

que es la magnitud contra la que ``gates.atr_exit_decision`` compara el umbral
(``paper_trading/gates.py:151``) y ``analysis.exit_replay`` replica
(``exit_replay.py:178``).

Dos poblaciones distintas, y la diferencia importa
--------------------------------------------------
* **Acumulada** — cuántos trades tienen ``excedente > k``: es la fracción cuyo
  trailing **estaría armado** con el umbral ``k``.
* **Diferencial** — cuántos trades tienen ``k < excedente <= 1.0``: son los que
  **cambian de comportamiento** al bajar el umbral de 1.0 a ``k``, y por lo tanto
  la única población que un brazo puede mover. El sanity de población de la T13
  (≥5%) se lee sobre **ésta**.

Sin red y sin tocar ``finanzias.db``. No toca ``engine.py``/``gates.py``.

Uso::

    python scripts/measure_trail_arm_t54.py            # tabla
    python scripts/measure_trail_arm_t54.py --json     # el detalle completo
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from itertools import pairwise
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.exit_replay import AtrParams, atr_series
from analysis.harness_config import (
    LIVE_MAX_POSITIONS,
    LIVE_UNIVERSE_FILE,
    announce,
    announce_grid,
    artifact_window,
)
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio
from analysis.scaleout_replay import CostModel, ScaleOutParams
from analysis.walkforward_power import regime_for_date
from scripts.precompute_pit_signals import parse_universe_file
from scripts.run_ranking_t21 import summarise
from scripts.run_stop_cal_replay_t26 import NO_STOP
from scripts.run_tp_cal_replay_t23 import buy_entries, load_bars_signals

# La config de la cuenta viva, la misma de la 37/51 (touch/decision/live_gates).
EVAL_MODE = "touch"
FILL_MODE = "decision"
LIVE_GATES = True
CAP_DAYS = 250

# El brazo VIVO desde el 2026-08-27: stop duro apagado + trailing en 2.0×ATR.
LIVE_TRAIL_MULT = 2.0
LIVE_MIN_EXCESS = 1.0

# La grilla candidata que este script existe para justificar (o descartar).
CANDIDATE_GRID: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5)


def trade_excess_atrs(res: PortfolioResult, bars_by: dict, period: int = 14) -> list[dict]:
    """Por trade: el **excedente máximo en ATRs** y el retorno realizado.

    Aproximación declarada, la misma de la 37 §7: ``avg_cost`` ≈ close de la barra
    de entrada (sin costos ni scale-out), que es lo que ``Trade`` expone.
    """
    atr_cache: dict[str, list] = {}
    idx_cache: dict[str, dict[str, int]] = {}
    out: list[dict] = []
    for t in res.trades:
        bars = bars_by.get(t.ticker)
        if not bars:
            continue
        if t.ticker not in idx_cache:
            idx_cache[t.ticker] = {b[0]: i for i, b in enumerate(bars)}
            atr_cache[t.ticker] = atr_series(bars, period=period)
        pos = idx_cache[t.ticker]
        i0, i1 = pos.get(t.entry_date), pos.get(t.exit_date)
        if i0 is None or i1 is None or i1 < i0:
            continue
        atr0 = atr_cache[t.ticker][i0]
        if atr0 is None or not math.isfinite(atr0) or atr0 <= 0:
            continue
        entry_close = bars[i0][4]
        hwm = max(b[2] for b in bars[i0 : i1 + 1])
        out.append(
            {
                "ticker": t.ticker,
                "entry": t.entry_date,
                "exit": t.exit_date,
                "excess_atrs": (hwm - entry_close) / atr0,
                "ret_pts": 100.0 * t.ret,
                "held_days": t.held_days,
            }
        )
    return out


def differential_population(excess: list[float], grid, base: float = LIVE_MIN_EXCESS) -> list[dict]:
    """Los trades que **cambian de comportamiento** al bajar el umbral a cada valor.

    Un brazo con umbral ``k < base`` sólo puede mover a los trades cuyo excedente
    cae en ``(k, base]``: los de arriba ya armaban el trailing y los de abajo siguen
    sin armarlo. Es la población que el sanity de la T13 tiene que mirar — la
    acumulada la sobrestima, y ése es justo el error que la 51 pagó por el otro eje.
    """
    n = len(excess)
    out = []
    for k in grid:
        lo, hi = min(k, base), max(k, base)
        if k == base:
            hit = 0
        else:
            hit = sum(1 for m in excess if lo < m <= hi)
        out.append(
            {
                "value": k,
                "n_changed": hit,
                "share": (hit / n) if n else 0.0,
                "direction": "baja" if k < base else ("sube" if k > base else "base"),
            }
        )
    return out


def _pct(sorted_vals: list[float], q: float) -> float:
    idx = math.ceil(q * len(sorted_vals)) - 1
    return sorted_vals[min(max(idx, 0), len(sorted_vals) - 1)]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="TRAIL-ARM: distribución del armado (tarea 54)")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    log = sys.stderr if args.json else sys.stdout
    tickers = parse_universe_file(_HERE.parent / args.universe)
    bars_by, sigs_by, _missing = load_bars_signals(tickers, args.period, args.warmup)
    if not bars_by:
        print("Sin datos PIT: corré scripts/precompute_pit_signals.py primero.", file=sys.stderr)
        return 1
    entries = buy_entries(bars_by, sigs_by, args.warmup)

    window = artifact_window(bars_by)
    announce(
        args.max_positions,
        args.universe,
        len(bars_by),
        window=window,
        eval_mode=EVAL_MODE,
        fill_mode=FILL_MODE,
        live_gates=LIVE_GATES,
        file=log,
    )
    print(f"Tickers: {len(bars_by)} · entradas `analyze BUY`: {len(entries)}", file=log)
    print(
        f"Brazo medido: el VIVO desde 2026-08-27 — stop duro OFF + trail "
        f"{LIVE_TRAIL_MULT}×ATR, armado en {LIVE_MIN_EXCESS}×ATR\n",
        file=log,
    )

    res = simulate_portfolio(
        entries,
        bars_by,
        sigs_by,
        atr_p=AtrParams(stop_mult=NO_STOP, trail_mult=LIVE_TRAIL_MULT, trail_min_excess_atrs=LIVE_MIN_EXCESS),
        eval_mode=EVAL_MODE,
        fill_mode=FILL_MODE,
        live_gates=LIVE_GATES,
        max_positions=args.max_positions,
        initial_capital=args.capital,
        cap_days=CAP_DAYS,
        so_params=ScaleOutParams(),
        costs=CostModel(),
        regime_of=regime_for_date,
        allow_reentry_while_open=False,
    )
    # El ancla de reproduccion del pre-registro: el brazo vivo tiene que dar el
    # 9.17% que publico la T37 (§7.7) sobre esta misma ventana y poblacion.
    base_sum = summarise(res)
    print(
        f"Brazo vivo soff_t{LIVE_TRAIL_MULT}: CAGR {100 * base_sum['cagr']:.2f}% · "
        f"Sharpe {base_sum['sharpe']:.2f} · maxDD {100 * base_sum['max_dd']:.1f}% · "
        f"tomadas {base_sum['n_taken']} · tenencia {base_sum['mean_held_days']:.1f}d\n",
        file=log,
    )

    rows = trade_excess_atrs(res, bars_by)
    excess = [r["excess_atrs"] for r in rows]
    if not excess:
        print("Sin trades medibles.", file=sys.stderr)
        return 1

    # 1. La distribución acumulada, con el instrumento de la 58.
    pop = announce_grid(excess, CANDIDATE_GRID, label="excedente máximo sobre la entrada (en ATRs)", file=log)

    # 2. La población DIFERENCIAL, que es la que un brazo puede mover.
    diff = differential_population(excess, CANDIDATE_GRID)
    print(
        "Población DIFERENCIAL — trades que cambian de comportamiento vs el "
        f"umbral vivo ({LIVE_MIN_EXCESS}×ATR):",
        file=log,
    )
    print(f"  {'umbral':>8} {'cambian':>9} {'población':>11}", file=log)
    for d in diff:
        marca = "" if d["share"] >= 0.05 or d["value"] == LIVE_MIN_EXCESS else "  <- bajo el 5% de la T13"
        print(f"  {d['value']:>8.2f} {d['n_changed']:>9} {100 * d['share']:>10.2f}%{marca}", file=log)

    # 3. El retorno por tramo: ¿los que se armarían tarde son los que pierden?
    tramos = []
    bordes = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
    for lo, hi in pairwise(bordes):
        sel = [r["ret_pts"] for r in rows if lo <= r["excess_atrs"] < hi]
        tramos.append(
            {"lo": lo, "hi": hi, "n": len(sel), "mean_ret_pts": statistics.fmean(sel) if sel else 0.0}
        )
    sel_neg = [r["ret_pts"] for r in rows if r["excess_atrs"] < 0]
    sel_top = [r["ret_pts"] for r in rows if r["excess_atrs"] >= bordes[-1]]
    print("\nRetorno medio por tramo de excedente (descriptivo, NO decide):", file=log)
    print(f"  {'tramo':>14} {'trades':>8} {'ret medio':>11}", file=log)
    print(
        f"  {'< 0.00':>14} {len(sel_neg):>8} {statistics.fmean(sel_neg) if sel_neg else 0.0:>10.2f} pts",
        file=log,
    )
    for t in tramos:
        etiqueta = f"{t['lo']:.2f}–{t['hi']:.2f}"
        print(f"  {etiqueta:>14} {t['n']:>8} {t['mean_ret_pts']:>10.2f} pts", file=log)
    print(
        f"  {'≥ 3.00':>14} {len(sel_top):>8} {statistics.fmean(sel_top) if sel_top else 0.0:>10.2f} pts",
        file=log,
    )

    s = sorted(excess)
    ctx = {
        "window": str(window),
        "universe": args.universe,
        "n_tickers": len(bars_by),
        "n_entries": len(entries),
        "n_trades": len(rows),
        "baseline": base_sum,
        "quantiles": {
            "p05": _pct(s, 0.05),
            "p25": _pct(s, 0.25),
            "p50": _pct(s, 0.50),
            "p75": _pct(s, 0.75),
            "p90": _pct(s, 0.90),
            "p95": _pct(s, 0.95),
            "max": s[-1],
            "min": s[0],
            "mean": statistics.fmean(s),
        },
        "cumulative": [
            {
                "value": a.value,
                "n_hit": a.n_hit,
                "share": a.share,
                "inert": a.inert,
                "underpowered": a.underpowered,
            }
            for a in pop.arms
        ],
        "differential": diff,
        "ret_by_band": tramos,
        "never_armed_share": sum(1 for m in excess if m <= LIVE_MIN_EXCESS) / len(excess),
    }
    if args.json:
        print(json.dumps(ctx, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
