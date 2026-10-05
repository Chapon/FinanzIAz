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
from datetime import date, datetime, timedelta
from pathlib import Path

MODELO = "claude-opus-5-5"
TIMEOUT_S = 240.0
MAX_NOTICIAS = 15
DIAS_NOTICIAS = 14

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
de analistas y noticias recientes con un tono clasificado por un modelo local.

Reglas:
- Usá SOLO esos datos. No inventes cifras, noticias, resultados ni eventos que no estén. Si falta \
algo importante para opinar, ponelo en datos_faltantes.
- Tené en cuenta lo que la app sabe de sus propias señales: ninguna tiene poder predictivo \
demostrado. Cuando se midió (su puntaje de compra contra el retorno a 5 días, y el impacto de las \
noticias) no se detectó relación; el modelo XGBoost, el consenso y el tono de las noticias no \
están validados. Pesalos con ese escepticismo.
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
) -> dict:
    """El resumen que se manda a Claude. **Puro**: todo llega por parámetro.

    No incluye la posición del usuario en la acción.
    """
    close = df["Close"].astype(float)
    ultimo = float(close.iloc[-1])

    def ret(n: int):
        return _num((ultimo / float(close.iloc[-1 - n]) - 1) * 100) if len(close) > n else None

    ventana = close.iloc[-252:]
    datos: dict = {
        "ticker": ticker.upper(),
        "empresa": (company or {}).get("name"),
        "sector": (company or {}).get("sector"),
        "fecha_datos": str(df.index[-1].date()) if hasattr(df.index[-1], "date") else str(df.index[-1]),
        "precio": _num(ultimo),
        "retornos_pct": {"5d": ret(5), "20d": ret(20), "60d": ret(60), "250d": ret(250)},
        "rango_52s": {"max": _num(ventana.max()), "min": _num(ventana.min())},
        "volatilidad_anual_20d_pct": _num(close.pct_change().iloc[-20:].std() * (252**0.5) * 100),
    }
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
    if noticias:
        datos["noticias"] = noticias[:MAX_NOTICIAS]
    return datos


def noticias_recientes(ticker: str, dias: int = DIAS_NOTICIAS) -> list[dict]:
    """Las noticias del ticker de los últimos ``dias``, de la DB (sólo lectura), más nuevas primero."""
    from analysis.news_digest import fetch_news_window
    from database.models import utcnow_naive

    filas = fetch_news_window(utcnow_naive() - timedelta(days=dias), tickers=[ticker.upper()])
    out = []
    for f in filas[:MAX_NOTICIAS]:
        cuando = f.published_at or f.fetched_at
        out.append(
            {
                "fecha": str(cuando)[:10] if cuando else None,
                "titulo": f.title,
                "tipo": f.event_type,
                "tono_-3_a_3": _num((f.sentiment_score or 0) * 3, 0)
                if f.sentiment_score is not None
                else None,
                "fuente": f.source,
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
