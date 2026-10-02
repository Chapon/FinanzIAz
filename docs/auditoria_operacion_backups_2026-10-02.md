# Auditoría — operación: backups, restore y migraciones — 2026-10-02

Tarea **273**, primera corrida de backups/restore dentro de `operacion` (ampliada por la 271). READ-ONLY. Kill-criteria congelado en `docs/auditoria_tanda_killcriteria_2026-10-02.md` §3.

## 1. Alcance real

**Mirado:**
- `database/backup.py` entero: backup, rotación, poda y `restore_database`.
- El botón de restore de `ui/settings_tab.py:255-300`.
- El directorio `backups/`.
- El orden de arranque de `main.py`.
- `_alembic_sync` (`database/models.py:700-733`) y `alembic/env.py`.
- `PRAGMA journal_mode`, los archivos `-wal`/`-shm` de la DB viva, y la integridad y la versión de esquema de dos backups diarios (abiertos en solo lectura).

**Cómo se probó el restore sin tocar la DB viva:** dos DBs **sintéticas** en el scratchpad, en WAL y con una conexión abierta que no hizo checkpoint, como la app. Sobre ellas se repitió la secuencia exacta de `restore_database`.

**NO mirado:**
- Una migración real que falle a medio camino. Motivo: forzarla exige escribir en una DB con el esquema real; se razona sobre el código (§2, B-2).

## 2. Hallazgos

### [B-1] El restore de Settings no restaura con la app abierta, y la copia para deshacer pierde lo que estaba en el WAL
Severidad: **HIGH** · Confianza: **ALTA** en el mecanismo (reproducido sobre DBs sintéticas)

**Ubicación:**
- `database/backup.py:262-289` (`restore_database`): `shutil.copy2(live, rollback)` y después `shutil.copy2(backup, live)`.
- `ui/settings_tab.py:283-300`: lo llama con la app corriendo, sin parar el scheduler ni cerrar el engine. El diálogo sólo pide *«Cerrá manualmente el portafolio»*.

**Evidencia:**
- La DB viva está en `journal_mode=wal` (`database/models.py:91`). Ahora mismo tiene un `finanzias.db-wal` de **6,2 MB** con cambios todavía no volcados al `.db`.
- La reproducción, con una «viva» de 5.000 filas en el WAL y un backup de 100:
  - después del restore, **al reabrir hay 5.000 filas**: no se restauró nada, porque la conexión abierta volcó su WAL al cerrar;
  - **la copia `.before-restore` tiene 0 filas**: copió sólo el `.db`, sin el WAL.
- Settings igual muestra *«Restore exitoso»*.

**Razonamiento:**
- Copiar el archivo principal de una DB en WAL con conexiones abiertas no es un restore: el `-wal` y el `-shm` viejos quedan al lado, y las conexiones vivas los vuelcan sobre el archivo nuevo.
- Lo mismo vale para la copia de rollback, que pierde todo lo que no se había volcado.
- La propia función lo advierte en su docstring (*«The caller is responsible for closing all open SQLAlchemy sessions»*), y el único llamador no lo hace.

**Impacto:**
- La herramienta de recuperación ante un desastre **dice que funcionó y no funcionó**.
- Si después de eso se confía en el `.before-restore` para volver atrás, faltan los cambios recientes.
- **El `verificador` lo midió con el autocheckpoint por defecto** (1000 páginas, commits chicos, una conexión abierta como la de la app). Es **peor** que lo que muestra mi caso:

| caso | WAL | `.before-restore` | DB tras cerrar la app |
|---|---|---|---|
| chico | 41 KB | pierde las 5 filas del WAL | **el restore se revierte solo** |
| chico | 420 KB | pierde 50 | **el restore se revierte solo** |
| medio | 4,1 MB | pierde 56 | restauró |
| grande, filas grandes | 4,1 MB | faltan filas | **`integrity_check` falla**, y la conexión viva lee `database disk image is malformed` |

  La DB viva tenía un WAL de 6,2 MB al medir.

**Fase adversarial (`verificador`, independiente):** ningún código de producción hace `dispose()` ni `wal_checkpoint` (sólo los tests), y el único test de restore (`tests/test_backup.py:126`) usa una DB sin WAL y con las conexiones cerradas. *«Reiniciá la app»* **empeora** el caso: al cerrar la última conexión se vuelca el WAL viejo sobre el archivo restaurado. Sobrevive como HIGH: hace falta una acción manual poco frecuente, pero es justo la herramienta de recuperación.

**¿Por qué no antes?** (b): backups y restore no estaban en ningún área hasta la 271.

**Acción:** el restore se hace con la app sin conexiones abiertas. Opciones:
- que el botón deje marcado el restore pendiente y lo ejecute `main.py` al arrancar, antes de `init_db`;
- o que pare el scheduler, haga `engine.dispose()` y use la API de backup de SQLite en las dos direcciones.

La copia de rollback también debe hacerse con la API de backup, no con `copy2`.

→ tarea **278**.

### [B-2] Las migraciones corren antes del backup diario: una migración nueva arranca sin una copia tomada justo antes
Severidad: **MEDIUM** · Confianza: **ALTA**

**Ubicación:** `main.py:38-45`: `init_db()`, que corre `command.upgrade(cfg, "head")` (`database/models.py:731`), va **antes** de `maybe_rotate_daily()`.

**Razonamiento:**
- Cuando entra una migración (como la 0015 de la 256), el último backup es el del arranque anterior, que pudo ser hace días, y el del día se toma **después** de migrar.
- Si la migración tira una excepción, `init_db` no la atrapa, la app no arranca y el backup del día **no se toma nunca**.

**Impacto:** ante una migración que falla o que daña datos, la copia más reciente puede tener días de atraso.

**¿Por qué no antes?** (b).

**Acción:** tomar el backup **antes** de `init_db`, por lo menos cuando hay una migración pendiente (comparar `alembic_version` contra el head).

→ tarea **278**, en el mismo enunciado.

## 3. Barrido limpio en lo demás

- **Backup diario:**
  - existe uno por cada día que la app arrancó (09-21, 23, 27, 28, 30, 10-01, 10-02), y la rotación deja 7;
  - se toma con la API de backup de SQLite (`backup.py:114`), que es consistente en WAL;
  - si eso falla, cae a una copia de archivo, con un WARNING.
- **Integridad:** el backup del 2026-10-02 da `quick_check = ok` y está en el esquema 0015, con `paper_scan_candidates`. El del 09-21 está en 0012; restaurarlo y reiniciar lo migra (`init_db` → `upgrade head`), y el mensaje de Settings pide reiniciar.
- **Poda de sueltos (la 187):** `prune_adhoc_backups` corre en cada arranque. Los sueltos que quedan (09-02, 09-07, 09-23) están dentro de los 30 días.
- **Fallas de backup:** se loguean (`log.exception("maybe_rotate_daily failed")`) y no frenan el arranque.

## 4. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| B-1 | 278 |
| B-2 | 278 |
