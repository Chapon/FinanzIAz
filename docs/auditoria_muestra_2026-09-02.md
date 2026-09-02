# Auditoría `muestra` — 2026-09-02

**Área:** chequeos por **cantidad** que son ciegos a la **ventana** o a la **población** ·
**READ-ONLY**, no se modifica nada · Tercera corrida de la skill `auditoria` · Fase
adversarial: agente `verificador`

---

## 1. Kill-criteria — congelado ANTES de abrir un archivo

*(Escrito y guardado antes del primer `grep`. La corrida arranca después de esta sección.)*

### Qué se busca

Un invariante verificado **contando** en vez de comparando **identidad, fechas o claves**.
La pregunta es siempre la misma:

> **¿esto sigue siendo verdad si la ventana rueda, o si la población cambia de forma?**

Cuatro formas concretas:

1. **Completitud por cantidad.** `len(x) >= n` o `count == esperado` que decide *"esto ya
   está"*, cuando lo que importa es **cuáles** están.
2. **Cobertura sobre el eje equivocado.** Un porcentaje medido sobre un eje (tickers) que
   su consumidor indexa por otro (fechas) — el defecto exacto de la tarea 75, cerrada hoy.
3. **Agregación que colapsa una distribución.** `min`/`max`/`sum`/media sobre un cohorte,
   usada para caracterizar a **todos** sus miembros.
4. **Población declarada ≠ población efectiva.** Contar candidatos cuando el brazo sólo
   toca a algunos (tarea 62: sobrestimaba **13×**).

### Corpus

`scripts/precompute_*.py` · `scripts/run_*.py` · `analysis/harness_config.py` ·
`analysis/portfolio_sim.py` · `analysis/exit_replay.py` · `analysis/scaleout_replay.py` ·
`paper_trading/engine.py` y sus gates · `data/quality.py` · `data/yahoo_finance.py`.

### Qué queda explícitamente AFUERA

- **Los tests.** Sus `assert len(...) == n` cuentan a propósito sobre fixtures sintéticos.
  (Excepción: un test cuya **población** puede quedar vacía y pasar vacío — eso sí entra,
  es el mismo defecto.)
- **`len()` de display/log.** Si no decide nada, no es un hallazgo (regla 3 de la skill).
- **Lo ya cerrado con guard**: la 69 (completitud PIT), la 62 (población de salidas), la 75
  (cobertura de `risk_score`), la 48/52 (ventana y población de reproducción). **Sí entra**
  buscar si el mismo patrón quedó **copiado** en un script hermano — la 69 encontró que lo
  estaba, y esa es la forma en que esta familia se propaga.
- Performance, dead code, seguridad, dependencias.

### Qué contaría como "acá no hay nada"

Barrido limpio **⇔** para **cada** comparación de tamaño que gatea una decisión, se cumple
al menos una de:

- **(a)** compara sobre el **mismo eje** que indexa el consumidor de esa decisión;
- **(b)** viene acompañada de un chequeo de **ventana o identidad** (fechas, claves) que la
  hace insensible al conteo;
- **(c)** es demostrablemente **sin decisión** (display, log, métrica reportada).

Si las tres fallan para alguna, hay hallazgo. Si ninguna falla, se cierra en limpio y se
dice — con el corpus mirado listado, para que el "no hay nada" sea auditable.

## 2. Predicciones — declaradas antes de mirar

Se escriben para que la corrida pueda **salir mal**. Una auditoría cuyas predicciones
aciertan todas no aprendió nada.

| | predicción |
|---|---|
| **P1** | `precompute_pit_risk_score.py` tiene el **mismo** chequeo por cantidad que la tarea 69 arregló en `precompute_pit_signals.py`. La 69 declaró que el patrón estaba **copiado** en el script hermano; si sólo se arregló uno, el otro sigue diciendo *"completo"* con fechas faltando. |
| **P2** | Algún gate de `paper_trading/engine.py` decide con un `len()` de candidatos o de posiciones que no mira la ventana — p.ej. un tope de exposición o de slots contado sobre una lista que puede estar recortada. |
| **P3** | Hay al menos un consumidor de `artifact_window` / `cohort_end` que usa la agregación (moda, `min`..`max`) **como si fuera de todos** los miembros del cohorte, no del agregado. |

