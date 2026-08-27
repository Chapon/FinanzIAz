"""
Runner de STOP-VALUE — **Tarea 37**.

Pre-registro CONGELADO: ``docs/stop_value_prereg_t37_2026-08-19.md`` (``d6ba1b8``).
Enmienda CONGELADA:     ``docs/stop_value_enmienda_t37_2026-08-27.md`` (``106892b``).

La pregunta
-----------
La **T34** midió que la curva de CAGR es monótona creciente **hasta apagar el stop**
(2.01% al múltiplo vivo contra 9.52% sin stop, con mejor maxDD y mejor Sharpe) y
**no cabló nada**, porque un máximo en el borde separa *"calibrar un parámetro"* de
*"eliminar un guardrail"*. Su descomposición dejó la pista concreta: apagar **sólo el
stop duro** dejando el trailing en 2.0 da **9.17%** — recupera 7.16 de los 7.51 pp.

O sea que la pregunta que decide plata **no** es *"¿stop sí o no?"* sino:

    ¿El stop duro desde el precio de ENTRADA aporta algo por encima del trailing
    desde el MÁXIMO y del flip de señal — o sólo convierte caídas recuperables en
    pérdidas realizadas?

Qué agrega sobre la T34
-----------------------
1. **Rejilla 2-D 5×3** (stop duro × trailing, **desacoplados**). La T34 corrió un
   solo knob: ``trail_mult=None`` ⇒ el trailing seguía al stop.
2. **Inyección de ruina** (``analysis.ruin_injection``): el universo son 127
   **sobrevivientes**, el ambiente más benévolo posible para no tener stop. El
   survivorship no se corrige — se **acota**, y la cota es **C9**.
3. **C5′** (enmienda): la tolerancia de régimen **se computa**, el gate va sobre el
   agregado de stress con IC, y las ventanas individuales no pueden bloquear. Más
   **C5′-bis**: una ventana que resuelve un efecto negativo **sube la vara de C9**.
4. **Sanity de reproducción tri-estado** (tarea 48) contra tres celdas que la T34
   ya publicó con esta misma config.

Sin red, sin tocar ``finanzias.db``. No toca ``engine.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
import statistics
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.exit_replay import AtrParams, max_drawdown  # noqa: E402
from analysis.harness_config import (  # noqa: E402
    LIVE_MAX_POSITIONS,
    LIVE_UNIVERSE_FILE,
    REPRO_OK,
    WINDOW_REFRESH_2026_08_09,
    announce,
    artifact_window,
    reproduction_check,
)
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio  # noqa: E402
from analysis.risk_sizing import cagr, sharpe_annual  # noqa: E402
from analysis.ruin_injection import (  # noqa: E402
    DECIDING_SHAPE,
    bars_digest,
    event_summary,
    inject_ruin,
    seeds as ruin_seeds,
    ticker_years,
)
from analysis.scaleout_replay import CostModel, ScaleOutParams  # noqa: E402
from analysis.walkforward_power import (  # noqa: E402
    BULL_NORMAL,
    STRESS_REGIMES,
    block_delta_sign_stability,
    detectable_mean_effect,
    paired_block_bootstrap,
    regime_for_date,
)
from scripts.precompute_pit_signals import parse_universe_file  # noqa: E402
from scripts.run_rank_neutral_t39 import aligned_daily  # noqa: E402
from scripts.run_ranking_t21 import trade_overlap  # noqa: E402
from scripts.run_regime_power_t46 import _delta_samples, _summarise_samples  # noqa: E402
from scripts.run_stop_cal_replay_t26 import (  # noqa: E402
    NO_STOP,
    RANDOM_KEEP_PROB,
    _oracle_stop_filter,
    random_stop_filter,
    summarise,
)
from scripts.run_tp_cal_replay_t23 import buy_entries, load_bars_signals  # noqa: E402

CAP_DAYS = 250
EVAL_MODE = "touch"
FILL_MODE = "decision"
LIVE_GATES = True

# ── §5 — la rejilla 2-D CONGELADA ────────────────────────────────────────────
STOP_MULTS: tuple[float, ...] = (2.0, 3.0, 4.0, 6.0, NO_STOP)
TRAIL_MULTS: tuple[float, ...] = (2.0, 3.0, NO_STOP)
LIVE_STOP, LIVE_TRAIL = 2.0, 2.0

ORACLE_ARM = "ORACULO_STOP"
RANDOM_KEEP_ARM = "AZAR_MISMA_TASA"

# `off` en el eje del TRAILING se corre como control, pero NO es shipeable:
# dejaría la política de salida colgando de un solo mecanismo (§5).
TRAIL_OFF_NOT_SHIPPABLE = True

# ── §8 — los nueve criterios CONGELADOS ──────────────────────────────────────
KILL_MIN_DCAGR_OOS = 0.0100      # C1 — ≥ +1.00 pp fuera de muestra
KILL_DD_TOL = 0.0100             # C2 — maxDD ≤ base + 1.00 pp (in-sample Y OOS)
KILL_MIN_DSHARPE = 0.05          # C4
KILL_TAIL_TOL_PTS = 2.00         # C6 — Δ(peor trade) y Δ(p1) ≥ −2.00 pp
KILL_MIN_FOLD_AGREEMENT = 4      # C7 — mismo brazo en ≥4/5 folds

# C5′ (enmienda §3): la tolerancia MATERIAL se declara acá; la EFECTIVA es el
# máximo entre ésta y lo detectable, que sale de la muestra.
TOL_MATERIAL_PTS = 1.00
STRESS_NAMES = tuple(r.name for r in STRESS_REGIMES)
REGIMES = (BULL_NORMAL,) + STRESS_NAMES

# ── §3 — el barrido de ruina CONGELADO ───────────────────────────────────────
RUIN_GRID: tuple[tuple[float, tuple[float, ...]], ...] = (
    (0.50, (0.0, 0.005, 0.01, 0.026, 0.05, 0.10)),
    (0.70, (0.0, 0.0047, 0.01, 0.02)),
)
# C9 — los dos puntos que deciden: las tasas MEDIDAS dentro del propio universo.
C9_POINTS: tuple[tuple[float, float], ...] = ((0.026, 0.50), (0.0047, 0.70))
# C5′-bis (enmienda §3-bis) — el escalón siguiente, ya presente en la rejilla.
C9_ESCALATION: tuple[float, float] = (0.05, 0.50)
# §7.5 — la inyección tiene que hacer daño: el baseline cae ≥2.00 pp en r=10%.
SANITY_RUIN_HIGH_RATE = 0.10
SANITY_RUIN_MIN_DAMAGE = 0.0200

# ── §7 — sanity del instrumento ──────────────────────────────────────────────
SANITY_ORACLE_VS_RANDOM_CAGR = 0.0150
SANITY_ORACLE_VS_RANDOM_DD = 0.0500
SANITY_MIN_TRADE_DIFF = 0.10     # §7.4 — el desacople muerde

# §7.7 (enmienda §4) — reproducción tri-estado contra tres celdas de la T34.
REPRO_EXPECTED: dict[str, float] = {}     # se llena en _repro_targets()
REPRO_TOL = 0.0005

BOOT_BLOCK = 20
BOOT_RESAMPLES = 2000
BOOT_SEED = 12345

# ── §6 — walk-forward congelado (idéntico a la T34) ──────────────────────────
FOLDS: tuple[tuple[str, str, str], ...] = (
    ("2020-08-01", "2021-08-01", "2022-07-31"),
    ("2021-08-01", "2022-08-01", "2023-07-31"),
    ("2022-08-01", "2023-08-01", "2024-07-31"),
    ("2023-08-01", "2024-08-01", "2025-07-31"),
    ("2024-08-01", "2025-08-01", "2026-07-31"),
)


# ── Cache reanudable + presupuesto de tiempo ─────────────────────────────────
#
# El entorno donde corre esto mata los procesos en background al terminar cada
# llamada, así que la corrida NO puede ser un solo proceso largo. Cada simulación
# se memoiza en disco por una clave que describe COMPLETAMENTE su cómputo; el
# runner corre hasta agotar su presupuesto, sale limpio, y la próxima invocación
# retoma exactamente donde quedó. Es cache, no atajo: los números son los mismos
# que daría una corrida de un tirón (el harness es determinista).
CACHE_VERSION = "t37-v1"


class BudgetExhausted(Exception):
    """Se acabó el presupuesto de esta invocación. Volver a correr para seguir."""


class SimCache:
    def __init__(self, path: Path | None, budget_s: float | None):
        self.path = path
        self.deadline = (time.monotonic() + budget_s) if budget_s else None
        self.hits = 0
        self.misses = 0
        if self.path:
            self.path.mkdir(parents=True, exist_ok=True)

    def _file(self, tag: str) -> Path | None:
        if not self.path:
            return None
        h = hashlib.sha256(f"{CACHE_VERSION}|{tag}".encode("utf-8")).hexdigest()[:32]
        return self.path / f"{h}.pkl"

    def run(self, tag: str, fn):
        f = self._file(tag)
        if f is not None and f.exists():
            self.hits += 1
            return pickle.loads(f.read_bytes())
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise BudgetExhausted(tag)
        res = fn()
        self.misses += 1
        if f is not None:
            tmp = f.with_suffix(".tmp")
            tmp.write_bytes(pickle.dumps(res))
            tmp.replace(f)
        return res


_CACHE = SimCache(None, None)


def _sim(tag: str, entries, bars_by, sigs_by, **kw) -> PortfolioResult:
    return _CACHE.run(tag, lambda: simulate_portfolio(entries, bars_by, sigs_by, **kw))


# ── Brazos ───────────────────────────────────────────────────────────────────


def _m(mult: float) -> str:
    return "off" if mult >= NO_STOP else f"{mult:.1f}"


def arm_name(stop: float, trail: float) -> str:
    return f"s{_m(stop)}_t{_m(trail)}"


BASELINE_ARM = arm_name(LIVE_STOP, LIVE_TRAIL)


def grid_cells() -> list[tuple[float, float]]:
    return [(s, t) for s in STOP_MULTS for t in TRAIL_MULTS]


def arm_params(stop: float, trail: float) -> dict:
    """kwargs del brazo. ``trail_mult`` SIEMPRE explícito: dejarlo en ``None``
    haría que el trailing siga al stop, que es exactamente el acople que esta
    tarea existe para romper."""
    return {
        "atr_p": AtrParams(stop_mult=stop, trail_mult=trail),
        "eval_mode": EVAL_MODE, "fill_mode": FILL_MODE, "live_gates": LIVE_GATES,
    }


def build_arms() -> dict[str, dict]:
    """Los 15 de la rejilla + los 2 de sanity."""
    arms = {arm_name(s, t): arm_params(s, t) for s, t in grid_cells()}
    base = {"atr_p": AtrParams(stop_mult=LIVE_STOP, trail_mult=LIVE_TRAIL),
            "eval_mode": EVAL_MODE, "fill_mode": FILL_MODE, "live_gates": LIVE_GATES}
    arms[ORACLE_ARM] = {**base, "stop_filter": _oracle_stop_filter}
    arms[RANDOM_KEEP_ARM] = {**base, "stop_filter": random_stop_filter(RANDOM_KEEP_PROB)}
    return arms


def is_shippable(stop: float, trail: float) -> bool:
    """El `off` del stop es candidato legítimo; el del trailing NO (§5)."""
    return not (TRAIL_OFF_NOT_SHIPPABLE and trail >= NO_STOP)


def _repro_targets() -> dict[str, float]:
    """§7.7 — las tres celdas que la T34 publicó con esta misma config."""
    return {
        arm_name(2.0, 2.0): 0.0201,        # `touch_2.0` — el BASELINE, lo vivo
        arm_name(NO_STOP, 2.0): 0.0917,    # `D1` (T34 §4) — stop off, trail 2.0
        arm_name(NO_STOP, NO_STOP): 0.0952,  # `touch_off` — las dos apagadas
    }


# ── Cola (C6) y descriptivo del trailing (§5) ────────────────────────────────


def _trade_rets_pts(res: PortfolioResult) -> list[float]:
    return sorted(100.0 * t.ret for t in res.trades)


def tail_stats(res: PortfolioResult) -> dict:
    rets = _trade_rets_pts(res)
    if not rets:
        return {"worst": 0.0, "p1": 0.0, "p5": 0.0, "n": 0}
    def _q(q: float) -> float:
        return rets[max(0, min(len(rets) - 1, int(q * len(rets))))]
    return {"worst": rets[0], "p1": _q(0.01), "p5": _q(0.05), "n": len(rets)}


def never_armed_trailing(res: PortfolioResult, bars_by: dict,
                         trail_min_excess_atrs: float = 1.0,
                         period: int = 14) -> dict:
    """§2c/§5 — fracción de trades cuyo HWM nunca superó entrada + 1×ATR.

    Es **la población que quedaría con una sola barrera** si se apaga el stop
    duro: el punto débil estructural del candidato. **Descriptivo, no decide.**

    Aproximación declarada: ``avg_cost`` ≈ close de la barra de entrada (sin
    costos ni scale-out), que es la información que ``Trade`` expone.
    """
    from analysis.exit_replay import atr_series

    atr_cache: dict[str, list] = {}
    idx_cache: dict[str, dict[str, int]] = {}
    n_never = 0
    rets_never: list[float] = []
    rets_armed: list[float] = []
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
        entry_close = bars[i0][4]
        if atr0 is None or not math.isfinite(atr0) or atr0 <= 0:
            continue
        threshold = entry_close + trail_min_excess_atrs * atr0
        hwm = max(b[2] for b in bars[i0:i1 + 1])
        if hwm > threshold:
            rets_armed.append(100.0 * t.ret)
        else:
            n_never += 1
            rets_never.append(100.0 * t.ret)
    total = n_never + len(rets_armed)
    return {
        "n_never_armed": n_never, "n_total": total,
        "share": (n_never / total) if total else 0.0,
        "mean_ret_never_pts": statistics.fmean(rets_never) if rets_never else 0.0,
        "mean_ret_armed_pts": statistics.fmean(rets_armed) if rets_armed else 0.0,
    }


# ── C5′ + C5′-bis (enmienda §3) ──────────────────────────────────────────────


def per_trade_pts(res: PortfolioResult) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {r: [] for r in REGIMES}
    for t in res.trades:
        out.setdefault(t.regime, []).append(100.0 * t.ret)
    return out


def regime_criterion(base: PortfolioResult, cand: PortfolioResult, *,
                     n_resamples: int, seed: int) -> dict:
    """C5′: tolerancia computada + gate sobre el AGREGADO de stress con IC.

    Falla **sólo** si el IC95% del Δ del agregado está enteramente por debajo de
    ``−tol``. Las ventanas individuales **no pueden bloquear** (46 §4.3).

    **C5′-bis** (enmienda §3-bis): además marca si alguna ventana de stress
    muestra un Δ **negativo** cuya magnitud **alcanza su propio piso de
    resolución**. Eso no bloquea acá — **sube la vara de C9**.
    """
    pb, pc = per_trade_pts(base), per_trade_pts(cand)
    pooled_b = [v for r in STRESS_NAMES for v in pb.get(r, [])]
    pooled_c = [v for r in STRESS_NAMES for v in pc.get(r, [])]

    windows: dict[str, dict] = {}
    for r in REGIMES + ("stress_POOLED",):
        xs = pooled_b if r == "stress_POOLED" else pb.get(r, [])
        ys = pooled_c if r == "stress_POOLED" else pc.get(r, [])
        n = len(xs)
        sd = statistics.stdev(xs) if n > 1 else 0.0
        delta = ((statistics.fmean(ys) if ys else 0.0)
                 - (statistics.fmean(xs) if xs else 0.0))
        stab = None
        if xs and ys:
            stab = _summarise_samples(
                _delta_samples(xs, ys, n_resamples=n_resamples, seed=seed), delta)
        det = detectable_mean_effect(sd, n) if n > 1 else None
        windows[r] = {
            "n_base": n, "n_cand": len(ys), "sd_pts": sd, "delta_pts": delta,
            "detectable": det, "stability": stab,
            # C5′-bis: ¿esta ventana RESUELVE un efecto negativo?
            "resolves_negative": bool(
                delta < 0 and det is not None and math.isfinite(det)
                and abs(delta) >= det),
        }

    pooled = windows["stress_POOLED"]
    det = pooled["detectable"]
    usable_det = det if (det is not None and math.isfinite(det)) else 0.0
    tol = max(TOL_MATERIAL_PTS, usable_det)
    ci_high = pooled["stability"]["ci_high"] if pooled["stability"] else None
    passes = not (ci_high is not None and ci_high < -tol)

    escalate = [r for r in STRESS_NAMES if windows[r]["resolves_negative"]]
    return {
        "tolerance_pts": tol, "material_pts": TOL_MATERIAL_PTS, "detectable_pts": det,
        "pooled_delta_pts": pooled["delta_pts"], "pooled_ci_high": ci_high,
        "pooled_ci_low": (pooled["stability"]["ci_low"] if pooled["stability"] else None),
        "passes": passes, "windows": windows,
        "escalate_c9": bool(escalate), "escalate_windows": escalate,
    }


# ── §6 — walk-forward de la selección sobre la rejilla 2-D ───────────────────


def entry_date_of(bars_by: dict, ticker: str, idx: int) -> str:
    return bars_by[ticker][idx][0]


def entries_between(entries, bars_by, lo: str | None, hi: str | None):
    out = []
    for tk, idx in entries:
        bars = bars_by.get(tk)
        if not bars or idx >= len(bars):
            continue
        d = bars[idx][0]
        if lo is not None and d < lo:
            continue
        if hi is not None and d > hi:
            continue
        out.append((tk, idx))
    return out


def _prev_day(iso10: str) -> str:
    return date.fromordinal(date.fromisoformat(iso10).toordinal() - 1).isoformat()


def walk_forward(entries, bars_by, sigs_by, common: dict, *, tag: str = "",
                 log=sys.stdout) -> dict:
    """Elige la CELDA (stop, trail) en cada train y la cobra en el test siguiente."""
    cells = grid_cells()
    picks: list[tuple[float, float]] = []
    per_fold: list[dict] = []
    proc_curve: list[tuple[str, float]] = []
    base_curve: list[tuple[str, float]] = []
    proc_eq = base_eq = float(common["initial_capital"])

    for fi, (train_end, test_lo, test_hi) in enumerate(FOLDS, 1):
        train = entries_between(entries, bars_by, None, _prev_day(train_end))
        test = entries_between(entries, bars_by, test_lo, test_hi)
        print(f"    fold {fi}/{len(FOLDS)} — train {len(train)} · test {len(test)} …",
              file=log, flush=True)

        train_cagr: dict[tuple[float, float], float] = {}
        for s, t in cells:
            r = _sim(f"wf{fi}|train|{arm_name(s, t)}|{tag}", train, bars_by, sigs_by,
                     **arm_params(s, t), **common)
            train_cagr[(s, t)] = cagr(r.equity_curve)
        pick = max(cells, key=lambda st: train_cagr[st])
        picks.append(pick)

        r_proc = _sim(f"wf{fi}|test|{arm_name(*pick)}|eq{proc_eq:.6f}|{tag}",
                      test, bars_by, sigs_by, **arm_params(*pick),
                      **{**common, "initial_capital": proc_eq})
        r_base = _sim(f"wf{fi}|test|{BASELINE_ARM}|eq{base_eq:.6f}|{tag}",
                      test, bars_by, sigs_by, **arm_params(LIVE_STOP, LIVE_TRAIL),
                      **{**common, "initial_capital": base_eq})
        proc_curve.extend(r_proc.equity_curve)
        base_curve.extend(r_base.equity_curve)
        proc_eq, base_eq = r_proc.final_equity, r_base.final_equity

        per_fold.append({
            "train_end": train_end, "test": f"{test_lo}..{test_hi}",
            "n_train": len(train), "n_test": len(test),
            "pick": arm_name(*pick),
            "train_cagr": {arm_name(s, t): train_cagr[(s, t)] for s, t in cells},
            "oos_cagr_proc": cagr(r_proc.equity_curve),
            "oos_cagr_base": cagr(r_base.equity_curve),
        })

    counts: dict[tuple[float, float], int] = {}
    for p in picks:
        counts[p] = counts.get(p, 0) + 1
    star = max(counts, key=lambda st: (counts[st], -st[0], -st[1]))
    return {
        "per_fold": per_fold, "picks": [arm_name(*p) for p in picks],
        "star": star, "star_arm": arm_name(*star), "agreement": counts[star],
        "proc": {"cagr": cagr(proc_curve), "max_dd": max_drawdown(proc_curve),
                 "final_equity": proc_eq},
        "base": {"cagr": cagr(base_curve), "max_dd": max_drawdown(base_curve),
                 "final_equity": base_eq},
    }


# ── §3 — el barrido de ruina (C9) ────────────────────────────────────────────


def ruin_sweep(entries, bars_by, sigs_by, common: dict, candidate: tuple[float, float],
               *, points: list[tuple[float, float]], shape: str = DECIDING_SHAPE,
               n_seeds_used: int | None = None, tag: str = "",
               log=sys.stdout) -> dict:
    """Corre baseline y candidato sobre mundos con ruina inyectada.

    ``points`` = lista de ``(rate, depth)``. Las series se generan **una vez por
    (rate, depth, shape, seed)** y las ven los dos brazos: la comparación sigue
    siendo pareada. **§7.6** se verifica acá mismo: se re-inyecta con la misma
    tripleta y se compara el hash, así el chequeo no depende de que la corrida
    llegue hasta el final.
    """
    all_seeds = ruin_seeds()
    if n_seeds_used:
        all_seeds = all_seeds[:n_seeds_used]
    base_p = arm_params(LIVE_STOP, LIVE_TRAIL)
    cand_p = arm_params(*candidate)
    ty = ticker_years(bars_by)
    out: dict[str, dict] = {}

    for rate, depth in points:
        key = f"d{depth:.2f}_r{rate:.4f}"
        per_seed: list[dict] = []
        use_seeds = (all_seeds[:1] if rate <= 0.0 else all_seeds)
        for sd in use_seeds:
            wtag = f"{shape}|d{depth:.4f}|r{rate:.6f}|s{sd}"
            world, events = inject_ruin(bars_by, rate=rate, depth=depth,
                                        shape=shape, seed=sd)
            digest = bars_digest(world)
            # §7.6 — determinismo del mundo, verificado en el momento.
            again, _ = inject_ruin(bars_by, rate=rate, depth=depth,
                                   shape=shape, seed=sd)
            digest_ok = bars_digest(again) == digest
            rb = _sim(f"ruin|{wtag}|base|{tag}", entries, world, sigs_by,
                      **base_p, **common)
            rc = _sim(f"ruin|{wtag}|cand{arm_name(*candidate)}|{tag}", entries,
                      world, sigs_by, **cand_p, **common)
            per_seed.append({
                "seed": sd, "digest": digest, "digest_ok": digest_ok,
                "base_cagr": cagr(rb.equity_curve),
                "cand_cagr": cagr(rc.equity_curve),
                "dcagr": cagr(rc.equity_curve) - cagr(rb.equity_curve),
                "base_dd": rb.max_dd, "cand_dd": rc.max_dd,
                "events": event_summary(events, len(bars_by), ty),
            })
        deltas = [p["dcagr"] for p in per_seed]
        out[key] = {
            "rate": rate, "depth": depth, "shape": shape, "per_seed": per_seed,
            "dcagr_mean": statistics.fmean(deltas),
            "dcagr_worst": min(deltas),
            "base_cagr_mean": statistics.fmean(p["base_cagr"] for p in per_seed),
            "cand_cagr_mean": statistics.fmean(p["cand_cagr"] for p in per_seed),
            "digests_ok": all(p["digest_ok"] for p in per_seed),
        }
        print(f"    ruina {shape} d={depth:.0%} r={rate:.2%} -> "
              f"D medio {100*out[key]['dcagr_mean']:+.2f} pp / "
              f"peor {100*out[key]['dcagr_worst']:+.2f} pp", file=log, flush=True)
    return out


def gradual_points() -> list[tuple[float, float]]:
    """Todos los puntos de la rejilla congelada del §3, en orden de tasa."""
    return [(r, d) for d, rates in RUIN_GRID for r in rates]


def breakeven_rate(sweep: dict, depth: float) -> float | None:
    """Primera tasa (interpolada) donde el Δ de la **peor** semilla cruza cero.

    Es el número que resume la tarea, pase lo que pase el veredicto (§11.6).
    ``None`` ⇒ el candidato aguanta toda la rejilla; ``0.0`` ⇒ ya pierde sin ruina.
    """
    pts = sorted(((v["rate"], v["dcagr_worst"]) for v in sweep.values()
                  if abs(v["depth"] - depth) < 1e-12), key=lambda x: x[0])
    if not pts or pts[0][1] < 0:
        return 0.0 if pts else None
    for (r0, d0), (r1, d1) in zip(pts, pts[1:]):
        if d1 < 0 <= d0:
            if d0 == d1:
                return r1
            return r0 + (r1 - r0) * (d0 / (d0 - d1))
    return None


def ruin_dose_response(sweep: dict, depth: float = 0.50) -> dict:
    """§7.5′ (enmienda 2) — la inyección hace daño y muestra dosis-respuesta.

    **(a) Daño** (sin cambios respecto del §7.5 congelado): el CAGR del baseline a
    ``r=10%`` cae al menos 2.00 pp respecto de ``r=0``.

    **(b) Dosis-respuesta con tolerancia COMPUTADA:** para cada par consecutivo de
    la rejilla, ``base_cagr(r_{i+1}) ≤ base_cagr(r_i) + 2·SE``, con ``SE`` el error
    estándar del Δ de las dos medias **sobre las semillas**.

    Por qué la tolerancia no se elige: a tasas bajas hay 6-13 eventos en todo el
    universo y el rango entre semillas de un mismo punto es de **3 a 5,4 pp**,
    mientras el paso que la monotonía estricta exigía detectar es de **0,2 pp** —
    19× por debajo de lo que la muestra resuelve. Un ascenso **dentro** del ruido
    de semilla del propio instrumento no es una violación de dosis-respuesta; uno
    que **sale** de esa banda sí lo es, y la corrida sigue siendo inválida.

    ``r=0`` es determinista por construcción (``n=1``, ``sd=0``): en el par que lo
    involucra la tolerancia sale enteramente del lado con semillas, que es lo
    correcto — no se le puede pedir dispersión a un punto sin sorteo.
    """
    pts = sorted(((v["rate"], v) for v in sweep.values()
                  if abs(v["depth"] - depth) < 1e-12), key=lambda x: x[0])
    if not pts:
        return {"steps": [], "dose_ok": False, "damage_pp": 0.0, "passes": False,
                "by_seed": []}

    def _stats(v) -> tuple[float, float, int]:
        xs = [ps["base_cagr"] for ps in v["per_seed"]]
        n = len(xs)
        mean = statistics.fmean(xs) if xs else 0.0
        sd = statistics.stdev(xs) if n > 1 else 0.0
        return mean, sd, n

    steps = []
    dose_ok = True
    for (r0, v0), (r1, v1) in zip(pts, pts[1:]):
        m0, sd0, n0 = _stats(v0)
        m1, sd1, n1 = _stats(v1)
        se = math.sqrt((sd0 ** 2 / n0 if n0 else 0.0) + (sd1 ** 2 / n1 if n1 else 0.0))
        tol = 2.0 * se
        ok = m1 <= m0 + tol
        dose_ok = dose_ok and ok
        steps.append({"r_from": r0, "r_to": r1, "cagr_from": m0, "cagr_to": m1,
                      "delta": m1 - m0, "tol": tol, "ok": ok})

    by_rate = {r: _stats(v)[0] for r, v in pts}
    damage = by_rate.get(0.0, 0.0) - by_rate.get(SANITY_RUIN_HIGH_RATE, 0.0)
    damage_ok = damage >= SANITY_RUIN_MIN_DAMAGE
    by_seed = [{"rate": r,
                "seeds": [ps["base_cagr"] for ps in v["per_seed"]],
                "spread": (max(ps["base_cagr"] for ps in v["per_seed"])
                           - min(ps["base_cagr"] for ps in v["per_seed"])
                           if v["per_seed"] else 0.0)}
               for r, v in pts]
    return {"steps": steps, "dose_ok": dose_ok, "damage_pp": damage,
            "damage_ok": damage_ok, "passes": bool(dose_ok and damage_ok),
            "by_seed": by_seed,
            "points": [(r, _stats(v)[0]) for r, v in pts]}


# ── §7 — sanity ──────────────────────────────────────────────────────────────


def evaluate_sanity(summaries: dict, results: dict, *, repro: dict,
                    window, ruin_mono: dict, ruin_digests_ok: bool) -> dict:
    orc, rnd = summaries[ORACLE_ARM], summaries[RANDOM_KEEP_ARM]
    s2 = SANITY_ORACLE_VS_RANDOM_CAGR <= (orc["cagr"] - rnd["cagr"])
    s2dd = (orc["max_dd"] - rnd["max_dd"]) <= -SANITY_ORACLE_VS_RANDOM_DD

    # §7.3 — control mecánico: `off` no dispara la barrera que apagó.
    mech: dict[str, bool] = {}
    for s, t in grid_cells():
        n = arm_name(s, t)
        mix = summaries[n]["exit_mix"]
        ok = True
        if s >= NO_STOP:
            ok = ok and mix.get("atr_stop", 0.0) == 0.0
        if t >= NO_STOP:
            ok = ok and mix.get("atr_trail", 0.0) == 0.0
        mech[n] = ok

    # §7.4 — el desacople muerde.
    diff = trade_overlap(results[BASELINE_ARM], results[arm_name(NO_STOP, 2.0)])

    # "NO APLICA" NO es OK: deja el sanity sin evaluar, y una corrida sin el §7.7
    # evaluado no puede dictar veredicto (por eso `wrong_universe` ⇒ smoke).
    repro_ok = all(st == REPRO_OK for st, _ in repro.values())
    accounting = all(v["accounting_ok"] for v in summaries.values())
    all_ok = bool(accounting and s2 and s2dd and all(mech.values())
                  and diff >= SANITY_MIN_TRADE_DIFF and ruin_mono["passes"]
                  and ruin_digests_ok and repro_ok)
    return {
        "accounting_ok": accounting,
        "oracle_vs_random_cagr": orc["cagr"] - rnd["cagr"], "s2_cagr": s2,
        "oracle_vs_random_dd": orc["max_dd"] - rnd["max_dd"], "s2_dd": s2dd,
        "mechanical": mech, "mechanical_ok": all(mech.values()),
        "trade_diff": diff, "s4_bite": diff >= SANITY_MIN_TRADE_DIFF,
        "ruin_monotone": ruin_mono, "ruin_digests_ok": ruin_digests_ok,
        "repro_states": {k: st for k, (st, _) in repro.items()},
        "repro_reasons": {k: why for k, (_, why) in repro.items()},
        "repro_ok": repro_ok, "window": str(window) if window else None,
        "all_ok": all_ok,
    }


# ── §8 — la regla de decisión: AND de los nueve ──────────────────────────────


def evaluate(summaries: dict, wf: dict, c5: dict, boot, tails: dict,
             sens5: dict | None, sens_close: dict | None, sweep: dict) -> dict:
    cand_arm = wf["star_arm"]
    base, cand = summaries[BASELINE_ARM], summaries[cand_arm]
    b_sh = base["sharpe"] if base["sharpe"] is not None else -1e9
    c_sh = cand["sharpe"] if cand["sharpe"] is not None else -1e9

    dcagr_oos = wf["proc"]["cagr"] - wf["base"]["cagr"]
    c1 = dcagr_oos >= KILL_MIN_DCAGR_OOS
    c2 = (cand["max_dd"] <= base["max_dd"] + KILL_DD_TOL
          and wf["proc"]["max_dd"] <= wf["base"]["max_dd"] + KILL_DD_TOL)
    c3 = boot is not None and boot.ci_low > 0.0
    c4 = (c_sh - b_sh) >= KILL_MIN_DSHARPE
    c5_ok = bool(c5["passes"])

    d_worst = tails[cand_arm]["worst"] - tails[BASELINE_ARM]["worst"]
    d_p1 = tails[cand_arm]["p1"] - tails[BASELINE_ARM]["p1"]
    c6 = d_worst >= -KILL_TAIL_TOL_PTS and d_p1 >= -KILL_TAIL_TOL_PTS

    c7 = wf["agreement"] >= KILL_MIN_FOLD_AGREEMENT
    c8a = bool(sens5) and sens5["dcagr"] >= 0.0
    c8b = bool(sens_close) and sens_close["dcagr"] >= 0.0
    c8 = c8a and c8b

    # C9 (+ C5′-bis): los dos puntos congelados, y el escalón si el régimen resolvió.
    c9_points = list(C9_POINTS)
    if c5.get("escalate_c9"):
        c9_points.append(C9_ESCALATION)
    c9_detail = []
    for rate, depth in c9_points:
        v = sweep.get(f"d{depth:.2f}_r{rate:.4f}")
        ok = v is not None and v["dcagr_worst"] >= 0.0
        c9_detail.append({"rate": rate, "depth": depth,
                          "dcagr_worst": (v["dcagr_worst"] if v else None), "ok": ok})
    c9 = all(d["ok"] for d in c9_detail)

    shippable = is_shippable(*wf["star"])
    ship = bool(c1 and c2 and c3 and c4 and c5_ok and c6 and c7 and c8 and c9
                and shippable)

    if wf["star_arm"] == BASELINE_ARM:
        outcome = ("NO-SHIP y resultado POSITIVO — el walk-forward elige el BASELINE: "
                   "el stop duro se gana su lugar y la serie 26→26b→34→37 queda "
                   "cerrada (§8, caso partido 3).")
    elif not shippable:
        outcome = ("NO-SHIP POR CONSTRUCCIÓN — el walk-forward elige un brazo con el "
                   "TRAILING apagado, que el §5 declaró no shipeable. Es evidencia de "
                   "que el instrumento premia no tener barreras, lo que refuerza la "
                   "lectura de survivorship (§8, caso partido 4).")
    elif ship:
        outcome = (f"SHIP — se cabla `atr_trail_mult` (y `atr_hard_stop_enabled` si "
                   f"corresponde) con el valor de {wf['star_arm']}. Es un cambio de "
                   f"política de salida EN VIVO y código nuevo en el gate (§9).")
    elif c1 and c2 and c3 and c4 and c5_ok and c6 and c7 and c8 and not c9:
        outcome = ("NO-SHIP por C9 — y es el resultado MÁS INFORMATIVO posible: "
                   "significa que la ventaja del candidato ES el survivorship "
                   "(§8, caso partido 1).")
    elif c1 and (not c2 or not c6):
        outcome = ("NO-SHIP — C1 pasa pero falla C2 o C6: más retorno con más drawdown "
                   "o peor cola en el knob de riesgo es asumir riesgo, no mejorar la "
                   "regla (§8, caso partido 2).")
    else:
        outcome = "NO-SHIP — no pasa el AND de los nueve criterios."

    return {
        "candidate_arm": cand_arm, "shippable": shippable,
        "dcagr_oos": dcagr_oos, "dcagr_insample": cand["cagr"] - base["cagr"],
        "dd_delta_insample": cand["max_dd"] - base["max_dd"],
        "dd_delta_oos": wf["proc"]["max_dd"] - wf["base"]["max_dd"],
        "sharpe_delta": c_sh - b_sh,
        "tail_worst_delta": d_worst, "tail_p1_delta": d_p1,
        "c1_cagr_oos": c1, "c2_maxdd": c2, "c3_boot": c3, "c4_sharpe": c4,
        "c5_regime": c5_ok, "c6_tail": c6, "c7_folds": c7,
        "c8_spec": c8, "c8a_slots5": c8a, "c8b_close": c8b,
        "c9_ruin": c9, "c9_detail": c9_detail,
        "c9_escalated": bool(c5.get("escalate_c9")),
        "ship": ship, "outcome": outcome,
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def _run(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="STOP-VALUE — Tarea 37")
    p.add_argument("--universe", default=LIVE_UNIVERSE_FILE)
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=CAP_DAYS)
    p.add_argument("--max-positions", type=int, default=LIVE_MAX_POSITIONS)
    p.add_argument("--sens-max-positions", type=int, default=5)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--resamples", type=int, default=BOOT_RESAMPLES)
    p.add_argument("--cache-dir", default=None,
                   help="directorio de memoización (permite reanudar la corrida)")
    p.add_argument("--budget-seconds", type=float, default=None,
                   help="corre hasta agotar el presupuesto y sale limpio; "
                        "volver a invocar retoma donde quedó")
    p.add_argument("--ruin-seeds", type=int, default=None,
                   help="usar menos de 3 semillas (SMOKE — invalida C9)")
    p.add_argument("--no-walkforward", action="store_true",
                   help="SMOKE: saltea el §6 y usa el mejor in-sample (invalida C1/C7)")
    p.add_argument("--no-ruin", action="store_true",
                   help="SMOKE: saltea el §3 (invalida C9 y el sanity §7.5)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    log = sys.stderr if args.json else sys.stdout
    # §4 — la población está CONGELADA. Correr sobre otro universo es cañería,
    # no veredicto: y además invalida el §7.7, cuyas anclas se midieron sobre el
    # universo vivo (ver `repro` más abajo).
    wrong_universe = args.universe != LIVE_UNIVERSE_FILE
    smoke = bool(args.no_walkforward or args.no_ruin or args.ruin_seeds
                 or wrong_universe)

    global _CACHE
    _CACHE = SimCache(Path(args.cache_dir) if args.cache_dir else None,
                      args.budget_seconds)

    tickers = parse_universe_file(_HERE.parent / args.universe)
    # Los artefactos PIT se releen en cada invocación y la corrida es reanudable,
    # así que se memoiza la CARGA igual que las simulaciones. Mismo principio:
    # la clave describe el cómputo entero, y no cambia ningún número.
    # La clave incluye la marca de tiempo de los artefactos: si se refrescan los
    # parquet o las señales PIT, el cache NO se reusa. Sin esto el cache
    # sobreviviría a un cambio de muestra, que es el defecto de reproducibilidad
    # que la tarea 48 desarmó para los veredictos (y la 52 para las anclas).
    def _art_stamp() -> str:
        out = []
        for d in ("data/parquet", "data/pit_signals"):
            root = _HERE.parent / d
            newest = max((f.stat().st_mtime_ns for f in root.glob("*")
                          if f.is_file()), default=0)
            out.append(f"{d}:{newest}")
        return "|".join(out)

    _load_tag = (f"load|{args.universe}|{args.period}|w{args.warmup}"
                 f"|t{len(tickers)}|{_art_stamp()}")
    bars_by, sigs_by, missing = _CACHE.run(
        _load_tag, lambda: load_bars_signals(tickers, args.period, args.warmup))
    if not bars_by:
        print("Sin datos PIT: corré scripts/precompute_pit_signals.py primero.",
              file=sys.stderr)
        return 1
    if missing:
        print(f"AVISO: {len(missing)} tickers sin señal/barras: {', '.join(missing)}",
              file=sys.stderr)
    entries = buy_entries(bars_by, sigs_by, args.warmup)
    if not entries:
        print("Sin entradas BUY.", file=sys.stderr)
        return 1

    window = artifact_window(bars_by)
    # El tag entra en TODA clave de cache: si cambia la muestra o la config, el
    # cache no se reusa. Un cache que sobrevive a un cambio de config es un bug
    # de reproducibilidad, no una optimización.
    run_tag = (f"{window}|u{args.universe}|n{len(bars_by)}|e{len(entries)}"
               f"|mp{args.max_positions}|cap{args.cap_days}|cap${args.capital:.2f}"
               f"|{EVAL_MODE}|{FILL_MODE}|g{int(LIVE_GATES)}")
    announce(args.max_positions, args.universe, len(bars_by), window=window,
             eval_mode=EVAL_MODE, fill_mode=FILL_MODE, live_gates=LIVE_GATES, file=log)
    print(f"Tickers: {len(bars_by)} · entradas analyze BUY: {len(entries)} · "
          f"ticker-años: {ticker_years(bars_by):.0f}", file=log)
    print(f"Rejilla 2-D: stop {[_m(s) for s in STOP_MULTS]} × "
          f"trail {[_m(t) for t in TRAIL_MULTS]} = {len(grid_cells())} brazos", file=log)
    print(f"BASELINE = {BASELINE_ARM} (la config viva, un solo knob)\n", file=log)
    if smoke:
        print("*** SMOKE — la corrida NO puede dictar veredicto ***\n", file=log)

    common = dict(
        max_positions=args.max_positions, initial_capital=args.capital,
        cap_days=args.cap_days, so_params=ScaleOutParams(), costs=CostModel(),
        regime_of=regime_for_date, allow_reentry_while_open=False,
    )

    # 1. La rejilla + los dos brazos de sanity.
    arms = build_arms()
    results: dict[str, PortfolioResult] = {}
    for i, (n, kw) in enumerate(arms.items(), 1):
        print(f"  [{args.max_positions} slots] {i}/{len(arms)} {n} …",
              file=log, flush=True)
        results[n] = _sim(f"grid|{n}|{run_tag}", entries, bars_by, sigs_by,
                          **kw, **common)
    summaries = {n: summarise(r) for n, r in results.items()}
    tails = {n: tail_stats(r) for n, r in results.items()}

    # §7.7 — reproducción tri-estado contra las tres celdas de la T34.
    #
    # `reproduction_check` es consciente de la VENTANA pero no de la POBLACIÓN,
    # así que sobre otro universo acusaría "cambió la cañería" por algo que no es
    # la cañería — el mismo error de categoría que la tarea 48 arregló para el
    # calendario. Acá se lo evita en el único lugar donde se puede: la referencia
    # se midió sobre el universo vivo, así que fuera de él el chequeo NO APLICA
    # (y la corrida ya es smoke por el §4).
    if wrong_universe:
        repro = {n: ("NO APLICA",
                     f"las anclas de la T34 se midieron sobre {LIVE_UNIVERSE_FILE}; "
                     f"esta corrida usa {args.universe}")
                 for n in _repro_targets()}
    else:
        repro = {n: reproduction_check(summaries[n]["cagr"], exp, tol=REPRO_TOL,
                                       current=window,
                                       measured_on=WINDOW_REFRESH_2026_08_09)
                 for n, exp in _repro_targets().items()}

    # 2. §6 — walk-forward de la selección.
    if args.no_walkforward:
        cells = [c for c in grid_cells()]
        star = max(cells, key=lambda st: summaries[arm_name(*st)]["cagr"])
        wf = {"per_fold": [], "picks": [], "star": star, "star_arm": arm_name(*star),
              "agreement": 0,
              "proc": {"cagr": summaries[arm_name(*star)]["cagr"],
                       "max_dd": summaries[arm_name(*star)]["max_dd"],
                       "final_equity": 0.0},
              "base": {"cagr": summaries[BASELINE_ARM]["cagr"],
                       "max_dd": summaries[BASELINE_ARM]["max_dd"],
                       "final_equity": 0.0},
              "SMOKE": True}
    else:
        print("  §6 — walk-forward de la selección …", file=log, flush=True)
        wf = walk_forward(entries, bars_by, sigs_by, common, tag=run_tag, log=log)
    cand_arm = wf["star_arm"]
    cand_cell = wf["star"]
    print(f"\n  CANDIDATO = {cand_arm} ({wf['agreement']}/{len(FOLDS)} folds)\n",
          file=log, flush=True)

    # 3. C3 — bootstrap pareado sobre la serie diaria completa.
    daily = aligned_daily(results, [BASELINE_ARM, cand_arm])
    boot = (paired_block_bootstrap([r for _, r in daily[BASELINE_ARM]],
                                   [r for _, r in daily[cand_arm]],
                                   block=BOOT_BLOCK, n_resamples=args.resamples,
                                   seed=BOOT_SEED)
            if cand_arm != BASELINE_ARM else None)

    # 4. C5′ + C5′-bis.
    c5 = (regime_criterion(results[BASELINE_ARM], results[cand_arm],
                           n_resamples=args.resamples, seed=BOOT_SEED)
          if cand_arm != BASELINE_ARM else
          {"passes": True, "tolerance_pts": TOL_MATERIAL_PTS, "material_pts":
           TOL_MATERIAL_PTS, "detectable_pts": None, "pooled_delta_pts": 0.0,
           "pooled_ci_low": None, "pooled_ci_high": None, "windows": {},
           "escalate_c9": False, "escalate_windows": []})

    # Descriptivo §2c/§5 — la población que quedaría con una sola barrera.
    trailing_gap = {n: never_armed_trailing(results[n], bars_by)
                    for n in (BASELINE_ARM, cand_arm)}

    # 5. C8 — especificación: 5 slots y modo `close`.
    sens5 = sens_close = None
    if cand_arm != BASELINE_ARM:
        print(f"  C8(a) — sensibilidad a {args.sens_max_positions} slots …",
              file=log, flush=True)
        s_common = dict(common, max_positions=args.sens_max_positions)
        sb = _sim(f"c8a|{BASELINE_ARM}|mp{args.sens_max_positions}|{run_tag}",
                  entries, bars_by, sigs_by,
                  **arm_params(LIVE_STOP, LIVE_TRAIL), **s_common)
        sc = _sim(f"c8a|{cand_arm}|mp{args.sens_max_positions}|{run_tag}",
                  entries, bars_by, sigs_by, **arm_params(*cand_cell), **s_common)
        sens5 = {"max_positions": args.sens_max_positions,
                 "base_cagr": cagr(sb.equity_curve), "cand_cagr": cagr(sc.equity_curve),
                 "dcagr": cagr(sc.equity_curve) - cagr(sb.equity_curve)}

        print("  C8(b) — sensibilidad en modo `close` …", file=log, flush=True)
        def _close(st):
            kw = arm_params(*st)
            return {**kw, "eval_mode": "close"}
        cb = _sim(f"c8b|{BASELINE_ARM}|close|{run_tag}", entries, bars_by, sigs_by,
                  **_close((LIVE_STOP, LIVE_TRAIL)), **common)
        cc = _sim(f"c8b|{cand_arm}|close|{run_tag}", entries, bars_by, sigs_by,
                  **_close(cand_cell), **common)
        sens_close = {"base_cagr": cagr(cb.equity_curve),
                      "cand_cagr": cagr(cc.equity_curve),
                      "dcagr": cagr(cc.equity_curve) - cagr(cb.equity_curve)}

    # 6. §3 — el barrido de ruina (C9) + la sensibilidad de forma.
    sweep: dict = {}
    sweep_gap: dict = {}
    ruin_mono = {"steps": [], "dose_ok": False, "damage_pp": 0.0,
                 "damage_ok": False, "passes": False, "by_seed": [], "points": []}
    digests_ok = True
    if not args.no_ruin and cand_arm != BASELINE_ARM:
        print("  §3 — barrido de ruina (`gradual`, la que DECIDE) …",
              file=log, flush=True)
        sweep = ruin_sweep(entries, bars_by, sigs_by, common, cand_cell,
                           points=gradual_points(), shape="gradual",
                           n_seeds_used=args.ruin_seeds, tag=run_tag, log=log)
        ruin_mono = ruin_dose_response(sweep, depth=0.50)
        digests_ok = all(v["digests_ok"] for v in sweep.values())

        print("  §3 — sensibilidad de FORMA (`gap`, NO decide) …", file=log, flush=True)
        sweep_gap = ruin_sweep(entries, bars_by, sigs_by, common, cand_cell,
                               points=list(C9_POINTS), shape="gap",
                               n_seeds_used=args.ruin_seeds, tag=run_tag, log=log)

    sanity = evaluate_sanity(summaries, results, repro=repro, window=window,
                             ruin_mono=ruin_mono, ruin_digests_ok=digests_ok)
    verdict = evaluate(summaries, wf, c5, boot, tails, sens5, sens_close, sweep)

    if smoke:
        verdict["ship"] = False
        verdict["outcome"] = ("SMOKE — corrida de cañería, sin veredicto. "
                              "Faltan legs congelados del pre-registro.")
    elif not sanity["all_ok"]:
        verdict["ship"] = False
        verdict["outcome"] = ("CORRIDA INVÁLIDA — falla un sanity del §7; no hay "
                              "veredicto. No se re-especifica nada para salvarla "
                              "(precedente T26, T34, 38).")

    ctx = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": len(bars_by), "n_entries": len(entries),
        "window": str(window) if window else None,
        "max_positions": args.max_positions, "cap_days": args.cap_days,
        "eval_mode": EVAL_MODE, "fill_mode": FILL_MODE, "live_gates": LIVE_GATES,
        "smoke": smoke,
        "verdict": verdict, "sanity": sanity, "c5": c5, "walk_forward": wf,
        "tails": tails, "trailing_gap": trailing_gap,
        "sens5": sens5, "sens_close": sens_close,
        "ruin": sweep, "ruin_gap": sweep_gap,
        "breakeven": {f"d{d:.2f}": breakeven_rate(sweep, d) for d, _ in RUIN_GRID}
                     if sweep else {},
        "boot": ({"observed": boot.observed, "ci_low": boot.ci_low,
                  "ci_high": boot.ci_high, "p_value": boot.p_value} if boot else None),
    }
    if args.json:
        print(json.dumps({"context": ctx, "summaries": summaries},
                         ensure_ascii=False, indent=2, default=str))
        return 0

    _report(summaries, tails, ctx)
    print(f"cache: {_CACHE.hits} reusadas · {_CACHE.misses} nuevas", file=log)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Envoltorio del presupuesto: la corrida es REANUDABLE.

    Con ``--cache-dir`` cada simulación queda memoizada por una clave que
    describe su cómputo entero, así que agotar el presupuesto no pierde trabajo:
    la próxima invocación con los mismos argumentos retoma donde quedó y produce
    exactamente los mismos números (el harness es determinista).
    """
    try:
        return _run(argv)
    except BudgetExhausted as exc:
        print(f"\n*** PRESUPUESTO AGOTADO — faltaba: {exc} ***", file=sys.stderr)
        print(f"    cache: {_CACHE.hits} reusadas · {_CACHE.misses} nuevas en "
              f"esta invocación.", file=sys.stderr)
        print("    Volvé a invocar con los MISMOS argumentos para retomar.",
              file=sys.stderr)
        return 2


