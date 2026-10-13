"""Recolector de la nube (tarea 355): el harvest de la app, corriendo en AWS Lambda.

**Qué hace.** Cada invocación recolecta **un lote** del universo publicado —consenso de
yfinance, 8-K de SEC y noticias de Finnhub— con los **mismos colectores** que la app
(``data/news_sources.py``), y lo escribe en la tabla DynamoDB ``finanzias_harvest`` con el
formato del §11.3 de ``docs/harvest_nube_t196_2026-09-14.md``. **No toca ``finanzias.db``**
(regla 5): eso lo hace la app al bajar lo pendiente (tarea 356).

**El formato** (§11.3):

* consenso: ``pk = consenso#{día UTC}``, ``sk = TICKER``, ``filas`` = las métricas del día;
* noticia: ``pk = noticia#{día UTC}``, ``sk = content_hash`` (el mismo hash que el UNIQUE
  de ``news_events``);
* corrida: ``pk = corrida#{día UTC}``, ``sk = lote{k}de{n}#{inicio}``: sobre cuántos tickers
  corrió, cuáles no y qué contestó cada fuente (§7.3: *el recolector declara sobre cuántos
  tickers corrió*).

Todos llevan ``capturado_at``, estampado **al terminar de recolectar el ticker y antes de
escribir** (§6.1): un reintento de escritura no lo mueve. Y ``expira`` a 90 días (§11.4).

**El primero del día gana**, como en la app (``_insert_estimate_if_new_today``): cada
``PutItem`` va con ``attribute_not_exists(pk)``, así que re-correr un lote el mismo día no
pisa la captura anterior y sólo completa lo que faltaba.

**Por lotes y con techo** (§7.1): con la red caída una corrida tardó 95 min con 52
tickers, y Lambda corta a los 15. Por eso cada invocación hace un lote (``tickers[k::n]``),
cada ticker tiene un techo de wall-clock, y antes de cada ticker se mira cuánto le queda a
la invocación: lo que no alcanzó queda declarado en ``sin_correr``, no perdido en silencio.

**Fuentes:** ``estimates``, ``sec`` y ``finnhub``. Las noticias de yfinance **no**, porque
``Ticker.news`` contesta 404 desde el 2026-10-01 (tarea 354); entran con la 357.

Local, sin AWS: ``correr_lote`` recibe la tabla y el reloj inyectados, y los tests la
corren contra una tabla simulada. ``boto3`` sólo se importa en ``lambda_handler``: viene
con el runtime de Lambda y no está en el entorno de la app.
"""

from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

TABLA_DEFAULT = "finanzias_harvest"
#: Cuántas invocaciones se reparten el universo. El template tiene un horario por lote y un
#: test verifica que coincidan.
LOTES = 5
#: Las fuentes del recolector. ``yfinance_news`` queda afuera hasta la 357 (ver arriba).
FUENTES_DEFAULT = ("estimates", "sec", "finnhub")
#: Techo por ticker. Una corrida sana tarda ~2,7 s por ticker (tarea 204, con las cuatro
#: fuentes); 60 s es más de 20 veces eso y deja que un ticker colgado no se coma el lote.
TECHO_POR_TICKER_S = 60.0
#: Lo que se reserva al final de la invocación para escribir el registro de la corrida.
MARGEN_FINAL_S = 90.0
RETENCION_DIAS = 90
#: Noticias publicadas hace más que esto no se escriben: el recolector corre todos los días
#: hábiles y ya las escribió. Finnhub trae 7 días y la app ~11.000 ítems por corrida, casi
#: todos repetidos; sin la ventana la nube los re-escribe cada día en otra partición. Con
#: tres días, un corte de hasta dos días hábiles no pierde nada; la app, al abrirse, sigue
#: trayendo sus 7 días.
VENTANA_NOTICIAS_DIAS = 3
UNIVERSO_CLAVE = {"pk": "universo", "sk": "vivo"}

#: Fuente del recolector → función de ``data.news_sources`` que la implementa. Se resuelve
#: por nombre al momento de llamar, para que sean las mismas funciones que usa la app.
_COLECTORES = {
    "estimates": "_yf_estimates",
    "yfinance_news": "_yf_news",
    "sec": "_sec_8k",
    "finnhub": "_finnhub_news",
}


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat(timespec="seconds")


