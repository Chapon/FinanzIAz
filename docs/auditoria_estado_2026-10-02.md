# Auditoría — estado — 2026-10-02

Tarea **275**. READ-ONLY. Kill-criteria congelado en `docs/auditoria_tanda_killcriteria_2026-10-02.md` §8–12 (`estado`).

## 1. Alcance real

**Mirado:**
- **`paper_scan_candidates`** (la 256): quién la escribe y quién la poda.
- **El cohorte con SPY refrescada** (la 251/253).
- **`data/catalyst/surprise_profiles.json`**, que estaba modificado sin commitear al empezar la sesión: quién lo regenera, cada cuánto, y quién commitea lo regenerado.
- **Los frames `1y` de `data/parquet/`**, que la 255 encontró congelados: la última fecha de cada uno, hoy.
- **`data/catalyst/historical_reaction.json`**.

**NO mirado:**
- El esquema `alembic` de las tablas regenerables, más allá de la 0015. Motivo: la 0015 es la única migración desde la corrida anterior, y `DB_SCHEMA.md` la documenta (la 256).

## 2. Hallazgos

### [E-1] Los frames `1y` del cache quedan congelados cuando nadie los pide, y un script que los lea directo mide sobre datos viejos sin enterarse; la 255 lo vio y no abrió tarea
Severidad: **LOW** · Confianza: **ALTA**

**Evidencia:**
- Hoy, de los frames `*__1y__1d.parquet`: **115 terminan el 2026-09-09**, 23 el 2026-10-02, y 4 en julio.
- La 255 lo registró en su detalle del backlog (*«123 de 131 terminan el 2026-09-09»*), repitió su medición con `2y` y agregó a su script un reporte de frescura. **No abrió ninguna tarea** (regla 6).

**Razonamiento:**
- Los consumidores vivos (Analysis, Portfolio, el motor) piden por `get_historical_data`, con TTL: el frame se refresca cuando se lo pide, así que el congelamiento no los toca.
- El riesgo son los **scripts que leen `parquet_cache.read` directo**, como hicieron la 255 y la 258. Esos dos declaran la frescura; nada obliga al próximo a hacerlo.

**Acción:** un chequeo de frescura reusable para quien lea el parquet directo (la forma de `announce_spy_coverage`), o que `parquet_cache.read` avise si el frame terminó hace más de N ruedas.

→ tarea **286**.

### [E-2] `surprise_profiles.json` se regenera solo y está versionado, pero nadie dispara el commit: lleva cinco días sin commitear y cada sesión arranca con el árbol sucio
Severidad: **LOW** · Confianza: **ALTA**

**Evidencia:**
- `git status` al empezar la sesión: ` M data/catalyst/surprise_profiles.json`, archivo escrito el 2026-09-27 21:42.
- Último refresh commiteado: `6d19390`, el 2026-09-21, a mano.
- Está versionado por decisión de la 173 (`210a949`).

**Razonamiento:**
- El rebuild semanal del scheduler (job 4, T-CAT-5a) reescribe el archivo en el working tree, y la app lee el working tree, así que **lo vivo está bien**.
- Lo que nadie dispara es el commit. La versión del repo atrasa, y cualquier lectura del repo (un clon, el CI, la Lambda de la 196, un `git checkout --`) usa la vieja.
- Encima ensucia cada sesión: una modificación ajena queda mezclada con el trabajo propio (la memoria del proyecto pide justamente no *bundlear* trabajo ajeno).

**Acción:** decidir una de dos: que el refresh se commitee como parte de un paso conocido (el cierre de cada tarea, o el `/ship`), o que el archivo deje de versionarse y la 173 se revise.

→ tarea **286**.

## 3. Barrido limpio en lo demás

- **`paper_scan_candidates`:** la escribe cada scan, después del commit y en sesión propia; la poda el propio scan a 90 días (`RETENTION_DAYS = 90`, por cuenta y fecha, con índice; `docs/auditoria_rendimiento_2026-10-02.md`). Tiene dueño y frecuencia.
- **El cohorte con SPY:** `refresh_cohort.py` incluye a SPY desde la 251, y los runners de régimen abortan si no cubre (con el punto ciego de `docs/auditoria_guards_2026-10-02.md` [GD-1]).
- **`historical_reaction.json`** (2026-09-11): lo regenera a mano `scripts/build_historical_reaction.py`. La pestaña Noticias no lo usa (la 255); su único lector es `scripts/run_catalyst_exit_veto_backtest.py:70`, el runner del veto de catalysts, que en vivo está apagado (`paper_catalyst_exit_veto_enabled = false`). Nada vivo decide con él, así que su edad no tiene costo hoy; quien re-corra ese runner tiene que regenerarlo antes.

## 4. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| E-1 | 286 |
| E-2 | 286 |
