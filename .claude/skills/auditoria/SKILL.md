---
name: auditoria
description: Auditoría profunda READ-ONLY de FinanzIAs, por área y con kill-criteria declarado antes de mirar. NO busca bugs de código (para eso están la suite, el CI y /code-review) — busca lo que esos no pueden ver: afirmaciones que dejaron de ser ciertas, chequeos que pasan midiendo la cosa equivocada, estado que se desalinea en silencio, y —desde la tarea 260— lo que la pantalla muestra, la cuenta registra, el log repite o la fuente dice sin que sea cierto. Usar después de mover la muestra (refresh de artefactos, re-precómputo, cambio de universo), antes de congelar un pre-registro que se apoye en números viejos, al cerrar una serie larga de tareas, cuando un número no cierra en dos lugares, o cuando la pantalla, la cuenta o el log muestran algo que no cierra.
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

**El «alcance real» del informe se escribe como LISTA, nunca como conteo (tanda 2026-09-30).**
La corrida del 2026-09-11 escribió que miró *«las 5 skills»* con **8** en disco, y la skill que no
leyó mandaba a verificar un Task Scheduler que no existe desde julio. Un conteo no se puede
contrastar contra la población; una lista sí. Es la categoría B aplicada a la auditoría misma.

**Una exclusión de alcance lleva su motivo, y el motivo se re-verifica en la corrida siguiente.**
El pipeline de catalysts se excluyó de `guards` dos veces con razón —no tenía guards propios— y la
razón caducó el 2026-09-15 (tarea 207) sin que nadie la re-mirara. Copiar la exclusión del informe
anterior no es declararla.

Una corrida de auditoría **es una tarea del backlog**, con el WIP de 1. No se cuelga como
paso extra de otra cosa ni se corre en un hook.

---

## Las categorías

Son de este repo, no genéricas. Cada una salió de un defecto real, y ese defecto está citado
para que se entienda qué forma tiene la cosa que se busca.

**A–E miran el análisis; F–H miran el producto en uso (tarea 260, 2026-10-02); I mira el contenido del dato de entrada (tarea 271); J y K, rendimiento y dependencias (tarea 274); L, el censo del log (tarea 287).** Hasta esa
fecha las cinco primeras eran todas, y todas preguntan si una **conclusión** sigue siendo cierta.
Ninguna preguntaba si lo que Chapa **ve en la pantalla, tiene en la cuenta o recibe del log** es
cierto, y los informes lo declaraban: *«NO mirado: los guards de la UI»*, *«NO mirado: `run_scan`
entero»*. La evidencia de que ese hueco costaba es de quién encontró qué: la 22, 218, 227, 254 y
255 (pantalla), la 93, 220 y 221 (cuentas) y la 148, 197 y 234 (operación) las encontró **Chapa
mirando la app o el log**, no una corrida. F–H siguen siendo READ-ONLY y siguen sin ser
`/code-review`: no buscan el bug del diff, buscan **lo que el usuario toma por cierto y no lo es**.

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

**Y las correcciones viejas se BUSCAN en todo el repo, no se leen (tanda 2026-09-30).** Por cada
claim que una tarea cerrada corrigió, buscar la **frase original** con `grep` en todo el repo — no
en el corpus de un guard, que es justamente lo que tenía el agujero. Así sobrevivieron dos: la 73
corrigió el *«`buy_score` no predice el fwd5»* en dos lugares de tres (quedó
`finanzias-conventions`), y la 181 y la 198 corrigieron *«cuenta activa id=1, kill_only»* en siete
y quedó `DB_SCHEMA.md`. Las corridas posteriores **leyeron** los dos archivos y no lo vieron:
leer no es buscar.

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

**La severidad de un desvío de SUSTRATO se mide en el veredicto, no en el archivo.** Que un proceso
reescriba un artefacto que lee un runner es el mecanismo; el daño es cuánto cambia lo que el runner
mide. El job que reescribe `SPY__10y` entró como HIGH y el `verificador` lo bajó a BAJA midiendo: el
régimen no cambia en ningún día hasta ~18 meses de desalineación (tanda 2026-09-30b, tarea 251).

**Y los textos de lo que SÍ está declarado se contrastan contra el valor vivo, no sólo contra
el código (tarea 233).** La corrida del 2026-09-11 leyó cada texto de desvío contra el código
y escribió *«ninguno afirma algo que el código contradiga»*, que era cierto y no alcanzaba: el
de `universe_screen` decía que el screen dropea *«por ADV$/fragilidad fundamental»*, y el
código **tiene** la pata de ADV$, pero con `paper_universe_min_adv_dollars = 0.0` está
**apagada**. Dos reglas:

- Toda afirmación de un desvío sobre **lo que hace el motor** se contrasta contra el valor
  vivo de **cada** perilla que la gobierna —las sub-perillas incluidas—, no sólo contra el
  master switch ni contra el código.
- Todo número que el texto presenta como **estado actual** (*«0 de 62 BUY vivas»*) lleva
  **fecha** o se **deriva**. Sin fecha, un conteo que caducó no se distingue de uno vigente.
- **Todo número de magnitud declara su MARCO** —slots, universo, ventana— y se contrasta contra
  el marco por default de los runners que lo imprimen (tanda 2026-09-30). El de `regime_scale`
  tenía fuente, tarea y fecha, pasaba las dos reglas de arriba, y era de 5 slots/41 tickers: en el
  marco de la cuenta el CAGR da el signo contrario. Es la lección de la 43 y la 119, que el método
  de esta área no tenía escrita.
- **Toda afirmación de FRECUENCIA del motor vivo se contrasta contra el REGISTRO de lo que corrió,
  no contra la perilla que la configura** (tarea 261). El desvío `barrier_eval` decía que el vivo
  evalúa las barreras *«cada ~15 min, más cerca de touch»*, y la perilla lo confirmaba; los
  snapshots de la cuenta 2 mostraban 22 días hábiles sin ningún scan entre julio y octubre. La
  perilla dice cada cuánto **intenta**; `paper_equity_snapshots` dice cada cuánto **corrió**.

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

**Y la mutación vale también para los guards de PROCESO** (`scripts/check_*.py`), no sólo para los
tests: construí el caso que lo debería disparar y fijate si la población del guard **puede
contenerlo**. El chequeo *«DB desde no-Windows»* de `check_repo_health.py` busca `finanzias.db` entre
los archivos staged, y la DB está gitignoreada: no se disparó nunca, desde el 2026-06-24, y una
corrida que lo leyó no lo vio (tanda 2026-09-30b, tarea 250).

**El CI es un guard de proceso y entra acá (tarea 274).** `.github/workflows/` decide qué se
considera verde fuera de la máquina de Chapa. Las preguntas son las de esta categoría aplicadas al
workflow: ¿un job con `continue-on-error` o *best-effort* puede tapar un rojo real?; ¿el CI corre
lo mismo que el *done* de `CLAUDE.md` (los cuatro comandos), o algo menos?; ¿la versión de Python
y de las dependencias del CI es la de la máquina donde corre la app? La 176 existe porque el CI
estuvo rojo 35 corridas sin que el proceso se enterara.

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

**Y por cada OPERACIÓN MANUAL que una tarea cerrada dejó y tiene que repetirse** —archivar,
compactar, rotar a mano—: ¿quién la dispara? *«Quién lo regenera»* es la pregunta de un cache, y
una operación periódica no se regenera: se **olvida**. Así se pasó la cinta intradía de
`price_cache` (tarea 81): se archivó una vez, a mano, y la corrida del 2026-09-11 la tenía en su
alcance con nueve días de filas sin archivar.

### F. Pantalla: el número que se muestra no es el que el rótulo dice

**Qué.** Cada número, color y selección por defecto de `ui/` que Chapa lee para decidir, trazado
hasta su fuente y contrastado contra la DB viva.

**Por qué rinde acá.** Es el área con más defectos encontrados **a mano**. La línea SPY de la
curva se congelaba en silencio y corrompía el *VS SPY* (22). El panel de Métricas leía una tabla
que la 0011 había vaciado, así que *VS SPY*, MAE/MFE y el fwd-5d estaban **apagados** sin decirlo
(218). Una alerta disparada quedaba disparada para siempre, y el panel mostraba *«por encima»* y
*«por debajo»* del mismo ticker, las dos en rojo (227). Métricas y Paper abrían en la cuenta
**cerrada** y su score se leía como el de la viva (254). El impacto de Noticias daba ±0.36 para
toda noticia de resultados o FDA, porque `rank_news` se llamaba sin la tabla de reacción (255).
Ninguno era un bug de código: los cinco hacían lo que el código decía.

