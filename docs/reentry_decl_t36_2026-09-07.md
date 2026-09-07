# Veredicto — Los gates de re-entrada contra los once harness publicados (Tarea 36, REENTRY-DECL)

**Fecha:** 2026-09-07 · **Tarea:** 36 (el *sexto* desvío harness↔engine, ya medido por la T34).
**Enabler:** `live_gates` en `analysis/portfolio_sim.py` (T34, default OFF).
**Precedente directo:** `docs/fill_lookahead_t33_2026-08-16.md` §7 — el mismo ejercicio para el *quinto*
desvío, y de donde sale el criterio que se aplica acá.

Esta tarea **no re-corre ningún veredicto**: aplica un criterio, uno por uno, y decide cuáles piden
re-lectura. Es análisis sobre lo publicado más lectura de código; los números que cita son los de los
docs de cada tarea y de la T33/T39/T45/T47.

---

## VEREDICTO

**De los once, uno pide re-lectura: T20.** Tres ya están re-leídas, uno no tiene veredicto que re-leer,
y los seis restantes no la piden — cada uno con su motivo escrito.

| # | harness | clase (eje de los brazos) | ¿el desvío se cancela? | decisión |
|---|---|---|---|---|
| T7 | SCALE-OUT | salida | **no** (dispara 2.5× más barreras en `C_A4`) | **no re-leer** — margen 5× · y el enabler **no lo cubre** |
| R2 | REGIME-GATE | selección (`hard`/`confirm` filtran) | no aplica | **no re-leer** — su eje quedó superado por T20 |
| T9 | META-LABEL | selección (sólo el **orden**) | no aplica | **no re-leer** el veredicto · sí vale para el *mecanismo* |
| T10 | SIZING | sizing (ni orden ni filtro) | **sí — nivel común exacto** | **no re-leer** |
| **T20** | **REGIME-SCALE** | **sizing** | **sí en forma, no en exposición** | **RE-LEER — prioridad ALTA** |
| T11b | ANOMALY | selección (filtro `(k,m)`) | — | **ya re-leída** — T45, `live_gates=True` |
| T12 | INSIDER | selección (filtro `(C,W)`) | no aplica | **no re-leer** — margen enorme · 10,76 h/corrida |
| T23 | TP-CAL | salida (`tp_mult`) | **sí** (win rate idéntico, n dentro de 5,2%) | **no re-leer** — y ya está muerto por otro lado |
| T13 | ENT1 | híbrido (A entra, B sale) | parcial | **no re-leer** — A falla 6/6, B sin población |
| T21 | RANKING | selección (orden) | — | **ya re-leída** — T39 |
| T26 | STOP-CAL | salida (`stop_mult`) | **no** (es el eje literal de la T34) | **nada que re-leer** — corrida INVÁLIDA, sin veredicto |
| T26b | STOP-PRICE | salida | no | **ya re-leída** — T47, y **movió** un hallazgo |

**Y lo que se encontró de paso pesa más que el conteo:** el brazo que está **cableado y decidiendo en
vivo** (`paper_regime_scale_factor = 0.50`) pasó su propio kill-criteria por **0.01**, y en la única
re-corrida que hubo desde entonces —la de la T33— quedó **por debajo del umbral en las dos patas y en
los dos modos de fill**. Eso no lo destapó el criterio de esta tarea: apareció al ir a buscar el margen
de cada veredicto. Va como **tarea 115**, y es lo que sube a T20 al tope.

---

## 1. El criterio: son dos, no uno, y hay que saber cuál aplica

El desvío es que `simulate_portfolio` sólo rechaza un candidato si el ticker **ya está abierto**,
mientras el engine además bloquea el re-BUY por **Gate 5** (anti-whipsaw: cualquier pérdida cerrada
dentro de 7 d, con `paper_whipsaw_min_loss_pct=0.0`) y **Gate 5b** (anti-churn: ≥3 ciclos en 10 d).
Vale **21,15%–36,36%** de las entradas que el harness toma sin gates (T34 §3).

