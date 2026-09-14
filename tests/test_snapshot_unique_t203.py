"""Tarea 203 — el "una fila por día" del consenso lo garantiza el ESQUEMA, no el código.

El defecto no era que hubiera duplicados: **no había ninguno** (44.105 filas,
44.105 claves, medido el 2026-09-14). Era que lo único que lo impedía era un
*read-then-write* en Python, y eso deja dos agujeros:

1. no es atómico — dos escritores pasan los dos por el ``if``;
2. compara el datetime **exacto**, así que un escritor que estampe
   ``snapshot_date`` con hora no encuentra la fila que ya está y **duplica**.

Funcionaba porque hay un solo escritor. La tarea 196 propone el segundo.

**Por qué los tests insisten con la hora.** El arreglo "obvio" —un
``UNIQUE (ticker, metric, period_label, snapshot_date)``— **no arregla nada**:
compara el mismo datetime exacto que comparaba el Python. Estos tests fallan con
ese índice y pasan con el de expresión, que es lo que los hace valer.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa

alembic = pytest.importorskip("alembic")

from alembic.config import Config

import paper_trading.models  # noqa: F401  — registra las tablas paper en Base.metadata
from alembic import command
from database.models import AnalystEstimateSnapshot, Base, missing_declared_indexes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INDICE = "ux_est_ticker_metric_period_dia"
TABLA = "analyst_estimate_snapshots"
DIA = datetime(2026, 9, 14, 0, 0, 0)


def _cfg(db_path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(ROOT, "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def _engine_con_indice(tmp_path):
    """DB completa por create_all — el índice viene declarado en el model."""
    return sa.create_engine(f"sqlite:///{tmp_path / 'con.db'}")


def _fila(conn, *, ticker="KO", metric="eps", period="0q", cuando=DIA, valor=1.0):
    conn.execute(
        sa.text(
            f"INSERT INTO {TABLA} (ticker, metric, period_label, consensus_value, snapshot_date) "
            "VALUES (:t, :m, :p, :v, :d)"
        ),
        {"t": ticker, "m": metric, "p": period, "v": valor, "d": cuando},
    )


# ── El índice existe, y llega por el camino de migración ─────────────────────


def test_el_model_declara_el_indice_unico():
    idx = {i.name: i for i in Base.metadata.tables[TABLA].indexes}
    assert INDICE in idx, f"el model dejó de declarar {INDICE}"
    assert idx[INDICE].unique is True


def test_create_all_lo_crea(tmp_path):
    engine = _engine_con_indice(tmp_path)
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        sql = conn.execute(
            sa.text("SELECT sql FROM sqlite_master WHERE type='index' AND name=:n"), {"n": INDICE}
        ).scalar()
    assert sql is not None, "create_all no creó el índice"
    assert "date(snapshot_date)" in sql.lower(), f"el índice no es por día: {sql}"
    assert "coalesce" in sql.lower(), f"el índice no cubre period_label NULL: {sql}"


def test_la_migracion_lo_crea_sobre_una_DB_que_no_lo_tiene(tmp_path):
    """El camino que le llega a la DB de Chapa: tabla puesta, índice no.

    ``create_all(checkfirst=True)`` saltea una tabla que ya existe, índices
    incluidos (tarea 74), así que sin migración el índice no llega nunca.
    """
    db = tmp_path / "vieja.db"
    engine = sa.create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    # `create_all` no deja `alembic_version`, así que hay que stampear el estado
    # ANTERIOR a esta revisión: es lo que hace `_alembic_sync` con una DB nueva, y
    # sin eso `upgrade head` arrancaría de 0001 sobre un esquema que ya está puesto.
    command.stamp(_cfg(db), "0011")
    with engine.begin() as conn:
        conn.execute(sa.text(f"DROP INDEX IF EXISTS {INDICE}"))
        _fila(conn)  # con datos adentro, como la DB real
    with engine.connect() as conn:
        assert (
            conn.execute(
                sa.text("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=:n"),
                {"n": INDICE},
            ).scalar()
            == 0
        )

    command.upgrade(_cfg(db), "head")

    with engine.connect() as conn:
        assert (
            conn.execute(
                sa.text("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=:n"),
                {"n": INDICE},
            ).scalar()
            == 1
        )


def test_la_migracion_es_idempotente(tmp_path):
    db = tmp_path / "dosveces.db"
    engine = sa.create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    command.stamp(_cfg(db), "0011")
    with engine.begin() as conn:
        conn.execute(sa.text(f"DROP INDEX IF EXISTS {INDICE}"))
    command.upgrade(_cfg(db), "head")
    command.downgrade(_cfg(db), "0011")
    command.upgrade(_cfg(db), "head")  # no explota
    with engine.connect() as conn:
        assert (
            conn.execute(
                sa.text("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=:n"),
                {"n": INDICE},
            ).scalar()
            == 1
        )


def test_la_migracion_FRENA_si_hay_duplicados_y_dice_cuales(tmp_path):
    """Arreglar duplicados es una decisión; la migración avisa, no elige."""
    db = tmp_path / "sucia.db"
    engine = sa.create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    command.stamp(_cfg(db), "0011")
    with engine.begin() as conn:
        conn.execute(sa.text(f"DROP INDEX IF EXISTS {INDICE}"))
        _fila(conn, cuando=DIA, valor=1.0)
        _fila(conn, cuando=DIA + timedelta(hours=13), valor=2.0)  # mismo día, otra hora

    with pytest.raises(Exception) as exc:
        command.upgrade(_cfg(db), "head")
    msg = str(exc.value)
    assert "duplicadas" in msg and "KO/eps" in msg, msg


# ── Lo que el índice frena, y lo que NO ──────────────────────────────────────


@pytest.fixture
def conn_con_indice(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'idx.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        _fila(conn)
        yield conn


def test_frena_el_MISMO_dia_con_OTRA_hora(conn_con_indice):
    """**El caso central.** Un UNIQUE sobre la columna dejaría pasar esto.

    Es la forma exacta del defecto: un escritor que estampe ``snapshot_date`` con
    hora —o en UTC contra un local— no encuentra la fila de medianoche que ya está.
    """
    with pytest.raises(sa.exc.IntegrityError):
        _fila(conn_con_indice, cuando=DIA + timedelta(hours=13, minutes=45))


def test_frena_el_mismo_dia_exacto(conn_con_indice):
    with pytest.raises(sa.exc.IntegrityError):
        _fila(conn_con_indice, cuando=DIA)


def test_frena_dos_period_label_NULL_del_mismo_dia(tmp_path):
    """SQLite trata cada NULL como distinto: sin COALESCE pasan las dos.

    Hoy no hay ninguna fila con ``period_label`` NULL (0 de 44.105), pero la
    columna es nullable y el índice tiene que cubrir lo que el esquema permite.
    """
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'nulos.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        _fila(conn, period=None)
        with pytest.raises(sa.exc.IntegrityError):
            _fila(conn, period=None, cuando=DIA + timedelta(hours=9))


def test_NO_frena_otro_dia(conn_con_indice):
    _fila(conn_con_indice, cuando=DIA + timedelta(days=1))  # la serie diaria sigue creciendo


def test_NO_frena_otro_period_label(conn_con_indice):
    _fila(conn_con_indice, period="+1q")


def test_NO_frena_otra_metrica_ni_otro_ticker(conn_con_indice):
    _fila(conn_con_indice, metric="revenue")
    _fila(conn_con_indice, ticker="NVDA")


# ── El guard de la tarea 74 tiene que poder VER un índice por expresión ──────


def test_missing_declared_indexes_NO_acusa_al_indice_por_expresion(tmp_path):
    """Sin esto el guard de la 74 quedaba en rojo permanente.

    ``inspect(engine).get_indexes()`` **saltea** los índices por expresión, así que
    el declarado se reportaba como faltante existiera o no — y no había forma de
    ponerlo en verde. Es la contraprueba del arreglo de ``missing_declared_indexes``.
    """
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'guard.db'}")
    Base.metadata.create_all(engine)
    assert missing_declared_indexes(engine) == []


def test_el_guard_SI_lo_acusa_cuando_falta_de_verdad(tmp_path):
    """Mutación: si el arreglo tapara el agujero mirando para otro lado, esto pasaría."""
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'sinidx.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text(f"DROP INDEX {INDICE}"))
    assert (TABLA, INDICE) in missing_declared_indexes(engine)


# ── El harvest: el pre-chequeo sigue, pero ya no es lo que garantiza ─────────


def _snap(ticker="KO", metric="eps", period="0q", valor=1.0):
    from data.news_sources import EstimateSnapshot

    return EstimateSnapshot(
        ticker=ticker, metric=metric, period_label=period, consensus_value=valor, num_analysts=3
    )


def test_el_harvest_cuenta_como_duplicado_lo_que_frena_el_indice(tmp_path, monkeypatch):
    """Una colisión no puede llevarse puesto el resto del ticker.

    La fase 2 persiste news + estimates del mismo ticker en **una** sesión, así que
    sin el savepoint un ``IntegrityError`` en un snapshot abortaría también sus
    noticias y marcaría el ticker como fallido.
    """
    from sqlalchemy.orm import sessionmaker

    import scripts.harvest_catalysts as hc

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'harvest.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    # Otro escritor ya dejó la fila del día, estampada CON HORA: es la que el
    # pre-chequeo del harvest no puede ver.
    with engine.begin() as conn:
        _fila(conn, cuando=DIA + timedelta(hours=8, minutes=30))

    session = Session()
    try:
        nuevo = hc._insert_estimate_if_new_today(session, _snap(), DIA)
        assert nuevo is False, "debería contarse como duplicado, no como fila nueva"
        # La sesión sigue viva: el savepoint revirtió sólo esa fila.
        session.add(
            AnalystEstimateSnapshot(ticker="NVDA", metric="eps", period_label="0q", snapshot_date=DIA)
        )
        session.commit()
    finally:
        session.close()

    with engine.connect() as conn:
        assert conn.execute(sa.text(f"SELECT COUNT(*) FROM {TABLA}")).scalar() == 2


def test_sin_el_indice_el_defecto_SE_REPRODUCE(tmp_path):
    """Mutación en el sentido del defecto: sacá el índice y la duplicación vuelve.

    Es lo que prueba que el índice es lo que garantiza el invariante, y no el
    ``if`` de Python que sigue estando en las dos corridas.
    """
    from sqlalchemy.orm import sessionmaker

    import scripts.harvest_catalysts as hc

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'sin.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text(f"DROP INDEX {INDICE}"))
        _fila(conn, cuando=DIA + timedelta(hours=8, minutes=30))

    session = sessionmaker(bind=engine)()
    try:
        nuevo = hc._insert_estimate_if_new_today(session, _snap(), DIA)
        session.commit()
    finally:
        session.close()

    assert nuevo is True, "sin el índice, el pre-chequeo NO ve la fila con hora"
    with engine.connect() as conn:
        n = conn.execute(
            sa.text(f"SELECT COUNT(*) FROM {TABLA} WHERE date(snapshot_date) = '2026-09-14'")
        ).scalar()
    assert n == 2, "el defecto de la 203, reproducido: dos filas para el mismo día"
