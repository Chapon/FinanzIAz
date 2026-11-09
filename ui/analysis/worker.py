"""
Background worker for the Analysis tab.

Migrated to ``BaseWorker`` so error/cancellation handling is consistent with
the rest of the UI.
"""

from __future__ import annotations

from datetime import date, timedelta

from PyQt6.QtCore import pyqtSignal

from analysis.technical import analyze
from config.logging_config import get_logger
from config.settings_manager import settings
from data.yahoo_finance import (
    get_analyst_data,
    get_company_info,
    get_current_price,
    get_historical_data,
)
from ui.workers import BaseWorker

log = get_logger(__name__)

# Los fundamentals guardados se rehacen si tienen más de esto: los anuales cambian una vez por
# año, pero un 10-K nuevo o una enmienda no tienen fecha fija.
REFRESCO_FUNDAMENTALS_DIAS = 30


def valuacion_de(ticker: str, precio: float | None):
    """La valuación de la tarea 383, o ``None``. Nunca levanta: la tarjeta se calla si falla.

    Los fundamentals salen del almacén de la 382; si el ticker no está o están viejos, se bajan
    de EDGAR y se guardan. Los cierres, ajustados por splits y no por dividendos.
    """
    try:
        from analysis.valuation import valuar
        from data import fundamentos_pit as fp
        from data.yahoo_finance import get_cierres_sin_ajuste_por_dividendos, get_split_events

        fund = fp.cargar(ticker)
        viejo = (date.today() - timedelta(days=REFRESCO_FUNDAMENTALS_DIAS)).isoformat()
        if fund is None or fund.generado < viejo:
            nuevo = fp.construir(ticker)
            if nuevo is not None:
                fp.guardar(nuevo)
                fund = nuevo
        cierres = get_cierres_sin_ajuste_por_dividendos(ticker)
        if precio is None and cierres:
            precio = cierres[-1][1]
        manana = (date.today() + timedelta(days=1)).isoformat()
        v = valuar(fund, precio, cierres, manana, get_split_events(ticker))
        if v is not None:
            v.calidad = calidad_en_el_universo(ticker, fund, manana)
        return v
    except Exception:
        log.exception("Valuación de %s: falló (la tarjeta no se muestra)", ticker)
        return None


# Los fundamentals del almacén, una vez por día y por proceso: son 126 archivos.
_POBLACION: dict[str, dict] = {}


def calidad_en_el_universo(ticker: str, fund, fecha: str) -> dict | None:
    """El puntaje de calidad de la tarea 384 del ticker, con percentiles contra el almacén de la 382.

    La población es todo lo que hay en ``data/fundamentals_pit/`` (el universo de la cuenta 2 y lo
    que se haya analizado). Todos —el ticker incluido— se miden con lo presentado antes del
    ``generado`` más viejo del almacén (tarea 394): el ticker abierto se acaba de rehacer y sus
    pares no, y en temporada de 10-K eso comparaba su año nuevo contra el año viejo de los demás.
    ``al`` es ese corte, para que la tarjeta lo diga. ``None`` si no llega a dos patas. Nunca levanta.
    """
    try:
        from analysis.calidad import corte_comun, patas_de, puntajes
        from data import fundamentos_pit as fp

        if fecha not in _POBLACION:
            _POBLACION.clear()
            _POBLACION[fecha] = {
                p.stem: fp.cargar(p.stem, p.parent) for p in sorted(fp.STORE_DIR.glob("*.json"))
            }
        fundamentos = dict(_POBLACION[fecha])
        fundamentos[ticker.upper()] = fund
        corte = corte_comun(fundamentos, fecha)
        r = puntajes({t: patas_de(f, corte) for t, f in fundamentos.items()})[ticker.upper()]
        if r["puntaje"] is None:
            return None
        return {"puntaje": r["puntaje"], "percentiles": r["percentiles"], "n": len(fundamentos), "al": corte}
    except Exception:
        log.exception("Calidad de %s: falló", ticker)
        return None


class AnalysisWorker(BaseWorker):
    """
    Fetches OHLCV history + current price + company info + analyst recos for a
    ticker, then runs the full ``analyze`` pipeline. Emits
    ``done(df, result, price_data, company_info, analyst_data)`` on success.
    """

    # df, result, price_data, company_info, analyst_data, valuacion (tarea 383)
    done = pyqtSignal(object, object, object, object, object, object)

    def __init__(self, ticker: str, period: str):
        super().__init__()
        self.ticker = ticker
        self.period = period

    def do_work(self) -> tuple:
        df = get_historical_data(self.ticker, period=self.period)
        result = (
            analyze(
                self.ticker,
                df,
                enable_sma_cross=settings.get("sma_cross"),
                enable_xgboost=True,
            )
            if df is not None
            else None
        )
        price_data = get_current_price(self.ticker)
        company = get_company_info(self.ticker)
        analyst = get_analyst_data(self.ticker)
        precio = price_data.get("price") if isinstance(price_data, dict) else None
        valuacion = valuacion_de(self.ticker, precio)
        return df, result, price_data, company, analyst, valuacion

    def on_success(self, result: tuple) -> None:
        df, ar, price_data, company, analyst, valuacion = result
        self.done.emit(df, ar, price_data, company, analyst, valuacion)
