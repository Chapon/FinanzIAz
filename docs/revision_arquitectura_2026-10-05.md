# Revisión de arquitectura — 2026-10-05

Tarea **313**. Pedido de Chapa (2026-10-05): *«¿tenemos una auditoría de arquitectura o performance? ¿sería necesaria?»* → *«hacerlo»*. READ-ONLY. Es la segunda revisión, después de `docs/architecture_review_2026-07-07.md`, y **no** es un área nueva de `/audit`: la arquitectura no caduca sola como un número o un cache, se mueve con decisiones grandes. Kill-criteria congelado antes de abrir el código: `docs/revision_arquitectura_killcriteria_2026-10-05.md`.

**Resultado:** 3 hallazgos (0 CRITICAL, 0 HIGH, **1 MEDIUM**, 2 LOW). Ninguno llegó a HIGH, así que la fase del `verificador` no aplicó. El veredicto de julio (*«sana y por encima del estándar»*) se sostiene: lo que cambió desde entonces se agregó en módulos propios (`dividends.py`, `splits.py`, `cuadre.py`, `scan_candidates.py`, `spinoffs.py`) y con guards. Lo que falta son **decisiones escritas**, y un diseño, el de la 196, antes de construir.

---

## 1. Hallazgos

### [R-1] El diseño de la 196 cubre cómo ESCRIBE la nube y no cómo LEE la app: credenciales, dependencia, claves de la tabla y retención no están decididas, y el doc sigue recomendando la Pi
Severidad: **MEDIUM** · Confianza: **ALTA** · Parte 3

- **Ubicación:** `docs/harvest_nube_t196_2026-09-14.md`. Se escribió cuando la recomendación era una máquina propia (§8 *«Recomiendo una máquina propia siempre prendida»*); la rama AWS + DynamoDB se eligió el 2026-10-01 (decisión en la 196 del backlog) y el doc no se actualizó. La 245 dice *«el transporte lo define la 196»*.
- **Evidencia:** en el doc, `grep -c -i` de `boto3`, `IAM`, `credencial`, `access key`, `partition`, `sort key`, `TTL` y `backup`: **0** en todos. `boto3` no está en ningún `requirements*`. El probe (`scripts/probe_yahoo_datacenter_t196.py`) no escribe ni lee DynamoDB.
- **Lo que falta decidir antes de escribir el recolector:**
  1. **Credenciales de la app.** La app en Windows tiene que leer DynamoDB: un usuario IAM de **sólo lectura de esa tabla**, con las keys en el entorno de Windows como `FINNHUB_API_KEY` — **nunca** en el repo, que es **público** (la 272 ya revisó secretos en la historia).
  2. **La dependencia.** `boto3` entra a `requirements.txt` y al lock (la 284), o el lector usa la API HTTP firmada a mano. Decidirlo con el tamaño medido.
  3. **Las claves de la tabla.** Es la decisión que más cuesta cambiar después. Con la clave por `snapshot_date` (o por día de captura), *«bajar lo pendiente»* es un `Query` desde el cursor. Con la clave por ticker, es un `Scan` de la tabla entera en cada arranque. Con los números del propio doc (§4.1: ~66.000 ítems/mes, ~215 MB/año) y las 25 RCU gratuitas (~200 KB/s en lectura eventual), un `Scan` completo tardaría del orden de **18 minutos por cada año de datos acumulados**, y creciendo. Es una estimación de orden de magnitud sobre las cifras del doc, no una medición.
  4. **Retención.** Si lo importado se borra (TTL de DynamoDB, gratis) o se queda. Sin TTL, la tabla crece sin techo dentro de los 25 GB; con TTL, la DB de la app pasa a ser el único registro, y eso tiene que estar dicho (DynamoDB sin PITR no tiene backup gratis).
  5. **El cursor** (§6.3: *«importado hasta X»*): dónde vive (¿en `finanzias.db`?) y qué pasa si la app importa a medias.
  6. **Dónde corre la sincronización:** en un worker, no en el hilo de la GUI (la 304 existe porque la GUI se trabó).
- **Impacto:** hoy, ninguno: no hay código. Si se construye el recolector antes de fijar las claves y el cursor, la forma de la tabla queda atada a la primera versión, y la 245 (sincronizar al arrancar) hereda un `Scan` que crece con el tiempo.
- **Acción:** completar el diseño del lado que lee, como sección nueva del doc de la 196 o como doc propio, **antes** del recolector. Se puede hacer hoy: no depende del probe.

