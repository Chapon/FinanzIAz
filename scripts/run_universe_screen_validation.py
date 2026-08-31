"""
Validación del kill-criteria de E1b — screen de universo por liquidez/calidad.

Corre el screen (``paper_trading.universe.screen_candidate``) sobre una watchlist
real usando datos VIVOS (yfinance para ADV$, EDGAR XBRL para fundamentals) y
reporta, nombre por nombre, si entraría o quedaría excluido y por qué.

Kill-criteria (BACKLOG §E1b): el screen **excluye los nombres tipo MLTX** (biotech
clínico pre-revenue, −89.9 %) **sin sacar nombres buenos**. Este script lo hace
medible:
  * ``--expect-fragile`` (default ``MLTX``): estos DEBEN quedar excluidos.
  * el resto de la watchlist son los "nombres buenos": ninguno debería caer por
    fundamentals; si el piso de ADV$ excluye alguno, se lista para revisión
    humana (puede ser un ilíquido legítimo, no necesariamente un "bueno").

Es **read-only** (no toca la DB ni el motor) y usa RED (yfinance + SEC). No corre
en la suite. Uso típico en Windows:

    python scripts/run_universe_screen_validation.py            # watchlist de Sim Principal
    python scripts/run_universe_screen_validation.py --min-adv 5000000
    python scripts/run_universe_screen_validation.py --tickers MLTX,AAPL,MU --json

Los defaults aíslan la pata fundamental (la que agarra a MLTX): ADV$ floor en 0
(solo informa el ADV$) salvo que pases ``--min-adv``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from data.edgar_fundamentals import get_fundamental_facts
from paper_trading.gates import recent_adv_dollars
from paper_trading.universe import (
    REASON_ADV,
    UniverseThresholds,
    screen_candidate,
)

DEFAULT_DB = "finanzias.db"
DEFAULT_ACCOUNT_ID = 1
DEFAULT_ADV_LOOKBACK = 20


def _load_watchlist(db: str, account_id: int) -> list[str]:
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT ticker FROM paper_watchlist WHERE account_id = ? ORDER BY ticker",
            (account_id,),
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def _fmt_money(v: float | None) -> str:
    return "—" if v is None else f"${v:,.0f}"


def _fmt_ni(ni: list[float]) -> str:
    if not ni:
        return "—"
    return ", ".join(f"{v:,.0f}" for v in ni[:3])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Validación del screen de universo E1b (read-only, red).")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--account-id", type=int, default=DEFAULT_ACCOUNT_ID)
    p.add_argument("--tickers", default="", help="CSV que sobreescribe la watchlist")
    p.add_argument("--expect-fragile", default="MLTX", help="CSV de nombres que DEBEN quedar excluidos")
    p.add_argument("--min-adv", type=float, default=0.0, help="Piso de ADV$ (0 = pata de liquidez off)")
    p.add_argument("--revenue-floor", type=float, default=10_000_000.0)
    p.add_argument("--min-neg-years", type=int, default=2)
    p.add_argument("--no-fundamentals", action="store_true", help="Apaga la pata fundamental")
    p.add_argument("--period", default="1y", help="Ventana de historia para el ADV$")
    p.add_argument("--adv-lookback", type=int, default=DEFAULT_ADV_LOOKBACK)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    if args.tickers.strip():
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = _load_watchlist(args.db, args.account_id)
    if not tickers:
        print("No hay tickers para evaluar (watchlist vacía o --tickers no dado).", file=sys.stderr)
        return 2

    expect_fragile = {t.strip().upper() for t in args.expect_fragile.split(",") if t.strip()}
    thresholds = UniverseThresholds(
        min_adv_dollars=args.min_adv,
        fundamentals_enabled=not args.no_fundamentals,
        min_negative_years=args.min_neg_years,
        revenue_floor=args.revenue_floor,
    )

    # Warm-up de la cache OHLCV en un batch (menos 401 crumb).
    from data.yahoo_finance import get_historical_data, get_historical_data_batch

    try:
        get_historical_data_batch(tickers, period=args.period)
    except Exception as e:
        print(f"warm-up batch falló ({e}); sigo per-ticker", file=sys.stderr)

    results = []
    for t in tickers:
        df = get_historical_data(t, period=args.period)
        adv = recent_adv_dollars(df, lookback_days=args.adv_lookback) if df is not None else None
        facts = get_fundamental_facts(t) if thresholds.fundamentals_enabled else None
        verdict = screen_candidate(t, adv, facts, thresholds)
        results.append(
            {
                "ticker": t,
                "adv_dollars": adv,
                "net_income_recent": facts.net_income_recent if facts else [],
                "revenue_latest": facts.revenue_latest if facts else None,
                "included": verdict.included,
                "reason": verdict.reason,
                "detail": verdict.detail,
            }
        )

    excluded = [r for r in results if not r["included"]]
    excluded_names = {r["ticker"] for r in excluded}
    fragile_caught = sorted(expect_fragile & excluded_names)
    fragile_missed = sorted(expect_fragile - excluded_names)
    # Exclusiones que NO son las esperadas → candidatas a "nombre bueno" recortado.
    other_exclusions = [r for r in excluded if r["ticker"] not in expect_fragile]
    other_by_fundamentals = [r for r in other_exclusions if r["reason"] != REASON_ADV]

    kill_pass = not fragile_missed and not other_by_fundamentals

    if args.json:
        print(
            json.dumps(
                {
                    "thresholds": {
                        "min_adv_dollars": thresholds.min_adv_dollars,
                        "fundamentals_enabled": thresholds.fundamentals_enabled,
                        "min_negative_years": thresholds.min_negative_years,
                        "revenue_floor": thresholds.revenue_floor,
                    },
                    "n": len(results),
                    "results": results,
                    "fragile_caught": fragile_caught,
                    "fragile_missed": fragile_missed,
                    "other_exclusions": [r["ticker"] for r in other_exclusions],
                    "kill_pass": kill_pass,
                },
                indent=2,
            )
        )
        return 0 if kill_pass else 1

    print(f"\nScreen de universo E1b — {len(results)} nombres  ·  DB={args.db} cuenta={args.account_id}")
    print(
        f"thresholds: min_adv={_fmt_money(thresholds.min_adv_dollars)} "
        f"fundamentals={'on' if thresholds.fundamentals_enabled else 'off'} "
        f"min_neg_years={thresholds.min_negative_years} "
        f"revenue_floor={_fmt_money(thresholds.revenue_floor)}\n"
    )
    print(f"{'TICKER':<8}{'VEREDICTO':<12}{'ADV$':>16}{'REVENUE':>18}  NET INCOME (últimos)   detalle")
    print("-" * 110)
    for r in sorted(results, key=lambda x: (x["included"], x["ticker"])):
        vd = "INCLUIDO" if r["included"] else f"EXCL:{r['reason']}"
        print(
            f"{r['ticker']:<8}{vd:<12}{_fmt_money(r['adv_dollars']):>16}"
            f"{_fmt_money(r['revenue_latest']):>18}  {_fmt_ni(r['net_income_recent']):<22} {r['detail']}"
        )

    print("\n── Kill-criteria ──")
    print(f"Esperados frágiles ({', '.join(sorted(expect_fragile)) or '—'}):")
    print(f"  agarrados: {', '.join(fragile_caught) or '—'}")
    if fragile_missed:
        print(f"  NO agarrados (FALLA): {', '.join(fragile_missed)}")
    if other_exclusions:
        print("Otras exclusiones (revisar si son 'nombres buenos' recortados):")
        for r in other_exclusions:
            print(f"  {r['ticker']}: {r['reason']} — {r['detail']}")
    else:
        print("Otras exclusiones: ninguna")
    print(f"\nVEREDICTO PROVISIONAL: {'PASS' if kill_pass else 'REVISAR/NO-SHIP'}")
    print(
        "  (PASS = todos los frágiles esperados excluidos y ningún nombre excluido "
        "por fundamentals fuera de los esperados. El ADV floor puede excluir "
        "ilíquidos legítimos — revisar a mano.)"
    )
    return 0 if kill_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
