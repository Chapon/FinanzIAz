"""Probe T196 — ¿responden las fuentes del harvest desde una IP de datacenter?

Diagnóstico, **no** código de producción: no toca la DB, no escribe nada, no importa
nada del repo. Única dependencia externa: `pip install yfinance` — SEC y la IP saliente
van por `urllib` de la stdlib a propósito, para no arrastrar el stack de la app.

**Qué pregunta.** El riesgo #1 de la tarea 196 es que Yahoo limite o bloquee las IPs
de datacenter. Si yfinance no responde desde ahí, no se puede mudar ni el harvest de
noticias ni —lo que importa de verdad— el **snapshot de consenso**, que es 100%
yfinance y es lo único que no se puede volver a bajar
(ver `docs/harvest_nube_t196_2026-09-14.md` §2 y §5).

**Qué NO contesta.** Corre en los runners de GitHub (Azure). Yahoo bloquea por
reputación de rango, y los rangos de **AWS** son los más castigados, así que un
resultado verde acá **no** demuestra que Lambda funcione: sólo descarta el fracaso
más barato de descubrir. Un resultado rojo, en cambio, sí es concluyente en el sentido
útil — si ya falla desde Azure, no hace falta abrir nada en AWS.

**Por qué el resultado sale por anotaciones.** Los logs de Actions piden
autenticación; la API de anotaciones responde sin token. Así que el veredicto se
emite con ``::warning::``/``::error::`` para poder leerlo desde afuera (tarea 65).

Uso:
    python scripts/probe_yahoo_datacenter_t196.py
    python scripts/probe_yahoo_datacenter_t196.py --tickers NVDA,KO
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

# Cinco del universo vivo, elegidos para no depender de un solo perfil: mega-cap
# tecnológica, consumo defensivo, y una con mucha cobertura de analistas.
DEFAULT_TICKERS = ["NVDA", "AAPL", "MSFT", "TSLA", "KO"]

# Apple. Sólo se usa para ver si EDGAR contesta; el CIK concreto da igual.
SEC_PROBE_URL = "https://data.sec.gov/submissions/CIK0000320193.json"
SEC_UA = os.environ.get("SEC_EDGAR_USER_AGENT", "FinanzIAs probe t196 (contacto en el repo)")


def _ip_saliente() -> str:
    """La IP pública del runner, best-effort. Sirve para dejar asentado que es datacenter."""
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=10) as r:
            return r.read().decode("utf-8", "replace").strip()
    except Exception as exc:  # pragma: no cover — diagnóstico
        return f"desconocida ({type(exc).__name__})"


def _probe_sec() -> tuple[bool, str]:
    req = urllib.request.Request(SEC_PROBE_URL, headers={"User-Agent": SEC_UA})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read().decode("utf-8", "replace"))
        dt = time.monotonic() - t0
        return (
            True,
            f"HTTP {r.status}, {len(payload.get('filings', {}).get('recent', {}).get('form', []))} forms, {dt:.1f}s",
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _probe_yf(ticker: str) -> tuple[bool, str, bool, str]:
    """``(news_ok, news_detalle, est_ok, est_detalle)`` para un ticker."""
    import yfinance as yf

    t = yf.Ticker(ticker)

    t0 = time.monotonic()
    try:
        news = t.news or []
        news_ok, news_det = True, f"{len(news)} items, {time.monotonic() - t0:.1f}s"
        if not news:
            # Una lista vacía no es un error de red, pero tampoco es un éxito: es
            # exactamente la forma que toma un bloqueo silencioso de Yahoo.
            news_ok, news_det = False, f"lista VACIA (sin excepción), {time.monotonic() - t0:.1f}s"
    except Exception as exc:
        news_ok, news_det = False, f"{type(exc).__name__}: {str(exc)[:120]}"

    t0 = time.monotonic()
    try:
        df = t.earnings_estimate
        n = 0 if df is None else len(df)
        est_ok, est_det = n > 0, f"{n} filas, {time.monotonic() - t0:.1f}s"
        if n == 0:
            est_det = f"VACIO (sin excepción), {time.monotonic() - t0:.1f}s"
    except Exception as exc:
        est_ok, est_det = False, f"{type(exc).__name__}: {str(exc)[:120]}"

    return news_ok, news_det, est_ok, est_det


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", default=",".join(DEFAULT_TICKERS), help="lista separada por comas")
    args = ap.parse_args(argv)
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    print(f"IP saliente: {_ip_saliente()}")
    print(f"Tickers: {', '.join(tickers)}\n")

    sec_ok, sec_det = _probe_sec()
    print(f"{'SEC EDGAR':<12} {'OK' if sec_ok else 'FALLA':<6} {sec_det}")
    print()

    print(f"{'ticker':<8} {'news':<6} {'detalle':<46} {'estimates':<10} detalle")
    news_ok_n = est_ok_n = 0
    for tk in tickers:
        n_ok, n_det, e_ok, e_det = _probe_yf(tk)
        news_ok_n += n_ok
        est_ok_n += e_ok
        print(f"{tk:<8} {'OK' if n_ok else 'FALLA':<6} {n_det:<46} {'OK' if e_ok else 'FALLA':<10} {e_det}")

    n = len(tickers)
    resumen = (
        f"T196 probe desde datacenter — yfinance news {news_ok_n}/{n}, "
        f"yfinance estimates {est_ok_n}/{n}, SEC EDGAR {'OK' if sec_ok else 'FALLA'}"
    )
    print(f"\n{resumen}")

    # El veredicto va por anotación: los logs de Actions piden token, las anotaciones no.
    todo_bien = news_ok_n == n and est_ok_n == n and sec_ok
    nivel = "warning" if todo_bien else "error"
    print(f"::{nivel}::{resumen}")

    # Siempre 0: esto es un diagnóstico, no un gate. Un rojo acá no es un CI roto.
    return 0


if __name__ == "__main__":
    sys.exit(main())
