# Auditoría — tanda completa (las 12 áreas), 2026-10-20

READ-ONLY. Skill `auditoria`. Kill-criteria **congelado el 2026-10-20, antes de abrir ningún
archivo**, para las 12 áreas juntas.

> **Estado: CORRIDA el 2026-10-20 (ver *Corrida*, al final).** Lo que sigue es el criterio tal como se congeló.
>
> **Estado original: PENDIENTE de correr (tarea 373).** Chapa aprobó este kill-criteria el 2026-10-20 y la
> corrida se difirió por falta de tiempo. Al correrla no se recalibra: si un criterio tiene que
> cambiar, el cambio va escrito al lado del original, con su motivo y su fecha. Donde dice *«hasta
> hoy»*, se lee *hasta el día de la corrida*.

**Alcance general.** Ninguna corrida es exhaustiva: cada área declara qué mira y qué no, y el
alcance real se escribe al final **como lista**, no como conteo. La ventana de log, de DB y de
backlog es **desde la tanda anterior** (la última `docs/auditoria_*` con fecha, a determinar
por contenido) **hasta hoy**. Para cada área, «barrido limpio» se escribe en las dos
direcciones: *lo escrito es falso* y *lo verdadero no está escrito*.

**Primero, antes de cualquier área (D, tarea 300/307):** `check_ci.py --ultimo` con su sha
comparado contra `origin/main`, y `git status`.

---

## A. claims

- **Se mira:** `CLAUDE.md`, la cabecera y *En curso* del backlog, las skills de
  `.claude/skills/` y `.claude/commands/` (lista en disco, no un conteo), y los claims que
  cerraron las tareas desde la tanda anterior (buscados con `grep` en todo el repo). Los
  procesos que están declarados en varios lugares (el done, el cierre de una tarea, el
  arranque de sesión, `/ship`) se comparan **lugar contra lugar**. Los contratos de proceso
  (*En curso* máx. 1) se comparan contra lo que se cuenta en el archivo.
- **Afuera:** los docs de análisis históricos (`docs/*_2026-*.md` que no sean de referencia),
  salvo que un archivo vivo los cite como actuales.
- **Limpio si:** (→) ningún número o afirmación de un doc vivo contradice el código, la DB o
  el estado medido hoy; (←) ningún comportamiento que una tarea cerrada desde la tanda
  anterior agregó falta en el doc que declara cubrirlo, con la granularidad que ese doc
  promete; y ningún par de lugares describe el mismo proceso de dos formas distintas.

## B. muestra

- **Se mira:** las comparaciones `len()`/`>=`/conteos en `scripts/` y `analysis/` que deciden
  *«ya está completo»* o *«esta es la muestra»*, y cada operación que movió la muestra desde la
  tanda anterior (refresh del cohorte, precómputos), cruzada **por contenido** contra la
  evidencia de que algo se re-corrió después.
- **Afuera:** tests, salvo los guards de inventario.
- **Limpio si:** (→) ningún chequeo por cantidad que decida completitud sigue siendo verdadero
  cuando la ventana rueda; (←) toda operación que movió la muestra tiene evidencia de
  re-verificación de los veredictos que pudo invalidar.

## C. desvios

- **Se mira:** `deviations_keyed()` contra la config del engine (el `settings.json` vivo, la
  cuenta 2 en la DB) y contra `harness_config`/`portfolio_sim`/`replay_cycle`; el texto de cada
  desvío declarado contra el **valor vivo** de cada perilla que lo gobierna, sub-perillas
  incluidas; los números de magnitud y de frecuencia contra su marco y contra el registro
  (`paper_equity_snapshots`); las clasificaciones `NO_MODELABLE` contra el valor vivo.
- **Afuera:** medir el efecto de un desvío nuevo en un veredicto (eso es una tarea de
  medición).
- **Limpio si:** (→) ningún texto de desvío afirma algo del motor que el valor vivo o el
  registro contradiga; (←) ninguna diferencia engine↔harness queda sin clave en
  `deviations_keyed()`.

## D. guards

