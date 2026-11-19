# Auditoría — tanda de las 12 áreas, 2026-11-16

**Tarea 429.** Pedido de Chapa (2026-11-16, *«correr auditorias»*; elegida la opción *«Tanda completa (12 áreas)»*). Ventana: desde la tanda anterior —la **404**, `docs/auditoria_tanda_2026-11-05.md`, cierre `22abba2`— hasta `HEAD` = `6b1fdba` (2026-11-11) y el estado vivo del 2026-11-16. READ-ONLY: no se tocó código, config, esquema, tests ni la DB.

## 0. Kill-criteria — congelados 2026-11-16 23:14 (UTC−3), los doce juntos, antes de abrir los archivos de ningún área

### 0.1 Lo que se vio ANTES de congelar

Lo vieron los chequeos de arranque de sesión (regla 7 y la memoria de *git status*), no el barrido. Se declara para que no se lea como hallazgo de un área ni calibre su criterio:

- **CI.** `check_ci.py --ultimo` salió con exit 1: *«el run de 6b1fdba sigue en curso; éste es el anterior: ROJO (cancelled)»*. Por la API pública: el run de `6b1fdba` está `queued` desde 2026-11-11 20:39Z **sin ningún job creado**; el de `d9b9d4c` (20:21Z) tampoco creó jobs y quedó `cancelled` el **2026-11-15 17:23Z**; el último verde es `564f2f7` (19:34Z, 6 min). `ci.yml` no cambió desde `bdfec90`, que dio verde siete veces seguidas.
- **Skill `auditoria`**, al cargarla: la pregunta (5) de la nube dice *«La factura: UStanda,00, o el mail del presupuesto»*.
- **Árbol:** WIP de la 425 sin commitear (`analysis/opinion_claude.py` modificado, `tests/test_opinion_volumen_t425.py` nuevo). *En curso* tiene un solo ítem: la 428, esperando su CI.
- **Backlog:** 427 encabezados `### N.` con máximo 428.

### 0.2 Reglas comunes a las doce áreas

- **READ-ONLY.** La DB se abre con `mode=ro` (o se copia); las mutaciones de guards van sobre copias en el scratchpad, nunca sobre el repo.
- **El alcance se escribe como lista.** Toda exclusión lleva su motivo, y **las exclusiones de la 404 se releen y su motivo se re-verifica**; copiar una no es declararla. Lo diferido entra al backlog como tarea.
- **Fuera de alcance común:** el WIP sin commitear de la 425 (es una tarea a medio hacer; se mira `HEAD`). Si la app corrió con ese WIP en el árbol, se dice como limitación.
- Cada hallazgo con evidencia reproducible, severidad y confianza por separado, y el *¿Por qué no antes?*. Antes de publicar, `grep` del tema en el backlog: si hay tarea o decisión, lo accionable es reabrirla con el dato nuevo, no proponerla de nuevo.
- HIGH y CRITICAL pasan por el `verificador` con mandato de refutar, con el instrumento al principio del pedido.

### 0.3 Por área

**A. `claims`**
- *Se mira:* `CLAUDE.md` entero; las skills de `.claude/skills/` y los comandos de `.claude/commands/` tocados desde la 404, más los que declaran un proceso (cierre de tarea, done, arranque de sesión, refresh del cohorte), comparados **lugar contra lugar**; los contratos de proceso del backlog (*En curso* máx 1, *«al arrancar una tarea, su registro va acá»*) contra la práctica medida; los números que las tareas abiertas de la cola citan como estado actual, y los textos nuevos desde la 404 que citan mediciones (413, 417–419, 422, 424, 428). Las frases que corrigieron las tareas cerradas desde la 404 se **buscan con grep en todo el repo**, no se leen.
- *Afuera:* los docs de análisis fechados (describen su momento) y la memoria del asistente (no es del proyecto).
- *Limpio:* (→) ninguna afirmación vigente de esos lugares contradice el código, la DB o la práctica de hoy; (←) ningún proceso o perilla nueva desde la 404 falta del lugar que promete documentarla.

**B. `muestra`**
- *Se mira:* (1) las comparaciones por cantidad (`len`, contadores, `>=` sobre tamaños) del código nuevo o tocado desde la 404 que decidan *«esto ya está»* o *«ésta es la muestra»*; (2) las operaciones que movieron la muestra desde la 404 (refresh del cohorte, re-precómputo, cambio de universo, re-clasificación) y los veredictos que quedaron sin re-verificar, cruzados **por contenido** (backlog y docs), no por nombre de archivo.
- *Afuera:* el código que no se tocó desde la 404 (lo cubrieron las tandas anteriores; sería c-alcance).
- *Limpio:* (→) ningún chequeo por cantidad nuevo es ciego a la ventana o a la población; (←) toda operación que movió la muestra tiene su re-verificación, o una tarea que la pide.

**C. `desvios`**
- *Se mira:* la config viva (`~/.finanzias/settings.json`, la cuenta 2) contra el harness (`analysis/harness_config.py`, `deviations_keyed()`); el diff de motor, harness y settings desde la 404; cada texto de `deviations()` contra el valor vivo de **cada** perilla que gobierna; las frecuencias contra `paper_equity_snapshots`; el marco de cada magnitud; las clasificaciones *NO_MODELABLE*.
- *Afuera:* volver a correr los runners.
- *Limpio:* (→) todo texto declarado coincide con el valor vivo y con el registro de lo que corrió; (←) ninguna diferencia viva motor↔harness sin su clave en `deviations_keyed()`.

**D. `guards`**
- *Se mira:* **primero el resultado del CI** —`check_ci.py --ultimo`, la lista de runs de `main`, desde cuándo no hay verde y cuántas tareas se cerraron en el medio—, con el sha contra `origin/main`; después `ci.yml`; después cada guard nuevo o tocado desde la 404 (402, 411, 412, 422, 424, 428, el `audit` de la 399, el aviso por mail de la 405, el percentil de la 394), con **mutación en el sentido del falso positivo** sobre una copia; los `except` nuevos en caminos de fondo, y los puntos ciegos que declaran los docstrings de los guards nuevos.
- *Afuera:* los guards que no se tocaron desde la 404, salvo el CI.
- *Limpio:* (→) el CI corre y su veredicto es del `HEAD`, y ningún guard nuevo pasa en verde con la declaración contraria; (←) ningún punto ciego declarado sin tarea.

**E. `estado`**
- *Se mira:* cada store regenerable —`data/parquet/`, `data/pit_signals/`, los artefactos del cohorte, `earnings_cache`, `price_cache` y su cinta intradía, `surprise_profiles`, los caches de EDGAR, consenso y tooltip, y los nuevos desde la 404 (la referencia de Home de la 392, la opinión de Claude, el percentil de calidad de la 394)—: quién lo regenera, cada cuánto, y su frescura contra la de sus pares; y cada operación manual periódica que dejó una tarea cerrada, con su última ejecución.
- *Afuera:* los backups (van en H).
- *Limpio:* (→) cada store tiene dueño y está fresco respecto de sus pares; (←) ninguna operación manual periódica vencida sin quien la dispare.

