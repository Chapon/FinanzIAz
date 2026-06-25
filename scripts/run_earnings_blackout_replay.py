#!/usr/bin/env python3
"""
run_earnings_blackout_replay.py — ¿conviene reactivar el earnings blackout?

Mide, sobre los BUYs reales de una cuenta, el impacto de haber bloqueado las
compras que cayeron cerca de un earnings (Gate 6, `earnings_blackout_days`).
Decide con datos si `earnings_blackout_days` debe volver a > 0 (ver
docs/BACKLOG.md tarea 8).

Pregunta que contesta
---------------------
1. De los BUYs cerrados (round-trips FIFO), ¿cuáles ocurrieron dentro de ±N días
   de un earnings del ticker? ¿Qué P/L tuvieron vs el resto?
2. Contrafactual "plata bloqueada → siguiente pick" (decidido con Chapa
   2026-06-25): si el blackout hubiera frenado esas compras, el capital se
   habría redeployado al siguiente nombre rankeado. Proxy: ese capital habría
   rendido el **retorno medio de los BUYs NO-near-earnings del mismo período**.
   Δ = P/L contrafactual − P/L real de los near-earnings. Δ > 0 → el blackout ayuda.

Sweep de N ∈ {1, 2, 3, 5} para encontrar la mejor ventana.

Calidad de datos
----------------
- Las fechas de earnings vienen de yfinance (`get_earnings_dates`) → **requiere
  red; correr en Windows**, no en el sandbox.
- Solo cuenta round-trips CERRADOS (las posiciones abiertas no tienen P/L
  realizado). Las compras near-earnings que siguen abiertas no se miden — es una
  cota inferior del efecto.
- El contrafactual "siguiente pick" es un PROXY (media de los no-near). La
  re-simulación completa del ranking point-in-time es el refinamiento riguroso.

Uso (Windows)
-------------
    python scripts/run_earnings_blackout_replay.py --account-id 1
    python scripts/run_earnings_blackout_replay.py --db backups\finanzias_2026-06-23_09-56-44_daily.db
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Ventanas de ±días a evaluar.
DEFAULT_WINDOWS = (1, 2, 3, 5)


# ── Funciones puras (testeables offline) ──────────────────────────────────────
def _as_date(value) -> date | None:
    """Coerce str/datetime/date a date (o None)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(s[: len(fmt) + 6], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def is_near_earnings(buy_day: date | None, earnings_dates, window_days: int) -> bool:
    """True si buy_day cae dentro de ±window_days de alguna fecha de earnings."""
    bd = _as_date(buy_day)
    if bd is None:
        return False
    for ed in earnings_dates or ():
        edd = _as_date(ed)
        if edd is not None and abs((bd - edd).days) <= window_days:
            return True
    return False


def classify_round_trips(round_trips, earnings_by_ticker, window_days: int):
    """Parte los round-trips en (near_earnings, far) según el día de COMPRA."""
    near, far = [], []
    for rt in round_trips:
        dates = earnings_by_ticker.get(rt["ticker"], ())
        (near if is_near_earnings(rt.get("buy_day"), dates, window_days) else far).append(rt)
    return near, far


def summarize(round_trips) -> dict:
    """Métricas agregadas de un grupo de round-trips."""
    n = len(round_trips)
    if n == 0:
        return {"n": 0, "total_pnl": 0.0, "mean_pnl_pct": 0.0, "median_pnl_pct": 0.0, "win_rate": 0.0}
    pnls = [rt["pnl"] for rt in round_trips]
    pcts = [rt["pnl_pct"] for rt in round_trips]
    wins = sum(1 for p in pnls if p > 0)
    return {
        "n": n,
        "total_pnl": sum(pnls),
        "mean_pnl_pct": mean(pcts),
        "median_pnl_pct": median(pcts),
        "win_rate": wins / n,
    }


def counterfactual_delta(near, far) -> dict:
    """Contrafactual 'siguiente pick': el capital de los near-earnings habría
    rendido la media de los far. Δ = cf_pnl − pnl_real_near (>0 → blackout ayuda)."""
    if not near:
        return {"real_near_pnl": 0.0, "cf_pnl": 0.0, "delta": 0.0, "proxy_ret_pct": 0.0}
    proxy = mean([rt["pnl_pct"] for rt in far]) if far else 0.0
    real = sum(rt["pnl"] for rt in near)
    cf = sum((rt["shares"] * rt["buy_price"]) * proxy for rt in near)
    return {"real_near_pnl": real, "cf_pnl": cf, "delta": cf - real, "proxy_ret_pct": proxy}


# ── Provider de earnings (inyectable; default = yfinance, red) ─────────────────
def default_earnings_provider(ticker: str) -> list[date]:
    """Fechas históricas de earnings vía el data layer del proyecto (yfinance)."""
    from data.news_sources import collect_yfinance_earnings_history

    rows = collect_yfinance_earnings_history(ticker, limit=24)
    out = []
    for period_label, _est, _rep in rows:
        d = _as_date(period_label)
        if d is not None:
            out.append(d)
    return out


# ── Carga de datos + orquestación ─────────────────────────────────────────────
def load_round_trips(db_path: Path, account_id: int) -> list[dict]:
    """Lee round-trips cerrados de la DB (read-only). Reusa metrics_panel."""
    from analysis.metrics_panel import _filled_orders, pair_round_trips

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        orders = _filled_orders(con, account_id)
    finally:
        con.close()
    return pair_round_trips(orders)


def run(round_trips, earnings_by_ticker, windows=DEFAULT_WINDOWS) -> list[dict]:
    """Corre el sweep de ventanas. Devuelve una fila de resultados por N."""
    results = []
    for n_days in windows:
        near, far = classify_round_trips(round_trips, earnings_by_ticker, n_days)
        cf = counterfactual_delta(near, far)
        results.append({
            "window_days": n_days,
            "near": summarize(near),
            "far": summarize(far),
            "counterfactual": cf,
        })
    return results


def _format_report(results: list[dict], n_total: int, n_tickers: int) -> str:
    lines = [
        "# Replay — earnings blackout (impacto sobre BUYs)",
        "",
        f"Fecha: {date.today().isoformat()}. Round-trips cerrados analizados: {n_total} "
        f"sobre {n_tickers} tickers. Contrafactual: plata bloqueada → siguiente pick "
        "(proxy = retorno medio de los BUYs no-near-earnings).",
        "",
        "| ±N días | # near | P/L near | %medio near | win% near | %medio far | Δ blackout (cf−real) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        ne, fa, cf = r["near"], r["far"], r["counterfactual"]
        lines.append(
            f"| {r['window_days']} | {ne['n']} | {ne['total_pnl']:+.2f} | "
            f"{ne['mean_pnl_pct']*100:+.2f}% | {ne['win_rate']*100:.0f}% | "
            f"{fa['mean_pnl_pct']*100:+.2f}% | {cf['delta']:+.2f} |"
        )
    lines += [
        "",
        "**Lectura:** Δ blackout > 0 ⇒ bloquear esos BUYs y redeployar habría mejorado el P/L "
        "→ restaurar `earnings_blackout_days` a esa N. Δ ≤ 0 ⇒ dejarlo en 0.",
        "",
        "_Cota inferior: las compras near-earnings aún abiertas no entran (sin P/L realizado). "
        "El contrafactual 'siguiente pick' es un proxy; la re-sim del ranking point-in-time es el refinamiento._",
    ]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Replay del earnings blackout sobre BUYs reales.")
    ap.add_argument("--db", type=str, default=str(ROOT / "finanzias.db"), help="Ruta a la DB (read-only).")
    ap.add_argument("--account-id", type=int, default=1)
    ap.add_argument("--windows", type=str, default="1,2,3,5", help="Ventanas ±días, coma-separadas.")
    ap.add_argument("--out", type=str, default=None, help="Ruta del informe .md (default: docs/earnings_blackout_replay_<fecha>.md).")
    args = ap.parse_args(argv)

    windows = tuple(int(x) for x in args.windows.split(",") if x.strip())
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: no existe la DB {db_path}", file=sys.stderr)
        return 2

    round_trips = load_round_trips(db_path, args.account_id)
    if not round_trips:
        print("No hay round-trips cerrados para esa cuenta.", file=sys.stderr)
        return 1

    tickers = sorted({rt["ticker"] for rt in round_trips})
    print(f"Bajando fechas de earnings de {len(tickers)} tickers (yfinance)...", file=sys.stderr)
    earnings_by_ticker = {t: default_earnings_provider(t) for t in tickers}

    results = run(round_trips, earnings_by_ticker, windows)
    report = _format_report(results, len(round_trips), len(tickers))
    print(report)

    out = Path(args.out) if args.out else ROOT / "docs" / f"earnings_blackout_replay_{date.today().isoformat()}.md"
    out.write_text(report, encoding="utf-8")
    print(f"Informe escrito en {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
