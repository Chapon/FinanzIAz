# Auditoría — tanda completa (las 12 áreas), 2026-10-23

READ-ONLY. Skill `auditoria`. Tarea **389**. Kill-criteria **congelado el 2026-10-23, antes de abrir
ningún archivo de código**, para las 12 áreas juntas. Lo único leído antes de congelar: el informe de
la tanda anterior, la lista de commits y el `--stat` del diff desde ella.

**Ventana.** Desde la tanda anterior (`docs/auditoria_tanda_2026-10-20.md`, cerrada en `306a9b5`)
hasta hoy: commits `4ff835b..ba049bf`, tareas **374–388**, log desde `2026-10-20 12:35:55` (donde
cortó el censo anterior), DB y backups desde el 2026-10-20 16:40.

**Base.** El criterio del 2026-10-20, que Chapa aprobó, **sin aflojar ninguno**. Lo que cambia es
(1) lo que entró al repo en la ventana, que se agrega a cada área, y (2) el *alcance no mirado* de la
tanda anterior, que esta vez entra (salvo donde se dice por qué no) — es la regla de la skill: una
exclusión se re-verifica, no se copia.

**Alcance general.** Ninguna corrida es exhaustiva: cada área declara qué mira y qué no, y el alcance
real se escribe al final **como lista**. «Barrido limpio» va en las dos direcciones: *lo escrito es
falso* y *lo verdadero no está escrito*.

**Primero, antes de cualquier área:** `check_ci.py --ultimo` con su sha contra `origin/main`, y
`git status`.

---

## A. claims

- **Se mira:** `CLAUDE.md`, cabecera y *En curso* del backlog, las skills de `.claude/skills/` y
  `.claude/commands/` (lista en disco). Los claims que cerraron las tareas 374–388, buscados con
  `grep` en todo el repo. **Nuevo en la ventana:** lo que afirman `docs/libros_inversion_analisis_2026-10-21.md`,
  la skill `fair-value-feature` (tocada) y los rótulos de la tarjeta de valuación (383/384) sobre lo
  que calculan; los veredictos NO-SHIP de la 385 y la 365, contra lo que el backlog y las skills dicen
  de ellos. Procesos declarados en varios lugares, lugar contra lugar.
- **Afuera:** los docs históricos que ningún archivo vivo cita como actuales.
- **Limpio si:** (→) ningún número o afirmación de un doc vivo contradice el código, la DB o lo
  medido hoy; (←) ningún comportamiento que agregó una tarea de la ventana falta en el doc que
  declara cubrirlo (`ARCHITECTURE.md`, `DB_SCHEMA.md` —la migración 0020—, `SETTINGS_REFERENCE.md`),
  con la granularidad que ese doc promete.

## B. muestra

- **Se mira:** las comparaciones `len()`/`>=`/conteos que deciden *«completo»* o *«esta es la
  muestra»* en el código nuevo de la ventana: `data/fundamentos_pit.py`, `scripts/build_fundamentals_pit.py`,
  `analysis/calidad.py`, `paper_trading/referencia.py`, `data/failed_tickers.py` (374) y los runners
  de la 379, 384 y 385; y cada operación que movió la muestra en la ventana, cruzada por contenido.
- **Afuera:** tests, salvo los guards de inventario.
- **Limpio si:** (→) ningún chequeo por cantidad que decida completitud sigue siendo verdadero
  cuando la ventana rueda; (←) toda operación que movió la muestra tiene evidencia de re-verificación
  de los veredictos que pudo invalidar.

## C. desvios

- **Se mira:** `deviations_keyed()` contra el `settings.json` vivo y la cuenta 2 en la DB; el texto
  de cada desvío contra el valor vivo de cada perilla (sub-perillas incluidas); magnitudes y
  frecuencias contra su marco y contra `paper_equity_snapshots` —ahora con la columna de la 0020—;
  `NO_MODELABLE` contra el valor vivo. **Nuevo:** lo que cambió en `analysis/harness_config.py`
  (376) y el runner de la 385 (¿declara su marco y sus desvíos?).
- **Afuera:** medir el efecto de un desvío nuevo en un veredicto.
- **Limpio si:** (→) ningún texto de desvío afirma algo que el valor vivo o el registro contradiga;
  (←) ninguna diferencia engine↔harness queda sin clave.

