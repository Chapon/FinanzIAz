# Auditoría READ-ONLY — área `muestra` — 2026-09-08

Décima corrida de `/audit`, y la última de las cinco áreas en esta tanda. Área: **invariantes
verificados CONTANDO en vez de comparando identidad, fechas o claves**. Corrida anterior de
esta área: `docs/auditoria_muestra_2026-09-02.md` (dejó las tareas 86 a 89).

---

## 1. Kill-criteria — CONGELADO 2026-09-08, antes de abrir ningún archivo

> Escrito **antes** de abrir un módulo. No se toca después.

### 1.1 Por qué ahora

Es el área que produjo **tres defectos el mismo día** (69, 62 y 30) y su patrón —*la ventana,
no el largo* (48); *la población, no la ventana* (52); *el conjunto, no el conteo* (87/89)— se
repite un nivel más abajo cada vez. Desde la corrida anterior se movió el sustrato entero
(111, 113, 117) y se agregaron chequeos nuevos (109, 110, 119, 123).

Y las cuatro corridas de hoy ya rozaron el área sin buscarla: la de `guards` encontró que
`stale_artifacts` compara contra **la moda de su propia población** (tarea **140**), que es la
misma familia vista desde el otro lado.

### 1.2 Qué se busca — una frase por sub-categoría

- **[M-largo]** Un `len(...) >= N` que decide *«esto ya está completo»* sin mirar **qué**
  falta.
- **[M-ventana]** Un chequeo que sigue siendo verdad hoy y deja de serlo cuando la ventana
  rueda, sin que nada lo declare.
- **[M-conjunto]** Una comparación de **tamaños** donde lo que importa es el **conjunto** —
  dos poblaciones del mismo tamaño y distinta composición pasan como iguales.
- **[M-umbral]** Un mínimo de muestra (`n >= k`) cuyo `k` se fijó una vez y nadie re-verificó
  contra la distribución real.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. **Lo ya encontrado hoy**: la referencia modal de `stale_artifacts` (tarea **140**), el
   predicado del guard del store (**141**) y las poblaciones-lista (**128**, **133**). Tienen
   cola; re-reportarlos sería inflar.
2. **Bugs de código** (suite, CI, `/code-review`).
3. **Correr harness o re-medir veredictos.**
4. **Los `len()` de código de UI y de parsing** que no deciden si una muestra es válida.

### 1.4 Qué contaría como "acá no hay nada" — condición de barrido limpio

Cierra **limpia** si: (1) todo chequeo que decide *«la muestra está completa»* compara
**claves o fechas**, no cantidades; (2) toda comparación de poblaciones compara **composición**
o declara por escrito que sólo mira el tamaño; y (3) todo mínimo de muestra tiene escrito de
dónde salió su umbral.

### 1.5 Alcance que se va a mirar

`analysis/harness_config.py`, `analysis/portfolio_sim.py`, `analysis/exit_replay.py`,
`analysis/surprise_score.py`, `analysis/ml_signals.py`, `scripts/precompute_pit_*.py`,
`scripts/build_surprise_profiles.py` y los guards de muestra de `tests/`.

---

## 2. Cómo se barrió

Por **AST**, no por grep: se buscaron todas las `ast.Compare` con un operador de orden
(`<`, `<=`, `>`, `>=`) donde alguno de los lados es un `len(...)`, un contador o un `n_*`,
sobre los ocho módulos del alcance. Salieron **21**, y se leyeron una por una.

De esas 21: seis son **índices de array** (`d_idx >= len(bars)`), tres son **reglas de negocio**
(edad mínima de tenencia, Gate 2b), tres son el `MIN_QUARTERS` de los perfiles de sorpresas —
que ya cerró la tarea **126**—, una es un **puntos suspensivos de display**
(`len(tickers) > 5`), y una está **declarada por escrito** como comparación de tamaños
(`cfg.n_tickers < LIVE_WATCHLIST_SIZE`, con el caveat que le escribió la tarea 89). Quedan las
que se examinaron a fondo abajo.

