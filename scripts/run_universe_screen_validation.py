"""
Validación del kill-criteria de E1b — screen de universo por liquidez/calidad.

Corre el screen (``paper_trading.universe.screen_candidate``) sobre una watchlist
real usando datos VIVOS (yfinance para ADV$, EDGAR XBRL para fundamentals) y
reporta, nombre por nombre, si entraría o quedaría excluido y por qué.

Kill-criteria (BACKLOG §E1b): el screen **excluye los nombres tipo MLTX** (biotech
clínico pre-revenue, −89.9 %) **sin sacar nombres buenos**. Este script lo hace
medible:
  * ``--expect-fragile`` (default ``MLTX``): estos DEBEN quedar excluidos **si
    están en el universo que se evalúa**.
  * el resto de la watchlist son los "nombres buenos": ninguno debería caer por
    fundamentals; si el piso de ADV$ excluye alguno, se lista para revisión
    humana (puede ser un ilíquido legítimo, no necesariamente un "bueno").

Es **read-only** (no toca la DB ni el motor) y usa RED (yfinance + SEC). No corre
en la suite. Uso típico en Windows:

    python scripts/run_universe_screen_validation.py            # watchlist de la cuenta VIVA
    python scripts/run_universe_screen_validation.py --min-adv 5000000
    python scripts/run_universe_screen_validation.py --tickers MLTX,AAPL,MU --json

Los defaults aíslan la pata fundamental (la que agarra a MLTX): ADV$ floor en 0
(solo informa el ADV$) salvo que pases ``--min-adv``.

**Tarea 128 — dos defectos que hacían inservible al instrumento.** (1) ``--account-id``
defaulteaba a ``DEFAULT_ACCOUNT_ID = 1``, la cuenta **pausada** desde el 2026-07-01,
así que sin flag medía la watchlist de una cuenta muerta; ahora se resuelve contra
``is_active`` como los siete runners de la tarea 99. (2) el ``--expect-fragile MLTX``
por default daba ``fragile_missed=["MLTX"]`` contra cualquier universo que no lo
tuviera —el de la cuenta viva, por ejemplo— y con eso ``kill_pass=False`` y **exit
1**: un NO-SHIP falso. Ahora sólo se exige a los frágiles que **están** en el
universo evaluado, y los que no están se declaran aparte, porque su ausencia
significa que el lado *verdadero-positivo* del kill-criteria **no se ejercita** en
esa corrida — que es distinto de que lo haya pasado.
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
from scripts.baseline_metrics import NoLiveAccount, resolve_account_id

DEFAULT_DB = "finanzias.db"
DEFAULT_ADV_LOOKBACK = 20


def _load_watchlist(db: str, account_id: int | None) -> tuple[int, list[str]]:
    """``(cuenta, tickers)``. Sin ``account_id`` se resuelve la **viva** (tarea 99).

    La cuenta se resuelve con la misma conexión con la que después se lee la
    watchlist: preguntarle a una base por la cuenta viva y leerle la watchlist a
    otra es justo el desvío que este script existe para no tener.
    """
    con = sqlite3.connect(db)
    try:
        account_id = resolve_account_id(con, account_id)
        rows = con.execute(
            "SELECT ticker FROM paper_watchlist WHERE account_id = ? ORDER BY ticker",
            (account_id,),
        ).fetchall()
    finally:
        con.close()
    return account_id, [r[0] for r in rows]


def _fmt_money(v: float | None) -> str:
    return "—" if v is None else f"${v:,.0f}"


def _fmt_ni(ni: list[float]) -> str:
    if not ni:
        return "—"
    return ", ".join(f"{v:,.0f}" for v in ni[:3])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Validación del screen de universo E1b (read-only, red).")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument(
        "--account-id",
        type=int,
        default=None,
        help="id de cuenta; sin esto se resuelve la cuenta VIVA contra is_active (tarea 99)",
    )
    p.add_argument("--tickers", default="", help="CSV que sobreescribe la watchlist")
    p.add_argument(
        "--expect-fragile",
        default="MLTX",
        help="CSV de nombres que DEBEN quedar excluidos si están en el universo evaluado",
    )
    p.add_argument("--min-adv", type=float, default=0.0, help="Piso de ADV$ (0 = pata de liquidez off)")
    p.add_argument("--revenue-floor", type=float, default=10_000_000.0)
    p.add_argument("--min-neg-years", type=int, default=2)
    p.add_argument("--no-fundamentals", action="store_true", help="Apaga la pata fundamental")
    p.add_argument("--period", default="1y", help="Ventana de historia para el ADV$")
    p.add_argument("--adv-lookback", type=int, default=DEFAULT_ADV_LOOKBACK)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    account_id: int | None = args.account_id
    if args.tickers.strip():
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        try:
            account_id, tickers = _load_watchlist(args.db, args.account_id)
        except NoLiveAccount as e:
            print(f"No se pudo resolver la cuenta: {e}", file=sys.stderr)
            return 2
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
    # Tarea 128: a un frágil esperado sólo se le puede exigir que quede excluido si
    # el screen llegó a mirarlo. Exigírselo cuando no está en el universo evaluado
    # es lo que producía el NO-SHIP falso contra la cuenta viva (MLTX está en la
    # watchlist de la 1 y no en la de la 2).
    universo = {r["ticker"] for r in results}
    fragile_evaluados = expect_fragile & universo
    fragile_ausentes = sorted(expect_fragile - universo)
    fragile_caught = sorted(fragile_evaluados & excluded_names)
    fragile_missed = sorted(fragile_evaluados - excluded_names)
    # Exclusiones que NO son las esperadas → candidatas a "nombre bueno" recortado.
    other_exclusions = [r for r in excluded if r["ticker"] not in expect_fragile]
    other_by_fundamentals = [r for r in other_exclusions if r["reason"] != REASON_ADV]

    kill_pass = not fragile_missed and not other_by_fundamentals
    # Y esto NO entra al veredicto: entra al lado del veredicto. Sin ningún frágil
    # en el universo, la corrida mide el lado **falso-positivo** (no recortar
    # buenos) y no ejercita el **verdadero-positivo** (agarrar a los tipo MLTX).
    # Un PASS que no lo diga se lee como si hubiera medido las dos cosas.
    true_positive_ejercitado = bool(fragile_evaluados)

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
                    "account_id": account_id,
                    "n": len(results),
                    "results": results,
                    "fragile_caught": fragile_caught,
                    "fragile_missed": fragile_missed,
                    "fragile_not_in_universe": fragile_ausentes,
                    "true_positive_exercised": true_positive_ejercitado,
                    "other_exclusions": [r["ticker"] for r in other_exclusions],
                    "kill_pass": kill_pass,
                },
                indent=2,
            )
        )
        return 0 if kill_pass else 1

    cuenta_txt = "—(--tickers)" if account_id is None else str(account_id)
    print(f"\nScreen de universo E1b — {len(results)} nombres  ·  DB={args.db} cuenta={cuenta_txt}")
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
    if fragile_ausentes:
        print(f"  fuera del universo evaluado (no se les puede exigir nada): {', '.join(fragile_ausentes)}")
    if other_exclusions:
        print("Otras exclusiones (revisar si son 'nombres buenos' recortados):")
        for r in other_exclusions:
            print(f"  {r['ticker']}: {r['reason']} — {r['detail']}")
    else:
        print("Otras exclusiones: ninguna")
    print(f"\nVEREDICTO PROVISIONAL: {'PASS' if kill_pass else 'REVISAR/NO-SHIP'}")
    print(
        "  (PASS = todos los frágiles esperados **presentes en este universo** "
        "excluidos, y ningún nombre excluido por fundamentals fuera de los "
        "esperados. El ADV floor puede excluir ilíquidos legítimos — revisar a mano.)"
    )
    if not true_positive_ejercitado:
        print(
            "  ALCANCE: ningún frágil esperado está en este universo, así que esta "
            "corrida mide el lado FALSO-POSITIVO (no recortar nombres buenos) y NO "
            "ejercita el verdadero-positivo (agarrar a los tipo MLTX)."
        )
    return 0 if kill_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
