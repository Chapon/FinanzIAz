"""Una opinión de Claude sobre una acción, con los datos de la app (tarea 320).

Qué es
------
La pestaña Análisis le manda a Claude un resumen de lo que ya calculó para un ticker —precio y
retornos, la señal general y sus indicadores, el régimen, soporte/resistencia, el consenso de
analistas y las noticias clasificadas— y recibe una recomendación (**COMPRAR / MANTENER /
VENDER**) con confianza, tesis, riesgos y qué la haría cambiar.

**Display-only** (regla 3): ningún gate, sizing ni scan la lee. Que la tesis sea buena no dice
que acierte (la 73 y la 255 lo enseñaron), así que cada opinión se **registra**
(``claude_opinions``) para medirla: es la tarea 321.

Cómo llama a Claude, y por qué así
----------------------------------
Sin pagar la API: a través de **Claude Code** en modo no interactivo (``claude -p``), con la
suscripción de Chapa (Chapa, 2026-10-05: *«se puede hacer sin pagar extra»*). Verificado ese día:
5 s para una pregunta chica, y ``--json-schema`` devuelve la respuesta validada en
``structured_output``. Lo que se aisla, porque Claude Code trae un entorno pensado para programar:

* ``--system-prompt`` propio (reemplaza las instrucciones de programar);
* ``--tools ""``: sin herramientas (no lee archivos ni corre nada) — opina sólo con los datos;
* ``--strict-mcp-config`` con una config vacía: no levanta los servidores MCP del usuario;
* ``--no-session-persistence``: no guarda la sesión;
* corre en una **carpeta neutra**, no en el repo: si no, Claude Code cargaría el ``CLAUDE.md``.

``--bare`` NO sirve: exige ``ANTHROPIC_API_KEY`` y no lee el login de la suscripción.

**Y el proceso se lanza SIN ``ANTHROPIC_API_KEY`` (tarea 322).** Claude Code le da prioridad a esa
variable sobre el login de claude.ai. En la máquina de Chapa existe a nivel de usuario con un
valor inválido (10 caracteres), y la primera versión fallaba en la app con *«401 API key is
invalid»* — tras 185 s de reintentos. La verificación de la 320 no lo vio porque corrió **adentro
de una sesión de Claude Code**, cuyas variables ``CLAUDE_CODE_*`` autenticaban al hijo por la sesión
padre. Por eso ``entorno()`` también saca esas: la app nunca corre adentro de una sesión, y una
verificación tampoco tiene que hacerlo (``scripts/probar_opinion_claude.py``).

**No se manda la posición de Chapa** en la acción (decisión por default de la tarea 320): sólo
datos de mercado.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

MODELO = "claude-opus-5-5"
TIMEOUT_S = 240.0
MAX_NOTICIAS = 15
# El resumen de una noticia, recortado (tarea 426): 15 de 300 caracteres son ~5 KB más.
MAX_RESUMEN = 300
DIAS_NOTICIAS = 14

# Qué recibe Claude, versionado (tarea 417): la 321 mide si las opiniones aciertan, y cambiar los
# datos cambia el instrumento. Cada tarea que agrega o cambia un bloque la sube; las filas viejas de
# ``claude_opinions`` no tienen el campo y son la versión 1.
#   2 — retorno del día, si el precio es intradiario, y la hora ET de las noticias (417).
#   3 — valuación de la tarjeta, fundamentales anuales de EDGAR y el P/E de yfinance (418).
#   4 — próximo balance y sorpresas de EPS de los últimos trimestres (419).
#   5 — volumen de la última barra contra el promedio de 20 ruedas, parcial si es intradiario (425).
#   6 — la calidad con sus definiciones y su corte, la fecha de los fundamentals, la relevancia de
#       cada noticia, y los objetivos sin el `current` de Yahoo, que no traía hora (434).
#   7 — el resumen de cada noticia, cuando la fuente lo trae (426).
#   8 — los pares de la misma industria, el ETF del sector y los índices (420).
#   9 — deuda, activos, patrimonio y acciones por año, y los múltiplos del último año (440).
#  10 — las noticias que se mandan las clasifica qwen al pedir la opinión, con tope (427).
#  11 — caja, capex, flujo de caja libre y ganancia operativa por año (441).
#  12 — las noticias se bajan al pedir si la app no tiene recientes, y van con su cobertura (442).
#  13 — las recomendaciones de analistas con el mes en curso, y sin la relevancia de la heurística (449).
#  14 — pares y una serie de referencia a mano cuando la industria de Yahoo no sirve (446).
#  15 — las noticias: las más relevantes de cada día de la ventana, sin las de otras empresas (452).
#  16 — el P/E, el EPS y la beta de Yahoo pedidos al armar la opinión, no del cache de 7 días (453).
VERSION_DATOS = 16
RUEDAS_VOLUMEN = 20
TRIMESTRES_SORPRESA = 4
ANIOS_FUNDAMENTALES = 4

# Cierre de la sesión regular de NYSE/NASDAQ, en hora del Este (ET).
_CIERRE_ET = (16, 0)

RECOMENDACIONES = ("COMPRAR", "MANTENER", "VENDER")

ESQUEMA: dict = {
    "type": "object",
    "properties": {
        "recomendacion": {"type": "string", "enum": list(RECOMENDACIONES)},
        "confianza": {"type": "integer", "minimum": 0, "maximum": 100},
        "tesis": {"type": "string"},
        "riesgos": {"type": "array", "items": {"type": "string"}},
        "cambiaria_opinion": {"type": "array", "items": {"type": "string"}},
        "datos_faltantes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["recomendacion", "confianza", "tesis", "riesgos", "cambiaria_opinion", "datos_faltantes"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Sos un analista de inversiones que le da su opinión a una persona sobre UNA acción \
de EE.UU. Recibís un JSON con lo que calculó su app (FinanzIAs): precio y retornos, una señal \
técnica agregada con sus indicadores, el régimen de mercado, soporte y resistencia, el consenso \
de analistas, noticias recientes con un tono clasificado por un modelo local y, cuando hay, la \
valuación y los fundamentales anuales de la empresa.

Reglas:
- Usá SOLO esos datos. No inventes cifras, noticias, resultados ni eventos que no estén. Si falta \
algo importante para opinar, ponelo en datos_faltantes.
- Tené en cuenta lo que la app sabe de sus propias señales: ninguna tiene poder predictivo \
demostrado. Cuando se midió (su puntaje de compra contra el retorno a 5 días, y el impacto de las \
noticias) no se detectó relación; el modelo XGBoost, el consenso y el tono de las noticias no \
están validados. Pesalos con ese escepticismo.
- Los retornos se miden contra cierres: "1d" es contra el cierre anterior. Si el bloque precio \
dice que el mercado estaba abierto, el precio es intradiario (a la hora que indica) y el día \
todavía no cerró: el cierre y el volumen del día todavía no existen, no los anotes en \
datos_faltantes (el volumen de esa barra es parcial y así lo dice el bloque volumen). Las horas \
de las noticias están en hora del Este de EE.UU. (ET).
- Cada noticia trae relevancia_0_a_1, del mismo clasificador que el tono: con 0,2 o menos, la \
noticia trata de otra empresa o de otra cosa, aunque aparezca bajo este ticker; no la tomes como \
un hecho de la empresa ni uses su tono. Si la clasificó la heurística (provisional, heuristic o \
fallback), la relevancia viene null: la heurística no la mide; juzgá por el título si es de la \
empresa. Algunas fuentes traen un resumen corto y otras sólo el \
título (resumen null): un resumen que no está no es un dato faltante, no lo anotes en datos_faltantes.
- cobertura_noticias dice cuántas noticias del ticker tiene la app en la ventana, de qué días (ET) \
y qué días no tiene ninguna. Si no hay noticias, es que la app no las tiene (lo dice su nota), no \
que el bloque se haya perdido. Si dice que el harvest estaba corriendo, las de hoy pueden faltar. \
Las noticias que se mandan no son las más nuevas: son las más relevantes de cada día de la ventana, \
repartidas entre los días, de la más nueva a la más vieja; las de otras empresas (relevancia 0,2 o \
menos) no van, y cobertura_noticias dice cuántas quedaron afuera por eso.
- pares trae los retornos de tickers de la misma industria que la app tiene guardados (no la \
industria entera), del ETF del sector y de los índices (SPY, QQQ), para separar lo que le pasa a \
la empresa de lo que le pasa al sector y al mercado; cada uno dice a qué día llega. Si trae \
pares_a_mano, la industria de Yahoo no servía y los pares los eligió la app (dice por qué); \
referencia es una serie que mueve al negocio (por ejemplo, el bitcoin para una minera). La app NO \
tiene precios de commodities ni de insumos \
(memoria, petróleo, metales, etc.): no los anotes en datos_faltantes; si te parecen decisivos, \
decilo en los riesgos.
- valuacion y fundamentales_anuales salen de los 10-K presentados a la SEC (EDGAR): son anuales, \
por año fiscal. La app NO tiene el guidance de la empresa ni las cifras trimestrales: no los \
anotes en datos_faltantes; si te parecen decisivos, decilo en los riesgos. El bloque yfinance es \
un dato de Yahoo, de otra fuente y sin verificar contra EDGAR. valuacion.calidad son percentiles \
contra las empresas del almacén de la app (100 es lo mejor en las cuatro patas, también en deuda, \
donde 100 es la menos endeudada); sus definiciones vienen en el bloque.
- fundamentales_anuales trae también la deuda de largo plazo, los activos y el patrimonio al cierre \
de cada año fiscal, y las acciones diluidas promedio del año: una deuda null es que el 10-K no la \
informó con los conceptos que lee la app, no que sea cero. multiplos usa el último año fiscal, y \
su capitalización es el precio de hoy por las acciones promedio de ese año, no por las de hoy. \
También trae la caja al cierre, el capex (lo pagado por activos fijos), el flujo de caja libre \
(flujo operativo menos capex) y la ganancia operativa. La app NO tiene las partidas no \
recurrentes (los 10-K no las presentan de forma estándar): no las anotes en datos_faltantes; si \
te parecen decisivas, decilo en los riesgos.
- Horizonte: de semanas a pocos meses.
- COMPRAR = abrir o aumentar posición; MANTENER = no hacer nada; VENDER = reducir o cerrar si \
la tiene, y no comprar si no la tiene.
- confianza (0-100) es cuán fuerte es la evidencia a favor de tu recomendación, no la \
probabilidad de que suba.
- Respondé en español rioplatense, concreto: la tesis en 3 a 6 oraciones, hasta 4 riesgos y \
hasta 3 cosas que te harían cambiar de opinión."""


