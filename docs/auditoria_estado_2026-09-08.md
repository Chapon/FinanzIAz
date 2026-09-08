# Auditoría READ-ONLY — área `estado` — 2026-09-08

Novena corrida de `/audit`. Área: **estado regenerable que nadie regenera** — caches,
artefactos y stores gitignoreados, sin contrato de frescura y sin dueño. Corrida anterior de
esta área: `docs/auditoria_estado_2026-09-02.md` (dejó las tareas 74 a 78).

---

## 1. Kill-criteria — CONGELADO 2026-09-08, antes de abrir ningún archivo

> Escrito **antes** de listar un directorio o abrir la DB. No se toca después.

### 1.1 Por qué ahora, y con qué pista

La corrida de `guards` de hoy dejó una pista que apunta directo a esta área: el cohorte **`5y`
tiene su última barra el 2026-06-01 —71 ruedas atrás— y ningún guard lo acusa**. Eso es un
hallazgo *de guard* (tarea **140**); la pregunta *de estado* es la otra mitad y no está
respondida: **¿quién regenera cada store, cada cuánto, y qué pasa si nadie lo hace?**

Además, la corrida anterior de esta área dejó explícitamente sin mirar tres cosas
(`precompute_pit_risk_score`, `earnings_cache` y los archivos de universo), y desde entonces se
movió el sustrato: la 111 reparó el cohorte, la 117 recomputó el store PIT, la 113 re-bajó
MNST, la 81 archivó `price_cache` a Parquet y la 77 borró el cache SQLite.

### 1.2 Qué se busca — una frase por sub-categoría

- **[E-dueño]** Un store sin **dueño**: nada ni nadie lo regenera de forma disparada, sólo a
  mano y cuando alguien se acuerda.
- **[E-contrato]** Un store **sin contrato de frescura**: no existe la respuesta escrita a
  *«¿a partir de cuándo está viejo?»*.
- **[E-huérfano]** Estado que **ya no lo lee nadie** y sigue ocupando lugar, o que sí lo lee
  alguien pero se escribió con un esquema que cambió.
- **[E-desparejo]** Dos stores del **mismo sustrato** que se desalinean entre sí sin que nada
  los compare.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. **La ceguera del guard de frescura** — es la tarea **140**, abierta hoy. Acá se mira el
   **estado**, no el guard.
2. **Bugs de código** (suite, CI, `/code-review`).
3. **Escribir en `finanzias.db`.** Se lee `mode=ro` y nada más (regla 5).
4. **Regenerar nada.** Es READ-ONLY: si un store está viejo se **reporta**, no se refresca.

### 1.4 Qué contaría como "acá no hay nada" — condición de barrido limpio

Cierra **limpia** si, para **cada** store regenerable: (1) hay un dueño identificable —un job,
un trigger de la app o un paso documentado—; (2) existe escrito el criterio de *«está viejo»*;
(3) todo lo que ocupa lugar tiene al menos un lector vivo; y (4) los stores del mismo sustrato
están alineados entre sí o algo los compara.

### 1.5 Alcance que se va a mirar

`data/parquet/` (los tres períodos), `data/pit_signals/`, `data/harness_results/`,
`data/baselines/`, los archivos de universo de `data/`, `backups/`, y en la DB viva
(`mode=ro`): `earnings_cache`, `price_cache`, `analyst_estimate_snapshots`, `news_events` y
`failed_tickers`.

---

## 2. Inventario del estado (medido, no supuesto)

| store | tamaño | rango de mtime |
|---|---|---|
| `data/parquet/` | 753 archivos, 60 MB | 2026-07-12 .. 2026-09-08 |
| `data/pit_signals/` | 501 archivos, 37 MB | 2026-08-09 .. 2026-09-07 |
| `data/harness_results/` | 26 archivos, 1 MB | 2026-05-29 .. 2026-05-30 |
| `data/baselines/` | 1 archivo | 2026-05-26 |
| `backups/` | 30 archivos, **370 MB** | 2026-06-16 .. 2026-09-08 |

