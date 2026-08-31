"""SPLITGUARD (tarea 63) — cuando la sospechosa es la REFERENCIA, no el precio.

El guard E5 (`tests/test_price_sanity.py`) toma el cache como verdad. Eso alcanza
para el caso KLAC —cotización corrupta, cache sano— pero no para el simétrico.

El caso que abrió la tarea, AVB 2026-08-27: Yahoo aplicó un split **fantasma** de
2.793 al frame ``2y`` y no al ``10y`` ni a la cotización, así que
``reference_close`` devolvía 68.14 contra un precio real de 184.06. El guard
descartó el precio **bueno** en cada fetch durante 4 días (927 WARNINGs), y como
los dos guards del engine no miran el lado, con posición abierta eso también
habría bloqueado la SELL: el modo de falla no es *no entramos*, es **no podemos
salir**.

De ahí los dos invariantes que estos tests fijan:

1. **Con la referencia en duda, el guard no bloquea** — pero sigue bloqueando
   cuando la referencia es coherente, que es para lo que E5 existe.
2. **Salir sí, entrar no.** Que la cotización sea creíble no alcanza para abrir:
   el ATR y las barreras salen del *mismo* histórico en duda, así que la posición
   entraría con un stop calculado en otra escala. Entrar es opcional; salir no.
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from data import yahoo_finance as yfm

# ── Helpers ───────────────────────────────────────────────────────────────────


def _seed(ticker: str, closes: list[tuple[str, float]], period: str) -> None:
    """Frame ``1d`` cacheado para ``(ticker, period)``."""
    from database.models import HistoricalDataCache, session_scope

    idx = pd.to_datetime([d for d, _ in closes])
    df = pd.DataFrame(
        {
            "Open": [c for _, c in closes],
            "High": [c for _, c in closes],
            "Low": [c for _, c in closes],
            "Close": [c for _, c in closes],
            "Volume": [1_000_000.0] * len(closes),
        },
        index=idx,
    )
    with session_scope() as s:
        s.add(
            HistoricalDataCache(
                ticker=ticker.upper(),
                period=period,
                interval="1d",
                data_json=df.to_json(orient="split", date_format="iso"),
            )
        )


def _info(ticker: str, price: float) -> dict:
    return {"ticker": ticker.upper(), "price": price, "change_pct": None, "volume": None, "market_cap": None}


@pytest.fixture(autouse=True)
def _clean_module_state():
    """La racha y el memo de splits son estado de módulo: no cruzarlos entre tests."""
    yfm._out_of_band_streak.clear()
    yfm._split_factor_cache.clear()
    yield
    yfm._out_of_band_streak.clear()
    yfm._split_factor_cache.clear()


def _splits(factor: float | None):
    """Stub de ``recent_split_factor`` que **respeta ``allow_network``**.

    Es la parte que hay que imitar bien: sin red el lookup sólo puede responder
    con lo memoizado, y de ese gating depende que un rechazo aislado se siga
    bloqueando como siempre.
    """

    def _inner(ticker, lookback_days=yfm._SPLIT_LOOKBACK_DAYS, allow_network=True):
        return factor if allow_network else None

    return _inner


@pytest.fixture
def no_split(monkeypatch):
    """El proveedor no reporta ningún split (y NO se toca la red)."""
    monkeypatch.setattr(yfm, "recent_split_factor", _splits(None))


# ── El ratio: qué es un split de verdad y qué es dato podrido ─────────────────


@pytest.mark.parametrize("factor", [2.0, 3.0, 4.0, 1.5, 2.5, 0.5, 0.1, 1 / 3])
def test_a_simple_fraction_is_a_real_split(factor):
    assert yfm.is_plausible_split(factor) is True


@pytest.mark.parametrize("factor", [2.793, 1.137, 7.31])
def test_a_fractional_ratio_is_not_a_split_it_is_rotten_data(factor):
    # El 2.793 que Yahoo reportó para AVB. Ninguna empresa parte así.
    assert yfm.is_plausible_split(factor) is False


def test_a_missing_or_absurd_factor_is_not_a_split():
    assert yfm.is_plausible_split(None) is False
    assert yfm.is_plausible_split(0.0) is False
    assert yfm.is_plausible_split(-2.0) is False
    assert yfm.is_plausible_split(float("inf")) is False


# ── ¿El split explica el desvío? ──────────────────────────────────────────────


def test_a_split_explains_the_deviation_in_both_directions():
    # Post-split la cotización vale 1/2 del close cacheado, o al revés.
    assert yfm.split_explains(100.0, 200.0, 2.0) is True
    assert yfm.split_explains(200.0, 100.0, 2.0) is True


def test_the_match_tolerates_that_the_price_moved_since_the_close():
    # AVB: 184.06 vivo contra un close de 68.14 de hace una semana → 2.70, no 2.793.
    assert yfm.split_explains(184.06, 68.14, 2.793) is True


def test_a_klac_scale_error_is_not_explained_by_a_2_to_1_split():
    # 10× no se parece a un 2:1 → el guard tiene que seguir acusando.
    assert yfm.split_explains(1942.70, 194.0, 2.0) is False


def test_without_a_reported_split_nothing_is_explained():
    assert yfm.split_explains(184.06, 68.14, None) is False


# ── El cruce entre frames: la señal gratis, sin red ───────────────────────────


def test_two_frames_that_disagree_on_the_verdict_are_a_dispute():
    # El caso AVB exacto: el 10y sano y el 2y con el split fantasma aplicado.
    _seed("AVB", [("2026-08-07", 187.55)], period="10y")
    _seed("AVB", [("2026-08-24", 68.14)], period="2y")
    assert yfm.scale_is_disputed(184.06, "AVB") is True


def test_two_frames_that_agree_are_not_a_dispute():
    # Los dos dicen "en banda": no hay nada que arbitrar.
    _seed("AAPL", [("2026-08-07", 200.0)], period="10y")
    _seed("AAPL", [("2026-08-24", 205.0)], period="2y")
    assert yfm.scale_is_disputed(203.0, "AAPL") is False


def test_two_frames_that_both_reject_are_not_a_dispute():
    # Los dos dicen "fuera de banda" → el cache SÍ puede arbitrar, y acusa.
    _seed("KLAC", [("2026-08-07", 194.0)], period="10y")
    _seed("KLAC", [("2026-08-24", 196.0)], period="2y")
    assert yfm.scale_is_disputed(1942.70, "KLAC") is False


def test_a_single_frame_cannot_be_disputed():
    _seed("KLAC", [("2026-08-24", 194.0)], period="2y")
    assert yfm.scale_is_disputed(1942.70, "KLAC") is False


def test_the_dispute_is_by_verdict_not_by_percentage():
    """El drift del re-ajuste por dividendos NO puede disparar una disputa.

    Dos frames del mismo ticker bajados con meses de diferencia difieren unos
    puntos porque el más nuevo tiene los dividendos posteriores back-ajustados.
    Por eso la disputa se define por el *veredicto* y no por un umbral de
    diferencia: un 3% nunca cambia el veredicto, un split sí.
    """
    _seed("PLD", [("2026-08-07", 140.0)], period="10y")
    _seed("PLD", [("2026-08-24", 135.8)], period="2y")  # −3% de re-ajuste
    assert yfm.scale_is_disputed(141.0, "PLD") is False


# ── El guard completo ─────────────────────────────────────────────────────────


def test_the_avb_case_the_good_price_is_no_longer_discarded(caplog):
    """El bug que abrió la tarea: el precio bueno se aceptaba nunca."""
    _seed("AVB", [("2026-08-07", 187.55)], period="10y")
    _seed("AVB", [("2026-08-24", 68.14)], period="2y")

    with caplog.at_level(logging.ERROR, logger="data.yahoo_finance"):
        out = yfm._reject_if_out_of_band("AVB", _info("AVB", 184.06))

    assert out is not None and out["price"] == pytest.approx(184.06)
    assert any("NO confiable" in r.message for r in caplog.records)


def test_klac_is_still_blocked(no_split, caplog):
    """El caso para el que E5 existe no se afloja: un solo frame coherente acusa."""
    _seed("KLAC", [("2026-05-29", 194.0)], period="2y")

    with caplog.at_level(logging.WARNING, logger="data.yahoo_finance"):
        out = yfm._reject_if_out_of_band("KLAC", _info("KLAC", 1942.70))

    assert out is None
    assert any("fuera de banda" in r.message for r in caplog.records)


def test_a_transient_rejection_does_not_touch_the_network(monkeypatch):
    """Un rechazo aislado es la corrupción pasajera que E5 espera: no se investiga.

    Sin esto, cada precio corrupto costaría una llamada de red **por scan** — y el
    guard corre en cada fetch de cada ticker.
    """
    _seed("KLAC", [("2026-05-29", 194.0)], period="2y")

    def _boom(fn, **kw):
        raise AssertionError("el primer rechazo no debe pegar a la red")

    monkeypatch.setattr(yfm, "_run_with_timeout", _boom)
    assert yfm._reject_if_out_of_band("KLAC", _info("KLAC", 1942.70)) is None


def test_the_network_lookup_waits_until_the_streak_proves_persistence(monkeypatch):
    _seed("KLAC", [("2026-05-29", 194.0)], period="2y")
    calls: list[int] = []

    def _count(fn, **kw):
        calls.append(1)
        return None

    monkeypatch.setattr(yfm, "_run_with_timeout", _count)
    for _ in range(yfm._ESCALATE_AFTER - 1):
        yfm._reject_if_out_of_band("KLAC", _info("KLAC", 1942.70))
    assert calls == []

    yfm._reject_if_out_of_band("KLAC", _info("KLAC", 1942.70))
    assert len(calls) == 1


def test_a_real_split_unblocks_and_invalidates_the_stale_cache(monkeypatch):
    """Un split REAL deja el cache viejo, no podrido → se invalida y se rebaja."""
    _seed("SPLIT", [("2026-08-24", 300.0)], period="2y")
    monkeypatch.setattr(yfm, "recent_split_factor", _splits(3.0))

    out = None
    for _ in range(yfm._ESCALATE_AFTER):
        out = yfm._reject_if_out_of_band("SPLIT", _info("SPLIT", 100.0))

    assert out is not None and out["price"] == pytest.approx(100.0)
    assert yfm.reference_close("SPLIT") is None  # el cache quedó invalidado


def test_a_phantom_split_unblocks_but_does_NOT_invalidate_the_cache(monkeypatch):
    """Con un ratio que no es un split, invalidar sólo re-bajaría la misma basura."""
    _seed("AVB", [("2026-08-24", 68.14)], period="2y")
    monkeypatch.setattr(yfm, "recent_split_factor", _splits(2.793))

    out = None
    for _ in range(yfm._ESCALATE_AFTER):
        out = yfm._reject_if_out_of_band("AVB", _info("AVB", 184.06))

    assert out is not None and out["price"] == pytest.approx(184.06)
    assert yfm.reference_close("AVB") == pytest.approx(68.14)  # intacto


def test_the_streak_escalates_to_error_instead_of_repeating_the_warning(no_split, caplog):
    """927 WARNINGs idénticos no distinguen «pasó una vez» de «hace 4 días»."""
    _seed("KLAC", [("2026-05-29", 194.0)], period="2y")

    with caplog.at_level(logging.DEBUG, logger="data.yahoo_finance"):
        for _ in range(6):
            yfm._reject_if_out_of_band("KLAC", _info("KLAC", 1942.70))

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(warnings) == 1, "el WARNING se anuncia una sola vez"
    assert len(errors) == 1, "y la racha escala a ERROR una sola vez"
    assert "INVISIBLE" in errors[0].message


def test_a_price_back_in_band_resets_the_streak(no_split):
    _seed("KLAC", [("2026-05-29", 194.0)], period="2y")
    yfm._reject_if_out_of_band("KLAC", _info("KLAC", 1942.70))
    assert "KLAC" in yfm._out_of_band_streak

    assert yfm._reject_if_out_of_band("KLAC", _info("KLAC", 200.0)) is not None
    assert "KLAC" not in yfm._out_of_band_streak


def test_an_unreliable_reference_does_not_reset_the_streak(monkeypatch):
    """Si la limpiara, el ticker oscilaría: bloqueado, bloqueado, aceptado, bloqueado.

    La investigación de la referencia depende de la racha, así que resetearla al
    dejar pasar el precio devolvería el contador a cero y volvería a bloquear.
    """
    # El split fantasma es el caso que dura: el cache NO se invalida, así que el
    # ticker sigue fuera de banda fetch tras fetch.
    _seed("AVB", [("2026-08-24", 68.14)], period="2y")
    monkeypatch.setattr(yfm, "recent_split_factor", _splits(2.793))

    # Los primeros rechazos bloquean (todavía parece transitorio) y suman racha.
    for _ in range(yfm._ESCALATE_AFTER - 1):
        assert yfm._reject_if_out_of_band("AVB", _info("AVB", 184.06)) is None

    # Al llegar al umbral se investiga la referencia y el precio pasa — sin que
    # el contador vuelva a cero, que es lo que evitaría la oscilación.
    for i in range(3):
        assert yfm._reject_if_out_of_band("AVB", _info("AVB", 184.06)) is not None
        assert yfm._out_of_band_streak["AVB"][0] == yfm._ESCALATE_AFTER + i


# ── Los dos guards tienen que decidir IGUAL ──────────────────────────────────
# Que el fetch acepte un precio y el engine lo rechace —con la misma referencia—
# es exactamente cómo una posición queda sin poder venderse: el guard del engine
# no mira el lado, así que bloquea la SELL con la misma facilidad que la BUY.


def test_the_engine_guard_lets_a_sell_out_on_a_disputed_reference():
    """Lo que la tarea existe para arreglar: quedar trapeado es peor que salir."""
    from paper_trading import engine

    _seed("AVB", [("2026-08-07", 187.55)], period="10y")
    _seed("AVB", [("2026-08-24", 68.14)], period="2y")
    assert engine._price_out_of_band("AVB", 184.06, "SELL") is False
    assert engine._price_out_of_band("AVB", 184.06) is False  # lado desconocido


def test_the_engine_guard_still_blocks_a_BUY_on_a_disputed_reference():
    """La asimetría: entrar es opcional, salir no.

    Que la *cotización* sea creíble no alcanza para abrir: el ATR y las barreras
    salen del **mismo** histórico en duda (``paper_history_period`` = ``2y``, que
    en AVB quedó 2.793× fuera de escala), así que la posición entraría con un stop
    calculado en otra escala — casi pegado a la entrada.
    """
    from paper_trading import engine

    _seed("AVB", [("2026-08-07", 187.55)], period="10y")
    _seed("AVB", [("2026-08-24", 68.14)], period="2y")
    assert engine._price_out_of_band("AVB", 184.06, "BUY") is True


def test_the_engine_guard_still_blocks_klac():
    from paper_trading import engine

    _seed("KLAC", [("2026-05-29", 194.0)], period="2y")
    assert engine._price_out_of_band("KLAC", 1942.70) is True
    assert engine._price_out_of_band("KLAC", 200.0) is False


def test_the_two_guards_agree_on_the_scale_verdict(no_split):
    """El invariante de la tarea: mismo ticker, mismo veredicto **de escala**.

    Lo que sigue difiriendo es la *política* (una BUY no entra con la referencia
    en duda), no el juicio sobre el precio — y esa diferencia es deliberada, no
    una contradicción entre dos guards.
    """
    from paper_trading import engine

    _seed("AVB", [("2026-08-07", 187.55)], period="10y")
    _seed("AVB", [("2026-08-24", 68.14)], period="2y")
    _seed("KLAC", [("2026-05-29", 194.0)], period="2y")

    for ticker, price in (("AVB", 184.06), ("KLAC", 1942.70)):
        fetch_acepta = yfm._reject_if_out_of_band(ticker, _info(ticker, price)) is not None
        engine_acepta = not engine._price_out_of_band(ticker, price, "SELL")
        assert fetch_acepta == engine_acepta, ticker


def test_the_engine_guard_never_hits_the_network(monkeypatch):
    """Un fill no puede colgarse esperando el lookup de splits de Yahoo."""
    from paper_trading import engine

    _seed("KLAC", [("2026-05-29", 194.0)], period="2y")

    def _boom(fn, **kw):
        raise AssertionError("el guard del engine no debe pegar a la red")

    monkeypatch.setattr(yfm, "_run_with_timeout", _boom)
    assert engine._price_out_of_band("KLAC", 1942.70, "SELL") is True


def test_the_engine_guard_reuses_what_the_fetch_already_learned(monkeypatch):
    """Sin red, pero sí con el memo: lo que el fetch aprendió le sirve al fill."""
    from paper_trading import engine

    _seed("AVB", [("2026-08-24", 68.14)], period="2y")
    # Un solo frame: no hay cruce posible, así que sin el memo el engine bloquea.
    assert engine._price_out_of_band("AVB", 184.06, "SELL") is True

    monkeypatch.setattr(
        yfm,
        "_run_with_timeout",
        lambda fn, **kw: pd.Series([2.793], index=pd.DatetimeIndex([pd.Timestamp.now(tz="UTC")])),
    )
    yfm.recent_split_factor("AVB")  # el fetch lo consulta y lo memoiza

    assert engine._price_out_of_band("AVB", 184.06, "SELL") is False


# ── El lookup de splits ───────────────────────────────────────────────────────


def test_recent_split_factor_only_counts_the_recent_ones(monkeypatch):
    now = pd.Timestamp.now(tz="UTC")
    series = pd.Series(
        [2.0, 3.0],
        index=pd.DatetimeIndex([now - pd.Timedelta(days=400), now - pd.Timedelta(days=2)]),
    )
    monkeypatch.setattr(yfm, "_run_with_timeout", lambda fn, **kw: series)
    assert yfm.recent_split_factor("X") == pytest.approx(3.0)


def test_recent_split_factor_is_memoized(monkeypatch):
    """El lookup pega a la red: un ticker roto no puede consultarlo una vez por minuto."""
    calls: list[int] = []

    def _fake(fn, **kw):
        calls.append(1)
        return pd.Series([2.0], index=pd.DatetimeIndex([pd.Timestamp.now(tz="UTC")]))

    monkeypatch.setattr(yfm, "_run_with_timeout", _fake)
    assert yfm.recent_split_factor("X") == pytest.approx(2.0)
    assert yfm.recent_split_factor("X") == pytest.approx(2.0)
    assert len(calls) == 1


def test_a_failing_split_lookup_leaves_the_guard_as_it_was(monkeypatch):
    """Fail-safe: sin respuesta del proveedor, el guard se comporta como antes."""

    def _boom(fn, **kw):
        raise RuntimeError("yahoo caido")

    monkeypatch.setattr(yfm, "_run_with_timeout", _boom)
    assert yfm.recent_split_factor("X") is None


# ── El par de ``latest_1d``: todos los frames, no el más fresco ───────────────


def test_all_1d_returns_every_period_newest_first(tmp_path):
    from data import parquet_cache

    parquet_cache.set_parquet_dir(tmp_path)
    try:
        idx = pd.to_datetime(["2026-08-24"])
        old = pd.DataFrame({"Close": [187.55]}, index=idx)
        new = pd.DataFrame({"Close": [68.14]}, index=idx)
        parquet_cache.write(
            "AVB", "10y", "1d", old, fetched_at=pd.Timestamp("2026-08-09", tz="UTC").to_pydatetime()
        )
        parquet_cache.write(
            "AVB", "2y", "1d", new, fetched_at=pd.Timestamp("2026-08-31", tz="UTC").to_pydatetime()
        )

        frames = parquet_cache.all_1d("AVB")
        assert len(frames) == 2
        assert float(frames[0]["Close"].iloc[-1]) == pytest.approx(68.14)
        assert float(frames[1]["Close"].iloc[-1]) == pytest.approx(187.55)
        # Y ``latest_1d`` sigue eligiendo el más fresco, sin cambios.
        assert float(parquet_cache.latest_1d("AVB")["Close"].iloc[-1]) == pytest.approx(68.14)
    finally:
        parquet_cache.set_parquet_dir(None)


def test_all_1d_is_empty_without_cache(tmp_path):
    from data import parquet_cache

    parquet_cache.set_parquet_dir(tmp_path)
    try:
        assert parquet_cache.all_1d("NOPE") == []
    finally:
        parquet_cache.set_parquet_dir(None)