**F. `pantalla`**
- *Se mira:* los números nuevos o cambiados desde la 404 —la referencia de Home (392/393), la tarjeta de calidad con su *«hasta cuándo»* (394) y el panel de la opinión de Claude (417–419: qué muestra, de dónde sale, qué pinta sin opinión, con una vieja o con otra cuenta)— y la selección por defecto de cuenta en las pestañas; cada número trazado hasta su función, tabla y columna, y recalculado a mano desde la DB en solo lectura.
- *Afuera:* estética y layout; abrir la GUI (se traza por código y DB).
- *Limpio:* (→) cada número mirado es lo que dice su rótulo, y un vacío se muestra como vacío; (←) ningún número nuevo sin rótulo de vigencia cuando su fuente puede estar vieja.

**G. `cuentas`**
- *Se mira:* el cuadre al centavo de las cuentas 1 y 2 (caja y acciones por ticker); las reglas en la ventana (`max_positions`, caja ≥ 0, ninguna orden nueva en la cuenta 1); los dividendos que **debieron** registrarse según la propia función del motor sobre los fills, contra los registrados; la cartera real (`positions` contra `transactions`, `avg_buy_price`, la fecha de cada transacción contra el rango de precios de ese día, y el cruce paper→real).
- *Afuera:* si las decisiones fueron buenas.
- *Limpio:* (→) todo cuadra y ninguna regla se violó; (←) ningún flujo que debió registrarse falta.

**H. `operacion`**
- *Se mira:* el log de la ventana agrupado por mensaje normalizado; cada job del scheduler por día hábil (con `paper_equity_snapshots` como vara del scan); Slack (lo que se mandó y lo que debió mandarse); los backups (se toman, rotan, y se pueden **restaurar**: prueba sobre una copia); alembic; y la nube, con las cinco preguntas de la skill (la app la lee; corrió cada día hábil con sus 5 lotes; alarmas y suscripción confirmada; versión desplegada contra el repo; factura).
- *Afuera:* lo que pida credenciales que esta máquina no tenga (se dice cuál, y si no se puede leer, **eso** es el hallazgo).
- *Limpio:* (→) ningún mensaje repetido sin tope, todo job corrió cada día hábil, el backup se restaura, y la nube se lee y está al día; (←) todo lo que debió avisar, avisó.

**I. `datos`**
- *Se mira:* lo que recibe la opinión de Claude desde la 417–419 (la valuación de la tarjeta, los cuatro años fiscales de EDGAR, el P/E de Yahoo, el próximo balance con sus días, las últimas cuatro sorpresas de EPS, el retorno del día, la marca de intradía y la hora ET de las noticias): para una muestra de tickers del universo vivo, cada bloque contra su fuente y entre fuentes; la distribución de la clasificación de noticias de la ventana; la cobertura por ticker del universo vivo (facts, consenso, noticias, balances).
- *Afuera:* si el dato predice algo.
- *Limpio:* (→) en la muestra, cada bloque dice lo que dice su rótulo; (←) ningún ticker del universo vivo se queda sin un dato sin que se avise.

**J. `rendimiento`**
- *Se mira:* la duración de cada scan contra su intervalo, y los `database is locked`, del log; `EXPLAIN QUERY PLAN` de las consultas nuevas desde la 404 (opinión de Claude, referencia de Home, percentil de calidad); el techo de tiempo de los jobs y llamadas nuevos (la llamada a Claude, EDGAR).
- *Afuera:* optimizar lo que no cambia conducta.
- *Limpio:* (→) ningún scan más largo que su intervalo, ningún lock, y ninguna consulta nueva con `SCAN` sobre una tabla que crece en el camino caliente; (←) todo job o llamada nuevo tiene techo.

**K. `dependencias`**
- *Se mira:* cada import de terceros (opcionales y locales incluidos) contra los `requirements*`; `requirements.txt`, `requirements-dev.txt` y `requirements.lock` **enteros** contra el `.venv` instalado, versión por versión, y contra el CI; `pip-audit -r requirements.lock`; el motivo de cada pin; las dependencias que no son de Python y que el código invoca (CLI de Claude, el servidor de qwen) y si están declaradas en algún lado; el intérprete con que corrió la app en la ventana (el WARNING de la 401).
- *Afuera:* actualizar.
- *Limpio:* (→) todo import está declarado, lo instalado es el lock, y no hay vulnerabilidades sin aceptar; (←) toda dependencia que corre está declarada en algún lado.

**L. `logs`**
- *Se mira:* el censo de cada firma WARNING+ y traceback de la ventana, separada por origen (`[proceso: …]`); cada firma clasificada como *conocida* (con su tarea y su **tasa**), *explicada* o *desconocida*; las firmas que debieron desaparecer tras el cierre de su tarea (la 407 y las cerradas en la ventana); y lo que no pasa por el logger (stderr, otros archivos).
- *Afuera:* los INFO, salvo que delaten una falla.
- *Limpio:* (→) ninguna firma sin clasificar; (←) ninguna *conocida* por encima de la tasa que midió su cierre.

---

# Corrida

**Del 2026-11-16 a las 23:14 al 2026-11-17 a las ~01:50 locales**, con la app **cerrada** desde el 11/11 a las ~18:43 (última línea del log 18:42:59; el `-wal` de la DB, 18:43:37). El criterio de arriba no se tocó después de congelarlo.

**Estado al empezar.** `check_ci.py --ultimo` → exit 1 (ver [D-1]). `HEAD` = `origin/main` = `6b1fdba`. Árbol: el WIP de la 425 (fuera de alcance). *En curso*: la 428, esperando el CI de un run que quedó huérfano el 11/11; por eso esta corrida (la 429) **no se pudo registrar en *En curso***: el guard de la 338 no admite un segundo ítem (es [A-1] en carne propia).

**Ventana de código:** `22abba2..6b1fdba` — la 409, 406, 405, 399, 411, 407, 402, 392, 393, 394, 412, 413, 417, 423, 422, 424, 418, 419 y 428. **Ventana de estado vivo:** el log desde `2026-11-05 12:10:00` (donde cortó el censo de la 404) hasta `2026-11-11 18:42:59`, 1.607 líneas; siete arranques de la app (05/11 16:36; 06/11 12:15; 09/11 10:52; 10/11 19:18; 11/11 11:38, 15:12 y 17:57). Días hábiles sin la app: 12, 13 y 16/11; el 10/11 abrió después del cierre.

**Instrumentos.** La DB es una copia de `finanzias.db` + `-wal` + `-shm` al scratchpad (23:20), abierta siempre con `mode=ro` (alembic `0020`). Lo que corrió con funciones del repo (`creditos_pendientes`) leyó esa copia. La mutación de [D-2] corrió sobre copias de `ci.yml` y `requirements.txt` en un directorio temporal. Nada de esta corrida escribió el log de producción, la DB viva ni el repo (salvo este informe y el backlog). La API pública de GitHub, Slack (sólo lectura) y `pip-audit` son las únicas salidas a la red.

## 1. Hallazgos sobrevivientes