## D. guards

- **Se mira:** primero el **resultado** del CI (último run de `main`, su sha contra `origin/main`,
  rojos en la ventana). Después `ci.yml` contra los cuatro comandos. **Esta vez con mutaciones
  propias en el sentido del falso positivo** (la tanda anterior no las hizo) sobre los detectores de
  la ventana: el de ráfaga de `failing` de la 374, la marca de posiciones a costo de la 376, la
  bandera de cierre de la 375 y el filtro de alias de la 367. Se construye el caso que tendría que
  disparar —o la declaración contraria— como **dato**, en un script del scratchpad que llama a la
  función del repo; **nunca se edita el repo**. Y los puntos ciegos que declaran los docstrings
  nuevos.
- **Afuera:** guards sin cambios en la ventana y ya mutados por una tanda anterior.
- **Limpio si:** (→) CI verde y del sha de `main`, y ningún detector pasa con el caso contrario;
  (←) ningún punto ciego declarado queda sin tarea.

## E. estado

- **Se mira:** **nuevo:** el store de fundamentals point-in-time de la 382 (quién lo regenera, cada
  cuánto, qué pasa si no, y qué lo lee: 383/384/385); los artefactos de la 377 (universo sin elegir
  en Home). Y los de siempre: `data/parquet/`, `data/pit_signals/`, los `10y` del cohorte, universo,
  la cinta intradía de `price_cache`, contra sus pares.
- **Afuera:** los backups (H).
- **Limpio si:** (→) ningún store queda atrás de sus pares sin que algo lo diga; (←) toda operación
  periódica tiene disparador o tarea.

## F. pantalla

- **Se mira:** **nuevo:** la referencia punteada de Home (377), el costo de operar debajo de la curva
  (386), la tarjeta de valuación de Analysis (383/384), la marca de snapshot a costo (376) y el
  resumen de Noticias sin Ollama (387): cada número trazado a su fuente y recalculado a mano contra
  una copia de la DB, con atención a cómo se pinta un vacío y a la selección por defecto. **Y la
  deuda de la skill de la tanda anterior:** snapshots de equity cruzados contra los cierres de su
  día. Además, Paper y Métricas más allá de los snapshots (alcance no mirado del 20/10).
- **Afuera:** estética y layout; no se lanza la app.
- **Limpio si:** (→) cada número mirado coincide con su recálculo y con su rótulo; (←) ningún vacío o
  dato viejo se pinta como dato.

## G. cuentas

- **Se mira:** el cuadre de caja y acciones de las cuentas 2 y 1 (slippage dentro del `fill_price`);
  `max_positions` y caja no negativa; dividendos que el motor **debió** acreditar, con su propia
  función; la cartera real (cantidad, `avg_buy_price`, fecha contra el rango del día). **Y la cartera
  «Tech»**, que ninguna tanda cuadró (alcance no mirado del 20/10).
- **Afuera:** si las decisiones fueron buenas.
- **Limpio si:** (→) todo cuadra al centavo y ningún límite se violó; (←) ningún flujo que el motor
  declara registrar falta en su ledger.

## H. operacion

- **Se mira:** el log de la ventana agrupado por frecuencia; cada job del scheduler por día hábil
  (calendario de la bolsa; log en hora local, DB en UTC); backups (que se toman, rotan y restauran:
  copia abierta en el scratchpad, `integrity_check` y revisión de alembic, que ahora tiene que ser
  `0020`); Slack sólo por el log.
- **Afuera:** la infraestructura de la 196/355; disparar jobs o restaurar de verdad.
- **Limpio si:** (→) ninguna firma se repite sin tope y ningún día hábil queda sin scan sin que algo
  lo diga; (←) el último backup restaura a un esquema que `init_db` reconoce.

## I. datos

- **Se mira:** distribución de tipo/polaridad/intensidad de las noticias de la ventana; cobertura por
  ticker del universo vivo en consenso y en facts de EDGAR. **Nuevo:** el contenido de los
  fundamentals PIT de la 382 —¿la fecha de presentación es la del filing?, ¿el valor es el del
  filing original o el reexpresado?— con una **muestra ≤5 filas contra EDGAR** (lectura pública; si
  no hay red, se dice) — es el *alcance no mirado* del 20/10. Y las noticias que la 367 re-etiqueta
  (GOOG→GOOGL, búsqueda por nombre): ¿son del ticker?