**Cómo se audita.** Por cada número visible: **¿de dónde sale?** (función, tabla y columna), y
**¿qué muestra cuando la fuente está vacía, vieja o en la cuenta equivocada?** Un vacío que se
pinta como `0`, `—` o el último valor conocido, sin decir que lo es, es el hallazgo típico. Tres
preguntas más, una por defecto citado: **¿el rótulo promete más de lo que mide?** (*«impacto
esperado»* sobre un prior constante); **¿la selección por defecto es la viva?** (cuenta, ventana,
benchmark); **¿el estado se re-arma solo o queda trabado?** Para contrastar, abrí la DB en solo
lectura (`file:finanzias.db?mode=ro`) y calculá el número a mano; no alcanza con leer el widget.

**Queda afuera:** estética, layout y performance de la GUI, salvo que oculten un número.

### G. Cuentas: la cartera viola una regla que declara, o no cuadra

**Qué.** Los invariantes de la contabilidad del motor vivo (`paper_trading/`): que órdenes,
posiciones, caja, dividendos y snapshots cuenten la misma historia, y que la cuenta respete sus
propios límites (`max_positions`, caja no negativa, cuenta cerrada que nadie toca).

**Por qué rinde acá.** La cuenta 2 llegó a **12 posiciones con `max_positions=10`**, en nueve
episodios y con hasta $51.093 de exposición sobre $50.000 de capital, porque los slots se
contaban descontando ventas que los gates podían frenar (93). El motor no acreditaba dividendos
mientras el harness corría sobre series total-return (221/222). Y nadie había corrido el harness
sobre la ventana de la cuenta para ver si su CAGR se parecía al vivo (220). Las tres eran
**reglas**, no sumas: la contabilidad aritmética cuadraba.

**Cómo se audita.** Dos pasadas. **(1) El cuadre**, por cuenta: `initial_capital` + ventas −
compras (a `fill_price × fill_shares`) − `commission_paid` + `paper_dividend_credits.cash` contra
`paper_accounts.cash`, y las acciones netas por ticker contra `paper_positions`. **Ojo con el
instrumento:** el slippage ya va **dentro** del `fill_price`, así que restar además
`slippage_cost` descuadra una cuenta sana. Medido así el 2026-10-02, las cuentas 1 y 2 cerraron
**al centavo**, y **no hay ningún chequeo que lo haga solo**: `reconcile_account` sólo expira
órdenes pendientes. **(2) Las reglas**: por cada límite que la cuenta declara, buscar en
`paper_orders` y `paper_equity_snapshots` un momento en que se haya violado, y por cada flujo de
plata que el harness modela (dividendos, splits, costos), verificar que el motor también lo haga.

**Y la cartera REAL entra igual (tarea 271).** `portfolios`, `positions` y `transactions` (lo
que se importa por CSV y lo que `ui/paper/real_portfolio.py` cruza desde una orden paper) son
plata de Chapa, y desde la 264 son lo que muestra Home. Las mismas dos pasadas: que
`positions.quantity` cuadre con la suma de sus `transactions` y que `avg_buy_price` salga de
ellas; y que el cruce paper→real no duplique ni pierda una transacción. Medido el 2026-10-02
cuadraba (cada posición con su compra), pero ninguna corrida lo había mirado.

**Queda afuera:** si las decisiones fueron **buenas**. Eso es trading y va por backtest con
kill-criteria (regla 2), no por auditoría.

### H. Operación: lo que corre de fondo falla, se repite o no corre

**Qué.** El log de producción (`~/.finanzias/finanzias.log*`, `catalyst_harvest.log`), el
scheduler y los jobs de fondo, el harvest, y los canales de aviso (Slack).

**Por qué rinde acá.** Un rebuild de surprise que fallaba reintentaba **cada 60 segundos sin
límite**: 389 fallos seguidos en el log vivo (197). `get_current_price` bajaba el precio bien y
devolvía `None` porque no había podido **escribir** el cache (234). Cada corrida de la suite le
mandaba mensajes reales a Slack (148). Y desde que se abrió la 196 el reloj de T-CAT-5b perdió
días hábiles porque con la app cerrada no se recolecta, y nada lo medía (245). Todos estaban en el
log o en el canal; nadie los leía con una pregunta.

**Cómo se audita.** Sobre una ventana declarada del log: **(1)** agrupar por mensaje normalizado
(sin tickers ni números) y ordenar por frecuencia; un mensaje que se repite sin cambiar es un
retry sin tope o un aviso que no escala. **(2)** Por cada job declarado en el scheduler, ¿hay
evidencia de que corrió en cada día hábil de la ventana? Los huecos de `paper_equity_snapshots`
son la vara para el scan. **(3)** Por cada `except` que loguea y sigue en un camino de fondo,
¿el resultado que entrega después es el dato bueno, uno viejo o un vacío? Es la pregunta de D,
pero mirando lo que **pasó** en el log y no lo que dice el código. **(4)** Slack: lo que se manda,
¿llega una vez, llega a quien tiene que llegar, y lo que **debería** avisar avisa?

