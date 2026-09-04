"""
Runner T6.1 — exit replay sobre los ciclos reales (roadmap v3, Sprint 6).

Corre desde la raíz del repo (Windows, o sandbox con un backup de la DB):

    python scripts/run_exit_replay_t61.py [--db PATH] [--account 1]
        [--cap-days 20] [--period 10y] [--atr-from-defaults] [--json]

Variantes (ver analysis/exit_replay.py):
    a) confirm_next_scan  — SELL de señal ejecuta al scan siguiente
    b) score_threshold    — skip SELLs de señal con score ≥ 0.25
    c) min_holding_2 / 3  — SELL de señal diferido hasta edad ≥ 2/3 días hábiles

Kill criteria (upfront): ship si ΔP/L ≥ +2 pts (% capital inicial) y
max DD ajustado ≤ 1.5× el real.

Los ATR params salen de la config VIVA, y si no se puede leer **levanta** (tarea
102). Antes caía en silencio a los defaults del engine — que traen el stop duro a
2.0×ATR, o sea el desvío que la 92 midió en 7,16 pp de CAGR: el camino de escape
devolvía justo la política que este runner existe para no suponer. Para correr con
los defaults a propósito está `--atr-from-defaults`, que lo avisa por stderr.

Las barras salen del cache **Parquet** (tarea 102). Leían de `historical_data_cache`,
que tiene CERO filas desde que la ARQ1 movió el cache — y como un evento sin barras
pasa sin modificar, las cuatro variantes salían `mod=0`/`Δ=0`, indistinguible de
"la variante no cambia nada". La columna `s/dato` de la tabla es la que separa las
dos lecturas, y si se saltea TODO lo modificable el runner sale con **exit 2**.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from analysis.exit_replay import (
    AtrParams,
    Bar,
    ReplayReport,
    SellEvent,
    build_report,
    simulate_variant,
)
from analysis.harness_config import StaleArtifactError, announce_artifacts, artifact_window
from scripts.baseline_metrics import fifo_match, load_fills, load_snapshots, resolve_account_id

DEFAULT_DB = "finanzias.db"
# El frame con cobertura: 506 de los 752 parquets `1d` en disco son `10y`, y los
# SELL de la cuenta viva caen todos adentro. Se declara acá y se puede mover con
# `--period` — lo que NO se hace es elegirlo por frescura (ver `make_bar_loader`).
DEFAULT_PERIOD = "10y"


def _atr_params_from_settings() -> AtrParams:
    from analysis.harness_config import NO_STOP_MULT

    try:
        from config.settings_manager import settings

        # Tarea 92: este era el ÚNICO runner que armaba sus `AtrParams` leyendo la
        # config viva… y leía tres claves ignorando **las dos que cambiaron** el
        # 2026-08-27 (`atr_hard_stop_enabled` y `atr_trail_mult`). O sea que el
        # camino "leo lo que corre en vivo" mentía en silencio, que es peor que no
        # leerlo: el que lo usa cree que está mirando la política real.
        #
        # El harness no tiene flag para apagar el stop duro — lo expresa con un
        # múltiplo que nunca dispara (`paper_trading/gates.py:113-117` documenta
        # que las dos formas son equivalentes dígito por dígito).
        hard_stop = bool(settings.get("atr_hard_stop_enabled", True))
        stop_mult = max(0.0, float(settings.get("atr_stop_mult", 2.0))) if hard_stop else NO_STOP_MULT
        trail_raw = float(settings.get("atr_trail_mult", 0.0))
        return AtrParams(
            period=max(2, int(settings.get("atr_period", 14))),
            stop_mult=stop_mult,
            tp_mult=max(0.0, float(settings.get("atr_tp_mult", 4.0))),
            trail_enabled=bool(settings.get("atr_trail_enabled", True)),
            # 0.0 es el default del engine y significa "usá `stop_mult`", que es
            # exactamente lo que `AtrParams` expresa con `None`.
            trail_mult=trail_raw if trail_raw > 0 else None,
        )
    except ImportError as e:
        # NO devuelve `AtrParams()` en silencio (tarea 102). Ese default trae el
        # stop duro encendido a 2.0×ATR, que es **el desvío que la 92 midió en 7,16
        # pp de CAGR** — o sea que el camino de escape devolvía justamente la
        # política que este runner existe para no suponer. Un `except` que tapa eso
        # convierte "no pude leer la config viva" en un número creíble.
        raise RuntimeError(
            "No se pudo leer la config viva (`config.settings_manager`): "
            f"{e}. Correr con --atr-from-defaults si se quieren los defaults del "
            "engine A PROPÓSITO — traen el stop duro a 2.0×ATR, el desvío que la "
            "tarea 92 midió en 7,16 pp de CAGR."
        ) from e


def make_bar_loader(period: str = DEFAULT_PERIOD):
    """``bar_loader(ticker) -> list[Bar]`` desde el cache **Parquet** (tarea 102).

    **Leía de ``historical_data_cache``, que tiene CERO filas.** Esa tabla es el
    backend viejo: la ARQ1 movió el cache histórico a Parquet y nadie volvió a
    tocar este runner. Todo lookup devolvía ``None``, y como un evento sin barras
    *pasa sin modificar*, las cuatro variantes salían con ``mod=0`` y ``Δ=0`` —
    que se lee como **«la variante no cambia nada»** y era **«no había datos»**.
    El resultado publicado (`docs/exit_replay_t61_2026-06-10.md`, mod 27/14/…) no
    está mal: se midió contra un backup cuando la tabla todavía tenía filas.

    El ``period`` es **explícito y declarado** en vez de "el frame más fresco":
    ``latest_1d`` elegiría por frescura y podría devolver un ``1y`` que no cubre
    los SELL viejos, y cruzar períodos es el peligro de escala de la 63/64. El
    default es ``10y`` porque es el que tiene cobertura (506 frames en disco).
    """
    from data import parquet_cache

    cache: dict[str, list[Bar] | None] = {}

    def load(ticker: str) -> list[Bar] | None:
        if ticker in cache:
            return cache[ticker]
        df = parquet_cache.read(ticker, period, "1d", ttl_hours=None)
        bars: list[Bar] | None = None
        if df is not None and not df.empty and {"Open", "High", "Low", "Close"} <= set(df.columns):
            tmp: list[Bar] = []
            for ts, row in df.sort_index().iterrows():
                o, h, lo, c = row["Open"], row["High"], row["Low"], row["Close"]
                if any(x is None for x in (o, h, lo, c)) or float(c) <= 0:
                    continue
                tmp.append((str(ts)[:10], float(o), float(h), float(lo), float(c)))
            bars = tmp or None
        cache[ticker] = bars
        return bars

    return load


def build_sell_events(con: sqlite3.Connection, account_id: int) -> list[SellEvent]:
    """SELL fills reales + contexto FIFO (avg_cost, entry) + reason/score."""
    fills = load_fills(con, account_id)
    trades, _ = fifo_match(fills)
    sell_fills = [f for f in sorted(fills, key=lambda x: x.filled_at) if f.side == "SELL"]
    if len(trades) != len(sell_fills):
        raise RuntimeError(f"FIFO mismatch: {len(trades)} trades vs {len(sell_fills)} SELL fills")

    # reason/score por order_id
    # La clave es el order_id, que es INT. (La anotacion automatica del batch
    # anterior habia puesto `str` por defecto.)
    meta: dict[int, tuple] = {
        int(r[0]): (r[1], r[2])
        for r in con.execute(
            "SELECT id, reason, signal_score FROM paper_orders "
            "WHERE account_id = ? AND side = 'SELL' AND status = 'filled'",
            (account_id,),
        )
    }

    events: list[SellEvent] = []
    # strict=True: el cuerpo ya levanta RuntimeError si el orden FIFO no calza,
    # asi que un largo distinto tambien tiene que gritar en vez de truncar.
    for f, t in zip(sell_fills, trades, strict=True):
        if t.ticker != f.ticker:
            raise RuntimeError(f"FIFO order mismatch: {t.ticker} != {f.ticker}")
        reason, score = meta.get(f.order_id, ("", None))
        avg_cost = t.cost_basis / t.shares if t.shares > 0 else 0.0
        events.append(
            SellEvent(
                order_id=f.order_id,
                ticker=f.ticker,
                sell_date=f.filled_at.strftime("%Y-%m-%d"),
                sell_price=f.price,
                reason=reason or "",
                signal_score=float(score) if score is not None else None,
                shares=t.shares,
                avg_cost=avg_cost,
                entry_date=t.open_date.strftime("%Y-%m-%d"),
                # seed del HWM: aproximamos el fill del BUY con el costo por share
                # (incluye fees: diferencia ~bps, irrelevante para el trail)
                entry_price=avg_cost,
                sell_commission=f.commission,
                sell_slippage=f.slippage,
            )
        )
    return events


VARIANTS: list[tuple[str, str, dict]] = [
    ("a_confirm_next_scan", "confirm_next_scan", {}),
    ("b_score_threshold_025", "score_threshold", {"sell_threshold": 0.25}),
    ("c_min_holding_2d", "min_holding", {"min_holding_days": 2}),
    ("c_min_holding_3d", "min_holding", {"min_holding_days": 3}),
]


def run(
    db_path: Path,
    account_id: int,
    cap_days: int,
    *,
    period: str = DEFAULT_PERIOD,
    atr_from_defaults: bool = False,
    strict_artifacts: bool = True,
) -> tuple[list[ReplayReport], dict]:
    con = sqlite3.connect(str(db_path))
    try:
        # Tarea 99: sin `--account` explícito, la cuenta es la **VIVA** (resuelta
        # contra `is_active`), no el literal 1. La 1 está pausada desde el
        # 2026-07-01 y tiene 91 fills congelados, así que el default viejo no
        # fallaba: medía una cuenta muerta y devolvía una tabla creíble.
        account_id = resolve_account_id(con, account_id)
        events = build_sell_events(con, account_id)
        bar_loader = make_bar_loader(period)

        # Frescura del cohorte antes de pagar la corrida (tarea 101). Este runner
        # entro a la poblacion recien ahora, porque hasta la 102 leia de una tabla
        # vacia y no tocaba el sustrato compartido. Lee las barras y NO el store de
        # senales: replaya fills reales, no senales precomputadas.
        bars_by = {t: b for t in sorted({e.ticker for e in events}) if (b := bar_loader(t))}
        announce_artifacts(bars_by, strict=strict_artifacts)
        ventana = artifact_window(bars_by)
        snaps = load_snapshots(con, account_id)
        real_curve = [(s.snapshot_at.strftime("%Y-%m-%d"), s.total_equity) for s in snaps]
        cap_row = con.execute(
            "SELECT initial_capital FROM paper_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        initial_capital = float(cap_row[0]) if cap_row else 50_000.0
        atr_p = AtrParams() if atr_from_defaults else _atr_params_from_settings()
        if atr_from_defaults:
            print(
                "AVISO: --atr-from-defaults — se corre con los defaults del engine "
                "(stop duro 2.0xATR), que es el desvio que la tarea 92 midio en 7,16 pp "
                "de CAGR. NO es la politica viva.",
                file=sys.stderr,
            )

        reports: list[ReplayReport] = []
        for label, variant, kw in VARIANTS:
            sims = simulate_variant(events, bar_loader, variant, cap_days=cap_days, atr_p=atr_p, **kw)
            rep = build_report(
                variant, sims, real_curve, initial_capital=initial_capital, bar_loader=bar_loader
            )
            rep.variant = label
            reports.append(rep)

        ctx: dict[str, Any] = {
            "db": str(db_path),
            "account_id": account_id,
            "n_sell_events": len(events),
            "n_signal_sells": sum(1 for e in events if e.is_signal_sell),
            "initial_capital": initial_capital,
            "cap_days": cap_days,
            "period": period,
            "ventana_artefactos": str(ventana) if ventana else None,
            "atr_from_defaults": atr_from_defaults,
            "atr_params": vars(atr_p) if not hasattr(atr_p, "__dict__") else atr_p.__dict__,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return reports, ctx
    finally:
        con.close()


def _fmt_pct(x, d=2):
    return "—" if x is None else f"{100 * x:+.{d}f}%"


def render_table(reports: list[ReplayReport], ctx: dict) -> str:
    lines = [
        f"T6.1 exit replay — {ctx['n_sell_events']} SELLs "
        f"({ctx['n_signal_sells']} por señal) · cap {ctx['cap_days']}d · "
        f"capital {ctx['initial_capital']:,.0f}",
        "",
        f"{'variante':<24} {'mod':>4} {'s/dato':>6} {'ΔP/L $':>10} {'ΔP/L pts':>9} "
        f"{'DD real':>8} {'DD sim':>8} {'ratio':>6} {'extra ret':>10} "
        f"{'capture':>8} {'PASS':>5}",
    ]
    for r in reports:
        lines.append(
            f"{r.variant:<24} {r.n_modified:>4} {r.n_skipped_no_data:>6} "
            f"{r.pnl_delta_total:>+10.2f} "
            f"{r.pnl_delta_pts:>+9.2f} {100 * r.max_dd_real:>7.2f}% "
            f"{100 * r.max_dd_sim:>7.2f}% {r.dd_ratio:>6.2f} "
            f"{_fmt_pct(r.median_extra_return):>10} "
            f"{_fmt_pct(r.capture_ratio_median, 0):>8} "
            f"{'✅' if r.passes_kill_criteria else '—':>5}"
        )
        if r.exits_by_reason:
            lines.append(f"{'':<24}   exits: {r.exits_by_reason}")
    lines.append("")
    lines.append(f"Barras: cache Parquet, period {ctx['period']}")
    lines.append("Kill criteria: ΔP/L ≥ +2.00 pts y DD ratio ≤ 1.50")
    lines.append(
        "`s/dato` = eventos modificables que NO se pudieron simular: sin frame, el "
        "dia del fill no es barra, o el SELL es mas nuevo que el cache. Un `mod=0` con "
        "`s/dato=0` es «la variante no cambia nada»; con `s/dato>0` es otra cosa."
    )
    return "\n".join(lines)


def sin_datos_del_todo(reports: list[ReplayReport]) -> bool:
    """¿Se salteó **todo** lo modificable por falta de barras? (tarea 102)

    El fail-open era mudo: con la fuente vacía las cuatro variantes decían `mod=0`
    y `Δ=0`, indistinguible de *"la variante no mueve la aguja"*. Éste es el
    predicado que separa las dos lecturas, y **no tiene flag para saltearlo**: no
    hay ningún caso legítimo de *"corré el replay sin datos"*. Con datos parciales
    el runner sigue — el número está en la columna `s/dato` y se lee.
    """
    modificables = [r for r in reports if r.n_modified + r.n_skipped_no_data > 0]
    return bool(modificables) and all(r.n_modified == 0 for r in modificables)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="T6.1 exit replay harness")
    p.add_argument("--db", default=None)
    p.add_argument(
        "--account",
        type=int,
        default=None,
        help="id de cuenta; sin esto se resuelve la cuenta VIVA contra is_active (tarea 99)",
    )
    p.add_argument("--cap-days", type=int, default=20)
    p.add_argument(
        "--period",
        default=DEFAULT_PERIOD,
        help=f"period del frame Parquet a leer (default {DEFAULT_PERIOD}, el que tiene cobertura)",
    )
    p.add_argument(
        "--allow-stale-artifacts",
        action="store_true",
        help="Sigue aunque el cohorte este desalineado (hay que declararlo en el pre-registro).",
    )
    p.add_argument(
        "--atr-from-defaults",
        action="store_true",
        help="Usa los defaults del engine en vez de la config viva. Los defaults traen "
        "el stop duro a 2.0xATR: la tarea 92 lo midio en 7,16 pp de CAGR.",
    )
    p.add_argument("--json", action="store_true", help="dump JSON a stdout")
    args = p.parse_args(argv)

    db_path = Path(args.db) if args.db else _HERE.parent / DEFAULT_DB
    if not db_path.exists():
        print(f"db no encontrada: {db_path}", file=sys.stderr)
        return 1

    try:
        reports, ctx = run(
            db_path,
            args.account,
            args.cap_days,
            period=args.period,
            atr_from_defaults=args.atr_from_defaults,
            strict_artifacts=not args.allow_stale_artifacts,
        )
    except StaleArtifactError as e:
        print(f"COHORTE DESALINEADO: {e}", file=sys.stderr)
        return 3

    # El fail-open deja de ser mudo (tarea 102): si NO se pudo modificar un solo
    # evento por falta de barras, la tabla diria `mod=0` en las cuatro variantes y
    # se leeria como un resultado. No lo es, y sale distinto de cero.
    if sin_datos_del_todo(reports):
        print(render_table(reports, ctx), file=sys.stderr)
        print(
            f"\nSIN DATOS: los {reports[0].n_skipped_no_data} eventos modificables se "
            f"saltearon por falta de barras (period {ctx['period']}). El resultado de "
            "arriba NO dice que las variantes no cambien nada: dice que no se midio "
            "ninguna. Revisar el cache Parquet o probar otro --period.",
            file=sys.stderr,
        )
        return 2

    if args.json:
        print(
            json.dumps(
                {"context": ctx, "reports": [r.to_dict() for r in reports]},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    else:
        print(render_table(reports, ctx))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
