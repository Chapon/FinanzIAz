"""Tarea 237 — ALERTAS-TRABAN-LA-DB.

`check_alerts` era una sola `session_scope`: el re-arme de la 227 hace `UPDATE` + `flush()`,
que toma el write lock de SQLite, y los precios se pedían con esa transacción abierta. Cada
`get_current_price` escribe `price_cache` por **otra** conexión, así que esperaba a su propio
llamador hasta el `busy_timeout`: 163 s medidos con las 10 alertas reales, y el scan tampoco
podía escribir (`docs/lock_arranque_t235_2026-09-28.md`).

**Estos tests necesitan una DB de ARCHIVO.** El lock es de SQLite, entre conexiones; con la
in-memory de `test_db` no hay dos conexiones sobre el mismo archivo y el defecto no existe.
El fetch se reemplaza por uno que hace lo mismo que el real en lo que importa acá: escribe el
cache por una conexión propia, con un timeout corto para que el rojo tarde 0,5 s y no 30.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from alerts.alert_manager import AlertManager
from database import models as db_models
from database.models import Alert, Portfolio, session_scope, utcnow_naive

_TIMEOUT_S = 0.5


@pytest.fixture
def db_archivo(tmp_path, monkeypatch):
    """La DB de la app sobre un archivo, en WAL como la viva, con timeout corto."""
    import paper_trading.models  # noqa: F401  (registra las tablas de paper en Base)

    path = tmp_path / "alertas.db"
    engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": _TIMEOUT_S})

    @event.listens_for(engine, "connect")
    def _wal(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")

    monkeypatch.setattr(db_models, "ENGINE", engine)
    monkeypatch.setattr(
        db_models, "SessionLocal", sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    )
    db_models.Base.metadata.create_all(engine)
    yield path
    engine.dispose()


class _FetchQueEscribeElCache:
    """Como `get_current_price`: devuelve el precio y escribe `price_cache` por otra conexión."""

    def __init__(self, path, precios, al_pedir=None):
        self.path, self.precios, self.al_pedir = path, precios, al_pedir
        self.bloqueos: list[str] = []
        self.esperas: list[float] = []

    def __call__(self, ticker):
        con = sqlite3.connect(self.path, timeout=_TIMEOUT_S)
        t0 = time.perf_counter()
        try:
            if self.al_pedir:
                self.al_pedir(con, ticker)
            con.execute(
                "INSERT INTO price_cache (ticker, price, fetched_at) VALUES (?, ?, ?)",
                (ticker, self.precios[ticker], utcnow_naive().isoformat(" ")),
            )
            con.commit()
        except sqlite3.OperationalError as e:
            self.bloqueos.append(f"{ticker}: {e}")
        finally:
            self.esperas.append(time.perf_counter() - t0)
            con.close()
        return {"price": self.precios[ticker]}


def _sembrar(*, rearmar: bool) -> None:
    """Dos tickers; con `rearmar`, una alerta disparada AYER, que es lo que toma el lock."""
    with session_scope() as s:
        p = Portfolio(name="PF")
        s.add(p)
        s.flush()
        s.add(Alert(portfolio_id=p.id, ticker="MARA", alert_type="ABOVE", target_value=15.0))
        s.add(
            Alert(
                portfolio_id=p.id,
                ticker="CRM",
                alert_type="ABOVE",
                target_value=230.0,
                is_active=not rearmar,
                triggered_at=utcnow_naive() - timedelta(days=1) if rearmar else None,
            )
        )


def test_con_una_alerta_para_REARMAR_el_fetch_escribe_el_cache_sin_esperar(db_archivo, monkeypatch):
    """El caso de la 235: primer chequeo del día. Antes, cada escritura del cache esperaba al
    re-arme de su propio llamador y terminaba en `database is locked`."""
    _sembrar(rearmar=True)
    fetch = _FetchQueEscribeElCache(db_archivo, {"MARA": 12.55, "CRM": 240.0})
    monkeypatch.setattr("alerts.alert_manager.get_current_price", fetch)

    disparadas = AlertManager(notifier=lambda t: True).check_alerts()

    assert fetch.bloqueos == []
    assert max(fetch.esperas) < _TIMEOUT_S / 2, fetch.esperas
    # Y el re-arme de la 227 se ve en el MISMO chequeo: CRM, disparada ayer, vuelve a disparar hoy.
    assert [a.ticker for a in disparadas] == ["CRM"]


def test_el_instrumento_VE_el_defecto(db_archivo):
    """Contraprueba del test de arriba: con la forma vieja —fetch adentro de la sesión que
    hizo el re-arme— el mismo fetch sí queda bloqueado. Sin esto, un fetch que no escribiera
    nada pasaría el test de arriba sin probar nada."""
    _sembrar(rearmar=True)
    fetch = _FetchQueEscribeElCache(db_archivo, {"MARA": 12.55})
    with session_scope() as s:
        AlertManager._rearmar_dia_nuevo(s)
        fetch("MARA")
    assert len(fetch.bloqueos) == 1 and "locked" in fetch.bloqueos[0]


def test_una_alerta_PAUSADA_mientras_se_pedian_los_precios_no_dispara(db_archivo, monkeypatch):
    """Los disparos se leen de nuevo después del fetch, en una sesión aparte. La pausa se
    escribe desde otra conexión en medio del fetch, que es justo lo que antes no podía pasar."""
    _sembrar(rearmar=False)

    def pausar_crm(con, ticker):
        if ticker == "CRM":
            con.execute("UPDATE alerts SET is_paused = 1 WHERE ticker = 'CRM'")
            con.commit()

    fetch = _FetchQueEscribeElCache(db_archivo, {"MARA": 16.0, "CRM": 240.0}, al_pedir=pausar_crm)
    monkeypatch.setattr("alerts.alert_manager.get_current_price", fetch)

    disparadas = AlertManager(notifier=lambda t: True).check_alerts()

    assert fetch.bloqueos == []
    assert [a.ticker for a in disparadas] == ["MARA"]


def test_los_disparos_quedan_commiteados_antes_de_avisar_a_Slack(db_archivo, monkeypatch):
    """El orden del NOTIF1 sobrevive a la partición: cuando el notifier corre, el disparo ya
    está en la DB (se lee por una conexión propia, que sólo ve lo commiteado)."""
    _sembrar(rearmar=False)
    monkeypatch.setattr(
        "alerts.alert_manager.get_current_price",
        _FetchQueEscribeElCache(db_archivo, {"MARA": 16.0, "CRM": 1.0}),
    )
    visto: list = []

    def notifier(_texto):
        con = sqlite3.connect(db_archivo)
        visto.extend(
            con.execute("SELECT ticker, is_active FROM alerts WHERE triggered_at IS NOT NULL").fetchall()
        )
        con.close()
        return True

    AlertManager(notifier=notifier).check_alerts()
    assert visto == [("MARA", 0)]
