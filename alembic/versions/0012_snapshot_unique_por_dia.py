"""El "una fila por día" del consenso pasa del código al esquema (tarea 203).

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-14

Qué garantizaba esto antes, y por qué no alcanza
------------------------------------------------
``AnalystEstimateSnapshot`` declara en su docstring, desde siempre, *"a lo sumo
una fila por (ticker, metric, period_label, día)"*. Lo **único** que lo sostenía
era ``harvest_catalysts._insert_estimate_if_new_today()``: consulta si la fila ya
está y recién entonces inserta. Eso es un *read-then-write* en Python, y tiene
dos agujeros:

1. **No es atómico.** Dos escritores concurrentes pasan los dos por el ``if``.
2. **Compara el datetime EXACTO** (``snapshot_date == _midnight(now)``). Un
   escritor que estampe la fecha **con hora**, o en UTC contra un local, no
   encuentra la fila que ya está y **duplica sin error y sin log**.

Funcionó hasta hoy por un motivo que no es del diseño: hay **un solo escritor**.
La tarea 196 (recolección continua fuera de la app) propone el segundo, y por eso
esto es su prerrequisito. La tabla hermana ``news_events`` ya tenía su garantía
en el esquema (``UNIQUE`` en ``content_hash``) — ésta no tenía ninguna.

Lo que se contamina si falla: la serie point-in-time del consenso, que es la base
del surprise score (T-CAT-5) y **la única serie del proyecto que no se puede
volver a bajar** — yfinance sólo expone el consenso *actual*.

Por qué el índice es por EXPRESIÓN
-----------------------------------
Un ``UNIQUE (ticker, metric, period_label, snapshot_date)`` a secas **no arregla
el defecto**: compara el mismo datetime exacto que comparaba el Python, así que
la fila de las 13:45 y la de medianoche del mismo día siguen siendo dos claves
distintas. Hace falta ``date(snapshot_date)``.

Y ``COALESCE(period_label, '')`` porque la columna es **nullable** y SQLite trata
cada NULL como distinto: sin eso, dos filas con ``period_label`` NULL del mismo
día pasan las dos. Hoy no hay ninguna NULL en la DB viva (verificado: 0 de
44.105), pero el esquema las permite y el índice tiene que cubrir lo que el
esquema permite, no lo que los datos traen hoy.

Estado de la DB viva al escribir esta revisión (2026-09-14)
-----------------------------------------------------------
44.105 filas, 44.105 claves ``(ticker, metric, period_label, DATE(snapshot_date))``
distintas: **cero duplicados**, cero ``period_label`` NULL, cero ``snapshot_date``
fuera de medianoche. O sea que el índice entra sin limpiar nada — el invariante ya
se cumplía de hecho, sólo que nada lo obligaba.

**Si hubiera duplicados**, ``CREATE UNIQUE INDEX`` falla. Esta revisión los busca
antes y levanta un error que dice cuántos y con qué clave, en vez de dejar el
``IntegrityError`` crudo de SQLite: arreglar duplicados es una decisión (cuál de
las dos filas es la buena) y no se toma dentro de una migración.

**Idempotente**: si el índice ya existe, no hace nada.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLA = "analyst_estimate_snapshots"
INDICE = "ux_est_ticker_metric_period_dia"

# La misma expresión que declara ``AnalystEstimateSnapshot.__table_args__``. Va
# escrita a mano y no importada de ``Base.metadata`` a propósito, igual que en la
# 0004 y la 0009: una revisión congela lo que hizo, y si el model cambia mañana
# eso es una revisión NUEVA, no un cambio retroactivo de ésta.
CLAVE = "ticker, metric, COALESCE(period_label, ''), date(snapshot_date)"

_DUPES = f"""
    SELECT ticker, metric, COALESCE(period_label, ''), date(snapshot_date), COUNT(*) n
    FROM {TABLA}
    GROUP BY 1, 2, 3, 4
    HAVING n > 1
"""


def _tiene(conn, nombre: str, tipo: str) -> bool:
    fila = conn.execute(
        sa.text("SELECT 1 FROM sqlite_master WHERE type = :tipo AND name = :n"),
        {"tipo": tipo, "n": nombre},
    ).first()
    return fila is not None


def upgrade() -> None:
    conn = op.get_bind()
    if not _tiene(conn, TABLA, "table"):
        return  # DB sin la tabla: nada que indexar (create_all la hará con el índice)
    if _tiene(conn, INDICE, "index"):
        return  # ya está (DB nueva construida por create_all)

    dupes = conn.execute(sa.text(_DUPES)).fetchall()
    if dupes:
        muestra = ", ".join(f"{t}/{m}/{p or '∅'}@{d} ×{n}" for t, m, p, d, n in dupes[:5])
        raise RuntimeError(
            f"{TABLA}: {len(dupes)} claves duplicadas por ({CLAVE}); el índice único no puede "
            f"crearse hasta resolverlas. Muestra: {muestra}. Cuál de las filas repetidas es la "
            "buena es una decisión, no algo que deba elegir una migración (tarea 203)."
        )

    op.execute(sa.text(f"CREATE UNIQUE INDEX {INDICE} ON {TABLA} ({CLAVE})"))


def downgrade() -> None:
    op.execute(sa.text(f"DROP INDEX IF EXISTS {INDICE}"))
