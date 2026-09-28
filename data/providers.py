"""Cadena de proveedores EOD con fallback — ARQ3 (tarea 14).

**Por qué existe.** yfinance es hoy el **punto único de fallo** para todos los precios
del sistema, y tiene historial: el 401 *Invalid Crumb* (mitigado con batch+retry), el
throttle que envenenó el failing set, y el precio ~10× corrupto de KLAC que llegó a
ejecutar un trade. Cada uno tiene ya su mitigación **específica** —y eso baja el valor
de esta tarea respecto de cuando se escribió, medido: en los cuatro días de log limpio
posteriores a la tarea 78 hay **cero** throttle y **cero** 401—. Lo que ninguna de esas
mitigaciones cubre es el caso estructural: **si Yahoo se cae, no hay precios**.

**La decisión de calidad más importante, y es la que restringe el diseño.** El fallback
**NUNCA mezcla fuentes dentro de una misma serie histórica**: `auto_adjust` y el
tratamiento de splits difieren entre proveedores, así que una serie híbrida es **peor
que un hueco** — tendría un escalón de escala en el medio, que es exactamente la clase
de defecto que las tareas 63, 64 y 113 vinieron a cazar. Por eso la cadena se consulta
**sólo cuando el primario devolvió nada**, y devuelve una serie **entera** de un solo
proveedor o nada.

**Default OFF** (`price_provider_fallback_enabled`), patrón E1b: shipear la cadena no
cambia el comportamiento hasta que alguien la encienda a propósito.

Proveedores
-----------
* **Stooq** — **NO USABLE** desde el 2026-09-07: devuelve una verificación
  proof-of-work en JavaScript en vez del CSV. Se deja con la evidencia.
* **Tiingo** — free tier, EOD limpio, **requiere** `TIINGO_API_KEY`. Sin la key se declara
  no disponible; no es un error. **La key existe en la máquina de Chapa desde el
  2026-09-28** (tarea 206): Tiingo es la tercera fuente de `second_opinions` y el
  proveedor de la cadena EOD. El CI no la tiene.
* **Finnhub** — sus velas históricas son **premium** (`/stock/candle` → 403 con la key
  que sí existe), pero su `/quote` **funciona** y sirve para el cross-check del precio
  actual: ver `second_opinion`.

**Estado, medido el 2026-09-07: no había un proveedor EOD de fallback sin dar de alta
una key nueva.** Con la key de Tiingo (2026-09-28) la cadena deja de estar vacía, pero
la mitad "histórico" de ARQ3 **sigue sin cablearse**: `fetch_with_fallback` no tiene
llamadores y el flag `price_provider_fallback_enabled` está OFF. La mitad "sanity del
precio actual" es la que mata la clase KLAC, y desde la tarea 206 vota con tres fuentes.
"""

from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from config.logging_config import get_logger

log = get_logger(__name__)

__all__ = [
    "MAYORIA",
    "OHLCV_COLUMNS",
    "QUOTE_SOURCES",
    "PriceProvider",
    "ProviderResult",
    "StooqProvider",
    "TiingoProvider",
    "arbitrate",
    "arbitrate_votes",
    "default_chain",
    "fetch_with_fallback",
    "second_opinion",
    "second_opinions",
    "tiingo_quote",
]

# El contrato de forma que `_normalize_ohlcv` deja y que el resto del sistema asume.
OHLCV_COLUMNS = ("Open", "High", "Low", "Close", "Volume")

# Cuántos días pedir según el `period` de yfinance. No es una traducción exacta —los
# proveedores de fallback no hablan el vocabulario de Yahoo— y por eso se redondea
# **para arriba**: es preferible traer de más y recortar que quedarse corto.
_DIAS_POR_PERIODO = {
    "1d": 5,
    "5d": 10,
    "1mo": 40,
    "3mo": 110,
    "6mo": 200,
    "1y": 400,
    "2y": 760,
    "5y": 1850,
    "10y": 3700,
    "ytd": 400,
    "max": 7500,
}