- **Se mira:** primero el **resultado** del CI (último run de `main`, su sha contra
  `origin/main`, y cuántas tareas se cerraron desde el último verde); después `ci.yml` contra
  los cuatro comandos del done; y los guards de proceso (`scripts/check_*.py`) y los tests-guard
  agregados o tocados desde la tanda anterior, **mutados en el sentido del falso positivo**
  (mutaciones sobre copia, en el scratchpad, nunca en el repo).
- **Afuera:** los guards que no cambiaron desde la tanda anterior y que esa tanda ya mutó (se
  cita).
- **Limpio si:** (→) el CI de `origin/main` está verde y es del sha de `main`, y ningún guard
  pasa en verde con la declaración contraria; (←) ningún punto ciego que un guard declara en su
  docstring queda sin tarea.

## E. estado

- **Se mira:** `data/parquet/`, `data/pit_signals/`, `precompute_pit_risk_score`,
  `earnings_cache`, los archivos de universo y los artefactos del cohorte: quién los regenera,
  su frescura comparada con la de sus pares, y las operaciones manuales periódicas que dejaron
  las tareas cerradas (archivar la cinta intradía de `price_cache`, rotar, compactar).
- **Afuera:** los backups (eso es H).
- **Limpio si:** (→) ningún store queda atrás de sus pares sin que algo lo diga; (←) toda
  operación periódica tiene un disparador, o una tarea que lo pida.

## F. pantalla

- **Se mira:** los números de Home, Paper y Métricas que se leen para decidir, trazados hasta
  su tabla y columna y recalculados a mano contra la DB en solo lectura (copia), con atención a
  las selecciones por defecto (cuenta, ventana, benchmark), a cómo se pinta un vacío y, en las
  curvas, a que cada ticker tenga historia de precios desde su primera compra.
- **Afuera:** estética y layout; las pestañas Analysis y Noticias más allá de lo que se tocó
  desde la tanda anterior; no se lanza la app.
- **Limpio si:** (→) cada número mirado coincide con su recálculo y con su rótulo; (←) ningún
  vacío o dato viejo se pinta como si fuera un dato.

## G. cuentas

- **Se mira:** el cuadre de caja y de acciones de la cuenta 2 (y de la 1, que tiene que quedar
  quieta: nadie la toca), con el slippage dentro del `fill_price`; `max_positions` y la caja
  no negativa en `paper_orders`/`paper_equity_snapshots`; los dividendos que el motor **debió**
  acreditar, contados con la propia función del motor contra `paper_dividend_credits`; la
  cartera real (cantidad y `avg_buy_price` contra `transactions`, y la fecha de cada
  transacción contra el rango del día).
- **Afuera:** si las decisiones fueron buenas.
- **Limpio si:** (→) todo cuadra al centavo y ningún límite se violó en la ventana; (←) ningún
  flujo que el motor declara registrar falta en su ledger.

## H. operacion

- **Se mira:** `~/.finanzias/finanzias.log*` y `catalyst_harvest.log` en la ventana: los
  mensajes agrupados por frecuencia (retries sin tope, avisos que no escalan); la evidencia de
  que cada job del scheduler corrió en cada día hábil (por calendario de la bolsa, no por
  reloj; log en hora local y DB en UTC); los backups de `backups/` (que se toman, que rotan y
  que **se pueden restaurar**: se verifica abriendo una copia en el scratchpad, sin tocar la DB
  viva); el estado de `alembic` de la DB; Slack sólo por lo que dice el log (sin postear).
- **Afuera:** la infraestructura de la 196; disparar jobs o restaurar de verdad.
- **Limpio si:** (→) ninguna firma se repite sin tope y ningún día hábil quedó sin scan sin que
  algo lo diga; (←) el último backup restaura a un esquema que `init_db` reconoce.

## I. datos

- **Se mira:** la distribución de tipo/polaridad/intensidad de las noticias clasificadas en la
  ventana; la cobertura por ticker del universo vivo en `analyst_estimate_snapshots` y en los
  facts de EDGAR; una muestra chica (≤10 filas) contrastada contra su fuente primaria cuando se
  pueda sin red de escritura; la consistencia entre fuentes cuando hay dos para el mismo dato.
