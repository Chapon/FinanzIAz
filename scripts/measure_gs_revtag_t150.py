"""
Tarea 150 (GS-REVTAG) — medir las tres opciones antes de decidir cuál se shipea.

`data.edgar_fundamentals.REVENUE_CONCEPTS` prueba cinco tags us-gaap. **Ninguno
está en los facts de Goldman Sachs**, que reporta su top line como
``RevenuesNetOfInterestExpense``. Hoy GS está conservado sólo porque
``_fragile_fundamentals`` exige **primero** la evidencia positiva de pérdidas
sostenidas, y su ``NetIncomeLoss`` es fuertemente positivo. El día que reporte
dos años seguidos de pérdida GAAP, su ``revenue_latest = None`` se va a leer como
*debajo del piso* —la excepción deliberada que existe para agarrar a MLTX— y el
screen lo va a sacar de los candidatos a BUY **sin decir nada**.

Este script NO decide: **mide**, para que la decisión de Chapa entre las tres
opciones del backlog se tome con números y no con intuición.

Las tres opciones, tal como las enuncia la tarea
------------------------------------------------
(a) **Ampliar la lista** — agregar ``RevenuesNetOfInterestExpense`` (y quizá
    ``PremiumsEarnedNet``) a ``REVENUE_CONCEPTS``. Se agregan **al final**: el
    orden importa, porque el parser corta en el primer concepto que resuelve, y
    poner uno adelante cambiaría el número de quien ya resolvía.
(b) **Dejarlo y declarar la excepción** — cero cambios de comportamiento.
(c) **Exigir revenue resuelto para poder excluir** — no leer la ausencia como
    pre-revenue salvo que el nombre no tenga **ningún** tag de revenue.

El eje que hace decidible a la (c), y que hay que medir en vez de suponer
--------------------------------------------------------------------------
La (c) necesita un predicado *"¿este nombre reporta revenue en algún lado?"*, y la
forma barata de escribirlo —*"algún tag con `Revenue` en el nombre"*— es un
**substring**, o sea la misma clase de defecto que la tarea 173. Medido sobre los
facts reales: ``CostOfRevenue``, ``DeferredRevenue`` y
``CashFlowHedgeGainLossReclassifiedToRevenueNet`` matchean y **no son revenue**.
Por eso el script reporta las dos variantes por separado:

  * ``c_amplio``   — substring ``Revenue``/``PremiumsEarned`` (el predicado laxo)
  * ``c_curado``   — sólo conceptos de **top line** de una lista declarada

y para cada una dice qué pasa con **MLTX**, que es el único verdadero-positivo
que el screen tiene demostrado (validado 2026-07-02: NI −227M/−118M sin revenue).

Uso (read-only, usa RED: SEC XBRL; NO toca la DB salvo para leer la watchlist)
------------------------------------------------------------------------------
    python scripts/measure_gs_revtag_t150.py
    python scripts/measure_gs_revtag_t150.py --tickers MLTX,GS,C,BAC,INTC
    python scripts/measure_gs_revtag_t150.py --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from data.edgar_fundamentals import (
    NET_INCOME_CONCEPT,
    REVENUE_CONCEPTS,
    fetch_company_facts,
    parse_fundamental_facts,
)
from paper_trading.universe import UniverseThresholds, _fragile_fundamentals
from scripts.baseline_metrics import NoLiveAccount, resolve_account_id

DEFAULT_DB = "finanzias.db"

# ── Opción (a): los dos que la tarea propone, AL FINAL de la lista ────────────
# Al final y no adelante: `parse_fundamental_facts` corta en el primero que
# resuelve, así que prependerlos cambiaría el revenue de los que hoy resuelven
# con `Revenues` (C, BAC, JPM, WFC…). Apendearlos sólo puede AGREGAR resolución.
#
# **OJO al re-correr esto DESPUÉS del 2026-09-11:** Chapa eligió la (a) y ya está
# shipeada, o sea que estos dos **ya viven** en `REVENUE_CONCEPTS`. Desde entonces
# la columna «(a)» del informe mide lo mismo que «hoy» y da cero diferencias — eso
# es la señal de que el cambio está puesto, no de que no sirva. Para ver el efecto
# original hay que comparar contra `REVENUE_CONCEPTS` sin estos dos, que es lo que
# hace `test_con_la_lista_VIEJA_ese_mismo_banco_SI_se_excluia`.
CONCEPTOS_A: tuple[str, ...] = ("RevenuesNetOfInterestExpense", "PremiumsEarnedNet")

# ── Opción (c) curada: qué cuenta como "reporta revenue" ──────────────────────
# Lista **declarada** de top lines, no un substring. Los componentes de una línea
# (BrokerageCommissionsRevenue, InvestmentBankingRevenue, PrincipalTransactions-
# Revenue) quedan afuera a propósito: que un banco reporte comisiones no dice que
# reporte su top line, y meterlos volvería a hacer laxo el predicado.
TOP_LINE_CURADO: tuple[str, ...] = (
    REVENUE_CONCEPTS
    + CONCEPTOS_A
    + (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "InterestAndDividendIncomeOperating",
        "RevenuesExcludingInterestAndDividends",
    )
)

# El predicado LAXO que el script mide para poder descartarlo con números.
_SUBSTRINGS_LAXOS = ("Revenue", "PremiumsEarned")


def _conceptos_usd(gaap: dict) -> set[str]:
    """Los conceptos us-gaap del nombre que traen serie en USD."""
    return {c for c, node in gaap.items() if ((node or {}).get("units") or {}).get("USD")}


def _resuelve_con(gaap: dict, conceptos: tuple[str, ...]) -> str | None:
    """El primer concepto de ``conceptos`` que este nombre resuelve, o None."""
    for c in conceptos:
        if ((gaap.get(c) or {}).get("units") or {}).get("USD"):
            return c
    return None


def _load_watchlist(db: str, account_id: int | None) -> tuple[int, list[str]]:
    """``(cuenta, tickers)``. Sin ``account_id`` se resuelve la **viva** (tarea 99)."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        account_id = resolve_account_id(con, account_id)
        rows = con.execute(
            "SELECT ticker FROM paper_watchlist WHERE account_id = ? ORDER BY ticker",
            (account_id,),
        ).fetchall()
    finally:
        con.close()
    return account_id, [r[0] for r in rows]