def _expira(capturado: datetime) -> int:
    return int((capturado + timedelta(days=RETENCION_DIAS)).timestamp())


def num_dynamo(v) -> Decimal | None:
    """Un número para DynamoDB: ``Decimal``, o ``None`` si no es finito.

    ``boto3`` rechaza ``float`` (exige ``Decimal``) y DynamoDB rechaza NaN e infinito.
    ``_safe_float`` de la app ya descarta NaN, pero deja pasar ``inf``.
    """
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return Decimal(repr(f))


def tickers_del_lote(tickers, lote: int, lotes: int) -> list[str]:
    """El lote ``lote`` (desde 0) de ``lotes``: cada ticker cae en exactamente uno."""
    if lotes < 1 or not 0 <= lote < lotes:
        raise ValueError(f"lote {lote} fuera de rango para {lotes} lotes")
    universo = sorted({str(t).strip().upper() for t in tickers if str(t).strip()})
    return universo[lote::lotes]


def item_consenso(ticker: str, snaps, capturado: datetime) -> dict:
    return {
        "pk": f"consenso#{capturado.date().isoformat()}",
        "sk": ticker.upper(),
        "capturado_at": _iso(capturado),
        "expira": _expira(capturado),
        "filas": [
            {
                "metric": s.metric,
                "period_label": s.period_label,
                "consensus_value": num_dynamo(s.consensus_value),
                "num_analysts": None if s.num_analysts is None else int(s.num_analysts),
            }
            for s in snaps
        ],
    }


def item_noticia(n, capturado: datetime) -> dict:
    return {
        "pk": f"noticia#{capturado.date().isoformat()}",
        "sk": n.content_hash(),
        "capturado_at": _iso(capturado),
        "expira": _expira(capturado),
        "ticker": n.ticker,
        "title": n.title,
        "source": n.source,
        "content": n.content,
        "url": n.url,
        "published_at": _iso(n.published_at),
    }


def noticia_en_ventana(n, capturado: datetime, dias: int = VENTANA_NOTICIAS_DIAS) -> bool:
    """¿Se escribe? Sin fecha de publicación, sí: no hay cómo saber que ya se escribió."""
    if n.published_at is None:
        return True
    p = n.published_at
    if p.tzinfo is None:
        p = p.replace(tzinfo=timezone.utc)
    return p >= capturado - timedelta(days=dias)


def _es_condicional(e: BaseException) -> bool:
    resp = getattr(e, "response", None) or {}
    return (resp.get("Error") or {}).get("Code") == "ConditionalCheckFailedException"


def escribir_si_no_esta(tabla, item: dict) -> bool:
    """``PutItem`` que no pisa: ``True`` si lo escribió, ``False`` si ya estaba."""
    try:
        tabla.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
        return True
    except Exception as e:
        if _es_condicional(e):
            return False
        raise


def con_techo(fn, techo_s: float):
    """``(resultado, colgado)``: corre ``fn`` en un hilo y no espera más de ``techo_s``.

    El hilo colgado sigue vivo hasta que Lambda congele el proceso, pero no escribe nada:
    todas las escrituras van en el hilo principal.
    """
    caja: dict = {}

    def _correr():
        try:
            caja["r"] = fn()
        except BaseException as e:  # pragma: no cover — los colectores no levantan
            caja["e"] = e

    hilo = threading.Thread(target=_correr, daemon=True)
    hilo.start()
    hilo.join(techo_s)
    if hilo.is_alive():
        return None, True
    if "e" in caja:
        raise caja["e"]
    return caja["r"], False


@dataclass
class Recoleccion:
    noticias: list = field(default_factory=list)
    estimates: list = field(default_factory=list)
    outcomes: list = field(default_factory=list)


def recolectar_ticker(ticker: str, fuentes) -> Recoleccion:
    """Las fuentes pedidas para un ticker, con los colectores de la app."""
    from data import news_sources as ns

    r = Recoleccion()
    for fuente in fuentes:
        items, outcome = getattr(ns, _COLECTORES[fuente])(ticker)
        r.outcomes.append(outcome)
        (r.estimates if fuente == "estimates" else r.noticias).extend(items)
    return r


