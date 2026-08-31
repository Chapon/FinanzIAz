"""Backoff exponencial + probe canario del breaker de throttle de Yahoo (NET1).

Incidente 2026-07-09: cooldown fijo de 90s → al expirar cada ventana se lanzaba
el batch completo (128 tickers) contra un Yahoo que rate-limiteaba, ~40-60
intentos/hora que prolongaban el throttle. NET1: cooldown exponencial (90s→30min)
+ probe de 1 ticker al expirar antes de liberar el batch + WARNING solo en
transiciones. Reloj mockeado (`time.monotonic`) para no depender de sleeps.
"""

from __future__ import annotations

import logging
import threading

from data import yahoo_finance as yfm


class _Clock:
    """Reloj monótono controlable (reemplaza time.monotonic en el test)."""

    def __init__(self, t0: float = 1000.0) -> None:
        self.t = t0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _patch_clock(monkeypatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(yfm.time, "monotonic", clock)
    yfm.reset_throttle()
    return clock


# ── Backoff exponencial + de-bounce ───────────────────────────────────────────


def test_cooldown_escalates_exponentially_and_caps(monkeypatch):
    clock = _patch_clock(monkeypatch)

    yfm._note_throttle()  # nivel 1 → 90s
    assert yfm.throttle_state()["level"] == 1
    assert abs(yfm.throttle_state()["cooldown_remaining"] - 90.0) < 1e-6

    # Dentro de la ventana, más fallos NO re-escalan (de-bounce).
    yfm._note_throttle()
    assert yfm.throttle_state()["level"] == 1

    clock.advance(91)
    yfm._note_throttle()  # nivel 2 → 270s
    assert yfm.throttle_state()["level"] == 2
    assert abs(yfm.throttle_state()["cooldown_remaining"] - 270.0) < 1e-6

    clock.advance(271)
    yfm._note_throttle()  # nivel 3 → 810s
    assert abs(yfm.throttle_state()["cooldown_remaining"] - 810.0) < 1e-6

    clock.advance(811)
    yfm._note_throttle()  # nivel 4 → 2430s capeado en 1800
    assert abs(yfm.throttle_state()["cooldown_remaining"] - 1800.0) < 1e-6

    clock.advance(1801)
    yfm._note_throttle()  # nivel 5 → sigue capeado en 1800
    assert yfm.throttle_state()["level"] == 5
    assert abs(yfm.throttle_state()["cooldown_remaining"] - 1800.0) < 1e-6


def test_fetch_success_resets_breaker(monkeypatch):
    _patch_clock(monkeypatch)
    yfm._note_throttle()
    assert yfm.throttle_state()["open"]
    yfm._note_fetch_success()
    st = yfm.throttle_state()
    assert not st["open"] and st["level"] == 0


# ── Gate del probe canario ────────────────────────────────────────────────────


def test_gate_level0_allows_without_probe(monkeypatch):
    _patch_clock(monkeypatch)
    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        return True

    assert yfm._should_attempt_fetch(probe) is True
    assert calls["n"] == 0  # a nivel 0 no se sondea


def test_gate_cooldown_active_failfast_no_probe(monkeypatch):
    _clock = _patch_clock(monkeypatch)
    yfm._note_throttle()  # cooldown vigente
    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        return True

    assert yfm._should_attempt_fetch(probe) is False
    assert calls["n"] == 0  # cooldown vigente → fail-fast sin sondeo


def test_gate_probe_ok_closes_and_allows(monkeypatch):
    clock = _patch_clock(monkeypatch)
    yfm._note_throttle()
    clock.advance(91)  # cooldown expirado

    def probe():
        yfm._note_fetch_success()  # como el fetch real: éxito cierra el breaker
        return True

    assert yfm._should_attempt_fetch(probe) is True
    assert yfm.throttle_state()["level"] == 0


def test_gate_probe_fail_escalates_and_blocks(monkeypatch):
    clock = _patch_clock(monkeypatch)
    yfm._note_throttle()  # nivel 1
    clock.advance(91)

    def probe():
        yfm._note_throttle()  # como el fetch real: fallo re-escala
        return False

    assert yfm._should_attempt_fetch(probe) is False
    assert yfm.throttle_state()["level"] == 2


def test_only_one_thread_pays_the_probe(monkeypatch):
    clock = _patch_clock(monkeypatch)
    yfm._note_throttle()
    clock.advance(91)  # cooldown expirado → toca sondear

    probe_calls = {"n": 0}
    started = threading.Event()
    release = threading.Event()

    def probe():
        probe_calls["n"] += 1
        started.set()
        release.wait(2)  # bloquea mientras llegan los demás threads
        return False  # no resetea → los otros siguen viendo el breaker abierto

    results: list[bool] = []

    def worker():
        results.append(yfm._should_attempt_fetch(probe))

    prober = threading.Thread(target=worker)
    prober.start()
    assert started.wait(2)  # el probe arrancó y tiene _throttle_probing=True

    others = [threading.Thread(target=worker) for _ in range(4)]
    for t in others:
        t.start()
    for t in others:
        t.join(2)

    release.set()
    prober.join(2)

    assert probe_calls["n"] == 1  # solo UN thread pagó el probe
    assert results.count(False) == 5  # los otros 4 hicieron fail-fast + el prober


# ── Higiene de log: WARNING solo en transiciones ──────────────────────────────


def test_warning_only_on_transitions(monkeypatch, caplog):
    clock = _patch_clock(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="data.yahoo_finance"):
        yfm._note_throttle()  # apertura → WARNING
        yfm._note_throttle()  # de-bounce → sin WARNING
        clock.advance(91)
        yfm._note_throttle()  # escalada → WARNING
        yfm._note_fetch_success()  # recuperación → WARNING
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 3  # apertura + escalada + cierre


def test_throttle_state_snapshot(monkeypatch):
    _patch_clock(monkeypatch)
    st = yfm.throttle_state()
    assert st == {"open": False, "level": 0, "cooldown_remaining": 0.0, "incident_seconds": 0.0}
    yfm._note_throttle()
    st = yfm.throttle_state()
    assert st["open"] and st["level"] == 1
    assert abs(st["cooldown_remaining"] - 90.0) < 1e-6


# ── Integración: el batch no toca la red bajo throttle ────────────────────────


def test_bulk_prices_gate_skips_network_when_throttled(test_db, monkeypatch):
    _clock = _patch_clock(monkeypatch)
    yfm._note_throttle()  # cooldown vigente → gate debe fail-fast

    calls = {"n": 0}

    def _spy(ticker, **kw):
        calls["n"] += 1
        return None

    monkeypatch.setattr(yfm, "_fetch_ticker_info", _spy)
    out = yfm.get_bulk_prices(["JPM", "LOW", "KLAC"])

    assert calls["n"] == 0  # ni el batch ni el probe tocaron la red
    assert all(out.get(t) is None for t in ["JPM", "LOW", "KLAC"])


# ── Kill-criteria: simulacro del incidente de 2h ──────────────────────────────


def test_incident_simulation_2h_throttle(test_db, monkeypatch, caplog):
    """Throttle sostenido de 2h con timers de 60s: sin el gate serían ~360 fetches
    y ~120 WARNINGs (uno por check); con NET1, un puñado. Y al recuperarse Yahoo,
    el breaker cierra dentro de una ventana de cooldown."""
    clock = _patch_clock(monkeypatch)
    universe = ["AAA", "BBB", "CCC"]
    yahoo_up = {"v": False}
    net_calls = {"n": 0}

    def _fake_fetch(ticker, **kw):
        net_calls["n"] += 1
        if yahoo_up["v"]:
            yfm._note_fetch_success()  # como el fetch real: éxito cierra el breaker
            return {"ticker": ticker.upper(), "price": 100.0}
        yfm._note_throttle()  # como el timeout real: escala el breaker
        return None

    monkeypatch.setattr(yfm, "_fetch_ticker_info", _fake_fetch)

    with caplog.at_level(logging.WARNING, logger="data.yahoo_finance"):
        for _ in range(120):  # 2h de checks cada 60s con Yahoo caído
            yfm.get_bulk_prices(universe)
            clock.advance(60)
        # Yahoo se recupera; avanzar más allá del cooldown vigente para permitir el probe.
        yahoo_up["v"] = True
        clock.advance(yfm.throttle_state()["cooldown_remaining"] + 1)
        out = yfm.get_bulk_prices(universe)

    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    # Reducción drástica vs el naive de ~360 fetches / ~120 WARNINGs.
    assert net_calls["n"] < 30, net_calls["n"]
    assert len(warns) <= 12, len(warns)
    # Recuperación detectada dentro de una ventana: breaker cerrado + batch con datos.
    assert yfm.throttle_state()["level"] == 0
    assert out.get("AAA") is not None