*(Resultado de las tres: §3.)*

## 3. Cómo salieron las predicciones — **las tres, mal**

| | predicción | resultado |
|---|---|---|
| **P1** | `precompute_pit_risk_score` tiene el chequeo por cantidad copiado | **REFUTADA.** No es copia: **importa** `pending_dates` de su hermano (`precompute_pit_risk_score.py:39`) y decide por fechas (`:98`). La tarea 69 llegó a los dos, y hay un test que lo fija (`test_the_SIBLING_precompute_has_the_same_guard`). |
| **P2** | Algún gate del engine decide con un `len()` ciego a la ventana | **REFUTADA.** `paper_trading/engine.py` tiene **tres** usos de `len()` y los tres son telemetría (`generated`, `prices_requested`, `prices_missing`). Los conteos de slots (`gates.py:385`, `strategies.py:468,630`) cuentan **slots**, que son un conteo por definición. |
| **P3** | Hay un consumidor de `artifact_window` que usa la agregación como si fuera de todos | **REFUTADA, y por un test que anticipó esta misma re-discovery.** Medido: el `start` de la ventana viva (`2016-08-08`) lo sostiene **un solo ticker de 127** —AVB, la excepción congelada— y el `n_bars` (2514) también. Pero eso **ya está declarado y fijado**: `test_the_live_window_start_rides_on_the_declared_refresh_exception` (tarea 68) dice *"el start de la ventana viva lo fija AVB… queda fijado acá para que no se re-descubra"*. Publicarlo habría sido re-reportar trabajo hecho. |

**Que las tres salieran mal es el resultado, no un accidente.** Las tres apuntaban a que la
familia B se hubiera propagado por copia, y el barrido dice que **no**: la 69 llegó al
script hermano, la 68 dejó su excepción fijada con test y el engine no decide por conteo.
Lo que sí apareció está **un nivel más arriba** — no en los productores sino en el
**contrato entre productor y consumidor** (§4).

## 4. Los hallazgos

Cuatro, ordenados por severidad. Los dos primeros pasaron por el agente `verificador` con
mandato de **refutar**: uno sobrevivió intacto, el otro salió **reformulado y bajado de
severidad** — y el informe publica la versión del verificador, no la mía.

### [B-2] Ningún consumidor chequea que el store de señales PIT cubra el cohorte de barras
**Severidad: HIGH (latente) · Confianza: ALTA · Categoría: chequeo por cantidad, ciego a la ventana**

**Ubicación.** Los **6** sitios consumidores: `run_anomaly_replay_t11b.py:126` ·
`run_insider_cluster_replay_t12.py:190` · `run_meta_label_t9.py:110` ·
`run_ranking_t21.py:117` · `run_scaleout_replay_t7.py:102` · `run_tp_cal_replay_t23.py:95`.
Son los **cuatro loaders compartidos** de los que cuelgan los 21 runners.

**Evidencia.** La tarea 69 arregló el **productor**: `pending_dates()` decide por fechas y su
docstring dice que `complete` *"ya no alcanza solo"*. Pero `grep pending_dates` sobre
`scripts/` y `analysis/` devuelve **sólo los dos `precompute_*`** — ningún runner lo llama.
Los seis consumidores hacen `if not blob.get("complete")` y nada más.

**Y el flag sí puede quedar corto después de la 69**: se escribe `done=True` al terminar el
barrido y **nada lo invalida cuando el frame rueda** — la 69 arregló la *guarda de salteo*
del productor, no el **significado** del flag.

**Razonamiento.** `announce_artifacts` —el guard del cohorte, cableado a los 21 runners hoy
mismo por la tarea 76— mira **las barras**. Nada mira el store de señales contra esas
barras. O sea que un runner puede **pasar el guard del cohorte y correr igual sobre una
muestra encogida**, y la única señal sería que el número no reproduce.

