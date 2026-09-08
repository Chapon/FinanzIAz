# Auditoría READ-ONLY — área `guards` — 2026-09-08

Octava corrida de `/audit`. Área: **guards que fallan en silencio, o que rechazan el dato
bueno**. Corrida anterior de esta área: `docs/auditoria_guards_2026-09-03.md` (dejó las tareas
97 a 105).

---

## 1. Kill-criteria — CONGELADO 2026-09-08, antes de abrir ningún archivo

> Escrito **antes** de mirar un guard. No se toca después.

### 1.1 Por qué ahora

Desde la corrida anterior se shipearon guards nuevos en las tareas **110, 113, 114, 117, 119,
123 y 127**, y **ninguno fue auditado todavía** — o sea que la población de guards creció
después del último barrido. Y las dos corridas de hoy ya encontraron **dos guards ciegos** sin
buscarlos (tareas **128** y **130**), lo que dice que el área tiene superficie sin mirar.

### 1.2 Qué se busca — una frase por sub-categoría

- **[G-mudo]** Un guard que falla abierto **sin dejar rastro**, o cuyo aviso no escala si se
  repite.
- **[G-buendato]** Un guard que puede estar **rechazando el dato bueno** — la pregunta que
  destapó la tarea 63, donde el guard E5 descartó el precio correcto de AVB durante 4 días.
- **[G-referencia]** Un guard cuya **referencia sale de la misma población que chequea**, así
  que es ciego al defecto mayoritario (pasó en la 101 y en la 110).
- **[G-inerte]** Un guard **declarado pero no cableado**, o cableado a menos lugares de los que
  su enunciado dice cubrir.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. **Bugs de código** (suite, CI, `/code-review`).
2. **Los dos guards ciegos que ya encontraron las corridas de hoy** —el `getattr` de la tarea
   99 (tarea **128**) y los espejos `LIVE_*` (tarea **130**)—. Ya tienen cola; re-reportarlos
   sería inflar.
3. **Guards de terceros** (ruff, pytest, alembic).
4. **Correr harness o re-medir veredictos.**

### 1.4 Qué contaría como "acá no hay nada" — condición de barrido limpio

Cierra **limpia** si: (1) todo `except` que traga una excepción en un camino de decisión deja
rastro y el rastro escala; (2) ningún guard usa como referencia la misma población que audita;
(3) todo guard declarado en un doc, skill o backlog está **efectivamente cableado** a lo que
dice cubrir; y (4) para cada guard que puede bloquear dato, existe la respuesta escrita a
*«¿qué pasa si el que se rechaza es el bueno?»*.

### 1.5 Alcance que se va a mirar

Los guards de datos (`data/quality.py`, `data/yahoo_finance.py`, `paper_trading/gates.py`,
`paper_trading/universe.py`), los guards de harness (`analysis/harness_config.py`), los guards
de proceso (`scripts/check_repo_health.py`, `scripts/check_backlog_integrity.py`) y los
`except` de los caminos de decisión de `paper_trading/engine.py` y `paper_trading/strategies.py`.

---

## 2. Alcance real, y cómo se barrió

**El barrido de [G-mudo] se hizo por AST, no por grep**, y hubo que afilarlo dos veces — que es
en sí una lección sobre el instrumento:

1. *«`except` sin log ni raise»* sobre `paper_trading/`, `analysis/`, `data/` y `config/` da
   **114 handlers**. Reportar eso sería ruido: la mayoría son parsers con
   `except ValueError: return None`, que es correcto.
2. Afilado a **`except` amplios** (`Exception`/bare) **y** en módulos del **camino de
   decisión** queda en **8**. Ése es un número sobre el que se puede razonar.

Los ocho se leyeron uno por uno (§4): ninguno sobrevivió como hallazgo, y el motivo de cada
descarte está escrito, que es lo que evita que la próxima corrida los vuelva a levantar.

**Lo que se miró además:** el cableado real de los siete `announce_*` por AST sobre los 39
scripts; la composición interna de los guards de `harness_config.py`; las poblaciones de los
cuatro guards que eligen runners; `cohort_end`/`stale_artifacts` contra el calendario real; y
el `SettingSpec` de los flags que gatean.

**NO mirado, y queda declarado:**

1. **Los dos guards ciegos que ya encontraron las corridas de hoy** — el `getattr` de la tarea
   99 (tarea **128**) y los espejos `LIVE_*` (tarea **130**). Tienen cola; re-reportarlos sería
   inflar.
2. **Los guards de la UI y del scheduler** más allá del chequeo de horario de mercado.
3. **`data/quality.py` y los guards de precio** (`unreliable_reference`, `recent_split_factor`):
   la 114 y la 127 los tocaron hace días y la 127 los probó por mutación en cuatro ejes.
4. **Los guards de terceros** (ruff, pytest, alembic).

