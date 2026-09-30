# Auditoría READ-ONLY — área `claims` — 2026-09-30

Primera corrida de la **tanda del 2026-09-30** (las cinco áreas, pedido de Chapa: *«hagamos todas
las auditorías nuevamente»*). Área: **afirmaciones y números que el proyecto usa HOY para decidir y
ya no son ciertos**. Corrida anterior de esta área: `docs/auditoria_claims_2026-09-11.md` (dejó las
tareas 178 a 182, las cinco cerradas).

---

## 1. Kill-criteria — CONGELADO 2026-09-30, antes de abrir ningún archivo

> Los **cinco** kill-criteria de esta tanda se congelaron **juntos, antes** de empezar ninguna
> corrida, y se commitean solos. Lo único mirado antes: los cinco informes del 2026-09-11, el de
> `desvios` del 2026-09-27, los **títulos** de `git log` desde el 2026-09-11 y la cola del backlog.

### 1.1 Por qué ahora

Desde la tanda anterior se cerraron **~60 tareas en 111 commits**. Lo que más mueve texto escrito:

- **`CLAUDE.md` se reescribió en su regla 1** (cortafuegos de red, tareas 209/211/213): es el texto
  que más se lee y el que más afirmaciones en presente hace sobre la suite.
- **La métrica VS SPY se rehízo cuatro veces** (218, 223, 224, 230) y entró un **score mensual**
  (194): todo número de alpha o de VS SPY citado antes del 2026-09-23 se midió con otra fórmula.
- **La segunda opinión** pasó de Finnhub solo a **mayoría de tres** (200, 201, 206), y *Acciones
  manuales* le pide a Chapa prenderla: es un texto que **dirige una acción**.
- **Dividendos a caja** (222) y el desvío re-descrito (221, 233).
- **El pipeline de catalysts perdió la rama RSS** (212) y ganó estados (`degraded`, `unavailable`,
  207/210/217): la skill `catalyst-pipeline` describe ese pipeline.
- **Nuevo veredicto:** T219 NO-SHIP; **T220** declara la reconciliación vivo↔harness *no decidible*.
- **La 196** cambió de destino tres veces (nube → Amazon → Pi de openHABian).

### 1.2 Qué se busca — una frase por sub-categoría

- **[C-numero]** Un número citado como vivo que hoy da otra cosa, o que se midió con una fórmula
  que ya no existe (foco: VS SPY/alpha pre-223, conteos de suite, de universo y de tickers).
- **[C-presente]** Una afirmación **en presente** que dejó de ser verdad, con foco en los textos
  que **dirigen una acción manual** (`CLAUDE.md`, *Acciones manuales*, skills, commands).
- **[C-dosLugares]** El mismo número o símbolo en dos lados con valores distintos.
- **[C-veredicto]** Un veredicto que se cita como vigente y que una re-medición posterior dio
  vuelta o dejó en duda (foco: T219, T220, y todo lo que dependa de la fórmula vieja de VS SPY).
- **[C-fundamento]** Un claim que **sostiene una regla o prioridad** y nadie re-verificó. Se
  publica como *«no se sabe»*, nunca como *«es falso»*, salvo que se mida.
- **[C-simbolo]** Un símbolo, archivo, comando o flag **retirado o renombrado** que un texto
  operativo sigue nombrando (foco: la rama RSS de la 212).

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. Bugs de código (suite, CI, `/code-review`).
2. Los docs de veredicto de tareas **cerradas**, salvo que alguien los cite como vivos.
3. Correr harness o re-medir veredictos: si uno está en duda, va como tarea de medición.
4. Las otras cuatro áreas de la tanda; si un claim toca una, se cita y no se re-reporta.

### 1.4 Qué contaría como "acá no hay nada" — en las DOS direcciones

**Dirección 1 — lo escrito es falso.** Toda afirmación en presente de `CLAUDE.md`, de las skills y
de las tareas abiertas/acciones manuales del backlog coincide con el código, la DB y el
`settings.json` **de hoy**; ningún símbolo retirado aparece en el corpus operativo.