**Impacto.** No es contaminación: es **encogimiento silencioso de la muestra**. Cuando pasó
—el 2026-09-01— movió el universo vivo de **141.777 a 142.670 entradas** y obligó a re-medir
**17 constantes publicadas** (tarea 68). Si vuelve a pasar cuesta lo mismo, y encima **B-1 lo
diagnostica como "cambió la cañería"** en vez de "re-anclá".

**Lo que acota el hallazgo, y va escrito o el enunciado exagera.** **(1) Hoy no hay hueco:**
medido sobre los 127 del universo vivo, 127 blobs `complete` y **0 fechas pendientes**; el
único disidente (última barra `2026-08-07`) es el mismo ticker en los dos lados — AVB, la
excepción declarada. Es **latente**. **(2) El disparador es manual:** nada refresca solo el
cohorte `10y/1d`. El engine vivo corre con `paper_history_period="2y"`
(`paper_trading/engine.py:181-186`) y el path del parquet lleva el period, así que la
operación diaria **nunca** rueda el cohorte del harness. Sólo rueda si alguien lo refresca a
propósito — el caso de la tarea 30.

**Verificación.** El `verificador` intentó voltearlo y no pudo. Corrigió la enumeración:
`run_ranking_t21.py:174` **sale** de la lista, porque desde la tarea 75 (cerrada hoy) ese
sitio mide cobertura sobre pares (ticker, fecha) con umbral y diagnóstico de cola aparte.
Es el **único consumidor del repo con guard a nivel de fechas** ⇒ es **precedente a favor**,
no contraejemplo. Por eso son 6 y no 7.

**Acción.** Un guard análogo a `announce_artifacts` para el store de señales — o extenderlo,
ya que los 21 runners ya lo llaman — que compare las fechas del store contra las del cohorte
y **falle ruidoso antes de pagar la corrida**. El patrón correcto ya está escrito dos veces:
`pending_dates()` (productor) y `load_risk_scores` post-T75 (consumidor).

---

### [B-1] `ArtifactPopulation` es ella misma un chequeo por cantidad, y su política se justifica al revés
**Severidad: MEDIA · Confianza: ALTA · Categoría: población declarada ≠ población efectiva**

> **Reformulado por el `verificador`, y bajado de HIGH a MEDIA.** Mi versión decía *"trata
> `no declarado` como `igual` y nadie lo vio"*. **Eso es falso**: está declarado en cuatro
> lugares (`harness_config.py:1239-1244`, el docstring de `matches`, `docs/BACKLOG.md:308`,
> `docs/repro_pop_t52_2026-08-28.md:62`) y **pinneado por dos tests**. No es un descuido: es
> **política**. Lo que sobrevive es más incómodo que lo que yo tenía.

**Ubicación.** `analysis/harness_config.py:480-495` (`same_universe_as`, `matches`),
`:1245-1246` (las anclas), `:586-605` (`reproduction_check`).

**Evidencia — la clase que existe para terminar con los chequeos ciegos a la muestra es
ella misma uno.** `same_universe_as` compara **un string de path y un entero**, nunca
*cuáles* tickers; `matches` saltea el único campo que queda. En producción, la frase
**"MISMA muestra ⇒ cambió la cañería"** se afirma con la fuerza de
`"data/harness_universe_live_acct2.txt" == "..."` y `127 == 127`. No hay ningún fingerprint
del archivo de universo ni del store en ningún lado (sin `hashlib`/`sha256` en el módulo).

**Y la rama que compararía las entradas es código muerto.** Los **8** call sites pasan una
de las dos anclas compartidas, y las dos tienen `n_entries=None`:

```python
POPULATION_LIVE_ACCT2 = ArtifactPopulation(LIVE_UNIVERSE_FILE, 127)   # n_entries = None
POPULATION_LEGACY_41  = ArtifactPopulation(LEGACY_UNIVERSE_FILE, 41)  # n_entries = None
```

`if self.n_entries is None or other.n_entries is None: return True` ⇒ la línea
`self.n_entries == other.n_entries` **sólo se ejecuta en un test**.

