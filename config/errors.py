"""
Custom exception hierarchy for FinanzIAs.

The standard library exceptions (`Exception`, `ValueError`, `RuntimeError`)
are too coarse to drive UX decisions on. With this hierarchy, the UI's
``error_handler`` can distinguish between recoverable network blips
(``NetworkError``), user-input validation problems (``ConfigError``,
``ValidationError``), and genuine internal bugs (everything else).

Hierarchy
---------
``FinanzIAsError`` — base class. Every domain-specific error inherits.
    ``DataError``         — anything wrong with market / cached data.
        ``NetworkError``  — timeout, DNS, 5xx, rate-limit on outbound calls.
        ``DataQualityError`` — got a response but it failed quality checks.
    ``StrategyError``     — engine / backtest / scheduler invariant violated.
    ``ConfigError``       — settings.json corrupt or invalid value.
    ``ValidationError``   — user input failed schema/format check.
    ``DatabaseError``     — SQLAlchemy operation failed in a way we recognise.

Usage
-----
    raise NetworkError("Yahoo Finance returned 503") from exc
    raise ValidationError("Ticker must be 1-20 alphanumeric")

The UI's ``show_error`` displays ``str(exc)``; for technical detail (``__cause__``,
traceback) it falls back to the "Show Details…" pane. So friendly messages
go in the constructor — context goes in ``raise … from exc``.
"""

from __future__ import annotations


class FinanzIAsError(Exception):
    """Base class for every FinanzIAs-specific error."""


# ── Data layer ───────────────────────────────────────────────────────────────


class DataError(FinanzIAsError):
    """Anything wrong with market data — fetch, cache, parse, validate."""


class NetworkError(DataError):
    """Outbound network failure: timeout, DNS, 5xx, rate-limited 429, etc."""


class DataQualityError(DataError):
    """Data was retrieved but failed validation (NaN flood, gaps, zeros…)."""


# ── Strategy / engine ────────────────────────────────────────────────────────


class StrategyError(FinanzIAsError):
    """Engine, backtest, or scheduler invariant violation."""


# ── User-facing input ────────────────────────────────────────────────────────


class ConfigError(FinanzIAsError):
    """settings.json is corrupt, missing required keys, or out of range."""


class ValidationError(FinanzIAsError):
    """User-supplied value failed format / range / schema validation."""


# ── Database ─────────────────────────────────────────────────────────────────


class DatabaseError(FinanzIAsError):
    """A SQLAlchemy / SQLite operation failed in a way we can describe.

    Wrap raw ``sqlalchemy.exc.SQLAlchemyError`` in this so the UI can
    present a clean message instead of leaking ORM internals.
    """


__all__ = [
    "ConfigError",
    "DataError",
    "DataQualityError",
    "DatabaseError",
    "FinanzIAsError",
    "NetworkError",
    "StrategyError",
    "ValidationError",
]