**Dirección 2 — lo verdadero no está escrito.** Todo mecanismo **vivo** agregado desde el
2026-09-11 que cambia lo que el operador tiene que saber (una perilla nueva del `SCHEMA`, un
estado nuevo del harvest, un aislamiento nuevo de la suite) aparece en la referencia que le toca
(`SETTINGS_REFERENCE.md`, la skill del área, `CLAUDE.md`).

Si las dos se cumplen, cierra limpia y se dice. Lo que no se pudo verificar se declara aparte.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Etiquetas (a) / (b) / (c-alcance) / (c-metodo) / (d) de la skill `auditoria`. Sólo (c-metodo) y
(d) son deuda de la skill. **El cruce de cobertura se hace por contenido, no por nombre de archivo.**

### 1.6 Alcance — qué se mira

1. `CLAUDE.md` completo.
2. `docs/BACKLOG.md` — header, *Acciones manuales pendientes*, la cola vigente y las tareas
   **abiertas**; no las cerradas.
3. `.claude/skills/**/*.md` y `.claude/commands/*.md`.
4. `docs/SETTINGS_REFERENCE.md` contra el `SCHEMA` vivo, **en las dos direcciones**.
5. Los docstrings/comentarios con mediciones de los módulos tocados desde el 2026-09-11
   (métricas VS SPY, segunda opinión, dividendos, harvest).

### 1.7 Alcance — qué NO se mira, dicho antes

- Los docs de veredicto de tareas cerradas uno por uno (§1.3.2).
- `ui/` salvo el texto que muestra la métrica VS SPY; `alembic/`; el README.
- `ARCHITECTURE.md` y `DB_SCHEMA.md` **sólo en las secciones que tocan módulos cambiados**
  desde el 2026-09-11; el resto se barrió el 2026-09-11. **Si esta corrida difiere algo, entra al
  backlog como tarea**, no como *«queda para la próxima»*.

---

## 2. Alcance real

**Mirado, por identidad y no por cuenta:** `CLAUDE.md`; las **8** skills
(`auditoria`, `backtest-replay-harness`, `catalyst-pipeline`, `fair-value-feature`,
`finanzias-conventions`, `git-workflow`, `hallazgo-a-backlog`, `testing`) y los **4** commands;
`docs/SETTINGS_REFERENCE.md` contra el `SCHEMA` en las dos direcciones; `docs/DB_SCHEMA.md`
**entero** (no sólo las secciones de módulos cambiados: la primera línea que se leyó ya estaba
caduca, ver [C-1]) contra las tablas y columnas de una copia de la DB; `docs/ARCHITECTURE.md` en las
secciones de dividendos, VS SPY, alertas, segunda opinión y harvest; del backlog, el header, *Acciones
manuales pendientes*, la cola vigente (sólo la 196 abierta) y *Bloqueado*; los docstrings y
comentarios de la segunda opinión (`data/providers.py`, `data/yahoo_finance.py`,
`paper_trading/engine.py:1625-1680`, `config/settings_manager.py:300`).

**Validación del instrumento.** El cruce `SCHEMA` ↔ filas de `SETTINGS_REFERENCE.md` dio 12 claves
sin fila y 1 fila sin spec. Antes de publicarlo se contrastó contra el guard de la 179: las 12 son
toggles de UI fuera del camino de decisión, y la fila `dashboard_refresh_account_id` está marcada
*(sin spec)* a propósito. **No es un hallazgo.** El cruce de `DB_SCHEMA.md` es por substring, así
que puede dar falsos «documentado» pero no falsos «ausente»: lo que marca como ausente, falta.

**NO mirado, y queda declarado:** los docs de veredicto de tareas cerradas; `ui/`; el README;
`ARCHITECTURE.md` fuera de las secciones nombradas. **Esto último no se difiere con dueño porque
la corrida del 2026-09-11 lo leyó entero** y nada de lo que cambió desde entonces vive ahí fuera
de esas secciones.