def leer_universo(tabla) -> dict | None:
    """El ítem ``universo/vivo``, o ``None`` si no hay uno usable."""
    item = (tabla.get_item(Key=dict(UNIVERSO_CLAVE)) or {}).get("Item")
    if not item:
        return None
    tickers = [str(t).strip().upper() for t in (item.get("tickers") or []) if str(t).strip()]
    if not tickers:
        return None
    return {"tickers": tickers, "publicado_at": item.get("publicado_at"), "origen": item.get("origen")}


@dataclass
class Corrida:
    lote: int
    lotes: int
    inicio: datetime
    universo_n: int = 0
    universo_publicado_at: str | None = None
    universo_origen: str | None = None
    pedidos: list = field(default_factory=list)
    corridos: list = field(default_factory=list)
    sin_correr: list = field(default_factory=list)
    techo: list = field(default_factory=list)
    errores_escritura: list = field(default_factory=list)
    fuentes: dict = field(default_factory=dict)
    consenso_nuevos: int = 0
    consenso_ya_estaban: int = 0
    noticias_nuevas: int = 0
    noticias_ya_estaban: int = 0
    noticias_fuera_de_ventana: int = 0
    error: str | None = None
    duracion_s: float = 0.0

    def anotar(self, outcome) -> None:
        f = self.fuentes.setdefault(outcome.source, {"con_items": 0})
        f[outcome.status] = f.get(outcome.status, 0) + 1
        if outcome.items > 0:
            f["con_items"] += 1

    def item(self, version: str | None) -> dict:
        return {
            "pk": f"corrida#{self.inicio.date().isoformat()}",
            "sk": f"lote{self.lote + 1}de{self.lotes}#{_iso(self.inicio)}",
            "capturado_at": _iso(self.inicio),
            "expira": _expira(self.inicio),
            "version": version,
            "error": self.error,
            "universo_n": self.universo_n,
            "universo_publicado_at": self.universo_publicado_at,
            "universo_origen": self.universo_origen,
            "pedidos": len(self.pedidos),
            "corridos": len(self.corridos),
            "sin_correr": self.sin_correr,
            "techo": self.techo,
            "errores_escritura": self.errores_escritura,
            "fuentes": self.fuentes,
            "consenso_nuevos": self.consenso_nuevos,
            "consenso_ya_estaban": self.consenso_ya_estaban,
            "noticias_nuevas": self.noticias_nuevas,
            "noticias_ya_estaban": self.noticias_ya_estaban,
            "noticias_fuera_de_ventana": self.noticias_fuera_de_ventana,
            "duracion_s": num_dynamo(round(self.duracion_s, 1)),
        }

    def resumen(self) -> str:
        if self.error:
            return f"Recolector lote {self.lote + 1}/{self.lotes}: ERROR — {self.error}"
        fuentes = ", ".join(
            f"{s} " + "/".join(f"{k} {v}" for k, v in sorted(d.items()))
            for s, d in sorted(self.fuentes.items())
        )
        return (
            f"Recolector lote {self.lote + 1}/{self.lotes}: {len(self.corridos)}/{len(self.pedidos)} tickers "
            f"(universo {self.universo_n}, {self.universo_origen}) en {self.duracion_s:.0f}s | "
            f"consenso +{self.consenso_nuevos} (ya {self.consenso_ya_estaban}) | "
            f"noticias +{self.noticias_nuevas} (ya {self.noticias_ya_estaban}, "
            f"fuera de ventana {self.noticias_fuera_de_ventana}) | sin correr {len(self.sin_correr)} | "
            f"techo {len(self.techo)} | errores de escritura {len(self.errores_escritura)} | {fuentes}"
        )