### [D-1] Los dos runs del CI del 11/11 quedaron huérfanos en un incidente de GitHub, y `check_ci.py` los leyó como «en curso»: cuatro días dijo VERDE del commit anterior y después ROJO, nunca «atascado» — **MEDIA** → tarea **430**

Severidad: MEDIUM · Confianza: ALTA · Categoría: guards (el CI es un guard de proceso: primero el resultado)

- **Evidencia.** API pública, sin auth: el run `43095498900` (`d9b9d4c`, creado 2026-11-11T20:21:00Z) quedó `completed/cancelled` recién el **2026-11-15T17:23:34Z**, con 0 jobs; el run `43097332677` (`6b1fdba` = `HEAD` = `origin/main`, creado 20:39:20Z) sigue **`queued`**, con 0 jobs y `updated_at` igual a su creación. **Control del instrumento:** el mismo endpoint devuelve los 4 jobs del run verde de `564f2f7`. **La causa es pública** (la trajo el `verificador`; re-verificado en `githubstatus.com/api/v2/incidents.json`): un incidente menor de Webhooks de 20:22 a 20:26Z y uno **crítico** de Webhooks, Actions, Pages y Copilot de 20:48 a 21:21Z, que cerró con *«the backlog of Actions jobs has been fully processed»* sin procesar estos dos. **Desde entonces no hubo ningún push** (`pushed_at` 2026-11-11T20:39:18Z): no hay evidencia de que el CI falle hoy. La sesión del 11/11 lo diagnosticó (*«CI sin verificar: las corridas están en cola por el incidente de GitHub»*, 20:55:56Z) y el diagnóstico no quedó en el backlog.
- **Lo que dijo el instrumento del proceso.** Con el código de `consultar()` (`scripts/check_ci.py:219-229`), que llama «en curso» a todo run de `origin/main` sin terminar **sin mirar su antigüedad ni sus jobs**: del 11/11 20:39Z al 15/11 17:23Z, `--ultimo` daba **exit 0, VERDE** —del run de `564f2f7`— con la nota *«sigue en curso; éste es el anterior»*; desde la cancelación de `d9b9d4c` da **exit 1, ROJO (cancelled)**, sin una línea de detalle (`detalle_del_rojo`, `:148-164`, no imprime nada con 0 jobs). Las dos respuestas dicen «en curso» de un run encolado hace días. Lo de leer el anterior es la decisión de la 307 (`:28-33`) y que un `cancelled` sea ROJO, la de la 300 (`:21`, `tests/test_check_ci_t300.py:118-120`); ninguna contempló un run que nunca crea jobs.
- **Impacto.** El modo VERDE es el peligroso: una sesión que abriera una tarea entre el 12 y el 15/11 habría leído «CI verde» con `main` sin veredicto, y desde el 15/11 la regla 7 manda a buscar un rojo que no tiene nada que arreglar. Lo que quedó sin veredicto es poco (el test de la 428), pero el run huérfano, el *En curso* de a uno y la regla 7 juntos dejaron la 425 sin commitear: es la precondición de [A-1] y de [K-3].
- **Patas que el `verificador` tumbó y se borraron:** *«el CI no corre desde el 11/11»* (no hubo nada que correr), *«sin auth la causa no se ve»* (está en githubstatus, y la sesión del 11/11 la vio), *«`--esperar` gasta 15 minutos por cierre»* (el cierre siguiente pushea y crea su propio run), y la severidad ALTA, que se apoyaba en esa premisa.
- **¿Por qué no antes?** **(a) NO EXISTÍA**: el incidente es del 11/11; la 404 leyó el CI verde (`3e9243f`).
- **Acción.** El próximo push dice si el CI corre (y si el huérfano retiene el grupo de `concurrency`: eso sólo se ve pusheando). En `check_ci.py`: un run sin terminar, **sin jobs** y con más de N veces la duración normal es «atascado» (no se sabe, dicho así y con la hora), también cuando el anterior está en `success`; un `cancelled` sin jobs es «nunca arrancó», no ROJO; y `--ultimo` dice cuántos commits de `main` no tienen un run terminado.

### [A-1] El cierre de una tarea no tiene camino para el «no se sabe» del CI: con un run huérfano, la 428 ocupa *En curso* desde el 11/11 y la 425 quedó sin commitear y sin registro — **MEDIA** → tarea **431**

Severidad: MEDIUM · Confianza: ALTA · Categoría: claims (un proceso declarado en varios lugares, comparado lugar contra lugar, y contra la práctica medida)

- **Evidencia.** Cinco lugares declaran el cierre. `CLAUDE.md:17` (regla 7): *«No se sabe … ⇒ el cierre lo dice así —«CI sin verificar»— y no «verde»»*. `CLAUDE.md:35`: *«con commit + push + CI del commit en verde, movela a Hecho reciente»*. `docs/BACKLOG.md:5` y `:21`: *«el commit del hash —con el CI en verde— lo mueve a Hecho reciente»*. `.claude/commands/ship.md:84-85` (paso 7): *«No se sabe … ⇒ el cierre dice «CI sin verificar» … y la próxima tarea arranca con `--ultimo`»*; `:89-95` (paso 8): el registro sale de *En curso* sólo **«con el CI en verde»**. `.claude/skills/git-workflow/SKILL.md:75`: igual que la regla 7. **Ninguno dice qué pasa con el registro de *En curso* cuando el CI no contesta**, y el guard de la 338 rechaza un segundo ítem.
- **La práctica medida.** La 428 sigue en *En curso* desde el 11/11 (`docs/BACKLOG.md:23`); la 425 quedó implementada y sin commitear, sin registro (`git status`: `analysis/opinion_claude.py` modificado a las 17:55 del 11/11 y un test nuevo; la sesión lo dijo: *«dejo la 425 implementada y probada pero sin commitear»*), y esta corrida tampoco se pudo registrar. Con un «no se sabe» pasajero (sin red, cuota) el hueco no se nota; con un run que no termina nunca, traba el proceso. Y el registro no guarda el porqué: la sesión del 11/11 diagnosticó el incidente de GitHub y eso quedó sólo en el transcript (lo encontró el `verificador`).
- **Impacto.** El paso 7 dice que la tarea siguiente arranca, el paso 8 no deja liberar *En curso*, y el guard no deja registrar la siguiente: la única salida es trabajar fuera del registro, que es lo que pasó (y la puerta de [K-3]).
- **¿Por qué no antes?** **(a) NO EXISTÍA** como costo: el hueco de texto está desde la 338 (2026-10-09), pero hasta el 11/11 todo «no se sabe» se resolvió en minutos.
- **Acción.** Decidir el camino y escribirlo igual en los cinco lugares (por ejemplo: el registro pasa a *Hecho reciente* con «CI sin verificar» y la tarea siguiente relee ese sha con `--sha` antes de cerrarse; o *En curso* admite, además de la tarea en marcha, las que esperan CI), y que el registro diga el estado del CI y su causa.

### [K-1] El mecanismo de la 401 no movió la práctica: la app se abrió con la Anaconda en los 9 arranques desde que existe el aviso, que sólo va al log, y las sesiones piden reabrirla sin decir cómo — **MEDIA** → tarea **432** (reabrir la 401 con el dato nuevo)