**Encontrado FUERA del alcance declarado**, y se publica igual porque la regla 6 no distingue: la
sección *Calidad de datos — restricción transversal* del backlog (ver [C-6]).

**Fase adversarial: PROPIA, no independiente.** Ningún hallazgo de esta área llegó a HIGH. Los
ángulos de refutación (commit que lo arregló, test que lo cubre, config que lo explica) van
escritos en cada uno.

---

## 3. Hallazgos

### [C-1] `DB_SCHEMA.md` afirma que la cuenta activa es la 1, «modo kill_only»

Severidad: **MEDIA** · Confianza: ALTA · Categoría: [C-presente]
Ubicación: `docs/DB_SCHEMA.md:11`

**Evidencia.** *«→ **Cuenta activa: "Sim Principal" (id=1)**, modo kill_only.»* Copia de la DB:
`paper_accounts` = `(1, 'Sim Principal', …, is_active=0)`, `(2, 'Sim Segundo', 'auto', …, 10, 1)`.
La línea es del 2026-06-24 (`ba6366e`) y la cuenta 1 está pausada desde el 2026-07-01 y cerrada
desde el 2026-09-13. *kill_only* no es un mecanismo desde la 181.

**Razonamiento.** Es exactamente el caso que la 198 existe para cazar —su propio test de parseo usa
**esa frase, textual**, como ejemplo (`tests/test_corpus_cuenta_y_killonly_t198.py:101`)— y el guard
no la ve porque `DB_SCHEMA.md` no está en su corpus (ver `docs/auditoria_guards_2026-09-30.md`
[G-1]). Aplicando las funciones del propio guard al archivo: `cuentas_que_no_son_la_viva` →
`[('Sim Principal', 1)]`, y `parrafos_killonly_sin_fuente` marca el párrafo.

**Impacto.** `CLAUDE.md` nombra `DB_SCHEMA.md` como el diccionario de la DB. Quien lo abra para
consultar la cuenta viva consulta la fila equivocada — el costo que la 198 escribió para el agente
`verificador`.

**Dirección 2, en el mismo archivo (BAJA):** la tabla `company_info_cache` (desde el 2026-07-08,
`6fccbb7`) no aparece, y `paper_accounts` no lista `description`, `fixed_amount` ni
`last_monthly_rebalance`.

**Verificación.** Se buscó un commit posterior que la corrigiera (`git blame`: ninguno) y otro
guard de corpus que incluya el archivo (72, 137, 198: ninguno).

**¿Por qué no antes? (c-metodo)** — la corrida del 2026-09-11 declara en su §2 haber mirado
`DB_SCHEMA.md` *«(los dos que la corrida del 2026-09-08 difirió explícitamente)»*, y la línea ya
estaba caduca. Y dos tareas que **corrigieron esta misma afirmación** en otros lugares (181 y 198)
no la buscaron en todo el repo sino en su corpus.

**Acción.** Corregir la línea y la dirección 2; y el guard, en la tarea de [G-1].

### [C-2] `finanzias-conventions` sigue dando como «razón medida» el claim del `buy_score` que la T73 mostró insostenible

Severidad: **MEDIA** · Confianza: ALTA · Categoría: [C-fundamento] + [C-dosLugares]
Ubicación: `.claude/skills/finanzias-conventions/SKILL.md:34`

**Evidencia.** *«Razón medida: la auditoría 2026-06-17 mostró que `buy_score` no predice el
forward-return a 5 días.»* La T73 (2026-09-01) re-midió: la muestra original (n=21) sólo detectaba
|r| > 0.58, así que **no podía afirmar eso**; hoy, n=85, r = −0.05, IC95% [−0.26, +0.17]. `CLAUDE.md`
regla 3 y la skill `fair-value-feature:10` ya lo dicen así. Esta línea no se tocó desde que se
escribió (`ba6366e`, 2026-06-24).

**Impacto.** Es la skill que se lee **siempre** al empezar. Afirma como medido un resultado que el
repo ya declaró que la medición no sostenía — y contradice a `CLAUDE.md` sobre el fundamento de una
regla no-negociable.

