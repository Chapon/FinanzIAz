"""
Tests for the token-bucket rate limiter inside ``data.market_data_service``.
"""

from __future__ import annotations

import time

import pytest

from data.market_data_service import RateLimiter


def test_initial_burst_is_immediate():
    rl = RateLimiter(rate_per_sec=2.0, burst=5)
    start = time.monotonic()
    for _ in range(5):
        rl.acquire(1)
    elapsed = time.monotonic() - start
    # All 5 should pass through the burst capacity without sleeping
    assert elapsed < 0.05


def test_subsequent_calls_are_throttled():
    rl = RateLimiter(rate_per_sec=10.0, burst=2)
    rl.acquire(2)  # exhaust the burst
    start = time.monotonic()
    rl.acquire(2)  # should wait ~0.2 s for refill
    elapsed = time.monotonic() - start
    assert elapsed >= 0.15  # allow some slack on slow CI runners


def test_try_acquire_does_not_block():
    rl = RateLimiter(rate_per_sec=1.0, burst=1)
    assert rl.try_acquire(1) is True
    # Bucket empty — should refuse immediately
    assert rl.try_acquire(1) is False


def test_invalid_rate_rejected():
    with pytest.raises(ValueError):
        RateLimiter(rate_per_sec=0)
    with pytest.raises(ValueError):
        RateLimiter(rate_per_sec=-1)