`data/parquet/` por período: **`10y` 506 frames**, **`2y` 134**, **`1y` 69**, **`5y` 42** (todos
con mtime del 2026-07-12, el día de la migración ARQ1), más dos sueltos (`AXON__3mo`,
`AXON__6mo`).

Las 19 tablas de la DB viva se listaron con su rango de fechas (`mode=ro`).

**NO mirado:** regenerar nada (es READ-ONLY), la ceguera del guard de frescura (es la tarea
**140**, abierta hoy), y los guards en sí.

**Sin fase adversarial:** ninguno de los dos hallazgos llega a HIGH y los dos son mecánicos —
un `sorted()` y un `unlink()`.

---

## 3. Hallazgos

### [E-1] El smoke test dice «corrida contra el último backup» y toma el último ALFABÉTICO, que por el esquema de nombres no puede ser nunca un backup diario

Severidad: **MEDIA** · Confianza: **ALTA** · Categoría: [E-contrato]
Ubicación: `tests/test_baseline_metrics.py:454-462`

**Evidencia.** El test hace `backups = sorted((repo_root / "backups").glob("finanzias_*.db"))` y
después `run(backups[-1], out_dir, write=True)`, con el docstring *«Smoke test: corrida contra
el último backup»*. Medido hoy:

- el que **elige** (`sorted[-1]`, o sea por **nombre**): `finanzias_pre_t81_20260902_140200.db`
  — del **2026-09-02**;
- el **más nuevo de verdad** (por mtime): `finanzias_2026-09-08_19-20-55_daily.db` — de **hoy**.

**Razonamiento — y esto es lo que lo hace estructural y no un desfase pasajero.** Los backups
diarios se llaman `finanzias_YYYY-MM-DD_…` y los manuales `finanzias_pre_*` / `finanzias_post_*`.
En orden ASCII, `p` > `2`, así que **cualquier backup `pre_`/`post_` le gana a todos los
fechados, para siempre**. El test no va a volver a ejercitar un backup diario mientras exista
uno manual, y va a saltar de uno manual a otro según qué sufijo ordene último.

**Impacto.** El smoke test que valida `baseline_metrics` end-to-end contra una DB real corre
—en silencio— contra una DB **arbitraria y congelada**, elegida por el alfabeto. Sigue pasando,
así que nada avisa. Y `finanzias_pre_t81_20260902` es, por su propio nombre, el backup **previo**
a la tarea 81: el test quedó clavado a un esquema anterior a esa migración.

**Verificación.** Se descartó que fuera casualidad de nombres de hoy: el orden ASCII lo
garantiza. Se confirmó que `baseline_metrics` abre con `mode=ro` (`scripts/baseline_metrics.py:777`),
o sea que **la suite no escribe** en la DB de backup — el defecto es de **selección**, no de
escritura.

**Nota lateral, del mismo test:** abrir un backup WAL en `mode=ro` **igual crea el `-shm`** al
lado. Por eso `finanzias_pre_t81_20260902_140200.db-shm` tiene mtime de hoy: lo tocó la suite.
Es inocuo por sí solo, pero se conecta con [E-2].

**Acción mínima.** Elegir por **mtime**, o restringir el glob al patrón fechado. Y que el
docstring diga cuál elige.

---

### [E-2] `rotate_backups` borra el `.db` y deja sus `-shm`/`-wal`: 18 archivos huérfanos de 9 backups que ya no existen

Severidad: **BAJA-MEDIA** · Confianza: **ALTA** · Categoría: [E-huérfano]
Ubicación: `database/backup.py:108-126`

**Evidencia.** La rotación hace `p.unlink()` **sólo sobre el `.db`**. Medido en `backups/`:

- **7** archivos `.db`,
- **22** side files `-shm`/`-wal`,
- **18 huérfanos** —9 pares— cuyo `.db` ya fue rotado: `2026-06-16`, `06-17`, `06-21`, `06-23`,
  `06-25`, `06-26`, `06-30`, `07-20` y `07-23`. Cada `-shm` pesa 32.768 bytes; los `-wal` están
  en 0.

