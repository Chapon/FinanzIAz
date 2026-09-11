# Auditoría READ-ONLY — área `estado` — 2026-09-11

Corrida de la tanda del **2026-09-11** (las cinco áreas). Área: **estado regenerable que
nadie regenera, y estado vivo que se desalinea en silencio**. Corrida anterior de esta área:
`docs/auditoria_estado_2026-09-08.md` (dejó las tareas 142 y 143).

---

## 1. Kill-criteria — CONGELADO 2026-09-11, antes de abrir ningún archivo

> Congelado junto con los otros cuatro de la tanda.

### 1.1 Por qué ahora

**Porque esta área acaba de cobrarse algo irreversible.** El 2026-09-09, durante la
operación de la 140, se refrescó el cohorte **a mano** y con eso se pisó
`ARTIFACT_REFRESH_EXCEPTIONS`: **AVB perdió la última copia sana de su histórico** y quedó
en 27 barras. No se puede recuperar. La 155 shipeó el script que faltaba, pero el episodio
dice qué tan cerca de la superficie está el riesgo en esta área.

Y hay dos cosas nuevas que tocan estado regenerable: los **JSON del scheduler** resultaron
versionados y se re-escribían en CRLF (tarea 173 — cerrada hoy, pero **el arreglo no toma
efecto hasta que se reinicie la app**, que sigue corriendo con el código viejo en memoria), y
el **store PIT** se recomputó dos veces esta semana (157, 158).

### 1.2 Qué se busca — una frase por sub-categoría

- **[E-huerfano]** Un store o cache **sin dueño**: nadie declarado lo regenera, y no hay
  contrato de cada cuánto.
- **[E-silencio]** Un artefacto que envejece sin que nada compare su frescura contra la de
  sus pares (la forma de la 30 y la 69).
- **[E-irreversible]** Estado cuya pérdida **no se puede deshacer** y que alguna operación
  manual puede pisar (el caso AVB).
- **[E-proceso]** Un proceso vivo —la app, el scheduler— que tiene código **viejo en
  memoria** y sigue escribiendo con él.
- **[E-crece]** Estado que crece sin poda ni archivo y nadie mide cuánto.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. **Bugs de código** y **re-correr harness**.
2. **Escribir en la DB o en cualquier artefacto.** Esta corrida es de lectura: si hay que
   regenerar algo, va como tarea.
3. Las otras cuatro áreas de la tanda.
4. La calidad de los datos de Yahoo como tal.

### 1.4 Qué contaría como "acá no hay nada"

Cierra limpia si, por cada store de §1.6:

- se puede nombrar **quién** lo regenera y **cada cuánto**;
- se puede decir **qué pasa si no** se regenera;
- hay algo que compare su frescura contra sus pares, o está declarado que no hace falta;
- y se dice cuáles no se barrieron.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Mismo protocolo que el §1.5 de `docs/auditoria_claims_2026-09-11.md`.

### 1.6 Alcance — qué se mira

1. `data/pit_signals/`, `data/parquet/`, `data/harness_results/`, `data/catalyst/`.
2. `data/*universe*.txt` y `data/harness_universe_*`.
3. Las tablas de cache de `finanzias.db` (`price_cache`, `earnings_cache`, los snapshots).
4. `backups/` — rotación y contenido.
5. Los procesos vivos: la app y el scheduler, qué regeneran y con qué cadencia.
6. `~/.finanzias/` — log y settings.

### 1.7 Alcance — qué NO se mira, dicho antes

- El esquema de la DB como tal (`alembic`) — eso tuvo su corrida en la 74.
- Los artefactos de sesiones de Claude y los temporales.
- `.venv` y dependencias.

---

## 2. Alcance real

**Mirado:** `data/pit_signals/` (500 archivos), `data/parquet/`, `data/harness_results/`,
`data/catalyst/`, `backups/` (13 archivos, 389 MB), las tablas de cache de `finanzias.db`, los
archivos de universo, y el proceso vivo de la app (PID y línea de comando).

**NO mirado, y queda declarado:** el esquema de la DB como tal (tuvo su corrida en la 74); los
temporales y artefactos de sesión; `.venv`.

---

## 3. Hallazgos

### [E-1] La app corre con el código de ayer en memoria, así que el arreglo de la 173 todavía no aplica

Severidad: **MEDIA** · Confianza: ALTA · Categoría: [E-proceso]
Ubicación: proceso `python.exe` PID 29264 (`"C:\Users\chapa\anaconda3\python.exe" main.py`),
arrancado el 2026-09-11 a las 11:38

**Evidencia.** La tarea **173** (cerrada hoy, commit `210a949`) agregó `newline="\n"` a
`scripts/build_surprise_profiles.py` y `scripts/build_historical_reaction.py` para que los dos
JSON versionados de `data/catalyst/` dejen de escribirse en CRLF. El proceso de la app arrancó a
las **11:38** y el commit es **posterior**: tiene los módulos viejos cargados.

**Razonamiento.** El scheduler semanal de `surprise_profiles` corre **dentro de la app**
(`SurpriseBuildWorker`). Cuando dispare, va a escribir con el código viejo y los dos archivos
vuelven a quedar CRLF contra un blob LF — que es exactamente el estado que la 173 midió y
normalizó esta mañana.