def correr_lote(
    lote: int,
    lotes: int,
    *,
    tabla,
    fuentes=FUENTES_DEFAULT,
    reloj=ahora_utc,
    restante_s=lambda: math.inf,
    techo_s: float = TECHO_POR_TICKER_S,
    ventana_dias: int = VENTANA_NOTICIAS_DIAS,
    version: str | None = None,
) -> Corrida:
    """Recolecta un lote y lo escribe. **No levanta**: todo queda en la ``Corrida``."""
    t0 = time.monotonic()
    c = Corrida(lote=lote, lotes=lotes, inicio=reloj())
    try:
        universo = leer_universo(tabla)
        if universo is None:
            c.error = "sin universo publicado (ítem universo/vivo vacío o ausente)"
        else:
            c.universo_n = len(universo["tickers"])
            c.universo_publicado_at = universo["publicado_at"]
            c.universo_origen = universo["origen"]
            c.pedidos = tickers_del_lote(universo["tickers"], lote, lotes)
            _recolectar(c, tabla, fuentes, reloj, restante_s, techo_s, ventana_dias)
    except Exception as e:
        c.error = f"{type(e).__name__}: {e}"[:300]
    c.duracion_s = time.monotonic() - t0
    try:
        tabla.put_item(Item=c.item(version))
    except Exception as e:  # el registro no puede tapar lo recolectado
        c.errores_escritura.append(f"corrida: {type(e).__name__}")
    return c


def _recolectar(c: Corrida, tabla, fuentes, reloj, restante_s, techo_s, ventana_dias) -> None:
    for i, ticker in enumerate(c.pedidos):
        if restante_s() < MARGEN_FINAL_S + techo_s:
            c.sin_correr = list(c.pedidos[i:])
            break
        res, colgado = con_techo(lambda t=ticker: recolectar_ticker(t, fuentes), techo_s)
        # La marca de captura es ÉSTA, antes de escribir (§6.1): un reintento de la
        # escritura —los hace botocore solo— no la mueve.
        capturado = reloj()
        if colgado:
            c.techo.append(ticker)
            continue
        c.corridos.append(ticker)
        for o in res.outcomes:
            c.anotar(o)
        try:
            if res.estimates:
                if escribir_si_no_esta(tabla, item_consenso(ticker, res.estimates, capturado)):
                    c.consenso_nuevos += 1
                else:
                    c.consenso_ya_estaban += 1
            for n in res.noticias:
                if not noticia_en_ventana(n, capturado, ventana_dias):
                    c.noticias_fuera_de_ventana += 1
                elif escribir_si_no_esta(tabla, item_noticia(n, capturado)):
                    c.noticias_nuevas += 1
                else:
                    c.noticias_ya_estaban += 1
        except Exception as e:
            c.errores_escritura.append(f"{ticker}: {type(e).__name__}")


def _version() -> str | None:
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recolector_version.txt")
    try:
        with open(p, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _cargar_finnhub_key(ssm, nombre: str | None) -> str | None:
    """Pone ``FINNHUB_API_KEY`` desde SSM (§7.5). Devuelve el motivo si no pudo."""
    if os.environ.get("FINNHUB_API_KEY"):
        return None
    if not nombre:
        return "sin FINNHUB_PARAM"
    try:
        valor = ssm.get_parameter(Name=nombre, WithDecryption=True)["Parameter"]["Value"]
    except Exception as e:
        return f"SSM {nombre}: {type(e).__name__}"
    os.environ["FINNHUB_API_KEY"] = valor
    return None


def lambda_handler(event, context):  # pragma: no cover — corre en AWS
    """Entrada de Lambda. El evento trae ``{"lote": k, "lotes": n}`` (lo pone el horario)."""
    os.environ.setdefault("FINANZIAS_LOG_FILE", ":sin-archivo:")
    import boto3
    import yfinance as yf
    from botocore.config import Config

    # En Lambda sólo /tmp es escribible: sin esto el primer pedido de yfinance falla por
    # el disco y se lee como un bloqueo de Yahoo (lo aprendió el probe de la 196).
    yf.set_tz_cache_location("/tmp/yf-cache")
    motivo = _cargar_finnhub_key(boto3.client("ssm"), os.environ.get("FINNHUB_PARAM"))
    if motivo:
        print(f"Finnhub sin key: {motivo} — la fuente sale 'unavailable'")
    config = Config(retries={"max_attempts": 10, "mode": "standard"})
    tabla = boto3.resource("dynamodb", config=config).Table(os.environ.get("TABLA", TABLA_DEFAULT))
    event = event or {}
    c = correr_lote(
        int(event.get("lote", 0)),
        int(event.get("lotes", LOTES)),
        tabla=tabla,
        restante_s=lambda: context.get_remaining_time_in_millis() / 1000.0,
        version=_version(),
    )
    print(c.resumen())
    return {"resumen": c.resumen(), "error": c.error, "corridos": len(c.corridos), "pedidos": len(c.pedidos)}
