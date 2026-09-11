---
name: auditoria
description: Auditoría profunda READ-ONLY de FinanzIAs, por área y con kill-criteria declarado antes de mirar. NO busca bugs de código (para eso están la suite, el CI y /code-review) — busca lo que esos no pueden ver: afirmaciones que dejaron de ser ciertas, chequeos que pasan midiendo la cosa equivocada, y estado que se desalinea en silencio. Usar después de mover la muestra (refresh de artefactos, re-precómputo, cambio de universo), antes de congelar un pre-registro que se apoye en números viejos, al cerrar una serie larga de tareas, o cuando un número no cierra en dos lugares.
---

# Auditoría profunda — FinanzIAs

## Qué NO es esto

**No busca errores de código.** De eso se ocupan, y bien, la suite (`/test`), el CI,
`/code-review` y el agente `verificador`. Si el objetivo es *"revisá este diff"* o
*"¿esto rompe algo?"*, **no es esta skill** — usá `/code-review`.

Esto busca lo que esos cuatro **no pueden ver por construcción**: el caso en que el código
está bien y **la conclusión ya no lo está**.

La evidencia de que ese hueco existe es el 2026-09-01. Ese día la suite estaba en **2.394
passed**, el CI en verde y `git status` limpio, y al mismo tiempo:

- el backlog estaba **vaciado** hacía cuatro commits (767 líneas, 69 tareas),
- el `10y` de TSM llevaba **21 ruedas** congelado y el ancla de ventana de la T48 estaba
  **construida sobre él**,
- el store de señales PIT estaba **17 ruedas atrás** de las barras y el precómputo decía
  *"ya completo"*,
- siete runners anclaban su sanity de reproducción a esa ventana contaminada.

Ninguna de esas cuatro cosas es un bug. Las cuatro pasaban todos los controles, porque los
controles verifican **que el código haga lo que dice**, no que lo que dice **siga siendo
verdad**.

## Reglas no negociables

1. **READ-ONLY.** No se modifica código, no se borran archivos, no se refactoriza, no se
   cambian configs ni esquemas, no se reescriben tests. Descubrimiento y remediación son
   dos cosas separadas, y la segunda necesita autorización explícita.
2. **Todo hallazgo lleva evidencia.** Ruta y línea, o el comando que lo reproduce. Sin eso
   no es un hallazgo, es una sospecha — y va marcada como tal.
3. **No se reporta algo sólo porque el código se ve raro.** Hace falta el costo concreto.
4. **Severidad y confianza son ejes distintos**, y se declaran por separado (ver abajo).
5. **Nunca presentar un LOW como si fuera un hecho.**
6. **Un barrido limpio es un resultado.** Si el área no tiene nada, se dice y se cierra. La
   presión por llenar secciones es lo que fabrica hallazgos falsos.
7. **Todo hallazgo accionable termina en `docs/BACKLOG.md`** (regla 6 del proyecto, skill
   `hallazgo-a-backlog`). El doc de auditoría es la **evidencia**; la cola es **una sola**.

## Kill-criteria: se declara ANTES de mirar

Igual que una tarea de trading (regla 2 del proyecto). Antes de abrir un archivo, escribí
en el doc:

- **qué área** se audita y **qué queda explícitamente afuera**;
- **qué se busca**, en una frase por categoría;
- **qué contaría como "acá no hay nada"** — la condición de barrido limpio.

Sin ese tercer punto, la corrida no puede cerrar en limpio sin que alguien sospeche que se
miró poco, y esa presión es exactamente la que inventa hallazgos.

**Una condición de barrido limpio se escribe en las DOS direcciones.** La del 2026-09-08 decía
*«toda afirmación de la doc coincide con el código»* — y eso caza **«lo escrito es falso»** y es
estructuralmente incapaz de cazar **«lo verdadero no está escrito»**. Por esa dirección faltante
sobrevivieron dos hallazgos hasta el 2026-09-11: cuatro perillas vivas de riesgo fuera de
`SETTINGS_REFERENCE.md` —una de ellas con espejo **y** con desvío declarado— y, un nivel más
arriba, cuatro perillas vivas sin espejo `LIVE_*`. Las dos direcciones van escritas, y el informe
reporta **las dos**.

