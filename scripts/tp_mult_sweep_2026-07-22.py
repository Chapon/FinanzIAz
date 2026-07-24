"""
Sweep de tp_mult (take-profit ATR) — análisis 2026-07-22 (pedido de Chapa).

Aisla la variable que Tarea 7 NO barrió: el múltiplo del take-profit. Entradas
neutras cada 20 barras (warmup 250) sobre el grid 41×10y, salidas gobernadas
SOLO por niveles ATR (mundo C_A4: la señal no preempta), reusando la maquinaria
pura ya validada de analysis/exit_replay.py.

Métricas: retorno medio neto, win%, payoff, días de hold, mezcla de salidas,
max DD del compuesto equal-weight, retorno ajustado por slot (ret/día), y
desglose por régimen (bull_normal + 3 ventanas de stress de E4).

NO toca la DB ni el engine. Display/research only.
"""
from __future__ import annotations
import sys, math, glob, os, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd

from analysis.exit_replay import (
    AtrParams, atr_series, atr_exit, _atr_trigger_level, _exit_fill_price, max_drawdown,
)

PARQUET = "data/parquet"
WARMUP = 250
SPACING = 20
CAP_DAYS = 20
COMM = 0.001      # 0.1% notional
SLIP = 0.0005     # 0.05%
STOP_MULT = 2.0
UNIVERSE = ("AAPL MSFT GOOGL NVDA AMD AVGO TSM CRM NOW HD LOW TGT NKE BKNG MCD KO PG "
            "WMT MDLZ PM IBM INTC TSLA F JPM GS BRK-B V UNH JNJ LLY PFE XOM CVX NEE "
            "AMT LIN CAT BA GE DIS").split()

TP_ARMS = {"3.0": 3.0, "4.0(actual)": 4.0, "5.0": 5.0, "6.0": 6.0, "8.0": 8.0, "sin-TP": None}


def regime(d: str) -> str:
    if "2018-10-01" <= d <= "2018-12-24": return "stress_2018q4"
    if "2020-02-20" <= d <= "2020-04-07": return "stress_covid_2020"
    if "2022-01-03" <= d <= "2022-10-12": return "stress_bear_2022"
    return "bull_normal"


def load_bars(t: str):
    f = os.path.join(PARQUET, f"{t}__10y__1d.parquet")
    if not os.path.exists(f): return None
    df = pd.read_parquet(f)
    out = []
    for idx, r in df.iterrows():
        out.append((idx.strftime("%Y-%m-%d"), float(r.Open), float(r.High),
                    float(r.Low), float(r.Close), float(r.Volume)))
    return out


def simulate(bars, e_idx, tp_mult):
    """Abre al close de e_idx, gestiona con ATR-only (stop/trail/tp/cap). Devuelve dict o None."""
    p = AtrParams(period=14, stop_mult=STOP_MULT, tp_mult=(tp_mult if tp_mult is not None else 1e9),
                  trail_enabled=True, trail_min_excess_atrs=1.0, trail_mult=None)
    b5 = [(d, o, h, l, c) for (d, o, h, l, c, v) in bars]  # sin volumen para atr funcs
    atrs = atr_series(b5, p.period)
    entry_date, _, _, _, entry_close, _ = bars[e_idx]
    avg_cost = entry_close * (1 + COMM + SLIP)   # fill de entrada con costos
    hwm = entry_close
    last_idx = min(e_idx + CAP_DAYS, len(bars) - 1)
    daily = []  # (date, daily_return_fraction) close-to-close while open
    prev_close = entry_close
    exit_idx = None; exit_reason = ""; exit_level = None
    for i in range(e_idx + 1, last_idx + 1):
        date_i, o_i, h_i, l_i, close_i, _ = bars[i]
        a = atrs[i]
        fired = None
        if a is not None:
            fired = atr_exit(current_price=close_i, avg_cost=entry_close,
                             high_water_mark=hwm, atr_value=a, p=p)
        daily.append((date_i, close_i / prev_close - 1.0))
        if fired is not None:
            exit_idx, exit_reason = i, fired
            exit_level = _atr_trigger_level(fired, avg_cost=entry_close, hwm=hwm, atr_value=a, p=p)
            break
        if i == last_idx:
            exit_idx, exit_reason = i, "cap_reached"
            break
        prev_close = close_i
        hwm = max(hwm, close_i)
    if exit_idx is None:
        return None
    if exit_reason in ("atr_stop", "atr_trail", "atr_tp"):
        exit_price = _exit_fill_price(exit_reason, exit_level, b5[exit_idx])
    else:
        exit_price = bars[exit_idx][4]
    exit_fill = exit_price * (1 - COMM - SLIP)
    ret = exit_fill / avg_cost - 1.0
    hold = exit_idx - e_idx
    return {"ret": ret, "hold": hold, "reason": exit_reason,
            "entry_date": entry_date, "daily": daily}