def medir_uno(ticker: str, thresholds: UniverseThresholds, max_years: int = 4) -> dict:
    """Un nombre bajo las cuatro reglas. Sólo lee: no cambia nada en el repo."""
    payload = fetch_company_facts(ticker)
    gaap = ((payload or {}).get("facts") or {}).get("us-gaap") or {}
    en_usd = _conceptos_usd(gaap)

    facts_hoy = parse_fundamental_facts(payload, ticker=ticker, max_years=max_years)
    hoy = _fragile_fundamentals(facts_hoy, thresholds)

    # (a): mismo parser, lista extendida al final.
    import data.edgar_fundamentals as ef

    original = ef.REVENUE_CONCEPTS
    try:
        ef.REVENUE_CONCEPTS = REVENUE_CONCEPTS + CONCEPTOS_A
        facts_a = ef.parse_fundamental_facts(payload, ticker=ticker, max_years=max_years)
    finally:
        ef.REVENUE_CONCEPTS = original
    opcion_a = _fragile_fundamentals(facts_a, thresholds)

    # (c): la exclusión por revenue ausente se bloquea si el nombre reporta
    # revenue en algún lado. `hoy`/`opcion_a` ya traen el veredicto; acá sólo se
    # pregunta si la ausencia era el motivo y si el bloqueo aplicaría.
    laxo = sorted(c for c in en_usd if any(s in c for s in _SUBSTRINGS_LAXOS))
    curado = sorted(c for c in en_usd if c in TOP_LINE_CURADO)

    # La (c) sólo cambia algo cuando el veredicto de HOY excluye **por ausencia**
    # de revenue (no por un revenue resuelto y bajo el piso).
    excluye_por_ausencia = hoy is not None and facts_hoy.revenue_latest is None
    opcion_c_amplio = None if (excluye_por_ausencia and laxo) else hoy
    opcion_c_curado = None if (excluye_por_ausencia and curado) else hoy

    return {
        "ticker": ticker,
        "tiene_net_income": NET_INCOME_CONCEPT in en_usd,
        "net_income_recent": list(facts_hoy.net_income_recent[:3]),
        "revenue_hoy": facts_hoy.revenue_latest,
        "concepto_hoy": _resuelve_con(gaap, REVENUE_CONCEPTS),
        "revenue_a": facts_a.revenue_latest,
        "concepto_a": _resuelve_con(gaap, REVENUE_CONCEPTS + CONCEPTOS_A),
        "revenue_like_laxo": laxo,
        "revenue_like_curado": curado,
        "excluido_hoy": hoy is not None,
        "excluido_a": opcion_a is not None,
        "excluido_c_amplio": opcion_c_amplio is not None,
        "excluido_c_curado": opcion_c_curado is not None,
        "detalle_hoy": hoy or "",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="T150 — medir las tres opciones de GS-REVTAG.")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--account-id", type=int, default=None, help="sin esto, la cuenta VIVA")
    p.add_argument("--tickers", default="", help="CSV que sobreescribe la watchlist")
    p.add_argument(
        "--control",
        default="MLTX",
        help="CSV que se agrega SIEMPRE al universo medido: son los verdaderos-positivos "
        "que ninguna opción puede perder (kill-criteria de la tarea)",
    )
    p.add_argument("--revenue-floor", type=float, default=10_000_000.0)
    p.add_argument("--min-neg-years", type=int, default=2)
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
    controles = [t.strip().upper() for t in args.control.split(",") if t.strip()]
    universo = list(dict.fromkeys(tickers))
    medidos = list(dict.fromkeys(universo + controles))
    if not medidos:
        print("No hay tickers para medir.", file=sys.stderr)
        return 2

    thresholds = UniverseThresholds(
        min_adv_dollars=0.0,  # la pata de liquidez no es el objeto de esta tarea
        fundamentals_enabled=True,
        min_negative_years=args.min_neg_years,
        revenue_floor=args.revenue_floor,
    )

    filas = []
    for i, t in enumerate(medidos, 1):
        if not args.json:
            print(f"  [{i}/{len(medidos)}] {t}", end="\r", file=sys.stderr)
        try:
            filas.append(medir_uno(t, thresholds))
        except Exception as e:  # un nombre que falla no puede matar el barrido
            filas.append({"ticker": t, "error": repr(e)})

    ok = [f for f in filas if "error" not in f]
    errores = [f for f in filas if "error" in f]

    sin_revenue_hoy = [f for f in ok if f["revenue_hoy"] is None]
    gana_con_a = [f for f in ok if f["revenue_hoy"] is None and f["revenue_a"] is not None]
    cambia_numero_a = [f for f in ok if f["revenue_hoy"] is not None and f["revenue_a"] != f["revenue_hoy"]]

    def _excl(clave: str) -> set[str]:
        return {f["ticker"] for f in ok if f[clave]}

    e_hoy, e_a = _excl("excluido_hoy"), _excl("excluido_a")
    e_ca, e_cc = _excl("excluido_c_amplio"), _excl("excluido_c_curado")

    resumen = {
        "n_medidos": len(ok),
        "n_errores": len(errores),
        "account_id": account_id,
        "controles": controles,
        "sin_revenue_hoy": sorted(f["ticker"] for f in sin_revenue_hoy),
        "gana_revenue_con_a": sorted(f["ticker"] for f in gana_con_a),
        "cambia_numero_con_a": sorted(f["ticker"] for f in cambia_numero_a),
        "excluidos_hoy": sorted(e_hoy),
        "excluidos_a": sorted(e_a),
        "excluidos_c_amplio": sorted(e_ca),
        "excluidos_c_curado": sorted(e_cc),
        "nuevos_excluidos_a": sorted(e_a - e_hoy),
        "nuevos_excluidos_c_amplio": sorted(e_ca - e_hoy),
        "nuevos_excluidos_c_curado": sorted(e_cc - e_hoy),
        "controles_perdidos_a": sorted(set(controles) - e_a),
        "controles_perdidos_c_amplio": sorted(set(controles) - e_ca),
        "controles_perdidos_c_curado": sorted(set(controles) - e_cc),
    }

    if args.json:
        print(json.dumps({"resumen": resumen, "filas": filas}, indent=2))
        return 0

    print(f"\n\nT150 — GS-REVTAG · {len(ok)} nombres medidos (cuenta {account_id})")
    if errores:
        print(f"  ERRORES: {[f['ticker'] for f in errores]}")

    print("\n── Nombres SIN revenue resuelto hoy (la exposición latente) ──")
    for f in sin_revenue_hoy:
        marca = "  ← gana con (a)" if f["revenue_a"] is not None else ""
        ni = ", ".join(f"{v:,.0f}" for v in f["net_income_recent"]) or "—"
        print(f"  {f['ticker']:6s} NI: {ni}{marca}")
        print(f"         top-line curado: {f['revenue_like_curado'] or '(ninguno)'}")
        print(f"         laxo (substring): {len(f['revenue_like_laxo'])} tags")
    if not sin_revenue_hoy:
        print("  (ninguno)")

    print("\n── Kill-criteria ──")
    for nombre, nuevos, perdidos in (
        ("(a) lista ampliada", resumen["nuevos_excluidos_a"], resumen["controles_perdidos_a"]),
        ("(c) amplio  ", resumen["nuevos_excluidos_c_amplio"], resumen["controles_perdidos_c_amplio"]),
        ("(c) curado  ", resumen["nuevos_excluidos_c_curado"], resumen["controles_perdidos_c_curado"]),
    ):
        veredicto = "PASA" if (not nuevos and not perdidos) else "FALLA"
        print(f"  {nombre}: {veredicto}")
        print(f"      nuevos excluidos: {nuevos or '(ninguno)'}")
        print(f"      controles perdidos: {perdidos or '(ninguno)'}")
    print(f"\n  excluidos hoy: {sorted(e_hoy) or '(ninguno)'}")
    print(f"  el número de revenue cambia con (a) en: {resumen['cambia_numero_con_a'] or '(ninguno)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
