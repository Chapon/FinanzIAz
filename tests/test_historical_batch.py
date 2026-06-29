"""Tests for ``get_historical_data_batch`` — descarga OHLCV por lotes.

El objetivo del batch es reducir los 401 "Invalid Crumb" de Yahoo agrupando los
cache-misses en una sola llamada ``yf.download`` que reutiliza un único crumb.
Estos tests verifican que esa agrupación NO cambia la calidad de los datos:
mismo split del MultiIndex, misma QA por ticker, mismo registro de fallos
individual, y que los cache hits no entran al lote.

Todo offline: ``yf.download`` se mockea, igual que el cache y la QA.
"""

from __future__ import annotations

import pandas as pd
import pytest

from data import yahoo_finance as yf_mod


# ── fixtures: aislar de red, cache, QA y limiter ────────────────────────────


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """No tocar rate limiter, sleeps, el record de fallos reales NI LA CACHE REAL.

    CRÍTICO: ``get_historical_data_batch`` escribe a la cache vía
    ``_finalize_historical`` → ``_write_historical_cache``, que pega a la
    ``finanzias.db`` real (estos tests no usan el fixture ``test_db``). Sin
    mockear la escritura, correr la suite **corrompe** el cache de producción
    con los frames sintéticos de ``_ohlcv`` (rampa 100→104, 2026-01-01..05).
    Pasó: rompió AAPL/MSFT 1y en la pestaña Análisis (2026-06-25).
    """
    monkeypatch.setattr(yf_mod, "_acquire_rate_token", lambda *_a, **_k: None)
    monkeypatch.setattr(yf_mod.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(yf_mod, "_write_historical_cache", lambda *_a, **_k: None)
    recorded = {"fail": [], "success": [], "transient": []}
    monkeypatch.setattr(
        yf_mod, "record_failure",
        lambda t, *a, **k: recorded["fail"].append(t.upper()),
    )
    monkeypatch.setattr(
        yf_mod, "record_success",
        lambda t, *a, **k: recorded["success"].append(t.upper()),
    )
    monkeypatch.setattr(
        yf_mod, "record_transient",
        lambda t, *a, **k: recorded["transient"].append(t.upper()),
    )
    return recorded


@pytest.fixture(autouse=True)
def _passthrough_qa(monkeypatch):
    """clean_ohlcv: passthrough usable salvo frame vacío/all-NaN."""

    class _Report:
        def __init__(self, usable):
            self._usable = usable

        @property
        def is_usable(self):
            return self._usable

        def has_issues(self):
            return False

        def summary(self):
            return "ok" if self._usable else "all-NaN"

    def _fake_clean(df, **_kw):
        usable = df is not None and not df.empty and not df.isna().all().all()
        return (df if usable else None), _Report(usable)

    monkeypatch.setattr(yf_mod, "clean_ohlcv", _fake_clean)


def _ohlcv(n=5, base=100.0):
    """Frame OHLCV mínimo y válido de ``n`` filas."""
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "Open": [base + i for i in range(n)],
            "High": [base + i + 1 for i in range(n)],
            "Low": [base + i - 1 for i in range(n)],
            "Close": [base + i + 0.5 for i in range(n)],
            "Volume": [1_000_000 + i for i in range(n)],
        },
        index=idx,
    )