def composite_dd(trades):
    """Max DD de la curva compuesta equal-weight (media diaria de posiciones abiertas)."""
    by_day = {}
    for tr in trades:
        for d, r in tr["daily"]:
            by_day.setdefault(d, []).append(r)
    curve = []
    eq = 1.0
    for d in sorted(by_day):
        eq *= (1 + statistics.mean(by_day[d]))
        curve.append((d, eq))
    return max_drawdown(curve) if curve else 0.0


def main():
    # entradas comunes a todos los brazos
    entries = []  # (ticker, e_idx, bars)
    barcache = {}
    for t in UNIVERSE:
        bars = load_bars(t)
        if bars is None or len(bars) < WARMUP + SPACING + 2:
            continue
        barcache[t] = bars
        for e in range(WARMUP, len(bars) - 2, SPACING):
            entries.append((t, e))
    print(f"Universo: {len(barcache)} tickers · {len(entries)} entradas neutras (spacing {SPACING}, warmup {WARMUP})\n")

    rows = []
    per_regime = {}
    for name, tp in TP_ARMS.items():
        rets, holds, reasons = [], [], []
        trades_full = []
        reg_rets = {}
        for (t, e) in entries:
            r = simulate(barcache[t], e, tp)
            if r is None: continue
            rets.append(r["ret"]); holds.append(r["hold"]); reasons.append(r["reason"])
            trades_full.append(r)
            reg_rets.setdefault(regime(r["entry_date"]), []).append(r["ret"])
        wins = [x for x in rets if x > 0]; losses = [x for x in rets if x <= 0]
        payoff = (statistics.mean(wins) / abs(statistics.mean(losses))) if wins and losses else float("nan")
        dd = composite_dd(trades_full)
        mean_ret = statistics.mean(rets)
        avg_hold = statistics.mean(holds)
        tp_share = sum(1 for x in reasons if x == "atr_tp") / len(reasons)
        trail_share = sum(1 for x in reasons if x == "atr_trail") / len(reasons)
        stop_share = sum(1 for x in reasons if x == "atr_stop") / len(reasons)
        cap_share = sum(1 for x in reasons if x == "cap_reached") / len(reasons)
        p5 = sorted(rets)[int(0.05 * len(rets))]
        rows.append({
            "arm": name, "mean%": mean_ret*100, "median%": statistics.median(rets)*100,
            "win%": len(wins)/len(rets)*100, "payoff": payoff,
            "avg_hold": avg_hold, "ret_per_day_bp": mean_ret/avg_hold*10000,
            "maxDD%": dd*100, "p5%": p5*100,
            "tp%": tp_share*100, "trail%": trail_share*100, "stop%": stop_share*100, "cap%": cap_share*100,
            "n": len(rets),
        })
        per_regime[name] = {k: statistics.mean(v)*100 for k, v in reg_rets.items()}

    # tabla principal
    hdr = ["arm","mean%","median%","win%","payoff","avg_hold","ret_per_day_bp","maxDD%","p5%","tp%","trail%","stop%","cap%"]
    print(" | ".join(f"{h:>13}" for h in hdr))
    print("-"*len(" | ".join(f"{h:>13}" for h in hdr)))
    for r in rows:
        print(" | ".join(f"{r[h]:>13.2f}" if isinstance(r[h], float) else f"{str(r[h]):>13}" for h in hdr))
    print(f"\nn por brazo: {rows[0]['n']}")

    print("\n=== Retorno medio % por régimen ===")
    regs = ["bull_normal","stress_2018q4","stress_covid_2020","stress_bear_2022"]
    print(f"{'arm':>13} | " + " | ".join(f"{r:>18}" for r in regs))
    for name in TP_ARMS:
        pr = per_regime[name]
        print(f"{name:>13} | " + " | ".join(f"{pr.get(r, float('nan')):>18.3f}" for r in regs))


if __name__ == "__main__":
    main()
