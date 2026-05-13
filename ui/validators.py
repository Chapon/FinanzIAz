"""
Reusable QValidator subclasses + small validation helpers for FinanzIAs.

Why a separate module?
----------------------
Throughout the codebase, dialogs accept tickers, share quantities, prices,
commissions, dates, and percentages. Without validators the user can type
``-1.5 shares`` or ``$abc`` and the app catches the error very late (or
silently writes garbage to the DB). Centralizing validation here means
every form can opt-in with a one-liner:

    self.qty_input.setValidator(PositiveDecimalValidator(decimals=4))
    self.ticker_input.setValidator(TickerValidator())

…and we get one consistent acceptance criterion across the whole UI.

Validators included
-------------------
``TickerValidator``           — uppercase letters, digits, ``.`` and ``-``,
                                 length 1-20.
``PositiveDecimalValidator``  — ``>= 0`` decimal with configurable precision.
``PercentValidator``          — 0–100 inclusive (or 0–1 for fractions).
``HHMMValidator``             — 5-char ``HH:MM`` time-of-day.
``parse_decimal_locale``      — accepts both ``1,234.56`` and ``1.234,56``.
"""

from __future__ import annotations

import re

from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator, QValidator

# ── TickerValidator ──────────────────────────────────────────────────────────

# Accepts: A-Z, 0-9, ".", "-". Lower case is auto-uppercased on commit.
# Examples accepted: AAPL, BRK-B, GGAL.BA, ^GSPC, BTC-USD
_TICKER_RE = QRegularExpression(r"^[A-Za-z0-9.\-^]{1,20}$")


class TickerValidator(QRegularExpressionValidator):
    """
    QValidator that restricts input to a plausible Yahoo-Finance ticker.
    Pair with ``QLineEdit.editingFinished → text.upper()`` to normalize.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(_TICKER_RE, parent)


def is_valid_ticker(s: str) -> bool:
    """Boolean form of TickerValidator — handy for non-widget call sites."""
    if not s:
        return False
    return bool(_TICKER_RE.match(s.strip().upper()).hasMatch())


# ── Numeric validators ───────────────────────────────────────────────────────


class PositiveDecimalValidator(QValidator):
    """
    Accept non-negative decimals with up to ``decimals`` fractional digits.

    Accepts both ``.`` and ``,`` as the decimal separator (resolved at
    parse time via ``parse_decimal_locale``). Empty input is treated as
    *Intermediate* so the user can clear & retype without the field going
    red mid-edit.
    """

    def __init__(self, decimals: int = 4, *, max_value: float | None = None, parent=None) -> None:
        super().__init__(parent)
        self.decimals = decimals
        self.max_value = max_value

    def validate(self, input_str: str, pos: int):  # type: ignore[override]
        if input_str == "" or input_str in {"-", "."}:
            return QValidator.State.Intermediate, input_str, pos

        # Single decimal separator only
        if input_str.count(".") + input_str.count(",") > 1:
            return QValidator.State.Invalid, input_str, pos

        # Allowed alphabet: digits + one separator
        if not re.fullmatch(r"\d*[.,]?\d*", input_str):
            return QValidator.State.Invalid, input_str, pos

        # Limit decimal precision
        if "," in input_str or "." in input_str:
            sep_idx = max(input_str.find("."), input_str.find(","))
            tail = input_str[sep_idx + 1 :]
            if len(tail) > self.decimals:
                return QValidator.State.Invalid, input_str, pos

        # Range check (best effort — Intermediate during partial edits)
        try:
            val = parse_decimal_locale(input_str)
        except ValueError:
            return QValidator.State.Intermediate, input_str, pos
        if val < 0:
            return QValidator.State.Invalid, input_str, pos
        if self.max_value is not None and val > self.max_value:
            return QValidator.State.Invalid, input_str, pos
        return QValidator.State.Acceptable, input_str, pos


class PercentValidator(PositiveDecimalValidator):
    """
    Decimal in ``[0, 100]`` (or ``[0, 1]`` if ``fractional=True``).

    Useful for commission/slippage fields. Pair with a small label that
    states the unit to avoid the classic 0.5%-vs-0.005-confusion bug.
    """

    def __init__(self, *, fractional: bool = False, decimals: int = 4, parent=None) -> None:
        super().__init__(
            decimals=decimals,
            max_value=1.0 if fractional else 100.0,
            parent=parent,
        )


# ── HHMM validator (US/Eastern time-of-day) ──────────────────────────────────

_HHMM_RE = QRegularExpression(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class HHMMValidator(QRegularExpressionValidator):
    """5-char ``HH:MM`` (00:00 - 23:59) — used for the daily-scan time setting."""

    def __init__(self, parent=None) -> None:
        super().__init__(_HHMM_RE, parent)


# ── Helpers ──────────────────────────────────────────────────────────────────


def parse_decimal_locale(text: str) -> float:
    """
    Parse a decimal string accepting both English (``1,234.56``) and Spanish
    (``1.234,56``) conventions. Raises ``ValueError`` on failure.

    Heuristic:
    - If both ``.`` and ``,`` are present, the *last* one is treated as the
      decimal separator and the other as a thousand separator.
    - If only one is present, it's the decimal separator.
    """
    if text is None:
        raise ValueError("empty input")
    s = text.strip().replace(" ", "")
    if not s:
        raise ValueError("empty input")

    has_dot = "." in s
    has_comma = "," in s
    if has_dot and has_comma:
        if s.rfind(",") > s.rfind("."):
            # Spanish: thousands ".", decimal ","
            s = s.replace(".", "").replace(",", ".")
        else:
            # English with thousands ","
            s = s.replace(",", "")
    elif has_comma and not has_dot:
        s = s.replace(",", ".")
    return float(s)
