"""
Background worker para el scanner masivo de leads.

Itera ``get_analyst_data`` sobre un universo de tickers, en paralelo limitado
(respeta el rate limiter global de Yahoo). Emite ``progress`` cada N tickers
para refrescar la barra de la UI. Cancelable.

Output: lista de ``LeadRow`` sin filtrar (la UI aplica filtros sobre el
resultado para que cambiar el slider no re-dispare el scan).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtCore import pyqtSignal

from analysis.leads import LeadRow, compute_lead_score
from config.constants import BULK_FETCH_WORKERS
from config.logging_config import get_logger
from data.failed_tickers import filter_skippable
from data.yahoo_finance import get_analyst_data
from ui.workers import BaseWorker

log = get_logger(__name__)


class LeadsScanWorker(BaseWorker):
    """Escanea un universo de tickers y devuelve LeadRows.

    Emite ``progress(pct, msg)`` periódicamente y ``done(list[LeadRow])`` al final.
    Cancelación cooperativa: chequea ``is_cancelled()`` entre tickers.
    """

    done = pyqtSignal(object)  # list[LeadRow]

    def __init__(self, tickers: list[str], parent=None):
        super().__init__(parent)
        self.tickers = list(tickers)

    def do_work(self) -> list[LeadRow]:
        # UNIV1: los símbolos que Yahoo ya declaró inexistentes (deslistados o
        # renombrados) no se re-consultan. Sin esto, un fallback stale quema ~2
        # requests 404 por ticker muerto en cada scan — presión de throttle gratis.
        tickers, skipped = filter_skippable(self.tickers)
        if skipped:
            log.info(
                "Leads: %d tickers salteados por el failing set: %s",
                len(skipped),
                ", ".join(sorted(skipped)[:10]),
            )

        total = len(tickers)
        if total == 0:
            return []

        rows: list[LeadRow] = []
        completed = 0

        # Paralelizamos al límite que ya respeta el rate limiter global de
        # yfinance — no podemos ir más rápido sin riesgo de 429s.
        with ThreadPoolExecutor(max_workers=BULK_FETCH_WORKERS, thread_name_prefix="leads-scan") as pool:
            future_to_ticker = {pool.submit(get_analyst_data, t): t for t in tickers}

            for fut in as_completed(future_to_ticker):
                if self.is_cancelled():
                    # Cancelamos futuros pendientes; los que ya están corriendo
                    # terminarán y se descartarán.
                    for f in future_to_ticker:
                        f.cancel()
                    log.info("LeadsScanWorker cancelado en %d/%d", completed, total)
                    break

                ticker = future_to_ticker[fut]
                completed += 1
                try:
                    analyst = fut.result()
                    row = compute_lead_score(analyst, ticker)
                    if row is not None:
                        rows.append(row)
                except Exception:
                    log.exception("Failed to score %s", ticker)

                # Progress cada 5 tickers o al final
                if completed % 5 == 0 or completed == total:
                    pct = int(completed / total * 100)
                    self.progress.emit(pct, f"{completed}/{total} — {len(rows)} con datos")

        return rows

    def on_success(self, result):
        self.done.emit(result)
