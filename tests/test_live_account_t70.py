"""CUENTA-VIVA-APP (tarea 70) — los jobs de fondo corrían sobre la cuenta PAUSADA.

Hasta el 2026-09-01, **los siete** call sites con alcance de cuenta del lado app
tenían el literal `1` como default —dashboard, rebuild de `surprise_profiles`,
harvest de catalysts y cuatro herederos— y **ninguno miraba `is_active`**. La
cuenta 1 está pausada desde el 2026-07-01, así que durante dos meses el dashboard
se re-estampó a diario con una cartera congelada y el harvest recolectó para 52
tickers en vez de 128 — **79 nombres del universo vivo sin una sola noticia en 45
días**, y esa cobertura no se recupera (`data/news_sources.py:477`, `days_back=7`).

Del lado harness esto estaba resuelto desde la tarea 27 (`LIVE_ACCOUNT_ID`). Acá
el arreglo **no es poner `2`**: eso es el mismo defecto con otro número, y el
próximo cambio de cuenta lo reabre. Se resuelve **contra la DB**.
"""

from __future__ import annotations

import logging

import pytest

from paper_trading.account import create_account, live_account_id


def _cuenta(nombre: str, *, activa: bool):
    acct = create_account(name=nombre, initial_capital=50_000.0)
    from database.models import session_scope
    from paper_trading.models import PaperAccount

    with session_scope() as s:
        row = s.query(PaperAccount).filter(PaperAccount.id == acct.id).first()
        row.is_active = activa
    return acct.id


# ── La resolución ────────────────────────────────────────────────────────────


def test_sin_flag_resuelve_la_cuenta_ACTIVA_no_la_primera(test_db):
    """El corazón del arreglo: el default deja de ser un literal. Hoy **ningún**
    flag está seteado, así que todos los jobs tomaban el `1` hardcodeado."""
    pausada = _cuenta("Pausada", activa=False)
    viva = _cuenta("Viva", activa=True)
    assert pausada < viva  # la pausada es la de menor id, como en producción
    assert live_account_id() == viva


def test_sin_ninguna_cuenta_activa_devuelve_None_y_el_job_NO_corre(test_db, caplog):
    """Un job de fondo que no sabe sobre qué cuenta opera **no debe elegir una**.
    No correr es la respuesta correcta, y se avisa."""
    _cuenta("Pausada", activa=False)
    with caplog.at_level(logging.WARNING, logger="paper_trading.account"):
        assert live_account_id() is None
    assert any("is_active=1" in r.getMessage() for r in caplog.records)


def test_con_varias_activas_elige_la_de_menor_id_y_avisa(test_db, caplog):
    """Ambigüedad, no error: se elige determinísticamente y se declara."""
    a = _cuenta("Una", activa=True)
    b = _cuenta("Otra", activa=True)
    with caplog.at_level(logging.WARNING, logger="paper_trading.account"):
        assert live_account_id() == min(a, b)
    assert any("cuentas activas" in r.getMessage() for r in caplog.records)


# ── El flag explícito ────────────────────────────────────────────────────────


def test_un_flag_explicito_se_respeta(test_db, monkeypatch):
    """Si el operador lo seteó, mandó él."""
    _cuenta("Viva", activa=True)
    pausada = _cuenta("Pausada", activa=False)
    from config.settings_manager import settings

    monkeypatch.setattr(settings, "get", lambda k, d=None: pausada if k == "mi_flag" else d)
    assert live_account_id("mi_flag") == pausada


def test_pero_si_apunta_a_una_PAUSADA_lo_grita(test_db, monkeypatch, caplog):
    """**El silencio es lo que dejó correr esto dos meses.** Se respeta la
    decisión del operador, pero no puede quedarse callado."""
    _cuenta("Viva", activa=True)
    pausada = _cuenta("Pausada", activa=False)
    from config.settings_manager import settings

    monkeypatch.setattr(settings, "get", lambda k, d=None: pausada if k == "mi_flag" else d)
    with caplog.at_level(logging.WARNING, logger="paper_trading.account"):
        live_account_id("mi_flag")
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "PAUSADA" in msg and "tarea 70" in msg