### [R-2] El ciclo de vida del modelo ML —la propuesta #2 de julio, impacto ALTO— no tiene tarea ni decisión, y su motivo principal se cayó sin que nadie lo escribiera
Severidad: **LOW** · Confianza: **ALTA** · Parte 1

- **Evidencia:** julio propuso entrenar offline y servir un artefacto versionado, como *«prerequisito práctico de la tarea 7»*. La tarea 7 cerró **NO-SHIP** el 2026-07-20. En el backlog no hay ninguna tarea ni decisión sobre el ciclo de vida (`grep` de *lifecycle*, *entrenamiento offline*, *model_version*, *artefacto versionado*: vacío). En el código, el cache de XGBoost sigue siendo **sólo en memoria** (`analysis/ml_signals.py:175`, `_XGB_CACHE`, LRU de 192), así que cada arranque re-entrena los 127 modelos: el primer scan de hoy registró `XGB entrenados=127` con **76 s** de `analyze`, contra 3 s en los scans siguientes.
- **Impacto:** chico y sin cambio de conducta (134 s contra un intervalo de 15 min). Lo que no existe es la trazabilidad que julio pedía: *«qué modelo decidió esta orden»* no queda en la orden. Lo que importa es que una propuesta de impacto ALTO desapareció sin decisión: la forma de la 97 (*«declarado no es cableado»*) aplicada a una revisión.
- **Acción:** que Chapa decida y quede escrito: adoptarla (con un motivo nuevo, porque el de la tarea 7 ya no está) o descartarla.
- **Decisión de Chapa (2026-10-07, tarea 315): DESCARTADA.** Mientras XGBoost no gane peso en una decisión, lo único que se pierde es latencia de arranque. Se reabre si un modelo pasa a decidir órdenes: ahí sí hace falta saber qué modelo decidió cada una.

### [R-3] La recomendación de julio de partir los archivos grandes *«cuando se los toque»* no tiene decisión; se tocaron decenas de veces y crecieron
Severidad: **LOW** · Confianza: **ALTA** · Partes 1 y 2

- **Evidencia** (`git log --since=2026-07-07`, `wc -l`, `ast` para las funciones):

  | archivo | 07-07 → hoy | commits desde 07-07 | función más larga |
  |---|---|---|---|
  | `analysis/harness_config.py` | **no existía** → 3.394 | **64** | `deviations_keyed`, 205 |
  | `data/yahoo_finance.py` | 1.533 → 3.001 | 24 | `get_bulk_prices`, 167 |
  | `paper_trading/engine.py` | 1.702 → 2.469 | 25 | **`run_scan`, 580 → 853** |
  | `analysis/ml_signals.py` | 1.499 → 1.684 | — | `detect_market_regime`, 127 |
  | `ui/paper_tab.py` | 1.468 → 1.520 | — | `_build_ui`, 310 |

  (`scripts/run_stop_value_t37.py`, 1.598, es un runner de una tarea cerrada: no es código vivo.)
- **El costo concreto, medido, es bajo, y por eso es LOW:**
  - los pasos que se agregaron al scan viven en **módulos propios** (`dividends.py`, `splits.py`, `cuadre.py`, `scan_candidates.py`, `spinoffs.py`); `run_scan` creció sobre todo con el pegamento y el logging de esos pasos;
  - los dos defectos de mezcla de `yahoo_finance.py` —el fetch y la escritura del cache en el mismo `try` (**234**) y el fetch dentro de una transacción de escritura (**237**)— se arreglaron en su lugar, con un barrido de la misma forma;
  - testear `run_scan` es caro pero está contenido: 21 archivos de test lo llaman, con los proveedores inyectados, y los monkeypatches de `engine.*` se concentran en uno (`get_strategy_fn`, 46 veces).
- **Lo que sí pesa:** `harness_config.py` concentra **2,5×** el churn del segundo archivo, y mezcla cinco cosas: los espejos `LIVE_*`, los textos de los desvíos, los guards de calidad de los artefactos, el parseo y la huella del universo, y el chequeo de reproducción. No se encontró un defecto atribuible a esa mezcla; los cinco guards de texto que lo rodean (130, 185, 231, 233, 242) son por lo que dicen los textos, no por dónde viven.
- **Acción:** que Chapa decida y quede escrito. Mi recomendación: **no partir nada ahora**, por el *«no refactorizar por deporte»* de julio y porque el costo medido es bajo. Si se toca `harness_config.py` por algo más, separar los guards de artefactos (`cohort_*`, `announce_*`, `mixed_scale_*`, `signal_store_*`) a su propio módulo, que es el corte más limpio.
- **Decisión de Chapa (2026-10-07, tarea 315): no partir ahora; partir al tocar.** Para que no se repita lo de julio (*«cuando se los toque»* sin dejarlo donde se lee), la regla quedó en el docstring de `analysis/harness_config.py`, que es lo que lee quien lo abre.