Severidad: MEDIUM (lo que se prueba no es lo que corre) · la pata de seguridad, LOW · Confianza: ALTA · Categoría: dependencias (lo que corre no es lo que se declara)

- **Evidencia.** En el log, cada `Iniciando FinanzIAs` desde el 30/10 va seguido de *«FinanzIAs corre con C:\Users\chapa\anaconda3\python.exe y no con el .venv del repo…»*: 30/10 19:04; 05/11 11:07 y 16:36; 06/11 12:15; 09/11 10:52; 10/11 19:18; 11/11 11:38, 15:12 y 17:57. El del 26/10 16:52 no lo trae porque el aviso (`da52708`) es del 27/10: no prueba que ése corriera en el `.venv`. El instrumento es sano (`config/entorno.py:19-22`; el traceback del 11/11 18:13 muestra `anaconda3\Lib\site-packages`). Son **7 arranques después de la tanda 404** y **5 después de la nota del 06/11** en la acción manual (`docs/BACKLOG.md:33`: *«Sigue pendiente…»*).
- **Versiones.** El `.venv` coincide con `requirements.lock` en los 105 pines. De los paquetes del lock, la Anaconda tiene 78 (faltan 27 de desarrollo) y **39 en otra versión** —contra 37 cuando se abrió la 401—: pillow 10.3.0 (lock 13.0.0), lxml 5.2.1 (6.1.3), platformdirs 3.10.0 (4.10.0), msgpack 1.0.3 (1.2.4), filelock 3.13.1 (4.2.9), certifi 2026.6.17 (2026.10.23), entre otras. `pip-audit` de esos paquetes en las versiones de la Anaconda: **81 ids en 12 paquetes** (pillow, 53), contra 2 paquetes en el lock.
- **Lo que pesa de verdad.** El done y el CI prueban el lock y la app corre otra combinación que nadie prueba (la 346 ya mostró que platformdirs cambia la conducta). La pata de seguridad es **baja** (la midió el `verificador`): PIL entra sólo por matplotlib (sin `Image.open` en la app), lxml sólo por `pd.read_html` sobre Wikipedia (su aviso es XXE en el parser de XML), nada importa protobuf ni msgpack, y certifi 2026.6.17 trae una raíz desconfiada.
- **Causa probable** (el `verificador`, sobre los transcripts): desde el 27/10 las sesiones le pidieron a Chapa 13 veces que reabriera la app, y sólo 6 nombran `abrir_app.bat` o el `.venv`; los dos pedidos del 11/11, ninguno.
- **Patas que cayeron:** *«46 en otra versión»* (eran 39: mi `pip freeze` contaba como distintos los builds de conda `@ file://`) y *«pillow, 69»* (son 53 ids; 69 eran entradas). Y no es nuevo: la 404 lo clasificó *«conocida (401)»*, la acción manual dice *«sigue pendiente»* desde el 06/11, y que el aviso vaya sólo al log está declarado (`CLAUDE.md:21`). Lo accionable es **reabrir la 401 con el dato nuevo**, no proponerla de nuevo.
- **¿Por qué no antes?** **(a)** para el dato que lo vuelve accionable: 7 de los 9 arranques son posteriores a la 404, que con dos lo clasificó —razonablemente— como conocida con acción manual pendiente.
- **Acción.** El aviso donde Chapa mira (la barra de estado, como el de la nube); que toda sesión que pida reabrir la app diga cómo (`abrir_app.bat`); que `CLAUDE.md:7` diga la práctica hasta que cambie; y, si Chapa lo elige, que `main.py` se relance solo con el `.venv` cuando existe.

### [K-3] La app corre lo que haya en el árbol de trabajo, WIP sin commitear incluido, y la sesión se lo pidió así: la opinión de MU del 11/11 salió del WIP de la 425, con un `version_datos` que `HEAD` no tiene — **MEDIA** (por la recurrencia; el daño medido es bajo) → tarea **433**

Severidad: MEDIUM · Confianza: ALTA · Categoría: dependencias (lo que corre no es lo que se declara) y operación