**Verificación.** `grep "no predice"` en `CLAUDE.md`, `.claude/`, `SETTINGS_REFERENCE.md`,
`ARCHITECTURE.md`: la única afirmación en presente que queda es ésta (la de `auditoria/SKILL.md:102`
la cita como historia).

**¿Por qué no antes? (c-metodo)** — las skills estuvieron en el alcance de las corridas del
2026-09-08 y del 2026-09-11, y la T73 corrigió el claim en dos lugares de tres. Ver §6.

**Acción.** Reescribir la línea con lo que dice `CLAUDE.md` regla 3.

### [C-3] Cinco textos describen la segunda opinión con la regla de DOS fuentes, y uno de ellos dirige la acción manual que Chapa tiene pendiente

Severidad: **MEDIA** · Confianza: ALTA · Categoría: [C-presente]

**Evidencia.** Desde la 206 (2026-09-28) votan Yahoo, Finnhub y Tiingo, el cierre guardado **no
vota**, y `"reference"` se da cuando las dos externas coinciden entre sí contra Yahoo **«avalen o no
el cierre guardado»** (`data/providers.py:395-399`). Siguen describiendo la regla vieja:

1. `docs/SETTINGS_REFERENCE.md:45` — *«consulta una fuente independiente (Finnhub `/quote`) y, si
   respalda a la referencia, rechaza el precio»*; *«si la fuente independiente respalda el cierre
   guardado, el scan usa su precio»*. Tiingo y `TIINGO_API_KEY` no aparecen.
2. `config/settings_manager.py:300-311` (el `doc` del `SettingSpec`) — *«gets a second opinion from
   an independent provider… If the independent source backs the reference, the price is rejected»*.
3. `paper_trading/engine.py:1625-1630` — el bloque que explica la decisión de Chapa: *«la fuente
   independiente respalda el CIERRE GUARDADO → …; no coincide con NINGUNO → …»*.
4. `paper_trading/engine.py:1673-1678` (`_dispute_note`, el texto que Chapa ve en la orden
   pendiente) — *«la fuente independiente dice X»*, en singular.
5. *Acciones manuales pendientes* (la entrada de `price_second_opinion_enabled`): parchea con
   *«donde abajo dice "Finnhub avala", leé "la mayoría avala"»*, y abajo dice *«Si Finnhub avala el
   cierre guardado, usa su precio»*. Con la sustitución queda *«si la mayoría avala el cierre
   guardado»*, que **no** es la regla: la mayoría manda aunque no avale el cierre guardado.

**Impacto.** El caso que la regla de tres agrega —las dos externas coinciden lejos de **las dos**
cosas de Yahoo— no está descrito en ningún texto que Chapa vaya a leer antes de prender el flag, y
el texto de la acción, leído con su propia instrucción de sustitución, lo describe al revés.

**Verificación.** Se buscó una versión actualizada en `ARCHITECTURE.md` y en la skill del área: no
hay mención de la segunda opinión. El texto de la clave `second_opinion` de `deviations_keyed()`
**sí** está al día (lo actualizó la 206).

**¿Por qué no antes? (a) NO EXISTÍA** — la 206 es del 2026-09-28.

**Acción.** Los cinco textos, antes de que se prenda el flag. Va en la misma tarea que
`docs/auditoria_guards_2026-09-30.md` [G-2], que es la otra mitad de *«antes de prenderlo»*.

### [C-4] La skill `catalyst-pipeline` manda a verificar un mecanismo que no existe desde julio

Severidad: **MEDIA** · Confianza: ALTA · Categoría: [C-presente] + [C-dosLugares]
Ubicación: `.claude/skills/catalyst-pipeline/SKILL.md:49` y `:55-57`

