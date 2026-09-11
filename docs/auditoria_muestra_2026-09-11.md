# Auditoría READ-ONLY — área `muestra` — 2026-09-11

Corrida de la tanda del **2026-09-11** (las cinco áreas). Área: **chequeos por CANTIDAD,
ciegos a la identidad de la muestra**. Corrida anterior de esta área:
`docs/auditoria_muestra_2026-09-08.md` (dejó las tareas 144 y 145).

---

## 1. Kill-criteria — CONGELADO 2026-09-11, antes de abrir ningún archivo

> Congelado **junto con los otros cuatro** de la tanda y antes de empezar ninguna corrida,
> para que el criterio de un área no se calibre con lo que apareció en otra.

### 1.1 Por qué ahora — y es la razón más fuerte de las cinco

**El sustrato de esta área se movió de verdad, no de a poco.** El 2026-09-09 se refrescó el
cohorte y eso cambió **la muestra misma**: la ventana pasó a `2016-09-12..2026-09-09`, las
17 constantes de reproducción se re-anclaron (157), la watchlist bajó de 128 a 126, y **AVB
perdió su histórico** quedando como miembro **inerte** de 27 barras (156).

Y hay un precedente exacto de lo que esta área existe para cazar, **de esta semana**: la
tarea **164** encontró que el brazo de control se sorteaba por **índice de barra**, así que
cualquier refresh lo re-sorteaba entero — y eso **invalidó al T37 y al T47** sin que ningún
control lo dijera. O sea: un chequeo que miraba la cantidad de barras y no **cuáles**.

### 1.2 Qué se busca — una frase por sub-categoría

- **[M-cantidad]** Un invariante decidido contando (`len(...) >= n`, un conteo de filas, un
  `n_tickers`) donde lo que importa es **cuáles** elementos, no cuántos.
- **[M-ventana]** Un chequeo que sigue siendo verdad con la ventana vieja y falso con la
  rodada, sin que nada lo declare.
- **[M-poblacion]** Una población derivada de una **lista** o de una convención de nombre en
  vez de de la **propiedad** que al chequeo le importa (la familia 133 / 141 / 147 / 161).
- **[M-inerte]** Un miembro que cuenta como sano para algún conteo pero no aporta nada
  —el caso AVB— y algún chequeo lo toma como evidencia.
- **[M-vacio]** Un chequeo que pasa **por población vacía** y se lee como *«no hay
  violaciones»* (el defecto de la 174, cerrado hoy).

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. **Bugs de código** y **re-correr harness**.
2. **Los guards** en cuanto a si degradan en silencio — eso es el área `guards` de esta
   misma tanda.
3. **Los desvíos harness↔engine** — área `desvios`.
4. **Los artefactos y su frescura** como problema de regeneración — área `estado`. Acá sólo
   interesa si un **chequeo** los lee mal.

### 1.4 Qué contaría como "acá no hay nada"

Cierra limpia si, habiendo barrido los sustratos de §1.6, se verifica que:

- todo `len(...)`/conteo que decide *«la muestra es ésta»* tiene al lado una comparación de
  identidad (fechas, claves o huella), o está declarado por qué no hace falta;
- ninguna población viva sale de una lista hardcodeada donde existe un predicado;
- los conteos pinneados en tests y runners coinciden con lo que el cohorte mide hoy;
- y se dice qué no se pudo verificar.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Mismo protocolo que el §1.5 de `docs/auditoria_claims_2026-09-11.md`: etiquetas **(a) NO
EXISTÍA**, **(b) FUERA DE ALCANCE**, **(c-alcance)**, **(c-metodo)** y **(d) SE DESCARTÓ
MAL**, y sólo **(c-metodo)** y **(d)** cuentan como deuda de la skill.

### 1.6 Alcance — qué se mira