@dataclass(frozen=True)
class ProviderResult:
    """Una serie **completa** de un proveedor, con su origen declarado.

    El ``source`` no es decoración: es lo que permite afirmar que una serie no está
    mezclada. Si algún día se guardan series de proveedores distintos en el mismo
    cache, este campo es lo que hace visible cuál es cuál.
    """

    source: str
    frame: pd.DataFrame


class PriceProvider(Protocol):
    """Un proveedor EOD. ``name`` identifica la fuente en logs y en el resultado."""

    name: str

    def available(self) -> bool:
        """¿Se puede usar? (p. ej. hay API key). Sin esto la cadena se acorta sola."""
        ...

    def daily(self, ticker: str, period: str) -> pd.DataFrame | None:
        """OHLCV diario con índice de fechas, o ``None`` si no pudo."""
        ...


def _a_frame(filas: list[dict], ticker: str, fuente: str) -> pd.DataFrame | None:
    """Filas crudas → el mismo contrato de forma que devuelve ``_normalize_ohlcv``.

    Descarta las filas sin close numérico en vez de dejar NaN: un NaN en el medio de
    una serie EOD se lee después como un hueco de calendario (T110) y confunde el
    diagnóstico.
    """
    if not filas:
        return None
    try:
        df = pd.DataFrame(filas)
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"]).set_index("Date").sort_index()
        for col in OHLCV_COLUMNS:
            if col not in df.columns:
                log.warning("%s: %s vino sin columna %s", fuente, ticker, col)
                return None
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["Close"])
        return df[list(OHLCV_COLUMNS)] if not df.empty else None
    except Exception:
        log.exception("%s: no se pudo normalizar la respuesta de %s", fuente, ticker)
        return None