**Evidencia.**
1. `:57`: *«`scripts/daily_catalyst_harvest.bat` corre vía Task Scheduler de Windows… confirmar
   periódicamente que corre (verificado funcionando 2026-06-09)»*. `Get-ScheduledTask` no tiene
   ninguna tarea de FinanzIAs; el harvest corre **in-app** desde el 2026-07-12
   (`paper_trading/scheduler.py:761`, `_maybe_hourly_harvest`), y el backlog lo dice (*Bloqueado*,
   T-CAT-5b: *«se removieron las tareas del Task Scheduler»*). La propia skill, en `:29`, habla del
   harvest *«que corre el scheduler cada hora»*.
2. `:49`: *«T-CAT-5b… **BLOQUEADA hasta ~fines jul 2026**»*. El backlog (*Bloqueado*) dice que la
   próxima ventana completa es **Q3, ~mediados de octubre a mediados de noviembre**.

**Impacto.** Es la skill que se carga para *«diagnosticar el harvest diario»*. Manda a mirar el
Task Scheduler —donde no hay nada que mirar— y da por vencido un bloqueo que sigue vigente. La 196
(recolección en la Pi) la va a leer para saber qué hay que mudar.

**¿Por qué no antes? (c-metodo)** — el 2026-09-11 existían **8** skills (`git ls-tree 569fae8`) y
el informe de esa corrida dice que miró *«las 5 skills»*. El alcance declaraba todo
`.claude/skills/**/*.md`; el alcance real se escribió como **conteo**, no como lista, y nadie notó
que no cerraba. Es la categoría B aplicada a la auditoría misma. Ver §6.

**Acción.** Reescribir la sección *Scheduler diario* (in-app, horario, qué mirar en el log) y la
fecha de T-CAT-5b.

### [C-5] La skill del harness no registra la T219 ni la T220 — segunda vez que la cola de lecciones queda atrás

Severidad: **MEDIA-BAJA** · Confianza: ALTA · Categoría: [C-veredicto]
Ubicación: `.claude/skills/backtest-replay-harness/SKILL.md` (última edición 2026-09-13)

**Evidencia.** La skill no menciona la T219 (NO-SHIP, eje de la demora del Gate 2b **cerrado**) ni
la T220 (reconciliación vivo↔harness **no decidible**; dividendos 2,54%/año). Y la T219 dejó una
**trampa de harness** de la clase que la skill registra: *`stop_mult=0.0` no es «stop apagado»* —el
centinela es `_NO_STOP = 1e9` (`analysis/scaleout_replay.py:87`)—; el primer intento de la corrida
salió **decidible y falso** (CAGR del baseline −17,89% contra +8,78%) y sólo lo cazó comparar contra
un número ya publicado (`docs/signal_exit_delay_t219_2026-09-22.md` §0).

**Impacto.** Quien diseñe la próxima corrida de salida no se entera de que el eje ya se cerró, y
puede pisar la misma trampa del centinela.

**¿Por qué no antes? (a) NO EXISTÍA** — las dos son del 2026-09-21/22. Pero es la **misma forma**
que el [C-3] del 2026-09-11 (tarea 180): el arreglo de entonces fue el párrafo, no un mecanismo, y
volvió a pasar a la primera.

**Acción.** Dos entradas en *Lecciones registradas*, y decidir si el cierre de una tarea de harness
con veredicto obliga a tocar la skill (un ítem del checklist de `/ship`, por ejemplo).

### [C-6] Restos menores de texto caducado (BAJA)

Severidad: **BAJA** · Confianza: ALTA · Categoría: [C-presente] / [C-simbolo]

1. `CLAUDE.md:9` — *«aunque hoy no hay ninguno: el marcador existe… y no lo usa ni un test, así que
   esa frase describe un conjunto vacío»*. Desde la 211 (`9c98c6d`, 2026-09-21) hay uno:
   `tests/test_cortafuegos_subproceso_t211.py:93`; es el `1 deselected` que reportan todos los
   cierres desde ese día. **(a)**
2. `CLAUDE.md:9` — *«Son cinco aislamientos autouse: log, DB, fetch de tooltip, Slack y red»*: la
   lista no nombra el del **settings** (`_disable_settings_persistence`, `tests/conftest.py:372`),
   que es el que explica el rojo de la 176. **(c-alcance)**