**Si la corrida difiere parte del alcance, ese diferimiento entra al backlog como tarea.** No
alcanza con escribir *«queda para la próxima corrida de esta área»*: eso es un pendiente sin
dueño. El 2026-09-08 se difirieron `ARCHITECTURE.md` y `DB_SCHEMA.md`, y el hallazgo de mayor
severidad de la tanda siguiente estaba ahí — sobrevivió sólo porque alguien leyó el informe
anterior. Es la tarea **97** (*«declarado» no es «cableado»*) aplicada al propio informe.

## Alcance: por área, nunca "exhaustiva"

`/audit <área>`. El repo es de un tamaño en el que **un barrido completo en una pasada no
es alcanzable**, y **una auditoría que declara una exhaustividad que no puede entregar es
ella misma un claim falso** — justo lo que venimos a cazar. Cada corrida declara qué miró y
qué no.

*(Acá había un conteo de archivos y otro de tests. Los dos caducaron —tarea 135— y el
argumento no dependía de ellos: sólo de que el repo sea grande, que lo es cada vez más. Si
querés los de hoy, contalos: `git ls-files '*.py' | wc -l` y `pytest --collect-only -q`.)*

Una corrida de auditoría **es una tarea del backlog**, con el WIP de 1. No se cuelga como
paso extra de otra cosa ni se corre en un hook.

---

## Las cinco categorías

Son de este repo, no genéricas. Cada una salió de un defecto real, y ese defecto está citado
para que se entienda qué forma tiene la cosa que se busca.

### A. Claims caducados

**Qué.** Toda afirmación o número que el proyecto **usa hoy** para decidir, re-verificado
contra el código y los datos **como están ahora**: `CLAUDE.md`, `docs/BACKLOG.md`, las
skills de `.claude/skills/`, los docstrings que citan mediciones, y las constantes de
reproducción de los runners.

**Por qué rinde acá.** El backlog acusaba a `CLAUDE.md` de decir la cuenta 1 como viva
cuando `019de1c` lo había arreglado **tres semanas antes**, y la tarea nunca se actualizó
(tarea 30). `CLAUDE.md` citó durante **tres meses** un *"buy_score no predice el fwd5"*
de junio como hecho vivo; al re-medirlo (tarea 73) resultó que la muestra original (n=21)
**no podía sostener esa afirmación** — sólo detectaba |r| > 0.58. Y el ancla de ventana (hoy `WINDOW_LIVE`) se usó en siete
runners durante semanas estando construida sobre un artefacto congelado.

**Cómo se audita.** Por cada claim: ¿dónde está escrito? ¿sobre qué muestra/ventana/fecha se
midió? ¿esa muestra todavía existe? ¿alguien lo está usando **como si fuera actual**? Ojo
especial con los números que aparecen **en dos lugares**: si difieren, uno de los dos
caducó.

### B. Chequeos por cantidad, ciegos a la muestra

**Qué.** Cualquier invariante verificado **contando** en vez de comparando identidad,
fechas o claves.

**Por qué rinde acá.** Es la familia que produjo **tres** defectos el mismo día:
`len(rows) >= n - warmup` decía *"ya completo"* con 17 fechas faltando (tarea 69, y estaba
**copiado** en el script hermano); la población **cruzada** sobrestimaba **13×** la efectiva
(tarea 62); y `min(starts)..max(ends)` escondía un artefacto congelado entre 505 sanos
(tarea 30). Es el patrón de la 48 (*la ventana, no el largo*) y la 52 (*la población, no la
ventana*) repitiéndose un nivel más abajo cada vez.

**Cómo se audita.** Buscar comparaciones de `len()`, contadores y `>=` sobre tamaños que
pretenden decidir *"esto ya está / esto es la muestra"*. La pregunta siempre es la misma:
**¿esto sigue siendo verdad si la ventana rueda?**

