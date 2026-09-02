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
import sys
from pathlib import Path

# ── File location ────────────────────────────────────────────────────────────
LOG_DIR = Path.home() / ".finanzias"
LOG_FILE = LOG_DIR / "finanzias.log"

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_LEVEL = logging.INFO
DEFAULT_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
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


def setup_logging(level: int = DEFAULT_LEVEL, *, log_file: Path | None = None) -> None:
    """
    Initialize the root logger. Idempotent — safe to call multiple times.
    Should be invoked exactly once from ``main.py`` before any logger is used.

    Dónde escribe, por precedencia (tarea 78):

    1. el argumento ``log_file``, si viene;
    2. la variable de entorno ``FINANZIAS_LOG_FILE`` — una ruta, o **vacía para
       no escribir ningún archivo** (sólo consola);
    3. ``~/.finanzias/finanzias.log``.

    El (2) existe porque la **suite escribía en el log de producción**: 551
    líneas por corrida, con tracebacks de `tests/` que se leen como defectos de
    la app. Eso es una fábrica de falsos positivos para cualquier triage que use
    el log como evidencia — y este proyecto lo usa (de ahí salieron las tareas
    18, 19 y 25). ``tests/conftest.py`` la setea vacía.
    """
    global _INITIALIZED
    if _INITIALIZED:
        return

    if log_file is None:
        env = os.environ.get("FINANZIAS_LOG_FILE")
        if env is not None:
            # Vacía = a propósito sin archivo. Es distinto de "no seteada".
            log_file = Path(env) if env.strip() else None
        else:
            log_file = LOG_FILE
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            # ~/.finanzias/ should always be creatable, but if not, fall back to
            # console-only logging instead of crashing the app on startup.
            log_file = None

    formatter = logging.Formatter(DEFAULT_FORMAT, datefmt=DEFAULT_DATEFMT)

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
            file_handler.setLevel(level)
            handlers.append(file_handler)
        except Exception as e:  # pragma: no cover — disk-full / perm
            print(f"[logging] file handler failed: {e}", file=sys.stderr)

    stream_handler = logging.StreamHandler(stream=sys.stderr)
    stream_handler.setFormatter(formatter)
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