**Razonamiento — la justificación está invertida, y es verificable.** El comentario que
sostiene la política (`:1242`) dice que comparar las entradas *"acusaría por un desvío de
config y no de muestra"*. **Comparar no puede acusar nunca**: un desajuste de entradas hace
`same_population=False` y cae en `REPRO_INDETERMINATE`. Declarar `n_entries` sólo puede mover
**FALLA → INDETERMINADO**, jamás al revés. La mitigación va exactamente **al revés de su
objetivo declarado**. Y la segunda mitad —*"las entradas dependen de `cap_days`, gates y
demás"*— es falsa en **6 de los 8** sitios: ahí
`entries = buy_entries(bars_by, sigs_by, args.warmup)` depende sólo de barras, señales y
warmup; `cap_days`/`max_positions`/`capital` van a la **simulación**, no a la construcción de
entradas.

**Reproducido con las funciones reales**, sin mocks (ventana sin mover, universo igual, la
corrida declara 138.000 entradas):

```
FALLA — MISMA muestra (ventana 2016-08-08..2026-09-01 (2514 barras) · población
data/harness_universe_live_acct2.txt (127 tickers, 138000 entradas)) ⇒ cambió la cañería
```

Con el ancla declarando `n_entries=142670`, el mismo caso da **INDETERMINADO**. Y de yapa:
**el mensaje de FALLA imprime las 138.000 entradas de la corrida adentro de la frase que
afirma que la muestra es idéntica** — se contradice en la misma línea, igual que el
`esperado 3.71%` de la tarea 71.

**Impacto, acotado por el `verificador`.** `REPRO_FAIL` y `REPRO_INDETERMINATE` son
**indistinguibles aguas abajo**: todos los gates de los runners son `== REPRO_OK`, y `grep`
no encuentra **ninguna** comparación contra `REPRO_FAIL` fuera de `harness_config.py`
(verificado). Un FALLA equivocado **no da vuelta ningún booleano**: el daño es **el
diagnóstico**, que manda a cazar un cambio de cañería en vez de re-anclar. Es exactamente el
daño por el que se abrió la 52 — pero no es HIGH.

**Alcanzabilidad — el camino obvio está tapado, y hay dos que no.** Un refresh de barras
**mueve `max(ends)`** ⇒ gana la rama de ventana ⇒ `INDETERMINADO`. Los que sí quedan:

1. **Re-anclar la constante de ventana después de un refresh con el store de señales corto**
   — que es **literalmente lo que hizo la tarea 68 el 2026-09-01**. Misma ventana (recién
   re-anclada), mismo `n_tickers`, menos entradas ⇒ FALLA acusando a la cañería. Es **B-2
   disparando a B-1**.
2. **`scripts/refresh_live_universe.py:100` regenera el archivo de universo en el lugar**,
   con el mismo nombre. Si la watchlist viva cambia **un ticker por otro** y el conteo queda
   en 127, `same_universe_as` devuelve **True**, el test de pinneo sigue pasando (127 == 127),
   las entradas cambian y no se comparan ⇒ **FALLA**. Es el escenario del smoke de la 37 que
   dio origen a la 52, con el mismo nombre de archivo.

**Acción.** No es "poner `n_entries` en las anclas": el `verificador` señala que no es
implementable como constante única, porque 7 runners con construcciones de entrada distintas
comparten `POPULATION_LIVE_ACCT2`. Las dos salidas reales son **declarar las entradas por
runner**, al lado de cada `REPRO_*_CAGR`, o **un fingerprint del conjunto** (universo + store)
en vez de dos enteros. Y en cualquier caso, **corregir el comentario `:1242`**, que hoy
justifica la política con lo contrario de lo que hace el código.

---

### [B-3] El hermano del t21 mide cobertura de señales POR TICKER — el enunciado literal de la tarea 75
**Severidad: MEDIA · Confianza: ALTA · Categoría: cobertura sobre el eje equivocado**

> Hallazgo del `verificador`, sobre algo que yo miré en el barrido y **descarté mal** por la
> cláusula (c) del kill-criteria (*"es display, no decide"*).