1. `analysis/harness_config.py` — los chequeos de población, ventana, frescura y store.
2. `analysis/portfolio_sim.py`, `analysis/scaleout_replay.py`, `analysis/exit_replay.py`.
3. `scripts/run_*.py` y `scripts/measure_*.py` — sus sanity y sus constantes pinneadas.
4. `scripts/precompute_pit_*.py` — las guardas de completitud.
5. Los tests que **pinnean conteos** como invariante de muestra.

### 1.7 Alcance — qué NO se mira, dicho antes

- El motor vivo (`paper_trading/engine.py`) salvo donde comparta un chequeo con el harness.
- `ui/`, `data/news_sources.py`, el pipeline de catalysts.
- La calidad de los datos de Yahoo en sí.

---

## 2. Alcance real

**Mirado:** el inventario de umbrales de sanity de la tarea 164
(`tests/test_sanity_no_anclado_t164.py`, dict `INVENTARIO`, 40 constantes), los 8 runners con
umbral de clase `magnitud`, `docs/reanchor_t157_2026-09-09.md`, el listado completo de docs
posteriores al refresh, los conteos pinneados en `tests/` y `scripts/`, y la watchlist / archivo
de universo / espejo `LIVE_WATCHLIST_SIZE` contrastados entre sí.

**NO mirado, y queda declarado:** no se re-corrió **ningún** harness (la corrida es read-only y
además correrlos es caro); `analysis/exit_replay.py` y `analysis/scaleout_replay.py` se miraron
sólo por grep; el motor vivo quedó afuera por §1.3.

---

## 3. Hallazgos

### [M-1] El T21 es el único runner con sanity de `magnitud` que no se re-corrió tras el refresh

Severidad: **BAJA** · Confianza: ALTA *(sobre el hecho de proceso)* · Categoría: [M-ventana]
Ubicación: `scripts/run_ranking_t21.py:102` (`SANITY_ORACLE_EDGE = 0.0500`) y `:504`

> **ESTE HALLAZGO SE PUBLICÓ PRIMERO CON TRES RUNNERS Y SEVERIDAD MEDIA, Y LA FASE ADVERSARIAL
> LO REDUJO A UNO CON SEVERIDAD BAJA.** La versión original y el motivo exacto de cada caída
> están en §4, porque el error de método que los produjo es más valioso que el hallazgo.

**El mecanismo, establecido por la tarea 164.** Un refresh mueve los umbrales de sanity de clase
`magnitud` —los que se comparan contra **pp de CAGR/maxDD**—, así que una corrida puede quedar
**INVÁLIDA sin que nada esté roto**. Le pasó al **T37** (un SHIP publicado) y al **T47**.

**Lo que queda en pie.** De los 8 runners con umbral `magnitud`, el **T21 es el único** que no
aparece en ninguna lista de re-corrida post-refresh: no está en los siete del re-anclaje
(`docs/reanchor_t157_2026-09-09.md`), no está en la tabla de la 164
(`docs/control_resorteado_t164_2026-09-10.md` §4), y **no tiene constante de reproducción
anclada**, que es justamente por qué no entró al re-anclaje. Su `SANITY_ORACLE_EDGE` no se
re-midió desde el refresh.

**Y por qué es BAJA y no más — cuatro razones, las cuatro traídas por la fase adversarial:**

1. **Margen de 94×.** El T21 midió oráculo **475,58%** contra baseline **6,48%**, o sea
   **+469 pp contra un umbral de +5,00 pp**. Para invalidarlo, el refresh tendría que haber
   borrado 464 pp de ventaja; el movimiento más grande que registró el re-anclaje fue de
   **3,6 pp**.
2. **El mecanismo que rompió al T37/T47 no le aplica.** Esos dos se cayeron por el **control
   sorteado por índice de barra** (tarea 164), y su margen era de pocos pp. El sanity de
   magnitud del T21 compara **oráculo contra baseline** —dos brazos deterministas— y **no usa**
   `random_stop_filter`.