class OpinionError(RuntimeError):
    """No se pudo obtener una opinión; el mensaje dice por qué, para mostrarlo tal cual."""


@dataclass(frozen=True)
class Opinion:
    recomendacion: str
    confianza: int
    tesis: str
    riesgos: list[str]
    cambiaria_opinion: list[str]
    datos_faltantes: list[str]
    modelo: str
    segundos: float


# ── El ejecutable ────────────────────────────────────────────────────────────


def ubicar_claude() -> str | None:
    """El ``claude`` a usar: ``FINANZIAS_CLAUDE_EXE``, el del PATH, o el de la extensión de VS Code.

    En la máquina de Chapa Claude Code corre como extensión de VS Code y su ``claude.exe`` NO está
    en el PATH (verificado el 2026-10-05). Entre varias versiones instaladas, la más nueva.
    """
    explicito = os.environ.get("FINANZIAS_CLAUDE_EXE") or ""
    if explicito and Path(explicito).is_file():
        return explicito
    en_path = shutil.which("claude")
    if en_path:
        return en_path
    ext = Path.home() / ".vscode" / "extensions"
    candidatos = sorted(ext.glob("anthropic.claude-code-*/resources/native-binary/claude*"), key=_version_de)
    candidatos = [c for c in candidatos if c.is_file()]
    return str(candidatos[-1]) if candidatos else None


def _version_de(p: Path) -> tuple:
    """``anthropic.claude-code-2.1.289-win32-x64`` → ``(2, 1, 289)``; lo que no parsea va primero."""
    nombre = p.parents[2].name.removeprefix("anthropic.claude-code-")
    partes = nombre.split("-")[0].split(".")
    try:
        return tuple(int(x) for x in partes)
    except ValueError:
        return (-1,)


# ── Los datos que se mandan ──────────────────────────────────────────────────


def _num(x, nd: int = 2):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else round(v, nd)


def armar_datos(
    ticker: str,
    df,
    result=None,
    company: dict | None = None,
    analyst: dict | None = None,
    noticias: list | None = None,
    soporte_resistencia: dict | None = None,
    obtenido: datetime | None = None,
    valuacion=None,
    anuales: list[dict] | None = None,
    balance: dict | None = None,
    pares: dict | None = None,
    cobertura_noticias: dict | None = None,
) -> dict:
    """El resumen que se manda a Claude. **Puro**: todo llega por parámetro.

    ``obtenido`` es cuándo llegó el ``df`` a la pestaña (con zona horaria): con eso se sabe si la
    última barra es intradiaria (tarea 417). Sin él, ``estado_precio`` no se manda.

    No incluye la posición del usuario en la acción.
    """
    close = df["Close"].astype(float)
    ultimo = float(close.iloc[-1])

    def ret(n: int):
        return _num((ultimo / float(close.iloc[-1 - n]) - 1) * 100) if len(close) > n else None

    ventana = close.iloc[-252:]
    fecha_ultima = df.index[-1].date() if hasattr(df.index[-1], "date") else None
    datos: dict = {
        "version_datos": VERSION_DATOS,
        "ticker": ticker.upper(),
        "empresa": (company or {}).get("name"),
        "sector": (company or {}).get("sector"),
        "fecha_datos": str(fecha_ultima) if fecha_ultima else str(df.index[-1]),
        "precio": _num(ultimo),
        "retornos_pct": {"1d": ret(1), "5d": ret(5), "20d": ret(20), "60d": ret(60), "250d": ret(250)},
        "rango_52s": {"max": _num(ventana.max()), "min": _num(ventana.min())},
        "volatilidad_anual_20d_pct": _num(close.pct_change().iloc[-20:].std() * (252**0.5) * 100),
    }
    if obtenido is not None and fecha_ultima is not None:
        datos["estado_precio"] = estado_precio(fecha_ultima, obtenido)
    vol = bloque_volumen(df, (datos.get("estado_precio") or {}).get("mercado_abierto", False))
    if vol:
        datos["volumen"] = vol
    if soporte_resistencia:
        datos["soporte"] = _num(soporte_resistencia.get("support"))
        datos["resistencia"] = _num(soporte_resistencia.get("resistance"))
    if result is not None:
        datos["senal_general"] = {
            "senal": result.overall_signal,
            "fuerza": result.overall_strength,
            "resumen": result.summary,
        }
        datos["indicadores"] = [
            {"indicador": s.indicator, "senal": s.signal, "fuerza": s.strength, "detalle": s.description}
            for s in result.signals
        ]
        ctx = getattr(result, "market_context", None)
        if ctx is not None:
            datos["regimen"] = {
                "regimen": getattr(ctx, "regime", None),
                "volatilidad_anual_pct": _num(getattr(ctx, "annual_volatility", None)),
                "riesgo_0_a_1": _num(getattr(ctx, "risk_score", None)),
            }
    if analyst:
        datos["analistas"] = {
            "recomendaciones": recomendaciones_recientes(analyst.get("recommendations")),
            "periodos": "0m es el mes en curso, -1m el anterior; de Yahoo, por mes",
            # Sin `current`: es el precio de cuando se bajó el consenso, sin hora, y quedaba al lado
            # del `precio` de otra hora sin rótulo (tarea 434).
            "precios_objetivo": _sin_current(analyst.get("price_targets")),
        }
    v = bloque_valuacion(valuacion)
    if v:
        datos["valuacion"] = v
    if anuales:
        datos["fundamentales_anuales"] = anuales
    m = bloque_multiplos(ultimo, anuales)
    if m:
        datos["multiplos"] = m
    if balance:
        datos["balance"] = balance
    yf_ = {
        "pe_trailing": _num((company or {}).get("pe_ratio")),
        "eps_trailing": _num((company or {}).get("eps")),
        "beta": _num((company or {}).get("beta")),
    }
    if any(x is not None for x in yf_.values()):
        datos["yfinance"] = yf_
    if noticias:
        datos["noticias"] = noticias[:MAX_NOTICIAS]
    if cobertura_noticias:
        # Va también sin noticias: es lo que dice por qué no hay (tarea 442).
        datos["cobertura_noticias"] = cobertura_noticias
    if pares:
        datos["pares"] = pares
    return datos


