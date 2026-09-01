"""
Precómputo de la señal ``analyze()`` point-in-time — enabler de la Tarea 7 (y de
las tareas 8/9/11/12/13, que también necesitan la señal PIT).

Qué hace
--------
Para cada ticker del universo, evalúa ``analyze(ticker, bars[:i+1])`` en **cada
barra** desde ``--warmup`` hasta el final, y persiste ``overall_signal`` +
``ml_probability`` por fecha. Ese artefacto convierte el barrido caro (≈5.5 h con
XGBoost) en un costo **único**: después, cualquier variante de política de salida
se replaya en segundos leyendo el JSON.

Por qué el ``analyze()`` completo y no el barato
------------------------------------------------
Medido el 2026-07-20 (ver ``docs/scaleout_trailing_t7_2026-07-20.md`` §2.1):
``enable_xgboost=False`` cuesta 2.7 ms vs 235 ms, pero acuerda solo **75%** con la
señal del engine (recall 74% / precisión 87% sobre el evento SELL). Como el evento
SELL *es* la población del harness de la Tarea 7, se paga la señal real.

Determinismo
------------
``analyze()`` con XGBoost dio 100% de auto-acuerdo in-process (n=300). Aun así el
artefacto se persiste para que los replays posteriores sean reproducibles sin
re-entrenar nada.

Datos
-----
Lee **directo del cache Parquet** (``data/parquet/``), sin pasar por
``yahoo_finance`` → **cero red**, y no toca ``finanzias.db`` (regla 5).

Paralelismo
-----------
El barrido es vergonzosamente paralelo por ticker (cada uno escribe su propio
JSON). XGBoost por defecto usa **todos** los núcleos en cada llamada, así que
correr N procesos sin pinear threads los hace pelearse por el mismo CPU
(oversubscription) y el paralelismo se evapora. Por eso cada worker arranca con
``OMP_NUM_THREADS=1`` y amigos: 1 thread por proceso × N procesos.

Uso
---
    python scripts/precompute_pit_signals.py                    # universo E4, 10y
    python scripts/precompute_pit_signals.py --tickers AAPL,MSFT --period 5y
    python scripts/precompute_pit_signals.py --dry-run          # solo estima costo
    python scripts/precompute_pit_signals.py --workers 1        # serial (debug)

**Resumable:** un JSON por ticker en ``data/pit_signals/``. Un ticker ya completo
se saltea; uno a medias se retoma desde la última fecha persistida.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

DEFAULT_UNIVERSE = "data/harness_universe_41_10y.txt"
OUT_DIR = _HERE.parent / "data" / "pit_signals"
SCHEMA_VERSION = 1

# Variables de entorno que pinean las librerías numéricas a 1 thread por proceso.
# Tienen que estar seteadas ANTES de importar numpy/xgboost (por eso el
# initializer del pool + los imports perezosos dentro de ``run_ticker``).
_THREAD_ENV = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def _init_worker() -> None:
    """Initializer del pool: 1 thread por proceso + sin spam de ml_signals.

    El warning ``val_acc std >8%`` se dispara en casi todas las barras (ver
    Observaciones del backlog): con 92k evaluaciones son 92k líneas inútiles que
    esconderían cualquier error real.
    """
    for var in _THREAD_ENV:
        os.environ[var] = "1"
    logging.getLogger("analysis.ml_signals").setLevel(logging.ERROR)
    logging.getLogger("analysis.garch_signals").setLevel(logging.ERROR)


def _run_ticker_job(job: tuple) -> tuple:
    """Envoltorio picklable para el pool. Devuelve (ticker, computed, total, error)."""
    ticker, period, warmup, save_every = job
    try:
        computed, total = run_ticker(ticker, period, warmup, save_every=save_every, verbose=False)
        return (ticker, computed, total, None)
    except Exception as exc:
        return (ticker, 0, 0, f"{type(exc).__name__}: {exc}")


def _out_path(ticker: str, period: str, warmup: int) -> Path:
    safe = ticker.replace("/", "_").replace("\\", "_")
    return OUT_DIR / f"{safe}__{period}__w{warmup}.json"


def _load_existing(path: Path) -> dict:
    """Artefacto parcial/completo previo, o vacío. Nunca revienta por JSON roto."""
    if not path.exists():
        return {}
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if blob.get("schema_version") != SCHEMA_VERSION:
        return {}
    return blob


def _save(path: Path, ticker: str, period: str, warmup: int, rows: dict, n_bars: int, done: bool) -> None:
    """Escritura atómica (tmp + replace) para que un Ctrl-C no deje JSON truncado."""
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = {
        "schema_version": SCHEMA_VERSION,
        "ticker": ticker,
        "period": period,
        "warmup": warmup,
        "n_bars": n_bars,
        "complete": done,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signals": rows,  # {iso10: [overall_signal, ml_probability|null]}
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def parse_universe_file(path: Path) -> list[str]:
    """Un ticker por línea; ``#`` introduce comentario. (Igual que E4.)

    ``utf-8-sig`` y no ``utf-8``: PowerShell 5.1 —el shell de la máquina de
    Chapa— escribe UTF-8 **con BOM** por default (``Out-File``,
    ``Set-Content -Encoding utf8``), y con ``utf-8`` el BOM se pega al primer
    ticker (``\\ufeffABBV``), que después no encuentra su artefacto PIT y **se cae
    del universo con un simple AVISO**. Sin BOM el comportamiento es idéntico.
    Tarea 41.
    """
    tickers: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "#" in line:
            line = line.split("#", 1)[0]
        for tok in line.strip().split(","):
            t = tok.strip().upper()
            if t:
                tickers.append(t)
    seen, out = set(), []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def pending_dates(df, rows: dict, warmup: int) -> list[str]:
    """Las fechas del frame (desde ``warmup``) que **no** están en el store.

    **Tarea 69 (PITROLL).** Antes esto se decidía por CANTIDAD —``len(rows) >= n -
    warmup``— y con la ventana **rodante** de los artefactos eso miente en las dos
    direcciones: al refrescar, el frame **suelta barras por la cabeza y agrega por
    la cola**, así que ``len(df)`` casi no se mueve mientras las **fechas** cambian;
    y el store **acumula** fechas de ventanas anteriores, o sea que termina con
    *más* filas de las que el frame necesita. Medido el 2026-09-01 sobre AAPL
    después del refresh de la tarea 30: ``len(rows)=2284`` contra ``n-warmup=2263``
    ⇒ la guarda decía **"ya completo"** con **17 fechas faltando**.

    Es la misma familia de defecto que la **48** (la ventana, no el largo) y que la
    **52** (la población, no la ventana), un nivel más abajo: un chequeo por
    cantidad que es ciego a **cuáles** son las barras.
    """
    return [d.strftime("%Y-%m-%d") for d in df.index[warmup:] if d.strftime("%Y-%m-%d") not in rows]


def run_ticker(ticker: str, period: str, warmup: int, *, save_every: int, verbose: bool) -> tuple[int, int]:
    """Devuelve (evaluadas_ahora, total_en_artefacto). No lanza: loguea y sigue."""
    from analysis.technical import analyze
    from data import parquet_cache

    path = _out_path(ticker, period, warmup)
    prev = _load_existing(path)

    # ttl_hours=None → sin chequeo de frescura: para un barrido histórico el frame
    # sirve por viejo que sea (lo que importa es la historia, no la última barra).
    df = parquet_cache.read(ticker, period, "1d", None)
    if df is None or df.empty:
        print(f"  {ticker:<6} SIN CACHE parquet ({period}/1d) — se saltea")
        return 0, 0
    df = df.sort_index()
    n = len(df)
    if n <= warmup:
        print(f"  {ticker:<6} solo {n} barras (<= warmup {warmup}) — se saltea")
        return 0, 0

    rows: dict = dict(prev.get("signals") or {})
    # T69: por FECHAS, no por cantidad. ``complete`` sigue mirándose porque marca
    # un barrido que terminó bien, pero ya no alcanza solo.
    faltan = pending_dates(df, rows, warmup)
    if prev.get("complete") and not faltan:
        print(f"  {ticker:<6} ya completo ({len(rows)} barras) — se saltea")
        return 0, len(rows)

    dates = [d.strftime("%Y-%m-%d") for d in df.index]
    t0 = time.perf_counter()
    computed = 0
    for i in range(warmup, n):
        iso = dates[i]
        if iso in rows:
            continue
        try:
            res = analyze(ticker, df.iloc[: i + 1])
        except Exception as exc:  # una barra rota no puede matar el barrido
            print(f"    {ticker} {iso}: analyze falló ({exc}) — se marca null")
            rows[iso] = [None, None]
            computed += 1
            continue
        if res is None:
            rows[iso] = [None, None]
        else:
            prob = res.ml_probability
            rows[iso] = [res.overall_signal, None if prob is None else round(float(prob), 6)]
        computed += 1
        if computed % save_every == 0:
            _save(path, ticker, period, warmup, rows, n, done=False)
            if verbose:
                el = time.perf_counter() - t0
                rate = computed / el if el > 0 else 0
                left = (n - warmup - len(rows)) / rate if rate > 0 else 0
                print(f"    {ticker} {len(rows)}/{n - warmup} ({rate:.1f}/s, faltan ~{left / 60:.1f} min)")

    _save(path, ticker, period, warmup, rows, n, done=True)
    el = time.perf_counter() - t0
    counts: dict = {}
    for v in rows.values():
        counts[v[0]] = counts.get(v[0], 0) + 1
    print(f"  {ticker:<6} OK {len(rows)} barras (+{computed} nuevas) en {el / 60:5.1f} min  {counts}")
    return computed, len(rows)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Precómputo de la señal analyze() PIT")
    p.add_argument("--universe", default=DEFAULT_UNIVERSE)
    p.add_argument("--tickers", default=None, help="lista separada por comas (pisa --universe)")
    p.add_argument("--period", default="10y")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--save-every", type=int, default=100)
    p.add_argument(
        "--workers",
        type=int,
        default=max(1, min(10, (os.cpu_count() or 2) // 2)),
        help="procesos en paralelo (1 = serial). Default: cores/2, tope 10.",
    )
    p.add_argument("--dry-run", action="store_true", help="solo inventario y estimación")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        upath = _HERE.parent / args.universe
        if not upath.exists():
            print(f"universo no encontrado: {upath}", file=sys.stderr)
            return 1
        tickers = parse_universe_file(upath)

    from data import parquet_cache

    print(f"Universo: {len(tickers)} tickers · period={args.period} · warmup={args.warmup}")
    print(f"Salida:   {OUT_DIR}")

    total_pending = 0
    missing: list[str] = []
    for t in tickers:
        df = parquet_cache.read(t, args.period, "1d", None)
        if df is None or df.empty:
            missing.append(t)
            continue
        prev = _load_existing(_out_path(t, args.period, args.warmup))
        # T69: contar las fechas que faltan, no restar cantidades. Con la ventana
        # rodante, `len(df) - warmup - len(rows)` daba **negativo** (⇒ 0 pendientes)
        # justo cuando el store estaba atrasado.
        total_pending += len(pending_dates(df, dict(prev.get("signals") or {}), args.warmup))
    if missing:
        print(f"SIN cache parquet ({len(missing)}): {', '.join(missing)}")
    # ~330 ms/eval medidos con XGBoost usando todos los núcleos; con los threads
    # pineados a 1 cada eval es más lenta, pero corren N en paralelo.
    est_serial_h = total_pending * 0.330 / 3600
    print(
        f"Barras PIT pendientes: {total_pending:,}  →  ~{est_serial_h:.2f} h serial"
        f" · ~{est_serial_h / max(1, args.workers) * 1.6:.2f} h con {args.workers} workers"
        f" (estimación gruesa)"
    )
    if args.dry_run:
        return 0

    t_start = time.perf_counter()
    grand = 0

    if args.workers == 1:
        _init_worker()
        for k, t in enumerate(tickers, 1):
            print(f"[{k}/{len(tickers)}] {t}", flush=True)
            try:
                done, _ = run_ticker(
                    t, args.period, args.warmup, save_every=args.save_every, verbose=not args.quiet
                )
                grand += done
            except KeyboardInterrupt:
                print("\ninterrumpido — el progreso quedó persistido (resumable)")
                return 130
            except Exception as exc:
                print(f"  {t}: ERROR {exc} — se sigue con el resto", flush=True)
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        jobs = [(t, args.period, args.warmup, args.save_every) for t in tickers]
        print(f"Paralelo: {args.workers} workers (1 thread c/u)", flush=True)
        try:
            with ProcessPoolExecutor(max_workers=args.workers, initializer=_init_worker) as pool:
                futures = {pool.submit(_run_ticker_job, j): j[0] for j in jobs}
                for k, fut in enumerate(as_completed(futures), 1):
                    ticker, computed, total, err = fut.result()
                    grand += computed
                    el = (time.perf_counter() - t_start) / 60
                    if err:
                        print(f"[{k}/{len(jobs)}] {ticker:<6} ERROR {err}", flush=True)
                    else:
                        print(
                            f"[{k}/{len(jobs)}] {ticker:<6} {total:5d} barras "
                            f"(+{computed}) · {el:5.1f} min transcurridos",
                            flush=True,
                        )
        except KeyboardInterrupt:
            print("\ninterrumpido — el progreso quedó persistido (resumable)")
            return 130

    print(f"\nListo: {grand:,} evaluaciones nuevas en {(time.perf_counter() - t_start) / 3600:.2f} h")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