def _multiindex_batch(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Replica el shape de yf.download(group_by='ticker') con varios símbolos:
    columnas MultiIndex (ticker, field) en un índice de fechas común."""
    return pd.concat(frames, axis=1)


# ── cache hits no entran al lote ─────────────────────────────────────────────


def test_cache_hits_skip_download(monkeypatch):
    cached = _ohlcv()
    monkeypatch.setattr(
        yf_mod, "_read_historical_cache",
        lambda t, p, i: cached if t == "AAPL" else None,
    )
    calls = {"chunks": []}

    def _fake_download(chunk, period, interval):
        calls["chunks"].append(list(chunk))
        return _multiindex_batch({t: _ohlcv() for t in chunk})

    monkeypatch.setattr(yf_mod, "_download_batch", _fake_download)

    out = yf_mod.get_historical_data_batch(["AAPL", "MSFT"], period="1y")

    # AAPL salió del cache; sólo MSFT se descargó.
    assert calls["chunks"] == [["MSFT"]]
    assert out["AAPL"] is cached
    assert out["MSFT"] is not None


# ── split correcto del MultiIndex ────────────────────────────────────────────


def test_multiindex_split_per_ticker(monkeypatch):
    monkeypatch.setattr(yf_mod, "_read_historical_cache", lambda *a: None)
    frames = {"AAPL": _ohlcv(base=100), "MSFT": _ohlcv(base=200)}
    monkeypatch.setattr(
        yf_mod, "_download_batch",
        lambda chunk, p, i: _multiindex_batch(frames),
    )

    out = yf_mod.get_historical_data_batch(["AAPL", "MSFT"])

    assert set(out) == {"AAPL", "MSFT"}
    # Cada ticker recibe su propio OHLCV, no mezclado.
    assert out["AAPL"]["Close"].iloc[0] == pytest.approx(100.5)
    assert out["MSFT"]["Close"].iloc[0] == pytest.approx(200.5)
    assert list(out["AAPL"].columns) == ["Open", "High", "Low", "Close", "Volume"]


# ── fallo parcial: un ticker all-NaN dentro del lote ─────────────────────────


def test_partial_failure_isolated(monkeypatch, _isolate):
    monkeypatch.setattr(yf_mod, "_read_historical_cache", lambda *a: None)
    good = _ohlcv()
    # símbolo deslistado → Yahoo rellena con NaN (float para evitar el cast int64)
    nan_frame = _ohlcv().astype("float64")
    nan_frame[:] = float("nan")
    monkeypatch.setattr(
        yf_mod, "_download_batch",
        lambda chunk, p, i: _multiindex_batch({"AAPL": good, "ZZZZ": nan_frame}),
    )

    out = yf_mod.get_historical_data_batch(["AAPL", "ZZZZ"])

    assert out["AAPL"] is not None
    assert out["ZZZZ"] is None
    # El fallo se registra sólo para el símbolo malo, sin tumbar al bueno.
    assert "ZZZZ" in _isolate["fail"]
    assert "AAPL" in _isolate["success"]
    assert "AAPL" not in _isolate["fail"]


# ── caso single-miss: columnas planas ────────────────────────────────────────


def test_single_miss_flat_columns(monkeypatch):
    monkeypatch.setattr(yf_mod, "_read_historical_cache", lambda *a: None)
    # Un solo símbolo → yf.download devuelve columnas planas (sin nivel ticker).
    monkeypatch.setattr(
        yf_mod, "_download_batch",
        lambda chunk, p, i: _ohlcv(base=50),
    )

    out = yf_mod.get_historical_data_batch(["AAPL"])

    assert out["AAPL"] is not None
    assert out["AAPL"]["Close"].iloc[0] == pytest.approx(50.5)


# ── chunking: respeta batch_size ─────────────────────────────────────────────


def test_chunking_respects_batch_size(monkeypatch):
    monkeypatch.setattr(yf_mod, "_read_historical_cache", lambda *a: None)
    seen = {"chunks": []}

    def _fake_download(chunk, period, interval):
        seen["chunks"].append(list(chunk))
        return _multiindex_batch({t: _ohlcv() for t in chunk})

    monkeypatch.setattr(yf_mod, "_download_batch", _fake_download)

    tickers = ["A", "B", "C", "D", "E"]
    out = yf_mod.get_historical_data_batch(tickers, batch_size=2)

    assert seen["chunks"] == [["A", "B"], ["C", "D"], ["E"]]
    assert set(out) == set(tickers)


# ── de-dup y normalización a mayúsculas ──────────────────────────────────────


def test_dedup_and_uppercase(monkeypatch):
    monkeypatch.setattr(yf_mod, "_read_historical_cache", lambda *a: None)
    seen = {"chunks": []}

    def _fake_download(chunk, period, interval):
        seen["chunks"].append(list(chunk))
        return _multiindex_batch({t: _ohlcv() for t in chunk})

    monkeypatch.setattr(yf_mod, "_download_batch", _fake_download)

    out = yf_mod.get_historical_data_batch(["aapl", "AAPL", "msft"])

    # "aapl"/"AAPL" colapsan a un solo símbolo en mayúsculas.
    assert seen["chunks"] == [["AAPL", "MSFT"]]
    assert set(out) == {"AAPL", "MSFT"}


# ── batch nulo (toda la descarga falló) ──────────────────────────────────────


def test_whole_batch_none_marks_transient_not_failing(monkeypatch, _isolate):
    """B3: un lote ENTERO vacío = throttle/timeout de Yahoo, no N delistings.

    No se envenena el failing set (large-caps reales seguirían excluidos del
    universo): se marca TRANSITORIO y se abre el circuit-breaker para frenar la
    cascada de hard-timeouts del resto del scan.
    """
    yf_mod.reset_throttle()
    monkeypatch.setattr(yf_mod, "_read_historical_cache", lambda *a: None)
    monkeypatch.setattr(yf_mod, "_download_batch", lambda chunk, p, i: None)

    out = yf_mod.get_historical_data_batch(["AAPL", "MSFT"])

    assert out["AAPL"] is None and out["MSFT"] is None
    assert _isolate["fail"] == []  # NINGUNO marcado como permanentemente fallido
    assert set(_isolate["transient"]) == {"AAPL", "MSFT"}
    assert yf_mod._is_throttled()  # breaker abierto → el resto del scan falla rápido
