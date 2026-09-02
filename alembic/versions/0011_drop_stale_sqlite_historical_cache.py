"""Borra el cache histórico SQLite congelado: el rollback de ARQ1 caducó (tarea 77).

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-02

Qué se borra y por qué NO es "una tabla que sobra"
--------------------------------------------------
``historical_data_cache`` tenía **288 filas / 22,7 MB de `data_json`** — el **24%
del archivo de DB** — con la última escritura del **2026-07-11**, o sea el día
**anterior** a activar el backend Parquet (ARQ1, 2026-07-12). No estaban ahí por
descuido: **esas filas SON el rollback** que el spec de ARQ1 vende
(*"volver el flag a `sqlite`; la tabla SQLite queda intacta"*).

La decisión —de Chapa, 2026-09-02— es que **ese rollback caducó**: Parquet corre
en vivo desde el 2026-07-12 sin incidentes, y volver a `sqlite` hoy no
restauraría un estado útil sino uno **de julio**.

Y borrarlas cierra además el agujero que la auditoría del 2026-09-02 reportó
como E-2: ``_read_latest_1d_frame`` y ``_read_all_1d_frames`` están marcados
*"Sin TTL"* y alimentan el **guard de sanity E5** y el **detector de split de la
T63**; con backend ``sqlite`` habrían usado el close del **2026-07-11** como
referencia hasta el primer fetch. Sin filas devuelven vacío, que es **fail-open
ruidoso** en vez de una referencia de julio disfrazada de actual.

**La tabla NO se borra**, sólo las filas: el backend ``sqlite`` sigue siendo un
camino de código válido (``historical_cache_backend``) y su default en el SCHEMA
sigue siendo ``sqlite``. Lo que deja de existir es el **contenido congelado**.

**Idempotente**: si la tabla no existe o ya está vacía, no hace nada.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if "historical_data_cache" not in set(sa.inspect(bind).get_table_names()):
        return
    bind.execute(sa.text("DELETE FROM historical_data_cache"))


def downgrade() -> None:
    """No-op **declarado**: no hay a dónde volver.

    Una bajada honesta tendría que **restaurar 22,7 MB de frames de julio**, y
    esta revisión no los guarda en ningún lado — justamente porque la decisión
    fue que ya no sirven. Fingir un `downgrade` que deja la tabla vacía sería
    peor: diría "revertido" sobre algo que no se revirtió. Si algún día hiciera
    falta el cache SQLite, se **re-puebla desde Parquet**, que es donde están los
    frames vivos.
    """