- **Afuera:** si el dato predice algo.
- **Limpio si:** (→) ningún campo degenerado ni hueco de cobertura nuevo sin tarea, y la muestra
  coincide con la fuente; (←) ningún ticker del universo vivo llega al screen o a la tarjeta sin
  datos sin que se avise.

## J. rendimiento

- **Se mira:** duración de los scans contra su intervalo; `database is locked`; `EXPLAIN QUERY PLAN`
  de las consultas **nuevas** de la ventana (referencia de Home, costo de rotar, fundamentals PIT en
  el worker de Analysis); techo de tiempo de todo job o worker nuevo.
- **Afuera:** la optimización que no cambia conducta.
- **Limpio si:** (→) ningún scan tarda más que su intervalo, sin locks, sin `SCAN TABLE` sobre una
  tabla que crece en un camino caliente; (←) todo job de fondo tiene techo.

## K. dependencias

- **Se mira:** los imports de terceros del código nuevo de la ventana (opcionales incluidos) contra
  `requirements*.txt` y el lock; lo declarado contra lo instalado en Anaconda y `.venv`; el motivo de
  cada pin.
- **Afuera:** actualizar; la divergencia que decidió la 284, salvo un dato nuevo.
- **Limpio si:** (→) todo import declarado y todo pin con motivo vigente; (←) ningún paquete del que
  dependa la conducta sin pin ni techo.

## L. logs

- **Se mira:** el censo de toda firma WARNING+/traceback de la ventana, normalizada, **separada por
  origen** (`[proceso: …]`; las 76 `stress_vigia` del 21/10 ya están atribuidas a la prueba a mano de
  la 380), clasificada conocida (con su tarea y su **tasa** contra la del cierre), explicada o
  desconocida. **Las firmas de la tanda anterior cuyo arreglo shipeó en la ventana (374, 375):
  ¿dejaron de aparecer?** `py.warnings` (372), que ahora sí corrió con la app viva; lo que la app
  escribe fuera de `finanzias.log` (`congelamientos.log`).
- **Afuera:** el contenido de los INFO.
- **Limpio si:** (→) ninguna firma sin clasificar y ninguna conocida por encima de lo que midió su
  cierre; (←) ningún camino de fondo traga a `debug` lo que debería verse.

---

**Fase adversarial:** todo HIGH/CRITICAL va al `verificador` con el mandato de **refutarlo**,
atacando primero el **instrumento**. Si no puede correr, se dice.

**Cierre:** la tabla `hallazgo → tarea`, verificada de a una contra `docs/BACKLOG.md`.

---

# Corrida

**2026-10-23, de 11:00 a 11:45 locales**, con la app **abierta** (arrancó a las 10:24). Antes de
cualquier área: `check_ci.py --ultimo` → `ba049bf` **VERDE**, el sha de `origin/main`; `git status`
limpio salvo este informe y el registro de la 389. El criterio de arriba no se tocó.

**Instrumentos.** La DB es una copia hecha con la API de backup desde `mode=ro` a las 11:05
(`integrity_check ok`, alembic `0020`). Lo que se calculó con funciones del repo corrió con
`FINANZIAS_DB_PATH` apuntando a esa copia, `FINANZIAS_LOG_FILE` a un archivo del scratchpad y
`FINANZIAS_DISABLE_SLACK=1`: **ninguna lectura tocó la DB viva ni el log de producción**. El censo
del log es un script del scratchpad que normaliza tickers, números, rutas y URLs y separa por
`[proceso: …]`.

**Dos instrumentos míos que dieron un número falso y se corrigieron antes de publicar:**

- **El cuadre de «Mis Acciones» marcó INTC y META como descuadradas**: promedié **todas** las
  compras, y `avg_buy_price` es el promedio FIFO de los lotes que **quedan** (INTC: 4 a $103,53
  después de vender los 9,57 de 2024; META: 7 a $726,13). Medido bien, cuadra.
- **`parse_universe_file` recibió un `str`** y se cayó; con `Path`, la comparación salió.