---

## 3. Hallazgos

Tres. Los dos que salieron del barrido pasaron por el `verificador` con mandato de refutarlos:
**los dos sobrevivieron, los dos con correcciones**, y la fase adversarial **agregó el
tercero** — que además es el que hace barato arreglar el segundo.

---

### [G-1] El guard del store de señales elige su población por PREFIJO DE NOMBRE — el defecto exacto que la 101 cerró en el guard hermano, y se le escapa el mismo archivo

Severidad: **MEDIA-ALTA** (latente hoy) · Confianza: **ALTA** · Categoría: [G-referencia]
Ubicación: `tests/test_signal_store_t86.py:222` · `scripts/measure_trail_arm_t54.py`

**Evidencia.** Dos guards hermanos, **el mismo regex de predicado**
(`load_bars_signals|load_bars_and_signals|parquet_cache\.read|artifact_window\(`), dos
poblaciones distintas:

| guard | población | exclusiones |
|---|---|---|
| frescura del cohorte (`tests/test_harness_config.py:1204`) — **arreglado por la 101** | `glob("*.py")` | `_NO_LE_CORRESPONDE_EL_GUARD`, **3 con motivo escrito** |
| store de señales (`tests/test_signal_store_t86.py:222`) — **sin arreglar** | `glob("run_*.py")` | `_NO_LEE_EL_STORE`, **1 entrada** |

El comentario del guard ya arreglado (`test_harness_config.py:1173-1174`) dice literalmente:
*«Es la única forma de que la lista no vuelva a ser "los que se llaman `run_`": el predicado es
una propiedad del archivo, y lo que queda afuera queda afuera escrito»*. **El hermano todavía
es «los que se llaman `run_`».**

**Los conteos, corregidos por el verificador** (mi primera versión inflaba):

- **30** archivos de `scripts/` cumplen el predicado.
- **21** son visibles al guard (no 22: `run_exit_replay_t61.py` sale con motivo escrito).
- **8** quedan afuera por el prefijo, pero **sólo 5 sin motivo en ningún lado** — los otros 3
  (`precompute_pit_signals.py`, `precompute_pit_risk_score.py`, `benchmark_historical_cache.py`)
  tienen motivo escrito en la lista **hermana**, y transfiere solo: son los **productores** del
  store y un benchmark de I/O.
- De los 5, **uno solo es hueco con consecuencia: `measure_trail_arm_t54.py`**, que llama a
  `load_bars_signals` (`:172`) y **nunca** a `announce_signal_store`.

**Y el remate: es el mismo archivo que la auditoría de la 101 tuvo que cazar a mano**, por la
misma razón — llega al sustrato por un **import** (toma `load_bars_signals` del runner de la
T23) y no por una llamada local, así que un barrido que mira *cómo se ve el archivo* no lo
encuentra. El único archivo que ya demostró que la heurística de nombre falla es el que sigue
afuera del guard hermano.

**Verificación (los cuatro intentos de refutación que fallaron).** ¿Lo cubre `load_bars_signals`
por adentro? **No**: `run_tp_cal_replay_t23.py:97` sólo mira `blob.get("complete")`, que es
*precisamente* el flag que el bloque de diseño de la T86 (`harness_config.py:1057-1060`)
declara insuficiente (*«se escribe al terminar un barrido y nada lo invalida cuando el frame
rueda»*). ¿Lo cubre `announce_artifacts`? **No**: es el otro sustrato (barras), no toca
`data/pit_signals/`. ¿Otro test? **No.** ¿Excluido a propósito? **No**, nada en `docs/` ni en
el backlog.

**Cota de severidad, medida hoy — es latente, no activo.**
`load_bars_signals(127, "10y", warmup=250)` carga 127 con `missing=0` y `signal_store_gaps`
devuelve **0**: el store está completo, así que hoy ese runner daría los mismos números con o
sin guard. **Lo que pasa cuando el store se queda corto** es el modo de falla de la T86: como
`complete` sigue en `True`, `load_bars_signals` **se queda con el ticker**, `sigs_by` no tiene
las fechas nuevas, `buy_entries` encuentra menos BUY y el runner produce números **sobre una
muestra encogida, sin error y sin mensaje**. Los otros 21 abortarían con `SignalStoreGapError`.

---

### [G-2] El guard de frescura del cohorte es ciego al cohorte uniformemente atrasado, porque su referencia es la moda de la misma población que audita

Severidad: **ALTA** · Confianza: **ALTA** · Categoría: [G-referencia]
Ubicación: `analysis/harness_config.py:507` (`cohort_end`) y `:521` (`stale_artifacts`)

**Evidencia.** `stale_artifacts` compara cada artefacto contra `cohort_end(bars_by)`, que es la
última barra **modal del propio cohorte**. Si todo el cohorte está igual de viejo, la moda se
mueve con él y no se acusa a nadie. Medido hoy sobre el universo vivo:

| cohorte | n | última barra modal | `stale_artifacts` | atraso vs. hoy |
|---|---|---|---|---|
| `2y` | 127 | 2026-09-08 | **0** | 0 |
| `10y` | 127 | 2026-09-01 | **0** | 5 |
| **`5y`** | **39** | **2026-06-01** | **0** | **71** |

**El `5y` está tres meses y medio atrás y el guard acusa CERO.** Ésa es la demostración
—la trajo el verificador y la re-medí—, no el `10y`.

**Corrección que me sacó el verificador, y va escrita porque importa:** mi primera versión
titulaba con *«el cohorte está 5 ruedas atrás **hoy**»* como si fuera un incidente. **No lo
es.** El **2026-09-07 es Labor Day** (primer lunes de septiembre, verificado) y no está en
ningún frame, así que el atraso real del `10y` es de **4 sesiones**, no 5; `_busday_lag`
sobre-cuenta porque no tiene calendario de feriados —lo dice su propio docstring (`:496`)— y
además cuenta hoy. Con `ARTIFACT_MAX_LAG_DAYS = 5`, **un guard cableado al calendario con esa
misma tolerancia tampoco dispararía hoy.** El hallazgo es estructural, no un incidente vivo.

**Cota honesta sobre el `5y`:** ningún runner con guard lo usa por default
(`run_switcher_validation.py:88` sí, pero no lee el cohorte Parquet). Es demostración
mecánica, no un número contaminado hoy.

**No hay ninguna otra fuente que mire el calendario**, y los tres candidatos caen:
`pending_dates` (T69) itera **las fechas del propio frame**, así que si el frame está atrasado
devuelve `[]` y el productor dice *«ya completo»* — hereda la staleness en vez de detectarla;
`signal_store_gaps` compara contra `bars_by`, el mismo sustrato; y el banner de la T48 **sólo
imprime**, no falla.

**No está declarado como limitación conocida.** Lo más cercano es
`harness_config.py:431`, que declara **la decisión de diseño** —*«lo que importa no es "¿está
viejo?" sino "¿está desalineado del resto?"»*— y la presenta como virtud. En ningún lado dice
*«si todo el cohorte se atrasa junto, esto no acusa»*.

**Y la asimetría no es sólo gratis: está premiada.**
`WINDOW_REFRESH_2026_09_01_LIVE = ArtifactWindow("2016-08-08", "2026-09-01", 2514)` es
exactamente la ventana del cohorte de hoy, y con ella `reproduction_check` devuelve
`REPRO_OK`/`REPRO_FAIL`, o sea un veredicto usable. **Refrescar** el cohorte lo pasa a
`REPRO_INDETERMINATE` y obliga a re-anclar constantes (la T68 tuvo que re-anclar **17**). Un
refresh **parcial** aborta la corrida; **no refrescar nunca** no cuesta nada y encima conserva
la reproducibilidad. El gradiente de incentivos apunta a no refrescar.

**El fix NO es agregarle un calendario al guard** — ver [G-3], que es más barato y esquiva el
problema de los feriados.

---

### [G-3] `cross_period_gaps` descarta la evidencia del hermano más nuevo con una justificación que sólo vale del lado izquierdo

Severidad: **MEDIA-ALTA** · Confianza: **ALTA** · Categoría: [G-buendato]
Ubicación: `analysis/harness_config.py:681-683`
Origen: **lo trajo el `verificador`**, y es el que hace barato arreglar [G-2].

**Evidencia.** El bloque de diseño de la T110 (`harness_config.py:609-618`) enuncia el
principio correcto y nombra el mecanismo: *«La fuente de verdad tiene que ser independiente del
cohorte que se chequea. La que hay sin red y sin dependencias nuevas: **el mismo ticker en otro
período**»*. `cross_period_gaps` lo implementa… y después se recorta:

```python
lo = max(lo_p, min(otras))
hi = min(hi_p, max(otras))     # ← acá
if lo > hi:
    continue                    # sin solape: no hay nada que comparar
```

El docstring lo justifica con *«fuera de ahí la ausencia no es un hueco, es que el frame no
llega»*. **Eso es cierto para el borde izquierdo y falso para el derecho.** Un hermano con
barras **más nuevas** no es «un frame que no llega»: es evidencia directa de que **este** frame
está atrasado — justo el dato que la T110 declaró estar buscando.

**Medido hoy:** los **127** tickers del universo vivo tienen un hermano `2y` que llega al
**2026-09-08** mientras su `10y` para el **2026-09-01**, y `cross_period_gaps` reporta **0
huecos**. La evidencia de que el `10y` está atrasado **ya está en el disco** y el guard la tira.