---

## 2. Seguimiento de la revisión de julio, propuesta por propuesta

| propuesta (julio) | estado verificado | dueño |
|---|---|---|
| #1 Parquet + DuckDB | **hecha** (ARQ1, `d2c6090`; el rollback a `sqlite` caducó por decisión, la 77) | — |
| #2 Ciclo de vida del modelo ML | **abierta, sin tarea ni decisión** | → [R-2] |
| #3 Provider con fallback + sanity bilateral | **parcial con decisión** (ARQ3 / tarea 14: la mitad histórica bloqueada por datos; la segunda opinión de tres fuentes shipeada y **apagada** en vivo, en *Acciones manuales*) | backlog |
| §4 Upsert de `earnings_cache` | **hecha** (OPS1-b; `data/yahoo_finance.py:2289`) | — |
| §4 Cola única de escritura | **no hizo falta como estaba planteada**: era condicional (*«si tras #1 el lock persiste»*); los locks que aparecieron (235, 237) se arreglaron por su causa | — |
| §4 Telemetría de scan por fase | **hecha** (OPS1-c; `fetch / analyze / process` en cada línea de scan) | — |
| §5 pyqtgraph | **en *Ideas*** (opcional, UX) | backlog |
| §6 Partir archivos grandes | **sin decisión** | → [R-3] |
| §6 hypothesis | **en *Ideas*** | backlog |
| §7 Structured outputs + polaridad | **hecha** (OPS1-a; JSON schema en `data/catalyst_classifier.py:245`; la escala de 7 niveles, 258/259/302) | — |
| §7 Eval del classify antes de cambiar de modelo | el modelo **no se cambió** (sigue `qwen2.5:14b`); la 255 y la 258 midieron la salida | — |

**§8, *«lo que NO cambiaría»*, re-verificado:**
- *PyQt6 + QThread + QTimer*: sigue valiendo; la 304 agregó un vigía, no cambió el modelo.
- *SQLite para lo transaccional*: sigue valiendo (WAL; los locks se arreglaron por su causa).
- *Alembic, settings, capas, suite*: sigue valiendo (0017 hoy; 4.361 tests).
- *«No microservicios, no web, no docker»*: **la 196 lo reemplaza a sabiendas**, por decisión de Chapa del 2026-10-01 (sólo la recolección, sin decisiones ni la DB). No es un hallazgo: es una decisión escrita que contradice una foto de julio.

## 3. Lo que salió limpio

- **Parte 1, en la otra dirección:** ninguna parte del código de hoy contradice un *«no cambiaría»* de §8 sin una decisión escrita.
- **Parte 2, en la otra dirección:** el churn fuera de los archivos grandes se concentra en `config/settings_manager.py` (21), `analysis/portfolio_sim.py` (18), `scripts/harvest_catalysts.py` (15) y los runners de tareas cerradas (13–16 cada uno). Ninguno tiene una función o una mezcla que haya producido un defecto en el backlog.
- **Parte 3, lo que el doc de la 196 sí resuelve bien:** costo contra el always-free con margen declarado (§4.1), el techo de 15 min por lotes (§7.1), sin VPC (§7.2), el universo publicado desde la app (§7.3), la key de Finnhub en SSM (§7.5), un solo recolector del consenso (§7.6), la marca de captura en la nube (§6.1), y el UNIQUE del consenso como prerrequisito (la 203, cerrada).

## 4. NO mirado, con motivo

- **`ui/` más allá de `paper_tab.py`:** la parte 2 cortó por tamaño (> 1.500 líneas) y por churn; la UI no aparece en el top de churn.
- **Rendimiento:** es un área de `/audit` (`rendimiento`) y salió limpia en la tanda de hoy.
- **El costo real de DynamoDB:** no hay nada desplegado. La cifra de [R-1] es una estimación sobre los números del doc de la 196.

## 5. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| [R-1] el diseño del lado que lee de la 196 (credenciales, `boto3`, claves, retención, cursor, worker) y el §8 del doc desactualizado | **314** |
| [R-2] el ciclo de vida del modelo ML sin decisión | **315** |
| [R-3] partir los archivos grandes sin decisión | **315** |
