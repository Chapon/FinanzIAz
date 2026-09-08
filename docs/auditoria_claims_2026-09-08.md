# Auditoría READ-ONLY — área `claims` — 2026-09-08

Séptima corrida de `/audit`. Área: **afirmaciones y números que el proyecto usa HOY para
decidir y ya no son ciertos**. Corrida anterior de esta área:
`docs/auditoria_claims_2026-09-01.md` (dejó las tareas 70, 71 y 72).

---

## 1. Kill-criteria — CONGELADO 2026-09-08, antes de abrir ningún archivo

> Escrito **antes** de mirar `CLAUDE.md`, las skills, `SETTINGS_REFERENCE.md` o los
> docstrings. No se toca después.

### 1.1 Por qué ahora

Desde la corrida anterior (2026-09-01) se cerraron **~40 tareas** y se movió el sustrato
debajo de casi todo lo que estaba escrito: el store PIT se recomputó (117), el cohorte se
reparó (111), el `10y` de MNST se re-bajó (113), la DB se compactó, y el **2026-09-07 Chapa
cambió tres cosas a mano** — `paper_regime_scale_factor` a 0.25, `paper_universe_screen_enabled`
a ON y `allocation_mode` de la cuenta 1. Un claim se escribe una vez y se lee cada sesión.

La corrida de `desvios` de hoy ya encontró **dos números caducados** en las skills (tarea 135)
sin buscarlos, lo que sugiere que la superficie no está barrida.

### 1.2 Qué se busca — una frase por sub-categoría

- **[C-numero]** Un número citado como vivo que se midió sobre una muestra que ya no existe,
  o que hoy da otra cosa.
- **[C-presente]** Una afirmación **en presente** (*«hoy X vale Y»*, *«el flag está en Z»*)
  que dejó de ser verdad, **con foco en los textos que dirigen una acción manual**.
- **[C-dosLugares]** El mismo número escrito en dos lados con valores distintos: uno de los
  dos caducó y hay que decir cuál.
- **[C-fundamento]** Un claim que **sostiene una regla o una prioridad** y nadie re-verificó
  — se publica como *«no se sabe»*, nunca como *«es falso»*, salvo que se mida.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. **Bugs de código** (suite, CI, `/code-review`).
2. **Los desvíos harness↔engine**, ya barridos hoy en `docs/auditoria_desvios_2026-09-08.md`.
   No se re-reportan; si un claim los toca, se cita la tarea que ya existe.
3. **Correr harness o re-medir veredictos publicados.**
4. **Los números de docs de tareas ya CERRADAS**, salvo que alguien los siga citando como
   vivos. Un doc de cierre es historia y tiene derecho a decir lo que era verdad ese día.

### 1.4 Qué contaría como "acá no hay nada" — condición de barrido limpio

Cierra **limpia** si: (1) toda afirmación en presente de `CLAUDE.md`, de las cinco skills, de
los cuatro commands y de la sección *Acciones manuales pendientes* del backlog coincide con el
código, el `settings.json` y la DB de hoy; (2) ningún número aparece con dos valores distintos
en dos lugares; y (3) los claims que sostienen las reglas no-negociables tienen fecha de
re-verificación posterior al último movimiento de su muestra.

### 1.5 Alcance que se va a mirar

`CLAUDE.md`, `.claude/skills/*/SKILL.md` (5), `.claude/commands/*.md` (4),
`.claude/agents/*.md`, `docs/SETTINGS_REFERENCE.md`, la sección *Acciones manuales pendientes*
y los blockquotes de priorización de `docs/BACKLOG.md`, y los docstrings de
`analysis/harness_config.py` y `config/settings_manager.py` que citan mediciones.

---

## 2. Alcance real

**Mirado:** `CLAUDE.md` (41 líneas, y su historia completa de 7 commits), las 5 skills de
`.claude/skills/`, los 4 commands, los 2 agents, `docs/SETTINGS_REFERENCE.md`, la sección
*Acciones manuales pendientes* de `docs/BACKLOG.md`, los docstrings de
`config/settings_manager.py` que citan valores vivos, y la DB viva (`mode=ro`) para contrastar.

**NO mirado, y queda declarado:**

1. **Los docs de tareas cerradas** (`docs/*_t*.md`, ~40 archivos). Un doc de cierre es
   historia y tiene derecho a decir lo que era verdad ese día. Sólo se miran si alguien los
   cita como vivos.
2. **`docs/ARCHITECTURE.md` y `docs/DB_SCHEMA.md`** — no entraron; quedan para la próxima
   corrida de esta área.
