"""Tarea 397 — una respuesta vacía de Yahoo no borra el perfil de surprise de un ticker que lo tenía.

El 2026-10-26 ACN pasó de n=24 a n=0 por un vacío transitorio de ``get_earnings_dates`` (media hora
después devolvía 25 filas), y el archivo la dejó afuera una semana sin aviso.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from scripts import build_surprise_profiles as b

_ACN = {
    "ticker": "ACN",
    "n_quarters": 24,
    "beat_rate": 0.75,
    "miss_rate": 0.25,
    "mean_surprise": 0.02,
    "median_surprise": 0.02,
    "last_surprise": 0.01,
    "directional_score": 0.3,
}
_VACIO = dict(_ACN, n_quarters=0, beat_rate=0.0, directional_score=0.0)
_AHORA = datetime(2026, 10, 26, 16, 52, tzinfo=timezone.utc)
_ANTES = "2026-10-19T16:50:00+00:00"


def test_un_vacio_conserva_el_perfil_anterior_y_lo_avisa(caplog):
    profiles = {"ACN": dict(_VACIO)}
    with caplog.at_level(logging.WARNING):
        conservados = b.conservar_caidos(
            profiles, {"ACN": _ACN}, _ANTES, _AHORA, reintentar=lambda t: dict(_VACIO)
        )
    assert conservados == ["ACN"]
    assert profiles["ACN"]["n_quarters"] == 24 and profiles["ACN"]["conservado_desde"] == _ANTES
    assert any("ACN" in r.getMessage() and "conserva" in r.getMessage() for r in caplog.records)


def test_si_el_reintento_trae_datos_va_el_reintento():
    nuevo = dict(_ACN, n_quarters=25)
    profiles = {"ACN": dict(_VACIO)}
    assert b.conservar_caidos(profiles, {"ACN": _ACN}, _ANTES, _AHORA, reintentar=lambda t: nuevo) == []
    assert profiles["ACN"]["n_quarters"] == 25 and "conservado_desde" not in profiles["ACN"]


def test_un_ticker_sin_perfil_antes_sigue_yendo_a_insufficient():
    """Un deslistado (o uno nuevo sin historia) no tenía perfil: no hay qué conservar."""
    profiles = {"WBD": dict(_VACIO, ticker="WBD")}
    assert b.conservar_caidos(profiles, {"ACN": _ACN}, _ANTES, _AHORA) == []
    assert profiles["WBD"]["n_quarters"] == 0


def test_no_se_conserva_para_siempre():
    """Conservado desde hace más de MAX_DIAS_CONSERVADO: deja de conservarse (un deslistado)."""
    viejo = dict(_ACN, conservado_desde="2026-09-01T00:00:00+00:00")
    profiles = {"ACN": dict(_VACIO)}
    assert b.conservar_caidos(profiles, {"ACN": viejo}, _ANTES, _AHORA) == []
    assert profiles["ACN"]["n_quarters"] == 0


def test_run_build_con_el_archivo_anterior(tmp_path, monkeypatch, caplog):
    out = tmp_path / "surprise_profiles.json"
    out.write_text(
        json.dumps({"_meta": {"built_at": datetime.now(timezone.utc).isoformat()}, "profiles": {"ACN": _ACN}})
    )
    monkeypatch.setattr(b, "resolve_universe", lambda account_id=None: ["ACN", "WBD"])
    monkeypatch.setattr(b, "collect_yfinance_earnings_history", lambda t, limit=16: [])
    with caplog.at_level(logging.WARNING):
        res = b.run_build(out=out)
    escrito = json.loads(out.read_text(encoding="utf-8"))
    assert "ACN" in escrito["profiles"] and escrito["profiles"]["ACN"]["n_quarters"] == 24
    assert escrito["_meta"]["insufficient_history"] == {"WBD": 0}
    assert res["conservados"] == ["ACN"] and res["caidos"] == []


def test_run_build_dice_cual_cayo(tmp_path, monkeypatch, caplog):
    """Un conservado vencido cae, y el WARNING del final lo nombra."""
    out = tmp_path / "surprise_profiles.json"
    viejo = dict(_ACN, conservado_desde="2026-01-01T00:00:00+00:00")
    out.write_text(
        json.dumps({"_meta": {"built_at": "2026-10-19T16:50:00+00:00"}, "profiles": {"ACN": viejo}})
    )
    monkeypatch.setattr(b, "resolve_universe", lambda account_id=None: ["ACN"])
    monkeypatch.setattr(b, "collect_yfinance_earnings_history", lambda t, limit=16: [])
    with caplog.at_level(logging.WARNING):
        res = b.run_build(out=out)
    assert res["caidos"] == ["ACN"] and res["conservados"] == []
    assert any("hoy no: ACN" in r.getMessage() for r in caplog.records)