- **Afuera:** si el dato predice algo.
- **Limpio si:** (→) ningún campo degenerado o hueco de cobertura nuevo que no esté ya en una
  tarea; (←) ningún ticker del universo vivo llega al screen sin datos sin que se avise.

## J. rendimiento

- **Se mira:** la duración de los scans en el log contra `paper_scan_interval_minutes`; los
  `database is locked`; `EXPLAIN QUERY PLAN` de las consultas del scan y de los refrescos de
  Home/Paper sobre una copia de la DB; el techo de tiempo de cada job de fondo.
- **Afuera:** la optimización que no cambia conducta.
- **Limpio si:** (→) ningún scan tarda más que su intervalo, no hay locks en la ventana y no
  hay `SCAN TABLE` sobre una tabla que crece en el camino caliente; (←) todo job de fondo tiene
  techo de tiempo.

## K. dependencias

- **Se mira:** los imports de terceros (opcionales incluidos) contra `requirements*.txt` y el
  lock; lo declarado contra lo instalado en la Anaconda y en el `.venv`; el motivo de cada pin
  (y si hay un techo faltante: la 348).
- **Afuera:** actualizar; las divergencias que una tarea decidió (la 284), salvo un dato nuevo.
- **Limpio si:** (→) todo import tiene su declaración y todo pin tiene un motivo que sigue
  vigente; (←) no hay ningún paquete del que dependa la conducta sin pin ni techo.

## L. logs

- **Se mira:** el censo de toda firma WARNING+/traceback de la ventana, normalizada, separada
  por origen (`[proceso: …]`), y clasificada como conocida (con su tarea **y su tasa** contra la
  del cierre), explicada (con el motivo verificado contra el código) o desconocida; las firmas
  que dejaron de aparecer después de su cierre; los `py.warnings` que entraron desde la 372; lo
  que la app escribe por fuera de `finanzias.log`.
- **Afuera:** el contenido de los INFO.
- **Limpio si:** (→) ninguna firma queda sin clasificar y ninguna conocida aparece más que lo
  que midió su cierre; (←) ningún camino de fondo traga a `debug` lo que debería verse.

---

**Fase adversarial:** todo HIGH/CRITICAL va al `verificador` con el mandato de **refutarlo**,
atacando primero el **instrumento**. Si no puede correr, el informe lo dice.

**Cierre:** la tabla `hallazgo → tarea`, verificada de a una contra `docs/BACKLOG.md`.

---

# Corrida

Arranca el **2026-10-20 a las 12:36 locales**, por **L**, porque Chapa avisó *«veo muchos errores en
los logs»*. Antes de cualquier área: `check_ci.py --ultimo` → `bae364f` **VERDE**, el sha de
`origin/main`; `git status` limpio. El criterio de arriba no se tocó.

## L. logs — corrida del 2026-10-20

**Ventana:** `~/.finanzias/finanzias.log` desde la línea `2026-10-19 12:51:05`, donde cortó la
tanda de logs anterior (`docs/auditoria_logs_2026-10-19.md`), hasta `2026-10-20 12:35:55`, la
última línea del log: **884 líneas, 297 WARNING+ en 27 firmas y 23 tracebacks en 8 firmas**. Ninguna
lleva marca `[proceso: …]`: todo es de la app. Dos instancias: la del **19/10 16:26:38**, que tenía
la 366 y la 369 pero **no** la 370, la 371 ni la 372 (sus commits son de las 16:48 en adelante), y la
del **20/10 12:35:30**, que vivió ~5 s.

**El instrumento:** el censo normaliza los tickers a `TK`, así que se contó por ticker cada firma que
importaba (lección de la tanda anterior). Las 14 filas de `failed_tickers` salen de una **copia** de
`finanzias.db` + `-wal` en el scratchpad, no de la viva.

### [L-1] Un corte de DNS al salir de la suspensión deja 14 tickers sanos en `failing`, y uno es una posición abierta de la cuenta 2 — **MEDIA** (era HIGH; la bajó el `verificador`) → tarea **374**