**Y la segunda pregunta, que es la que rinde después de un refresh: «esta operación movió la
muestra — ¿qué quedó sin re-verificar?»** No es la misma que la de arriba: acá no se busca un
chequeo mal escrito sino un **veredicto que nadie volvió a mirar**. El 2026-09-09 se refrescó el
cohorte; el re-anclaje de la 157 declaró las 17 constantes de reproducción en OK y eso era
**cierto y angosto** — la 164 estableció después que **repro OK no implica sanity OK**, y por esa
vía el T37 (un SHIP publicado) y el T47 estaban inválidos con la reproducción **pasando**. La
corrida del 2026-09-11 enumeró los runners con umbral de sanity de clase `magnitud` —el
inventario los deriva en `tests/test_sanity_no_anclado_t164.py`— y encontró veredictos más que
nadie había re-mirado.

El método concreto: listar lo que la operación pudo invalidar, cruzarlo contra la evidencia de
re-corrida posterior a la fecha, y publicar la diferencia como **tarea de medición** — *«no se
sabe»*, nunca *«es falso»*.

**Y ese cruce se hace por CONTENIDO, no por nombre de archivo.** Es el error que la corrida del
2026-09-11 cometió: midió la cobertura con un `ls docs/*<fecha>*` y publicó veredictos como *«no
re-chequeados»* cuando sí lo estaban — la evidencia vivía en una línea del backlog y en una fila
de tabla de un doc que se llama por **otra** tarea. En este repo el backlog es donde vive la
mitad de la evidencia operativa; un archivo que se llame como la tarea es una **convención**, no
una garantía. El glob de nombres no podía ver el objeto que buscaba, que es exactamente la forma
que esta skill cataloga en *«Guards que degradan en silencio»* — cometida por la auditoría.

### C. Desvíos harness↔engine no declarados

**Qué.** ¿Hay un desvío que `analysis/harness_config.deviations()` **no nombra**?

**Por qué rinde acá.** Es el riesgo central del proyecto, y **cada uno** de los declarados
salió de una auditoría previa, **uno por uno**: slots, tamaño de universo, ventana de
`analyze()`, precio de decisión de las barreras (T32), fill de esa barrera (T33), gates de
re-entrada (T34), la ventana **rodante** de los artefactos (T48), la política de salida
(T92), los tres de sizing y gates (T94/95/96) y el screen de universo (T131). Cada uno
estuvo sin declarar hasta que alguien lo miró.

**Sin ordinal, y a propósito (tarea 135).** Esta pregunta decía *«¿hay un **octavo**?»* y
antes *«¿hay un **séptimo**?»*: **el número caducó dos veces**, la primera en 20 minutos, y
la segunda pese a la advertencia que se agregó para evitarlo. El remedio de entonces —pedir
que se contara en el fuente— funcionó (la corrida del 2026-09-08 lo detectó **contando**)
pero no impidió la recurrencia. Así que el ordinal se fue: la pregunta es *«¿falta alguno?»*,
que no caduca.

**Ojo con dos números distintos.** El **ordinal histórico** de un desvío (T48 *es* el
séptimo en el orden en que se descubrieron) y el **conteo vivo de líneas** que `deviations()`
emite hoy son cosas diferentes, y confundirlas fabrica un hallazgo falso — casi pasó en la
corrida del 2026-09-08. Desde la tarea **152** cada desvío tiene una **clave estable**
(`deviations_keyed()`), así que para preguntar *«¿está declarado X?»* se compara la clave y
no se cuenta nada.

**Cómo se audita.** Poner al lado la config del engine (`paper_trading/engine.py`,
`~/.finanzias/settings.json`, la cuenta viva) y la del harness
(`analysis/harness_config.py`, `portfolio_sim`, `replay_cycle`), y buscar dónde difieren sin
que el banner lo diga.

### D. Guards que degradan en silencio

**Qué.** Fail-open sin log, `except` que traga, defaults que enmascaran, avisos que no
escalan.

**Por qué rinde acá.** El guard E5 descartó el precio **bueno** de AVB durante **4 días y
927 WARNINGs** antes de que alguien mirara el log (tarea 63).

**Cómo se audita.** Por cada guard: cuando falla, ¿alguien se entera? ¿el aviso escala si se
repite? Y la pregunta que destapó la 63: **¿el guard puede estar rechazando el dato bueno?**

**Y la que más rinde, porque el 2026-09-11 falló CUATRO veces en un día: ¿el guard puede ver el
defecto que describe?** Los cuatro casos, para reconocer la forma:

| tarea | el guard preguntaba | lo satisfacía |
|---|---|---|
| **173** | `glob in attrs` — *¿`.gitattributes` declara este path?* | una línea que declara `eol=lf`, **lo contrario** del permiso que la excepción suponía |
| **150** | `concepto in REVENUE_CONCEPTS` | la pertenencia, cuando lo que decide es el **orden** (el parser corta en el primero que resuelve) |
| **176** | `comando in doc` | el **frontmatter** `allowed-tools`, no la instrucción del cuerpo |
| **177** | los archivos de universo **reales** del repo | ninguno tiene una coma, así que la población **no contenía el caso** que separa las dos semánticas |

Tres son *comparar el **nombre** en vez del **valor***; la cuarta es *una población real que no
contiene el caso distinguidor*. Las cuatro veces el guard estaba bien intencionado y escrito, a
veces con el comentario correcto al lado — **leerlo no alcanza**.

**La técnica que sí los caza: mutar en el sentido del FALSO POSITIVO.** No *«¿se pone rojo si
rompo lo que chequea?»* —eso suele funcionar— sino **poner la declaración que dice lo contrario y
exigir que se ponga rojo**. Si pasa en verde, está matcheando el nombre. Los cuatro se
encontraron así, ninguno leyéndolo.

**Corolario: cuando un guard declara su propio punto ciego, ese punto ciego ES un hallazgo.** No
es una nota de color ni una muestra de honestidad. El guard de la 130 escribió *«una perilla viva
que no tiene espejo le es invisible»*, las tareas 131 y 132 taparon los dos casos **conocidos**, y
nunca se shipeó el mecanismo que encuentra el próximo — había al menos dos más. Un punto ciego
declarado y no cerrado es una promesa, no un guard. Y peor: ese mismo guard **afirmaba cuántos
casos había**, que es exactamente lo único que no podía saber.

### E. Estado regenerable que nadie regenera

**Qué.** `data/parquet/`, `data/pit_signals/`, artefactos y caches: gitignoreados, sin
contrato de frescura, sin dueño.

**Por qué rinde acá.** La 30 y la 69 taparon dos agujeros de esta familia. Quedan sin mirar
`precompute_pit_risk_score`, `earnings_cache` y los archivos de universo.

**Cómo se audita.** Por cada store: ¿quién lo regenera, cada cuánto, y **qué pasa si no**?
¿Hay algo que compare su frescura contra la de sus pares?

### Las genéricas

Dead code, performance, dependencias, seguridad: **disponibles pero no obligatorias**. Se
piden explícitamente. Para *security* está `security-review`; para el diff, `/code-review`.

**Antes de declarar código muerto**, verificar imports dinámicos, inyección de dependencias,
reflection, decoradores, eventos, callbacks, configuración, hooks de framework, código
generado, jobs agendados y consumidores externos. Sin esa checklist, no es un hallazgo.

---

## Severidad y confianza

**Severidad** — el daño si es cierto:

| | |
|---|---|
| **CRITICAL** | pérdida de datos, resultado de trading incorrecto, corrupción, fallo catastrófico |
| **HIGH** | conducta de negocio incorrecta, decisión tomada sobre un número falso, workflow roto |
| **MEDIUM** | ineficiencia real, duplicación, deuda técnica, hueco de test |
| **LOW** | limpieza menor, naming, documentación |

**Confianza** — cuánto lo sostiene la evidencia:

| | |
|---|---|
| **ALTA** | demostrado por código, test, config, esquema o conducta reproducible |
| **MEDIA** | evidencia fuerte, pero algo dinámico impide la certeza |
| **BAJA** | preocupación plausible, falta evidencia |

Los dos ejes van **siempre juntos**. Un HIGH/BAJA no es un hallazgo: es una pregunta.

## Formato de hallazgo

```
### [A-3] Título en una línea
Severidad: HIGH · Confianza: ALTA · Categoría: claims caducados
Ubicación:  ruta/archivo.py:123
Evidencia:  el comando o el fragmento exacto que lo demuestra
Razonamiento: por qué la evidencia establece el hallazgo
Impacto:    la consecuencia concreta (qué decisión se toma mal)
Verificación: qué se buscó para intentar refutarlo
¿Por qué no antes? (a) / (b) / (c-alcance) / (c-metodo) / (d) — ver la sección propia
Acción:     la corrección más chica que lo resuelve
```

## Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Pedido de Chapa el 2026-09-11, y es lo que convierte una re-corrida en algo más que repetir el
barrido: **si un defecto estaba ahí la vez pasada y la corrida no lo vio, el hueco es de la
skill, no del repo.**

Todo hallazgo lleva un campo `¿Por qué no antes?` con una de estas etiquetas:

| etiqueta | significa | ¿mejora la skill? |
|---|---|---|
| **(a) NO EXISTÍA** | lo introdujo un commit posterior a la corrida anterior | **no** — la skill funcionó |
| **(b) FUERA DE ALCANCE** | estaba, pero la corrida anterior lo excluyó explícitamente | **no**, pero se revisa si la exclusión sigue siendo razonable |
| **(c-alcance)** | estaba y entraba, pero la corrida anterior declaró que barría por muestreo | **no** — es el límite declarado de *«por área, nunca exhaustiva»* |
| **(c-metodo)** | estaba, entraba, la corrida dijo que lo miraba, y se pasó por alto | **SÍ — es el caso que importa** |
| **(d) SE VIO Y SE DESCARTÓ MAL** | apareció y se rechazó con un argumento que no se sostiene | **SÍ, y con prioridad** |

**Sólo (c-metodo) y (d) son deuda de la skill**, y cada uno obliga a contestar *¿qué le faltaba
al método para verlo?*. Esa respuesta va al §6 del informe y, consolidada, a una mejora concreta
de este archivo. Las otras tres etiquetas se escriben igual: distinguir *«el repo se movió»* de
*«no miré bien»* es la mitad del valor.

**El límite, para no inflarlo:** un (c-alcance) **no** es una falla. El repo es grande y la
skill declara que se barre por área; confundirlo con (c-metodo) convierte cada corrida en una
autoflagelación y deja de distinguir lo que sí hay que arreglar.

**Congelá los kill-criteria de TODAS las áreas juntos, antes de empezar la primera.** Es más
estricto que de a una: impide calibrar el criterio de un área con lo que apareció en la anterior,
que es la forma más fácil de fabricar un barrido "limpio". Se hizo así el 2026-09-11 y funcionó.

## Fase adversarial: la hace el `verificador`

Todo hallazgo **HIGH o CRITICAL** pasa por el agente `verificador` con el mandato de
**refutarlo**, no de confirmarlo. Es read-only y ya conoce las convenciones del proyecto.

Lo que tiene que intentar: buscar el caller que falta, la config que lo explica, el test que
ya lo cubre, el camino alternativo, el commit reciente que lo arregló (**pasó**: la 30(a)
estaba arreglada hacía tres semanas). Lo que no sobrevive, **se borra del informe** — no se
degrada a MEDIUM para salvarlo.

**Lo primero que el `verificador` tiene que atacar es el INSTRUMENTO, no la conclusión.** Las dos
correcciones grandes del 2026-09-11 fueron las dos del instrumento: un hallazgo retirado entero
porque la regex con que se midió pedía un carácter de más, y otro reducido de tres casos a uno
porque la cobertura se midió con un glob de **nombres de archivo** cuando la pregunta era sobre
contenido. En los dos el razonamiento era impecable sobre un número que significaba otra cosa.
Mandá el instrumento al principio del prompt del agente, no al final.

**Un hallazgo puede sobrevivir con parte del impacto refutado, y eso se escribe.** El 2026-09-11
el `verificador` confirmó el núcleo de [C-5] y **tumbó dos de sus tres patas de impacto** (*«en el
CI arrancan ON»* — falso, `conftest` redirige el settings; *«hmm y stacking en el camino vivo»* —
falso para stacking). Las dos se **borraron del enunciado** y el hallazgo quedó más chico y más
cierto. Además trajo un impacto **mejor** que el que yo había escrito. Un verificador que sólo
puede decir sí/no desperdicia la pasada.