3. Comentarios que nombran la rama RSS borrada por la 212: `scripts/harvest_catalysts.py:356` y
   `:522`, `data/news_sources.py:461`. **(a)**
4. Backlog, *Calidad de datos — restricción transversal*: *«la watchlist son 52/52 vivos»* (hoy
   127), y en *Backlog / ideas*: *«la watchlist es estática (52 nombres…)»*. **(b)** — fuera del
   alcance de las corridas de claims, que barren header, prioridad y tareas abiertas.
5. `docs/BACKLOG.md:11` (header, **en** el alcance): *«Config viva (Sim Segundo, id=2) … modo
   kill_only. La cuenta 1 ("Sim Principal") está PAUSADA»*. *kill_only* como «modo» es lo que la 181
   retiró, y la cuenta 1 está **cerrada** desde el 2026-09-13. Pasa el guard de la 198 **por su punto
   ciego declarado**: el párrafo menciona `settings.json`, y eso alcanza para el chequeo. **(c-metodo)**
   para la corrida del 2026-09-11 en la mitad de kill_only (el header estaba en su alcance); **(a)**
   en la de «cerrada».

**Acción.** Una pasada de texto.

---

## 4. Barrido limpio en el resto del área — las dos direcciones

**Dirección 1 (lo escrito es falso).** Fuera de [C-1]–[C-6], se verificó contra lo vivo: la cuenta
activa, sus parámetros y la cuenta 1 cerrada en `CLAUDE.md` y `finanzias-conventions` (copia de la
DB); hmm/stacking OFF en el settings y leídos con `default=True` (`analysis/technical.py:733,856`);
`HARNESS_MODEL_TOGGLES` existe; ningún hook de git instalado (`.git/hooks` sólo tiene `.sample`); el
cortafuegos de red corre en la suite; `analysis/valuation.py` sigue sin existir (`fair-value-feature`
lo dice bien).

**Dirección 2 (lo verdadero no está escrito).** Perillas nuevas del `SCHEMA` desde el 2026-09-11:
todas con fila (lo impone el guard de la 179). Estados nuevos del harvest (`degraded`, `unavailable`,
presupuesto): en la skill `catalyst-pipeline`. Lo que **no** está escrito es la regla de tres de la
segunda opinión ([C-3]) y lo que se mudó al scheduler in-app ([C-4]).

---

## 5. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [C-1] `DB_SCHEMA.md` afirma la cuenta 1 y kill_only | MEDIA | **239** (con guards [G-1]) |
| [C-2] `finanzias-conventions` da el claim del `buy_score` como medido | MEDIA | **240** |
| [C-3] cinco textos con la regla de dos fuentes | MEDIA | **241** (con guards [G-2]) |
| [C-4] `catalyst-pipeline`: Task Scheduler y fecha de T-CAT-5b | MEDIA | **240** |
| [C-5] la skill del harness no registra T219/T220 | MEDIA-BAJA | **240** |
| [C-6] restos menores (5 puntos) | BAJA | **247** |

---

## 6. Deuda de método

Tres (c-metodo) en esta área, y los tres tienen la misma raíz: **la corrida mira lo que declara, pero
declara con una forma que no permite verificar que lo miró.**

1. **[C-4] — el alcance real se escribió como conteo.** *«Las 5 skills»* con 8 en disco. Un conteo
   en el §2 no se puede contrastar contra la población; una **lista** sí. Es la categoría B que la
   skill le pide al repo, cometida por la auditoría sobre sí misma.
2. **[C-1] y [C-2] — una corrección vieja no se buscó en todo el repo.** La 73 corrigió el claim
   del `buy_score` en dos lugares de tres; la 181 y la 198 corrigieron la cuenta/kill_only en siete
   y dejaron `DB_SCHEMA.md`. Las corridas posteriores **leyeron** esos archivos y no lo vieron,
   porque leer no es buscar la frase. Lo que faltaba: *para cada claim que una tarea cerrada
   corrigió, buscar la frase original en todo el repo* — no en el corpus de un guard, que es
   justamente lo que tenía el agujero.