# ── Reporte ──────────────────────────────────────────────────────────────────


def _pp(x: float | None, w: int = 8, signed: bool = False) -> str:
    if x is None:
        return "—".rjust(w)
    return (f"{100*x:+.2f}%" if signed else f"{100*x:.2f}%").rjust(w)


def _report(summaries: dict, tails: dict, ctx: dict) -> None:
    v, s, wf, c5 = ctx["verdict"], ctx["sanity"], ctx["walk_forward"], ctx["c5"]
    W = 78
    print("\n" + "=" * W)
    print("STOP-VALUE — Tarea 37 · ¿el stop duro aporta sobre el trailing?")
    print("=" * W)
    print(f"Ventana: {ctx['window']} · {ctx['n_tickers']} tickers · "
          f"{ctx['n_entries']} entradas · {ctx['max_positions']} slots")
    print(f"\nVEREDICTO: {'SHIP' if v['ship'] else 'NO-SHIP'} — {v['outcome']}\n")

    print("-" * W)
    print("LA REJILLA 2-D (stop duro × trailing)")
    print("-" * W)
    head = "stop \\ trail".ljust(14) + "".join(_m(t).rjust(11) for t in TRAIL_MULTS)
    print(head)
    for st in STOP_MULTS:
        row = _m(st).ljust(14)
        for tr in TRAIL_MULTS:
            n = arm_name(st, tr)
            mark = "*" if n == v["candidate_arm"] else (
                "#" if n == BASELINE_ARM else " ")
            row += f"{100*summaries[n]['cagr']:9.2f}%{mark}"
        print(row)
    print("  # = BASELINE (lo vivo)   * = CANDIDATO (lo elige el walk-forward)")

    print(f"\n{'brazo':<14}{'CAGR':>9}{'Sharpe':>8}{'maxDD':>9}"
          f"{'%stop':>7}{'%trail':>8}{'peor':>8}{'p1':>8}{'tomadas':>9}")
    for n in [arm_name(*c) for c in grid_cells()] + [ORACLE_ARM, RANDOM_KEEP_ARM]:
        d, t = summaries[n], tails[n]
        sh = f"{d['sharpe']:.2f}" if d["sharpe"] is not None else "—"
        print(f"{n:<14}{100*d['cagr']:8.2f}%{sh:>8}{100*d['max_dd']:8.1f}%"
              f"{100*d['exit_mix'].get('atr_stop',0):6.1f}%"
              f"{100*d['exit_mix'].get('atr_trail',0):7.1f}%"
              f"{t['worst']:7.1f}%{t['p1']:7.1f}%{d['n_taken']:9d}")

    if wf.get("per_fold"):
        print("\n" + "-" * W)
        print("§6 — WALK-FORWARD DE LA SELECCIÓN")
        print("-" * W)
        print(f"{'test OOS':<26}{'n_train':>9}{'n_test':>8}{'elige':>14}"
              f"{'OOS proc':>10}{'OOS base':>10}")
        for f in wf["per_fold"]:
            print(f"{f['test']:<26}{f['n_train']:9d}{f['n_test']:8d}{f['pick']:>14}"
                  f"{100*f['oos_cagr_proc']:9.2f}%{100*f['oos_cagr_base']:9.2f}%")
        print(f"\nCadena encadenada: {100*wf['proc']['cagr']:.2f}% de CAGR con "
              f"{100*wf['proc']['max_dd']:.1f}% de maxDD contra "
              f"{100*wf['base']['cagr']:.2f}% y {100*wf['base']['max_dd']:.1f}% "
              f"del baseline fijo.")
        print(f"Acuerdo: {wf['agreement']}/{len(FOLDS)} folds eligen "
              f"{wf['star_arm']}  ({' · '.join(wf['picks'])})")

    if c5.get("windows"):
        print("\n" + "-" * W)
        print("C5′ — RÉGIMEN CON POTENCIA (enmienda §3)")
        print("-" * W)
        det = c5["detectable_pts"]
        print(f"Tolerancia efectiva {c5['tolerance_pts']:.2f} pts = max(material "
              f"{c5['material_pts']:.2f} · detectable "
              f"{'—' if det is None else f'{det:.2f}'}) — computada, no elegida")
        print(f"\n{'ventana':<22}{'n':>7}{'σ':>8}{'detect.':>10}{'Δ pts':>9}"
              f"{'IC95%':>22}{'':>3}")
        for r in REGIMES + ("stress_POOLED",):
            w = c5["windows"].get(r)
            if not w:
                continue
            d2 = "—" if w["detectable"] is None else f"±{w['detectable']:.2f}"
            st = w["stability"]
            ci = (f"[{st['ci_low']:+.2f}, {st['ci_high']:+.2f}]" if st else "—")
            star = " ← GATE" if r == "stress_POOLED" else (
                " ← RESUELVE" if w["resolves_negative"] else "")
            print(f"{r:<22}{w['n_base']:7d}{w['sd_pts']:8.2f}{d2:>10}"
                  f"{w['delta_pts']:+9.2f}{ci:>22}{star}")
        print(f"\nC5′ {'PASA' if c5['passes'] else 'FALLA'} · "
              f"C5′-bis: {'ESCALA C9 a r=5.00%/d=50% (' + ', '.join(c5['escalate_windows']) + ')' if c5['escalate_c9'] else 'no escala — ninguna ventana resuelve un efecto negativo'}")

    if ctx.get("trailing_gap"):
        print("\n" + "-" * W)
        print("§2c — LA POBLACIÓN SIN TRAILING (descriptivo, no decide)")
        print("-" * W)
        print("Trades cuyo HWM nunca superó entrada + 1×ATR ⇒ sin trailing.")
        print("Aproximado: avg_cost ≈ close de la barra de entrada, sin costos.")
        for n, g in ctx["trailing_gap"].items():
            print(f"  {n:<14} {g['share']:6.1%} de {g['n_total']:5d} trades · "
                  f"ret medio sin trailing {g['mean_ret_never_pts']:+6.2f} pts "
                  f"vs con trailing {g['mean_ret_armed_pts']:+6.2f} pts")

    if ctx.get("ruin"):
        print("\n" + "-" * W)
        print("§3 / C9 — INYECCIÓN DE RUINA (el criterio central de la tarea)")
        print("-" * W)
        for depth, _ in RUIN_GRID:
            print(f"\n  profundidad −{depth:.0%}")
            print(f"  {'tasa/año':<12}{'base':>9}{'cand':>9}{'Δ medio':>10}"
                  f"{'Δ peor':>10}")
            for k in sorted(ctx["ruin"], key=lambda k: ctx["ruin"][k]["rate"]):
                r = ctx["ruin"][k]
                if abs(r["depth"] - depth) > 1e-12:
                    continue
                print(f"  {r['rate']:<11.2%}{100*r['base_cagr_mean']:8.2f}%"
                      f"{100*r['cand_cagr_mean']:8.2f}%"
                      f"{100*r['dcagr_mean']:+9.2f}{100*r['dcagr_worst']:+10.2f}")
            be = ctx["breakeven"].get(f"d{depth:.2f}")
            be_txt = ("aguanta toda la rejilla" if be is None
                      else f"{be:.2%}/año" if be > 0 else "ya pierde SIN ruina")
            print(f"  → TASA DE RUINA DE BREAKEVEN: {be_txt}"
                  f"   (medida en el universo: "
                  f"{'2,60' if depth == 0.50 else '0,47'}%/año)")
        rm = ctx["sanity"]["ruin_monotone"]
        if rm.get("by_seed"):
            print("\n  §7.5′(c) — el baseline por SEMILLA (descriptivo obligatorio):")
            print(f"    {'tasa':<10}{'semillas (CAGR %)':<34}{'rango':>8}")
            for row in rm["by_seed"]:
                xs = " · ".join(f"{100*x:6.3f}" for x in row["seeds"]) or "—"
                print(f"    {row['rate']:<10.2%}{xs:<34}{100*row['spread']:7.2f} pp")
            print(f"\n    {'paso':<18}{'Δ':>9}{'tol (2·SE)':>12}")
            for st in rm["steps"]:
                mark = "" if st["ok"] else "   ← SALE DE LA BANDA"
                print(f"    {st['r_from']:.2%}→{st['r_to']:.2%}".ljust(22)
                      + f"{100*st['delta']:+8.2f}{100*st['tol']:11.2f}{mark}")

        print("\n  C9 (peor de las semillas ≥ 0):")
        for d in ctx["verdict"]["c9_detail"]:
            dv = ("—" if d["dcagr_worst"] is None
                  else f"{100*d['dcagr_worst']:+.2f} pp")
            print(f"    r={d['rate']:.2%} / d={d['depth']:.0%} → {dv}  "
                  f"{'OK' if d['ok'] else 'FALLA'}")

    print("\n" + "-" * W)
    print("§7 — SANITY DEL INSTRUMENTO")
    print("-" * W)
    rows = [
        ("contabilidad ≤1e-6 en todos los brazos", s["accounting_ok"]),
        (f"oráculo vs azar igualado ΔCAGR ≥ +1.50 pp "
         f"({100*s['oracle_vs_random_cagr']:+.2f})", s["s2_cagr"]),
        (f"oráculo vs azar ΔmaxDD ≤ −5.00 pp "
         f"({100*s['oracle_vs_random_dd']:+.2f})", s["s2_dd"]),
        ("control mecánico: `off` no dispara su barrera", s["mechanical_ok"]),
        (f"el desacople muerde ≥10% ({s['trade_diff']:.1%})", s["s4_bite"]),
        (f"§7.5′ la ruina hace daño ({100*s['ruin_monotone']['damage_pp']:.2f} pp "
         f"a r=10%, umbral 2.00) y muestra dosis-respuesta dentro del ruido de "
         f"semilla", s["ruin_monotone"]["passes"]),
        ("la inyección es idéntica para todos los brazos (hash)",
         s["ruin_digests_ok"]),
    ]
    for label, ok in rows:
        print(f"  [{'OK ' if ok else 'FALLA'}] {label}")
    print("\n  §7.7 — reproducción tri-estado contra la T34 (tarea 48):")
    for n, st in s["repro_states"].items():
        print(f"    [{st:<13}] {n:<14} {s['repro_reasons'][n]}")

    print("\n" + "-" * W)
    print("§8 — LOS NUEVE CRITERIOS")
    print("-" * W)
    b = ctx["boot"]
    ci = (f"[{100*b['ci_low']:+.2f}, {100*b['ci_high']:+.2f}] p={b['p_value']:.3f}"
          if b else "—")
    checks = [
        ("C1", "ΔCAGR fuera de muestra ≥ +1.00 pp",
         f"{100*v['dcagr_oos']:+.2f} pp", v["c1_cagr_oos"]),
        ("C2", "maxDD in-sample Y OOS ≤ base +1.00 pp",
         f"{100*v['dd_delta_insample']:+.2f} / {100*v['dd_delta_oos']:+.2f} pp",
         v["c2_maxdd"]),
        ("C3", "bootstrap pareado, IC95% inferior > 0", ci, v["c3_boot"]),
        ("C4", "ΔSharpe ≥ +0.05", f"{v['sharpe_delta']:+.3f}", v["c4_sharpe"]),
        ("C5′", "régimen con potencia (agregado de stress, IC)",
         f"Δ {c5['pooled_delta_pts']:+.2f} pts vs tol {c5['tolerance_pts']:.2f}",
         v["c5_regime"]),
        ("C6", "cola: Δ(peor) y Δ(p1) ≥ −2.00 pp",
         f"{v['tail_worst_delta']:+.2f} / {v['tail_p1_delta']:+.2f} pp", v["c6_tail"]),
        ("C7", "mismo brazo en ≥4/5 folds",
         f"{wf['agreement']}/{len(FOLDS)}", v["c7_folds"]),
        ("C8", "signo a 5 slots Y en modo `close`",
         (f"{100*ctx['sens5']['dcagr']:+.2f} / "
          f"{100*ctx['sens_close']['dcagr']:+.2f} pp"
          if ctx.get("sens5") and ctx.get("sens_close") else "—"), v["c8_spec"]),
        ("C9", "ruina: Δ ≥ 0 en los puntos medidos"
         + (" + escalón (C5′-bis)" if v["c9_escalated"] else ""),
         " · ".join(f"{100*d['dcagr_worst']:+.2f}" if d["dcagr_worst"] is not None
                    else "—" for d in v["c9_detail"]), v["c9_ruin"]),
    ]
    for code, label, measured, ok in checks:
        print(f"  {code:<4}{'PASA ' if ok else 'FALLA'} {label:<44} {measured}")
    print("\n" + "=" * W)
    if ctx["smoke"]:
        print("SMOKE — sin veredicto.")
    print()


if __name__ == "__main__":
    raise SystemExit(main())