- **Qué se vio.** 2026-10-20 00:19:39: el Vigía avisa 21.895 s sin latir (suspensión). En los 3 s
  siguientes, antes de que vuelva el DNS, `fast_info` devuelve `last_price=None` (yfinance se traga
  el `DNSError` y escribe `$TK: possibly delisted`) y `_fetch_ticker_info`
  (`data/yahoo_finance.py:1538-1567`) lo anota como *«Sin precio (símbolo posiblemente
  deslistado)»*. Con el breaker todavía **cerrado** (abre recién a las 00:19:42), `_record_miss`
  (`:382-393`) llama `record_failure` → `failing`. En la tabla, 14 filas de las 03:19:40–42 UTC:
  **ABBV, ABT, ACN, ADBE, AEP, AMD, AMGN, AMZN, AVGO, AXP, BA, BAC, BKR, BMY**, las 14 de la
  watchlist de la cuenta 2.
- **Por qué importa.** `get_failing_set()` las saltea en `get_bulk_prices` y en el batch histórico
  durante `REINTENTO_DIAS = 7` (`data/failed_tickers.py:222`). **AMGN es la posición abierta id 129
  (12 acciones).** ~~Hasta el 2026-10-27, cada scan la daría «SIN evaluar»~~ — **refutado por el
  `verificador`, verificado contra el código:** la estrategia de la cuenta 2 pide la historia por
  ticker (`paper_trading/strategies.py:395` y `:442`) con `get_historical_data`, que **no** consulta
  `get_failing_set`, y su `record_success(…, "historical")` borra la fila (`data/failed_tickers.py:198-200`).
  Así que los 14 se curan en el **primer scan con red**, y el daño es ese scan: AMGN sin precio, sin
  stop ATR y con la equity a `avg_cost` (`paper_trading/engine.py:962-975`). Lo que sí queda 7 días
  es lo que está **fuera** del universo paper: EMBJ y MLTX (cartera real) entraron igual con la
  suspensión del 09/10 y siguieron hasta el 19/10 (es el caso que ya citó la 366). **Y es frágil:**
  lo que cura es una asimetría (el batch saltea `failing`, el fetch por ticker no); si alguien la
  «arregla», el daño pasa a ser de 7 días. Los otros 13 quedan afuera del screen. **Y no se ve:** que 14
  tickers entren a `failing` en el mismo segundo no escribe nada; el único rastro son las líneas de
  yfinance, iguales a las de un deslistado de verdad.
- **Por qué no lo vio la corrida anterior:** (c-nuevo para el universo paper). Según los backups
  (`verificador`), las suspensiones del 14/10 fallaron con el lote **entero**, que se marca
  `transient`. La del 09/10 dejó EMBJ y MLTX en `failing`, y la 366 lo leyó como un ticker que no
  se reintentaba, no como un efecto del corte de red.
- **Fase adversarial (`verificador`): PARCIAL.** Confirmado: las 14 filas, que vienen sólo de
  `_fetch_ticker_info` (`data/yahoo_finance.py:1540`), sin otro proceso y con DNS caído en las tres
  fuentes. Refutado: la duración del daño en la cuenta 2 (ver arriba). Severidad: HIGH → **MEDIA**.

### [L-2] Un cierre que no pasa por `main.py:113` deja apagada la bandera de la tarea 82, y el arreglo de la 289 cubre uno solo de los cuatro caminos que fallan al cerrar — **MEDIA** → tarea **375**

- **Qué se vio.** La instancia de las 12:35:30 entra en *interpreter shutdown* a las 12:35:35. En los
  20 s siguientes escribe **81 WARNING** `ui.ticker_tooltip: fetch failed … cannot schedule new
  futures after (interpreter) shutdown`, **12 ERROR con traceback** `Bulk dividend calendar fetch
  failed` (`get_bulk_dividend_calendar` → `_run_with_timeout`), **1 ERROR con traceback**
  `SignalWorker: error in do_work()` (`ui/portfolio_tab.py:172` → `get_historical_data_batch`) y, al
  final, un **CRITICAL** `Uncaught exception`: `RuntimeError: wrapped C/C++ object of type
  _FetchSignals has been deleted` en `ui/ticker_tooltip.py:85`, que el hook global convierte en el
  diálogo *«Error inesperado»*.
- **Lo que está firme.** (1) El `emit` de la línea 85 corrió a las 12:35:55, así que
  `_SHUTTING_DOWN` **se leyó falsa** veinte segundos después de que empezara la finalización, y la
  protección de la 82 no actuó. (2) Antes de ese CRITICAL no hay ningún otro.