def bloque_volumen(df, intradiario: bool) -> dict | None:
    """El volumen de la última barra contra el promedio de las ``RUEDAS_VOLUMEN`` anteriores (425).

    El promedio **no** cuenta la última barra: si no, la barra se compara contra sí misma, y con
    una barra intradiaria parcial el promedio queda tirado para abajo. Si la barra es intradiaria
    lo dice, porque a media rueda la relación no es la de un día entero.
    """
    if "Volume" not in df.columns or len(df) < 2:
        return None
    v = df["Volume"].astype(float)
    ultimo = float(v.iloc[-1])
    previos = v.iloc[-1 - RUEDAS_VOLUMEN : -1]
    promedio = float(previos.mean()) if len(previos) else None
    out = {
        "ultima_barra": _num(ultimo, 0),
        f"promedio_{RUEDAS_VOLUMEN}_ruedas_previas": _num(promedio, 0),
        "relacion": _num(ultimo / promedio, 2) if promedio else None,
    }
    if intradiario:
        out["parcial"] = "barra intradiaria: es el volumen hasta la hora del precio, no el del día entero"
    return out


# Lo que es cada pata de la calidad (``analysis/calidad.py``), para que el percentil se lea bien:
# en la opinión de MU del 2026-11-11, `roe: 20` con un ROE de ~61 % el último año (la pata es el
# ROE de 10 años menos su desvío) y `deuda: 100` (es la MENOS endeudada) — tarea 434.
DEFINICIONES_CALIDAD = {
    "roe": "ROE medio de hasta 10 años menos su desvío: premia el retorno alto y parejo, no el del último año",
    "rentab_bruta": "ganancia bruta sobre activos del último año fiscal",
    "deuda": "años de ganancia neta para pagar la deuda de largo plazo; 100 = la menos endeudada",
    "regularidad": "fracción de los años en que la ganancia neta creció",
}


def _meses_atras(r) -> int:
    try:
        return -int(str(r.get("period", "")).rstrip("m"))
    except (TypeError, ValueError, AttributeError):
        return 99


def recomendaciones_recientes(recs, n: int = 3) -> list:
    """Los ``n`` meses más nuevos de las recomendaciones de Yahoo, del más nuevo al más viejo (449).

    Yahoo las da del más viejo al más nuevo (−3m, −2m, −1m, 0m en 518 de 563 tickers del cache el
    2026-11-20), y tomar las tres primeras dejaba afuera el mes en curso: en NVDA, después del
    desplome, la compra bajaba de 49 a 34 y Claude no lo veía.
    """
    return sorted((r for r in recs or [] if isinstance(r, dict)), key=_meses_atras)[:n]


def _sin_current(objetivos):
    if not isinstance(objetivos, dict):
        return objetivos
    return {k: x for k, x in objetivos.items() if k != "current"}


def _pct(x, nd: int = 1):
    return None if x is None else _num(float(x) * 100, nd)


def bloque_valuacion(v) -> dict | None:
    """Lo que muestra la tarjeta de valuación (``analysis.valuation.Valuacion``), como datos (418).

    Mismo objeto que lee ``ui/analysis/valuation_card.lineas_de``: lo que ve Chapa en la tarjeta y lo
    que recibe Claude no pueden diferir. ``None`` si la tarjeta se calla.
    """
    if v is None:
        return None
    out: dict = {
        "fuente": f"EDGAR (10-K), lo presentado hasta el {v.generado}, cuando se bajó"
        if getattr(v, "generado", None)
        else "EDGAR (10-K)",
        "ultimo_anio_fiscal": v.fin_ultimo_anio,
        "eps_diluido": _num(v.eps),
        "pe_con_ese_eps": _num(v.precio / v.eps, 1) if v.eps and v.eps > 0 else None,
        "valor_libro_x_accion": _num(v.valor_libro_x_accion),
        "graham": {"valor": _num(v.numero_graham), "margen_de_seguridad_pct": _pct(v.margen_graham)},
        "buffettology": {
            "crecimiento_eps_anual_pct": _pct(v.crecimiento),
            "anios_crecimiento": v.anios_crecimiento,
            "pe_historico_mediano": _num(v.pe_historico, 1),
            "anios_pe": v.anios_pe,
            "precio_en_10_anios": _num(v.precio_en_10),
            "retorno_anual_esperado_pct": _pct(v.retorno_anual),
            "precio_max_para_15_anual": _num(v.precio_max_objetivo),
        },
        "lynch": {"peg": _num(v.peg), "categoria": v.categoria, "motivo": v.motivo_categoria},
    }
    if v.calidad:
        out["calidad"] = {
            "puntaje_0_a_100": _num(v.calidad.get("puntaje"), 0),
            "percentiles": {k: _num(p, 0) for k, p in (v.calidad.get("percentiles") or {}).items()},
            "sentido": "percentil dentro de las empresas comparadas: 100 es lo mejor en todas las patas",
            "definiciones": {
                k: DEFINICIONES_CALIDAD[k]
                for k in (v.calidad.get("percentiles") or {})
                if k in DEFINICIONES_CALIDAD
            },
            "empresas_comparadas": v.calidad.get("n"),
            "con_lo_presentado_antes_del": v.calidad.get("al"),
        }
    if v.avisos:
        out["avisos"] = list(v.avisos)
    return out


def bloque_balance(fecha_reporte, sorpresas: list[tuple], hoy: date) -> dict | None:
    """El próximo reporte de resultados y las últimas sorpresas de EPS (tarea 419). **Pura.**

    ``fecha_reporte`` es lo de ``get_next_earnings_date``, que **a propósito** devuelve la última
    fecha pasada cuando no hay una futura (el Gate 6 la usa para la ventana post-balance). Acá
    eso NO se manda como próxima: va como ``ultimo_conocido``. Las sorpresas son las filas de
    ``collect_yfinance_earnings_history``: ``(fecha, estimado, reportado)``, la más nueva primero.
    """
    out: dict = {}
    if fecha_reporte is not None:
        dia = fecha_reporte.date() if hasattr(fecha_reporte, "date") else fecha_reporte
        if dia >= hoy:
            out["proximo"] = dia.isoformat()
            out["dias_hasta"] = (dia - hoy).days
        else:
            out["proximo"] = None
            out["ultimo_conocido"] = dia.isoformat()
            out["dias_desde"] = (hoy - dia).days
    filas = []
    for fecha, est, rep in sorpresas[:TRIMESTRES_SORPRESA]:
        sorpresa = _num((rep - est) / abs(est) * 100, 1) if est not in (None, 0) and rep is not None else None
        filas.append(
            {"fecha": fecha, "eps_estimado": _num(est), "eps_reportado": _num(rep), "sorpresa_pct": sorpresa}
        )
    if filas:
        out["sorpresas_eps"] = filas
        out["aviso"] = (
            "el estimado es la vista ACTUAL de Yahoo, no el consenso del día anterior al reporte: "
            "puede estar revisado después"
        )
    if not out:
        return None
    if "proximo" not in out:
        out["proximo"] = None
    return out


def balance_de(ticker: str, hoy: date | None = None) -> dict | None:
    """``bloque_balance`` con los datos de Yahoo; nunca levanta y nunca se cuelga.

    La fecha sale del cache ``earnings_cache`` (24 h) o de Yahoo con tope; las sorpresas, con el
    mismo tope (``collect_yfinance_earnings_history`` no tiene uno propio).
    """
    try:
        from data.news_sources import collect_yfinance_earnings_history
        from data.yahoo_finance import _run_with_timeout, get_next_earnings_date

        fecha = get_next_earnings_date(ticker)
        sorpresas = _run_with_timeout(collect_yfinance_earnings_history, ticker, default=[], retries=0) or []
        return bloque_balance(fecha, sorpresas, hoy or date.today())
    except Exception:
        from config.logging_config import get_logger

        get_logger(__name__).exception("Balance de %s para la opinión: falló", ticker)
        return None