3. **El mismo umbral pasó post-refresh en el runner hermano.**
   `scripts/run_rank_neutral_t39.py:101` tiene `SANITY_ORACLE_EDGE = 0.0500` con el comentario
   *«umbral de T21 §5.2»*, mismo universo vivo y misma ventana, y quedó **VÁLIDA el 2026-09-10**.
   No es una re-corrida formal del T21, pero mata el *«nadie miró este eje»*.
4. **Nada está cableado sobre el T21.** Su peor caso es **NO-SHIP → sin veredicto**, y las dos
   ramas dejan lo mismo: *«No se toca `engine.py` ni `strategies.py`»*
   (`docs/ranking_t21_2026-08-12.md`). Compárese con el criterio por el que la 164 se puso ALTA:
   *«uno de ellos sostiene una decisión **cableada en el motor**»*. El T21 no tiene esa pata.

**Un ataque que probé y que resultó FALSO, y conviene que quede escrito** para que nadie lo
reutilice: *«el NO-SHIP aguanta igual porque lo decidió otro criterio»*. No se sostiene
mecánicamente — `scripts/run_ranking_t21.py:513-517` hace que el sanity **pise** al criterio: si
cae, no queda «NO-SHIP por C3», queda **CORRIDA INVÁLIDA sin veredicto**. Lo mismo en el T39
(`run_rank_neutral_t39.py:534-535`).

**Y la exposición es puramente documental, no de ejecución.** El sanity se evalúa **en cada
corrida sobre la muestra de esa corrida** (`run_ranking_t21.py:511-517`), así que un sanity viejo
no puede colarse en una corrida nueva. Además *«su validez sobre la muestra de hoy es
desconocida»* es la **semántica declarada de todo veredicto publicado** en este repo desde la
T48 (`docs/harness_window_t48_2026-08-20.md:13-14`: *«ningún veredicto publicado vuelve a
reproducir»*), reforzada en el §6 del re-anclaje y el §5 del doc de la 164.

**¿Por qué no antes? (a) NO EXISTÍA** — el refresh fue el 2026-09-09.

**Acción.** Línea de higiene, no tarea de medición con severidad: re-correr el T21 en modo smoke
la próxima vez que se toque esa familia.

### [M-2] Las re-corridas post-refresh no son trazables: viven en una línea del backlog o en una fila de tabla de otro doc

Severidad: **MEDIA** · Confianza: ALTA · Categoría: [M-ventana]
Ubicación: `docs/BACKLOG.md` (entrada 164), `docs/control_resorteado_t164_2026-09-10.md:62`

**Este hallazgo lo trajo la fase adversarial, y es el que de verdad importa del área.**

**Evidencia.** El 2026-09-10 se re-corrieron **siete** runners sobre el cohorte refrescado y se
declaró su validez. Dónde quedó escrito eso:

- **T37 y T47** → tienen doc propio (`stop_value_rerun_t167`, dentro de `control_resorteado_t164`)
- **T39, T45, T49, T51, T54** → **una sola línea** dentro de la entrada 164 del backlog
- **T34** → **una fila de una tabla** en un doc que se llama por la tarea 164

**Razonamiento.** El resultado de una re-corrida post-refresh es exactamente el dato que la
próxima auditoría —o el próximo pre-registro— necesita para saber si puede apoyarse en un
veredicto. Hoy ese dato no es buscable: no está en el nombre de ningún archivo, no está en el
doc de la tarea re-corrida, y la única forma de encontrarlo es leer entera la entrada de **otra**
tarea del backlog.

**Impacto — demostrado, y el caso soy yo.** Esta misma auditoría midió la cobertura con
`ls docs/*2026-09-09* docs/*2026-09-10*` y por eso **no vio** ni la línea del backlog ni la fila
de la tabla: publicó tres runners como *«nadie los re-chequeó»* cuando **dos de los tres sí lo
habían sido**. La próxima auditoría se va a equivocar igual.

**¿Por qué no antes? (a) NO EXISTÍA** — las re-corridas son del 2026-09-10.

