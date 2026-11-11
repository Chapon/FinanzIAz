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
DIAS_NOTICIAS = 14

# Qué recibe Claude, versionado (tarea 417): la 321 mide si las opiniones aciertan, y cambiar los
# datos cambia el instrumento. Cada tarea que agrega o cambia un bloque la sube; las filas viejas de
# ``claude_opinions`` no tienen el campo y son la versión 1.
#   2 — retorno del día, si el precio es intradiario, y la hora ET de las noticias (417).
#   3 — valuación de la tarjeta, fundamentales anuales de EDGAR y el P/E de yfinance (418).
#   4 — próximo balance y sorpresas de EPS de los últimos trimestres (419).
VERSION_DATOS = 4
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
todavía no cerró. Las horas de las noticias están en hora del Este de EE.UU. (ET).
- valuacion y fundamentales_anuales salen de los 10-K presentados a la SEC (EDGAR): son anuales, \
por año fiscal. La app NO tiene el guidance de la empresa ni las cifras trimestrales: no los \
anotes en datos_faltantes; si te parecen decisivos, decilo en los riesgos. El bloque yfinance es \
un dato de Yahoo, de otra fuente y sin verificar contra EDGAR.
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
            "recomendaciones": (analyst.get("recommendations") or [])[:3],
            "precios_objetivo": analyst.get("price_targets"),
        }
    v = bloque_valuacion(valuacion)
    if v:
        datos["valuacion"] = v
    if anuales:
        datos["fundamentales_anuales"] = anuales
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
    return datos


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
        "fuente": "EDGAR (10-K), lo presentado hasta hoy",
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
            "empresas_comparadas": v.calidad.get("n"),
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
            }
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


def noticias_recientes(ticker: str, dias: int = DIAS_NOTICIAS) -> list[dict]:
    """Las noticias del ticker de los últimos ``dias``, de la DB (sólo lectura), más nuevas primero."""
    from analysis.news_digest import classify_missing, fetch_news_window
    from database.models import utcnow_naive

    filas = fetch_news_window(utcnow_naive() - timedelta(days=dias), tickers=[ticker.upper()])
    # Tarea 406: las que qwen todavía no clasificó salían con tipo y tono en None. Van con la
    # heurística al vuelo, como en la pestaña Noticias, y el campo `clasificador` lo dice.
    filas = classify_missing(filas[:MAX_NOTICIAS])
    out = []
    zona = _zona_et()
    for f in filas:
        cuando = f.published_at or f.fetched_at
        out.append(
            {
                "publicada": hora_et(cuando, zona),
                "titulo": f.title,
                "tipo": f.event_type,
                "tono_-3_a_3": _num((f.sentiment_score or 0) * 3, 0)
                if f.sentiment_score is not None
                else None,
                "fuente": f.source,
                "clasificador": "heuristica provisional (qwen todavia no la clasifico)"
                if f.provisional
                else f.classified_by,
            }
        )
    return out


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


def guardar(ticker: str, opinion: Opinion, datos: dict, hoy: date | None = None) -> None:
    """Upsert por ``(ticker, día)``: pedirla de nuevo el mismo día la reemplaza."""
    from database.models import ClaudeOpinion, session_scope, utcnow_naive

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
        fila.recomendacion = opinion.recomendacion
        fila.confianza = opinion.confianza
        fila.precio = datos.get("precio")
        fila.modelo = opinion.modelo
        fila.respuesta_json = json.dumps(respuesta, ensure_ascii=False)
        fila.datos_json = json.dumps(datos, ensure_ascii=False)
        fila.segundos = opinion.segundos
        fila.creado_at = utcnow_naive()


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