def anuales_de(ticker: str) -> list[dict]:
    """``fundamentales_anuales`` del almacén local, sin red. Nunca levanta: sin datos, ``[]``.

    Los splits salen de lo memoizado (``allow_network=False``): la valuación de la pestaña ya los
    pidió con red al analizar el ticker.
    """
    try:
        from data import fundamentos_pit as fp
        from data.yahoo_finance import get_split_events

        manana = (date.today() + timedelta(days=1)).isoformat()
        return fundamentales_anuales(fp.cargar(ticker), manana, get_split_events(ticker, allow_network=False))
    except Exception:
        from config.logging_config import get_logger

        get_logger(__name__).exception("Fundamentales anuales de %s para la opinión: fallaron", ticker)
        return []


def fundamentales_anuales(fund, fecha: str, splits=None, n: int = ANIOS_FUNDAMENTALES) -> list[dict]:
    """Los últimos ``n`` años fiscales de EDGAR, en millones de USD y márgenes en % (418).

    Del almacén point-in-time de la 382, con lo presentado antes de ``fecha``. El EPS va en la base
    de acciones de hoy (``splits``), como en la valuación. Sin fundamentals, ``[]``.
    """
    if fund is None or getattr(fund, "extranjera", False):
        return []
    ventas = dict(fund.serie("revenue", fecha))
    ganancia = dict(fund.serie("ganancia_neta", fecha))
    bruta = dict(fund.serie("ganancia_bruta", fecha))
    flujo = dict(fund.serie("flujo_operativo", fecha))
    eps = dict(fund.serie("eps_diluido", fecha, splits))
    # Las acciones, como el EPS, en la base de hoy; los de balance son al cierre del año fiscal (440).
    acciones = dict(fund.serie("acciones_diluidas", fecha, splits))
    deuda = dict(fund.serie("deuda_lp", fecha))
    activos = dict(fund.serie("activos", fecha))
    patrimonio = dict(fund.serie("patrimonio", fecha))
    caja = dict(fund.serie("caja", fecha))
    capex = dict(fund.serie("capex", fecha))
    operativa = dict(fund.serie("ganancia_operativa", fecha))
    fines = sorted(set(ventas) | set(ganancia))[-n:]

    def millones(x):
        return None if x is None else _num(x / 1e6, 0)

    def margen(num, den):
        return _num(num / den * 100, 1) if num is not None and den else None

    out = []
    for fin in fines:
        r, g, b = ventas.get(fin), ganancia.get(fin), bruta.get(fin)
        # La PRIMERA presentación: los 10-K siguientes repiten el año como comparativo, y con la
        # última el año fiscal 2023 de MU decía «presentado 2025-10-03».
        presentado = min(
            (x.filed for x in fund.registros if x.end == fin and x.concepto in ("revenue", "ganancia_neta")),
            default=None,
        )
        out.append(
            {
                "fin_anio_fiscal": fin,
                "presentado_por_primera_vez": presentado,
                "ventas_musd": millones(r),
                "ganancia_neta_musd": millones(g),
                "margen_bruto_pct": margen(b, r),
                "margen_neto_pct": margen(g, r),
                "eps_diluido": _num(eps.get(fin)),
                "flujo_operativo_musd": millones(flujo.get(fin)),
                "acciones_diluidas_m": _num(acciones[fin] / 1e6, 1) if fin in acciones else None,
                "deuda_lp_musd": millones(deuda.get(fin)),
                "activos_musd": millones(activos.get(fin)),
                "patrimonio_musd": millones(patrimonio.get(fin)),
                "caja_musd": millones(caja.get(fin)),
                "capex_musd": millones(capex.get(fin)),
                # Sin capex no hay flujo libre: tomarlo como 0 lo inflaría hasta el flujo operativo (441).
                "flujo_caja_libre_musd": (
                    millones(flujo[fin] - capex[fin]) if fin in flujo and fin in capex else None
                ),
                "ganancia_operativa_musd": millones(operativa.get(fin)),
                "margen_operativo_pct": margen(operativa.get(fin), r),
            }
        )
    return out


def bloque_multiplos(precio, anuales: list[dict] | None) -> dict | None:
    """Capitalización, precio/ventas y deuda/patrimonio con el último año fiscal de ``anuales`` (440).

    **Puro.** La capitalización es el precio de hoy por las acciones diluidas **promedio** de ese
    año, que es lo que trae el 10-K, y no por las de hoy: si después hubo emisiones o recompras,
    difiere. Sin las acciones del último año no hay capitalización: las de un año anterior, con una
    dilución como la de MARA (de ~113 a ~355 M en cuatro años), serían de otra empresa.
    """
    if not anuales or precio is None:
        return None
    u = anuales[-1]
    acciones, ventas = u.get("acciones_diluidas_m"), u.get("ventas_musd")
    deuda, patrimonio = u.get("deuda_lp_musd"), u.get("patrimonio_musd")
    cap = _num(float(precio) * acciones, 0) if acciones else None
    out = {
        "fin_anio_fiscal": u.get("fin_anio_fiscal"),
        "capitalizacion_musd": cap,
        "precio_ventas": _num(cap / ventas, 2) if cap and ventas and ventas > 0 else None,
        # Con el patrimonio negativo el cociente no dice nada (y cambia de signo): no va.
        "deuda_lp_sobre_patrimonio": (
            _num(deuda / patrimonio, 2) if deuda is not None and patrimonio and patrimonio > 0 else None
        ),
    }
    if all(v is None for k, v in out.items() if k != "fin_anio_fiscal"):
        return None
    out["nota"] = (
        "capitalización = precio de hoy × acciones diluidas promedio de ese año fiscal, no las de hoy"
    )
    return out


def _zona_et():
    from data.yahoo_finance import market_timezone

    return market_timezone()


def hora_et(cuando: datetime | None, zona=None) -> str | None:
    """``cuando`` (UTC naive, como persiste la app, o con zona) en hora del Este: ``AAAA-MM-DD HH:MM ET``.

    Antes la noticia iba con ``str(cuando)[:10]``: la fecha **UTC**, sin hora. Una nota de las 21 h
    ET salía con la fecha del día siguiente, y una de la preapertura no se distinguía de una del
    cierre (tarea 417). Sin zona resoluble, cae a UTC y lo dice.
    """
    if cuando is None:
        return None
    if cuando.tzinfo is None:
        cuando = cuando.replace(tzinfo=timezone.utc)
    zona = zona if zona is not None else _zona_et()
    if zona is None:
        return cuando.strftime("%Y-%m-%d %H:%M UTC")
    return cuando.astimezone(zona).strftime("%Y-%m-%d %H:%M ET")


def estado_precio(fecha_ultima: date, obtenido: datetime, zona=None) -> dict:
    """Si el último precio es un cierre o es intradiario, y a qué hora (tarea 417).

    La opinión de MU del 2026-11-11 se pidió a media hora de la apertura: el precio era
    intradiario (+8,5 % en el día) y Claude no podía saberlo; vio −1 % a 5 días y una nota de
    *«+7 % hoy»* y sospechó que los datos estaban desincronizados. La barra es **intradiaria** si es
    del día de ``obtenido`` en ET, en un día hábil, antes del cierre de las 16:00. Los feriados no
    se conocen: un feriado no tiene barra del día, así que cae en *cierre*, que es lo correcto.
    """
    zona = zona if zona is not None else _zona_et()
    if obtenido.tzinfo is None:
        obtenido = obtenido.replace(tzinfo=timezone.utc)
    local = obtenido.astimezone(zona) if zona is not None else obtenido
    sufijo = "ET" if zona is not None else "UTC"
    abierto = fecha_ultima == local.date() and local.weekday() < 5 and (local.hour, local.minute) < _CIERRE_ET
    return {
        "mercado_abierto": abierto,
        "precio_es": "intradiario, el día no cerró" if abierto else f"cierre del {fecha_ultima}",
        "precio_consultado": local.strftime(f"%Y-%m-%d %H:%M {sufijo}"),
    }


def resumen(texto: str | None, maximo: int = MAX_RESUMEN) -> str | None:
    """El resumen de la noticia en una línea y recortado, o ``None`` si la fuente no trae (426)."""
    limpio = " ".join((texto or "").split())
    if not limpio:
        return None
    return limpio if len(limpio) <= maximo else limpio[: maximo - 1].rstrip() + "…"


def noticias_recientes(ticker: str, dias: int = DIAS_NOTICIAS, clasificar=None) -> list[dict]:
    """Las noticias para Claude de los últimos ``dias`` (las que elige ``elegir_noticias``, la 452),
    de la DB, de la más nueva a la más vieja."""
    return noticias_y_cobertura(ticker, dias, clasificar)[0]