---

## 3. Lo que se revisó y NO dio hallazgo

Va primero, porque en esta corrida es la mayor parte del resultado y porque **un descarte con
motivo escrito es lo que evita que la próxima corrida lo vuelva a levantar**.

- **`ArtifactPopulation.same_universe_as` compara el CONJUNTO, y el orden es el correcto.**
  Chequea `universe_file`, después `n_tickers`, y después las huellas cuando **las dos** las
  declaran. El fallback al conteo existe sólo para poblaciones sin huella, y está documentado.
  La tarea 100 ya arregló el orden que la 87 había dejado mal (la huella devolvía temprano y
  volvía inalcanzable el conteo). **Los dos ejes viven, y la razón de cada uno está escrita.**
- **Los umbrales de `mixed_scale_frames` (tarea 113) tienen origen medido y separación
  declarada:** *«MNST da 6 pares y spread 0,031; el siguiente más alto tiene 2 pares. La
  separación es de un factor 3 en el eje que decide»*. Es exactamente lo que pide [M-umbral].
- **Y el guard sobrevive a que su único positivo real haya sido reparado.** MNST se re-bajó el
  2026-09-07, así que hoy `mixed_scale_frames` sobre el universo vivo da **limpio** y MNST ni
  siquiera está en él. Eso podría haber dejado al guard sin caso positivo — pero
  `tests/test_cohorte_continuidad_t110.py` tiene un **MNST sintético** más **tres controles
  negativos** (crash y rebote, un solo cambio de escala, y ruido caótico). El guard puede
  seguir fallando si alguien lo rompe.
- **`signal_store_gaps` compara FECHAS, no cantidades** — es lo que arregló la tarea 69 y sigue
  así. Su `len(bars) <= warmup` es un descarte previo correcto: sin barras evaluables no hay
  cobertura que exigir.

---

## 4. Hallazgos

Dos, los dos **latentes**. El primero pasó por el `verificador` con mandato de refutarlo:
**sobrevivió con tres correcciones**, y una de ellas **da vuelta la consecuencia**. El segundo
lo trajo la fase adversarial.

---

### [M-1] La tripleta de la ventana mezcla dos agregaciones incompatibles, y el `n_bars` clavado en AVB ENMASCARA que el cohorte encoja

Severidad: **MEDIA** (latente) · Confianza: **ALTA** · Categoría: [M-largo]
Ubicación: `analysis/harness_config.py:394` (`artifact_window`) · `:391` (`__str__`) · `:1431`

**Lo primero, porque cambia cómo se lee todo lo demás: esto NO es un descubrimiento.** El
hecho está medido y escrito desde el **2026-09-02** en
`docs/auditoria_muestra_2026-09-02.md:81` y `docs/BACKLOG.md:371`: *«el `start` (2016-08-08) y
el `n_bars` (2514) los sostiene un solo ticker de 127 —AVB—»*. **Lo nuevo es que la refutación
con la que se cerró no se sostiene.** Se descartó como *«REFUTADA, y por un test que anticipó
esta misma re-discovery»*, y ese test —`tests/test_harness_config.py:594-600`— assertea
exactamente dos cosas: que AVB está en `ARTIFACT_REFRESH_EXCEPTIONS`, y que
`WINDOW_REFRESH_2026_09_01_LIVE.start < ..._LEGACY.start`. **Nada de `n_bars`.** Se barrieron
las otras cuatro fuentes candidatas (el comentario del ancla en `:2283-2288`, la skill del
harness, `docs/reanchor_t68_2026-09-01.md` y `docs/harness_window_t48_2026-08-20.md`) y **las
cuatro hablan sólo del `start`**. De ahí no salió ni tarea, ni test, ni comentario.

