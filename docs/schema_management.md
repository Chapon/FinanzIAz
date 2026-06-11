# Gestión de esquema — alembic como único camino (T7.3, 2026-06-11)

Cierra **M1** del code review 2026-06-09: el esquema vivía en dos fuentes de
verdad (alembic abandonado en 0003 + `create_all` y parches `ALTER TABLE`
manuales en `database.models._migrate`). Decisión tomada con Chapa: **migración
catch-up** y alembic vuelve a ser el mecanismo oficial.

## Estado

- Revisión `0004_catchup_post_0003_schema` congela el delta post-0003 en el
  timeline: tablas `earnings_cache`, `analyst_data_cache`, `news_events`,
  `analyst_estimate_snapshots` + columnas `paper_accounts.slack_notify`,
  `paper_equity_snapshots.portfolio_sigma`, `positions.purchase_date`. Es
  **idempotente** (guards con inspector): la DB de producción, que ya tiene
  todo por create_all/_migrate, pasa sin DDL y queda en head.
- `database.models._migrate()` fue **eliminado**; lo reemplaza
  `_alembic_sync()`, que corre en cada `init_db()`:
  - DB nueva (sin `alembic_version`): `create_all` ya armó el esquema completo
    → `stamp head`.
  - DB existente: `upgrade head`.
- `alembic` pasó de `requirements-dev.txt` a `requirements.txt` (dependencia
  de runtime).
- `alembic/env.py` respeta una `sqlalchemy.url` pre-seteada (Config
  programático de `_alembic_sync` y tests apuntan a DBs temporales sin tocar
  `finanzias.db`).

## Cómo hacer un cambio de esquema (flujo oficial)

1. Editar los modelos (`database/models.py` / `paper_trading/models.py`).
2. Generar la revisión: `alembic revision --autogenerate -m "describe change"`
   (desde la raíz del repo, con la DB local en head). Revisar el archivo
   generado a mano — autogenerate en SQLite necesita `render_as_batch` (ya
   configurado en env.py) y a veces propone ruido.
3. No hace falta aplicarla a mano: `init_db()` corre `upgrade head` en el
   próximo arranque de la app. Para aplicarla ya: `alembic upgrade head`.
4. Tests: los unit tests siguen usando `Base.metadata.create_all` sobre
   engines in-memory (conftest) — eso es correcto y no cambia. Si la revisión
   tiene lógica no trivial, agregar un caso a `tests/test_alembic_catchup.py`
   o un archivo propio.

**Prohibido desde T7.3**: agregar parches `ALTER TABLE` manuales en
`init_db`/helpers, o crear tablas nuevas confiando solo en `create_all` sin su
revisión alembic. (`create_all` sigue corriendo en `init_db` — es inocuo y
necesario para DBs nuevas y tests — pero ya no es la fuente de verdad de la
evolución del esquema.)

## Por qué el baseline sigue siendo no-op

`0001_baseline` es no-op a propósito: las DBs reales nacieron por `create_all`.
El onboarding de una DB nueva sigue siendo create_all + `stamp head`
(automatizado en `_alembic_sync`). El timeline alembic existe para la
**evolución** del esquema, no para el génesis — eso evita mantener dos
definiciones DDL completas en paralelo.

## Verificación

`tests/test_alembic_catchup.py` cubre: equivalencia (estado-0003 + `upgrade
head` == esquema create_all, incluyendo índices), idempotencia sobre DB
completa stampeada en 0003 (el caso producción), stamp de DB nueva, upgrade de
DB vieja vía `_alembic_sync`, y downgrade simétrico. Requiere SQLite ≥ 3.35
(DROP COLUMN) para fabricar el estado-0003.
