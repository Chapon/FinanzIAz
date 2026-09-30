# Auditoría READ-ONLY — área `estado` — 2026-09-30

Quinta corrida de la **tanda del 2026-09-30**. Área: **estado regenerable que nadie regenera**.
Corrida anterior de esta área: `docs/auditoria_estado_2026-09-11.md` (dejó las tareas 186 a 188,
las tres cerradas).

---

## 1. Kill-criteria — CONGELADO 2026-09-30, antes de abrir ningún archivo

> Congelado **junto con los otros cuatro** de la tanda y antes de empezar ninguna corrida.

### 1.1 Por qué ahora

1. **Tres semanas desde el último refresh del cohorte** (2026-09-09) y dos y media desde el último
   re-precómputo del store PIT de riesgo (2026-09-12, tarea 192). Es el intervalo más largo sin
   regenerar desde que el área existe.
2. **Stores nuevos o que cambiaron de forma**: el ledger de dividendos (`paper_dividend_credits`,
   222), el registro de la segunda opinión (206), el consenso con *una fila por día* en el esquema
   (203), `surprise_profiles.json` —hoy **modificado sin commitear** en el árbol de trabajo—, y la
   rotación de backups que la 187/193 cambió.
3. **La 196** va a mover la recolección a otra máquina: todo store que hoy se regenera por un
   proceso de esta máquina puede quedar sin dueño en el traspaso.
4. **La 236**: la suite sin estado dejaba el cache de yfinance **en el repo**.

### 1.2 Qué se busca — una frase por sub-categoría

- **[E-huerfano]** Un store o cache **sin dueño** ni contrato de frescura.
- **[E-silencio]** Un artefacto que envejece sin que nada compare su frescura con la de sus pares.
- **[E-irreversible]** Estado cuya pérdida no se deshace y que una operación manual puede pisar.
- **[E-proceso]** Un proceso vivo con código viejo en memoria que sigue escribiendo.
- **[E-crece]** Estado que crece sin poda y nadie mide cuánto.
- **[E-versionado]** Un archivo **versionado** que un proceso vivo reescribe, dejando el árbol sucio
  (forma de la 173 y del `surprise_profiles.json` de hoy).

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. Bugs de código y re-correr harness.
2. **Escribir en la DB o en cualquier artefacto.** La DB se lee **sobre una copia**.
3. Las otras cuatro áreas; la calidad de los datos de Yahoo; el esquema como tal.

### 1.4 Qué contaría como "acá no hay nada" — en las DOS direcciones

**Dirección 1 — lo escrito es falso.** Todo contrato de frescura escrito (docstring, skill,
checklist de la 192) coincide con la edad real del store.

**Dirección 2 — lo verdadero no está escrito.** Todo store de §1.6 tiene nombrado **quién** lo
regenera, **cada cuánto** y **qué pasa si no**, o está declarado que no hace falta; y lo que se
regenera con proceso de esta máquina tiene previsto su dueño en el traspaso de la 196.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Mismo protocolo.

### 1.6 Alcance — qué se mira

1. `data/pit_signals/`, `data/parquet/`, `data/harness_results/`, `data/catalyst/`.
2. Los archivos de universo.
3. Las tablas de cache/registro de `finanzias.db` (**copia**): `price_cache`, `earnings_cache`,
   consenso, dividendos, segunda opinión, alertas.
4. `backups/` — rotación real contra la que la 187/193 declara.
5. Los procesos vivos (app, scheduler) y qué regeneran.
6. `~/.finanzias/` — log y settings; y la raíz del repo (residuos de la 236).

### 1.7 Alcance — qué NO se mira, dicho antes

- `alembic` y el esquema como tal; `.venv`; temporales de sesión.

---

## 2. Alcance real

**Mirado:** edad y tamaño de cada store de `data/` (`pit_signals` 500 archivos, `pit_risk` 127,
`parquet` 827, `price_tape` 4, `form345` 42, `harness_results`, `harness_walkforward`,
`walkforward_power`, `catalyst`); `backups/` (13 archivos, 795 MB) contra la rotación de
`database/backup.py`; en una **copia** de la DB (backup API de SQLite, sobre `mode=ro`) las tablas
`price_cache`, `earnings_cache`, `analyst_estimate_snapshots`, `dividend_calendar_cache`,
`paper_dividend_credits`, `company_info_cache`, `news_events`; `~/.finanzias/` (log y rotación); la
raíz del repo; el proceso vivo (la app, PID 25808, arrancada 2026-09-30 14:32); el Task Scheduler de
Windows.

**NO mirado, y queda declarado:** el esquema (`alembic`); `.venv`; los temporales de sesión.

**Fase adversarial: PROPIA, no independiente.** Ningún hallazgo llegó a HIGH.

---

## 3. Hallazgos

### [E-1] La cinta intradía se archivó UNA vez, a mano, y desde entonces vive sólo en la DB operativa

Severidad: **MEDIA-BAJA** · Confianza: ALTA · Categoría: [E-huerfano] + [E-crece]
Ubicación: `scripts/archive_price_cache.py`; tabla `price_cache`

**Evidencia.** La tarea 81 (2026-09-02) decidió **archivar, no podar**: `price_cache` es *«la única
serie intradía del proyecto»*. El archivador se corrió **una vez** (los cuatro Parquet de
`data/price_tape/` son del 2026-09-02 14:02) y **no lo llama nada**: ni el scheduler, ni un `.bat`,
ni `/ship`; su único invocador es la línea de uso del docstring. Hoy `price_cache` tiene **199.756
filas** (2026-08-27 → hoy), y la DB volvió de **42,8 MB** (post-81, con `VACUUM`) a **~90 MB**; los
diarios de `backups/` crecen de 71 MB (09-15) a 90 MB (09-30), ~1,3 MB/día.

