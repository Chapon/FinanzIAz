# Auditoría READ-ONLY — área `claims` — 2026-09-11

Undécima corrida de `/audit`, y **primera de la tanda del 2026-09-11** (las cinco áreas).
Área: **afirmaciones y números que el proyecto usa HOY para decidir y ya no son ciertos**.
Corrida anterior de esta área: `docs/auditoria_claims_2026-09-08.md`.

---

## 1. Kill-criteria — CONGELADO 2026-09-11, antes de abrir ningún archivo

> Los **cinco** kill-criteria de esta tanda se congelaron **juntos y antes** de empezar
> ninguna de las cinco corridas. Es a propósito y es más estricto que congelarlos de a uno:
> impide calibrar el criterio de un área con lo que apareció en la anterior, que es la forma
> más fácil de fabricar un barrido "limpio".

### 1.1 Por qué ahora

Desde la corrida anterior (2026-09-08) se cerraron **~50 tareas en 58 commits** y el
sustrato se movió por debajo de casi todo lo escrito:

- **el cohorte se refrescó el 2026-09-09** durante la operación de la 140, y en esa
  operación **AVB perdió su histórico** de forma irreversible (tarea 156);
- **la watchlist bajó de 128 a 126** y AVB salió del universo, del store y de la watchlist;
- **las 17 constantes de reproducción se re-anclaron** (tarea 157) y la ventana pasó a
  `2016-09-12..2026-09-09`;
- **un veredicto se dio vuelta**: el T37 era SHIP por los nueve criterios y al re-correrlo
  sobre la muestra refrescada dio **NO-SHIP** (tarea 167) — y ese veredicto es el que
  sostiene la política de salida **viva**;
- **la 170 cerró la rejilla de salida** por no decidible;
- **el CI estuvo rojo 35 corridas** y 36 tareas se cerraron declarando *«suite verde»*
  (tarea 175), así que **todo lo que esas 36 tareas afirmaron sobre su propia verificación
  hay que mirarlo con desconfianza**;
- el criterio de *done* pasó de tres a **cuatro** comandos (tarea 176);
- dos símbolos muy citados se **renombraron**: `WINDOW_REFRESH_2026_09_01_*` →
  `WINDOW_LIVE`/`WINDOW_LEGACY` (tarea 163).

Un claim se escribe una vez y se lee cada sesión. Con esa cantidad de sustrato movido, la
pregunta no es *si* hay claims caducados sino **cuántos**.

### 1.2 Qué se busca — una frase por sub-categoría

- **[C-numero]** Un número citado como vivo que se midió sobre una muestra que ya no existe
  —sobre todo la **pre-refresh del 2026-09-09**— o que hoy da otra cosa.
- **[C-presente]** Una afirmación **en presente** que dejó de ser verdad, con foco en los
  textos que **dirigen una acción manual** o que describen la cuenta/universo vivos.
- **[C-dosLugares]** El mismo número o símbolo escrito en dos lados con valores distintos:
  uno de los dos caducó y hay que decir cuál.
- **[C-veredicto]** Un veredicto publicado que se sigue citando como vigente y que la
  re-medición del refresh dio vuelta, o cuya validez quedó en duda.
- **[C-fundamento]** Un claim que **sostiene una regla o una prioridad** y nadie
  re-verificó. Se publica como *«no se sabe»*, nunca como *«es falso»*, salvo que se mida.
- **[C-simbolo]** Un símbolo renombrado o retirado que algún texto **operativo** sigue
  nombrando (el corpus de la tarea 72).

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. **Bugs de código** — suite, CI, `/code-review`.
2. **Los docs de veredicto de tareas CERRADAS**, salvo que alguien los cite como vivos. Un
   doc de cierre es historia y tiene derecho a decir lo que era verdad ese día. Esta
   distinción es la que hizo viable la tarea 163.
3. **Correr harness o re-medir veredictos publicados.** Si un veredicto está en duda, se
   publica como tarea de medición, no se mide acá.