- **Lo que no está resuelto: por qué se leyó falsa.** Chapa: *«la cerré nomás»*, o sea un cierre
  normal de la ventana, que pasa por `_tooltip_shutdown()` (`main.py:110-115`) y la prende. Eso
  descarta la primera hipótesis de este informe (un `KeyboardInterrupt` que saltara la línea 113).
  **Hipótesis que queda, sin verificar:** los hilos del `QThreadPool` no son hilos de `threading`,
  así que la finalización no los espera; siguen corriendo mientras Python 3.12 limpia los módulos,
  que pone los globales en `None`, y `None` es falso. Si es así, la bandera de la 82 sólo protege
  mientras el módulo vive. **Y tampoco está escrito el aviso del drenado** (`cierre: N fetch(es) …`),
  que tendría que haber salido si el pool tenía trabajo: eso también lo tiene que explicar la
  reproducción. (3) Con cualquier cierre, también el normal, `_es_cierre_del_interprete`
  (tarea 289) sólo se consulta en `get_bulk_prices` (`data/yahoo_finance.py:2642`, usada sólo en `:2755`): el
  calendario de dividendos, el worker de Cartera y el tooltip escriben ERROR/WARNING por ticker.
- **Por qué no lo vio la corrida anterior:** (c-alcance). La 289 midió el único caso que había en el
  log (`get_bulk_prices`, 2026-09-30). Ésta es la primera vez que el cierre agarra el arranque, con
  todos los workers en vuelo.

### Censo: las 27 firmas WARNING+ y las 8 de traceback

| Firma (normalizada) | Líneas | Clase | Motivo |
|---|---|---|---|
| `ui.ticker_tooltip: fetch failed … after (interpreter) shutdown` | 81 | **[L-2]** | |
| `Bulk dividend calendar fetch failed` + `RuntimeError @ _run_with_timeout` | 12 + 13 tb | **[L-2]** | 12 del calendario, 1 del worker de Cartera |
| `SignalWorker: error in do_work()` | 1 | **[L-2]** | |
| `CRITICAL Uncaught exception` + `UI error 'Error inesperado'` (`_FetchSignals` borrado) | 2 + 2 tb | **[L-2]** | |
| `yfinance: $TK possibly delisted (1y/5d)` del 20/10 00:19 | ~45 | **[L-1]** | DNS caído; 14 terminaron en `failing` |
| `yfinance: $WBD possibly delisted (5d)` (+ `[repetido N veces]`) | 26 + 4 | conocida (369) | Explicada: el `2y` de una fila lo escribió el código viejo a las 16:07, y los scans de 16:28, 16:42 y 17:06 lo encontraron dentro de la TTL de 1 h. La detección nueva todavía no tuvo ocasión de correr; **verificación en vivo pendiente** en el primer scan con mercado abierto. |
| `news_sources: … failed for TK` (yfinance/SEC/Finnhub) + 3 ERROR `falla de red` + resumen `fallas de red sin traceback` | 117 + 3 + 1, 8 tb | conocida (289, 353) | Un traceback por fuente, como fijó la 289 (los 8 tb son las 3 cadenas encadenadas). Es la misma ventana de DNS de [L-1]. |
| `Harvest … FUENTES CAIDAS 40/127 … sin datos 40` (00:23) | 1 | conocida (353) | La misma ventana de DNS; la app no volvió a correr para reintentarlo. |
| `XGBoost TK: unstable model` | 12 | conocida (364) | Todas en el primer scan tras el reinicio (16:27) y **0** en los siguientes: la misma tasa que midió la tanda del 19/10. |
| `Harvest … FUENTES MUDAS: yfinance_news 0/127` | 3 | conocida (357) | 13:10–15:11, código viejo. **Dejó de aparecer:** el harvest de las 16:32, ya reiniciado, dio **4/4 limpias**. |
| `Harvest … degradadas: yfinance_estimates 6` (16:11) | 1 | explicada | Los dos 401 de crumb de las 16:06, en la misma corrida horaria. |
| `yfinance: HTTP Error 401 Invalid Crumb` / `User is unable to access this feature` | 1 + 1 | explicada | Crumb transitorio; `_TRANSIENT_HINTS` incluye 401 y el resumen del harvest lo cuenta como degradada. |
| `Throttle de Yahoo detectado — breaker abierto` / `se recuperó tras 0 min` (00:19) | 1 + 1 | conocida (370) | La instancia corría sin la 370. Lo que disparó el breaker fue el DNS, no un throttle (ver [L-1]). |
| `cachean la barra de la sesion de HOY` | 2 | conocida (243) | Por diseño. |
| `Nube — FUENTE NO DISPONIBLE` | 1 | conocida (356) | Falta el perfil (*Acciones manuales*). |
| `Vigía: la interfaz no latió durante 21895 s` | 1 | explicada | Suspensión del equipo. |