**Por qué esto reformula el arreglo de [G-2].** Des-recortar la cola es más barato que cablear
un calendario, **no necesita tabla de feriados** (esquiva entera la corrección del Labor Day) y
hereda gratis la propiedad que la T110 ya se ganó: un ticker sin otro frame queda afuera solo,
sin umbrales inventados.

**Precondición que queda escrita para quien lo tome:** `_busday_lag` (`:490`) no tiene
calendario de feriados y hoy sobre-cuenta 1. En `stale_artifacts` es inocuo —las dos fechas
salen del mismo cohorte y el guard es relativo— pero **un guard calendario ingenuo se volvería
ruidoso alrededor de cada feriado**. Es la segunda razón para ir por el hermano y no por el
almanaque.

**Y el patrón ya es idiomático en el repo:** `ui/paper/equity_chart.py:62` (`overlay_is_stale`,
T22) compara el último close de SPY contra el último `snapshot_at`. Comparar frescura contra
algo de afuera del dato no sería inventar nada.

---

## 4. Lo que se revisó y NO dio hallazgo

Los descartes van con su motivo para que la próxima corrida no los vuelva a levantar.

**Los ocho `except` amplios y mudos del camino de decisión:**

| ubicación | por qué NO es hallazgo |
|---|---|
| `engine.py:282` `_is_market_open_safe` | envuelve a `is_market_open()`, que es **datetime puro**, ya falla cerrado y **con motivo logueado** (T104). La rama de excepción es prácticamente inalcanzable. |
| `scheduler.py:134` `_is_market_open_now` | ídem. |
| `engine.py:310` `_estimate_book_sigma` | **mi hipótesis inicial era falsa**: no alimenta el overlay de sizing sino `record_equity_snapshot` (`:1365-1366`), o sea telemetría. |
| `engine.py:623` nota de R:R | display. |
| `engine.py:842` y `:850` | telemetría de log, **declarada best-effort en el comentario** (T25a/T67). |
| `gates.py:561` `recent_adv_dollars` | **el caller sí se entera**: la T103 dejó en Gate 3b un warning explícito para `adv is None`, con la condición escrita al lado *«para que no puedan derivar por separado»*. |
| `costs.py:256` | fallback del plan de comisiones ante un `settings.get` que falla; inalcanzable en la práctica. |
| `harness_config.py:2397` `_read_owner` | describe el dueño de un lock para un mensaje de error. |

**Otros sub-barridos limpios:**

- **Los guards de las tareas 110 y 113 SÍ están cableados a los 27 lectores.**
  `announce_artifacts` **compone** a `announce_continuity` y `announce_mixed_scale` en vez de
  pedir un call site nuevo — que es la lección de la 97 y la 101 aplicada al diseño. Mi barrido
  inicial los dio en «0 runners» porque miraba sólo `scripts/`: **el instrumento estaba mal, no
  el repo.**
- **Los guards de población tienen su contraprueba de «no pasó verde por estar vacío».** Mi
  detector marcó cuatro sospechosos y **los cuatro eran falsos positivos míos**: la 99 escribe
  su contraprueba con otra forma (`py.exists()` por nombre, no `len(...) >= N`) y los otros tres
  no son guards de runners.
- **El circuit-breaker de throttle no es mudo:** loguea apertura, escalada y cierre a
  `warning`, y los chequeos repetidos a `debug` **a propósito**; tiene sonda canaria (SPY) para
  cerrarse solo.
- **Los otros dos guards que globean `run_*.py`** (`test_repro_literales_t71.py:36` y
  `test_harness_config.py:589`) tienen la misma ceguera de prefijo pero **hoy sin defecto vivo**:
  ningún archivo fuera de `run_*` tiene ancla de reproducción ni ancla de ventana. Queda dicho
  para que la 141 los cubra de paso.

---

## 5. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [G-2] El guard de frescura es ciego al atraso uniforme | **ALTA** | **140** COHORTE-UNIFORME |
| [G-1] El guard del store elige por prefijo de nombre | MEDIA-ALTA (latente) | **141** STORE-PREFIJO |
| [G-3] `cross_period_gaps` tira la evidencia del hermano nuevo | MEDIA-ALTA | **139** XPERIOD-COLA |

Tres hallazgos, tres filas, ninguna vacía. **La 139 va primero** aunque su severidad sea menor:
es el mecanismo con el que se cierra la 140, y hacerla al revés significaría cablear un
calendario de feriados que la 139 vuelve innecesario.

## 6. Limitaciones

1. **No se corrió ningún harness** ni se re-midió ningún veredicto.
2. **El `5y` es demostración mecánica, no un número contaminado hoy**: ningún runner con guard
   lo usa por default.
3. **[G-1] es latente**: el store está completo hoy (`signal_store_gaps` = 0).
4. Los guards de UI, del scheduler más allá del horario, y los de precio (114/127, tocados hace
   días) quedaron fuera del alcance.
