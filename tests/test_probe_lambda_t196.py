"""Tarea 196 — el probe de Yahoo empaquetado para AWS Lambda (decisión de Chapa 2026-10-01).

Lo que se fija, sin red ni AWS:

1. **GitHub y Lambda miden lo mismo:** ``main`` y ``lambda_handler`` pasan por ``run_probe``.
2. **El handler manda los caches de yfinance a ``/tmp``:** en Lambda es lo único escribible, y
   un cache en otro lado hace fallar el primer pedido de una forma que se lee como bloqueo
   de Yahoo (el mismo tipo de error del instrumento que la corrida 34872679069 tuvo con SEC).
3. **SEC sin User-Agent es «no probado», no «falla».**
4. **El zip lleva la yfinance de ``requirements.lock``,** el probe en la raíz y nada de
   ``__pycache__`` ni ``tests``.
"""

from __future__ import annotations

import zipfile

import pytest

import scripts.build_probe_lambda_t196 as build
import scripts.probe_yahoo_datacenter_t196 as probe


@pytest.fixture
def sin_red(monkeypatch):
    monkeypatch.setattr(probe, "_ip_saliente", lambda: "1.2.3.4")
    monkeypatch.setattr(probe, "_probe_sec", lambda: (None, "NO PROBADO"))
    resultados = {"NVDA": (True, "3 items", True, "4 filas"), "KO": (True, "2 items", False, "VACIO")}
    monkeypatch.setattr(probe, "_probe_yf", lambda tk: resultados[tk])


def test_run_probe_agrega_y_sec_no_probado_no_es_falla(sin_red):
    r = probe.run_probe(["NVDA", "KO"], emit=lambda *_: None)
    assert r["ip"] == "1.2.3.4"
    assert "news 2/2" in r["resumen"] and "estimates 1/2" in r["resumen"]
    assert r["ok"] is False  # un estimate vacío es falla
    r2 = probe.run_probe(["NVDA"], emit=lambda *_: None)
    assert r2["ok"] is True  # SEC «n/d» no lo voltea
    assert r2["sec"] == "n/d"


def test_lambda_handler_usa_tmp_y_los_tickers_del_evento(sin_red, monkeypatch):
    import yfinance as yf

    vistos = []
    monkeypatch.setattr(yf, "set_tz_cache_location", vistos.append)
    r = probe.lambda_handler({"tickers": "nvda, ko"}, None)
    assert vistos == ["/tmp/yf-cache"]
    assert [f["ticker"] for f in r["tickers"]] == ["NVDA", "KO"]


def test_lambda_handler_sin_evento_usa_los_default(monkeypatch):
    import yfinance as yf

    monkeypatch.setattr(yf, "set_tz_cache_location", lambda _d: None)
    vistos = []
    monkeypatch.setattr(probe, "run_probe", lambda tks: vistos.append(tks) or {"resumen": "x"})
    probe.lambda_handler(None, None)
    assert vistos == [probe.DEFAULT_TICKERS]


def test_main_y_handler_comparten_run_probe():
    import inspect

    assert "run_probe(" in inspect.getsource(probe.main)
    assert "run_probe(" in inspect.getsource(probe.lambda_handler)


def test_versiones_desde_el_lock():
    lock = "numpy==2.2.6\ncurl_cffi==0.15.0\nyfinance==1.4.1  # comentario\n"
    assert build.pinned_versions(lock) == {"curl_cffi": "0.15.0", "yfinance": "1.4.1"}
    with pytest.raises(SystemExit):
        build.pinned_versions("numpy==2.2.6\n")


def test_el_lock_real_fija_lo_que_el_zip_necesita():
    v = build.pinned_versions(build.LOCK.read_text(encoding="utf-8"))
    assert set(v) == {"yfinance", "curl_cffi"}


def test_zip_sin_basura_y_con_el_probe_en_la_raiz(tmp_path):
    src = tmp_path / "pkg"
    (src / "yfinance" / "__pycache__").mkdir(parents=True)
    (src / "yfinance" / "__init__.py").write_text("x = 1\n")
    (src / "yfinance" / "__pycache__" / "a.pyc").write_bytes(b"\0")
    (src / "pandas" / "tests").mkdir(parents=True)
    (src / "pandas" / "tests" / "t.py").write_text("")
    (src / "pandas" / "core.py").write_text("")
    out = tmp_path / "out" / "p.zip"
    build.zip_dir(src, out, build.PROBE)
    nombres = zipfile.ZipFile(out).namelist()
    assert "probe_yahoo_datacenter_t196.py" in nombres
    assert "yfinance/__init__.py" in nombres and "pandas/core.py" in nombres
    assert not [n for n in nombres if "__pycache__" in n or "/tests/" in n]