def noticias_y_cobertura(
    ticker: str, dias: int = DIAS_NOTICIAS, clasificar=None, bajar=None
) -> tuple[list[dict], dict]:
    """Las noticias para Claude y el bloque ``cobertura_noticias`` (tarea 442).

    Con ``bajar`` (``bajar_noticias`` en la app), si la app no tiene noticias del ticker de las
    últimas ``FRESCURA_NOTICIAS_H`` horas, primero las baja: TTWO y MARA no están en el universo que
    se cosecha y el 2026-11-20 no tenían ninguna.
    """
    from analysis.news_digest import fetch_news_window, harvest_en_curso
    from database.models import utcnow_naive

    ahora = utcnow_naive()
    desde = ahora - timedelta(days=dias)
    filas = fetch_news_window(desde, tickers=[ticker.upper()])
    intento = bajar is not None and hay_que_bajar(filas, ahora)
    bajadas = None
    if intento:
        bajadas = bajar(ticker)
        if bajadas:
            filas = fetch_news_window(desde, tickers=[ticker.upper()])
    zona = _zona_et()
    noticias, descartadas = _noticias_para_claude(filas, clasificar, zona)
    cobertura = bloque_cobertura(
        filas,
        desde,
        ahora,
        dias=dias,
        intento_bajar=intento,
        bajadas=bajadas,
        harvest_en_curso=harvest_en_curso(),
        zona=zona,
        se_mandan=len(noticias),
        descartadas=descartadas,
    )
    return noticias, cobertura


def _noticias_para_claude(filas: list, clasificar, zona) -> tuple[list[dict], int]:
    """Las noticias elegidas, como las recibe Claude, y cuántas se descartaron por ser de otra empresa."""
    from analysis.news_digest import classify_missing

    # Tarea 452: se elige de toda la ventana, así que se clasifica antes de elegir. Lo que qwen todavía
    # no vio lo clasifica ahora, con tope y de la más nueva a la más vieja (la 427); el resto va con la
    # heurística al vuelo (la 406), como en la pestaña Noticias, y el campo `clasificador` lo dice.
    if clasificar is not None:
        filas = clasificar_a_demanda(filas, clasificar)
    filas = classify_missing(filas)
    filas, descartadas = elegir_noticias(filas, zona)
    out = []
    for f in filas:
        cuando = f.published_at or f.fetched_at
        out.append(
            {
                "publicada": hora_et(cuando, zona),
                "titulo": f.title,
                "resumen": resumen(f.content),
                "tipo": f.event_type,
                "tono_-3_a_3": _num((f.sentiment_score or 0) * 3, 0)
                if f.sentiment_score is not None
                else None,
                "relevancia_0_a_1": relevancia_medida(f),
                "fuente": f.source,
                "clasificador": "heuristica provisional (qwen todavia no la clasifico)"
                if f.provisional
                else f.classified_by,
            }
        )
    return out, descartadas


# ── La cotización de Yahoo, fresca (tarea 453) ──────────────────────────────

# Lo que cambia con el precio y no guarda el cache de 7 días de ``get_company_info``.
CAMPOS_DE_COTIZACION = ("pe_ratio", "eps", "beta", "dividend_yield")


def completar_cotizacion(company: dict | None, fresca: dict | None) -> dict:
    """``company`` con el P/E, el EPS, la beta y el dividendo de ``fresca``, sin pisar lo demás. **Pura**.

    El ``company`` de la pestaña sale del cache de ``get_company_info`` (nombre, sector, industria):
    con fila vigente, el bloque ``yfinance`` de la 418 no salía (6 de 7 opiniones). Al pedir la
    opinión se consulta a Yahoo de nuevo (``fresco=True``) y se suma sólo lo de cotización: si Yahoo
    no contesta, ``fresca`` es el nombre pelado y no tiene que tapar el nombre ni el sector.
    """
    out = dict(company or {})
    for k in CAMPOS_DE_COTIZACION:
        v = (fresca or {}).get(k)
        if v is not None:
            out[k] = v
    return out


# ── Qué noticias van (tarea 452) ─────────────────────────────────────────────

# Con 0,2 o menos la noticia trata de otra empresa (lo dice el prompt): no va, y se cuenta.
RELEVANCIA_DE_OTRA = 0.2
# La que no midió un modelo (la heurística) no se descarta, ni le gana a una medida alta.
_RELEVANCIA_DESCONOCIDA = 0.5


def elegir_noticias(filas: list, zona=None, maximo: int = MAX_NOTICIAS) -> tuple[list, int]:
    """Las ``maximo`` noticias para Claude, y cuántas se descartaron por ser de otra empresa. **Pura**.

    Iban las más nuevas: el 2026-11-23 NVDA tenía 933 en la ventana, las 15 salieron de ese día —7 de
    otras empresas— y quedaron afuera la renuncia del CEO y las investigaciones de los días previos,
    con relevancia 1,0. Ahora, fuera las de relevancia medida ≤ ``RELEVANCIA_DE_OTRA``; del resto, por
    rondas, la más relevante todavía no elegida de cada día (ET), del día más nuevo al más viejo (a igual
    relevancia, la más nueva), hasta ``maximo``. Salen de la más nueva a la más vieja, como antes.
    """

    def momento(f):
        return f.published_at or f.fetched_at or datetime.min

    def relevancia(f) -> float:
        r = relevancia_medida(f)
        return _RELEVANCIA_DESCONOCIDA if r is None else r

    descartadas = 0
    por_dia: dict[str, list] = {}
    for f in filas:
        r = relevancia_medida(f)
        if r is not None and r <= RELEVANCIA_DE_OTRA:
            descartadas += 1
            continue
        m = f.published_at or f.fetched_at
        por_dia.setdefault(hora_et(m, zona)[:10] if m else "", []).append(f)
    for lista in por_dia.values():
        lista.sort(key=lambda f: (relevancia(f), momento(f)), reverse=True)
    dias = sorted(por_dia, reverse=True)
    elegidas: list = []
    ronda = 0
    while len(elegidas) < maximo:
        tanda = [por_dia[d][ronda] for d in dias if ronda < len(por_dia[d])]
        if not tanda:
            break
        elegidas.extend(tanda[: maximo - len(elegidas)])
        ronda += 1
    elegidas.sort(key=momento, reverse=True)
    return elegidas, descartadas


# La heurística no mide relevancia: usa su confianza (0,20 sin pista), y el prompt dice que con 0,2
# o menos la noticia es de otra empresa. Con ese número, Claude descartaba toda noticia provisional
# (14 de 15 en NVDA el 2026-11-20): va null y el prompt lo explica (tarea 449).
_SIN_RELEVANCIA_MEDIDA = frozenset({"heuristic", "fallback"})


def relevancia_medida(f) -> float | None:
    """La relevancia de la fila si la midió un modelo; ``None`` si es de la heurística."""
    if getattr(f, "provisional", False) or (f.classified_by or "") in _SIN_RELEVANCIA_MEDIDA:
        return None
    return _num(f.relevance, 2)


# ── Noticias a demanda y su cobertura (tarea 442) ───────────────────────────

# Las fuentes del harvest de la app menos la SEC: las 8-K se le piden a EDGAR con el User-Agent de
# contacto y quedan para el harvest; el consenso lo junta la nube (la 356).
FUENTES_A_DEMANDA = ("yfinance_news", "finnhub")
TOPE_BAJAR_NOTICIAS_S = 20.0
# Si la más nueva tiene más que esto, se bajan. Un ticker del universo tiene el harvest horario; la
# opinión de MSFT del 2026-11-20, pedida a mitad del harvest, tenía la más nueva del 11/11.
FRESCURA_NOTICIAS_H = 24


