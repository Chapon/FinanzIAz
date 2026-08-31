"""
Runner T-CAT-6 (re-evaluación) — backtest del exit-veto (Gate 2c) CON la
dirección del track record de sorpresas (T-CAT-5a) en vez del mean neutral.

Contexto: el backtest original (docs/catalyst_t_cat_6_backtest_2026-06-11.md)
encontró que el veto disparaba 0/3 porque `imminent_catalyst` usaba el mean
neutral de reacción (≈0) → score 0.05-0.09 << veto_min_score 0.30. Con
`surprise_profiles.json` (T-CAT-5a) presente, la dirección del track record
reemplaza ese mean y la magnitud sube. Este runner mide si el veto ahora dispara
y si pasa el kill-criteria de activación.

Contrafactual de la posición vetada (decidido con Chapa 2026-06-12):
**"re-evaluar al próximo scan"** — el veto re-chequea imminencia cada scan, así
que persiste mientras el earnings siga a ≤ horizon_bdays y deja pasar el SELL en
el primer scan donde el catalyst ya no es inminente (≈ el día hábil siguiente al
earnings). ATR stops siguen activos en el medio (un risk-stop gana al veto).
Simplificación honesta: no podemos re-correr el score del modelo en los días
intermedios (no está guardado), así que asumimos que la intención de vender
persiste y se ejecuta en el primer scan no-vetado.

Kill-criteria de activación (docs/catalyst_t_cat_4_design.md §7):
ΔP/L total ≥ +1.5 pts (% capital inicial) y max DD ≤ 1.3× el real, sin degradar
el opportunity-capture. Si no pasa, el flag `paper_catalyst_exit_veto_enabled`
queda OFF (dead-code documentado).

Read-only: nada se escribe a la DB. Correr contra un BACKUP limpio (no la DB
viva — incoherencia virtiofs conocida).

    python scripts/run_catalyst_exit_veto_backtest.py \
        --db backups\finanzias_AAAA-MM-DD_..._daily.db \
        [--account 1] [--cap-days 20] [--horizon 3] [--json] \
        [--out docs/catalyst_t_cat_6_reeval_YYYY-MM-DD.md]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT))

from analysis.exit_replay import (
    SimExit,
    _idx_on_or_after,
    _passthrough,
    build_report,
    replay_event,
)
from analysis.impact_score import exit_veto_block, imminent_catalyst
from analysis.surprise_score import make_surprise_loader
from scripts.baseline_metrics import load_snapshots

# reutilizamos la infraestructura ya probada del runner T6.1
from scripts.run_exit_replay_t61 import (
    _atr_params_from_settings,
    build_sell_events,
    make_bar_loader,
)

DEFAULT_DB = "finanzias.db"
SURPRISE_JSON = ROOT / "data" / "catalyst" / "surprise_profiles.json"
REACTION_JSON = ROOT / "data" / "catalyst" / "historical_reaction.json"


# ── settings (con fallback a los defaults del engine para el veto) ────────────
def _veto_settings() -> dict:
    g = {
        "gray_low": 0.25,  # paper_signal_sell_bypass_score (T6.4)
        "gray_high": 0.50,  # paper_catalyst_veto_gray_high
        "veto_min_score": 0.30,  # paper_catalyst_veto_min_score
    }
    try:
        from config.settings_manager import settings  # type: ignore

        g["gray_low"] = float(settings.get("paper_signal_sell_bypass_score", g["gray_low"]))
        g["gray_high"] = float(settings.get("paper_catalyst_veto_gray_high", g["gray_high"]))
        g["veto_min_score"] = float(settings.get("paper_catalyst_veto_min_score", g["veto_min_score"]))
    except Exception:
        pass
    return g


def _load_json(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _parse_dt(s) -> datetime | None:
    if not s:
        return None
    s = str(s)
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(s[:26], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", ""))
    except Exception:
        return None


def build_earnings_calendar(con: sqlite3.Connection) -> dict[str, list[datetime]]:
    """ticker -> lista ascendente de fechas de earnings (point-in-time).

    Mismo criterio que el backtest original: eventos `earnings_results` de
    news_events con published_at no nulo. La FECHA del earnings se conoce de
    antemano (no es look-ahead); imminent_catalyst sólo usa la fecha + el track
    record de sorpresas (trimestres pasados), nunca el resultado real.
    """
    cal: dict[str, list[datetime]] = {}
    rows = con.execute(
        "SELECT ticker, published_at FROM news_events "
        "WHERE event_type = 'earnings_results' AND published_at IS NOT NULL"
    ).fetchall()
    for ticker, pub in rows:
        dt = _parse_dt(pub)
        if dt is None:
            continue
        cal.setdefault(str(ticker).upper(), []).append(dt)
    for t in cal:
        cal[t] = sorted(set(cal[t]))
    return cal


def make_earnings_loader_asof(calendar: dict[str, list[datetime]], asof: datetime):
    """earnings_loader(ticker) -> próxima fecha de earnings con date >= asof."""
    asof_d = asof.date()

    def _load(ticker: str) -> datetime | None:
        for dt in calendar.get(str(ticker).upper(), ()):
            if dt.date() >= asof_d:
                return dt
        return None

    return _load


def run(db_path: Path, account_id: int, cap_days: int, horizon: int):
    con = sqlite3.connect(str(db_path))
    try:
        events = build_sell_events(con, account_id)
        bar_loader = make_bar_loader(con)
        snaps = load_snapshots(con, account_id)
        real_curve = [(s.snapshot_at.strftime("%Y-%m-%d"), s.total_equity) for s in snaps]
        cap_row = con.execute(
            "SELECT initial_capital FROM paper_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        initial_capital = float(cap_row[0]) if cap_row else 50_000.0
        atr_p = _atr_params_from_settings()

        calendar = build_earnings_calendar(con)
        reaction_table = _load_json(REACTION_JSON)
        sp = _load_json(SURPRISE_JSON) or {}
        profiles = sp.get("profiles", sp)  # soporta {_meta, profiles} o dict plano
        surprise_loader = make_surprise_loader(profiles)
        vs = _veto_settings()

        sims: list[SimExit] = []
        diagnostics: list[dict] = []  # candidatos con earnings inminente

        for ev in events:
            sell_dt = _parse_dt(ev.sell_date) or datetime.strptime(ev.sell_date, "%Y-%m-%d")
            earn_loader = make_earnings_loader_asof(calendar, sell_dt)
            signal = imminent_catalyst(
                ev.ticker,
                sell_dt,
                reaction_table=reaction_table,
                earnings_loader=earn_loader,
                surprise_loader=surprise_loader,
                horizon_bdays=horizon,
            )
            veto_msg = exit_veto_block(
                reason=ev.reason,
                signal_score=ev.signal_score,
                ticker=ev.ticker,
                scan_at=sell_dt,
                signal=signal,
                enabled=True,  # forzamos ON para el backtest (el flag real sigue OFF)
                gray_low=vs["gray_low"],
                gray_high=vs["gray_high"],
                veto_min_score=vs["veto_min_score"],
            )
            vetoed = veto_msg is not None

            if signal is not None:
                diagnostics.append(
                    {
                        "ticker": ev.ticker,
                        "sell_date": ev.sell_date,
                        "reason": ev.reason,
                        "signal_score": ev.signal_score,
                        "in_gray": (
                            ev.signal_score is not None
                            and vs["gray_low"] <= ev.signal_score <= vs["gray_high"]
                        ),
                        "earnings": (
                            earn_loader(ev.ticker).strftime("%Y-%m-%d") if earn_loader(ev.ticker) else None
                        ),
                        "days_until": signal.days_until,
                        "cat_basis": signal.basis,
                        "cat_direction": signal.expected_direction,
                        "cat_score": round(signal.score, 4),
                        "vetoed": vetoed,
                    }
                )

            if not vetoed:
                sims.append(_passthrough(ev))
                continue

            # contrafactual: salir en el primer scan post-earnings (ATR activo).
            bars = bar_loader(ev.ticker)
            edt = earn_loader(ev.ticker)
            sched_idx = None
            if bars and edt is not None:
                e_idx = _idx_on_or_after(bars, edt.strftime("%Y-%m-%d"))
                sched_idx = e_idx + 1  # primer scan donde el catalyst ya no es inminente
            sim = replay_event(ev, bars or [], scheduled_exit_idx=sched_idx, cap_days=cap_days, atr_p=atr_p)
            if sim is None:  # sin datos: cae como passthrough no-modificado
                sim = SimExit(
                    event=ev,
                    modified=False,
                    exit_date=ev.sell_date,
                    exit_price=ev.sell_price,
                    exit_reason="no_data",
                    pnl_sim=ev.pnl_real,
                )
            sims.append(sim)

        report = build_report(
            "catalyst_exit_veto", sims, real_curve, initial_capital=initial_capital, bar_loader=bar_loader
        )

        # kill-criteria T-CAT-6 (distinto del built-in de T6.1)
        passes_tcat6 = report.pnl_delta_pts >= 1.5 and report.dd_ratio <= 1.3

        ctx = {
            "db": str(db_path),
            "account_id": account_id,
            "n_sell_events": len(events),
            "n_signal_sells": sum(1 for e in events if e.is_signal_sell),
            "n_candidates": len(diagnostics),
            "n_vetoed": sum(1 for d in diagnostics if d["vetoed"]),
            "initial_capital": initial_capital,
            "cap_days": cap_days,
            "horizon_bdays": horizon,
            "veto_settings": vs,
            "kill_criteria": {"min_delta_pts": 1.5, "max_dd_ratio": 1.3},
            "passes_tcat6": passes_tcat6,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return report, diagnostics, ctx
    finally:
        con.close()


def _fmt_pct(x, d=2):
    return "—" if x is None else f"{100 * x:+.{d}f}%"


def render_md(report, diagnostics, ctx) -> str:
    L = []
    L.append("# T-CAT-6 — Re-evaluación del exit-veto con dirección de sorpresas (T-CAT-5a)")
    L.append("")
    L.append(
        f"Fecha: {ctx['generated_at'][:10]}. Read-only sobre `{ctx['db']}`. "
        f"Contrafactual: re-evaluar al próximo scan (salida post-earnings, ATR activo)."
    )
    L.append("")
    L.append("## Resultado en una línea")
    L.append("")
    verdict = (
        "**PASA** el kill-criteria → candidato a activar el veto."
        if ctx["passes_tcat6"]
        else "**NO pasa** el kill-criteria → el flag queda OFF (dead-code documentado)."
    )
    L.append(
        f"{verdict} ΔP/L = {report.pnl_delta_pts:+.2f} pts "
        f"(umbral ≥ +1.5), DD ratio = {report.dd_ratio:.2f} (umbral ≤ 1.3). "
        f"Vetó {ctx['n_vetoed']}/{ctx['n_candidates']} SELLs con earnings inminente."
    )
    L.append("")
    L.append("## Configuración")
    L.append("")
    L.append(
        f"- Universo: {ctx['n_sell_events']} SELLs filled "
        f"({ctx['n_signal_sells']} por señal), cuenta {ctx['account_id']}."
    )
    L.append(
        f"- Zona gris: [{ctx['veto_settings']['gray_low']}, {ctx['veto_settings']['gray_high']}], "
        f"veto_min_score = {ctx['veto_settings']['veto_min_score']}, "
        f"imminencia ≤ {ctx['horizon_bdays']} días hábiles."
    )
    L.append(f"- Capital inicial: {ctx['initial_capital']:,.0f}. Cap de holding: {ctx['cap_days']}d.")
    L.append("")
    L.append("## Candidatos (SELLs con earnings inminente)")
    L.append("")
    L.append("| Ticker | SELL | score venta | gris | earnings | díasháb | basis | dir | cat_score | vetado |")
    L.append("|--------|------|-------------|------|----------|---------|-------|-----|-----------|--------|")
    for d in sorted(diagnostics, key=lambda x: x["sell_date"]):
        ss = "—" if d["signal_score"] is None else f"{d['signal_score']:.3f}"
        L.append(
            f"| {d['ticker']} | {d['sell_date']} | {ss} | "
            f"{'sí' if d['in_gray'] else 'no'} | {d['earnings']} | {d['days_until']} | "
            f"{d['cat_basis']} | {d['cat_direction']:+d} | {d['cat_score']:.3f} | "
            f"{'**SÍ**' if d['vetoed'] else 'no'} |"
        )
    L.append("")
    L.append("## Métricas agregadas")
    L.append("")
    L.append(f"- SELLs modificados (vetados c/datos): {report.n_modified}")
    L.append(f"- ΔP/L total: {report.pnl_delta_total:+,.2f} USD ({report.pnl_delta_pts:+.2f} pts)")
    L.append(
        f"- Max DD real: {100 * report.max_dd_real:.2f}% · sim: {100 * report.max_dd_sim:.2f}% "
        f"· ratio: {report.dd_ratio:.2f}"
    )
    L.append(f"- Mediana extra-return (modificados): {_fmt_pct(report.median_extra_return)}")
    L.append(f"- Mediana capture del rally 20d: {_fmt_pct(report.capture_ratio_median)}")
    L.append(f"- Salidas por razón: {report.exits_by_reason}")
    L.append("")
    L.append("## Decisión")
    L.append("")
    if ctx["passes_tcat6"]:
        L.append(
            "El veto mejora el P/L por encima del umbral sin degradar el DD más de 1.3×. "
            "Activar `paper_catalyst_exit_veto_enabled = True` en settings de Windows y "
            "monitorear el panel T6.2 (opportunity-cost) en producción."
        )
    else:
        L.append(
            "El veto no alcanza el umbral de mejora exigido (o degrada el DD). "
            "`paper_catalyst_exit_veto_enabled` queda False (dead-code documentado, "
            "mismo destino que cross-sectional en T05). Revisitar cuando T-CAT-5b "
            "(consenso point-in-time) reemplace el prior v0."
        )
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="T-CAT-6 re-eval del exit-veto con surprise direction.")
    p.add_argument("--db", default=DEFAULT_DB, help="Path a la DB (usar un BACKUP limpio).")
    p.add_argument("--account", type=int, default=1)
    p.add_argument("--cap-days", type=int, default=20)
    p.add_argument("--horizon", type=int, default=3, help="Días hábiles de imminencia.")
    p.add_argument("--json", action="store_true", help="Emite JSON en vez de markdown.")
    p.add_argument("--out", default=None, help="Escribe el informe markdown a este path.")
    args = p.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: no existe la DB {db_path}", file=sys.stderr)
        return 2

    report, diagnostics, ctx = run(db_path, args.account, args.cap_days, args.horizon)

    if args.json:
        print(
            json.dumps(
                {"report": report.to_dict(), "diagnostics": diagnostics, "ctx": ctx}, indent=2, default=str
            )
        )
    else:
        md = render_md(report, diagnostics, ctx)
        print(md)
        out = args.out or f"docs/catalyst_t_cat_6_reeval_{ctx['generated_at'][:10]}.md"
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"\n[escrito] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