**Firmas que dejaron de aparecer tras su cierre:** *FUENTES MUDAS* (357) sí. Las de la 370, la
371 y la 372 no se pueden juzgar: ninguna instancia corrió ese código más de 5 s. **`py.warnings`
(372):** ninguno, por la misma razón.

**Alcance no mirado:** la consola (stderr) de la instancia de las 12:35; `congelamientos.log` más allá de su última entrada (00:19:39); los logs de
la Lambda.

**(←) Lo que debería verse y no se ve:** que una ráfaga de tickers entre a `failing` en el mismo
segundo no escribe nada propio (va con [L-1]).

**Confirmado en vivo después del informe (Chapa reabrió la app a las 16:07):** el primer scan
(16:08:56) dijo *«15/127 tickers sin precio — posiciones SIN evaluar (stops no corridos): AMGN»* y,
mientras analizaba, las filas se fueron borrando (AMGN, ACN, ADBE, AMD, AMZN y AVGO, las primeras).
Es exactamente lo que dedujo el `verificador`.

## Las otras once áreas — corrida del 2026-10-20, 16:00–16:40

**Ventana:** las tareas **350–372** (desde la tanda completa anterior, `docs/auditoria_tanda_2026-10-10.md`,
`1f67440`) y el estado vivo desde el 2026-10-10. **La DB** es una copia que se hizo con la API de
backup desde `mode=ro` a las 16:08, con la app **abierta** (Chapa la reabrió a las 16:07), más
consultas `mode=ro` sobre la viva para lo que cambiaba en el momento.

### [F-1] Un snapshot de equity con posiciones sin precio las guarda a COSTO, y Home, Paper y Métricas lo pintan como valor de mercado — **BAJA-MEDIA** → tarea **376**

- **Qué se vio.** El 13/10 los dos scans de la cuenta 2 (22:17 UTC) corrieron con **127/127 tickers
  sin precio** (el throttle de ese día). El snapshot que quedó, que también es el último del día y
  por eso el punto de Home, tiene `positions_value = 42.354,16`, que es **exacto** Σ acciones ×
  último fill de compra de las seis posiciones. Con los cierres del 13/10 de los frames `2y`, daba
  **42.432,37**. Hoy, el scan de las 16:08 dejó a AMGN a costo ($403,61 contra ~$441).
- **Por qué.** `record_equity_snapshot` (`paper_trading/account.py:288`) guarda lo que devuelve
  `compute_equity`, que marca a `avg_cost` lo que no tiene precio (`paper_trading/engine.py:977-980`
  lo dice para el scan). La fila no registra cuántas posiciones fueron a costo. Los lectores
  —`equity_diaria` (Home, 359), `get_equity_curve` (Paper), `analysis/metrics_panel.py:1185`
  (Métricas), `scripts/baseline_metrics.py`— no lo pueden saber. Home rotula esa curva *«Efectivo +
  posiciones a valor de mercado»* y la vista *invertido*, *«a valor de mercado, no a costo»*.
- **Y el mismo agujero en C:** `cobertura_de_scan` (`analysis/harness_config.py:476`) cuenta un
  snapshot como scan que **evaluó** las barreras, aunque una posición haya quedado sin precio. En la
  ventana pasó una sola vez dentro de la sesión (hoy, AMGN), y el número de `barrier_eval` es del
  02/10 y lleva fecha. Por eso no va como tarea aparte.