def bajar_noticias(ticker: str, *, collector=None, tope_s: float = TOPE_BAJAR_NOTICIAS_S) -> int | None:
    """Baja las noticias de ``ticker`` con las fuentes del harvest y las guarda en ``news_events``.

    Con el mismo dedup del harvest (``_insert_news_if_new``, como la importación de la nube), así
    las ve la pestaña Noticias y las clasifica qwen. Devuelve cuántas guardó, o ``None`` si no se
    pudo (sin red, pasado el tope). Nunca levanta. **Red: sí**; corre en el worker de la opinión.
    """
    from config.logging_config import get_logger

    try:
        from data.news_sources import collect_all
        from data.yahoo_finance import _run_with_timeout
        from database.models import session_scope
        from scripts.harvest_catalysts import _insert_news_if_new

        res = _run_with_timeout(
            collector or collect_all,
            ticker.upper(),
            set(FUENTES_A_DEMANDA),
            timeout=tope_s,
            default=None,
            retries=0,
        )
        if res is None:
            return None
        nuevas = 0
        vistos: set[str] = set()
        urls: set[str] = set()
        with session_scope() as s:
            for item in res.news:
                nuevas += bool(_insert_news_if_new(s, item, vistos, urls))
        get_logger(__name__).info("Noticias de %s a demanda: %d nuevas", ticker.upper(), nuevas)
        return nuevas
    except Exception:
        get_logger(__name__).exception("Noticias de %s a demanda: falló", ticker)
        return None


def _momentos(filas) -> list[datetime]:
    return sorted(m for f in filas if (m := f.published_at or f.fetched_at) is not None)


def hay_que_bajar(filas, ahora: datetime, frescura_h: float = FRESCURA_NOTICIAS_H) -> bool:
    """Sin noticias, o con la más nueva de hace más de ``frescura_h`` horas. **Puro**."""
    momentos = _momentos(filas)
    return not momentos or ahora - momentos[-1] > timedelta(hours=frescura_h)


def bloque_cobertura(
    filas,
    desde: datetime,
    ahora: datetime,
    *,
    dias: int,
    intento_bajar: bool = False,
    bajadas: int | None = None,
    harvest_en_curso: bool = False,
    zona=None,
    se_mandan: int | None = None,
    descartadas: int = 0,
) -> dict:
    """Qué noticias tiene la app del ticker en la ventana y de qué días (ET). **Puro** (442).

    ``dias_sin_noticias`` son los días de la ventana sin ninguna en la app: con un ticker muy cubierto,
    el tope de ítems por pedido de las fuentes no llega a los más viejos (MSFT, del 12 al 17/11).
    ``bajadas`` es lo que se bajó al pedir (``None``: no se pudo); sólo va si se intentó.
    ``se_mandan`` y ``descartadas`` salen de ``elegir_noticias`` (la 452); sin ``se_mandan``, el tope.
    """
    momentos = _momentos(filas)
    out: dict = {
        "ventana_dias": dias,
        "en_la_ventana": len(filas),
        "se_mandan": min(len(filas), MAX_NOTICIAS) if se_mandan is None else se_mandan,
    }
    if descartadas:
        out["descartadas_de_otras_empresas"] = descartadas
    if momentos:
        con = {hora_et(m, zona)[:10] for m in momentos}
        d0 = date.fromisoformat(hora_et(desde, zona)[:10])
        d1 = date.fromisoformat(hora_et(ahora, zona)[:10])
        rango = [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]
        out["mas_vieja"] = hora_et(momentos[0], zona)
        out["mas_nueva"] = hora_et(momentos[-1], zona)
        out["dias_sin_noticias"] = [d for d in rango if d not in con]
        nota = (
            "se mandan las más relevantes de cada día, repartidas entre los días de la ventana (no las "
            "más nuevas), sin las de otras empresas; un día sin noticias en la app no es un día sin "
            "noticias"
        )
    elif intento_bajar and bajadas is None:
        nota = (
            f"la app no tiene noticias de este ticker de los últimos {dias} días, y al pedir la "
            "opinión no se pudieron bajar (sin red o sin respuesta de las fuentes)"
        )
    elif intento_bajar:
        nota = f"las fuentes de la app no trajeron noticias de este ticker de los últimos {dias} días"
    else:
        nota = f"la app no tiene noticias de este ticker de los últimos {dias} días"
    if intento_bajar:
        out["bajadas_al_pedir"] = bajadas
    if harvest_en_curso:
        out["harvest_en_curso"] = True
        nota += "; el harvest de noticias del día estaba corriendo: las de hoy pueden no estar todavía"
    out["nota"] = nota
    return out


# ── Clasificar a demanda (tarea 427) ─────────────────────────────────────────

# qwen tarda ~3 s por noticia (la 413). Con 15 pendientes son ~45 s, que se suman a los ~15 s de la
# opinión; pasado el tope se manda la heurística, rotulada, como antes. Una llamada que ya arrancó
# puede pasarse del tope hasta su propio timeout.
TOPE_CLASIFICAR_S = 45.0
TIMEOUT_POR_NOTICIA_S = 20.0


def clasificador_a_demanda():
    """El clasificador del pipeline diario (``hybrid-ollama`` con el mismo modelo), con un timeout corto."""
    from analysis.news_digest import DEFAULT_CLASSIFY_MODEL
    from data.catalyst_classifier import classify, make_hybrid_backend, make_ollama_backend

    backend = make_hybrid_backend(
        llm_backend=make_ollama_backend(model=DEFAULT_CLASSIFY_MODEL, timeout=TIMEOUT_POR_NOTICIA_S)
    )
    return lambda titulo, contenido, fuente, ticker: classify(
        titulo, contenido, fuente, ticker, backend=backend
    )


def _guardar_clasificacion(news_id: int, c) -> None:
    """Lo mismo que guarda el classify diario (``scripts/classify_catalysts._persistir``), para una fila."""
    from database.models import NewsEvent, session_scope, utcnow_naive

    with session_scope() as s:
        ev = s.get(NewsEvent, news_id)
        if ev is None:
            return
        ev.event_type = c.event_type
        ev.sentiment = c.sentiment
        ev.classifier_confidence = c.confidence
        ev.classified_at = utcnow_naive()
        ev.classified_by = c.classifier
        ev.sentiment_score = c.sentiment_score
        ev.relevance = c.relevance


def clasificar_a_demanda(
    filas: list,
    clasificar,
    *,
    tope_s: float = TOPE_CLASIFICAR_S,
    reloj=time.monotonic,
    guardar=_guardar_clasificacion,
) -> list:
    """Clasifica con el modelo las ``filas`` que todavía no tienen su clasificación, y la guarda.

    Pendiente es sin clasificar o con el respaldo de un LLM caído (``fallback``, la 436). Las de
    ``sec_8k`` no: las clasifica la heurística por diseño. Si el modelo no contesta (devuelve la
    heurística o el respaldo), no se insiste con las demás; pasado ``tope_s``, tampoco. Lo que queda
    sin clasificar sigue a ``classify_missing``, rotulado provisional como antes. Guardar sirve
    también a la pestaña Noticias. Nunca levanta.
    """
    from dataclasses import replace

    from data.catalyst_classifier import RESPALDO

    limite = reloj() + tope_s
    caido = False
    out = []
    for f in filas:
        pendiente = (f.event_type is None or f.classified_by == RESPALDO) and f.source != "sec_8k"
        if not pendiente or caido or reloj() >= limite:
            out.append(f)
            continue
        try:
            c = clasificar(f.title, f.content, f.source, f.ticker)
        except Exception:
            c = None
        if c is None or c.classifier in ("heuristic", RESPALDO):
            caido = True
            out.append(f)
            continue
        try:
            guardar(f.id, c)
        except Exception:
            from config.logging_config import get_logger

            get_logger(__name__).exception("No se pudo guardar la clasificación de la noticia %s", f.id)
        out.append(
            replace(
                f,
                event_type=c.event_type,
                sentiment=c.sentiment,
                classifier_confidence=c.confidence,
                sentiment_score=c.sentiment_score,
                classified_by=c.classifier,
                relevance=c.relevance,
                provisional=False,
            )
        )
    return out


# ── Los pares (tarea 420) ────────────────────────────────────────────────────

MAX_PARES = 5
# Un par cuya serie termina más de estos días antes que la del ticker no entra: el cache guarda
# tickers que nadie refresca (el 2026-11-20, 20 de 158 terminaban entre agosto y octubre), y sus
# retornos serían de otra ventana.
MAX_DESFASE_DIAS = 5
# Los índices, para separar lo que le pasa a la empresa de lo que le pasa al mercado (la opinión de
# MSFT del 2026-11-20 lo pidió: «para saber si la caída es de Microsoft o de todo el mercado»).
INDICES = ("SPY", "QQQ")
# El ETF del sector: SPDR por sector de Yahoo, y SOXX para semiconductores, que es la que pidió la
# opinión de MU (sus pares de memoria se movían ±25 %).
ETF_POR_INDUSTRIA = {"Semiconductors": "SOXX", "Semiconductor Equipment & Materials": "SOXX"}
ETF_POR_SECTOR = {
    "Technology": "XLK",
    "Communication Services": "XLC",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
}


