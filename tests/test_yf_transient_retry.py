"""Tests for transient-error classification + retry in ``_run_with_timeout``.

Covers the Yahoo "Invalid Crumb" / 401 failure mode: yfinance raises a 401 or a
bare ``TypeError('argument of type NoneType is not iterable')`` from its crumb
scraper, which should be (a) classified transient, (b) retried with backoff, and
(c) logged as a one-line warning instead of a full traceback.
"""

from __future__ import annotations

import pytest

from data import yahoo_finance as yf_mod
from data.yahoo_finance import _is_transient, _run_with_timeout


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Backoff sleeps would slow the suite — make them instant."""
    monkeypatch.setattr(yf_mod.time, "sleep", lambda *_a, **_k: None)


@pytest.fixture(autouse=True)
def _no_rate_token(monkeypatch):
    """Don't touch the global rate limiter from unit tests."""
    monkeypatch.setattr(yf_mod, "_acquire_rate_token", lambda *_a, **_k: None)


# ── classification ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "exc",
    [
        Exception("HTTP Error 401: Unauthorized"),
        Exception('{"description":"Invalid Crumb"}'),
        Exception("HTTP Error 429: Too Many Requests"),
        TypeError("argument of type 'NoneType' is not iterable"),
    ],
)
def test_transient_errors_classified(exc):
    assert _is_transient(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("bad symbol"),
        KeyError("longName"),
        TypeError("unsupported operand type(s) for +: int and str"),
    ],
)
def test_non_transient_errors_not_classified(exc):
    assert _is_transient(exc) is False


# ── retry behaviour ─────────────────────────────────────────────────────────


def test_transient_error_is_retried_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise Exception("HTTP Error 401: Invalid Crumb")
        return {"ok": True}

    result = _run_with_timeout(flaky, retries=2, retry_backoff=0.0)
    assert result == {"ok": True}
    assert calls["n"] == 3  # 1 initial + 2 retries


def test_transient_error_exhausts_retries_returns_default():
    calls = {"n": 0}

    def always_401():
        calls["n"] += 1
        raise Exception("HTTP Error 401: Unauthorized")

    result = _run_with_timeout(always_401, default="FALLBACK", retries=2, retry_backoff=0.0)
    assert result == "FALLBACK"
    assert calls["n"] == 3  # 1 initial + 2 retries, then gives up


def test_non_transient_error_is_not_retried():
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise ValueError("genuine bug")

    result = _run_with_timeout(boom, default=None, retries=2, retry_backoff=0.0)
    assert result is None
    assert calls["n"] == 1  # no retries for non-transient errors


def test_nonetype_typeerror_is_retried():
    """The yfinance crumb-scraper TypeError must be treated as transient."""
    calls = {"n": 0}

    def crumb_typeerror():
        calls["n"] += 1
        raise TypeError("argument of type 'NoneType' is not iterable")

    result = _run_with_timeout(crumb_typeerror, default="FB", retries=1, retry_backoff=0.0)
    assert result == "FB"
    assert calls["n"] == 2  # 1 initial + 1 retry


def test_success_first_try_no_retry():
    calls = {"n": 0}

    def good():
        calls["n"] += 1
        return 42

    assert _run_with_timeout(good, retries=2, retry_backoff=0.0) == 42
    assert calls["n"] == 1