class StooqProvider:
    """CSV de Stooq — **NO USABLE desde el 2026-09-07**, y se deja con la evidencia.

    El enunciado de la tarea 14 (escrito el 2026-07-07) lo daba como *"EOD sin API key,
    CSV directo"*. Verificado contra el servicio real: hoy devuelve **200 con una
    página de verificación proof-of-work en JavaScript** en vez del CSV — un desafío
    SHA-256 que hay que resolver y postear a ``/__verify`` antes de que sirva datos.

    **No se implementa el bypass**: es una medida anti-bot explícita del sitio, y
    eludirla no es una decisión técnica sino una de otra clase. ``available()``
    devuelve **False**, así que la cadena simplemente no lo usa; queda acá para que el
    próximo que busque un proveedor EOD sin key no vuelva a gastar el intento.
    """

    name = "stooq"
    URL = "https://stooq.com/q/d/l/"

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = float(timeout)

    def available(self) -> bool:
        # Bloqueado por la verificación proof-of-work del sitio (ver el docstring).
        return False

    def _simbolo(self, ticker: str) -> str:
        # Stooq usa el sufijo de mercado y el punto como separador de clase
        # (BRK.B, no BRK-B, que es la forma de Yahoo).
        return f"{ticker.strip().upper().replace('-', '.')}.US".lower()

    def daily(self, ticker: str, period: str) -> pd.DataFrame | None:
        import requests

        try:
            resp = requests.get(
                self.URL,
                params={"s": self._simbolo(ticker), "i": "d"},
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
        except Exception:
            log.warning("stooq: falló la descarga de %s", ticker)
            return None
        texto = resp.text.strip()
        # Stooq devuelve 200 con un cuerpo de texto cuando el símbolo no existe.
        if not texto or "," not in texto.splitlines()[0]:
            log.warning("stooq: respuesta no-CSV para %s (%s)", ticker, texto[:60])
            return None
        filas = list(csv.DictReader(io.StringIO(texto)))
        df = _a_frame(filas, ticker, self.name)
        if df is None:
            return None
        dias = _DIAS_POR_PERIODO.get(period)
        return df.tail(dias) if dias else df


class TiingoProvider:
    """Tiingo free tier. **Requiere** ``TIINGO_API_KEY``; sin ella no está disponible."""

    name = "tiingo"
    URL = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"

    def __init__(self, timeout: float = 15.0, api_key: str | None = None) -> None:
        self.timeout = float(timeout)
        self._key = api_key if api_key is not None else os.environ.get("TIINGO_API_KEY")

    def available(self) -> bool:
        return bool(self._key)

    def daily(self, ticker: str, period: str) -> pd.DataFrame | None:
        if not self.available():
            return None
        import requests

        dias = _DIAS_POR_PERIODO.get(period, 400)
        desde = (pd.Timestamp.utcnow().normalize() - pd.Timedelta(days=dias)).date().isoformat()
        try:
            resp = requests.get(
                self.URL.format(ticker=ticker.strip().upper()),
                params={"startDate": desde, "format": "json", "token": self._key},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            crudo = resp.json()
        except Exception:
            log.warning("tiingo: falló la descarga de %s", ticker)
            return None
        if not isinstance(crudo, list) or not crudo:
            return None
        # `adjClose` y amigos: se toma la serie AJUSTADA entera, nunca mezclada con la
        # cruda — el mismo criterio que impide mezclar proveedores.
        filas = [
            {
                "Date": r.get("date"),
                "Open": r.get("adjOpen", r.get("open")),
                "High": r.get("adjHigh", r.get("high")),
                "Low": r.get("adjLow", r.get("low")),
                "Close": r.get("adjClose", r.get("close")),
                "Volume": r.get("adjVolume", r.get("volume")),
            }
            for r in crudo
        ]
        return _a_frame(filas, ticker, self.name)


def default_chain() -> list[PriceProvider]:
    """La cadena EOD, ya filtrada por disponibilidad.

    **Sin ``TIINGO_API_KEY`` queda VACÍA, y ése fue el hallazgo de la tarea 14** (medido
    el 2026-09-07): Stooq bloqueó a los clientes no-browser con un proof-of-work, y las
    velas diarias de Finnhub son **premium** en el free tier (``/stock/candle`` devuelve
    403). Con la key —en la máquina de Chapa desde el 2026-09-28— queda ``[tiingo]``.

    El cross-check del **precio actual** no usa esta cadena sino ``second_opinions``.
    """
    return [p for p in (StooqProvider(), TiingoProvider()) if p.available()]


def fetch_with_fallback(
    ticker: str,
    period: str,
    *,
    chain: list[PriceProvider] | None = None,
) -> ProviderResult | None:
    """Primera serie **completa** que consiga algún proveedor de la cadena.

    Devuelve la serie de **un solo** proveedor o ``None``. No combina, no rellena
    huecos de uno con barras de otro, y no reintenta el mismo proveedor: eso es lo que
    mantiene la promesa de que una serie no está mezclada.
    """
    for prov in chain if chain is not None else default_chain():
        try:
            df = prov.daily(ticker, period)
        except Exception:
            log.exception("proveedor %s reventó con %s", prov.name, ticker)
            continue
        if df is not None and not df.empty:
            log.info("fallback: %s servido por %s (%d barras)", ticker, prov.name, len(df))
            return ProviderResult(source=prov.name, frame=df)
    return None


# ── Segunda opinión sobre el PRECIO ACTUAL — la mitad viable de ARQ3 ─────────
#
# El sanity E5 de hoy es **unilateral**: compara el precio contra el último close
# *cacheado*. Cuando discrepan sabe que **algo** está podrido, pero no **cuál** — y por
# eso `unreliable_reference` tiene que decidir con heurísticas (cruce de frames,
# splits). Una fuente **independiente** desempata, que es exactamente lo que el
# enunciado pedía al hablar de "sanity bilateral", y es la mitad que mata la clase
# KLAC: un precio corrupto que llegó a ejecutar un trade.
#
# Finnhub `/quote` sirve para esto **con la key que este entorno ya tiene** (la que usa
# el harvest de noticias). Sus velas históricas NO — `/stock/candle` da 403 en el free
# tier, medido — así que esto no arregla el histórico, sólo el precio actual.
#
# **Tarea 206 — tres fuentes, manda la mayoría** (regla de Chapa, 2026-09-13). La tercera
# es Tiingo (`docs/fuentes_precio_t202_2026-09-14.md`). El ORDEN de la tupla es el de
# desempate al elegir qué precio independiente se usa cuando dos coinciden.
QUOTE_SOURCES = ("finnhub", "tiingo")

# Votos que hacen mayoría sobre tres fuentes (Yahoo + las dos de `QUOTE_SOURCES`).
MAYORIA = 2


def second_opinion(ticker: str, *, timeout: float = 10.0, api_key: str | None = None) -> float | None:
    """El precio actual según **Finnhub** ``/quote``, independiente de Yahoo, o ``None``.

    Es una de las fuentes de ``second_opinions``; conserva el nombre de cuando era la
    única (tareas 127/200/201), que es el que stubean sus tests.

    Fail-open en todos los caminos —sin key, error de red, respuesta rara— porque el
    llamador es el guard del precio: una segunda opinión que no llega tiene que dejar
    la decisión como estaba, nunca frenar un fill por sí misma.
    """
    key = api_key or os.environ.get("FINNHUB_API_KEY") or os.environ.get("FINNHUB_TOKEN")
    if not key:
        return None
    import requests

    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": ticker.strip().upper(), "token": key},
            timeout=timeout,
        )
        resp.raise_for_status()
        px = float((resp.json() or {}).get("c") or 0.0)
    except Exception:
        log.warning("second_opinion: no se pudo consultar %s", ticker)
        return None
    return px if px > 0 else None


def tiingo_quote(ticker: str, *, timeout: float = 10.0, api_key: str | None = None) -> float | None:
    """El precio actual según **Tiingo** (endpoint IEX), o ``None``. Fail-open como Finnhub.

    ``tngoLast`` es el último de Tiingo (intradía); fuera de hora puede venir vacío, y
    entonces se cae a ``last`` y a ``prevClose``. Con la banda del 50% un cierre alcanza
    (`docs/fuentes_precio_t202_2026-09-14.md` §2). Verificado en vivo el 2026-09-28: AAPL
    devuelve ``tngoLast``; un ticker inexistente, 404.
    """
    key = api_key or os.environ.get("TIINGO_API_KEY")
    if not key:
        return None
    import requests

    try:
        resp = requests.get(
            "https://api.tiingo.com/iex/",
            params={"tickers": ticker.strip().upper(), "token": key},
            timeout=timeout,
        )
        resp.raise_for_status()
        filas = resp.json()
        fila = filas[0] if isinstance(filas, list) and filas else {}
        crudo = fila.get("tngoLast") or fila.get("last") or fila.get("prevClose")
        px = float(crudo or 0.0)
    except Exception:
        log.warning("tiingo_quote: no se pudo consultar %s", ticker)
        return None
    return px if px > 0 else None


def second_opinions(ticker: str, *, timeout: float = 10.0) -> dict[str, float | None]:
    """El precio actual según **cada** fuente de ``QUOTE_SOURCES``: cuál contestó qué.

    ``None`` para la que no contestó. Las funciones se resuelven al llamar (no al importar)
    para que un stub de ``second_opinion`` en un test siga surtiendo efecto.
    """
    consultas = {"finnhub": second_opinion, "tiingo": tiingo_quote}
    out: dict[str, float | None] = {}
    for fuente in QUOTE_SOURCES:
        try:
            out[fuente] = consultas[fuente](ticker, timeout=timeout)
        except Exception:
            log.warning("second_opinions: %s reventó con %s", fuente, ticker)
            out[fuente] = None
    return out


def arbitrate_votes(
    price: float, reference: float, opiniones: dict[str, float | None], *, band: float
) -> tuple[str, float | None]:
    """La regla de tres fuentes (tarea 206): ``(veredicto, precio independiente a usar)``.

    Los votos son **tres precios**: el de Yahoo y los de las dos fuentes independientes.
    La referencia (el cierre guardado) no vota: es de Yahoo también, y es lo que está en
    disputa. Dos precios «coinciden» si difieren menos que ``band``.

    * ``"price"`` — Yahoo y al menos una externa coinciden: mayoría para el precio.
    * ``"reference"`` — las dos externas coinciden entre sí y Yahoo no: mayoría contra el
      precio. Se usa el de las externas **avalen o no el cierre guardado** (decisión de
      Chapa, 2026-09-28: también cuando las dos cosas de Yahoo están mal, manda la mayoría).
      El nombre se conserva por el camino de la 201, que lo lee como *«el precio de Yahoo
      pierde»*.
    * ``"ninguno"`` — sin mayoría: los tres discrepan. Chapa (2026-09-28): se comporta
      **igual que hoy**, sin precio ese scan y con aviso.
    * **Una sola externa contesta** ⇒ la regla de **dos** fuentes de siempre
      (``arbitrate``), llamada a propósito y no por accidente.
    * **Ninguna contesta** ⇒ ``"sin_opinion"``: el guard queda como estaba (Chapa,
      2026-09-28: que se caigan dos APIs no dispara ventas).
    """
    if price is None or reference is None or price <= 0 or reference <= 0:
        return "sin_opinion", None
    orden = [f for f in QUOTE_SOURCES if f in opiniones] + [f for f in opiniones if f not in QUOTE_SOURCES]
    validas = [float(opiniones[f]) for f in orden if opiniones[f] is not None and opiniones[f] > 0]
    if not validas:
        return "sin_opinion", None
    if len(validas) == 1:
        # Degradado explícito a dos fuentes: con un solo voto externo no hay mayoría de
        # tres que contar, y lo que decide es la regla de la 127/201.
        return arbitrate(price, reference, validas[0], band=band), validas[0]

    def coinciden(a: float, b: float) -> bool:
        return abs(a / b - 1.0) <= band

    con_yahoo = [px for px in validas if coinciden(px, price)]
    if 1 + len(con_yahoo) >= MAYORIA:
        return "price", con_yahoo[0]
    for px in validas:
        if sum(coinciden(q, px) for q in validas) >= MAYORIA:
            return "reference", px
    return "ninguno", None


def arbitrate(price: float, reference: float, independent: float | None, *, band: float) -> str:
    """La regla de **dos** fuentes: ¿a quién le da la razón la única independiente?

    Desde la tarea 206 la usa ``arbitrate_votes`` cuando contesta una sola externa.

    Devuelve ``"price"``, ``"reference"``, ``"ninguno"`` o ``"sin_opinion"``.

    Se separa del fetch a propósito: es **la** regla del chequeo bilateral, y una regla
    se testea con números a mano. Enterrada adentro de la llamada de red obligaría a
    mockear HTTP para probar un ``if`` — que es como un criterio termina sin test (la
    lección de la tarea 120).
    """
    if independent is None or independent <= 0 or price <= 0 or reference <= 0:
        return "sin_opinion"
    cerca_del_precio = abs(independent / price - 1.0) <= band
    cerca_de_la_ref = abs(independent / reference - 1.0) <= band
    if cerca_del_precio and not cerca_de_la_ref:
        return "price"
    if cerca_de_la_ref and not cerca_del_precio:
        return "reference"
    # Con los dos cerca la banda es demasiado ancha para que esto discrimine; con
    # ninguno cerca, la tercera fuente discrepa de las dos y lo único honesto es
    # decir que nadie tiene respaldo.
    return "ninguno"