3. **Los desvíos harness↔engine**, barridos hoy en `docs/auditoria_desvios_2026-09-08.md`.
4. **El claim que sostiene la regla 3** (`corr(buy_score, fwd5) = −0.05`, n=85, re-medido el
   2026-09-01 por la tarea 73) **se revisó y NO es un hallazgo.** Su muestra se movió después
   —la 117 recomputó el store PIT y la 111 reparó el cohorte, las dos el 2026-09-04— así que
   el `n` de hoy probablemente no sea 85. Pero la regla dice explícitamente que **no depende de
   ningún coeficiente**, y el texto de `CLAUDE.md` ya declara el límite de la muestra (*«sólo
   descarta |r| > 0.30»*). **Nada decide distinto si el número cambió**, así que reportarlo
   sería inflar el informe.

**Sin fase adversarial, y se dice por qué:** la skill manda al `verificador` los hallazgos
**HIGH o CRITICAL**, y ninguno de los tres publicados llega a HIGH. Los tres son mecánicos —
bytes, `git log` y una consulta a la DB—, no interpretaciones.

---

## 3. Hallazgos

### [C-1] `CLAUDE.md` está truncado a mitad de palabra, y lo está desde su primer commit

Severidad: **MEDIA** · Confianza: **ALTA** · Categoría: el archivo de instrucciones no termina
Ubicación: `CLAUDE.md:41` (última línea, 5.042 bytes)

**Evidencia.** El archivo termina en `- \`docs/DB_SCHEMA.md\` — dicc`, **a mitad de la palabra
«diccionario» y sin salto de línea final** (verificado con `od -c`). Recorriendo la historia
del blob:

| commit | bytes | termina en |
|---|---|---|
| `ba6366e` (el primero) | 2.438 | `— dicc` |
| `019de1c` | 2.641 | `— dicc` |
| `d31aaf2` | 3.749 | `— dicc` |
| `35245a8` | 3.944 | `— dicc` |
| `b965208` | 4.352 | `— dicc` |
| `f0df87a` (HEAD) | 5.042 | `— dicc` |

**Razonamiento.** No hubo un commit que lo truncara: **nació así** y creció monotónicamente.
Los seis commits posteriores lo editaron sin notarlo porque **todos tocan el principio** —
reglas, mapa, comandos— y el corte está en el último renglón.

**Impacto.** Es el archivo que se carga como instrucciones del proyecto **en cada sesión**. La
última entrada de *Documentación de referencia* es ilegible, y no hay forma de saber si había
entradas después: el corte es anterior a la historia registrada. El daño está acotado a esa
lista, pero **el hecho de que haya sobrevivido siete commits dice que nadie leyó el archivo
hasta el final**, que es un problema aparte en un archivo cuyo propósito es ser leído entero.

**Verificación (lo que se intentó).** Se buscó un commit que lo cortara (`git log` sobre el
blob, tamaños uno por uno): no existe. Se descartó que fuera un problema de lectura: `wc -c`,
`od -c` y `git cat-file -s` coinciden en 5.042.

**Acción mínima.** Completar la línea y agregar el newline final. Y —esto es lo que evita la
recurrencia— un chequeo de que `CLAUDE.md` termina en línea completa, que es barato y
mecánico.

---

### [C-2] La skill del harness dice «hoy: el factor 0.50» y el factor vivo es 0.25 — y esa frase dirige el diseño del próximo pre-registro

Severidad: **MEDIA** · Confianza: **ALTA** · Categoría: claim en presente caducado
Ubicación: `.claude/skills/backtest-replay-harness/SKILL.md:110`

**Evidencia.** El texto dice: *«**Preferir el mecanismo ya validado.** Si existe un overlay
shipeado (**hoy: el factor 0.50 de T20**), el candidato primario es el que lo reusa»*. Escrito
el 2026-08-19 (`8ac5459`). El valor vivo es **0.25** desde el 2026-09-07 (tarea 115), y el
`SettingSpec` lo dice bien: *«0.50 was the previous value and no longer meets the T20
kill-criteria»*.

**Razonamiento.** No es una cita histórica: la palabra es **«hoy»** y la frase **manda a
reusar** ese mecanismo al escribir el próximo pre-registro. Un candidato primario diseñado
sobre un factor que ya no corre nace desalineado con la cuenta viva.

**Y prueba algo más, que es la parte accionable.** El paso 4 de `/ship` existe justamente para
barrer el corpus operativo cuando se mueve una constante, y su propio texto registra que el
barrido del 2026-09-07 *«cazó el `SettingSpec`, la referencia y el espejo de `harness_config`, y
**dejó pasar** la nota de verificación de R2b»*. **Dejó pasar dos, no una:** ésta también. O
sea que el barrido a ojo falló en **2 de 5** lugares, y sólo se documentó uno.

**Acción mínima.** Corregir la línea, y —lo que importa— hacer mecánica la parte mecánica del
barrido: un flag vivo citado con su valor en el corpus se puede chequear contra el
`SettingSpec` sin leer nada a ojo.

---

### [C-3] Una acción manual afirma una edad que envejece sola: dice «30–41 ruedas» y hoy son 49–60

