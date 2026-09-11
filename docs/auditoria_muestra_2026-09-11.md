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

### [M-1] El refresh del 2026-09-09 dejó tres veredictos NO-SHIP con validez DESCONOCIDA

Severidad: **MEDIA** · Confianza: ALTA *(sobre el hecho de proceso, no sobre los veredictos)*
Categoría: [M-ventana]
Ubicación: `scripts/run_rank_neutral_t39.py`, `scripts/run_ranking_t21.py`,
`scripts/run_stop_loosen_t34.py` · inventario en `tests/test_sanity_no_anclado_t164.py`

**El mecanismo no lo invento yo, lo estableció la tarea 164.** Un refresh del cohorte mueve los
umbrales de sanity de clase `magnitud` —los que se comparan contra **pp de CAGR/maxDD**—, así
que con una muestra de menos alpha el instrumento pierde resolución y una corrida se declara
**INVÁLIDA sin que nada esté roto**. Ya pasó: el **T37** (un SHIP publicado, el que sostiene la
política de salida viva) y el **T47** quedaron inválidos por esa vía.

**Y el re-anclaje de la 157 dio una tranquilidad que no cubría este eje.** Declaró las 17
constantes de reproducción en OK, y eso era *cierto y angosto*: la 164 estableció que **repro OK
no implica sanity OK** — T37 y T47 tenían la reproducción pasando y el sanity roto.

**Evidencia.** El `INVENTARIO` clasifica **12 constantes de clase `magnitud` en 8 runners**.
Desde el refresh, `ls docs/*2026-09-09* docs/*2026-09-10* docs/*2026-09-11*` sólo muestra
re-corridas para **T37** (`stop_value_rerun_t167`), **T26b** (`t26b_sanity_t168`), **T47**
(dentro de `control_resorteado_t164`) y el **T170**, que es nuevo. Para T38, T39, T21, T26 y T34
**no hay ningún doc**.

**Refutación propia, y funcionó a medias — dos de los cinco se caen:**

- **T38** cerró como *«CORRIDA INVÁLIDA por sanity §5.4 → sin veredicto»* (`docs/BACKLOG.md:1306`)
- **T26** cerró como *«CORRIDA INVÁLIDA por sanity → NO-SHIP»* (`docs/BACKLOG.md:2920`)

En los dos **no hay veredicto vivo que proteger**, así que salen del hallazgo. Quedan **tres**:
T39, T21 y T34.

**La otra refutación que probé y NO funcionó:** ¿corren sobre el cohorte legacy congelado, que
el refresh no tocó? **No.** Los cinco defaultean a `LIVE_UNIVERSE_FILE`
(`run_anom_regime_t38.py:253`, `run_rank_neutral_t39.py:355`, `run_ranking_t21.py:371`,
`run_stop_cal_replay_t26.py:378`, `run_stop_loosen_t34.py:394`).

**Impacto, y acotado a propósito.** Los tres supervivientes son **NO-SHIP**, no SHIP — o sea que
el daño es menor que el del T37: lo que puede haber caducado es **la razón para no shipear**, no
una política viva. Pero dos de los tres se citan en los blockquotes de priorización del backlog
como el motivo de que la cola esté ordenada como está (la 39 sobre el ranking, la 34 sobre el
múltiplo del stop).

**Lo que este hallazgo NO afirma.** No digo que esos veredictos sean falsos. Digo que **su
validez es desconocida**, que nadie la miró, y que el mecanismo por el que T37 y T47 se cayeron
aplica a ellos por construcción. Va como **tarea de medición**, con el límite escrito adelante —
la forma que la skill prescribe para la tarea 73.

**Agravante de proceso.** El checklist de refresh que la 164 shipeó (en `scripts/refresh_cohort.py`)
se agregó el **2026-09-11**, o sea **después** del refresh que lo motivó. Ese refresh nunca pasó
por él, y nada lo corrió retroactivamente.

**¿Por qué no antes? (a) NO EXISTÍA** — el refresh fue el 2026-09-09, posterior a la corrida del
2026-09-08.

**Acción.** Re-correr los tres y mirar el sanity; si alguno no reproduce, declararlo como se
hizo con el T37. Sin cambiar ningún umbral para que pase.

**Nota sobre la fase adversarial:** este hallazgo se mandó al agente `verificador`, que **murió
por límite de sesión** antes de devolver nada. La refutación de arriba la hice yo con los mismos
ángulos que le había pedido, y **dos de los cinco runners se cayeron**. Queda dicho que la fase
adversarial de este hallazgo fue **propia y no independiente**.

---

## 4. Barrido limpio en el resto del área

Los otros cuatro ejes del kill-criteria **no produjeron hallazgos**, y eso se publica como
resultado:

- **[M-cantidad]** — el barrido de conteos pinneados en `tests/` y `scripts/` dio sólo literales
  sintéticos (fixtures) y prosa histórica. Los tres conteos vivos (watchlist 127, universo 126,
  `LIVE_WATCHLIST_SIZE` 127) **coinciden entre sí y con la DB**.
- **[M-poblacion]** — no apareció ninguna población nueva derivada de lista donde exista
  predicado. Las cuatro de esta familia (133, 141, 147, 161) están cerradas, y la 161 de hoy
  convirtió la última en predicado AST.
- **[M-inerte]** — AVB sigue siendo el único miembro inerte y `announce_inert_members` lo declara
  en cada corrida.
- **[M-vacio]** — el único caso conocido era el de la tarea **174**, cerrado hoy.

---

## 5. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [M-1] tres NO-SHIP con validez desconocida post-refresh | MEDIA | **183** |

---

## 6. Deuda de método

**Ninguna (c-metodo) ni (d) en esta área.** El único hallazgo es **(a)**: el defecto nació
después de la corrida anterior. La skill funcionó acá.

Lo que sí queda anotado para §6 de `docs/auditoria_guards_2026-09-11.md` es una observación de
**alcance**, no de método: el área `muestra` no tiene hoy ninguna categoría para *«una operación
movió la muestra — ¿qué quedó sin re-verificar?»*. Este kill-criteria la agregó como
**[M-ventana]** y fue la que produjo el único hallazgo del área, así que conviene que quede en
la skill en vez de depender de que alguien la re-invente.