**La formulación fuerte, que es la que nadie escribió: la tripleta describe a ningún ticker.**
`start` y `end` son la **envolvente** del cohorte (unión); `n_bars` es un **máximo de miembro**.
Medido:

| | |
|---|---|
| ventana publicada | `2016-08-08..2026-09-01 (2514 barras)` |
| unión de fechas del cohorte **dentro** de esa ventana | **2531** ruedas |
| diferencia | **17 barras** — exactamente el atraso de AVB que el banner ya imprime |
| único objeto real con 2514 barras | **AVB**, con **su** ventana: `2016-08-08..2026-08-07` |

O sea: **ninguna serie puede tener 2514 barras en la ventana publicada.** La tripleta es
`start` de AVB + largo de AVB + `end` de los otros 126.

**Y el módulo ya sabe que esta agregación es la equivocada, un campo más arriba.**
`cohort_end` (`:507`) usa la **moda** con el motivo escrito: *«Moda y no máximo a propósito: un
único artefacto refrescado de más haría que todos los demás parecieran atrasados»*. El caso
espejo —*un único artefacto **no** refrescado se queda con el `min` y con el `max`*— es
exactamente el que ocurre, sobre la misma población, en el mismo archivo.

**La consecuencia, corregida — y mi primera versión la tenía al revés.** Yo había escrito que
el riesgo era `REPRO_INDETERMINATE` de más. **No lo es:** en los cuatro estados en que `n_bars`
puede dejar de ser el de AVB (se refresca, se levanta la excepción, sale del universo, o entra
un ticker con más historia), **otro eje ya declarado y testeado se mueve en el mismo evento** —
el `start`, o directamente la población, que se chequea primero y devuelve `REPRO_NA`. Ahí
`n_bars` es redundante.

**Donde sí muerde es la inversa: enmascaramiento.** El 2514 está estrictamente **por encima**
de todo el cohorte sano (moda 2513, mínimo 2511), así que el `max` queda clavado a un frame que
**por diseño nadie va a refrescar nunca**. Probado por mutación sobre el cohorte real,
sacándole **una rueda interior a los 126 sanos** —que es la clase de defecto de la T110, medida
en este repo con el 2026-08-28 faltando en 457/506—:

```
hoy                : 2016-08-08..2026-09-01 (2514 barras)
126 sanos −1 barra : 2016-08-08..2026-09-01 (2514 barras)   same_window: True
sin AVB, hoy       : 2016-09-01..2026-09-01 (2513 barras)
sin AVB, −1 barra  : 2016-09-01..2026-09-01 (2512 barras)   same_window: False
```

Con AVB el cohorte entero encoge y `str(window)` queda **byte-idéntico** ⇒ `same_window=True` ⇒
se habilita la rama que puede devolver **`REPRO_FAIL — MISMA muestra ⇒ cambió la cañería`**
sobre una muestra que **sí** cambió. Es acusar **de más**, y `REPRO_FAIL` invalida la corrida
entera: justo lo que la tarea 52 documentó como *«una máquina de invalidar corridas buenas»*.
Sin AVB, `n_bars` seguiría a la moda y se movería con el cohorte; con AVB el colchón es
permanente.

**Que `n_bars` está en la identidad y no es una etiqueta, verificado:** el docstring de
`ArtifactWindow` (`:382-384`) dice *«Dos corridas con la misma tripleta corrieron sobre la misma
muestra»*, `__str__` lo incluye, y `:1431` calcula `same_window` con
`str(measured_on) == str(current)` — **la única forma**. Hay **8 call sites** de
`reproduction_check`, 7 anclados al `LIVE` y 1 al `LEGACY`.