def test_un_flag_que_apunta_a_una_cuenta_inexistente_cae_a_la_viva(test_db, caplog, monkeypatch):
    viva = _cuenta("Viva", activa=True)
    from config.settings_manager import settings

    monkeypatch.setattr(settings, "get", lambda k, d=None: 9999 if k == "mi_flag" else d)
    with caplog.at_level(logging.WARNING, logger="paper_trading.account"):
        assert live_account_id("mi_flag") == viva
    assert any("no existe" in r.getMessage() for r in caplog.records)


def test_un_error_de_DB_no_rompe_el_scan(monkeypatch, caplog):
    """Fail-safe, mismo criterio que los guards de la 59 y la 64: un guard nuevo
    que rompe un scan es peor que el problema que resuelve."""
    import paper_trading.account as acc

    def _boom(**_kw):
        raise RuntimeError("DB caida")

    monkeypatch.setattr(acc, "list_accounts", _boom)
    with caplog.at_level(logging.ERROR, logger="paper_trading.account"):
        assert live_account_id() is None


# ── El cableado: los siete call sites ────────────────────────────────────────


@pytest.mark.parametrize(
    "modulo",
    [
        "scripts/harvest_catalysts.py",
        "scripts/news_feed.py",
        "scripts/dashboard_data.py",
    ],
)
def test_ningun_script_defaultea_a_un_literal(modulo):
    """Regresión del arreglo: `DEFAULT_ACCOUNT_ID = 1` es el defecto. Si vuelve,
    vuelve el bug entero — y en `dashboard_data.py` estaba el **séptimo** call
    site, que ni la auditoría había enumerado."""
    from pathlib import Path

    txt = (Path(__file__).resolve().parent.parent / modulo).read_text(encoding="utf-8")
    assert "DEFAULT_ACCOUNT_ID = 1" not in txt


def test_el_scheduler_resuelve_los_dos_jobs_contra_is_active():
    """Los dos jobs del scheduler (dashboard y rebuild de surprise) pasan por el
    mismo resolver, y **saltean** si no hay cuenta viva."""
    from pathlib import Path

    txt = (Path(__file__).resolve().parent.parent / "paper_trading" / "scheduler.py").read_text(
        encoding="utf-8"
    )
    assert 'settings.get("dashboard_refresh_account_id", 1)' not in txt
    assert 'settings.get("surprise_build_account_id", 1)' not in txt
    assert txt.count("_job_account_id(") >= 3  # la def + los dos jobs
    assert txt.count("if account_id is None:") >= 2  # los dos saltean


def test_el_harvest_sin_flag_usa_la_cuenta_viva(test_db):
    """La punta que más dolía: el universo del harvest sale de la cuenta viva."""
    from scripts.harvest_catalysts import resolve_account_id

    _cuenta("Pausada", activa=False)
    viva = _cuenta("Viva", activa=True)
    assert resolve_account_id() == viva
    assert resolve_account_id(123) == 123  # un id explícito se respeta


# ── El artifact del dashboard ────────────────────────────────────────────────


def test_el_artifact_neutro_gana_pero_el_legacy_es_el_fallback(monkeypatch, tmp_path):
    """El nombre `sim-principal` quedó mintiendo, pero cambiar la constante a secas
    habría hecho que `targets_ready()` diera False y el refresh se saltease **en
    silencio** — cambiar una falla silenciosa por otra."""
    import scripts.refresh_dashboard as rd

    neutro = tmp_path / "finanzias-dashboard" / "index.html"
    legacy = tmp_path / "finanzias-sim-principal-dashboard" / "index.html"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("x", encoding="utf-8")
    monkeypatch.setattr(rd, "ARTIFACT_NEUTRAL", neutro)
    monkeypatch.setattr(rd, "ARTIFACT_LEGACY", legacy)

    assert rd.default_artifact() == legacy  # hoy: sólo existe el legacy

    neutro.parent.mkdir(parents=True)
    neutro.write_text("x", encoding="utf-8")
    assert rd.default_artifact() == neutro  # el día que se renombre la carpeta