## [I-1] El puntaje de calidad y la tarjeta de valuación toman el último año de cada concepto aunque sea de hace una década, y lo muestran como actual — **MEDIA** → tarea **390**

Severidad: MEDIA · Confianza: ALTA · Categoría: datos (y muestra)

- **Ubicación.** `analysis/calidad.py:55-61` (`patas_de`: `bruta[-1]`, `deuda[-1]`, sin comparar su
  fin de período con el de la ganancia) y `analysis/valuation.py:153` (`v.eps = eps_serie[-1]`).
- **Evidencia.** Sobre el almacén de la 382 (125 tickers, `generado` 2026-10-21), el último año
  de cada concepto contra el último de la ganancia neta:
  - **ganancia bruta: 24 de 125** con dos o más años de atraso. AT&T **2014**, Williams **2012**,
    T-Mobile, Verizon, Thermo Fisher, RTX, Northrop, Schlumberger, Halliburton y BKNG **2017**,
    Oracle 2018, etc. AT&T no reporta `GrossProfit` y su `CostOfRevenue` termina en 2014: su pata
    `rentab_bruta` de hoy es **0,242**, ventas menos costo de 2014 sobre activos de 2014.
  - **deuda: 6 de 125.** JPM **2013**, GS 2018, O 2016, F 2020, DE 2021, ORCL 2022. La pata
    divide esa deuda por la ganancia del **último** año: la de JPM es la deuda de largo plazo de
    2013 sobre la ganancia de 2025 (**4,70**).
  - **EPS: EXC y HAL terminan en 2021.** La tarjeta de valuación los usa como el EPS de hoy (al
    menos su pie dice *«Último año fiscal: 2021-12-31»*).
  - **En la muestra que midió la 384** (cada 1° de marzo y septiembre de 2016 a 2026, con lo
    conocido a esa fecha): **15,2%** de las patas de rentabilidad bruta (303 de 1.995) y **3,6%**
    de las de deuda (87 de 2.431) venían de un año con dos o más de atraso.
- **Y la cobertura que declaró la 382 lo contaba por cantidad** (categoría B):
  *«la ganancia bruta en 88»* y `build_fundamentals_pit.py` (`cobertura`: años ≥ 8) cuentan
  **cuántos** años hay, no **cuáles**. Los 24 de arriba entran en las 88.
- **Impacto.** (1) La tarjeta de Análisis muestra un percentil de calidad *«entre 126 empresas»*
  mezclando años, sin decirlo. (2) **El NO-PASA de la 384 y el NO-SHIP de la 385 se midieron con
  ese instrumento.** No se afirma que cambien: un ruido así tiende a llevar el resultado hacia
  cero, pero la dirección no está medida. **No se sabe**, y por eso va como re-medición.
- **Verificación.** Se miraron los registros crudos (AT&T: `ganancia_bruta` vacío,
  `costo_ventas` 2007–2014 con `CostOfRevenue`; JPM: `deuda_lp` 2008–2013 con `LongTermDebt`), y
  `patas_de` sobre los mismos objetos devuelve esos números.
- **¿Por qué no antes?** (a) NO EXISTÍA: 382–385 son de la ventana.
- **Acción.** Una pata va sólo si su fin de período es el de la ganancia (o uno antes), y si no
  queda vacía; lo mismo para el EPS de la tarjeta, que avisa si el último año queda atrás. La
  cobertura de la 382 se cuenta por año vigente. Re-correr la 384 y la 385 con el instrumento
  corregido y escribir si el veredicto se mueve.

## [K-1] Once dependencias sin techo, `yfinance` entre ellas: el CI instala `requirements.txt` sin lock y un release nuevo lo puede poner rojo sin que cambie el código — **MEDIA** → tarea **391**

Severidad: MEDIA · Confianza: ALTA · Categoría: dependencias

- **Ubicación.** `requirements.txt`: `yfinance>=0.2.40`, `requests>=2.33.0`, `urllib3>=2.8.0`,
  `lxml>=5.2.1`, `alembic>=1.13`, `duckdb>=1.0`, `mplfinance>=0.12.10b0`, `reportlab>=4.0.0`,
  `openpyxl>=3.1.0`, `hmmlearn>=0.3.0` y `arch>=6.0`, todas sin `<`.