**Razonamiento.** Es el footgun estándar de SQLite: una base WAL son **tres** archivos y
borrarla es borrar los tres. Acá se borra uno, así que `backups/` acumula un par por cada
backup rotado, **sin techo**.

**Impacto.** Hoy es chico y es sobre todo higiene: ~288 KB y un directorio ilegible de un
vistazo. El riesgo real es el de la forma, no el del tamaño: **un `-wal` al lado de una base no
es inerte** — si alguna vez se restaura un backup copiándolo a un destino donde quedó un `-wal`
con el mismo nombre base, SQLite lo aplica. Hoy los `-wal` están en 0 bytes, así que **no hay
daño**; lo que hay es un mecanismo que garantiza que la basura se acumule.

**Acción mínima.** Que `rotate_backups` borre los tres archivos. Y de paso limpiar los 18 que
ya están (decisión de Chapa: es borrar archivos, y esta corrida es READ-ONLY).

---

## 4. Lo que se revisó y NO dio hallazgo

**Tres hipótesis mías se cayeron al verificarlas**, y van escritas porque el descarte vale tanto
como el hallazgo:

1. **«El cohorte `5y` está congelado desde el 2026-07-12, nadie lo regenera».** **Falso como
   defecto.** El cache Parquet **tiene** contrato de frescura: `parquet_cache.read` aplica
   `ttl_hours` y un frame vencido es un *miss* que se re-baja. El `5y` está viejo porque **nadie
   pidió un gráfico de 5 años desde julio** — es un cache perezoso funcionando bien. Lo que sí
   queda dicho, y refuerza la tarea **140**: `cohort_bars` lee con **`ttl_hours=None`** a
   propósito (`analysis/harness_config.py:583`), porque un backtest no puede re-bajar datos en
   el medio. O sea que en el camino del harness **el TTL no existe y el guard es la única línea
   de defensa** — que es justo la que la 140 dice que está ciega.
2. **«`dividend_cache` tiene 908 filas de abril, un índice que le creó la tarea 74, y ningún
   lector».** **Falso:** `data/yahoo_finance.py:1858-1884` lo lee y lo escribe. Está viejo
   porque nadie consultó dividendos desde abril.
3. **«`backups/` no tiene política de retención».** **Falso:** `database/backup.py` expone
   `rotate_backups(keep=7)` y hay exactamente **7** `.db`, o sea que funciona. Lo que **no**
   limpia son los side files — eso es [E-2].

**Y una cuarta que también se cayó, con más razón para escribirla:**

4. **«`earnings_cache` cubre 42 de 128 tickers (33%), así que el Gate 6 tiene un agujero para
   86».** **Falso.** `get_next_earnings_date` es un cache con TTL y **fail-open**: un miss
   consulta a Yahoo y decide igual. Las 42 filas son el *hit rate* en un instante, no la
   cobertura del gate. (Lo que sí queda, y ya está en el backlog como OPS1-b, es que la
   escritura del cache es el `delete-then-insert` que pelea por el lock.)

**Revisados y coherentes:** `data/pit_signals/` (501 artefactos, recomputado el 2026-09-07 por
la 117; `signal_store_gaps` da **0** sobre el universo vivo), `historical_data_cache` (0 filas,
como la dejó la 77), y las tablas legacy `portfolios`/`transactions` (leídas por la UI de
cartera real, congeladas porque esa pestaña no se usa desde abril — no son huérfanas).

---

## 5. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [E-1] «el último backup» es el último alfabético | MEDIA | **142** BACKUP-ALFABETICO |
| [E-2] la rotación deja 18 `-shm`/`-wal` huérfanos | BAJA-MEDIA | **143** ROTATE-SIDEFILES |

Dos hallazgos, dos filas, ninguna vacía, ninguno agrupado dentro de otro.

## 6. Limitaciones

1. **No se regeneró ni se borró nada** — incluidos los 18 huérfanos, que son una decisión de
   Chapa.
2. **`data/harness_results/` y `data/baselines/`** se inventariaron (26 archivos de mayo y 1 de
   mayo) pero **no se auditó si sus números se citan como vigentes** en algún lado; queda para
   la próxima corrida de esta área.
3. Una corrida por área no es exhaustiva.