- **Evidencia.** `analysis/opinion_claude.py` (WIP de la 425) se modificó el 11/11 a las 17:55:40 locales; la app arrancó a las 17:57:02 y a las 18:00 (21:00:08Z) guardó la opinión de MU (#15, 21,1 s) con `version_datos=5` y un bloque `volumen` con la forma exacta del WIP. En `HEAD`, `VERSION_DATOS = 4` (`analysis/opinion_claude.py:65`) y no hay `volumen`. La fila no salió de un test ni de otra corrida (el `verificador`: los tests usan un runner falso y la DB aislada; `scripts/probar_opinion_claude.py` no guarda; el chequeo de la sesión sólo llamó a `armar_datos`). Nada registra con qué código salió un resultado guardado: ni el log ni `claude_opinions` tienen el commit.
- **La causa, y por qué se va a repetir** (el `verificador`, sobre el transcript del 11/11): el último mensaje de la sesión le pidió a Chapa *«reabrila y pedí la opinión de MU otra vez … el volumen va a entrar cuando commitee la 425»*, con el WIP en el árbol. El agente da por hecho que el commit decide lo que corre la app.
- **Impacto.** Una fila de la medición de la 321 hecha con código que no pasó por el done (bajo: `datos_json` guarda el bloque entero, así que las formas se distinguen después); y, en general, todo WIP del árbol corre en vivo al abrir la app, el motor incluido si el WIP lo toca.
- **Pata que cayó:** *«pisó la opinión que citan como origen la 425–427»*. Fue el reemplazo por día, no el WIP, y pasó dos veces ese día, una con código commiteado: es [E-1].
- **¿Por qué no antes?** **(a) NO EXISTÍA** el caso: es la primera vez en las ventanas auditadas que el log muestra la app abierta con un WIP en el árbol.
- **Acción.** Al arrancar, loguear el commit y si el árbol tiene `.py` modificados (y decirlo en la UI si los tiene); guardar el commit con cada opinión; que una sesión no pida reabrir la app con WIP en el árbol (o lo diga); y decidir si se trabaja en un `git worktree` aparte.

### [E-1] La opinión de Claude se guarda una por `(ticker, día)` y pedirla de nuevo la reemplaza: el 11/11 la de MU se pisó dos veces —una con código commiteado— y se perdió la evidencia de origen de ocho tareas abiertas — **MEDIA** → tarea **438**

Severidad: MEDIUM · Confianza: ALTA · Categoría: estado (un registro que se pisa) · lo trajo el `verificador`

- **Evidencia.** `guardar` (`analysis/opinion_claude.py:629-655` en `HEAD`) es un *upsert* por `(ticker, día)` a propósito (*«pedirla de nuevo el mismo día la reemplaza»*), con `ux_claude_opinions_ticker_fecha` único. El 11/11 la fila de MU se reemplazó dos veces (el `verificador`, sobre el transcript): la de las 15:02Z —origen de la 417 a la 421— por la de las 18:13Z, hecha **con código commiteado** (`605d998`); y ésa —origen de la 425 a la 427, *«12 de 15»* provisionales— por la del WIP de las 21:00Z, que tiene 3 de 15. En la copia de la DB queda una sola fila de MU de ese día, y el WAL no guarda las anteriores.
- **Impacto.** La evidencia de origen de ocho tareas abiertas (417–421 y 425–427, cinco sin ningún WIP de por medio) existe sólo como cita en el backlog y en un transcript. La costumbre que la dispara es razonable: volver a pedir la opinión para ver si un cambio llegó. Y la medición de la 321 se queda con la última opinión del día, no con la que Chapa leyó primero.
- **Es reabrir una decisión** (la de la 320: una por día, para mostrarla sin volver a pedirla), con el dato nuevo de cuánto borra.
- **¿Por qué no antes?** **(a) NO EXISTÍA** como costo: hasta el 11/11 nadie había pedido la misma opinión dos veces en un día para verificar un cambio.
- **Acción.** Guardar cada pedido (una fila por pedido, o la reemplazada en un histórico) y seguir mostrando la última; que la 321 decida cuál cuenta.

### [I-1] Lo que recibe la opinión de Claude no dice lo que dicen sus rótulos: la calidad va sin definición ni corte, las noticias sin su relevancia, y el precio de los objetivos sin su hora — **MEDIA** → tarea **434**

Severidad: MEDIUM · Confianza: ALTA · Categoría: datos (y pantalla: la tarjeta sí lo dice)

- **(a) Calidad.** `analysis/opinion_claude.py:290-294` (`HEAD`) manda `{"puntaje_0_a_100", "percentiles": {"roe", "rentab_bruta", "deuda", "regularidad"}, "empresas_comparadas"}` con las claves crudas. Pero `roe` es *«el ROE medio de hasta 10 años menos su desvío»* (`analysis/calidad.py:8`, `:53-55`), y en `deuda` **100 es lo mejor** (`MAYOR_ES_MEJOR`, `:35`). La tarjeta las traduce (*«ROE estable»*, *«deuda baja»*) y dice el corte (`ui/analysis/valuation_card.py:76-87`); la opinión no manda ninguna de las dos cosas, y el prompt (`:88-114`) no las define. En la #15, MU sale con `roe: 20` teniendo un ROE de ~61 % en su último año, y `deuda: 100`; Claude anotó como faltante *«solo hay un percentil de deuda»*. Además `"fuente": "EDGAR (10-K), lo presentado hasta hoy"` es un literal (`:273`), y el almacén se rehace de a un ticker recién a los 30 días (`ui/analysis/worker.py:29`): hoy los 125 archivos son del 21/10. La 394 decidió *«manual, pero dicho donde se ve»*, y la opinión no lo dice.
- **(b) Noticias.** `noticias_recientes` manda las 15 más nuevas del ticker sin la `relevance` que guarda el clasificador. En la #15, **7 de 15 tenían relevancia ≤ 0,2** (eran de otras empresas), con su tono; Claude tomó una de relevancia **0,0** (*«Wall Street is cooling on Jensen Huang's Nvidia»*, tono −1) como riesgo de MU. En la ventana, el 47 % de las noticias tiene relevancia ≤ 0,2.
- **(c) Objetivos.** `precios_objetivo` va crudo desde Yahoo (`:239`), con su `current`: en la #15, 787,35, el precio de cuando se bajó el consenso (15:01Z, las 10:01 ET), al lado de un `precio` de 811,53 de las 15:59 ET, sin rótulo.
- **Impacto.** Una opinión display-only que razona con números mal rotulados: el percentil invertido se puede leer al revés, el tono de otra empresa como el del ticker, y dos precios distintos sin hora. Ninguna tarea abierta lo cubre (la 426 es el resumen, la 427 la clasificación, la 420 el sector).
- **¿Por qué no antes?** **(a) NO EXISTÍA**: la 418 (valuación) es del 11/11; las noticias sin relevancia vienen de la 320, pero hasta la 417 ninguna opinión las recibía clasificadas, y la 404 sólo vio la opinión como daño latente de su [I-1].
- **Acción.** Mandar la definición y el sentido de cada pata y el corte (`al`), la fecha del almacén en lugar de «hasta hoy», la relevancia de cada noticia (o filtrar), y el `current` con su hora (o sacarlo); que el prompt lo explique, y subir `version_datos`.

### [D-2] El guard de la 399 acepta un comentario que dice lo contrario, y [K-2] el lock ya no está limpio: soupsieve 2.10 tiene tres CVE nuevos — **BAJA** → tarea **435**

Severidad: LOW · Confianza: ALTA · Categoría: guards (un guard que compara la frase, no el valor) y dependencias

- **[D-2] Evidencia (mutación en el sentido del falso positivo, sobre copias).** `_aceptados_en_requirements` (`tests/test_audit_ignora_solo_lo_aceptado_t399.py:26-35`) da por aceptado todo id que esté en un bloque donde aparezca `riesgo\s+aceptado`. Se agregó a una copia de `requirements.txt` *«# soupsieve CVE-2026-126190: NO hay riesgo aceptado; hay que subirlo a 3.0.2»* y a una copia de `ci.yml` su `--ignore-vuln`: el test da **VERDE**. Control (el `--ignore-vuln` sin el comentario): **ROJO**. Es la forma de la 173 y la 176 (el nombre en vez del valor).
- **[K-2] Evidencia.** `pip-audit -r requirements.lock --no-deps --disable-pip` (2026-11-16): además de PYSEC-2024-110 (aceptado), **soupsieve 2.10**: CVE-2026-126190 (se corrige en 4.0.0), CVE-2026-126193 y CVE-2026-126191 (3.0.2), de complejidad y ReDoS en el parseo y el matcheo de selectores CSS. El repo no importa `bs4` directamente: llega como dependencia. El job `audit` lo vería en rojo, pero tiene `continue-on-error` (decisión de la 65 y la 391), y desde el 11/11 no hubo un run que lo corra ([D-1]).
- **Impacto.** Bajo hoy. El guard muerde justo cuando alguien documente estos CVE: una frase negativa con el id silencia el aviso.
- **¿Por qué no antes?** **(a) NO EXISTÍA**: el guard es de la 399 (06/11) y los CVE son posteriores.
- **Acción.** Subir soupsieve (o aceptarlo por escrito), y que el guard pida una marca afirmativa por id (p. ej. `Riesgo aceptado: <id> — <motivo>`) y rechace las negaciones.

### [I-2] Los metadatos del classify dicen otra cosa: `classified_at` es la hora en que ARRANCÓ la corrida, y lo que cae a la heurística por timeout queda como clasificación definitiva — **BAJA** → tarea **436**

Severidad: LOW · Confianza: ALTA · Categoría: datos

- **Evidencia.** `scripts/classify_catalysts.py:143` fija `now` al empezar, y los checkpoints de la 409 (`:235`, `:239` → `:257`) graban ese mismo `now`. En la corrida del 11/11, las filas que fallaron por timeout entre las 21:13 y las 21:42Z tienen `classified_at = 21:02:48Z`. Hay corridas de 7 h (06/11, de 12:21 a 19:16). Lo que cae a la heurística por timeout (`Ollama backend failed … falling back to heuristic`) se graba `classified_by='heuristic'` con `event_type` puesto, y la cola sólo toma `event_type IS NULL` (`:168`): **qwen no la vuelve a ver**. `docs/DB_SCHEMA.md:73` lista `"fallback"` entre los valores de `classified_by`, y en la tabla no hay ninguno (ollama 68.544, ollama-7n 43.445, heuristic 1.951).
- **Impacto.** El único lector de `classified_at` es la 413 (`scripts/measure_news_cost_benefit_t413.py:257-259`), que lo usó como demora: su *«51 % tenían más de 1 día al clasificarse»* es una **cota inferior** (la conclusión se refuerza, no se cae). Y en noviembre hay 134 heurísticas por respaldo (11 el 11/11 entre las 18:13 y las 18:42), que se ven como `heuristic` igual que las de sec_8k por diseño.
- **¿Por qué no antes?** **(a) NO EXISTÍA**: la 409 y la 413 son de la ventana; el timeout de Ollama la 404 lo vio una vez y lo explicó bien, pero no a qué quedaba la fila.
- **Acción.** `classified_at` al persistir cada lote; marcar el respaldo distinto (`fallback`) y que la cola lo vuelva a tomar; corregir `DB_SCHEMA.md:73`; y una nota en el doc de la 413.

### [A-2] El header del backlog dice que la cuenta 1 es `signal_weighted`; la DB dice `equal_weight` desde el 07/09 — **BAJA** → parte de la tarea **431**

Severidad: LOW · Confianza: ALTA · Categoría: claims

- **Evidencia.** `docs/BACKLOG.md:11`: la cuenta 1 es *«`manual`, `signal_weighted`, 5 slots»*. La tarea 10 la renombró con un `UPDATE … allocation_mode='equal_weight' WHERE id=1` el 2026-09-07 (`docs/BACKLOG.md:4948`, *«cierra la mentira de config N1»*); la frase del header se escribió después del 13/09 (dice *«cerrada por Chapa el 2026-09-13»*). La DB hoy: `allocation_mode='equal_weight'`.
- **Impacto.** Chico: la cuenta está cerrada, pero quien reproduzca su historia la configura con el modo que el rename vino a desmentir.
- **¿Por qué no antes?** **(c-metodo)**: la 404 tenía en alcance *«header y En curso del backlog»* (`docs/auditoria_tanda_2026-11-05.md:21`) y la frase ya estaba. Ver §6.
- **Acción.** Corregir la palabra (va en la 431, que edita el mismo header).

### [H-1] Un aviso de Slack que sale bien no deja rastro: ni el log ni el canal permiten saber si llegó — **BAJA** → parte de la tarea **437**

Severidad: LOW · Confianza: ALTA · Categoría: operación

- **Evidencia.** `post_to_slack` (`integrations/slack.py:322-380`) loguea los fallos y devuelve `True` sin loguear cuando sale bien. En la ventana hubo 8 fills de la cuenta 2 (`slack_notify=1`, `slack_notify_on=both`) y ningún WARNING de Slack: lo más probable es que hayan salido, pero no hay cómo verlo. El token del bot no puede leer el canal: `conversations.history` → `missing_scope` (pide `channels:history`).
- **Impacto.** La pregunta (4) de `operacion` (*¿lo que debió avisar, avisó?*) no tiene cómo contestarse, y la 404 escribió *«ningún envío a Slack, ni fallido ni bueno»* con 10 fills en su ventana (§6).
- **¿Por qué no antes?** **(d) SE VIO Y SE DESCARTÓ MAL** en la 404: concluyó que no hubo envíos a partir de un log que no registra los buenos.
- **Acción.** Una línea INFO por envío bueno (tipo de aviso, sin el texto), o el scope de lectura para el bot.

## 2. Retirados

**Instrumentos míos que dieron un número falso, frenados antes de publicar:**

- **«La caja reconstruida de la cuenta 2 da $1.085.281 contra $1.036».** Comparé `side == "buy"` y la columna viene en mayúsculas (`BUY`/`SELL`): todas las órdenes contaron como ventas. Con `.lower()`, las dos cuentas cuadran al centavo (§4).
- **«2.425 noticias sin clasificar y la cola no las ve».** Conté `classified_by IS NULL`, que incluye filas viejas con `event_type` puesto (anteriores a esa columna). Las de `event_type IS NULL` son **147, todas del 11/11**: la corrida que cortó el cierre de la app (la 409, por diseño).
- **«La skill dice *UStanda,00*».** El archivo dice `US$0,00` (`.claude/skills/auditoria/SKILL.md:461`): el cargador de skills reemplazó `$0` por el primer argumento con que la invoqué (`tanda`). No es del repo; va a §6 como nota de método.
- **«La Anaconda no tiene `feedparser`».** No hace falta: la rama `rss` se borró en la 212 (`data/news_sources.py:28-36`).

## 3. Fase adversarial (el `verificador`)

Corrió como agente **independiente**, read-only, con el mandato de refutar y el instrumento primero, sobre [D-1] (el único ALTO) y los dos MEDIOS con los números más discutibles ([K-1] y [K-3]). No corrió la suite (pytest escribe cachés en el repo). Resultado: **los tres sobreviven recortados**, ninguno cae entero, y trajo un hallazgo mejor que los tres ([E-1]).

- **[D-1]:** cayó la premisa. No es que el CI no corra: dos runs quedaron huérfanos en un incidente público de GitHub y después no hubo ningún push. Bajó de ALTA a MEDIA. Sobrevivió, y más filoso, lo de `check_ci`: simulado con el `consultar()` real y un fetch falso, dijo VERDE cuatro días y después ROJO. También cayeron *«sin auth no se ve la causa»* y los 15 minutos por cierre.
- **[K-1]:** las 46 versiones distintas son 39 (mi instrumento: el `pip freeze` de conda); los 69 de pillow son 53 ids (mezclé entradas con ids); la pata de seguridad es baja (alcance real en la app); y no es nuevo, así que se reabre la 401. Trajo la causa probable: los pedidos de reabrir la app sin decir cómo.
- **[K-3]:** el núcleo sobrevive con mejor evidencia (el transcript del 11/11). Cayó la pata *«pisó la opinión de origen»*, que es del reemplazo por día y no del WIP → [E-1].
- **Su veredicto sobre el backlog ya escrito** (*«no apto para commit»*): los números de la 432, la premisa y la severidad de la 430, la acción manual de GitHub y la pata de la 433. Se corrigió todo, y la acción manual se sacó: el próximo push es la prueba.
- **Re-verificado por mí antes de aceptarlo:** los dos incidentes del 11/11 en `githubstatus.com`; los 39 contra el lock; los 53 ids de pillow; y que la 417–421 citan *«la opinión de MU del 2026-11-11»*. Una cita suya (`opinion_claude.py:659-684`) era del archivo con el WIP: en `HEAD` es `:629-655`.

## 4. Barridos limpios (con lo que se miró)

- **B. muestra.** Los conteos nuevos que deciden algo llevan su ventana a la vista: `TRIMESTRES_SORPRESA = 4` y `ANIOS_FUNDAMENTALES = 4` mandan la fecha de cada fila; el aviso de cola de la 406, la fecha de la más vieja; el test de la 422 cuenta los skips **por su motivo** y tiene su propio control (`test_el_contador_ve_los_skips_y_no_otros`). Ninguna operación movió la muestra de un veredicto: `pit_signals` y el cohorte siguen en el 09/09 por diseño (251, 286), el universo sigue en 127 (WBD incluido, acción manual de la 369), y el vaciado de la cola de noticias (12.866 → 147) no tocaba ningún veredicto publicado (lo de la 413 va en [I-2]).
- **C. desvíos.** `settings.json` sin cambios desde el 13/09; `analysis/harness_config.py` sin cambios en la ventana; el diff de `paper_trading/engine.py` es sólo el decorador de avisos de la 407. El número fechado de `barrier_eval` sigue fechado, y envejece: en la ventana, el 10, 12, 13 y 16/11 no hubo scan en sesión.
- **E. estado.** `data/fundamentals_pit/`: los 125 archivos del 21/10, **decidido** por la 394 (disparador manual, dicho en la tarjeta); lo que la opinión no dice va en [I-1]. `earnings_cache` (68 tickers) y `dividend_cache` (último fetch 02/10) se llenan a demanda con TTL: el tamaño y la fecha dicen uso, no atraso. La cinta intradía se archivó sola el 06/11 21:00 (1.910 filas de octubre). Surprise es semanal: el último el 05/11 y el siguiente tocaba el 12/11, con la app cerrada.
- **F. pantalla (lo demás).** Los 102 snapshots de la cuenta 2 en la ventana cumplen `cash + positions_value = total_equity` exacto, y la caja del último (21:05Z del 11/11) es la de la cuenta. La tarjeta de calidad nombra cada pata y el corte; la de la opinión dice *«no validada»*. Lo de los datos de la opinión va en [I-1].
- **G. cuentas.** Cuenta 2: caja **$1.036,08** reconstruida al centavo (capital + ventas − compras − comisiones + $117,50 de dividendos), acciones netas = las 10 posiciones; cuenta 1: **$4.673,98**, cuadrada, sin órdenes en la ventana. Ninguna violación de `max_positions` después del 02/09 (la de ese día es la 93). Dividendos: `creditos_pendientes` del motor sobre la copia → **0 pendientes** (4 acreditados; los ex-date futuros de las posiciones todavía no están en el calendario, como sabe la 350). Cartera real: 0 posiciones que difieren de sus transacciones; ninguna transacción nueva.
- **H. operación (lo demás).** Scan cada 15 min los días con la app abierta; harvest horario 127/127 con *«fuentes 4/4 limpias»*; el classify terminó cinco veces (06/11 19:16, detenido a pedido; 09/11 13:38; 10/11 20:28; 11/11 13:18 y 15:36) y la cola bajó de 12.866 a 147. Backups: los 9 de `backups/` pasan `quick_check`, con alembic coherente con su fecha (`0020` = la cabeza del repo), y la rotación deja 7 diarios. La nube sigue sin lector: 7 de 7 arranques con *«FUENTE NO DISPONIBLE»* (la 356, con fecha límite ~25/01/2027) y el stack y el zip de la 405 sin subir (acción manual): es lo conocido, y se suman 12, 13 y 16/11 como días cuyo consenso sólo existe en DynamoDB, si la Lambda corrió.
- **J. rendimiento.** Scans de 3,3 a 142 s contra 900 s de intervalo; ningún `database is locked`. Las consultas nuevas usan índice: `noticias_recientes` → `SEARCH … ix_news_events_ticker` (4,9 ms); `opinion_de_hoy` → `SEARCH … ux_claude_opinions_ticker_fecha`. La llamada a Claude tiene techo (`TIMEOUT_S = 240`) y el balance va por `_run_with_timeout`.
- **K. dependencias (lo demás).** Ningún import de terceros nuevo en la ventana (`git diff 22abba2..HEAD`: stdlib, módulos propios, PyQt6 y SQLAlchemy). Lo que no es Python está declarado: el CLI de Claude (el de la extensión de VS Code) en `analysis/opinion_claude.py:136-151`, y Ollama/qwen en la skill `catalyst-pipeline`. `requirements-dev.txt` sin techo salvo ruff: conocido y cubierto por el `-c requirements.lock` del CI (la 404).

## 5. Censo de logs (ventana `2026-11-05 12:10:00` → `2026-11-11 18:42:59`)

279 WARNING+ en 14 familias (42 firmas normalizadas: las líneas de un solo ticker de antes de la 407 y las variantes de yfinance cuentan aparte), más 11 tracebacks (cada uno, la cadena `TimeoutError` → `ReadTimeoutError` → `ReadTimeout` de Ollama). Ninguna de procesos de la suite; una de una prueba a mano.

| firma | n | origen | clase | nota |
|---|---|---|---|---|
| `Scan Sim Segundo (cuenta 2): 1/127 tickers sin precio este scan` | 100 | app | conocida (369), con su tasa | una por scan: WBD, hasta que se haga la acción manual |
| `… 51/127 sin precio — posiciones SIN evaluar (stops no corridos): ROST, WELL` | 1 | app | explicada | 09/11 17:22, dentro del breaker escalado (17:20–17:26); el scan siguiente vuelve a 1/127 |
| `XGBoost TK: unstable model` | 90 | app | conocida (364), con su tasa | 7 a 11 por re-entrenamiento; hubo 10, al arrancar y con cada barra nueva (12:10 la de la sesión, 18:06 la del cierre), como en la 404 |
| `N ticker(s) cachean la barra de la sesion de HOY` | 22 | app | conocida (407): **el arreglo se confirma** | 13 del 05/11, antes de `fc3e304` (11 de un solo ticker); desde el 06/11, 9 en 6 arranques: a lo sumo una del arranque y una del primer scan |
| `FinanzIAs corre con …anaconda3… y no con el .venv` | 7 | app | **conocida por encima de su cierre** | [K-1]: todos los arranques |
| `Nube — FUENTE NO DISPONIBLE` | 7 | app | conocida (356) | acción manual pendiente |
| `WBD: La serie diaria (2y) termina…` | 7 | app | conocida (369) | |
| `Vigía: la interfaz estuvo trabada N s` | 5 | app | explicada | 2,2 a 3,0 s al arrancar, bajo el umbral de volcado (5 s); `congelamientos.log` sin escrituras desde el 21/10 |
| `$TK: possibly delisted; no price data found` (yfinance) | 13 | app | explicada | UPS, XEL, V, TEAM y ADBE, segundos antes de abrir el breaker (son lo que lo dispara); MMM, GM y EXC transitorios (el scan siguiente sólo extraña WBD); 5 de JNJH, tipeado en la UI (`failed_tickers`, `last_operation=analyst`) |
| `classify: la cola no se vacía — N noticias…` | 4 | app | conocida (406), por diseño | la cola baja: 12.866 → 4.906 → 3.262 → 1.913 |
| `Throttle de Yahoo detectado / se recuperó / persiste` | 4 + 4 + 1 | app | explicada | el breaker anda: de 2 a 7 min por incidente |
| `TK Error 401: Invalid Crumb` | 2 | app | explicada | transitorio, como en las tandas anteriores |
| `Ollama backend failed … falling back to heuristic` + tb `ReadTimeout` | 11 | app | explicada, **con la tasa en alza** → [I-2] | 11 en 30 min (11/11, 18:13–18:42) contra 1 en la ventana anterior; timeout de 60 s por diseño; cada una deja una heurística definitiva |
| `El intérprete se apaga sin haber pasado por el cierre de la app` | 1 | `python -c` | explicada | una prueba a mano del 05/11 16:35, no la app |

**Lo que no aparece y debería:** un envío bueno a Slack ([H-1]). Los fallos de la opinión de Claude tampoco se loguean, pero eso es **una decisión** (la 320 y la 287: *«vuelven como resultado, no como excepción»*, `ui/analysis/opinion_card.py:31-37`), no un hallazgo.

## 6. Deuda de método (sólo lo que es (c-metodo) o (d))

1. **[H-1], (d) de la 404: un envío a Slack que sale bien no deja línea, así que la ausencia en el log no dice nada.** La 404 escribió *«ningún envío a Slack, ni fallido ni bueno»* con 10 fills de la cuenta 2 en su ventana (05/11, 11:09 y 11:38 locales), que el motor avisa por diseño. Para `operacion`: los avisos que debieron salir se cuentan desde lo que los dispara (fills, caídas, alertas), no desde el log.
2. **[A-2], (c-metodo): una afirmación de configuración de cuenta se contrasta contra su fila de `paper_accounts`, también la de la cuenta cerrada.** La corrección (el `UPDATE` de la tarea 10) estaba en el backlog; la frase falsa se escribió después, y las corridas leían el header sin cruzarlo con la DB.
3. **Lección de esta corrida (no es deuda de una anterior):** antes de afirmar que *el CI no corre*, cruzar el run trabado contra `githubstatus.com` y contra `pushed_at`: sin un push posterior no hay evidencia de que falle hoy. Lo cazó el `verificador` ([D-1]). Y una acción manual que lleva varios arranques sin hacerse se lee en el log, no en su ítem ([K-1]).
4. **Nota:** la skill, invocada con argumentos, muestra `US$0,00` como `UStanda,00`, porque el cargador reemplaza `$0`. Un monto en la skill no debería escribirse `$` + dígito.

## 7. Alcance no mirado (lista)

- **F:** la referencia de Home no se recalculó a mano: su cálculo (`paper_trading/referencia.py`) no cambió en la ventana; la 392 cambió dónde corre y la 393 la unión de frames, las dos con tests. **Diferido → tarea 437.**
- **D:** los guards nuevos de la 402, 411, 412, 424, 405 y 394 se leyeron pero **no se mutaron**; se mutó el de la 399 ([D-2]), y el de la 422 trae su propio control. **Diferido → tarea 437.**
- **I:** los bloques de EDGAR de la opinión contra la fuente primaria, más allá del año fiscal 2025 de MU (que coincide con el 10-K: ventas 37.378 M, ganancia 8.539 M, EPS 7,59). Pedirle a la SEC manda el `SEC_EDGAR_USER_AGENT` de Chapa, y no se hizo sin preguntar. **Diferido → tarea 437.**
- **H:** la entrega de Slack ([H-1] → 437). La Lambda, la tabla, las alarmas y la factura de AWS: sin credenciales en la máquina (motivo re-verificado: 7 de 7 arranques sin el perfil `[finanzias-lector]`); es la 356 y la acción manual de la 405, ya en la cola.
- **K:** los pines del zip de la Lambda contra el lock: el `dist/recolector_nube.zip` en disco es del 19/10 y la acción manual de la 405 dice regenerarlo; lo que corre en AWS no se puede ver (la 356).
- **L:** fuera de `finanzias.log` y `congelamientos.log`, nada (stderr de la app no se guarda).
- **A–E:** el código sin cambios desde la tanda anterior (c-alcance).

## 8. Mapeo hallazgo → tarea

Verificado fila por fila contra `docs/BACKLOG.md` (2026-11-17, ~01:40): el encabezado `### N.` existe, el enunciado nombra el hallazgo (los agrupados, con su etiqueta), y la tarea está en el `El orden queda …` del *Repriorizado 2026-11-16*.

| hallazgo | sev. | tarea | verificado en el backlog |
|---|---|---|---|
| [D-1] runs huérfanos; `check_ci` dijo VERDE 4 días y después ROJO | MEDIA | **430** | `### 430.` — *«huérfanos»*, *«exit 0, VERDE»*, el caso `queued` con el anterior en `success` en los criterios |
| [A-1] el cierre sin camino para el «no se sabe» | MEDIA | **431** | `### 431.` — *«[A-1] Qué pasa»*, los cinco lugares y el estado del CI en el registro |
| [A-2] `signal_weighted` de la cuenta 1 en el header | BAJA | **431** (parte de) | `### 431.` — *«[A-2] Qué pasa»* y *«corregir el header»* en el alcance |
| [K-1] la app en la Anaconda: reabrir la 401 | MEDIA | **432** | `### 432.` — *«39 en otra versión»*, los 13 pedidos de reabrir |
| [K-3] la app corre el WIP del árbol | MEDIA | **433** | `### 433.` — *«version_datos=5»*, *«cuando commitee la 425»* |
| [E-1] la opinión se pisa por día | MEDIA | **438** | `### 438.` — *«upsert»*, *«ocho tareas abiertas»* |
| [I-1] (a) calidad, (b) noticias, (c) objetivos | MEDIA | **434** | `### 434.` — las tres patas, cada una con su rótulo |
| [D-2] el guard de la 399 acepta lo contrario | BAJA | **435** (parte de) | `### 435.` — *«[D-2] Qué pasa»* y la mutación en los criterios |
| [K-2] soupsieve 2.10 con tres CVE | BAJA | **435** | `### 435.` — *«[K-2] Qué pasa»* |
| [I-2] `classified_at` de la corrida; respaldo como `heuristic` | BAJA | **436** | `### 436.` — las dos patas y `DB_SCHEMA.md:73` |
| [H-1] un aviso de Slack bueno no deja rastro | BAJA | **437** (parte de) | `### 437.` — *«[H-1] Slack»* |
| §7 alcance diferido (referencia de Home, mutaciones, EDGAR) | — | **437** | `### 437.` — *«Alcance diferido por la 429»*, los tres ítems |
| §6 deuda de método (Slack, `signal_weighted`, githubstatus, `$0`) | — | **437** | `### 437.` — *«Deuda de método»*, (a)–(d) |
| la corrida misma | — | **429** | `### 429.` — el resumen y lo que falta para cerrarla |

**Sin publicar en la cola, a propósito:** los cuatro instrumentos míos retirados (§2) y las patas que tumbó el `verificador` (§3), que se borraron de los enunciados.