- **Evidencia.** Es exactamente la forma de la **348**: `pyarrow>=17.0` resolvió la 26.0.0 en el CI y
  lo puso rojo. La 348 le puso techo a **pyarrow** y a nada más. `yfinance` es la fuente de casi
  todo el dato y sacó versiones con cambios de API (0.2 → 1.x); hoy Anaconda, el `.venv` y el lock
  tienen la **1.4.1**.
- **Impacto.** Un rojo de CI sin cambio de código (la regla 7 obliga a pararlo todo), y un
  `pip install -r requirements.txt` en otro entorno que no instala lo que corre la app.
- **¿Por qué no antes?** **(c-metodo).** La tanda del 2026-10-20 tenía escrita la condición
  *«(←) ningún paquete del que dependa la conducta sin pin ni techo»* y la dio por limpia mirando
  `boto3` y la 348. Le faltó **recorrer la lista**: la condición se leyó contra lo nuevo de la
  ventana, no contra el archivo.
- **Acción.** Techo de versión mayor en cada una (o la decisión escrita de por qué no), y que el CI
  instale con el lock o con una restricción que lo derive.

## [J-1] La referencia de la 377 se calcula en el hilo de la interfaz: 1,5 a 2,5 s trabada cada vez que se entra a Home con una cuenta paper tildada — **BAJA-MEDIA** → tarea **392**

Severidad: BAJA-MEDIA · Confianza: ALTA (el tiempo) / BAJA (la relación con la 381) · Categoría: rendimiento

- **Evidencia.** `referencia_de_cuenta(2)` sobre la copia: **2,49 s en frío y 1,53 s en caliente**
  (lee los frames `1d` de los 127 tickers). La llama `HomeTab._referencia` (`ui/home_tab.py:579`)
  desde el pintado, sin worker. `_llenar_cuentas` (`:409`) vacía `self._ref` en cada `load_data`,
  y `main_window` llama `home_tab.refresh` **cada vez que se navega a Home** (`ui/main_window.py:257`).
  Lo tildado se conserva entre refrescos, así que una vez tildada una cuenta paper, cada visita
  a Home la recalcula en el hilo de la GUI.
- **Relación con la 381 (sin verificar).** La única traba registrada desde el arreglo de la 380
  es de **2,6 s**, a los 41 s del arranque del 21/10 (`finanzias.log`, 13:20:31). Es del orden de
  este cálculo en frío, pero ese día no se sabe si había una cuenta paper tildada. Es un candidato,
  no una causa.
- **¿Por qué no antes?** (a) NO EXISTÍA: la 377 es de la ventana.
- **Acción.** Calcularla en un worker (como el resto de Home lee de la DB en el hilo, ésta es la
  única que lee 127 frames), o cachearla por día y no por carga.

## [F-1] Home dice que WBD quedó afuera de la referencia por *«sin precio al alta»*, y el motivo es un frame `2y` de una fila — **BAJA** → tarea **393**

Severidad: BAJA · Confianza: ALTA · Categoría: pantalla

- **Evidencia.** `referencia_de_cuenta(2)`: `n = 126`, `sin_historia = ['WBD']`, y
  `_nota_referencia` (`ui/home_tab.py:613-614`) lo rotula *«afuera, sin precio al alta»*. WBD sí
  cotizaba el 18/06. El frame más fresco del cache es `WBD__2y__1d` con **una fila** (2026-10-05);
  los otros dos terminan el 09/09. `unir_cierres` (`database/cartera_real.py:454`) no pega una
  serie vieja que no comparte ningún día con la ya unida, así que WBD queda con un solo cierre,
  posterior al alta.
- **El mismo mecanismo, en general:** un frame degenerado más fresco borra la historia del ticker
  para Home (la cartera real usa la misma unión). En el cache hay cuatro frames de menos de 20
  filas: WBD, EA, EQR y ME; sólo WBD está en un universo vivo.
- **Y un (←) de la misma tarea ([A-1], BAJA):** `docs/ARCHITECTURE.md` lista los módulos de
  `paper_trading/` uno por uno y no nombra `referencia.py` (377). `valuation.py`, `calidad.py` y
  `fundamentos_pit.py` sí están.