**Impacto.** El arreglo se revierte solo en la próxima corrida del scheduler, y el guard
(`check_repo_health.py`) lo va a marcar sin que se entienda por qué, porque el fuente **ya está
arreglado**.

**Verificación.** Se confirmó que el proceso es la app (no un harness) y que la 173 tocó
justamente el writer que ese proceso ejecuta.

**¿Por qué no antes? (a) NO EXISTÍA** — la 173 cerró hoy.

**Acción.** Reiniciar la app. Es una acción manual de Chapa, va a *Acciones manuales pendientes*.

### [E-2] `backups/` no tiene rotación para los backups ad-hoc: 389 MB y el más viejo es de junio

Severidad: **LOW-MEDIA** · Confianza: ALTA · Categoría: [E-crece]
Ubicación: `backups/`

**Evidencia.** 13 archivos, **389 MB** — el mayor consumidor de disco del repo, más que
`data/parquet` (61 MB) y `data/pit_signals` (37 MB) juntos. La rotación **sí** existe para los
`*_daily.db`, pero los ad-hoc se acumulan sin límite: `finanzias_pre_e5_20260701` (30 de junio),
`finanzias_pre_0007_20260709`, `finanzias_post_t77_20260902`, `finanzias_pre_t81_20260902`
(93 MB), `finanzias_pre_manuales_20260907`, `finanzias_2026-09-10_..._pre_t156_avb`.

**Razonamiento.** Cada uno se creó a mano antes de una operación riesgosa, que es **buena
práctica**; lo que falta es la política de cuánto se conservan. La tarea 143 cerró *«una rotación
que deja basura»* y cubrió los dailies.

**Impacto.** Disco, y nada más. No hay riesgo de corrección. Por eso es LOW-MEDIA.

**¿Por qué no antes? (c-alcance)** — la corrida del 2026-09-08 miró `backups/` y produjo las
tareas 142 y 143, que fueron sobre el **smoke test** y la **rotación de dailies**. El volumen de
los ad-hoc no estaba en esa muestra.

**Acción.** Decidir una política (¿los `pre_*` se conservan N días? ¿se mueven fuera del repo?).
Decisión de Chapa.

### [E-3] Un backup quedó con `-shm`/`-wal` colgados, o sea que alguien lo ABRIÓ

Severidad: **LOW-MEDIA** · Confianza: MEDIA · Categoría: [E-irreversible] (potencial)
Ubicación: `backups/finanzias_pre_e5_20260701_035340.db-shm` y `.db-wal`

**Evidencia.** El backup del 1 de julio tiene a su lado un `-shm` de **32 KB con mtime
2026-09-02** y un `-wal` de **0 bytes**. SQLite sólo crea esos dos archivos cuando **abre** la
base; el `-shm` con fecha de septiembre dice que el backup se abrió **dos meses después** de
crearse.

**Razonamiento.** Un backup es, por definición, algo que no se toca. Que tenga rastro de apertura
significa que alguna herramienta lo montó — y si lo montó en modo escritura, el backup **ya no es
el estado que dice ser**.

**Impacto.** No se puede afirmar que ese backup siga siendo fiel. Es el único de los 13 con este
rastro.

**Confianza MEDIA a propósito:** no medí si la apertura fue de lectura o de escritura, y no lo
voy a medir en una corrida read-only sobre un backup. La afirmación es *«se abrió»*, no *«se
corrompió»*.

**¿Por qué no antes? (c-alcance)** — mismo motivo que [E-2].

**Acción.** Verificar la integridad de ese backup (`PRAGMA integrity_check` sobre una copia) y
decidir si se conserva. Y averiguar qué lo abrió el 2026-09-02 — ese día se compactó la DB
(tarea 85) y se cerró la 77, que borró caches.

---

## 4. Barrido limpio en el resto del área

- **[E-huerfano]** — `data/pit_signals/` tiene **500 archivos** contra un universo vivo de
  **126**, o sea ~374 de tickers que ya no se usan. **No es un hallazgo**: son cache regenerable,
  gitignoreada, y `retired_tickers()` ya existe para distinguirlos. 37 MB no justifica una tarea.
- **[E-silencio]** — la frescura del cohorte **sí** tiene guard desde la 30 (`announce_artifacts`),
  y el store PIT desde la 69 y la 86. Los 126 artefactos vivos tienen mtime del 2026-09-09, que
  es el día del refresh: **coherentes entre sí**.
- **`historical_data_cache` está en 0 filas**, lo cual es correcto: la tarea 81 la archivó a
  Parquet.

---

## 5. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [E-1] la app corre con el código viejo (la 173 no aplica aún) | MEDIA | **186** (+ *Acciones manuales*) |
| [E-2] `backups/` sin rotación para los ad-hoc (389 MB) | LOW-MEDIA | **187** |
| [E-3] un backup con `-shm`/`-wal` colgados | LOW-MEDIA | **188** |

---

## 6. Deuda de método

**Ninguna (c-metodo) ni (d).** Dos hallazgos son **(c-alcance)** —el área es grande y `backups/`
se barrió por muestreo— y uno es **(a)**. La skill funcionó acá; lo que faltó fue tamaño de
muestra, que es el límite que la propia skill declara en *«Alcance: por área, nunca
exhaustiva»*.