**Acción.** Que una re-corrida post-refresh deje su resultado **en el doc de la tarea
re-corrida** (una nota de corrección fechada, como las que ya usa el repo), no sólo en la entrada
de quien la disparó. Y/o una tabla única *«veredicto → última muestra sobre la que se validó»*.

---

## 4. Hallazgos CORREGIDOS por la fase adversarial

### [M-1] pasó de TRES runners y MEDIA a UNO y BAJA

**Versión publicada primero:** *«T39, T21 y T34 tienen veredicto NO-SHIP cuya validez es
desconocida»*, severidad MEDIA. **Dos de los tres eran falsos:**

- **T39 se cae.** `docs/BACKLOG.md` (entrada 164): *«Las consecuencias sobre veredictos
  publicados, **medidas re-corriendo los siete (2026-09-10)** … **T39, T45 y T49 siguen
  VÁLIDAS**»*. Verificado verbatim. Está repetido en el *Hecho reciente* de la 156.
- **T34 se cae.** `docs/control_resorteado_t164_2026-09-10.md:62`, fila de la tabla de §4:
  `| **T34** | VÁLIDA · NO-SHIP por C6 y C5 | no medido | **VÁLIDA · NO-SHIP por C6** |`.
  Verificado verbatim.

**Y había una inconsistencia interna que la fase adversarial marcó:** el hallazgo **sacó** al T45
de la lista por aparecer en la tabla del re-anclaje, y **dejó** al T39, que aparece en la misma
tabla. Dos criterios distintos para el mismo tipo de evidencia.

### El error de método que los produjo, y es el mismo de todo el día

**Medí la cobertura por NOMBRE DE ARCHIVO** (`ls docs/*2026-09-09* docs/*2026-09-10*`) cuando la
pregunta era sobre **contenido**. Las re-corridas del T39 y del T34 **existen y están
documentadas** — sólo que no en un archivo que se llame como ellas.

Es, exactamente, la forma que esta misma tanda catalogó cuatro veces en el área `guards`: **la
referencia del chequeo no puede ver el objeto que busca**. Cometido por la auditoría que existe
para cazarlo, y encontrado sólo porque un agente independiente lo atacó. Va al §6 consolidado de
`docs/auditoria_guards_2026-09-11.md` como el **cuarto** hueco de método de la tanda.

---

## 5. Barrido limpio en el resto del área

Los otros cuatro ejes del kill-criteria **no produjeron hallazgos**, y eso se publica como
resultado:

- **[M-cantidad]** — el barrido de conteos pinneados en `tests/` y `scripts/` dio sólo literales
  sintéticos (fixtures) y prosa histórica. Los tres conteos vivos (watchlist 127, universo 126,
  `LIVE_WATCHLIST_SIZE` 127) **coinciden entre sí y con la DB**.
- **[M-poblacion]** — no apareció ninguna población nueva derivada de lista donde exista
  predicado. Las cuatro de esta familia (133, 141, 147, 161) están cerradas.
- **[M-inerte]** — AVB sigue siendo el único miembro inerte y `announce_inert_members` lo declara
  en cada corrida.
- **[M-vacio]** — el único caso conocido era el de la tarea **174**, cerrado hoy.

---

## 6. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [M-1] el T21 sin re-correr post-refresh | BAJA | **183** (reducida de alcance) |
| [M-2] las re-corridas post-refresh no son trazables | MEDIA | **189** |

---

## 7. Deuda de método

**Una (c-metodo), y es de esta corrida, no de la anterior:** medir cobertura por **nombre de
archivo** en vez de por contenido. Va consolidada en el §6 de
`docs/auditoria_guards_2026-09-11.md`.

La observación de alcance que ya estaba anotada se mantiene: el área `muestra` no tenía
categoría para *«una operación movió la muestra — ¿qué quedó sin re-verificar?»*. Este
kill-criteria la agregó como **[M-ventana]** y produjo los dos hallazgos del área — pero el
primero salió **mal medido**, así que la categoría sirve y el **instrumento** con que se la
aplica es lo que hay que arreglar.