4. **Las otras cuatro áreas de esta tanda** — muestra, desvíos, guards y estado — cada una
   con su doc. Si un claim toca una de ellas, se cita y no se re-reporta.

### 1.4 Qué contaría como "acá no hay nada" — condición de barrido limpio

La corrida cierra **limpia** si, habiendo mirado los seis sustratos de §1.5, se verifica que:

- los números vivos de `CLAUDE.md` (cuenta activa, flags, universo, criterio de done)
  coinciden con la DB y el `settings.json` reales;
- ningún símbolo retirado por la 163 aparece en el corpus operativo;
- los conteos de la watchlist/universo citados en textos operativos coinciden con la DB;
- ningún doc operativo cita un veredicto que la 167 o la 170 dieron vuelta;
- y **se dice explícitamente qué no se pudo verificar**.

Un barrido limpio es un resultado válido y se publica como tal.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

> Pedido de Chapa, incorporado **antes** de abrir ningún archivo. Es la parte que convierte
> esta tanda en algo más que repetir el barrido: si un defecto estaba ahí el 2026-09-08 y la
> corrida de entonces no lo vio, **el hueco es de la skill**, no del repo.

Todo hallazgo lleva un campo **`¿Por qué no antes?`** con una de estas cuatro etiquetas:

| etiqueta | significa | ¿mejora la skill? |
|---|---|---|
| **(a) NO EXISTÍA** | el defecto lo introdujo un commit posterior a la corrida anterior | **no** — la skill funcionó |
| **(b) FUERA DE ALCANCE** | estaba, pero la corrida anterior lo había excluido explícitamente | **no**, pero se revisa si la exclusión sigue siendo razonable |
| **(c) EN ALCANCE Y NO SE VIO** | estaba, entraba en el alcance declarado, y se pasó por alto | **SÍ — es el caso que importa** |
| **(d) SE VIO Y SE DESCARTÓ MAL** | apareció y se rechazó con un argumento que no se sostiene | **SÍ, y con prioridad** |

Las etiquetas **(c)** y **(d)** obligan a responder una segunda pregunta: *¿qué le faltaba
al método para verlo?* — y esa respuesta va al §5 de cada doc y, consolidada, a una mejora
concreta de `.claude/skills/auditoria/SKILL.md`.

**El límite, dicho para no inflarlo:** un (c) no siempre significa que la skill esté mal.
Puede ser que el área sea grande y la corrida anterior declarara honestamente que no barría
todo (§"Alcance: por área, nunca exhaustiva"). Se distingue en el informe: **(c-alcance)**
si la corrida anterior dijo que no lo miraba, **(c-metodo)** si dijo que sí y no lo vio.
Sólo **(c-metodo)** y **(d)** son deuda de la skill.

### 1.6 Alcance — qué se mira

1. `CLAUDE.md` completo.
2. `docs/BACKLOG.md` — sólo el **header**, las secciones de prioridad y las tareas
   **abiertas**; no las cerradas.
3. `.claude/skills/**/*.md` y `.claude/commands/*.md`.
4. `docs/SETTINGS_REFERENCE.md`, `docs/ARCHITECTURE.md`, `docs/DB_SCHEMA.md`.
5. Las constantes de reproducción y los banners de `analysis/harness_config.py`.
6. Los docstrings que citan mediciones en `paper_trading/`, `analysis/` y `scripts/run_*`.

### 1.7 Alcance — qué NO se mira, dicho antes

- Los ~20 docs de análisis y veredicto de `docs/` uno por uno (son historia; §1.3.2).
- `ui/`, `alembic/`, `tests/` (salvo que un test **sea** la fuente de un claim operativo).
- El README y los docs de diseño de sprints viejos.

---

## 2. Hallazgos

_(se completa al correr)_

## 5. Deuda de método — qué le faltaba a la corrida anterior

_(se completa al correr; sólo entra lo etiquetado (c-metodo) o (d))_