- **¿Por qué no antes?** (a) NO EXISTÍA (la 377). El frame de una fila sí estaba: la tanda del 20/10
  lo explicó como *«escrito por el código viejo»*, sin preguntar qué hacía con la historia.
- **Acción.** Que `unir_cierres` no deje que una serie de pocas filas sin solapamiento tape a las
  largas (o que el rótulo diga el motivo real), y la línea en ARCHITECTURE. Sacar WBD de la
  watchlist (la 369, acción manual) lo resuelve para este caso, no para el mecanismo.

## [E-1] El almacén de fundamentals no tiene quién lo regenere, y el percentil de calidad se calcula contra él entero — **BAJA** → tarea **394**

Severidad: BAJA · Confianza: ALTA · Categoría: estado

- **Evidencia.** Los 125 archivos de `data/fundamentals_pit/` son del 2026-10-21. Se rehacen sólo
  de a uno, cuando se abre ese ticker en Análisis y tiene más de 30 días
  (`ui/analysis/worker.py:29`, `REFRESCO_FUNDAMENTALS_DIAS`). `build_fundamentals_pit.py` es manual
  y nada lo llama. Pero `calidad_en_el_universo` (`:67`) calcula el percentil contra **todo** el
  almacén.
- **Impacto.** Desde ~el 20/11, el ticker que se abre tiene su 10-K nuevo y sus pares no: el
  percentil compara años distintos. Con la temporada de 10-K (de noviembre a marzo), hasta la mitad
  del universo. Es display-only.
- **¿Por qué no antes?** (a) NO EXISTÍA.
- **Acción.** Un disparador (un job del scheduler o un paso de `refresh_cohort`), o que el
  percentil diga contra qué vintage compara.

## [C-1] El script que mide la frecuencia del desvío `barrier_eval` tiene los feriados de 2026 escritos a mano, y desde el 1/1/2027 contaría los de 2027 como días sin scan — **BAJA** → tarea **395**

Severidad: BAJA · Confianza: ALTA · Categoría: desvíos

- **Evidencia.** `scripts/medir_cobertura_de_scan_t265.py:26` (`FERIADOS_NYSE_2026`) y `--hasta`
  con default hoy. Es lo que alimenta `SCAN_COBERTURA` del desvío `barrier_eval`
  (`analysis/harness_config.py:561`). Desde 2027, cada feriado cae como día hábil sin scan, sin
  aviso.
- **¿Por qué no antes?** (c-alcance): hasta este trimestre no muerde; ninguna corrida miró
  constantes con fecha de vencimiento en los scripts de medición.
- **Acción.** Que falle (o avise) si el rango sale de los años con feriados cargados, o un
  calendario de la bolsa.

## Barridos limpios (con lo que se miró)

- **A. claims.** `CLAUDE.md` contra la DB y el `settings.json`: la cuenta 2 es `auto`,
  `analyze_single`, 10 posiciones, activa; la 1, inactiva; `hmm_enabled` y `stacking_enabled` en
  `False`. (←) `DB_SCHEMA.md` tiene `positions_at_cost` (0020); `ARCHITECTURE.md` tiene la 382,
  la 383 y la 384 (falta la 377: [A-1], dentro de la 393); la ventana no agregó settings. La skill
  `fair-value-feature` (tocada en la ventana) dice lo que hace el código.
- **B. muestra.** Lo de `fundamentos_pit` va en [I-1]. `referencia.py` decide la población por
  identidad y fecha (`s[0][0] <= d0`) y su fin por el último cierre común; la ráfaga de la 374
  cuenta entradas a `failing`, no fallas. Ninguna operación de la ventana movió el cohorte (los
  `10y` siguen en el 09/09).
- **C. desvíos.** El cambio de la 376 en `cobertura_de_scan` es conservador y lo dice: un scan
  con una posición sin precio cuenta como que no evaluó ninguna barrera. Lo de los feriados va en
  [C-1].
- **D. guards.** CI **verde** en `ba049bf`, el sha de `origin/main`. **Mutaciones propias**, con
  funciones del repo sobre la copia: la marca de la 376 cuenta *a costo* un precio NaN, cero,
  negativo, `None` o ausente (5 de 5); **un `inf` pasa como precio**, y no se encontró ningún camino
  por el que llegue (se anota como límite, no como hallazgo). La 374 rechaza hacia `transient`, que
  es el lado seguro, y no hubo ninguna ráfaga ni *«Sin red hacia Yahoo»* desde que shipeó. La 367
  sigue filtrando por la etiqueta de Yahoo después de buscar por nombre: lo recolectado desde el
  22/10 es de la empresa, o tangencial por la etiqueta (una nota de PNR etiquetada DE), como en el
  resto del universo.
