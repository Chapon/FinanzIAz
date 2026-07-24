"""
Detector de **insider cluster buys** (SEC Form 4) — enabler de la **Tarea 12 (FORM4)**.

Pre-registro CONGELADO (kill-criteria ANTES de codear):
``docs/insider_cluster_prereg_t12_2026-07-24.md``.

Qué detecta (§2 del pre-registro, forma congelada — sin sweep en el brazo primario)
-----------------------------------------------------------------------------------
Sobre una lista de transacciones de insiders ya normalizadas (una fila por línea
de ``NONDERIV_TRANS`` joineada con su submission y su reporting-owner), un issuer
dispara un **evento de cluster** en la **fecha de filing** ``f`` de una compra que
cumple el filtro, si el número de **CIK de insider distintos** con una compra que
cumple el filtro cuya ``filing_date ∈ [f − W + 1, f]`` es **≥ C**.

Filtro de transacción (CONGELADO): solo cuentan las compras open-market —
``trans_code == "P"`` **y** ``acq_disp == "A"`` **y** ``shares > 0`` **y**
``price > 0``. Se ignoran ventas (``S``), grants/awards (``A`` como código),
ejercicios de opciones (``M``), disposiciones por impuestos (``F``), y todo lo
derivativo (que ni siquiera llega acá: el ingester solo emite ``NONDERIV_TRANS``).

Point-in-time por diseño: se usa ``filing_date`` (fecha oficial de disclosure),
**NO** ``transaction_date`` — el cluster solo es conocible cuando los filings son
públicos; usar la fecha de la operación sería look-ahead. El Form 4 se publica
dentro de los 2 días hábiles del trade, así que el ``filing_date`` es dato duro y
sin sesgo de revisión (a diferencia del consenso point-in-time que bloquea el
Brazo A de la T11 / T-CAT-5b).

Dedup / re-arm (calendario-nativo, sin depender del calendario de trading): tras
un evento aceptado en un ticker, no se emite otro hasta que el conteo distinto en
la ventana **vuelve a caer por debajo de C** (o hasta que pasó una ventana entera
desde el último disparo, lo que evita perder un cluster genuinamente nuevo de
same-day filings). El **refractario de 20 ruedas** (que es "ruedas" = días de
trading) NO se aplica acá: lo aplica el **harness** al mapear eventos → entradas
contra el calendario de precios, donde "rueda" está definida. Así el detector
queda agnóstico del pipeline (mismo criterio que ``anomaly_signal``).

Módulo **puro** (stdlib): las transacciones entran como ``list[InsiderTx]`` y los
tests corren offline con datos sintéticos. No decide nada por sí solo (regla 3):
solo emite candidatos; quién los consume vive en el harness (y, si pasa el
kill-criteria, en el engine detrás de un flag default OFF).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

MIN_INSIDERS = 3          # C congelado (brazo primario)
WINDOW_DAYS = 15          # W congelado (días calendario)
DEFAULT_REFRACTORY = 20   # ruedas — lo aplica el HARNESS, no el detector


@dataclass(frozen=True)
class InsiderTx:
    """Una transacción no-derivativa de un insider, ya normalizada por el ingester.

    ``filing_date`` es ISO ``YYYY-MM-DD`` (fecha oficial de disclosure, point-in-time).
    ``owner_cik`` es la clave de conteo distinto; ``accession`` la de dedup.
    """

    issuer_ticker: str
    filing_date: str      # ISO YYYY-MM-DD
    owner_cik: str
    trans_code: str       # "P", "S", "A", "M", "F", ...
    acq_disp: str         # "A" (adquisición) / "D" (disposición)
    shares: float
    price: float
    accession: str = ""
    is_officer: bool = False
    is_director: bool = False


@dataclass(frozen=True)
class ClusterParams:
    """Definición del cluster. Lo único que barre la grilla del harness es (C, W)
    y ``require_officer``; el resto de la forma está congelado (§2)."""

    min_insiders: int = MIN_INSIDERS   # C
    window_days: int = WINDOW_DAYS     # W (días calendario)
    require_officer: bool = False      # arm CLU_C3_W15_senior


@dataclass(frozen=True)
class ClusterEvent:
    """Un cluster observable point-in-time. ``event_date`` es la ``filing_date``
    del filing que hace cruzar el conteo distinto a ≥ C dentro de la ventana."""

    ticker: str
    event_date: str        # ISO YYYY-MM-DD
    n_insiders: int        # CIK distintos en la ventana al disparar
    total_dollars: float   # Σ shares·price de las compras en la ventana (ranking $)
    has_officer: bool


def _finite_pos(x: float | None) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x) and x > 0


def passes_purchase_filter(tx: InsiderTx) -> bool:
    """True si ``tx`` es una compra open-market que cuenta para el cluster (§2)."""
    return (
        tx.trans_code == "P"
        and tx.acq_disp == "A"
        and bool(tx.owner_cik)
        and _finite_pos(tx.shares)
        and _finite_pos(tx.price)
    )


def _parse_iso(d: str) -> date | None:
    try:
        return date.fromisoformat(d)
    except (ValueError, TypeError):
        return None


def build_cluster_events(
    txs: list[InsiderTx],
    params: ClusterParams = ClusterParams(),
) -> list[ClusterEvent]:
    """Eventos de cluster ``(ticker, event_date, ...)`` a partir de transacciones.

    Agrupa por issuer, filtra a compras open-market (§2), y para cada fecha de
    filing computa el conteo de ``owner_cik`` distintos en la ventana móvil
    ``[f − W + 1, f]`` (días calendario). Dispara la **primera** vez que el conteo
    cruza ≥ C; re-arma cuando cae por debajo de C (o al pasar una ventana entera).

    Determinista: eventos ordenados por (event_date, ticker). Fail-safe: transacciones
    con fecha inválida o que no pasan el filtro se ignoran; nunca rompe.
    """
    C = max(1, int(params.min_insiders))
    W = max(1, int(params.window_days))

    # Agrupar compras válidas por ticker, con la fecha ya parseada.
    by_ticker: dict[str, list[tuple[date, InsiderTx]]] = {}
    for tx in txs:
        if not passes_purchase_filter(tx):
            continue
        d = _parse_iso(tx.filing_date)
        if d is None:
            continue
        by_ticker.setdefault(tx.issuer_ticker, []).append((d, tx))

    out: list[ClusterEvent] = []
    for ticker, dated in by_ticker.items():
        dated.sort(key=lambda dt: (dt[0], dt[1].accession))
        unique_dates = sorted({d for d, _ in dated})
        armed = True
        last_fire: date | None = None
        for f in unique_dates:
            lo = f - timedelta(days=W - 1)
            window = [tx for d, tx in dated if lo <= d <= f]
            owners = {tx.owner_cik for tx in window}
            count = len(owners)
            officer_ok = (not params.require_officer) or any(tx.is_officer for tx in window)

            # Re-arm: la ventana ya no tiene un cluster activo (cayó < C) o pasó
            # una ventana entera desde el último disparo (cluster nuevo posible).
            if count < C or (last_fire is not None and (f - last_fire).days >= W):
                armed = True

            if armed and count >= C and officer_ok:
                dollars = sum(tx.shares * tx.price for tx in window)
                out.append(
                    ClusterEvent(
                        ticker=ticker,
                        event_date=f.isoformat(),
                        n_insiders=count,
                        total_dollars=dollars,
                        has_officer=any(tx.is_officer for tx in window),
                    )
                )
                last_fire = f
                armed = False

    out.sort(key=lambda e: (e.event_date, e.ticker))
    return out