- **Lo que no se afirma:** que haya decidido algo mal. El breaker de drawdown
  (`paper_trading/dd_breaker.py`) lee snapshots, pero **nadie lo llama**. Lo que se ve afectado es
  la pantalla: el día queda con un retorno inventado (en el caso medido, −0,15% y su rebote) y el
  máximo drawdown puede tomar un falso mínimo.
- **Por qué no lo vio la corrida anterior:** (c-nuevo en parte). La curva de las cuentas paper en
  Home es de la 359 (15/10), y el snapshot a costo del 13/10 es de esta ventana. Pero `compute_equity`
  ya marcaba a costo antes: Paper y Métricas lo venían mostrando y ninguna corrida de `pantalla`
  cruzó un snapshot contra los cierres de su día (**c-metodo**).

### Barridos limpios (con lo que se miró)

- **D. guards.** CI de `main` **verde en los 45 runs desde el 10/10** (de `1f67440` a `bae364f`),
  sin un solo rojo, y el último es el de `origin/main`. `ci.yml` corre `ruff check`, `ruff format
  --check` y `pytest -m "not network"`; el cuarto comando del done es la suite sin estado vivo, que
  el CI cumple por construcción (176). Ningún `scripts/check_*.py` cambió en la ventana. Las
  tareas cerradas que agregaron detectores (350, 351, 353, 354, 357, 359, 360, 363, 366, 369, 370,
  371 y 372) dejaron escritas sus mutaciones, todas rojas; la 356, 362 y 364 siguen abiertas. **No
  hice mutaciones propias en el sentido del falso positivo**: ver *Alcance no mirado*.
- **A. claims.** `CLAUDE.md` contra la DB y el código: la cuenta 2 es `auto`, `equal_weight`, 10
  posiciones; hmm/stacking en `False` en `settings.json` y `default=True` en el `SettingSpec`
  (`config/settings_manager.py:623-637`, como dice la 181). El cierre con `check_ci.py --esperar`
  está descripto igual en `CLAUDE.md`, `/ship`, `finanzias-conventions`, `git-workflow` y `testing`.
  En la otra dirección: la única setting nueva de la ventana (`nube_sync_enabled`) está en
  `SETTINGS_REFERENCE.md`, `cloud_import_cursor` (0019) está en `DB_SCHEMA.md`, y la acción manual
  de WBD que pidió la 369 está en *Acciones manuales*.
- **B. muestra.** La única decisión de completitud nueva es el cursor de la nube (356):
  `dias_a_bajar` relee el último día importado (`desde = cursor`) y deduplica, así que un día
  parcial se completa en la sincronización siguiente. En la ventana no hubo refresh del cohorte (los
  `10y` y `data/pit_signals/` siguen con última fecha 2026-09-09 en los 126).
- **C. desvíos.** `deviations_keyed()` con la config de la cuenta viva: 16 claves. `dividendos`
  coincide con el registro (3 créditos, $93,96, cargados por la 350). La 369 saca del universo
  vivo a un ticker deslistado, pero el cohorte termina el 09/09, antes del deslistado de WBD, así
  que no es una diferencia que hoy exista. Lo de `barrier_eval` va con [F-1].
- **E. estado.** Las señales PIT y los `10y` del cohorte coinciden entre sí (09/09) y tienen su
  refresh propio. `harness_universe_live_acct2.txt` tiene 126 contra 127 de la watchlist: falta
  ASML, ya declarado en `analysis/harness_config.py:202`. La cinta intradía se archivó a las 00:19 y
  a las 16:07, con su job del scheduler.
- **G. cuentas.** Las cuentas 1 y 2 cuadran **al centavo** en caja (4.673,98 y 31,00) y en
  acciones. La cuenta 1 no tiene fills desde el 01/07. La cuenta 2: 10 posiciones de 10 como
  máximo, caja mínima 4,69 en 828 snapshots. Dividendos, con `creditos_pendientes` del propio motor
  sobre los fills (desde `PISO_DIVIDENDOS`): **0 pendientes** en las dos cuentas; los ex-dates de
  CSCO (02/10) y JPM (06/10) son anteriores a la compra. «Mis Acciones»: 10 abiertas, sus 20
  transacciones cuadran y no hay transacciones nuevas en la ventana. Hoy hubo dos ventas normales
  de la estrategia (SBUX y CSCO, 19:10 UTC).