**Si el `verificador` no puede correr, se dice.** El mismo día el segundo agente **murió por
límite de sesión**; la refutación se hizo a mano con los mismos ángulos —y tumbó **dos de los
cinco** casos del hallazgo—, pero el informe dice explícitamente que esa fase fue **propia y no
independiente**. Una fase adversarial que uno se hace a sí mismo vale menos, y el lector tiene
que poder saberlo.

**Y antes de mandarlo: validá tu propio instrumento.** El 2026-09-11 publiqué internamente un
hallazgo de `claims` —*«faltan flags en `SETTINGS_REFERENCE.md`»*— que era **mi regex**, no el
repo: pedía un `|` pegado al backtick, y las filas que marcó como ausentes **existían** — sólo
formatean el default con un sufijo `(OFF)` adentro de la celda. Peor: comparé la foto histórica
con **otra** regex que la de la corrida, así que la diferencia que me llamó la atención era un
artefacto de comparar **dos instrumentos**. Re-medido con la misma regex en las dos fechas:
**idéntico**. Una auditoría que mide con un instrumento sin
validar produce exactamente lo que viene a cazar — un número limpio que significa otra cosa
([[validar-el-instrumento-antes-del-numero]]). **Los hallazgos retirados se publican con el
motivo**, en su propia sección.

## Salida

**Un doc por corrida**, con la convención que ya usa el repo:
`docs/auditoria_<área>_<fecha>.md`. No se abre un directorio nuevo: `docs/` ya tiene ~20
análisis con este formato y partir el corpus en dos hace que la mitad no se lea.

El doc lleva: kill-criteria declarado (con la fecha en que se congeló), alcance mirado y
**alcance NO mirado**, hallazgos sobrevivientes ordenados por severidad, hallazgos
**rechazados** por el verificador con el motivo, y las limitaciones de la corrida.

**Y después, lo único que importa:** cada hallazgo accionable entra como tarea en
`docs/BACKLOG.md`. Un `15_FINDINGS.md` que vive aparte del backlog es una **segunda cola**,
y una segunda cola se pudre — la tarea 66 shipeó un guard justamente porque la primera se
vació sin que nadie lo notara durante cuatro commits.

## El cierre: mapeo UNO A UNO, no "ya anoté las tareas"

Una corrida **no está cerrada** cuando se escribieron tareas: está cerrada cuando **cada
hallazgo tiene la suya, verificada de a una**. El último paso es escribir en el informe la
tabla `hallazgo → tarea`, con **una fila por hallazgo publicado y ninguna vacía**.

**Pasó en la primera corrida de esta skill** (`docs/auditoria_claims_2026-09-01.md`): se
publicaron **7 hallazgos y 3 tareas**, y **dos hallazgos quedaron sin cola**. Los encontró
Chapa preguntando *"¿tenemos tareas para corregir los problemas?"* — o sea que una auditoría
de **claims caducados** produjo su propio hallazgo sin cola, y no lo detectó ella. De ahí
salen las dos reglas de abajo, que son las que ese cierre no tenía.

### Un hallazgo declarado "parte de" otro igual tiene que estar en el ENUNCIADO de esa tarea

Si el informe dice *"C-7 es parte de R-1"* y la tarea de R-1 no lo menciona, quien la ejecute
**arregla la mitad**. La prueba concreta: arreglar los tres defaults de cuenta sin tocar
`CLAUDE.md:20` deja la instrucción escrita mandándote a correr el job equivocado **a mano**.
Agrupar hallazgos en una tarea está bien; **hacerlos desaparecer del enunciado, no**.

### Un hallazgo que la auditoría NO pudo verificar igual va a la cola si es accionable

Son dos afirmaciones distintas y sólo una necesita medición:

- *"este número es falso"* — **exige medirlo**. Sin la medición no se publica: una auditoría
  no puede afirmar lo que no midió.
- *"nadie re-chequeó en tres meses el número que sostiene una regla no-negociable"* — es un
  hecho **sobre el proceso**, verificable con `git log`, y **sí se publica**.

Lo segundo va como **tarea de medición**, con el límite escrito adelante para que nadie lo
lea mal: *no se afirma que caducó, se dice que **no se sabe***. El caso real es la tarea 73
(el `buy_score` que justifica la regla 3 de `CLAUDE.md`): la corrida lo dejó explícitamente
sin verificar y **por eso mismo** casi se queda afuera de la cola.