# Tarea 446: cuando la industria de Yahoo no dice nada del negocio. MARA es una minera de bitcoin y
# Yahoo la pone en *Capital Markets*: con la 420 recibía GS, MS y SCHW (2026-11-20). TTWO no tenía
# ningún par de su industria en el cache. Cada entrada dice por qué; se agregan a mano.
PARES_A_MANO: dict[str, tuple[tuple[str, ...], str]] = {
    "MARA": (
        ("RIOT", "CLSK", "CIFR", "HUT"),
        "minera de bitcoin; Yahoo la pone en Capital Markets, con los bancos de inversión",
    ),
    "TTWO": (
        ("RBLX", "NTDOY"),
        "videojuegos; el cache no tenía ningún par de su industria (EA dejó de cotizar en 2026)",
    ),
}
REFERENCIA_A_MANO: dict[str, tuple[str, str]] = {
    "MARA": ("BTC-USD", "su ingreso es el bitcoin que mina; su precio lo sigue"),
}


def _retornos(serie) -> dict | None:
    """Retorno a 5 y 20 ruedas de una serie ``[(día, cierre)]``, contra cierres; ``None`` si es corta."""
    if not serie or len(serie) < 6:
        return None
    ultimo = serie[-1][1]
    out = {"al": serie[-1][0], "5d": _pct(ultimo / serie[-6][1] - 1)}
    out["20d"] = _pct(ultimo / serie[-21][1] - 1) if len(serie) >= 21 else None
    return out


def _desfase(serie, al: str | None) -> int | None:
    """Días entre el último cierre de ``serie`` y ``al``; ``None`` sin ``al`` o sin serie."""
    if not serie or not al:
        return None
    try:
        return (date.fromisoformat(al[:10]) - date.fromisoformat(str(serie[-1][0])[:10])).days
    except ValueError:
        return None


def _al_dia(serie, al: str | None) -> bool:
    d = _desfase(serie, al)
    return bool(serie) and (d is None or d <= MAX_DESFASE_DIAS)


def bloque_pares(
    ticker: str,
    industria,
    sector,
    universo: dict,
    series,
    maximo: int = MAX_PARES,
    *,
    referencia=None,
    al: str | None = None,
) -> dict | None:
    """Los retornos de hasta ``maximo`` pares de la **misma industria**, del ETF del sector y de los
    índices. **Puro**.

    ``universo`` es ``{ticker: (sector, industria)}``; ``series(t)`` devuelve los cierres guardados de
    un par (``[(día, cierre)]`` o ``None``) y ``referencia(t)`` los del ETF y los índices (por defecto,
    ``series``; en la app los baja si faltan). ``al`` es el día de la última barra del ticker: lo que
    termine más de ``MAX_DESFASE_DIAS`` antes no entra. Por industria y no por sector: en *Technology*
    entran el software y los semiconductores juntos, y a MU no le dice nada cómo se mueve Microsoft.
    ``None`` si no hay nada.
    """
    referencia = referencia or series
    propio = ticker.upper()
    industria = None if not industria or industria == "N/A" else industria
    pares = []
    a_mano = PARES_A_MANO.get(propio)
    # Los pares a mano no están en el universo guardado: se piden como el ETF (y se bajan si faltan).
    for t in a_mano[0][:maximo] if a_mano else ():
        serie = referencia(t)
        r = _retornos(serie) if _al_dia(serie, al) else None
        if r is not None:
            pares.append({"ticker": t, **r})
    for t in sorted(universo) if industria and not a_mano else ():
        if t == propio or universo[t][1] != industria:
            continue
        serie = series(t)
        r = _retornos(serie) if _al_dia(serie, al) else None
        if r is not None:
            pares.append({"ticker": t, **r})
        if len(pares) >= maximo:
            break

    def _de_referencia(t):
        if t == propio:
            return None
        serie = referencia(t)
        r = _retornos(serie) if _al_dia(serie, al) else None
        return None if r is None else {"ticker": t, **r}

    etf_t = ETF_POR_INDUSTRIA.get(industria or "") or ETF_POR_SECTOR.get(sector or "")
    etf = _de_referencia(etf_t) if etf_t else None
    indices = [x for x in map(_de_referencia, INDICES) if x is not None]
    ref = None
    if propio in REFERENCIA_A_MANO:
        ref_t, motivo = REFERENCIA_A_MANO[propio]
        ref = _de_referencia(ref_t)
        if ref is not None:
            ref["motivo"] = motivo
    if not pares and etf is None and not indices and ref is None:
        return None
    out = {
        "industria": industria,
        "nota": (
            "retornos contra cierres. pares: los tickers de la misma industria que la app tiene "
            "guardados, no la industria entera; etf_del_sector e indices: para separar lo de la "
            "empresa de lo del sector y del mercado"
        ),
        "pares": pares,
        "etf_del_sector": etf,
        "indices": indices,
    }
    if a_mano:
        out["pares_a_mano"] = a_mano[1]
    if ref is not None:
        out["referencia"] = ref
    return out


def _dato(x) -> str | None:
    return None if not x or x == "N/A" else str(x)


def _ultimo_dia(df) -> str | None:
    try:
        i = df.index[-1]
    except (AttributeError, IndexError, TypeError):
        return None
    return str(i.date()) if hasattr(i, "date") else str(i)[:10]


def _bajar_al_cache(t: str) -> None:
    """Baja la serie de ``t`` con el período del scan y la deja en el cache (``get_historical_data``).

    El mismo período que el scan: para SPY, que el scan baja como benchmark, es el mismo frame.
    """
    from data.yahoo_finance import get_historical_data
    from paper_trading.engine import _resolve_history_period

    get_historical_data(t, period=_resolve_history_period(), interval="1d")


def pares_de(ticker: str, company: dict | None, df=None, bajar=_bajar_al_cache) -> dict | None:
    """El bloque ``pares``: la industria de ``company_info_cache`` y los cierres del cache de precios.

    Los pares salen sólo del cache (sin red). El ETF del sector y los índices se bajan con ``bajar``
    cuando el cache no los tiene o termina antes que el ticker (``df``): si no, el ETF no saldría
    nunca (el 2026-11-20 el cache tenía SPY y ningún ETF). Corre en el worker de la opinión, no en el
    hilo de la GUI. ``None`` si falla o no hay nada.
    """
    from config.logging_config import get_logger

    try:
        from data import historical_series
        from database.models import CompanyInfoCache, session_scope

        def guardada(t):
            # Una sesión por lectura, y no una abierta durante las bajadas. La conexión de la sesión y
            # no el archivo por fuera: así lee la misma DB que la app (y en los tests, la de memoria).
            with session_scope() as s:
                return historical_series.close_series(s.connection().connection.dbapi_connection, t)

        with session_scope() as s:
            universo = {f.ticker.upper(): (f.sector, f.industry) for f in s.query(CompanyInfoCache).all()}
        guardado = universo.get(ticker.upper(), (None, None))
        # `get_company_info` devuelve "N/A" cuando Yahoo no tiene el dato: eso no es una industria.
        industria = _dato((company or {}).get("industry")) or _dato(guardado[1])
        sector = _dato((company or {}).get("sector")) or _dato(guardado[0])
        al = _ultimo_dia(df)

        def de_referencia(t):
            serie = guardada(t)
            desfase = _desfase(serie, al)
            if serie and (desfase is None or desfase <= 0):
                return serie
            try:
                bajar(t)
            except Exception:
                get_logger(__name__).warning("Pares: no se pudo bajar %s", t, exc_info=True)
                return serie
            return guardada(t)

        return bloque_pares(ticker, industria, sector, universo, guardada, referencia=de_referencia, al=al)
    except Exception:
        get_logger(__name__).exception("Pares de %s para la opinión: falló", ticker)
        return None


# ── La llamada ───────────────────────────────────────────────────────────────


def comando(exe: str, modelo: str = MODELO) -> list[str]:
    """Los argumentos de ``claude -p``, aislados (ver el docstring del módulo)."""
    return [
        exe,
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(ESQUEMA, ensure_ascii=False),
        "--system-prompt",
        SYSTEM_PROMPT,
        "--tools",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--no-session-persistence",
        "--model",
        modelo,
    ]


