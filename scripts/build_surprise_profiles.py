"""
T-CAT-5a builder — per-ticker EPS surprise profiles (v0 *gratis*).

Sprint 5 · Catalyst Intelligence Engine. For each ticker in the account's
universe (watchlist ∪ open positions) it fetches the past-earnings surprise
history from yfinance, aggregates it into a :class:`SurpriseProfile`, and writes
a JSON snapshot consumed at runtime by ``imminent_catalyst`` (the exit-veto's
directional prior). Prints a summary ranked by directional score.

Network-bound (yfinance) and read-only on the DB (only resolves the universe).
Safe to run anytime; intended cadence is roughly weekly — surprise track records
move only when a new quarter prints.

⚠️  v0 caveat: yfinance reports its *current* estimate per past quarter, not the
consensus as of the day before the print (revision/look-ahead bias). The clean
point-in-time path is T-CAT-5b (blocked until the daily ``analyst_estimate_snapshots``
accumulate one earnings season). See docs/roadmap_v3_2026-06-09.md.

Usage
-----
    python scripts/build_surprise_profiles.py
    python scripts/build_surprise_profiles.py --account-id 1 --limit 16
    python scripts/build_surprise_profiles.py --out data/catalyst/surprise_profiles.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.surprise_score import MIN_QUARTERS, PROFILES_PATH, build_surprise_profile
from config.logging_config import get_logger
from data.news_sources import collect_yfinance_earnings_history
from scripts.harvest_catalysts import DEFAULT_ACCOUNT_ID, resolve_universe

log = get_logger(__name__)

# La ruta la declara `analysis.surprise_score` (tarea 160): la cadencia del
# scheduler se lee del `_meta.built_at` de ESTE archivo, así que el que lo escribe
# y el que lo lee tienen que hablar del mismo path o la marca no se ve.
DEFAULT_OUT = PROFILES_PATH


def build_profiles(tickers: list[str], limit: int = 16) -> dict[str, dict]:
    profiles: dict[str, dict] = {}
    for t in tickers:
        rows = collect_yfinance_earnings_history(t, limit=limit)
        prof = build_surprise_profile(t, rows)
        profiles[t] = prof.to_dict()
        log.info(
            "surprise %s: n=%d dir=%.3f beat=%.2f mean=%.3f",
            t,
            prof.n_quarters,
            prof.directional_score,
            prof.beat_rate,
            prof.mean_surprise,
        )
    return profiles


def split_by_min_quarters(profiles: dict[str, dict]) -> tuple[dict[str, dict], dict[str, int]]:
    """Separa los perfiles **usables** de los que no llegan al mínimo — Tarea 126.

    El archivo declaraba ``min_quarters`` en su ``_meta`` y escribía igual los que no
    lo alcanzan, **con todos los campos en cero**. Producción no se veía afectada —
    ``SurpriseProfile.is_usable`` y el gate de ``imminent_catalyst`` los descartan y
    caen al ``basis="reaction"``— pero **cualquier lectura ad-hoc del JSON** ve un
    ``directional_score: 0.0`` que es indistinguible de un neutral medido sobre 24
    trimestres. Un archivo que declara un filtro tiene que cumplirlo.

    No se tiran: van a ``_meta.insufficient_history`` con su ``n_quarters``, para no
    perder el *"se intentó y no había datos"* — que es distinto de *"no se intentó"*.
    """
    usables = {t: p for t, p in profiles.items() if p.get("n_quarters", 0) >= MIN_QUARTERS}
    cortos = {t: int(p.get("n_quarters", 0)) for t, p in profiles.items() if t not in usables}
    return usables, cortos


def _payload(profiles: dict[str, dict], n_tickers: int) -> dict:
    usables, cortos = split_by_min_quarters(profiles)
    return {
        "_meta": {
            "built_at": datetime.now(timezone.utc).isoformat(),
            "source": "yfinance.get_earnings_dates",
            "version": "v0-free-T-CAT-5a",
            "caveat": "current-estimate per quarter, not point-in-time (T-CAT-5b replaces this)",
            "min_quarters": MIN_QUARTERS,
            "n_tickers": n_tickers,
            # `n_tickers` es cuántos se INTENTARON; `n_profiles` cuántos entraron.
            # Antes coincidían porque entraban todos, incluidos los que no llegaban
            # al mínimo — que es justo lo que la 126 vino a cerrar.
            "n_profiles": len(usables),
            "insufficient_history": cortos,
        },
        "profiles": usables,
    }


# Tarea 397: una respuesta vacía de `get_earnings_dates` borraba el perfil de un ticker por una
# semana, sin aviso (ACN el 2026-10-26: n=24 el 19/10, n=0 ese día, 25 filas media hora después).
# Un ticker que la corrida anterior tenía con perfil y hoy viene corto se reintenta una vez y, si
# sigue corto, conserva el perfil anterior con la fecha desde la que se conserva. Pasado este
# plazo deja de conservarse: un deslistado (WBD) cae a `insufficient_history` como antes.
MAX_DIAS_CONSERVADO = 28


def perfiles_anteriores(out_path: str | Path) -> tuple[dict[str, dict], str | None]:
    """Los perfiles usables del archivo anterior y su ``built_at``; vacío si no hay o no se lee."""
    try:
        d = json.loads(Path(out_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, None
    return d.get("profiles") or {}, (d.get("_meta") or {}).get("built_at")


def conservar_caidos(
    profiles: dict[str, dict],
    anteriores: dict[str, dict],
    built_at_anterior: str | None,
    ahora: datetime,
    reintentar=None,
) -> list[str]:
    """Conserva el perfil anterior de los que hoy vinieron cortos (tarea 397). Devuelve cuáles.

    Modifica ``profiles``. ``reintentar(t)`` devuelve el perfil de un segundo intento.
    """
    conservados = []
    for t, prof in profiles.items():
        if prof.get("n_quarters", 0) >= MIN_QUARTERS or t not in anteriores:
            continue
        if reintentar is not None:
            otro = reintentar(t)
            if otro.get("n_quarters", 0) >= MIN_QUARTERS:
                profiles[t] = otro
                log.warning(
                    "surprise %s: vino vacío y el reintento trajo n=%d (tarea 397)", t, otro["n_quarters"]
                )
                continue
        previo = dict(anteriores[t])
        desde = previo.get("conservado_desde") or built_at_anterior
        try:
            vencido = desde is None or (ahora - datetime.fromisoformat(desde)).days > MAX_DIAS_CONSERVADO
        except (TypeError, ValueError):
            vencido = True
        if vencido:
            continue
        previo["conservado_desde"] = desde
        profiles[t] = previo
        conservados.append(t)
        log.warning(
            "surprise %s: vino con n=%d y la corrida anterior tenía n=%d: se conserva el perfil anterior "
            "(desde %s) (tarea 397)",
            t,
            prof.get("n_quarters", 0),
            previo.get("n_quarters", 0),
            desde,
        )
    return conservados


def run_build(
    account_id: int | None = DEFAULT_ACCOUNT_ID,  # T70: None => la cuenta viva
    limit: int = 16,
    out: str | Path = DEFAULT_OUT,
) -> dict:
    """Resolve the universe, build every profile, write the JSON snapshot.

    Single source of truth shared by the CLI (``main``) and the in-app weekly
    scheduler worker (``paper_trading.scheduler.SurpriseBuildWorker``). Returns a
    small result dict: ``{"out", "n_tickers", "n_usable", "profiles"}``. Network-
    bound (yfinance) and read-only on the DB (only resolves the universe).
    """
    tickers = resolve_universe(account_id)
    log.info("building surprise profiles for %d tickers", len(tickers))
    profiles = build_profiles(tickers, limit=limit)

    out_path = Path(out)
    anteriores, built_at_anterior = perfiles_anteriores(out_path)
    conservados = conservar_caidos(
        profiles,
        anteriores,
        built_at_anterior,
        datetime.now(timezone.utc),
        reintentar=lambda t: build_profiles([t], limit=limit)[t],
    )
    caidos = sorted(
        t for t in anteriores if t in profiles and profiles[t].get("n_quarters", 0) < MIN_QUARTERS
    )
    if caidos:
        log.warning("surprise: tenían perfil la corrida anterior y hoy no: %s (tarea 397)", ", ".join(caidos))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # `newline` explicito (tarea 173): este JSON esta VERSIONADO y el repo lo guarda en LF.
    # Sin esto, `write_text` traduce cada salto a CRLF en Windows y el archivo queda
    # desalineado contra su blob en cada corrida del scheduler. Mismo arreglo que la 165,
    # que a este writer lo habia excluido llamandolo "artefacto no versionado".
    out_path.write_text(
        json.dumps(_payload(profiles, len(tickers)), indent=2), encoding="utf-8", newline="\n"
    )
    n_usable = sum(1 for p in profiles.values() if p.get("n_quarters", 0) >= MIN_QUARTERS)
    return {
        "out": str(out_path),
        "n_tickers": len(tickers),
        "n_usable": n_usable,
        "profiles": profiles,
        "conservados": conservados,
        "caidos": caidos,
    }


def _print_summary(profiles: dict[str, dict]) -> None:
    rows = [(t, p) for t, p in profiles.items() if p.get("n_quarters", 0) >= MIN_QUARTERS]
    rows.sort(key=lambda r: r[1].get("directional_score", 0.0), reverse=True)
    print(f"\nSurprise profiles (n ≥ {MIN_QUARTERS} quarters), by directional score:")
    print(f"  {'ticker':<8} {'n':>3} {'dir':>7} {'beat%':>7} {'meanSurp':>9} {'lastSurp':>9}")
    for t, p in rows:
        print(
            f"  {t:<8} {p['n_quarters']:>3} {p['directional_score']:>7.3f} "
            f"{p['beat_rate'] * 100:>6.1f}% {p['mean_surprise'] * 100:>8.2f}% "
            f"{p['last_surprise'] * 100:>8.2f}%"
        )
    skipped = len(profiles) - len(rows)
    if skipped:
        print(f"  ({skipped} ticker(s) with < {MIN_QUARTERS} usable quarters → neutral, omitted)")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="T-CAT-5a surprise-profile builder (v0 free).")
    p.add_argument(
        "--account-id", type=int, default=DEFAULT_ACCOUNT_ID, help="Account whose universe to use."
    )
    p.add_argument("--limit", type=int, default=16, help="Max past quarters to pull per ticker.")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="Output JSON path.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    res = run_build(account_id=args.account_id, limit=args.limit, out=args.out)
    print(
        f"Wrote {res['out']} — {res['n_tickers']} tickers, "
        f"{res['n_usable']} with ≥ {MIN_QUARTERS} usable quarters."
    )
    _print_summary(res["profiles"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
