"""
Centralized logging configuration for FinanzIAs.

Usage
-----
    from config.logging_config import get_logger
    log = get_logger(__name__)
    log.info("hello")

The logging system is initialized once at app startup via ``setup_logging()``.
After that, every module just calls ``get_logger(__name__)`` and never
configures handlers itself.

Design
------
- One rotating file handler at ``~/.finanzias/finanzias.log`` (5 MB × 3).
- One stream handler to stderr for development visibility.
- Per-module log levels can be raised/lowered via the
  ``logging_levels`` dict in ``settings.json`` (e.g. ``{"data.yahoo_finance": "DEBUG"}``).
- Noisy third-party libraries (urllib3, yfinance, matplotlib) are pinned to
  WARNING by default.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys
from pathlib import Path

# ── File location ────────────────────────────────────────────────────────────
LOG_DIR = Path.home() / ".finanzias"
LOG_FILE = LOG_DIR / "finanzias.log"
# Valor de ``FINANZIAS_LOG_FILE`` que pide «sin archivo» (tarea 294). La vacía también lo
# pide, pero en Windows una variable vacía **no se hereda**: el hijo la ve sin setear y cae al
# log de producción. El ``:`` hace que no pueda ser una ruta válida en Windows.
SIN_ARCHIVO = ":sin-archivo:"

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_LEVEL = logging.INFO
# Tarea 288: `%(origen)s` va al FINAL y vale "" para la app, así que una línea de la app es
# idéntica a la de antes y los que parsean el log (el censo, la telemetría) no se rompen.
DEFAULT_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s%(origen)s"
DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3

# ── Modules whose default log level should be quieter than the root ──────────
NOISY_LIBS = (
    "urllib3",
    "urllib3.connectionpool",
    "yfinance",
    "matplotlib",
    "matplotlib.font_manager",
    "PIL",
)

_INITIALIZED = False

# Cada cuántas repeticiones idénticas se emite un resumen. Ver ``_RepeatFilter``.
REPEAT_SUMMARY_EVERY = 25


class _RepeatFilter(logging.Filter):
    """Colapsa mensajes **idénticos** repetidos de una librería ruidosa (tarea 85).

    Medido sobre el log limpio (la ventana posterior al arreglo de la tarea 78,
    que sacó a la suite del log de producción): de **100 ERROR**, **98** eran la
    misma línea de ``yfinance`` —``$AVB: possibly delisted; no price data found
    (period=5d)``— repetida **2 veces por scan durante 4h18m**. Un ticker era el
    **99%** de los ERROR del log.

    Eso no es un defecto de producción: es una condición conocida repetida. Pero
    entrena a saltear los ERROR, y este proyecto **usa el log como evidencia para
    priorizar** (las tareas 18, 19 y 25 salieron de triagear logs). Es el mismo
    problema que la 25 resolvió por dedup, un nivel más abajo.

    Qué hace: deja pasar la **primera** ocurrencia intacta y después una cada
    ``REPEAT_SUMMARY_EVERY``, anotando el conteo. **No se pierde información**: el
    mensaje sigue estando y ahora además dice cuántas veces pasó — que es el dato
    que antes había que contar a mano con ``grep -c``.

    Sólo se aplica a ``NOISY_LIBS``, que ya están declaradas como ruidosas. El log
    de la app **no se toca**: una línea nuestra repetida es una señal, no ruido.
    """

    def __init__(self, cada: int = REPEAT_SUMMARY_EVERY) -> None:
        super().__init__()
        self._cada = max(2, int(cada))
        self._vistos: dict[tuple[str, str], int] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            clave = (record.name, record.levelno, record.getMessage())
        except Exception:  # pragma: no cover — un %-format roto no puede tapar el log
            return True
        n = self._vistos.get(clave, 0) + 1
        self._vistos[clave] = n
        if n == 1:
            return True
        if n % self._cada == 0:
            record.msg = f"{clave[2]}  [repetido {n} veces]"
            record.args = ()
            return True
        return False


# Tarea 276: valores de credenciales en lo que se escribe al log. La key de Finnhub viajaba
# como `?token=` en la URL, y un error de `requests` escribe la URL completa: quedaba 450
# veces en texto plano en `finanzias.log`. Los proveedores ya la mandan por header; esto es
# la segunda capa, para cualquier URL o mensaje que la traiga.
_SECRETOS = re.compile(
    r"(?P<k>\b(?:token|apikey|api_key|apiKey|access_token|X-Finnhub-Token)[\"']?\s*[=:]\s*[\"']?)"
    r"(?P<v>[A-Za-z0-9_\-\.]{6,})"
)
_SLACK = re.compile(r"\bxox[abprs]-[0-9A-Za-z\-]{6,}")


def enmascarar(texto: str) -> str:
    """Reemplaza por ``***`` el valor de una credencial en ``texto``. Puro."""
    texto = _SECRETOS.sub(lambda m: m.group("k") + "***", texto)
    return _SLACK.sub("xox?-***", texto)


def origen_del_proceso(argv: list[str] | None = None) -> str | None:
    """De qué proceso viene el log: ``None`` para la app (``main.py``), o el nombre del script.

    Tarea 288: ``get_logger`` configura el archivo de producción para **cualquier** proceso que
    importe un módulo del proyecto, así que un runner, una prueba a mano o un job escribían en
    ``finanzias.log`` igual que la app. La auditoría de logs encontró dos firmas *desconocidas*
    que no eran de la app (una corrida a mano del cuadre de la 266 y una prueba de stooq).
    """
    argv = sys.argv if argv is None else argv
    primero = (argv[0] if argv else "") or ""
    if primero in ("-c", ""):
        return "python -c"
    if primero == "-":
        return "python stdin"
    nombre = Path(primero).name
    if nombre == "main.py":
        return None
    return nombre[:-3] if nombre.endswith(".py") else nombre


class _FiltroOrigen(logging.Filter):
    """Agrega ``record.origen``: vacío para la app, ``  [proceso: X]`` para cualquier otro."""

    def __init__(self, origen: str | None) -> None:
        super().__init__()
        self._sufijo = "" if origen is None else f"  [proceso: {origen}]"

    def filter(self, record: logging.LogRecord) -> bool:
        record.origen = self._sufijo
        return True


class FormatterQueEnmascara(logging.Formatter):
    """``logging.Formatter`` que enmascara credenciales en el texto **ya formateado**.

    Va en el formatter y no en un ``Filter`` porque el traceback (``exc_text``) se arma
    adentro de ``format()``: un filtro sobre el mensaje no lo ve, y era justamente ahí
    —en el ``MaxRetryError`` con la URL— donde estaba la key.
    """

    def format(self, record: logging.LogRecord) -> str:
        return enmascarar(super().format(record))


def setup_logging(level: int = DEFAULT_LEVEL, *, log_file: Path | None = None) -> None:
    """
    Initialize the root logger. Idempotent — safe to call multiple times.
    Should be invoked exactly once from ``main.py`` before any logger is used.

    Dónde escribe, por precedencia (tarea 78):

    1. el argumento ``log_file``, si viene;
    2. la variable de entorno ``FINANZIAS_LOG_FILE`` — una ruta, o ``SIN_ARCHIVO``
       (o vacía) para **no escribir ningún archivo** (sólo consola);
    3. ``~/.finanzias/finanzias.log``.

    El (2) existe porque la **suite escribía en el log de producción**: 551
    líneas por corrida, con tracebacks de `tests/` que se leen como defectos de
    la app. Eso es una fábrica de falsos positivos para cualquier triage que use
    el log como evidencia — y este proyecto lo usa (de ahí salieron las tareas
    18, 19 y 25). ``tests/conftest.py`` la setea en ``SIN_ARCHIVO``: vacía, los
    subprocesos de la suite la perdían en Windows y escribían acá (tarea 294).
    """
    global _INITIALIZED
    if _INITIALIZED:
        return

    if log_file is None:
        env = os.environ.get("FINANZIAS_LOG_FILE")
        if env is not None:
            # Centinela o vacía = a propósito sin archivo. Es distinto de "no seteada".
            sin_archivo = not env.strip() or env.strip() == SIN_ARCHIVO
            log_file = None if sin_archivo else Path(env)
        else:
            log_file = LOG_FILE
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            # ~/.finanzias/ should always be creatable, but if not, fall back to
            # console-only logging instead of crashing the app on startup.
            log_file = None

    formatter = FormatterQueEnmascara(DEFAULT_FORMAT, datefmt=DEFAULT_DATEFMT)  # tarea 276
    origen = _FiltroOrigen(origen_del_proceso())  # tarea 288

    handlers: list[logging.Handler] = []

    if log_file is not None:
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=MAX_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler.addFilter(origen)
            file_handler.setLevel(level)
            handlers.append(file_handler)
        except Exception as e:  # pragma: no cover — disk-full / perm
            print(f"[logging] file handler failed: {e}", file=sys.stderr)

    stream_handler = logging.StreamHandler(stream=sys.stderr)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(origen)
    stream_handler.setLevel(level)
    handlers.append(stream_handler)

    root = logging.getLogger()
    root.setLevel(level)
    # Replace any pre-existing handlers (e.g. installed by libraries on import).
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in handlers:
        root.addHandler(h)

    # Quiet noisy libraries by default.
    # Un filtro COMPARTIDO: así el conteo es por mensaje y no por librería, y dos
    # libs que emitan la misma línea no se cuentan por separado.
    repetidos = _RepeatFilter()
    for name in NOISY_LIBS:
        lg = logging.getLogger(name)
        lg.setLevel(logging.WARNING)
        # Nivel y filtro son cosas distintas y hacen falta las dos: el nivel no
        # alcanza para esto porque el ruido medido venía en **ERROR**, que está
        # por encima de WARNING y pasa igual (tarea 85).
        lg.addFilter(repetidos)

    # Apply user-configured per-module overrides if available.
    try:
        from config.settings_manager import settings  # local import — avoid cycles

        overrides = settings.get("logging_levels") or {}
        if isinstance(overrides, dict):
            for name, lvl in overrides.items():
                if isinstance(lvl, str):
                    parsed = getattr(logging, lvl.upper(), None)
                    if isinstance(parsed, int):
                        logging.getLogger(name).setLevel(parsed)
                elif isinstance(lvl, int):
                    logging.getLogger(name).setLevel(lvl)
    except Exception:
        pass

    _INITIALIZED = True
    logging.getLogger(__name__).debug("logging initialized → %s", log_file)


def get_logger(name: str) -> logging.Logger:
    """
    Return a module-scoped logger. Lazily ensures ``setup_logging`` has run so
    early imports (e.g. database.models loaded by tests) still get a working
    logger even before ``main()`` calls ``setup_logging`` explicitly.
    """
    if not _INITIALIZED:
        setup_logging()
    return logging.getLogger(name)