**Criterio A — el de la T33, para los harness de SALIDA:** *¿los brazos disparan barreras a tasas
distintas?* Si no, el desvío entra como **nivel común** y se cancela en la comparación entre brazos;
si sí, no se cancela y puede mover un signo. Confirmado en dos casos (T34 lo modela por eso; T47 lo
verificó del lado del acierto: ahí los brazos disparaban stop 19,9% vs 13,4% y el desvío **sí** movió).

**Criterio B — el que agregó la T39, para los harness de SELECCIÓN:** el criterio A **no alcanza**. Los
gates no cambian el nivel: cambian **quién entra**, y en un harness cuyo eje es *quién entra* eso es el
eje mismo. Medido: con `touch` + `live_gates`, el ranking vivo de la T21 pasa de estar **debajo de la
banda entera** del azar a caer **adentro** (déficit −3.23 → −1.80 pp), con el sanity de reproducción
devolviendo el 1.97% publicado al dígito. O sea que un veredicto de la serie ya cambió su hallazgo
central al modelar los gates, **y no era uno que el criterio A marcara**.

**Cómo se clasifica, y por qué es un hecho de código y no una opinión:** la clase sale de mirar qué
kwarg difiere entre los brazos del runner. Si los brazos mueven `so_params`/`atr_p`/`tp_mult`/
`stop_mult`/`time_stop` ⇒ **salida**. Si mueven `rank_score` (orden) o `entry_filter` a cero (filtro)
⇒ **selección**. Si sólo mueven `size_weight` o un `entry_filter` que nunca llega a 0 ⇒ **sizing**, que
es una tercera clase que ni la T33 ni la T39 habían nombrado y que resulta ser la más limpia de las
tres (§3).

## 2. El tercer eje, que no estaba escrito en ningún lado: ¿hay un claim vivo?

Los dos criterios de arriba responden *"¿el desvío puede mover el número?"*. Falta la otra mitad, que
es la que decide si vale la pena pagarlo: **¿hay algo colgado de ese número?** Un NO-SHIP que falla por
5× el umbral y que nadie cita no cambia de estado aunque el desvío lo mueva un 20%. Un SHIP cableado
sí, aunque lo mueva un 2%.

Esto no es una excusa para no medir: es exactamente lo que hizo la T33 cuando se salió del enunciado
para re-correr R2 y T10/T20 —*"T20 es la única decisión de esta serie que está cableada y ACTIVA en la
cuenta viva. Si su conclusión colgaba del defecto, eso no es un tema de backlog"*— y es lo que ordena
las once decisiones de abajo. **De los once veredictos, exactamente uno está cableado: T20.**

---

## 3. Los once, uno por uno

### T7 (SCALE-OUT) — el criterio dice "no se cancela", el margen dice que da igual, y el enabler ni siquiera lo cubre

**Clase: salida.** Los brazos mueven `sell_fraction` del flip (1.0 → 0.0) y el `trail_mult` del
remanente.

**Criterio A: NO se cancela.** El mejor brazo, `C_A4` (la señal no vende nada), sale por barrera mucho
más que el baseline: **1280 stops + 996 trails + 782 TP contra 503/360/330** (T33 §3). Los brazos
disparan a tasas muy distintas, así que el desvío no entra como nivel común.

**Y aun así no se re-lee, por dos razones que no se cancelan entre sí:**

1. **El margen es de 5×.** Umbral pre-registrado **+1.5 pts**; el mejor brazo da **+0.31** con el fill
   honesto (+0.52 legacy), y a 5 slots `C_A4` se desploma a **+0.088**. No hay corrección del 20-36%
   que cierre esa brecha.
2. **`live_gates` no existe para el T7.** Es el único de los once que **no llama a
   `simulate_portfolio`**: replaya cada entrada con `replay_cycle`, capital ilimitado, `--notional`
   fijo y sin cartera. El enabler de la T34 vive adentro del simulador de cartera, así que **re-leer el
   T7 con gates pide código nuevo, no una corrida.** Eso no estaba anotado en ningún lado → **tarea
   116**.