**Backups, restore y migraciones entran acá (tarea 271).** No son estado regenerable —un backup es
justo lo que **no** se puede regenerar— y por eso `estado` no los mira. Las preguntas: ¿el backup
diario se toma, y se puede **restaurar** (no sólo existe)? El botón de Settings llama
`restore_database` (`database/backup.py`) y **reemplaza la DB viva**: ¿qué pasa si el backup
elegido es de un esquema anterior, o si la app tiene la DB abierta? ¿La rotación de `backups/`
(la 187) corre? ¿Una migración de `alembic` que falla a medio camino deja la DB en un estado que
`init_db` reconoce?

**Queda afuera:** la infraestructura nueva de la 196 (Lambda/DynamoDB), hasta que exista.

### I. Datos: el contenido del dato de entrada no dice lo que se cree

**Qué.** Lo que el sistema toma por cierto de sus fuentes, mirado por su **contenido**: la
clasificación de noticias (tipo, polaridad e intensidad que devuelve qwen), el consenso de
analistas (`analyst_estimate_snapshots`), los fundamentals (facts de EDGAR) y el universo.

**Por qué rinde acá.** Las otras áreas preguntan si el dato está **fresco** (E) o en **escala**
(D); ninguna pregunta si **dice la verdad**. La polaridad de qwen viene agrupada en cuatro valores
y la escala de siete niveles muestra en la práctica −2, 0, +2 y +3 (259). Cuatro nombres del
universo vivo llegaban al screen sin facts y el screen los dejaba pasar (149). Yahoo le aplicó a
AVB un split fantasma de 2,793 a un frame y no a los otros (63). Las tres se vieron de pasada o
por una pregunta, no por una corrida.

**Cómo se audita.** Por cada fuente: **(1)** la **distribución**: un campo con pocos valores
distintos, o con uno que domina, es un dato degenerado (la forma de la 259); **(2)** la
**cobertura por ticker del universo vivo**: un hueco que no avisa es la forma de la 149;
**(3)** una **muestra contra la fuente primaria**: unas filas elegidas al azar, contrastadas a
mano contra el texto de la noticia, el filing o el sitio del proveedor; **(4)** la
**consistencia entre fuentes** cuando hay más de una para el mismo dato.

**Queda afuera:** si el dato **predice** algo. Eso es una medición con pre-registro (la 255, la
258), no una auditoría.

### J. Rendimiento: algo tarda tanto que cambia lo que pasa

**Qué.** Tiempos que alteran la conducta, no la comodidad: locks de SQLite que frenan una
escritura, consultas sin índice en el camino caliente, jobs sin techo de tiempo, scans que tardan
más que su intervalo.

**Por qué rinde acá.** `check_alerts` pedía precios con una transacción de escritura abierta y
retenía el lock 30 s por ticker sin cache: 163 s medidos, y el scan tampoco podía escribir (237).
Había índices declarados en los models que no existían en la DB, y el lookup más caliente de la
GUI era ~1.800× más lento (74). Con la red caída el harvest tardaba 16× más y nada lo cortaba (204).

**Cómo se audita.** **(1)** Del log: la duración de cada scan contra `paper_scan_interval_minutes`
(un scan que tarda más que su intervalo se saltea el siguiente), y los `database is locked`.
**(2)** De la DB: `EXPLAIN QUERY PLAN` de las consultas que corren en cada scan y en cada
refresco de pantalla; un `SCAN TABLE` sobre una tabla que crece es el hallazgo. **(3)** Por cada
job de fondo: ¿tiene techo de tiempo?, ¿qué pasa si no termina antes del próximo disparo?

**Queda afuera:** la optimización que no cambia conducta. Que algo tarde 2 s en vez de 1 no es un
hallazgo si nada depende de eso.

### K. Dependencias: lo que corre no es lo que se declara

**Qué.** `requirements.txt`, `requirements-dev.txt` y `requirements.lock` contra lo que de verdad
importa el código y lo que está instalado en los entornos que lo corren (la Anaconda de Chapa, el
`.venv`, el CI).

**Por qué rinde acá.** `feedparser` no era dependencia de nada, así que `--sources rss` recolectaba
cero y se reportaba como `skipped`, que por diseño no alarma (212). La Anaconda y el `.venv` son
entornos separados y divergen: al `.venv` le faltan `platformdirs` y un parser de HTML, y da otro
conteo de tests. El stack está pineado a propósito (numpy<2, scikit-learn<1.8, PyQt6<6.8) porque
subirlo rompe, y eso es una decisión que caduca.