**Ubicación.** `scripts/run_insider_cluster_replay_t12.py:507`, con el loader en `:188-194`.

**Evidencia.**

```python
f" · {n_sig} tickers con señal PIT ({100 * n_sig / max(1, len(bars_by)):.0f}% cobertura)"
```

Con 17 ruedas de cola faltando en los 127 blobs, esto imprime **100%**.

**Razonamiento — por qué mi descarte estaba mal.** Lo tomé por display. Pero el loader deja
al ticker sin señal en **ATR-only en silencio** (`:190-194`), así que ese porcentaje es **la
única visibilidad que existe** sobre si el brazo `analyze_flip` está corriendo con señal o
sin ella. Un número que miente **es** el daño, exactamente como en la tarea 75: *"el daño no
es ese 0,65%, es el reporte de cobertura que miente"*.

**Impacto.** Es la instancia de la familia **48 / 52 / 62 / 69 / 75** que quedó viva. La 75
se cerró **hoy** para el store de riesgo en el t21 y **no tocó al hermano**.

**Acción.** La más chica: medir sobre pares (ticker, fecha) y declarar el hueco de cola
aparte del porcentaje — el patrón ya está escrito al lado, en `run_ranking_t21.py:151-184`.

---

### [B-4] El desvío de universo se declara con un entero hardcodeado, unilateral y ciego al conjunto
**Severidad: BAJA-MEDIA · Confianza: ALTA · Categoría: población declarada ≠ población efectiva**

**Ubicación.** `analysis/harness_config.py:74` (`LIVE_WATCHLIST_SIZE = 128`) y `:662`.

**Evidencia.**

```python
if cfg.n_tickers < LIVE_WATCHLIST_SIZE:
    out.append(f"universo {cfg.n_tickers} tickers vs {LIVE_WATCHLIST_SIZE} de la watchlist viva")
```

**Razonamiento.** Tres problemas en una línea, los tres de esta familia: **(a)** el `128` es
una constante hardcodeada que **nada re-verifica** contra la DB; **(b)** la comparación es
**unilateral** (`<`), así que un universo de harness **más grande** que la watchlist viva no
declara nada; **(c)** es un **conteo parado en lugar de un conjunto** — un ticker cambiado
por otro deja el número igual y no genera ninguna línea de desvío. Es el mismo defecto que
B-1, en otro consumidor.

**Lo que acota:** hoy el número es correcto (medido: la watchlist de la cuenta 2 tiene
exactamente **128**) y el desvío **sí se declara** (el universo de harness tiene 127). O sea
que hoy funciona; lo que falla es **por qué** funciona.

**Acción.** Resolver `LIVE_WATCHLIST_SIZE` contra la DB o contra el archivo de universo en
vez de hardcodearlo, y comparar **conjuntos** en vez de tamaños — o, como mínimo, hacer la
comparación bilateral y declarar la diferencia simétrica.

## 5. Lo rechazado, y con qué motivo

- **P1, P2 y P3** — las tres predicciones, refutadas. Detalle en §3. La P3 merece subrayarse:
  medí que el `start` y el `n_bars` de la ventana viva los sostiene **un solo ticker de 127**
  y estuve a punto de publicarlo como HIGH. Ya estaba **declarado y fijado con un test**
  (tarea 68) que dice *"queda fijado acá para que no se re-descubra"*. El test hizo
  exactamente su trabajo, sobre mí.
- **El framing original de B-1** (*"nadie lo vio"*) — **rechazado por el `verificador`**, con
  cuatro citas y dos tests. Se publica la versión reformulada, con la severidad bajada.
- **`paper_trading/universe.py:109`** (`if len(ni) < need`) — **rechazado por mí**. Es un
  fail-open **documentado** sobre evidencia débil, y el orden que asume (*"most-recent-first"*)
  **está garantizado** por un `sorted(..., reverse=True)` en el constructor
  (`data/edgar_fundamentals.py:144`). No es un conteo ciego: es una abstención declarada.