**Un detalle que hace al T7 estructuralmente distinto, y conviene que quede escrito:** sus entradas se
arman con `spacing=20` barras por ticker (`build_entries`), contado desde la última entrada aceptada.
Con esa separación **Gate 5b es imposible**: necesita ≥3 ciclos cerrados del mismo ticker dentro de
10 días y ahí cierra como mucho uno cada 20 ruedas. Gate 5 sí puede morder, y muerde **más en los
brazos de tenencia larga** —los que llegan al cap— que son justamente `C_A4` y los `B_trail`. O sea que
el desvío del T7 no sólo no se cancela: **sesga a favor de su propio ganador.** Con un margen de 5×
sigue sin cambiar el veredicto, pero es el orden correcto de la conclusión.

### R2 (REGIME-GATE) — selección, y su eje ya lo re-midió otro harness

**Clase: selección.** `make_entry_filter` devuelve **0.0** en `hard` y en `confirm` (bloquea la entrada
⇒ `n_filtered`), y 0.5 en `half`. Los dos primeros son filtros de entrada; el tercero es sizing.

**Criterio B ⇒ no aplica el A.** Pero no se re-lee, por tres razones:

1. El veredicto es **NO-SHIP** y el déficit de los brazos que filtran es catastrófico: `R2a` **−112.28
   pts** y `R2c` **−124.67 pts** de P/L con el fill honesto (T33 §7). El hallazgo —*apagar entradas
   destruye el compounding*— no lo da vuelta un 21-36% de entradas menos: los gates **también** apagan
   entradas, o sea que empujan al baseline en la dirección del brazo perdedor, no en contra.
2. El único brazo de R2 que sobrevivió (`R2b_half_size`, +15.04 pts) **es sizing, no filtro**, y su
   lectura la reemplazó T10/T20, que barrió el factor completo (0.25/0.50/0.75) sobre el mismo eje.
   Re-leer R2 para decidir sobre `R2b` sería re-leer el harness viejo del brazo cableado teniendo el
   nuevo.
3. La T33 ya lo re-corrió una vez **fuera de su enunciado**, por el mismo motivo (los brazos cambian la
   tasa de disparo), y aguantó.

### T9 (META-LABEL) — el veredicto no, el mecanismo sí

**Clase: selección pura.** Los cuatro brazos difieren **sólo en cómo ordenan** los candidatos que
compiten por el mismo slot el mismo día — el eje idéntico al de la T21.

**Criterio B ⇒ los gates son el eje.** Y sin embargo no se re-lee el veredicto: el umbral era
**+1.5 pp** de CAGR y los tres brazos dan **−2.17, −8.03 y −4.00**. El primario es el que más pierde.
Además el nulo no cuelga sólo de la cartera: **AUC OOS = 0.4980** sobre 47.005 barras etiquetadas y
6 folds, que no depende de la config del simulador en absoluto.

