"""
Tests for ``ui.validators``.

We avoid spinning up a QApplication where possible by exercising the pure
helpers (``is_valid_ticker``, ``parse_decimal_locale``). The QValidator
subclasses are smoke-tested only — full Qt integration tests live in the
pytest-qt fixtures (out of scope for this initial suite).
"""

from __future__ import annotations

import pytest

from ui.validators import is_valid_ticker, parse_decimal_locale


@pytest.mark.parametrize(
    "ticker",
    [
        "AAPL",
        "MSFT",
        "BRK-B",
        "GGAL.BA",
        "BTC-USD",
        "^GSPC",
        "TSLA",
    ],
)
def test_valid_tickers(ticker):
    assert is_valid_ticker(ticker)


@pytest.mark.parametrize(
    "ticker",
    [
        "",
        "AAPL!",  # invalid char
        "TICKERTOOLONG12345678901",  # > 20 chars
        "with space",
        "AAPL/X",  # slash not allowed
    ],
)
def test_invalid_tickers(ticker):
    assert not is_valid_ticker(ticker)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("123", 123.0),
        ("123.45", 123.45),
        ("123,45", 123.45),  # Spanish decimal
        ("1,234.56", 1234.56),  # English thousands
        ("1.234,56", 1234.56),  # Spanish thousands
        (" 99.5 ", 99.5),  # whitespace tolerated
        ("0", 0.0),
    ],
)
def test_parse_decimal_locale_accepts(text, expected):
    assert parse_decimal_locale(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "   ", "abc", None])
def test_parse_decimal_locale_rejects(text):
    with pytest.raises(ValueError):
        parse_decimal_locale(text)
