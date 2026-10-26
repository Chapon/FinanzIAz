"""
Fundamentals **point-in-time** desde EDGAR ``companyfacts`` — tarea 382.

Para que la valuación (383), el puntaje de calidad (384) y la cartera de largo plazo (385)
puedan preguntar *«qué se sabía de esta empresa en tal fecha»* sin mirar el futuro. No decide
nada: es la capa de datos.

Por qué un módulo aparte de ``data.edgar_fundamentals``
-------------------------------------------------------
Ése alimenta el screen de la E1b y su orden de conceptos de revenue es **contrato** (tarea
150): cortar en el primer concepto que resuelve. Acá hace falta otra cosa —la serie entera,
con la fecha en que se supo cada número—, así que se parsea aparte y aquél no se toca.

Cómo se arma
------------
- Cada dato de ``companyfacts`` trae ``end`` (fin del período), ``filed`` (cuándo se presentó),
  ``form``, ``fp`` y el valor. Verificado contra el payload real el 2026-10-21.
- Sólo datos **anuales**: de un 10-K / 20-F / 40-F (o su enmienda ``/A``) con ``fp == "FY"``.
  Los de flujo (ganancia, ventas) además tienen que cubrir ~un año; los de stock (patrimonio,
  deuda) son instantáneos. Un 10-K trae también los años anteriores como comparativos, y se
  guardan: son números que se conocían desde ese ``filed``.
- **Cascada de tags por año, no por empresa.** Las empresas cambian de tag (en 2018, con la norma
  de ingresos ASC 606, media muestra pasó de ``SalesRevenueNet`` a
  ``RevenueFromContractWithCustomer…``). Elegir un tag por empresa cortaría la serie. Para
  cada fin de período manda el tag de más arriba en ``CONCEPTOS`` que tenga dato.
- **CIK predecesores.** Una empresa que se re-registra pierde la historia en su CIK nuevo (XOM,
  BLK y MRVL, verificados el 2026-10-21; la 149 lo había visto y sólo lo declaró). Se unen los
  datos de los dos.
- **La regla point-in-time:** ``al(fecha)`` usa sólo los datos con ``filed < fecha``. Estricto a
  propósito: un 10-K se suele presentar después del cierre, así que el mismo día no vale. Si el
  mismo período se presentó más de una vez (comparativos de años siguientes, enmiendas), manda
  el último presentado **antes** de la fecha.
- **Extranjeras:** una empresa que reporta en ifrs-full o por 20-F queda marcada. Su ganancia por
  acción puede venir en otra moneda y no se compara con el precio del ADR (TSM: dólares
  taiwaneses, 1 ADR = 5 acciones).

Lo que NO cubre, medido sobre el universo de la cuenta 2 el 2026-10-21: la ganancia bruta no
existe para bancos, eléctricas, REITs y transporte (87 de 126 la tienen, directa o como ventas
menos costo de ventas); Visa reporta el EPS por clase de acción, que ``companyfacts`` no trae.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from config.logging_config import get_logger

log = get_logger(__name__)

SCHEMA_VERSION = 1
STORE_DIR = Path(__file__).resolve().parent / "fundamentals_pit"

# Por concepto, los tags en orden de preferencia. El de más arriba que tenga dato para un
# período manda en ese período. Los us-gaap van antes que los ifrs-full.
CONCEPTOS: dict[str, tuple[str, ...]] = {
    "ganancia_neta": (
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "ProfitLoss",
        "ProfitLossAttributableToOwnersOfParent",
    ),
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "RevenuesNetOfInterestExpense",
        "PremiumsEarnedNet",
        "Revenue",
    ),
    "ganancia_bruta": ("GrossProfit",),
    "costo_ventas": (
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
        "CostOfServices",
    ),
    "patrimonio": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "EquityAttributableToOwnersOfParent",
    ),
    "activos": ("Assets",),
    "deuda_lp": (
        "LongTermDebtNoncurrent",
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
    ),
    "eps_diluido": (
        "EarningsPerShareDiluted",
        "DilutedEarningsLossPerShare",
        "EarningsPerShareBasicAndDiluted",
        "EarningsPerShareBasic",
    ),
    "acciones_diluidas": (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasicAndDiluted",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ),
    "dividendo_x_accion": (
        "CommonStockDividendsPerShareDeclared",
        "CommonStockDividendsPerShareCashPaid",
    ),
    "flujo_operativo": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "CashFlowsFromUsedInOperatingActivities",
    ),
}

# Los de stock son instantáneos (un balance a una fecha); el resto cubre un período.
INSTANTANEOS = frozenset({"patrimonio", "activos", "deuda_lp"})
# Los que cambian con un split: los por acción se dividen y la cantidad de acciones se multiplica.
POR_ACCION = frozenset({"eps_diluido", "dividendo_x_accion", "acciones_diluidas"})
UNIDADES: dict[str, str] = {
    "eps_diluido": "USD/shares",
    "dividendo_x_accion": "USD/shares",
    "acciones_diluidas": "shares",
}
_TAXONOMIAS = ("us-gaap", "ifrs-full")
_FORMULARIOS_ANUALES = ("10-K", "20-F", "40-F")

# Re-registros: el CIK que da hoy el mapa de la SEC no tiene la historia. Verificados uno por
# uno contra `entityName` y las fechas de sus 10-K el 2026-10-21; cada historia empalma con la
# del CIK nuevo.
CIK_PREDECESORES: dict[str, tuple[int, ...]] = {
    "XOM": (34088,),  # Exxon Mobil Corporation, 10-K 2010 → 2026-02; el nuevo es un holding
    "BLK": (1364742,),  # hoy «BlackRock Finance», 10-K 2010 → 2024-02; el nuevo, desde 2024-11
    "MRVL": (1058057,),  # Marvell Technology Group (Bermudas), 10-K 2010 → 2021-03
}


@dataclass(frozen=True)
class Registro:
    concepto: str
    end: str
    filed: str
    val: float
    form: str
    tag: str


def _es_anual(e: dict, instantaneo: bool) -> bool:
    if e.get("fp") != "FY":
        return False
    if not str(e.get("form") or "").startswith(_FORMULARIOS_ANUALES):
        return False
    if instantaneo:
        return not e.get("start")
    start, end = e.get("start"), e.get("end")
    if not (isinstance(start, str) and isinstance(end, str)):
        return False
    try:
        dias = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days
    except ValueError:
        return False
    return 330 <= dias <= 400


def parse_registros(payload: dict | None) -> list[Registro]:
    """Pura: ``companyfacts`` → los registros anuales de todos los conceptos. Nunca levanta."""
    out: list[Registro] = []
    facts = (payload or {}).get("facts") or {}
    for concepto, tags in CONCEPTOS.items():
        unidad = UNIDADES.get(concepto, "USD")
        inst = concepto in INSTANTANEOS
        for tag in tags:
            for tax in _TAXONOMIAS:
                entradas = (((facts.get(tax) or {}).get(tag) or {}).get("units") or {}).get(unidad) or []
                for e in entradas:
                    if not isinstance(e, dict) or not _es_anual(e, inst):
                        continue
                    try:
                        val = float(e["val"])
                        end, filed = str(e["end"]), str(e["filed"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    out.append(Registro(concepto, end, filed, val, str(e.get("form") or ""), tag))
    return out


def es_extranjera(payload: dict | None) -> bool:
    """Reporta en ifrs-full o presenta 20-F/40-F: sus números por acción no van contra el ADR."""
    facts = (payload or {}).get("facts") or {}
    if facts.get("ifrs-full"):
        return True
    for tags in (facts.get("us-gaap") or {}).values():
        for entradas in (tags.get("units") or {}).values():
            for e in entradas[:50]:
                if str(e.get("form") or "").startswith(("20-F", "40-F")):
                    return True
    return False


@dataclass
class Fundamentos:
    """Los registros de un ticker, con la pregunta point-in-time."""

    ticker: str
    registros: list[Registro] = field(default_factory=list)
    extranjera: bool = False
    ciks: tuple[int, ...] = ()
    generado: str = ""

    def serie(
        self, concepto: str, fecha: str, splits: list[tuple[str, float]] | None = None
    ) -> list[tuple[str, float]]:
        """``(fin_de_período, valor)`` del concepto, como se lo conocía **antes** de ``fecha``.

        Por período: manda el tag más preferido de ``CONCEPTOS`` que tenga un dato presentado
        antes de ``fecha``, y dentro de ese tag el último presentado. Ordenado del más viejo al
        más nuevo.

        ``splits`` (``[(fecha, ratio)]``, como ``get_split_events``) lleva los conceptos por acción
        a la base de acciones **de hoy** (tarea 383): cada número está en la base del día en que
        se presentó, así que se divide por los splits posteriores a su ``filed`` (y las acciones
        se multiplican). Sin esto, un EPS de antes del 10 a 1 de NVDA queda 10 veces más grande
        que uno de después, contra precios que Yahoo ya ajustó.
        """
        if concepto == "ganancia_bruta":
            return self._ganancia_bruta(fecha)
        prioridad = {t: i for i, t in enumerate(CONCEPTOS[concepto])}
        mejor: dict[str, Registro] = {}
        for r in self.registros:
            if r.concepto != concepto or r.filed >= fecha:
                continue
            cur = mejor.get(r.end)
            if cur is None or (prioridad[r.tag], cur.filed) < (prioridad[cur.tag], r.filed):
                mejor[r.end] = r
        if not splits or concepto not in POR_ACCION:
            return sorted((end, r.val) for end, r in mejor.items())
        out = []
        for end, r in mejor.items():
            factor = math.prod(ratio for dia, ratio in splits if dia > r.filed)
            out.append((end, r.val * factor if concepto == "acciones_diluidas" else r.val / factor))
        return sorted(out)

    def _ganancia_bruta(self, fecha: str) -> list[tuple[str, float]]:
        directa = dict(self._serie_simple("ganancia_bruta", fecha))
        ventas = dict(self.serie("revenue", fecha))
        for end, costo in self.serie("costo_ventas", fecha):
            if end not in directa and end in ventas:
                directa[end] = ventas[end] - costo
        return sorted(directa.items())

    def _serie_simple(self, concepto: str, fecha: str) -> list[tuple[str, float]]:
        mejor: dict[str, Registro] = {}
        for r in self.registros:
            if r.concepto == concepto and r.filed < fecha:
                cur = mejor.get(r.end)
                if cur is None or r.filed > cur.filed:
                    mejor[r.end] = r
        return sorted((end, r.val) for end, r in mejor.items())

    def al(self, fecha: str) -> dict[str, list[tuple[str, float]]]:
        """Todos los conceptos como se los conocía antes de ``fecha``."""
        return {c: self.serie(c, fecha) for c in CONCEPTOS}

    # ── Persistencia ────────────────────────────────────────────────────────────────

    def a_json(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "ticker": self.ticker,
            "ciks": list(self.ciks),
            "extranjera": self.extranjera,
            "generado": self.generado,
            "registros": [[r.concepto, r.end, r.filed, r.val, r.form, r.tag] for r in self.registros],
        }

    @classmethod
    def de_json(cls, blob: dict) -> Fundamentos:
        if blob.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"schema {blob.get('schema_version')} != {SCHEMA_VERSION}")
        return cls(
            ticker=blob["ticker"],
            registros=[Registro(c, e, f, float(v), fo, t) for c, e, f, v, fo, t in blob["registros"]],
            extranjera=bool(blob.get("extranjera")),
            ciks=tuple(blob.get("ciks") or ()),
            generado=str(blob.get("generado") or ""),
        )


def unir(ticker: str, payloads: list[tuple[int, dict]], generado: str = "") -> Fundamentos:
    """Pura: los payloads de un ticker (CIK actual y predecesores) en un ``Fundamentos``.

    Un mismo dato puede aparecer en los dos CIK (la sociedad nueva re-presenta comparativos):
    se deduplica por (concepto, fin, presentado, tag).
    """
    vistos: dict[tuple[str, str, str, str], Registro] = {}
    extranjera = False
    for _cik, p in payloads:
        extranjera = extranjera or es_extranjera(p)
        for r in parse_registros(p):
            vistos.setdefault((r.concepto, r.end, r.filed, r.tag), r)
    return Fundamentos(
        ticker=ticker,
        registros=sorted(vistos.values(), key=lambda r: (r.concepto, r.end, r.filed, r.tag)),
        extranjera=extranjera,
        ciks=tuple(c for c, _ in payloads),
        generado=generado,
    )


VIGENCIA_DIAS = 400


def es_vigente(fin: str, ganancia: list[tuple[str, float]]) -> bool:
    """¿``fin`` es el cierre de la ganancia más reciente, o el anterior? (tarea 390).

    El último dato de un concepto puede ser de hace una década —la ganancia bruta de AT&T termina
    en 2014, la deuda de JPM en 2013— y tomarlo como el de hoy lo mezcla con la ganancia del último
    año. Se compara contra el cierre de la ganancia neta con una tolerancia de un año y un mes, que
    cubre los ejercicios de 52/53 semanas y no depende de que la ganancia tenga todos los años.
    Sin ganancia no hay contra qué comparar: no es vigente.
    """
    if not ganancia:
        return False
    ultimo = date.fromisoformat(ganancia[-1][0])
    return (ultimo - date.fromisoformat(fin)).days <= VIGENCIA_DIAS


def anios_cubiertos(fund: Fundamentos, concepto: str, fecha: str) -> int:
    """Cuántos años tiene el concepto, **si su último es vigente** (tarea 390); si no, cero.

    Contar sólo la cantidad daba por cubierta la ganancia bruta de 24 tickers cuyo último año era
    de 2017 o antes.
    """
    serie = fund.serie(concepto, fecha)
    if concepto == "ganancia_neta" or not serie:
        return len(serie)
    return len(serie) if es_vigente(serie[-1][0], fund.serie("ganancia_neta", fecha)) else 0


# ── Red y disco ─────────────────────────────────────────────────────────────────────


def _bajar_cik(cik: int, session) -> dict | None:
    from data.news_sources import SEC_DATA_BASE

    try:
        r = session.get(f"{SEC_DATA_BASE}/api/xbrl/companyfacts/CIK{cik:010d}.json", timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception:
        log.exception("companyfacts falló para el CIK %s", cik)
        return None


def construir(
    ticker: str, *, session=None, mapping: dict | None = None, pausa_s: float = 0.15
) -> Fundamentos | None:
    """Baja los CIK del ticker (actual + predecesores) y arma sus fundamentals. ``None`` si nada."""
    from data.news_sources import _sec_session, cik_for_ticker

    sess = session or _sec_session()
    ciks: list[int] = []
    actual = cik_for_ticker(ticker, mapping)
    if actual is not None:
        ciks.append(int(actual))
    ciks += [c for c in CIK_PREDECESORES.get(ticker.upper(), ()) if c not in ciks]
    payloads = []
    for cik in ciks:
        p = _bajar_cik(cik, sess)
        if p is not None:
            payloads.append((cik, p))
        time.sleep(pausa_s)  # la SEC pide no pasar de 10 pedidos por segundo
    if not payloads:
        return None
    return unir(ticker.upper(), payloads, generado=date.today().isoformat())


def ruta(ticker: str, store: Path = STORE_DIR) -> Path:
    return store / f"{ticker.upper()}.json"


def guardar(fund: Fundamentos, store: Path = STORE_DIR) -> Path:
    store.mkdir(parents=True, exist_ok=True)
    p = ruta(fund.ticker, store)
    p.write_text(json.dumps(fund.a_json()), encoding="utf-8")
    return p


def cargar(ticker: str, store: Path = STORE_DIR) -> Fundamentos | None:
    p = ruta(ticker, store)
    if not p.exists():
        return None
    try:
        return Fundamentos.de_json(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        log.exception("fundamentals PIT ilegibles para %s", ticker)
        return None
