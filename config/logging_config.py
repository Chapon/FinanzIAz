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


def setup_logging(level: int = DEFAULT_LEVEL, *, log_file: Path | None = None) -> None:
    """
    Initialize the root logger. Idempotent — safe to call multiple times.
    Should be invoked exactly once from ``main.py`` before any logger is used.
    """
    global _INITIALIZED
    if _INITIALIZED:
        return

    log_file = log_file or LOG_FILE
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
    for name in NOISY_LIBS:
        logging.getLogger(name).setLevel(logging.WARNING)

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