- **H. operación.** Scans por día hábil: 12/10 → 1, 13/10 → 2, 14/10 → 5, 15/10 → 13, 16/10 → 23,
  19/10 → 25, 20/10 → 1 (hasta ahora). Los huecos en sesión son la app cerrada (245, 196). Los
  backups dan `integrity_check ok` con alembic `0019` (el de 20/10 12:35) y `0018` (el de 12/10); la
  rotación deja 7. **En vivo:** el reintento de la 353 arrancó al reabrir (16:07:48, con
  `corridas_degradadas: 1`), y el consenso de hoy pasó de 87 a 113 tickers mientras corría.
- **I. datos.** 10.161 noticias en la ventana, ninguna fuente nueva sin etiqueta; `yfinance:search`
  (357) aporta 526. Las sin clasificar (690) son todas de hoy y las clasifica el refresh en curso.
  Extremos: 1 en −3 y 119 en +3, que es la **365** (abierta). Consenso: 127 tickers por día salvo el
  10/10 (95, que es la H-1 de la tanda anterior → 353) y hoy (en curso). Ningún ticker de la
  watchlist sin consenso desde el 13/10 ni sin noticias en la ventana.
- **J. rendimiento.** Scan más largo de la ventana: **187 s** (11/10), contra 15 min. El último
  `database is locked` es del 27/09. La consulta nueva de Home (`equity_diaria`) usa
  `ix_paper_equity_account_at`. El job nuevo (`NubeSyncWorker`) tiene techo: `connect_timeout=10`,
  `read_timeout=30` y 10 intentos.
- **K. dependencias.** `boto3>=1.40,<2` declarado (356), con `boto3`, `botocore`, `s3transfer` y
  `jmespath` en el lock. `test_entorno_cumple_requirements_t284` pasa con Anaconda y con el `.venv`.
  `scripts/audit_dependencies.py` corrió `pip-audit` sobre el `.venv` (41 avisos en 6 paquetes,
  p. ej. lxml 5.2.1): es la divergencia del `.venv` que decidió la 284, así que queda afuera por
  criterio.

### Alcance no mirado (lista)

- **D:** mutaciones propias en el sentido del falso positivo sobre los detectores de la ventana; se
  usaron las que dejaron escritas las tareas.
- **F:** Paper y Métricas más allá de la serie de snapshots; los KPI de Home de «Mis Acciones», que
  la tanda del 10/10 recalculó y que no cambiaron (no hay transacciones nuevas); la app no se lanzó.
- **G:** la cartera «Tech» (22 posiciones de 1 acción, importadas el 15/04, sin cambios en la
  ventana), que ninguna tanda cuadra.
- **H:** Slack, sólo por lo que dice el log; la infraestructura de la 196/355.
- **I:** la muestra contra la fuente primaria (≤10 filas), porque no se pegó a la red.
- **J:** `EXPLAIN` de las consultas del scan que no cambiaron.

## Fase adversarial

[L-1] (HIGH) pasó por el `verificador` con el mandato de refutarlo atacando primero el instrumento.
**Veredicto: PARCIAL.** Confirmó las 14 filas, el camino único que las escribe y que no fue otro
proceso ni un throttle. **Refutó la duración del daño** (para el universo paper es un scan, no una
semana), y eso se confirmó en vivo. **Agregó** el antecedente de EMBJ y MLTX (09/10) y la fragilidad
de la asimetría que cura. La severidad bajó a **MEDIA**. [L-2] y [F-1] son MEDIA y BAJA-MEDIA, así
que no pasan por el `verificador` (regla de la skill).

## Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| [L-1] | 374 |
| [L-2] | 375 |
| [F-1] | 376 |

## Deuda de la skill

- **[F-1] (c-metodo):** `pantalla` recalcula los números contra la DB, pero la DB guarda lo que el
  motor calculó. Falta cruzar **un snapshot de equity contra los cierres de su día** cuando el scan
  que lo escribió dijo *«sin precio»*.