Severidad: **BAJA-MEDIA** · Confianza: **ALTA** · Categoría: claim que caduca por construcción
Ubicación: `docs/BACKLOG.md:780` (sección *Acciones manuales pendientes*)

**Evidencia.** La nota dice que la cuenta 1 tiene *«sus 5 slots ocupados por posiciones
abiertas entre el 16/06 y el 01/07 (SBUX, LRCX, MO, KO, CL; **30–41 ruedas**) que nadie
evalúa»*. Contra la DB viva hoy (`mode=ro`, `np.busday_count` al 2026-09-08):

| ticker | abierta | ruedas hábiles hoy |
|---|---|---|
| SBUX | 2026-06-16 | **60** |
| LRCX | 2026-06-25 | **53** |
| MO | 2026-06-25 | **53** |
| KO | 2026-06-29 | **51** |
| CL | 2026-07-01 | **49** |

Los tickers y las fechas son correctos; **sólo la edad caducó**, y caduca de nuevo mañana.

**Razonamiento.** Es una clase de claim distinta de las otras dos: no se rompió porque alguien
cambió algo, **se rompe sola con el paso del tiempo**. Y está en la sección que el paso 4 de
`/ship` marca como la más peligrosa, porque *«afirman en presente y son las que Chapa ejecuta a
mano»*.

**Impacto.** Bajo hoy —el número no dirige ninguna acción— pero la nota ya trae las **fechas**,
que no caducan, así que el conteo de ruedas es **redundante y decadente a la vez**.

**Acción mínima.** Borrar el rango de ruedas y dejar las fechas. Actualizarlo sería volver a
plantar el mismo defecto con otro número. Y barrer si hay más de esta clase (se buscó
`N-M ruedas`, `hace N días`, `lleva N`: los otros dos hits son fechas fijas, no edades).

---

### [C-4] Un tercer número caducado en la skill `auditoria` — se acumula a la tarea 135, no abre tarea nueva

Severidad: **BAJA** · Confianza: **ALTA**
Ubicación: `.claude/skills/auditoria/SKILL.md:60`

Dice *«El repo tiene ~330 archivos y **2.396 tests**»*. Hoy: **373** archivos `.py` trackeados
y **2.807** tests (2.804 passed + 3 skipped). El argumento que sostiene —*«un barrido completo
en una pasada no es alcanzable»*— **no cambia**; si acaso se refuerza.

Es el mismo defecto exacto que la tarea **135** (números escritos a mano en las skills donde el
fuente puede contarlos), en el **mismo archivo**, así que se acumula ahí en vez de abrir una
tarea nueva. **El enunciado de la 135 se actualizó para nombrarlo** — un hallazgo agrupado que
no aparece en el enunciado de su tarea es un hallazgo perdido.

---

## 4. Lo que se revisó y NO dio hallazgo

Un barrido limpio parcial también es un resultado, y decir qué se miró sin encontrar nada es lo
que permite que la próxima corrida no lo repita:

- **Los hechos de la cuenta viva en `CLAUDE.md` y en `finanzias-conventions`** (id=2, `auto`,
  `equal_weight`, 10 slots, cuenta 1 pausada): **coinciden con la DB**.
- **`hmm/stacking OFF` por kill_only**: coincide con el settings vivo (los dos en `False`).
- **Los 127 tickers del universo de harness** citados en la skill: coinciden con el archivo.
- **`WINDOW_REFRESH_2026_09_01_LIVE`** citada como el ancla de hoy: existe y es la vigente.
- **Los dos docstrings de `settings_manager.py` que afirman un valor vivo**
  (`paper_vol_penalty_coef` y `paper_regime_scale_factor`): **correctos y fechados** — la 115 y
  la 124 los actualizaron.
- **`Suite: 855 passed`** en `git-workflow`: es un **ejemplo de formato**, no un claim. No es
  hallazgo.
- **`docs/SETTINGS_REFERENCE.md` documentando defaults y no valores vivos**: es lo que su
  propio encabezado declara (*«Flags definidos en `config/settings_manager.py`»*), así que no
  es un claim falso. Que el estado efectivo no esté documentado en ningún lado ya está en el
  backlog como idea sin priorizar, y esta corrida no la promueve.

---

## 5. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [C-1] `CLAUDE.md` truncado desde el primer commit | MEDIA | **136** CLAUDEMD-TRUNCADO |
| [C-2] «hoy: el factor 0.50» y el vivo es 0.25 | MEDIA | **137** CORPUS-FACTOR-VIEJO |
| [C-3] «30–41 ruedas» que hoy son 49–60 | BAJA-MEDIA | **138** CLAIMS-QUE-ENVEJECEN |
| [C-4] «2.396 tests» y hoy son 2.807 | BAJA | **135** (acumulado; enunciado actualizado) |

Cuatro hallazgos, cuatro filas, ninguna vacía. El agrupado ([C-4]) **está nombrado en el
enunciado de la 135**, verificado leyendo la tarea y no de memoria.