# Lo que se saca del entorno del proceso: las credenciales de API (le ganan al login de la
# suscripción) y las variables de una sesión de Claude Code (autentican por la sesión padre).
_SIN_ESTAS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
_SIN_PREFIJO = ("CLAUDECODE", "CLAUDE_CODE_", "CLAUDE_AGENT_SDK")


def entorno(base: dict | None = None) -> dict:
    """El entorno con que se lanza ``claude``: el de la app, sin credenciales de API ni sesión."""
    base = dict(os.environ if base is None else base)
    return {
        k: v
        for k, v in base.items()
        if k.upper() not in _SIN_ESTAS and not k.upper().startswith(_SIN_PREFIJO)
    }


def carpeta_neutra() -> Path:
    """Una carpeta fuera del repo, para que Claude Code no cargue el ``CLAUDE.md`` del proyecto."""
    d = Path(tempfile.gettempdir()) / "finanzias_opinion_claude"
    d.mkdir(parents=True, exist_ok=True)
    return d


def validar(salida: dict) -> dict:
    """La opinión de ``structured_output``, chequeada contra el esquema (el CLI ya valida; esto
    es la red por si una versión futura cambia el formato). Levanta ``OpinionError``."""
    op = salida.get("structured_output")
    if not isinstance(op, dict):
        raise OpinionError("Claude respondió sin el formato pedido (no hay structured_output).")
    if op.get("recomendacion") not in RECOMENDACIONES:
        raise OpinionError(f"Recomendación inválida: {op.get('recomendacion')!r}.")
    conf = op.get("confianza")
    if not isinstance(conf, int) or not 0 <= conf <= 100:
        raise OpinionError(f"Confianza inválida: {conf!r}.")
    if not isinstance(op.get("tesis"), str) or not op["tesis"].strip():
        raise OpinionError("La opinión vino sin tesis.")
    for k in ("riesgos", "cambiaria_opinion", "datos_faltantes"):
        if not isinstance(op.get(k), list) or not all(isinstance(x, str) for x in op[k]):
            raise OpinionError(f"El campo {k} no es una lista de textos.")
    return op


def pedir_opinion(
    datos: dict,
    *,
    exe: str | None = None,
    modelo: str = MODELO,
    timeout_s: float = TIMEOUT_S,
    runner=subprocess.run,
) -> Opinion:
    """Le pide la opinión a Claude Code y la devuelve validada. Levanta ``OpinionError``."""
    exe = exe or ubicar_claude()
    if not exe:
        raise OpinionError(
            "No se encontró Claude Code (ni en el PATH ni en la extensión de VS Code). "
            "Instalalo o indicá su ruta en la variable FINANZIAS_CLAUDE_EXE."
        )
    pregunta = "Estos son los datos de la acción. Dame tu opinión con el formato pedido.\n\n" + json.dumps(
        datos, ensure_ascii=False, indent=1
    )
    inicio = time.monotonic()
    try:
        proc = runner(
            comando(exe, modelo),
            input=pregunta,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_s,
            cwd=str(carpeta_neutra()),
            env=entorno(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as e:
        raise OpinionError(f"Claude no respondió en {timeout_s:.0f} s.") from e
    except OSError as e:
        raise OpinionError(f"No se pudo ejecutar Claude Code: {e}") from e
    segundos = time.monotonic() - inicio
    try:
        salida = json.loads(proc.stdout or "")
    except json.JSONDecodeError as e:
        detalle = (proc.stderr or proc.stdout or "").strip()[:300]
        raise OpinionError(f"Claude Code no devolvió JSON (código {proc.returncode}): {detalle}") from e
    if salida.get("is_error") or proc.returncode != 0:
        detalle = str(salida.get("result") or proc.stderr or "")[:300]
        if "401" in detalle or "authenticat" in detalle.lower():
            detalle += (
                " — Claude Code no pudo entrar con tu login de claude.ai: abrí Claude Code una vez "
                "y verificá que estés logueado."
            )
        raise OpinionError(f"Claude Code devolvió un error: {detalle}")
    op = validar(salida)
    return Opinion(
        recomendacion=op["recomendacion"],
        confianza=op["confianza"],
        tesis=op["tesis"].strip(),
        riesgos=list(op["riesgos"]),
        cambiaria_opinion=list(op["cambiaria_opinion"]),
        datos_faltantes=list(op["datos_faltantes"]),
        modelo=modelo,
        segundos=round(segundos, 1),
    )


# ── El registro ──────────────────────────────────────────────────────────────


def guardar(ticker: str, opinion: Opinion, datos: dict, hoy: date | None = None) -> bool:
    """Upsert por ``(ticker, día)``: pedirla de nuevo el mismo día la reemplaza, y la reemplazada
    pasa antes a ``claude_opinions_reemplazadas`` (tarea 438).

    Guarda también con qué código corre la app (tarea 433): el commit del arranque y si había WIP
    sin commitear. **Y si el árbol cambió desde el arranque** (la 449), ``codigo_wip`` va ``True``:
    este módulo y los demás que se importan tarde pueden ser de otro código que el del commit.
    Devuelve si la opinión salió con código mezclado.
    """
    from config import codigo as _codigo
    from database.models import (
        COLUMNAS_OPINION,
        ClaudeOpinion,
        ClaudeOpinionReemplazada,
        session_scope,
        utcnow_naive,
    )

    codigo = _codigo.al_arrancar()
    mezcla = _codigo.mezclado(codigo, _codigo.estado_del_codigo())
    if mezcla:
        from config.logging_config import get_logger

        get_logger(__name__).warning(
            "La opinión de %s salió con código mezclado: la app arrancó en %s y el árbol cambió "
            "después (tarea 449); se guarda como WIP",
            ticker.upper(),
            codigo.corto,
        )

    fecha = (hoy or date.today()).isoformat()
    respuesta = {
        k: getattr(opinion, k)
        for k in ("recomendacion", "confianza", "tesis", "riesgos", "cambiaria_opinion", "datos_faltantes")
    }
    with session_scope() as s:
        fila = (
            s.query(ClaudeOpinion)
            .filter(ClaudeOpinion.ticker == ticker.upper(), ClaudeOpinion.fecha == fecha)
            .one_or_none()
        )
        if fila is None:
            fila = ClaudeOpinion(ticker=ticker.upper(), fecha=fecha)
            s.add(fila)
        else:
            # Tarea 438: la que se pisa pasa entera al histórico, en la misma transacción.
            s.add(
                ClaudeOpinionReemplazada(
                    opinion_id=fila.id,
                    reemplazada_at=utcnow_naive(),
                    **{c: getattr(fila, c) for c in COLUMNAS_OPINION},
                )
            )
        fila.recomendacion = opinion.recomendacion
        fila.confianza = opinion.confianza
        fila.precio = datos.get("precio")
        fila.modelo = opinion.modelo
        fila.respuesta_json = json.dumps(respuesta, ensure_ascii=False)
        fila.datos_json = json.dumps(datos, ensure_ascii=False)
        fila.segundos = opinion.segundos
        fila.creado_at = utcnow_naive()
        fila.codigo_commit = codigo.commit
        fila.codigo_wip = (codigo.wip or mezcla) if codigo.commit else None
    return mezcla


def opinion_de_hoy(ticker: str, hoy: date | None = None) -> tuple[Opinion, datetime | None] | None:
    """La opinión ya guardada hoy para ``ticker`` (para no pedirla de nuevo), o ``None``."""
    from database.models import ClaudeOpinion, session_scope

    fecha = (hoy or date.today()).isoformat()
    with session_scope() as s:
        fila = (
            s.query(ClaudeOpinion)
            .filter(ClaudeOpinion.ticker == ticker.upper(), ClaudeOpinion.fecha == fecha)
            .one_or_none()
        )
        if fila is None:
            return None
        r = json.loads(fila.respuesta_json)
        return (
            Opinion(
                recomendacion=r["recomendacion"],
                confianza=int(r["confianza"]),
                tesis=r["tesis"],
                riesgos=list(r.get("riesgos", [])),
                cambiaria_opinion=list(r.get("cambiaria_opinion", [])),
                datos_faltantes=list(r.get("datos_faltantes", [])),
                modelo=fila.modelo or MODELO,
                segundos=float(fila.segundos or 0.0),
            ),
            fila.creado_at,
        )