- **`paper_trading/gates.py:385` y `strategies.py:468,630`** — **rechazados por mí**: cuentan
  **slots**, que son un conteo por definición.
- **`data/quality.py`** — rechazado: los conteos son sobre la identidad que cuentan (gaps de
  calendario) y los umbrales están documentados.

## 6. Alcance NO mirado

- **`analysis/metrics_panel.py`, `scripts/dashboard_data.py`, `ui/`**: son display. Sus
  `len()` no deciden nada y quedaron fuera por la cláusula (c) del kill-criteria.
- **`data/quality.py`**: se miró por arriba (los conteos son sobre la identidad que cuentan
  —gaps de calendario— y los umbrales están documentados), no se auditó su calibración.
- **Los tests que descubren su población por `glob`**: se revisaron los cuatro que lo hacen
  (`t71`, `t72`, `harness_config`, `baseline_metrics`) y **los cuatro tienen guarda de
  vacuidad** o fallan ruidoso si el barrido queda corto. No se revisaron los ~180 tests que
  no descubren población.
- **`scripts/regime_attribution.py` y `scripts/baseline_metrics.py`**: tienen decenas de
  `len(...) < 2` que son guardas estadísticas triviales; no se auditaron uno por uno.
- **Las otras cuatro áreas** de la skill: `claims`, `desvios`, `guards`, `estado`
  (esta última corrida el 2026-09-02, ver `docs/auditoria_estado_2026-09-02.md`).

## 7. Cierre — mapeo hallazgo → tarea

**Una fila por hallazgo publicado, ninguna vacía.** Verificado de a uno contra
`docs/BACKLOG.md` (`grep "^### NN\."` + la referencia al hallazgo en el título), no de
memoria. Sin esta tabla la auditoría no está cerrada: en la primera corrida de la skill se
publicaron 7 hallazgos con 3 tareas y dos quedaron sueltos.

| hallazgo | severidad | tarea | título de la tarea |
|---|---|---|---|
| **B-2** | ALTA (latente) | **86** | PITCOV-CONSUMIDOR — Ningún runner chequea que el store de señales PIT cubra el cohorte de barras |
| **B-1** | MEDIA | **87** | POBLACION-CONJUNTO — `ArtifactPopulation` es ella misma un chequeo por cantidad, y su política se justifica al revés |
| **B-3** | MEDIA | **88** | T12-COBERTURA — El hermano del t21 mide cobertura de señales POR TICKER |
| **B-4** | BAJA-MEDIA | **89** | WATCHLIST-SIZE — El desvío de universo se declara con un entero hardcodeado, unilateral y ciego al conjunto |

**Los dos casos que la skill avisa que se escapan, chequeados explícitamente:**

- **Hallazgo agrupado como "parte de" otro** — **ninguno**. El mapeo es **1:1**: cuatro
  hallazgos, cuatro tareas, ninguna agrupa a otra. (La 89 dice que *se puede hacer junto con
  la 87* porque es el mismo defecto en otro consumidor, pero **tiene enunciado y número
  propios**: nadie puede arreglar la 87 y creer que cerró la 89.)
- **Hallazgo que no se pudo verificar pero es accionable** — **ninguno**. Los cuatro se
  publican **medidos**: B-2 con el barrido de los 127 blobs, B-1 reproducido con las
  funciones reales sin mocks, B-3 leído en el fuente con su loader al lado, B-4 contrastado
  contra la watchlist viva de la DB. Nada quedó en *"habría que re-chequear"*.

**Lo rechazado no lleva tarea, y eso es correcto:** P1, P2, P3, el framing original de B-1 y
los cuatro descartes propios de §5 **no** entran a la cola. Una auditoría que abre tareas
para lo que refutó convierte su propia fase adversarial en decoración.

**Estado del repo al cerrar** (verificado por el `verificador`): suite **2531 passed, 3
skipped** en Windows, `check_repo_health.py` sin problemas sobre 2.690 archivos, árbol limpio
salvo este informe. **READ-ONLY cumplido: no se tocó código, config, esquema ni tests.**