**Lo que sí vale, y es una pregunta distinta:** la T39 usó el mecanismo de la T9 —*el costo de
concentrar el book*— como **hipótesis explicativa** de por qué los gates ensanchan la banda del azar
(*"los gates y el `touch` acortan y espacian los ciclos, y con eso le sacan a cualquier clave de orden
parte de su capacidad de concentrar el book"*). Esa hipótesis está **declarada como no medida** en el
propio doc de la T39. Medirla es una tarea con pre-registro propio, no una re-lectura de la T9.

### T10 (SIZING) y T20 (REGIME-SCALE) — la clase limpia, y el único que hay que re-leer

**Clase: sizing.** Los siete brazos mueven `size_weight` y/o un `entry_filter` en modo `scale`
(0.25/0.50/0.75). **Ninguno cambia el orden ni filtra.**

**Acá el criterio A se puede aplicar con respaldo de código, y da "se cancela" en su forma más fuerte
que en ningún otro harness de la serie:**

- `shares = notional / entry_price` — **fraccionarias, sin redondeo** (`scaleout_replay.py:294`).
- `CostModel` cobra comisión y slippage como **fracción del notional**, sin piso ni mínimo.
- ⇒ el **retorno porcentual** de un ciclo es exactamente invariante al notional.
- El cash **nunca rechaza** una entrada: `notional = min(notional, cash)`, y sólo se rechaza si ≤ 0
  (`portfolio_sim.py:409`). Ese fue justamente el bug que la T10 encontró y corrigió con su brazo
  oráculo.
- `scale` nunca devuelve 0.0, así que `n_filtered` es 0 en los siete brazos.

**Consecuencia:** entradas idénticas, fechas de salida idénticas y `ret` idéntico en los siete brazos.
Los gates bloquearían **exactamente los mismos candidatos** en todos. No es "tasas parecidas": es el
mismo conjunto. **T10 no se re-lee** — su NO-SHIP falla por −3.76 y −4.27 pp contra un umbral de
+1.0 pp, y el desvío es literalmente común.

**Pero T20 no hereda esa tranquilidad, y hay que decir por qué.** Que el conjunto borrado sea el mismo
no quiere decir que la **exposición** al borrado sea la misma: ése es el eje del brazo. Y el mecanismo
de los dos está correlacionado en la misma variable:

> Gate 5 bloquea el re-BUY después de un cierre **en pérdida** reciente. Las pérdidas se **agrupan en
> risk-off**. `R2b` recorta el tamaño **en risk-off**. O sea que el engine, con los gates puestos, ya
> hace en parte lo que el harness le acreditó entero a `R2b`: **bajar la exposición nueva justo cuando
> el mercado va en contra.** Con los gates modelados, el baseline `B0` llegaría a risk-off ya recortado
> por su cuenta, y el aporte incremental de `R2b` debería **encogerse**.

Eso es un **mecanismo, no una medición**, y tiene un contra-argumento honesto: un candidato bloqueado
libera el slot para el siguiente, así que la exposición se redistribuye en vez de caer — salvo cuando
la pila entera de candidatos está bloqueada, que es precisamente lo que pasa en un selloff amplio.
Cuál de los dos efectos gana **no se sabe, y no se puede saber sin correrlo**.

**Por qué eso alcanza para re-leerlo, y con prioridad:** T20 es la **única decisión cableada y activa**
de los once, y su margen es de **0.01**. El kill-criteria pre-registrado era `ΔSharpe ≥ 0.10` **OR**
`ΔCAGR ≥ 1.0 pp`, y el brazo cableado (`R2b_f050`) pasó con **ΔSharpe +0.11 / ΔCAGR +0.59 pp**: una
sola pata, por una centésima. Un efecto que "debería encogerse" contra un margen de una centésima no
es una nota al pie.

**Y al ir a buscar ese margen apareció algo peor, que es un hallazgo aparte (§4).**

### T11b (ANOMALY) — ya re-leída

La T45 corrió el detector con `eval_mode="touch"` + `fill_mode="decision"` + **`live_gates=True`**
(`docs/anom_profile_t45_2026-08-20.md`). Resultado relevante para esta tarea: cambiar los tres modos
—gates incluidos— **deja el perfil de régimen intacto** (`bear_2022` −2.01 → −2.54); lo que da vuelta
el hallazgo publicado de la T11b es la **población** (41→127 tickers, 5→10 slots). O sea que acá los
gates se comportaron como nivel común aunque el harness sea de selección — que es el caso que muestra
que el criterio B es una *condición de cautela*, no una predicción.

### T12 (INSIDER) — selección, brazos muy distintos, y aun así no

**Clase: selección** (la grilla `(C, W)` es un filtro de entrada; el brazo `_senior` además cambia la
fuente). **Y el feed de los gates difiere muchísimo entre brazos: 577 / 306 / 262 / 208 trades**, un
factor de **2,8×**. Los dos criterios apuntan a re-leer.

**No se re-lee, por margen y por costo:** el umbral era **+2 pp** de CAGR sobre la mediana del baseline
aleatorio, y los brazos dan **+0.24%, −0.18%, −0.50% y −3.26%** de CAGR absoluto. El primario queda
debajo de la mediana del azar. Y la corrida cuesta **10,76 h** (T33 §7). Pagar medio día de cómputo
para mover un veredicto que falla por varios múltiplos del umbral no es una decisión difícil.

### T23 (TP-CAL) — el único harness de salida donde el criterio A da "se cancela" con números

**Clase: salida** (`tp_mult` ∈ {4.0, 6.0, off}).

**Criterio A: se cancela.** Los tres brazos de decisión toman **1337 / 1277 / 1268** trades — un
spread de **5,2%**, contra el **76%** de la rejilla de la T34 (4200 vs 2388) — y tienen **el mismo
maxDD y el mismo perfil**: el `%salida TP` cae de 8% a 0% pero el TP cierra **ganadores**, que es
justo lo que Gate 5 **no** mira. El feed diferencial al gate que decide es esencialmente nulo.

**Y encima el veredicto ya está muerto por otro camino:** la T33 lo re-corrió con el fill honesto y
**dio vuelta el hallazgo** (ΔCAGR +1.25 → **−1.50 pp**), con el brazo fallando **su propio sanity** y
el PBO volviendo a 0.873. No hay un número de la T23 sosteniendo nada hoy.

### T13 (ENT1) — híbrido, y los dos brazos fallan por goleada

**Clase: híbrida.** `A_pullback` retrasa la entrada hasta K=5 ruedas esperando un retroceso ⇒ cambia
**quién y cuándo** entra (selección). `B_timestop` agrega un time stop ⇒ salida.

**No se re-lee.** `A_pullback` falla **los 6 criterios**, con ΔCAGR **−3.94 pp** contra un umbral de
+0.30 pp. `B_timestop` cerró **"NO-SHIP — sin población"**: toma 1314 trades contra 1311 del baseline,
o sea que el brazo casi no existe. Modelar los gates no crea población donde no la hay ni cierra
4,24 pp con seis criterios en contra.

### T21 (RANKING) — ya re-leída, y es la que fundó el criterio B

T39, con `touch` + `live_gates`. Su afirmación central quedó **config-dependiente** y con nota de
corrección en `docs/ranking_t21_2026-08-12.md`. Nada que agregar acá.

### T26 (STOP-CAL) — no hay veredicto que re-leer

**Clase: salida**, y su eje es **literalmente** el de la T34 (`stop_mult` 1.0 → off), donde el bloqueo
de Gate 5 va de **36,36% a 21,15%** con gradiente monótono. Por el criterio A, el desvío es lo más
lejos de un nivel común que hay en la serie.

**Y da igual, porque no queda nada en pie que re-leer:** la corrida fue declarada **INVÁLIDA** por
fallar el sanity §5.5 (el oráculo rindió −1.87 pp *por debajo* del baseline), así que **no hay
veredicto**; y sus §1, §3 y §4 quedaron **caducados como evidencia** por la 26b, que encontró el
look-ahead del fill y dio vuelta la monotonía entera. La pregunta que la T26 hacía la contestó la T37,
que **sí** modeló los gates y cerró SHIP.

### T26b (STOP-PRICE) — ya re-leída, y es el caso que probó que el criterio A acierta

T47, con `--live-gates` (`docs/stop_price_redecide_t47_2026-08-19.md`). Los gates **movieron** un
hallazgo: el Δ por régimen se dio vuelta (−0.15/−0.08 → **+0.05/+0.12**) y el IC inferior del C3 pasó
de **+0.03 a −0.23**. Ahí los dos brazos disparaban stop a 19,9% vs 13,4% ⇒ el criterio A había
anticipado que iba a moverse.

---

## 4. Lo que apareció de paso (y va al backlog)

### 4.1 El brazo cableado está por debajo de su propio umbral desde la re-corrida de la T33 → **tarea 115**

El kill-criteria de T20 (`docs/sizing_exposure_prereg_t10_t20_2026-07-22.md` §5, congelado) es
`ΔSharpe ≥ 0.10` **OR** `ΔCAGR ≥ 1.0 pp`. Lo que pasó con `R2b_f050`, que es el factor **cableado y
activo** (`paper_regime_scale_factor = 0.50`):

| corrida | ΔSharpe | ΔCAGR | ¿pasa el kill-criteria? |
|---|--:|--:|---|
| T20 publicada (2026-07-22) | **+0.11** | +0.59 pp | **sí**, por 0.01, en una sola pata |
| T33 re-corrida legacy (2026-08-16) | **+0.09** | +0.44 pp | **no** — falla las dos |
| T33 re-corrida honesta (2026-08-16) | **+0.08** | +0.52 pp | **no** — falla las dos |

La T33 lo reportó como *"veredicto SHIP en las dos corridas, mismo brazo seleccionado, y el factor 0.50
que Chapa eligió cablear sigue mejorando las tres métricas a la vez"*. **Las tres afirmaciones son
ciertas** — y ninguna es el kill-criteria. El brazo que el harness **selecciona** es `R2b_f025`
(+0.15 Sh honesto), que pasa cómodo; el brazo que **decide en vivo** es `f050`, que no. La re-lectura
verificó el veredicto del harness, no la decisión cableada, y son dos objetos distintos.

**Qué NO se afirma acá:** que T20 esté mal. La muestra se movió entre julio y agosto (ventana rodante,
T48), así que la caída de +0.11 a +0.09 puede ser sample y no fill. Eso es exactamente lo que hay que
medir, y por qué es una tarea con pre-registro y no una conclusión de este doc.

### 4.2 El enabler `live_gates` no cubre el T7 → **tarea 116**

`run_scaleout_replay_t7.py` es el único de los once que no usa `simulate_portfolio`. La T34 escribió
*"el enabler ya existe, así que el costo es de análisis, no de código"* y para diez de los once es
cierto. Queda anotado para que el próximo que quiera re-leer el T7 con gates —o escribir un harness
nuevo sobre `replay_cycle`— no descubra el hueco en el medio de una corrida.

### 4.3 Piso de costo operativo (no es un defecto: es estado)

Hoy **ninguno de los once se puede correr** sin pasar antes por `scripts/precompute_pit_signals.py`:
el guard de cobertura de la tarea 86 aborta con **101 de 127 tickers** a los que les falta 1 fecha
contra el cohorte (última barra 2026-09-01). El guard hace exactamente lo que tiene que hacer; lo que
importa para esta tarea es que *"re-leer"* tiene un piso de costo que no es cero, y eso pesa en la
decisión de no re-leer seis veredictos que fallan por múltiplos de su umbral.

---

## 5. Qué se cambió en código

Nada del motor ni de ningún runner. Un solo texto, en `analysis/harness_config.py`:

`deviations()` declaraba el sexto desvío citando **la conclusión de la T34** —*"no es un nivel común y
no se cancela"*— como si valiera para todo harness. **Eso es falso para al menos dos de los once**
(T10/T20 por construcción, T23 por medición) e **insuficiente** para los de selección, donde el
criterio ni siquiera es ése. El banner ahora declara **las dos lecturas y de qué depende cuál aplica**,
en vez de exportar la conclusión de un harness de salida a todos. Mismo cambio en el docstring del
módulo y en el bloque de constantes. Con test.

## 6. Qué NO se hizo, declarado

- **No se re-corrió ningún harness.** El enunciado lo pide así y el análisis no lo necesitó: la clase
  sale del código y los márgenes salen de los docs publicados.
- **No se midió el mecanismo de §3 (T20).** Es la tarea 115, con pre-registro propio, porque toca una
  decisión cableada y activa (regla 2).
- **No se tocó el brazo `live_gates` de ningún runner** ni se agregó el flag a los ocho que no lo
  tienen. Se agrega cuando haya una tarea que lo corra, no antes.