**Lo que lo acota, y va primero cuando se tome la tarea:** (a) `same_window` **sólo se consulta
después** de fallar la tolerancia — si el número reproduce, la ventana no se mira; (b) la clase
que queda enmascarada (hueco interior) **tiene guard propio y anterior** —`cross_period_gaps` /
`announce_continuity`, T110— con cobertura de **126 de 127** en el universo vivo, y aborta con
`StaleArtifactError`; (c) hoy el ancla coincide exactamente con el cohorte medido, incluso
cargando con el loader real de los runners: **no hay ningún veredicto publicado contaminado**.

**Trampa de alcance que hay que escribir:** el arreglo naíf *«usá la moda también en
`artifact_window`»* **choca de frente con la tarea 140**, que está atacando la moda desde el
otro lado (una referencia que sale de la población que chequea). Las dos tareas se pisan si no
se dice.

---

### [M-2] La razón de que existan DOS anclas de ventana descansa entera en AVB, y el test que la custodia compara dos literales

Severidad: **BAJA-MEDIA** (latente) · Confianza: **ALTA** · Categoría: [M-ventana]
Ubicación: `tests/test_harness_config.py:570` y `:581`
Origen: **lo trajo el `verificador`**.

**Evidencia, re-medida.** La ventana viva **sin AVB** es `2016-09-01..2026-09-01 (2513 barras)`,
que es **campo por campo, byte a byte, `WINDOW_REFRESH_2026_09_01_LEGACY`**. O sea que hoy el
ancla del cohorte vivo (127 tickers) y la del legacy (41) se distinguen **únicamente** por el
artefacto congelado de AVB.

**Consecuencia.** El día que AVB se refresque o salga del universo, las dos anclas pasan a ser
el **mismo objeto**, y `same_window` deja de poder distinguir *«medido sobre el cohorte vivo»*
de *«medido sobre el legacy de 41»*. Toda la lección de la tarea 68 —*«son DOS, una por
universo, porque difieren en el `start`»* (`harness_config.py:2270-2276`)— se apoya en eso.

**Lo que lo vuelve un hallazgo de esta área y no una curiosidad:** el test que lo custodia es
`assert WINDOW_REFRESH_2026_09_01_LIVE != WINDOW_REFRESH_2026_09_01_LEGACY` — **una comparación
entre dos constantes literales**, que va a seguir en verde para siempre mientras el hecho que
codifica se vuelve falso. Y el test que lo contiene se llama
`test_the_anchor_constants_match_the_measured_windows` pero **no mide nada**: assertea los
strings de las constantes contra sí mismos. **Nada en la suite compara jamás un ancla contra un
cohorte real.** Es literal la sub-categoría [M-ventana]: *un chequeo que sigue siendo verdad hoy
y deja de serlo cuando la ventana rueda, sin que nada lo declare*.

**Lo que lo acota:** el eje **población** (T52) sí las separa —`universe_file` y `n_tickers`
127 vs 41— y se chequea **primero**, devolviendo `REPRO_NA`. Hay defensa en profundidad y **no
es un incidente vivo**. Lo que falla es *por qué* funciona — el mismo tipo de defecto que la
tarea 89.

---

## 5. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [M-1] La tripleta mezcla dos agregaciones y el `n_bars` de AVB enmascara el encogimiento | MEDIA (latente) | **144** VENTANA-FRANKENSTEIN |
| [M-2] Las dos anclas se distinguen sólo por AVB, y el test compara dos literales | BAJA-MEDIA (latente) | **145** ANCLA-TAUTOLOGICA |

Dos hallazgos, dos filas, ninguna vacía.

## 6. Limitaciones

1. **Ninguno de los dos es un incidente vivo.** Hoy el ancla coincide con el cohorte medido y
   ningún veredicto publicado está contaminado.
2. **No se corrió ningún harness** ni se re-midió ningún veredicto.
3. El barrido de comparaciones por cantidad cubrió **ocho módulos**, no el repo entero.
4. Lo ya encontrado hoy por las otras corridas (tareas **128**, **133**, **140**, **141**) se
   excluyó a propósito para no re-reportar.
