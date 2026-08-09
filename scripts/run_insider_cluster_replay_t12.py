"""
Runner del replay del **detector de insider cluster buys (SEC Form 4)** — Tarea 12.

Pre-registro con kill-criteria CONGELADOS:
``docs/insider_cluster_prereg_t12_2026-07-24.md``. Hermano del harness de la T11b
(``run_anomaly_replay_t11b.py``): misma familia "de dónde salen los candidatos",
mismo simulador (``portfolio_sim``), mismo baseline Monte Carlo time-matched, mismo
descuento por selección múltiple (DSR/PBO) y mismos kill-criteria de cartera.

Insumos (offline en la corrida, precargados en la etapa ``backtest-runner``):
    1. artefacto de transacciones ``data/form345/insider_txs.json`` — lo genera
       ``scripts/ingest_form345.py`` a partir de los SEC Form 345 quarterly datasets.
    2. barras EOD del universo S&P 500 en el cache Parquet (``data/parquet/``).
    3. (modo ``analyze_flip``) señales PIT ``data/pit_signals/`` para el flip
       ``analyze SELL`` del exit — ver la nota del modo de exit más abajo.

    python scripts/ingest_form345.py --start 2016q1 --end 2026q2 \
        --universe data/sp500_universe.txt --dest data/form345
    python scripts/precompute_pit_signals.py --universe data/sp500_universe.txt   # solo analyze_flip
    python scripts/run_insider_cluster_replay_t12.py --signals-mode atr_only
    python scripts/run_insider_cluster_replay_t12.py --json

Qué hace (fiel al pre-registro)
-------------------------------
1. Carga las transacciones y arma los **eventos de cluster** de los 6 brazos
   ``(C, W)`` + seniority (§4.2) con ``analysis.insider_cluster``.
2. Mapea eventos → entradas contra el calendario de precios (``events_to_entries``):
   scan EOD en/ tras ``event_date`` → fill a la rueda siguiente (``entry = scan+1``),
   con el **refractario de 20 ruedas** aplicado ACÁ (§2: "ruedas" = días de trading)
   y desempate de slot por **monto total comprado en dólares** (§4.2).
3. **Gate de conteo mínimo (§3.3):** si el brazo primario arroja < 150 eventos en
   10y, PARA antes de correr el harness y escala el universo (small/mid) como
   follow-up, en vez de publicar un null sin poder.
4. Baseline = **Monte Carlo de K carteras aleatorias time-matched** por mes
   calendario al brazo primario, mismo capital y mismos exits.
5. Oráculo de validación (look-ahead deliberado): confirma que el harness detecta
   calidad de entrada (si no despega, el NO-SHIP no vale).
6. Mide CAGR, Sharpe anualizado y maxDD de cartera; descuenta por selección
   múltiple (PBO/DSR sobre los 6 brazos); aplica el kill-criteria (§6), con
   robustez de régimen como la prueba clave (§6.5) y LOTO (§6.6).

Nota sobre el modo de exit (§7 vs costo de cómputo)
---------------------------------------------------
§7 congeló el exit como la triple barrera completa **+ flip ``analyze SELL``**. Ese
flip necesita la señal PIT de ``analyze()`` para CADA ticker que la cartera pueda
tocar — y el baseline sortea de TODO el universo, así que serían señales PIT del
S&P 500 entero (~500 tickers), un precómputo XGBoost walk-forward de decenas de
horas (medido: ~5.5 h para 41 tickers). Por eso el modo es un flag explícito y
DOCUMENTADO en la corrida, no un cambio silencioso:

  * ``--signals-mode analyze_flip`` (default, fiel a §7): carga ``data/pit_signals/``
    por ticker; los que no tengan artefacto salen ATR-only. Reporta la cobertura.
  * ``--signals-mode atr_only``: exit ATR puro (stop/TP/trail) para brazos Y baseline
    — simétrico, justo, y coherente con el hallazgo de T7 (el SELL de ``analyze()``
    es peor que dejar actuar a los niveles ATR). Es una desviación de §7 que se
    documenta en el veredicto.

Sin red y sin tocar ``finanzias.db``: lee Parquet + JSON. No cambia ningún flag vivo.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import numpy as np  # noqa: E402

from analysis.exit_replay import AtrParams, Bar  # noqa: E402
from analysis.insider_cluster import (  # noqa: E402
    ClusterEvent,
    ClusterParams,
    InsiderTx,
    build_cluster_events,
)
from analysis.portfolio_sim import PortfolioResult, simulate_portfolio  # noqa: E402
from analysis.risk_sizing import cagr, precompute_oracle_returns, sharpe_annual  # noqa: E402
from analysis.scaleout_replay import CostModel, ScaleOutParams  # noqa: E402
from analysis.walkforward_power import (  # noqa: E402
    STRESS_REGIMES,
    _sharpe,
    _skew_kurt,
    deflated_sharpe_ratio,
    pbo_cscv,
    regime_for_date,
)
from scripts.precompute_pit_signals import _load_existing, _out_path  # noqa: E402

DEFAULT_UNIVERSE = "data/sp500_universe.txt"
DEFAULT_TXS = "data/form345/insider_txs.json"

# Brazos pre-registrados (§4.2): grilla (C, W) + una variante de seniority.
CANDIDATE_ARMS: dict[str, ClusterParams] = {
    "CLU_C3_W15": ClusterParams(min_insiders=3, window_days=15),          # PRIMARIO
    "CLU_C2_W15": ClusterParams(min_insiders=2, window_days=15),
    "CLU_C4_W15": ClusterParams(min_insiders=4, window_days=15),
    "CLU_C3_W10": ClusterParams(min_insiders=3, window_days=10),
    "CLU_C3_W30": ClusterParams(min_insiders=3, window_days=30),
    "CLU_C3_W15_senior": ClusterParams(min_insiders=3, window_days=15, require_officer=True),
}
PRIMARY_ARM = "CLU_C3_W15"
ORACLE_ARM = "V_oracle_entry"

# Kill-criteria (§6) — congelados (idénticos a T11b).
KILL_MIN_DCAGR = 0.02        # +2pp de CAGR vs la mediana del baseline random
KILL_RANDOM_PCTILE = 95      # CAGR y Sharpe > percentil 95 del baseline
KILL_DD_MULT = 1.5           # maxDD <= 1.5x la mediana del maxDD random
KILL_MIN_DSR = 0.5
KILL_MAX_PBO = 0.5
MIN_EVENTS_GATE = 150        # §3.3: < 150 eventos primarios → PARAR antes de correr


# ── Carga de transacciones + barras ──────────────────────────────────────────


def load_txs(path: Path) -> dict[str, list[InsiderTx]]:
    """Lee ``{ticker: [tx_dict, ...]}`` (artefacto del ingester) → InsiderTx por ticker."""
    blob = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[InsiderTx]] = {}
    for ticker, rows in blob.items():
        out[ticker.upper()] = [
            InsiderTx(
                issuer_ticker=ticker.upper(),
                filing_date=r.get("filing_date", ""),
                owner_cik=str(r.get("owner_cik", "")),
                trans_code=str(r.get("trans_code", "")).upper(),
                acq_disp=str(r.get("acq_disp", "")).upper(),
                shares=float(r.get("shares", float("nan"))),
                price=float(r.get("price", float("nan"))),
                accession=str(r.get("accession", "")),
                is_officer=bool(r.get("is_officer", False)),
                is_director=bool(r.get("is_director", False)),
            )
            for r in rows
        ]
    return out


def load_bars(tickers: list[str], period: str, signals_mode: str, warmup: int):
    """{ticker: [Bar]} + {ticker: {iso10: signal}}.

    En ``atr_only`` las señales quedan vacías (exit ATR puro). En ``analyze_flip``
    se cargan de ``data/pit_signals/`` cuando el artefacto existe y está completo;
    los tickers sin señal salen ATR-only (se reporta la cobertura)."""
    from data import parquet_cache

    bars_by: dict[str, list[Bar]] = {}
    sigs_by: dict[str, dict] = {}
    n_with_signals = 0
    for t in tickers:
        df = parquet_cache.read(t, period, "1d", None)
        if df is None or df.empty:
            continue
        df = df.sort_index()
        bars: list[Bar] = []
        for ts, row in df.iterrows():
            try:
                o, h, lo, c = (float(row["Open"]), float(row["High"]),
                               float(row["Low"]), float(row["Close"]))
            except (KeyError, TypeError, ValueError):
                continue
            if not all(math.isfinite(x) for x in (o, h, lo, c)) or c <= 0:
                continue
            bars.append((ts.strftime("%Y-%m-%d"), o, h, lo, c))
        if not bars:
            continue
        bars_by[t] = bars
        sigs_by[t] = {}
        if signals_mode == "analyze_flip":
            blob = _load_existing(_out_path(t, period, warmup))
            if blob and blob.get("complete"):
                sig = {d: sv[0] for d, sv in (blob.get("signals") or {}).items() if sv[0]}
                if sig:
                    sigs_by[t] = sig
                    n_with_signals += 1
    return bars_by, sigs_by, n_with_signals


# ── Eventos → entradas (refractario de 20 ruedas + ranking $) ─────────────────


def events_to_entries(
    events: list[ClusterEvent],
    bar_dates: list[str],
    *,
    warmup: int,
    cap_days: int,
) -> list[tuple[int, float]]:
    """Mapea los eventos de UN ticker a ``(entry_idx, total_dollars)`` contra su
    calendario de precios ``bar_dates`` (ISO, ordenado).

    Fiel al pre-registro (§2):
      * ``scan_idx`` = primera barra con fecha ≥ ``event_date`` (el primer EOD que
        ve el filing público — nunca mira el futuro). ``entry_idx = scan_idx + 1``
        (fill a la rueda siguiente, como el engine: scan post-close → fill próximo
        close). Para un ``event_date`` que cae en día hábil esto es ``i(event)+1``.
      * Dominio operable ``[warmup+1, n-2]`` (idéntico a ``operable_entries``: hay
        barra de fill y una posterior para el ciclo) — fail-safe por warmup y borde.
      * **Refractario de 20 ruedas**: tras aceptar una entrada, se saltea la
        siguiente del mismo ticker hasta ``cap_days`` ruedas después (espeja el
        "no reabrir mientras está en cartera" del engine).
    """
    n = len(bar_dates)
    lo_idx, hi_idx = warmup + 1, n - 2
    out: list[tuple[int, float]] = []
    last_entry: int | None = None
    for ev in sorted(events, key=lambda e: (e.event_date,)):
        scan_idx = bisect.bisect_left(bar_dates, ev.event_date)
        if scan_idx >= n:
            continue  # evento posterior a la última barra
        entry_idx = scan_idx + 1
        if entry_idx < lo_idx or entry_idx > hi_idx:
            continue  # warmup / borde / sin barra posterior
        if last_entry is not None and entry_idx < last_entry + cap_days:
            continue  # refractario
        out.append((entry_idx, ev.total_dollars))
        last_entry = entry_idx
    return out


def build_arm_entries(
    txs_by: dict[str, list[InsiderTx]],
    bars_by: dict[str, list[Bar]],
    params: ClusterParams,
    *,
    warmup: int,
    cap_days: int,
) -> tuple[list[tuple[str, int]], dict[tuple[str, str], float]]:
    """Entradas ``(ticker, idx)`` de un brazo + lookup de ranking por $ del cluster.

    El lookup ``{(ticker, entry_date_iso): total_dollars}`` alimenta el desempate de
    slot (mayor monto comprado entra primero; §4.2)."""
    entries: list[tuple[str, int]] = []
    rank_lookup: dict[tuple[str, str], float] = {}
    for ticker, bars in bars_by.items():
        txs = txs_by.get(ticker)
        if not txs:
            continue
        events = build_cluster_events(txs, params)
        if not events:
            continue
        bar_dates = [b[0] for b in bars]
        for entry_idx, dollars in events_to_entries(
            events, bar_dates, warmup=warmup, cap_days=cap_days
        ):
            entries.append((ticker, entry_idx))
            rank_lookup[(ticker, bar_dates[entry_idx])] = dollars
    entries.sort(key=lambda ti: (bars_by[ti[0]][ti[1]][0], ti[0]))
    return entries, rank_lookup


def make_rank_score(rank_lookup: dict[tuple[str, str], float]):
    def rank_score(ticker: str, date_iso: str) -> float:
        return rank_lookup.get((ticker, date_iso), 0.0)
    return rank_score


def gate_blocks(n_primary: int, min_events: int, force: bool) -> bool:
    """§3.3: True si hay que PARAR antes de correr (menos eventos que el mínimo y
    sin ``--force``). Puro, para testearlo offline sin bajar dato."""
    return (not force) and n_primary < min_events


# ── Grilla operable (baseline y oráculo) ─────────────────────────────────────


def operable_entries(bars_by: dict[str, list[Bar]], warmup: int) -> list[tuple[str, int]]:
    """Todas las entradas operables ``(ticker, idx)`` con ``idx ∈ [warmup+1, n-2]``."""
    out: list[tuple[str, int]] = []
    for t, bars in bars_by.items():
        for idx in range(warmup + 1, len(bars) - 1):
            out.append((t, idx))
    return out


def _month(bars_by, ti: tuple[str, int]) -> str:
    return bars_by[ti[0]][ti[1]][0][:7]  # "YYYY-MM"


# ── Simulación / métricas (idénticas a T11b) ─────────────────────────────────


def make_runner(bars_by, sigs_by, common):
    def run(entries, rank_score=None) -> PortfolioResult:
        return simulate_portfolio(entries, bars_by, sigs_by, rank_score=rank_score, **common)
    return run


def summarise(res: PortfolioResult) -> dict:
    return {
        "cagr": cagr(res.equity_curve),
        "sharpe": sharpe_annual(res.equity_curve),
        "max_dd": res.max_dd,
        "n_taken": res.n_taken,
        "n_offered": res.n_offered,
        "exposure": res.exposure_share,
        "total_return_pts": res.total_return_pts,
        "accounting_ok": _accounting_ok(res),
    }


def _accounting_ok(res: PortfolioResult) -> bool:
    if not res.equity_curve or res.final_equity <= 0:
        return True
    dev = abs(res.equity_curve[-1][1] - res.final_equity) / res.final_equity
    return dev <= 1e-6


def regime_trade_breakdown(res: PortfolioResult) -> dict:
    """Retorno medio por trade (pts) y n por régimen — robustez de signo (§6.5)."""
    out: dict[str, dict] = {}
    for name in ["bull_normal"] + [r.name for r in STRESS_REGIMES]:
        tr = [t for t in res.trades if t.regime == name]
        out[name] = {
            "n": len(tr),
            "mean_ret_pts": 100.0 * statistics.fmean([t.ret for t in tr]) if tr else 0.0,
        }
    return out


def loto_edge(run, entries, rank_score, random_median_cagr: float) -> dict | None:
    """Saca el ticker que más aporta al P/L y re-corre; el edge sobrevive si el
    CAGR sigue sobre la mediana del baseline random (§6.6)."""
    res = run(entries, rank_score)
    if not res.trades:
        return None
    pnl_by: dict[str, float] = {}
    for t in res.trades:
        pnl_by[t.ticker] = pnl_by.get(t.ticker, 0.0) + t.pnl
    dropped = max(pnl_by, key=lambda k: pnl_by[k])
    kept = [ti for ti in entries if ti[0] != dropped]
    cg = cagr(run(kept, rank_score).equity_curve)
    return {"dropped": dropped, "cagr_without": cg, "survives": cg > random_median_cagr}


# ── Baseline Monte Carlo time-matched ────────────────────────────────────────


def random_baseline(
    run, bars_by, count_by_month: dict[str, int],
    operable_by_month: dict[str, list[tuple[str, int]]], *, k_random: int, seed0: int,
) -> dict[str, list[float]]:
    """K carteras aleatorias que respetan la distribución mensual del brazo primario."""
    dist: dict[str, list[float]] = {"cagr": [], "sharpe": [], "max_dd": []}
    for s in range(k_random):
        rng = random.Random(seed0 + s)
        entries: list[tuple[str, int]] = []
        for month, cnt in count_by_month.items():
            pool = operable_by_month.get(month) or []
            if not pool or cnt <= 0:
                continue
            if len(pool) >= cnt:
                entries.extend(rng.sample(pool, cnt))
            else:
                entries.extend(rng.choices(pool, k=cnt))
        entries.sort(key=lambda ti: (bars_by[ti[0]][ti[1]][0], ti[0]))
        res = run(entries, None)
        dist["cagr"].append(cagr(res.equity_curve))
        sh = sharpe_annual(res.equity_curve)
        dist["sharpe"].append(sh if sh is not None else 0.0)
        dist["max_dd"].append(res.max_dd)
    return dist


def _pct(xs: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(xs, dtype=float), q)) if xs else float("nan")


def _median(xs: list[float]) -> float:
    return float(np.median(np.asarray(xs, dtype=float))) if xs else float("nan")


# ── PBO/DSR sobre retornos diarios de equity (patrón T10/T11b) ───────────────


def aligned_returns(results: dict[str, PortfolioResult], arms: list[str]) -> dict[str, list[float]]:
    eq_by: dict[str, dict[str, float]] = {}
    cal: set[str] = set()
    for name in arms:
        d = {dt: v for dt, v in results[name].equity_curve}
        eq_by[name] = d
        cal |= set(d)
    dates = sorted(cal)
    out: dict[str, list[float]] = {}
    for name in arms:
        d = eq_by[name]
        last = results[name].initial_capital
        filled: list[float] = []
        for dt in dates:
            if dt in d:
                last = d[dt]
            filled.append(last)
        out[name] = [filled[i] / filled[i - 1] - 1.0
                     for i in range(1, len(filled)) if filled[i - 1] > 0]
    return out


# ── Main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay del detector de insider cluster (Tarea 12)")
    p.add_argument("--universe", default=DEFAULT_UNIVERSE)
    p.add_argument("--txs", default=DEFAULT_TXS, help="artefacto insider_txs.json del ingester")
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--cap-days", type=int, default=20)
    p.add_argument("--max-positions", type=int, default=5)
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--k-random", type=int, default=500)
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--min-events", type=int, default=MIN_EVENTS_GATE,
                   help="gate §3.3: por debajo de esto, PARA antes de correr")
    p.add_argument("--signals-mode", choices=("analyze_flip", "atr_only"),
                   default="analyze_flip", help="modelo de exit (ver docstring)")
    p.add_argument("--force", action="store_true", help="ignora el gate de conteo mínimo")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    from scripts.precompute_pit_signals import parse_universe_file

    upath = _HERE.parent / args.universe
    txpath = _HERE.parent / args.txs
    if not upath.exists():
        print(f"universo no encontrado: {upath}", file=sys.stderr)
        return 1
    if not txpath.exists():
        print(f"artefacto de transacciones no encontrado: {txpath}\n"
              f"corré scripts/ingest_form345.py primero.", file=sys.stderr)
        return 1

    tickers = parse_universe_file(upath)
    txs_by = load_txs(txpath)
    bars_by, sigs_by, n_sig = load_bars(tickers, args.period, args.signals_mode, args.warmup)
    if not bars_by:
        print("Sin barras en Parquet: precargá el cache del universo primero.", file=sys.stderr)
        return 1
    print(f"Universo: {len(tickers)} tickers · con barras: {len(bars_by)} · "
          f"con transacciones: {sum(1 for t in bars_by if txs_by.get(t))}")
    print(f"Modo de exit: {args.signals_mode}"
          + (f" · {n_sig} tickers con señal PIT ({100*n_sig/max(1,len(bars_by)):.0f}% cobertura)"
             if args.signals_mode == "analyze_flip" else ""))

    common = dict(
        max_positions=args.max_positions, initial_capital=args.capital,
        cap_days=args.cap_days, atr_p=AtrParams(), so_params=ScaleOutParams(),
        costs=CostModel(), regime_of=regime_for_date,
        allow_reentry_while_open=False,  # engine-faithful
    )
    run = make_runner(bars_by, sigs_by, common)

    # Entradas + ranking por brazo.
    entries_by: dict[str, list[tuple[str, int]]] = {}
    rank_by: dict[str, dict] = {}
    for name, params in CANDIDATE_ARMS.items():
        e, rl = build_arm_entries(txs_by, bars_by, params,
                                  warmup=args.warmup, cap_days=args.cap_days)
        entries_by[name] = e
        rank_by[name] = rl
    prim = entries_by[PRIMARY_ARM]
    print(f"Entradas por brazo: { {n: len(e) for n, e in entries_by.items()} }")
    print(f"Brazo primario {PRIMARY_ARM}: {len(prim)} entradas\n")

    # Gate de conteo mínimo (§3.3) — congelado ANTES de correr.
    if gate_blocks(len(prim), args.min_events, args.force):
        print(f"GATE §3.3: el brazo primario arrojó {len(prim)} < {args.min_events} eventos.")
        print("PARAR: escalar el universo a small/mid caps como follow-up documentado,")
        print("en vez de correr un null sin poder. (--force para correr igual.)")
        return 2
    if not prim:
        print("El brazo primario no produjo entradas — nada que evaluar.", file=sys.stderr)
        return 1

    # Baseline Monte Carlo time-matched al primario.
    operable = operable_entries(bars_by, args.warmup)
    operable_by_month: dict[str, list[tuple[str, int]]] = {}
    for ti in operable:
        operable_by_month.setdefault(_month(bars_by, ti), []).append(ti)
    count_by_month: dict[str, int] = {}
    for ti in prim:
        count_by_month[_month(bars_by, ti)] = count_by_month.get(_month(bars_by, ti), 0) + 1
    rand_dist = random_baseline(run, bars_by, count_by_month, operable_by_month,
                                k_random=args.k_random, seed0=args.seed)
    rb = {
        "cagr_p95": _pct(rand_dist["cagr"], KILL_RANDOM_PCTILE),
        "cagr_median": _median(rand_dist["cagr"]),
        "sharpe_p95": _pct(rand_dist["sharpe"], KILL_RANDOM_PCTILE),
        "sharpe_median": _median(rand_dist["sharpe"]),
        "maxdd_median": _median(rand_dist["max_dd"]),
        "k": args.k_random,
    }

    # Oráculo: mejores entradas operables por retorno realizado (look-ahead).
    oracle_ret = precompute_oracle_returns(operable, bars_by, sigs_by,
                                           so_params=ScaleOutParams(), atr_p=AtrParams(),
                                           cap_days=args.cap_days, costs=CostModel())
    op_scored = [(ti, oracle_ret.get((ti[0], bars_by[ti[0]][ti[1]][0]))) for ti in operable]
    op_scored = [(ti, r) for ti, r in op_scored if r is not None]
    op_scored.sort(key=lambda x: x[1], reverse=True)
    oracle_entries = sorted((ti for ti, _ in op_scored[:len(prim)]),
                            key=lambda ti: (bars_by[ti[0]][ti[1]][0], ti[0]))

    # Correr todos los brazos (con su ranking $) + oráculo.
    results: dict[str, PortfolioResult] = {
        n: run(entries_by[n], make_rank_score(rank_by[n])) for n in CANDIDATE_ARMS
    }
    results[ORACLE_ARM] = run(oracle_entries, None)
    summaries = {n: summarise(results[n]) for n in CANDIDATE_ARMS}
    oracle_sum = summarise(results[ORACLE_ARM])

    # Filtro local por brazo: bate p95 en CAGR y Sharpe + riesgo OK + ΔCAGR.
    def passes_local(s: dict) -> bool:
        sh = s["sharpe"] if s["sharpe"] is not None else -1e9
        return bool(
            s["accounting_ok"]
            and s["cagr"] > rb["cagr_p95"]
            and sh > rb["sharpe_p95"]
            and s["max_dd"] <= KILL_DD_MULT * rb["maxdd_median"]
            and (s["cagr"] - rb["cagr_median"]) >= KILL_MIN_DCAGR
        )
    for s in summaries.values():
        s["passes_local"] = passes_local(s)

    # Brazo de decisión = mejor Sharpe entre los que pasan local.
    eligibles = [n for n in CANDIDATE_ARMS if summaries[n]["passes_local"]]
    ranked = sorted(CANDIDATE_ARMS,
                    key=lambda n: (summaries[n]["sharpe"] if summaries[n]["sharpe"] is not None else -1e9),
                    reverse=True)
    selected = next((n for n in ranked if n in eligibles), None)

    # PBO/DSR sobre los 6 brazos.
    cand = list(CANDIDATE_ARMS)
    rets = aligned_returns(results, cand)
    T = len(next(iter(rets.values()))) if rets else 0
    pbo = pbo_cscv({c: rets[c] for c in cand}, n_splits=10) if T >= 10 else None
    trial_sharpes = [_sharpe(rets[c]) for c in cand]
    dsr = None
    if selected is not None and T >= 2:
        sk, ku = _skew_kurt(rets[selected])
        dsr = deflated_sharpe_ratio(trial_sharpes, n_obs=T,
                                    selected=_sharpe(rets[selected]), skew=sk, kurtosis=ku)

    # Robustez del brazo de decisión: régimen (§6.5) + LOTO (§6.6).
    reg = regime_trade_breakdown(results[selected]) if selected else {}
    regime_sign_ok = bool(reg) and all(v["mean_ret_pts"] >= 0 for v in reg.values())
    loto = (loto_edge(run, entries_by[selected], make_rank_score(rank_by[selected]),
                      rb["cagr_median"]) if selected else None)

    ship = bool(
        selected is not None
        and dsr is not None and dsr.deflated_sharpe > KILL_MIN_DSR
        and pbo is not None and pbo.pbo < KILL_MAX_PBO
        and regime_sign_ok
        and loto is not None and loto["survives"]
    )

    ctx = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signals_mode": args.signals_mode, "n_tickers_with_bars": len(bars_by),
        "n_entries_primary": len(prim), "max_positions": args.max_positions,
        "capital": args.capital, "random_baseline": rb, "selected_arm": selected,
        "pbo": (pbo.pbo if pbo else None), "dsr": (dsr.deflated_sharpe if dsr else None),
        "dsr_obs": T, "regime_sign_ok": regime_sign_ok, "loto": loto, "ship": ship,
        "kill_criteria": {
            "min_dcagr": KILL_MIN_DCAGR, "random_pctile": KILL_RANDOM_PCTILE,
            "dd_mult": KILL_DD_MULT, "min_dsr": KILL_MIN_DSR, "max_pbo": KILL_MAX_PBO,
            "min_events_gate": args.min_events,
        },
    }

    if args.json:
        print(json.dumps({
            "context": ctx,
            "summaries": {n: summaries[n] for n in CANDIDATE_ARMS},
            "oracle": oracle_sum,
            "regime_breakdown_selected": reg,
        }, ensure_ascii=False, indent=2, default=str))
        return 0

    _report(summaries, oracle_sum, rb, cand, selected, pbo, dsr, T,
            reg, regime_sign_ok, loto, ship)
    return 0


def _f(x, w=8, p=2, suf=""):
    if x is None:
        return f"{'—':>{w}}"
    return f"{x*(100 if suf == '%' else 1):>{w-len(suf)}.{p}f}{suf}"


def _report(summaries, oracle_sum, rb, cand, selected, pbo, dsr, T,
            reg, regime_sign_ok, loto, ship):
    print(f"Baseline random (K={rb['k']}): "
          f"CAGR mediana {_f(rb['cagr_median'],0,1,'%')} · p95 {_f(rb['cagr_p95'],0,1,'%')} | "
          f"Sharpe mediana {rb['sharpe_median']:.2f} · p95 {rb['sharpe_p95']:.2f} | "
          f"maxDD mediana {_f(rb['maxdd_median'],0,1,'%')}\n")
    hdr = (f"{'brazo':<20}{'CAGR':>9}{'Sharpe':>9}{'maxDD':>9}{'tomad':>7}"
           f"{'ofrec':>7}{'expos':>7}{'local':>7}")
    print(hdr)
    print("-" * len(hdr))
    for n in cand:
        s = summaries[n]
        mark = "*" if n == selected else ("PRIM" if n == PRIMARY_ARM else "")
        print(f"{n:<20}{_f(s['cagr'],9,2,'%')}{_f(s['sharpe'],9,2)}{_f(s['max_dd'],9,1,'%')}"
              f"{s['n_taken']:>7}{s['n_offered']:>7}{_f(s['exposure'],7,0,'%')}"
              f"{('SI' if s['passes_local'] else 'no'):>5}{mark:>2}")
    o = oracle_sum
    print(f"{ORACLE_ARM:<20}{_f(o['cagr'],9,2,'%')}{_f(o['sharpe'],9,2)}{_f(o['max_dd'],9,1,'%')}"
          f"{o['n_taken']:>7}{o['n_offered']:>7}{_f(o['exposure'],7,0,'%')}{'val':>7}")

    print("\nBrazo de decisión:", selected or "(ninguno pasa el filtro local)")
    if selected:
        print("Por régimen — ret medio por trade (pts) / n:")
        for name, v in reg.items():
            print(f"  {name:<18} {v['mean_ret_pts']:>+7.2f}  (n={v['n']})")
        print(f"  signo estable por régimen: {'SI' if regime_sign_ok else 'NO'}")
        if loto:
            print(f"  LOTO (sacando {loto['dropped']}): CAGR {_f(loto['cagr_without'],0,2,'%')} "
                  f"→ edge {'sobrevive' if loto['survives'] else 'SE CAE'}")
    print(f"\nDescuento por selección múltiple (6 brazos, T={T} obs):")
    print(f"  PBO (CSCV) = {pbo.pbo:.3f}" if pbo else "  PBO = n/d")
    print(f"  DSR = {dsr.deflated_sharpe:.3f} (SR0={dsr.expected_max_sharpe:.4f})" if dsr
          else "  DSR = n/d (ningún brazo pasa local)")
    print(f"\n  VEREDICTO: {'SHIP' if ship else 'NO-SHIP'}")
    print(f"\nKill-criteria: CAGR y Sharpe > p95 random · ΔCAGR ≥ +{100*KILL_MIN_DCAGR:.0f}pp vs mediana "
          f"· maxDD ≤ {KILL_DD_MULT}× · DSR>{KILL_MIN_DSR} · PBO<{KILL_MAX_PBO} · "
          f"signo estable por régimen y por ticker (LOTO)")


if __name__ == "__main__":
    raise SystemExit(main())