**Cómo se audita.** **(1)** Cada `import` de terceros del código contra lo declarado (con imports
locales y opcionales incluidos: el caso de la 212 era un import opcional). **(2)** Lo declarado
contra lo instalado en cada entorno, versión por versión. **(3)** Los pines: ¿el motivo de cada
uno sigue siendo cierto?, ¿hay avisos de seguridad sobre la versión pineada?

**Queda afuera:** actualizar. Esta área dice qué diverge; subir versiones es la tarea propia de
*Ideas* («Actualizar dependencias»), con su riesgo medido.

### L. Logs: el censo de cada error que la app registra

**Qué.** El log de producción mirado **como población**: cada firma distinta de WARNING, ERROR,
CRITICAL y traceback de una ventana declarada, clasificada una por una.

**Por qué rinde acá, y por qué no alcanza con H.** `operacion` (H) mira el log buscando lo que
**se repite** y lo que **no corrió**; un error que aparece tres veces en un mes, o una excepción
en un camino poco usado, no se repite lo suficiente para verse. La 234 (el precio bueno
descartado porque no se pudo escribir el cache) estaba en el log como un puñado de `Error
fetching price`; la 263 ni siquiera llegaba al log. Pedido de Chapa (2026-10-02, tarea 287):
*«una auditoría de logs, para buscar errores que no estemos viendo»*.

**Cómo se audita.** **(1)** Normalizar cada línea WARNING+ (tickers → `TK`, números → `N`,
rutas y URLs fuera) y agrupar por `(nivel, módulo, mensaje)`; por cada traceback, la firma es
`(tipo de excepción, último frame del repo)`. **(2)** Cada firma se clasifica en **una** de tres:
*conocida* (tiene tarea, abierta o cerrada: citarla), *explicada* (benigna, con el motivo escrito
y verificado contra el código), o *desconocida*. **(3)** Toda *desconocida* se investiga hasta su
causa o se publica como tarea de medición. **(4)** Las firmas que **dejaron** de aparecer después
del cierre de su tarea confirman el arreglo; las que siguen apareciendo después del cierre son un
hallazgo (el arreglo no arregló). **(5)** Lo que no aparece y debería: un `except` que loguea a
`debug` en un camino de fondo es invisible en producción (el log corre en INFO).

**Desde la 288 cada línea dice su origen:** las de la app (`main.py`) no llevan marca y las de
cualquier otro proceso terminan en `  [proceso: <script>]` (los jobs que lanza la app, los runners,
las pruebas a mano). El censo separa las firmas por origen **antes** de clasificar: una firma que
sólo aparece con `[proceso: python -c]` es de una prueba, no de la app. La primera corrida tuvo que
deducirlo del traceback.

**Barrido limpio:** ninguna firma queda sin clasificar, y ninguna *conocida* sigue apareciendo
después del cierre de su tarea.

**Queda afuera:** el contenido de los INFO, salvo que delaten una falla.

### Las genéricas

Dead code y seguridad: **disponibles pero no obligatorias**. Se piden explícitamente. Para
*security* está `security-review`; para el diff, `/code-review`. **Performance y dependencias
dejaron de ser genéricas** (tarea 274): son las categorías J y K.

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

**Tres formas del mismo error, de la tanda del 2026-10-02 (tarea 275):**

- **Reproducí con la configuración REAL, no con la por defecto.** El hallazgo de la venta total
  de la cartera real se reprodujo con una sesión `autoflush=True` y daba *«se borran la compra y
  la venta»*; la app usa `autoflush=False` y la venta **sobrevive huérfana**. El `verificador`
  lo vio leyendo `sessionmaker(...)`. Antes de reproducir, copiá la configuración de la app
  (sesión, `PRAGMA`s, journal mode, settings), no la de la librería.
- **Un barrido que puede cortar en silencio no es un barrido.** `git log -p | grep` paró en
  *«Binary file matches»* a mitad de la historia y devolvía una lista corta que parecía
  completa. Con `-a` (y `--text` en `git log`) se repitió.
- **El cuarto comando del done no se corre con el repo en movimiento.** Escribir informes
  mientras corre `run_suite_sin_estado_vivo.py` dispara el guard de la 236 (`rc=3`, *«la suite
  dejó cambios en el repo»*): no es un fallo de la suite, pero esa corrida no vale como done.

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
