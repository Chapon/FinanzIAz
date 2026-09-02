"""Tarea 74 — el esquema declarado en los models tiene que existir en la DB.

El defecto que cierran estos tests no es "faltaban 24 índices": es el
**mecanismo** que los dejó faltando y que nada notaba.
``Base.metadata.create_all(checkfirst=True)`` **saltea entera** una tabla que ya
existe —índices incluidos—, así que un índice agregado a un model **después** de
que su tabla existiera no llega nunca a una DB existente. Y como los tests
miraban el ORM (o una DB recién creada por ``create_all``), **confirmaban la
mentira**: en el ORM el índice siempre está.

Por eso el invariante que se fija acá se mide sobre el **camino de migración**,
que es el único que le llega a una DB que ya existe:

    tablas puestas + cero índices declarados + ``upgrade head``
        ⇒ no falta ninguno de los declarados

Consecuencia deseada: **agregar un índice a un model sin revisión alembic nueva
pone este test en rojo**, que es exactamente lo que no pasó entre el 2026-05-06
y hoy.
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa

alembic = pytest.importorskip("alembic")

from alembic.config import Config

import paper_trading.models  # noqa: F401  — registra las tablas paper en Base.metadata
from alembic import command
from database import models as db_models
from database.models import Base, missing_declared_indexes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cfg(db_path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(ROOT, "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def _declared() -> set[tuple[str, str]]:
    """{(tabla, índice)} declarados en los models, con las paper_* incluidas."""
    return {(t.name, i.name) for t in Base.metadata.sorted_tables for i in t.indexes}


def _full_db(path):
    """DB con el esquema completo vía create_all (todos los índices puestos)."""
    engine = sa.create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    return engine


def _strip_indexes(engine) -> int:
    """Deja las tablas pero borra TODOS los índices declarados. Devuelve cuántos."""
    with engine.begin() as conn:
        for _table, idx in sorted(_declared()):
            conn.execute(sa.text(f"DROP INDEX IF EXISTS {idx}"))
    return len(_declared())


def test_hay_indices_declarados():
    """Sanity: si esto diera 0, los tests de abajo pasarían vacíos y no dirían nada.

    Es un **piso contra la vacuidad**, no un conteo de la verdad: el número real
    se mueve cuando se agrega o se saca un índice (la tarea 81 sacó dos de
    ``price_cache`` que nadie usaba), y un test que haya que ir subiendo o
    bajando a mano no es un invariante.
    """
    assert len(_declared()) > 20


def test_el_barrido_incluye_las_tablas_paper():
    """Regresión de la tarea 79: sin registrar los models paper, el barrido cuenta de menos.

    El informe de la auditoría publicó *"18 índices en 7 tablas"* y le atribuyó
    el error al verificador, que decía 24 en 11. El verificador tenía razón: el
    barrido corrió **sin** ``import paper_trading.models``, así que las cinco
    tablas ``paper_*`` ni estaban en ``Base.metadata`` y sus 6 índices eran
    invisibles. Es el mismo defecto que la auditoría fue a buscar —un chequeo
    que mide la cosa equivocada— un nivel más arriba.
    """
    tablas = {t for t, _ in _declared()}
    assert {"paper_orders", "paper_positions", "paper_watchlist", "paper_equity_snapshots"} <= tablas


def test_upgrade_restaura_todos_los_indices_declarados(tmp_path):
    """EL GUARD: una DB con las tablas y sin índices sale de ``upgrade head`` completa.

    Falla si alguien agrega un índice a un model y no escribe la revisión que lo
    crea — el índice existiría sólo en DBs nuevas.
    """
    path = tmp_path / "drift.db"
    engine = _full_db(path)
    _strip_indexes(engine)

    # Sanity: la DB de verdad quedó sin los índices declarados (si no, el test
    # pasaría por no haber borrado nada).
    faltan_antes = missing_declared_indexes(engine)
    assert len(faltan_antes) == len(_declared())

    command.stamp(_cfg(path), "0008")
    command.upgrade(_cfg(path), "head")

    assert missing_declared_indexes(engine) == []


def test_upgrade_es_idempotente_sobre_una_db_completa(tmp_path):
    """El caso de la DB nueva: ``create_all`` ya la dejó completa ⇒ 0009 no toca nada."""
    path = tmp_path / "full.db"
    engine = _full_db(path)
    command.stamp(_cfg(path), "0008")

    def snap():
        insp = sa.inspect(engine)
        return {
            t: {i["name"] for i in insp.get_indexes(t)}
            for t in insp.get_table_names()
            if t != "alembic_version"
        }

    antes = snap()
    command.upgrade(_cfg(path), "head")
    command.upgrade(_cfg(path), "head")
    assert snap() == antes
    assert missing_declared_indexes(engine) == []


def test_los_indices_unicos_siguen_siendo_unicos(tmp_path):
    """La reconstrucción no puede degradar un índice ÚNICO a uno común.

    Tres de los declarados son ``unique=True`` (uno de ellos, ``ix_news_content_hash``,
    es lo que evita noticias duplicadas). Recrearlos sin el flag sería cambiar
    una restricción de datos por un índice de performance, en silencio.
    """
    path = tmp_path / "uniq.db"
    engine = _full_db(path)
    unicos = {
        (t.name, i.name) for t in Base.metadata.sorted_tables for i in t.indexes if i.unique
    }
    assert unicos, "el test se quedó sin población"

    _strip_indexes(engine)
    command.stamp(_cfg(path), "0008")
    command.upgrade(_cfg(path), "head")

    insp = sa.inspect(engine)
    for tabla, idx in unicos:
        real = next(i for i in insp.get_indexes(tabla) if i["name"] == idx)
        assert real["unique"], f"{idx} se recreó sin unique"


def test_el_arranque_avisa_cuando_falta_un_indice(tmp_path, caplog):
    """``_warn_on_index_drift`` emite UNA línea, y en el caso sano no dice nada.

    Mismo estilo que la telemetría de la 25 y la 67: que la línea aparezca es la
    señal. Caza el caso que el test de migración no puede — una DB restaurada de
    un backup viejo o stampeada a mano en una revisión que no le corresponde.
    """
    path = tmp_path / "warn.db"
    engine = _full_db(path)

    with caplog.at_level("WARNING"):
        assert db_models._warn_on_index_drift(engine) == []
    assert not [r for r in caplog.records if "índice" in r.getMessage()]

    with engine.begin() as conn:
        conn.execute(sa.text("DROP INDEX ix_price_cache_ticker_fetched"))
    caplog.clear()
    with caplog.at_level("WARNING"):
        faltan = db_models._warn_on_index_drift(engine)
    assert faltan == [("price_cache", "ix_price_cache_ticker_fetched")]
    avisos = [r for r in caplog.records if "índice" in r.getMessage()]
    assert len(avisos) == 1
    assert "ix_price_cache_ticker_fetched" in avisos[0].getMessage()


def test_el_lookup_de_price_cache_usa_el_indice(tmp_path):
    """El consumidor caliente deja de escanear la tabla.

    ``get_current_price`` filtra por ticker + ``fetched_at >= cutoff`` y ordena por
    ``fetched_at`` descendente. Sin ``ix_price_cache_ticker_fetched`` el plan es
    ``SCAN price_cache`` + ``USE TEMP B-TREE FOR ORDER BY`` (38,7 ms sobre las
    400.453 filas de la DB viva). Este test fija el plan, no el tiempo: un
    milisegundo depende de la máquina, el ``SEARCH`` no.
    """
    path = tmp_path / "plan.db"
    engine = _full_db(path)
    q = (
        "EXPLAIN QUERY PLAN SELECT * FROM price_cache "
        "WHERE ticker = 'AAPL' AND fetched_at >= '2020-01-01' "
        "ORDER BY fetched_at DESC LIMIT 1"
    )
    with engine.connect() as conn:
        plan = " | ".join(str(r[3]) for r in conn.execute(sa.text(q)))
    assert "SCAN price_cache" not in plan, plan
    assert "ix_price_cache_ticker_fetched" in plan, plan