**Razonamiento.** El dato que la 81 decidió preservar existe, pero desde el 2026-09-02 **no está
archivado**: está en la tabla operativa, que es lo que la 81 quería evitar, y el contrato de
*«quién lo archiva y cada cuánto»* no existe. Nada lo mide ni lo avisa.

**Impacto.** Hoy, costo de tamaño (DB y cada backup diario). El día que alguien pode la tabla
—o que la 196 mude la recolección— sin correr antes el archivador, se pierde el tramo no archivado,
que es irrecuperable.

**¿Por qué no antes? (c-metodo)** — `price_cache` estaba en el alcance de la corrida del 2026-09-11
y su kill-criteria pedía *«quién lo regenera y cada cuánto»*. Para la cinta la respuesta ya era
*«nadie, fue una vez»* (nueve días de filas sin archivar). El método pregunta por stores que se
**regeneran**; una operación **manual que tiene que repetirse** no tiene esa forma y se pasó.

**Acción.** Darle dueño y cadencia al archivador (el tick diario del scheduler, con `--days 7`), o
declarar que se corre a mano y con qué recordatorio.

### [E-2] El reloj de T-CAT-5b perdió 6 de 12 días hábiles desde que se abrió la 196, y nada lo mide

Severidad: **MEDIA** · Confianza: ALTA · Categoría: [E-silencio]
Ubicación: tabla `analyst_estimate_snapshots`; backlog *Bloqueado* (T-CAT-5b)

**Evidencia.** Fechas con snapshot, días hábiles del 2026-09-14 al 2026-09-29 (12): **completos**
(127 tickers) el 14, 15, 21, 23 y 28; **parcial** el 22 (**7 de 127**); **sin captura** el 16, 17,
18, 24, 25 y 29. Es la app cerrada: los backups diarios —que se toman al arrancar— son del 15, 20,
21, 23, 27, 28 y 30. El 30 capturó (`estimates +1267` a las 14:37).

**Razonamiento.** *Bloqueado* dice que la próxima ventana completa para T-CAT-5b es **Q3 (~mediados
de octubre a mediados de noviembre), y sólo si la app corre de forma continua**, y remite a
*«mantener la app abierta (ver Acciones manuales pendientes)»* — pero esa acción **ya no está** en
*Acciones manuales pendientes*. La 196 (la Pi) está bloqueada esperando un dato de Chapa. Q3 empieza
en ~2 semanas y la tasa de captura de las últimas dos es ~45%. Y el día 22 con 7 de 127 **cuenta**
como día capturado para cualquier chequeo que cuente fechas.

**Impacto.** Si Q3 se captura como las últimas dos semanas, T-CAT-5b se corre otra temporada
(la de Q4, ~enero-febrero 2027), y hoy nadie lo va a ver hasta intentar desbloquearla.

**¿Por qué no antes? (a) NO EXISTÍA** — los huecos son posteriores al 2026-09-11.

**Acción.** Un chequeo de cobertura (días hábiles con snapshot **completo** en los últimos N) que
avise, y reponer en *Acciones manuales* la instrucción a la que *Bloqueado* remite — o sacar la
remisión. Emparenta con la 196, que es la solución de fondo; esto es lo que cubre el mientras tanto.

---

## 4. Barrido limpio en el resto del área — las dos direcciones

- **`pit_signals`:** los 126 del universo vivo son del 2026-09-09 (el refresh de la 157); los otros
  374 son del 2026-08-09/10 y no son del universo vivo. El harness lee a `WINDOW_LIVE`, fija, así
  que la edad no sesga: **declarado por diseño (T48)**.
- **`pit_risk`:** 126 del 2026-09-12 (la 192) + 1 del 2026-08-12. Más nuevo que `pit_signals`, lo
  que es inocuo porque el harness corta en la ventana.
- **`parquet`:** refrescado hoy por el warm-up del scan.
- **`backups/`:** 7 diarios + sueltos de ≤ 30 días, **como declara la 187/193**.
- **`earnings_cache`:** las 9 tenencias tienen fecha futura, bajada al comprar. Limpio.
- **Dividendos:** el calendario de las tenencias se refresca con el scan (fetched hoy 17:33).
- **`surprise_profiles.json`:** modificado sin commitear en el árbol, es el rebuild semanal del
  scheduler sobre un archivo **versionado** ([E-versionado]). Hay precedente de commitearlo a mano
  (`6d19390`, *«refresh surprise_profiles.json (rebuild del scheduler)»*). No se publica como
  hallazgo y se deja sin tocar: no es de esta corrida.
- **Raíz del repo:** `finanzias.db.rebuilt` (0 B) y su journal (512 B), del 2026-05-27, gitignoreados.
  Residuo inerte; se menciona y no se publica.
- **`data/harness_results/`** (mayo) y **`data/harness_walkforward/`** (junio): artefactos de
  corridas viejas, sin consumidor vivo, 800 KB. No es un hallazgo.

---

## 5. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [E-1] la cinta intradía sin dueño ni cadencia de archivo | MEDIA-BAJA | **244** |
| [E-2] 6 de 12 días hábiles sin snapshot, sin monitor, con Q3 a dos semanas | MEDIA | **245** |

---

## 6. Deuda de método

**[E-1] es (c-metodo).** El kill-criteria del área pregunta *«quién lo regenera y cada cuánto»*, que
es la pregunta de un **cache**. Una **operación manual que tiene que repetirse** (archivar,
compactar, rotar a mano) no se regenera: se **olvida**. Lo que faltaba: *por cada tarea cerrada que
dejó una operación periódica, preguntar quién la dispara*.