- **E. estado.** Lo nuevo va en [E-1]. `harness_universe_live_acct2.txt` contra la watchlist:
  falta ASML (declarado). El `10y` de SPY termina el 01/10: desde la 251 es sustrato del cohorte, y
  el VS SPY usa el frame `max`, que el job 9 rehace cada 90 días.
- **F. pantalla.** Recalculado sobre la copia: el costo de operar de la cuenta 2 da **$565,77, 17,9×
  y 12,2 días en 90 cerradas** (190 fills; crece desde los $542,76 del 20/10 con los fills de la
  ventana); la referencia da **+5,07%** contra **+3,13%** de la cuenta; ningún día marcado a costo.
  **La deuda de la skill de la tanda anterior:** el último snapshot de cada día del 14 al 22/10
  contra los cierres de su día, con las posiciones reconstruidas desde los fills: diferencias entre
  −0,013% y +0,021% (el snapshot es de las 16:05). Lo de WBD va en [F-1].
- **G. cuentas.** Cuentas 1 y 2 **al centavo** en caja (4.673,98 y 585,40) y en acciones. Máximo de
  10 posiciones en la ventana; caja mínima histórica 4,69. Dividendos con la función del motor
  (`creditos_pendientes` sobre `dividend_calendar_cache`, desde `PISO_DIVIDENDOS`): **0
  pendientes**; ninguna posición sin su fila en el calendario. «Mis Acciones»: 12 posiciones,
  cantidad y `avg_buy_price` FIFO cuadran con sus transacciones, sin transacciones nuevas desde el
  07/10. **«Tech» (por primera vez):** 22 posiciones de una acción, una compra cada una, todas a
  la hora de la importación del 15/04: cuadra; es una lista de seguimiento y su fecha no se puede
  contrastar contra el rango del día (no es la de una operación).
- **H. operación.** Snapshots de la cuenta 2 (total / en sesión): 20/10 → 5/4, 21/10 → 16/15,
  22/10 → 24/23, 23/10 → 4/3 hasta las 11:10. El hueco del 21/10 a la mañana es el cierre de la
  380. Último backup: `integrity_check ok`, alembic `0020`, y uno `pre-migration` del mismo
  arranque (el que aplicó la 0020). La clasificación de noticias corre una vez por día: las 1.587
  sin clasificar son del 22 a la tarde y del 23, y las está clasificando la corrida que arrancó a
  las 10:30.
- **I. datos.** Noticias de la ventana: 4.683, las clases y la escala de siete niveles como en la
  tanda anterior (los extremos son la 365, cerrada NO-SHIP). Consenso: los 127 de la watchlist
  todos los días del 15 al 23/10. Muestra contra la fuente: la ganancia neta de MSFT (FY2024,
  88.136 M), de KO (2024, 10.631 M; ventas 47.061 M) y de JPM (2024, 58.471 M), y el EPS diluido de
  NVDA (FY2025, 2,94) coinciden con sus 10-K, y la fecha de presentación es la del 10-K de cada uno.
- **J. rendimiento.** Scans de 137 a 153 s contra 15 min; ningún `database is locked`.
  `costo_de_rotar_de_cuenta` y `equity_diaria_marcada`, ~0,01 s. Lo de la referencia va en [J-1].
  `valuacion_de` puede pegar a la SEC (dos pedidos de 30 s como máximo), pero corre en el worker de
  Análisis.
- **K. dependencias.** Los imports de terceros del código de la ventana están todos declarados. Lo
  de los techos va en [K-1].
- **L. logs.** Ventana `2026-10-20 12:35:56` → `2026-10-23 11:27`: **352 WARNING+ en 21 firmas y 5
  tracebacks**. Todas clasificadas:

| Firma (normalizada) | Líneas | Origen | Clase | Motivo |
|---|---|---|---|---|
| `cachean la barra de la sesion de HOY` (1 y 10 tickers) | 140 + 7 | app | conocida (112, 243) | Una línea por lote, por diseño. |
| `Vigía: la interfaz estuvo trabada N s (umbral 0.05)` | 70 | `stress_vigia` | explicada | La prueba a mano de la 380 (anotado en la 381). |
| `XGBoost TK: unstable model` | 54 | app | conocida (364), **con su tasa** | 10, 12, 11 y 12 en el primer scan de cada arranque, y 9 a las 11:25 de hoy con `motivos: cierres+filas+ultima_fila`: la app arrancó antes de la apertura y entró la primera barra del día, que la 364 manda re-entrenar. |
| `Scan … 1/127 tickers sin precio` | 49 | app | conocida (369) | WBD; acción manual pendiente. |
| `Nube — FUENTE NO DISPONIBLE` | 5 | app | conocida (356) | Una por arranque. |
| `parquet_cache: TK 10y se lee directo … hace N ruedas` | 12 | runners de la 379, 384, 385 y `python stdin` | explicada | El cohorte termina el 09/09 (SPY el 01/10): por diseño de la 251. |
| `WBD: la serie diaria (2y) termina …` + `$WBD possibly delisted` | 4 + 1 | app | conocida (369) | |
| `HTTP Error 401 Invalid Crumb` / `User is unable to access` | 2 + 1 | app | explicada | Crumb transitorio. |
| `Scan … 15/127 sin precio — SIN evaluar: AMGN` | 1 | app | conocida (374) | 20/10 16:08, antes del arreglo. |
| `Vigía: la interfaz estuvo trabada 2.6 s` | 1 | app | conocida (381) | Ver [J-1]. |
| `Ollama backend failed … falling back to heuristic` + 2 tb `ReadTimeout` | 2 | app | explicada | Timeout de 60 s de Ollama; cae a la heurística, por diseño. |
| `news_digest: Ollama briefer failed` + 1 tb | 1 | app | conocida (387) | 22/10 11:24, antes del arreglo de las 16:06. |
| `collect_sec_8k failed … falla de red` / `yfinance news fetch failed … Timeout` + 2 tb | 1 + 1 | app | conocida (289, 353) | Un traceback por fuente. |

  **Firmas que dejaron de aparecer tras su cierre:** las de la 375 no se pueden juzgar todavía (la
  única instancia con ese código, la de hoy, no se cerró); las de la 374 necesitan un corte de red
  para verse. **`py.warnings`: cero desde la 372**, y la captura **anda**: `setup_logging` con un
  log del scratchpad registró un `UserWarning` de prueba. **(←)** `congelamientos.log` no cambia
  desde el 21/10 12:03.

## Fase adversarial

**No hubo HIGH ni CRITICAL**, así que el `verificador` no corrió (regla de la skill). La refutación
de [I-1], el de más peso, fue **propia y no independiente**: se atacó el instrumento contra los
registros crudos (que `serie()` no estuviera perdiendo años por la fecha de corte) y contra la
función que usa la pantalla, y se sostuvo.

## Alcance no mirado (lista)

- **D:** mutaciones ejecutadas sobre la 375 y la 380 (se razonaron contra el docstring, no se
  corrieron).
- **F:** la tarjeta de valuación renderizada; la pestaña Noticias (387) en vivo. La app no se lanzó.
- **H:** Slack, sólo por el log; la infraestructura de la 196/355.
- **I:** la muestra contra EDGAR se contrastó con cifras de los 10-K conocidas, **sin bajar** los
  filings (no se pegó a la red); la reexpresión de comparativos (que el valor de un año cambie en
  un 10-K posterior) no se midió.
- **J:** `EXPLAIN QUERY PLAN` de las consultas nuevas: no se corrió; se midió el tiempo total.

## Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| [I-1] | 390 |
| [K-1] | 391 |
| [J-1] | 392 |
| [F-1] (con [A-1]) | 393 |
| [E-1] | 394 |
| [C-1] | 395 |

## Deuda de la skill

- **[K-1] (c-metodo):** una condición (←) sobre un archivo entero (*«ningún paquete sin techo»*) se
  leyó contra lo que cambió en la ventana. Falta escribir en el método de K que la condición se
  verifica **recorriendo el archivo**, no el diff.
