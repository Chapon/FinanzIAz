# Auditoría — tanda de las 12 áreas, 2026-11-05

Pedido de Chapa: *«corré todas las auditorías, y chequeá si todo lo que creamos en Amazon está
funcionando como lo esperamos»*. Se corren las 12 áreas **de a una**, cada una con su ciclo
(kill-criteria → barrido → `verificador` sobre HIGH/CRITICAL → tareas → tabla de mapeo). Un doc
para la tanda, como las anteriores (`auditoria_tanda_2026-10-26.md`).

**Ventana común:** desde la tanda anterior (2026-10-26) hasta hoy, 2026-11-05. Log en hora local
(UTC−3), DB en UTC: todo cruce convierte.

## §0. Kill-criteria — congelados el 2026-11-05, ANTES de abrir un archivo

Se congelan los doce juntos. Cada condición de barrido limpio va en las DOS direcciones:
*lo escrito es falso* y *lo verdadero no está escrito / no está hecho*.

**Exclusión heredada que se re-verifica:** `operacion` (H) excluía *«la infraestructura de la 196
(Lambda/DynamoDB), hasta que exista»*. Existe desde la 355: **la exclusión caducó y Amazon entra**.

| área | se mira | queda afuera (motivo) | barrido limpio = |
|---|---|---|---|
| **claims** (A) | `CLAUDE.md`; las skills de `.claude/skills/` y los comandos de `.claude/commands/` (por lista, no por conteo); header y *En curso* del backlog; las frases que corrigieron las tareas cerradas desde el 10-26, buscadas con `grep` en todo el repo; los procesos declarados en varios lugares (done, arranque, cierre, intérprete de la app) comparados lugar contra lugar | docs de análisis fechados (son fotos, no claims vivos) | (1) ninguna afirmación mirada contradice al código/DB de hoy; (2) todo cambio de proceso desde el 10-26 (401 `.venv`, 403 certifi) está en **cada** lugar que declara ese proceso |
| **muestra** (B) | comparaciones `len()`/contadores que deciden «completo» en el código cambiado desde el 10-26; operaciones que movieron la muestra desde el 10-26, cruzadas **por contenido** con su re-verificación | código sin cambios desde la tanda anterior (lo barrió ella) | (1) ningún chequeo por cantidad nuevo decide completitud; (2) ninguna operación que movió muestra quedó sin re-verificación |
| **desvios** (C) | `deviations_keyed()` contra la config viva (settings.json + cuenta 2) y contra el código de `run_scan` | si los desvíos importan para un veredicto (es medición) | (1) ningún texto declarado contradice el valor vivo de sus perillas; (2) ninguna perilla viva que difiere del harness queda sin clave |
| **guards** (D) | el **resultado** del CI (sha contra `origin/main`); el workflow contra los cuatro comandos del done; los guards nuevos o cambiados desde el 10-26 (`check_ci` con certifi, aviso de intérprete de `main.py`) mutados en el sentido del falso positivo | guards sin cambios desde la tanda anterior | (1) el CI del sha de `origin/main` está verde y corre lo mismo que el done; (2) cada guard nuevo se pone rojo con la declaración contraria |
| **estado** (E) | `data/parquet/`, `data/pit_signals/`, artefactos del cohorte, `surprise_profiles.json`, `earnings_cache`, universos, archivo de la cinta intradía, y el espejo local de lo que baja DynamoDB | regenerar nada (read-only) | (1) cada store tiene dueño que lo regenera; (2) ninguno está más atrás que sus pares fuera de su contrato |
| **pantalla** (F) | Home (curva y cartera real) y Paper de la cuenta 2: cada número recalculado a mano desde la DB en solo lectura | estética, layout; pestañas no listadas acá | (1) cada número mirado coincide con el cálculo a mano y su rótulo; (2) todo vacío/viejo se dice como tal |
| **cuentas** (G) | cuadre de caja y acciones de la cuenta 2 (y que la 1 no se movió); `max_positions`, caja ≥ 0; dividendos que **debió** registrar contra los registrados; cartera real (cantidades, promedio, fecha contra el rango del día) | si las decisiones fueron buenas (es backtest) | (1) cuadra al centavo; (2) ningún límite violado y ningún flujo debido sin registrar |
| **operacion** (H) | log de la ventana por frecuencia; scan en cada día hábil (`paper_equity_snapshots`); Slack; backups, rotación y **restore** a una copia; **Amazon**: la Lambda corrió en cada día hábil (`corrida#{día}`), lotes completos, `nube_sync` importó cada día, credenciales y TTL | — | (1) ningún job falló, se repitió sin tope ni dejó de correr en un día hábil; (2) cada día hábil tiene corrida de Lambda + import local, y el backup restaura |
| **datos** (I) | distribución de la clasificación de noticias desde el 10-26; cobertura de consenso y facts por ticker del universo vivo; lo que trae la nube contra lo que trae Yahoo localmente | si el dato predice (es medición) | (1) ningún campo degenerado nuevo; (2) ningún ticker del universo vivo sin cobertura que no avise |
| **rendimiento** (J) | duración de scan contra su intervalo en el log; `database is locked`; techo de tiempo de los jobs, **el timeout de la Lambda contra su duración real** | optimizaciones que no cambian conducta | (1) nada tarda más que su intervalo/techo; (2) todo job de fondo tiene techo |
| **dependencias** (K) | imports de terceros contra lo declarado; `.venv` contra el lock versión por versión; `pip-audit -r requirements.lock`; `requirements-dev.txt`; los pines del zip de la Lambda contra el lock | actualizar versiones | (1) nada de lo declarado diverge de lo instalado; (2) nada importado sin declarar, ni pin con aviso de seguridad sin tarea |
| **logs** (L) | censo de toda firma WARNING+/traceback de la ventana, separada por origen, cada una clasificada conocida / explicada / desconocida, con su tasa | contenido de los INFO | (1) ninguna firma sin clasificar; (2) ninguna conocida reaparece después del cierre de su tarea o por encima de su tasa medida |

---

# Corrida

**2026-11-05, de ~11:50 a ~13:30 locales**, con la app **abierta** (arrancó a las 11:07, con la
Anaconda). Antes de cualquier área: `check_ci.py --ultimo` → `3e9243f` **VERDE**, que es
`origin/main` y `HEAD`; `git status` con sólo `data/catalyst/surprise_profiles.json` modificado (el
rebuild del scheduler; se commitea aparte, decisión de la 286). El criterio de arriba no se tocó.

**Ventana de código:** desde `f5058e4` (la tanda anterior) entraron la 390, 391, 400, 401 y 403.
**Ventana de estado vivo:** el log desde `2026-10-26 17:05:45` (donde cortó el censo anterior); la
app abrió el 30/10 y hoy. Días hábiles sin la app: 27, 28 y 29/10, 2, 3 y 4/11.

**Instrumentos.** La DB es una copia de `finanzias.db` + `-wal` al scratchpad a las 12:12, abierta
siempre con `mode=ro` (alembic `0020`). Lo que corrió con funciones del repo (`creditos_pendientes`,
`medir_cobertura_de_scan_t265.py`) leyó esa copia. Nada de esta corrida escribió el log de
producción ni la DB viva.

**Dos instrumentos míos que dieron un número falso, frenados antes de publicar:**

- **«6 tracebacks de Slack en la ventana».** Filtré la ventana con `awk '$0 >= "2026-10-26 …"'`,
  que compara texto: las líneas de traceback no empiezan con fecha, y `requests…` ordena después
  de `2026`, así que entraban **todas** las del log. Por número de línea, las 14 de `slack.com`
  son anteriores a la ventana: en la ventana no hubo ningún envío a Slack, ni fallido ni bueno.
- **«`pit_signals` sin fecha de fin».** Leí el último elemento de una lista que no existe: el
  artefacto guarda `signals` como dict por fecha. Releído con `max(signals)`: los 126 terminan el
  2026-09-09, `complete=True` (el cohorte, por diseño de la 251).

## Hallazgos sobrevivientes

### [I-1] El classify diario escribe todo al final: no persiste nada desde el 23/10, la cola crece sola y mientras corre apaga el harvest horario — **ALTA** → tarea **406**

Severidad: HIGH · Confianza: ALTA · Categoría: datos (y operación, y logs: lo que no aparece)

- **Ubicación.** `scripts/classify_catalysts.py:115-183` (fase 1 lee **todas** las `event_type IS
  NULL`, fase 2 clasifica en memoria, fase 3 escribe al final); `analysis/news_digest.py:544` (sin
  `--limit` ni techo); `paper_trading/scheduler.py:240-259`, `:615-617` (un `QThread` que el cierre
  suelta a los 2 s); `:280-281`, `:1086-1088` (el gate del harvest horario).
- **Evidencia.** `news_events` por `fetched_at`: 0 sin clasificar hasta el 22/10; el 23/10, 906 de
  1.723 (las de los harvest horarios posteriores a la corrida); el 26/10, 30/10 y 05/11, **todas**
  (2.159, 5.920, 5.169). Cola: **14.154**, publicadas del 20/10 al 05/11. Ninguna fila con
  `classified_at ≥ 2026-10-26`. Log: las corridas del 21, 22 y 23/10 terminan con `Classify:
  scanned …` en 1–1¼ h (1.518 noticias, 11:28→12:41 el 22/10); la del 23/10 (11:47) es **la última
  que terminó**. La del 26/10 (16:58) y la del 30/10 (19:13) arrancaron y nunca escribieron la línea
  final; la de hoy (11:16) está corriendo con la cola entera. Último `fetched_at` de hoy: 14:16:33
  UTC (11:16 local): ningún harvest horario en toda la rueda.
- **Razonamiento.** A ~2,9 s por noticia, 14.154 son ~11 h: la corrida sólo termina con una sesión
  de ≥11 h seguidas, y cada día con la app cerrada suma 2.000–6.000 (Finnhub se pone al día con 7
  días). Cerrar la app mata el `QThread` y se pierde todo lo clasificado.
- **Impacto.** (1) Desde el 23/10 ninguna noticia tiene tipo ni tono de qwen. (2) Mientras corre, el
  harvest horario está apagado (`daily_worker_running`): hoy, cero noticias intradía. (3) Noticias
  muestra la heurística al vuelo (tono −1/0/+1) y la celda no distingue heurística de escala vieja
  (el tooltip `TONO_ESCALA_VIEJA` mezcla las dos). (4) Latente: `opinion_claude.noticias_recientes`
  lee las columnas crudas y la próxima opinión sale con `tipo`/`tono` en `None`, que entra así a la
  muestra de la 321. (5) Nada lo avisa: el resumen sólo se loguea si la corrida termina.
- **Verificación (el `verificador`).** No hay otro camino que persista parcial (el `.bat` tampoco usa
  `--limit` y no está programado); ninguna tarea lo cubre (lo más cercano, la 234, es de locks);
  `tests/test_news_digest.py` inyecta el `classify_main` y no prueba el corte.
- **¿Por qué no antes?** **(d) SE VIO Y SE DESCARTÓ MAL**: la tanda del 26/10 escribió *«906, todas
  sin clasificar todavía (la clasificación diaria arrancó a las 16:52)»* y lo dio por bueno sin
  mirar si esa corrida terminaba; no terminó. Ver §6.
- **Acción.** Persistir por lotes durante la clasificación (o un techo por corrida), sacar el classify
  del gate del harvest horario, avisar cuando una corrida no termina, y vaciar la cola.

### [H-1] Lo de AWS lleva 14 días hábiles desplegado sin que nada lo lea ni lo vigile, con la temporada Q3 en juego — **ALTA** → tarea **405**

Severidad: HIGH · Confianza: ALTA (que nada lo lee ni lo vigila) / no medible desde acá (si la
Lambda corre) · Categoría: operación (y guards: un aviso que no existe)

- **Qué es, y qué no** (recorte del `verificador`). No es un defecto nuevo de código: es el costo de
  la deuda que ya anotan la 355 (kill-criteria sin medir), la 356 (sin key) y la 245 (el aviso,
  detrás de la 356). Lo que publica esta corrida es cuánto lleva y qué se pierde.
- **Evidencia.** Sin `~/.aws/credentials`, sin variables `AWS_*`, sin CLI `aws`;
  `cloud_import_cursor` vacía; `Nube — FUENTE NO DISPONIBLE` en los diez arranques desde el 19/10.
  `infra/recolector_nube.cfn.json`: tabla, log group (14 días), rol, Lambda, reintentos (sin
  `DestinationConfig`), cinco horarios, usuario lector y presupuesto — **ninguna alarma**. La 355
  (desplegada el 16/10) con sus kill-criteria (a)–(d) sin medir; `git log --since=2026-10-16` sobre la
  nube: sólo código (`843af2b`, `01e5d33`, `37bb2f3`), ninguna medición. En la DB local faltan los
  consensos de **27, 28 y 29/10 y 2, 3 y 4/11** (127 tickers los demás días hábiles).
- **Impacto.** Si la Lambda corrió, esos seis días existen sólo en DynamoDB, con TTL de 90 días: el
  del 27/10 vence ~25/01/2027. Si no corrió, ya no se recuperan y nadie lo sabe. Es justo la
  temporada Q3 de la que depende T-CAT-5b (*Bloqueado*).
- **Patas del impacto que el `verificador` tumbó y se borraron:** *«los logs de CloudWatch ya
  expiraron, nadie puede saber si corrió»* — la evidencia sobrevive en `corrida#{día}` (TTL 90 días,
  `scripts/recolector_nube.py:268`) y en las métricas de la Lambda (15 meses); y *«el zip viejo
  pierde las noticias del fin de semana»* — sólo en DynamoDB: la app trae 7 días de Finnhub
  (`data/news_sources.py:683`) y abrió con huecos menores a 7 días.
- **A verificar (no se afirma):** si el paso 6 de *Acciones manuales* (confirmar el mail de Budgets)
  existe — el template suscribe el mail directo (`SubscriptionType: EMAIL`), no por SNS.
- **¿Por qué no antes?** **(b) FUERA DE ALCANCE, con la exclusión caducada**: la skill (§H) excluye
  *«la infraestructura nueva de la 196 (Lambda/DynamoDB), hasta que exista»*; existe desde el 16/10,
  y la tanda del 26/10 la heredó sin re-verificar el motivo (vio la falta de credenciales y la dio
  por *«bien listada como abierta»*). La skill manda re-verificar el motivo de cada exclusión: es
  deuda de método (§6).
- **Acción.** La key de la 356 antes del 25/01/2027 y medir la 355 sobre los `corrida#`; una alarma o
  destino de falla en el template; aclarar el paso 6; y sacar la exclusión de la skill.

### [L-1] El aviso de barra provisional sale una vez por ticker dentro del scan: 126 líneas, cuando la 243 cerró «una por arranque» — **MEDIA** → tarea **407**

Severidad: MEDIUM · Confianza: ALTA · Categoría: logs (conocida que reaparece por encima de su cierre)

- **Evidencia.** `cachean la barra de la sesion de HOY`: 126 el 05/11 (12:08:14 → 12:10:00, dentro
  del scan que cierra a las 12:10, intercalados con el XGBoost por ticker), 127 el 23/10, 69 el
  26/10; casi todas de 1 ticker. `_avisar_provisionales` (`data/yahoo_finance.py:1935`) emite una
  línea por llamada pública (`:2109`, `:2266`), y la fase `analyze` pide de a un ticker. Son 126 de
  los 171 WARNING+ de la ventana (74%; el 68% era lo que motivó la 243).
- **¿Por qué no antes?** **(d) SE VIO Y SE DESCARTÓ MAL**: las tandas del 23/10 y del 26/10 la dieron
  por *«conocida (112, 243): una línea por lote, por diseño»* sin contrastar la tasa contra el cierre
  de la 243. Es la regla de *«una conocida se clasifica con su tasa»* (§L), salteada.
- **Acción.** Un resumen por scan, no por llamada pública.

### [K-1] La 399 quedó corta: msgpack es un noveno paquete y pillow 12.3.0 ya corrige 13 de 52 — **BAJA** → parte de la **399**

Severidad: LOW · Confianza: ALTA · Categoría: dependencias

- **Evidencia.** `pip-audit -r requirements.lock --no-deps --disable-pip` (2026-11-05): 83 ids
  distintos en 9 paquetes. `msgpack` 1.2.1, CVE-2026-114613 (corrige 1.2.3; lo arrastra
  `CacheControl`, o sea `pip-audit`). pillow: 13 ids corrigen en 12.3.0 y 39 en 13.0.0. El `.venv`
  coincide con el lock en los 105 pines y tiene `boto3`.
- **¿Por qué no antes?** **(a) NO EXISTÍA**: avisos publicados después de la 399.
- **Acción.** Re-medición escrita en el enunciado de la 399 (2026-11-05).

### [A-1] Tres lugares siguen diciendo Anaconda y una skill manda la recolección a la Pi — **BAJA** → tarea **408**

Severidad: LOW · Confianza: ALTA · Categoría: claims

- **Evidencia.** `tests/README.md:6` y `tests/test_entorno_cumple_requirements_t284.py:3-7` (el done
  en la Anaconda), `scripts/daily_catalyst_harvest.bat:4,25` (*«Run by Windows Task Scheduler»* y el
  python de la Anaconda; ningún llamador), `.claude/skills/catalyst-pipeline/SKILL.md:69` (*«la
  solución de fondo es la recolección en la Pi»*). Buscado con `grep` en todo el repo, no leído.
- **¿Por qué no antes?** Lo de la Anaconda, **(a)**: lo volvió falso la 401, posterior a la tanda del
  26/10. Lo de la Pi, **(c-metodo)**: falso desde el 01/10, y las tandas del 20/10 y del 23/10
  declararon leer las skills; la regla de *«las correcciones viejas se BUSCAN»* aplica también a las
  **decisiones** que cambian un destino (Pi → AWS), no sólo a los claims que una tarea corrigió.

## Retirados

Ninguno entero. El `verificador` recortó patas de los dos ALTA (escritas arriba, en cada uno) y
corrigió cuatro afirmaciones de [I-1] antes de publicarse: *«desde el 23/10»* (la corrida del 23
terminó; lo que no se clasificó ese día es posterior), *«la del 05/11 nunca terminó»* (está en
curso), *«no puede volver a terminar sola»* (puede, con ≥11 h de app abierta) y *«sesiones de 1–2
h»* (el 26/10 la app siguió viva más de 3 h). También tumbó *«surprise, reacción y briefing ven la
ventana vacía»*: `surprise_score` no lee `news_events`, `exit_veto` está apagado, la reacción es
manual y el briefing pasa por la heurística; queda sólo `opinion_claude`, como daño latente.

## Barridos limpios (con lo que se miró)

- **B. muestra.** El único conteo nuevo que decide algo es `anios_cubiertos` (la 390), y la 390
  justamente le agregó la vigencia; sólo lo usa el reporte de `build_fundamentals_pit.py`. Ninguna
  operación movió la muestra: `pit_signals` sigue en el 09/09 (por diseño de la 251).
- **C. desvíos.** `settings.json` sin cambios desde el 13/09. La cobertura de scan re-medida con
  `medir_cobertura_de_scan_t265.py` sobre la copia: 45 de 90 días hábiles sin scan en sesión (01/07 →
  05/11), contra los 34 de 66 que el texto de `barrier_eval` declara con fecha (02/10): número
  fechado, no falso.
- **D. guards.** `check_ci.py --ultimo` → `3e9243f` VERDE = `origin/main` = `HEAD`. El aviso de
  intérprete de `main.py` compara la ruta del `.venv`, no las versiones, pero
  `test_el_interprete_del_done_tiene_las_versiones_del_lock` las compara en el done: no es ciego.
- **E. estado.** Frames `10y` y `1y` del cohorte en el 09/09 (la 251 y la 286); `2y` al día salvo WBD
  (la 369). ASML sin artefacto PIT: declarado (149/156/268).
- **F. pantalla.** El código de `ui/` no cambió desde la tanda anterior. Ningún snapshot de ninguna cuenta viola
  `cash + positions_value = total_equity` (a 0,01); la caja de la cuenta es la del último snapshot. Lo de
  Noticias va en [I-1].
- **G. cuentas.** Cuenta 2: caja $14.228,81 reconstruida al centavo, acciones netas = posiciones; la 1
  sin movimientos desde el 01/07 y cuadrada. Ninguna compra sobre `max_positions` desde la 93
  (02/09). Dividendos: `creditos_pendientes` del motor sobre la copia da **0 pendientes**; 4
  acreditados (el de OKE del 02/11, hoy). Cartera real: 0 posiciones que difieren de sus
  transacciones; ninguna transacción nueva desde el 07/10.
- **H. operación (lo demás).** Backups del 26/10, 30/10 y 05/11 (uno por arranque); los 12 de octubre
  y noviembre pasan `integrity_check` copiados sin su `-wal`, alembic coherente con su fecha. Los
  `-wal` sueltos (20/10 y 26/10) tienen 0 B: son de una lectura posterior. Slack: ningún envío en la
  ventana. Scheduler: refresh diario, cinta, dashboard y surprise corrieron los días con la app
  abierta.
- **J. rendimiento.** Scans de 5,2 a 159,8 s contra 15 min; ningún `database is locked`. La Lambda:
  timeout 900 s contra 24 s del lote medido el 16/10.
- **K. dependencias (lo demás).** `requirements-dev.txt` sin techo, pero el CI lo instala con `-c
  requirements.lock`; lo del pin del done es la 402.

## Censo de logs (ventana `2026-10-26 17:05:45` → `2026-11-05 12:10:00`)

171 WARNING+ en 12 firmas, más un traceback. Ninguna de procesos de la suite.

| firma | n | origen | clase | nota |
|---|---|---|---|---|
| `cachean la barra de la sesion de HOY` | 126 | app | **conocida por encima de su cierre** | [L-1] → 407 |
| `XGBoost TK: unstable model` | 23 | app | conocida (364), con su tasa | 4 en el primer scan del 30/10; 10 en el primero de hoy y 9 a las 12:08, con la primera barra de la sesión (como el 23/10) |
| `Scan … 1/127 tickers sin precio` | 6 | app | conocida (369) | WBD, acción manual pendiente |
| `parquet_cache: ABBV 10y … hace 33 ruedas` | 3 + 3 | `measure_calidad_t384`, `run_cartera_calidad_valor_t385` | conocida (286) | runners del 26/10, no la app |
| `FinanzIAs corre con …anaconda3… y no con el .venv` | 2 | app | conocida (401) | acción manual pendiente: la app se abrió el 30/10 y hoy con la Anaconda |
| `Nube — FUENTE NO DISPONIBLE` | 2 | app | conocida (356) | ver [H-1] |
| `WBD: La serie diaria (2y) termina el 2026-10-05` | 2 | app | conocida (369) | |
| `HTTP Error 401 Invalid Crumb` / `User is unable to access` | 1 + 1 | app | explicada | crumb transitorio (como el 23/10) |
| `Transient yfinance error … 'NoneType' is not iterable` | 1 | app | explicada | el mismo segundo del 401; el reintento anduvo (el refresh terminó a las 19:04:41) |
| `Ollama backend failed … falling back to heuristic` + tb `ReadTimeout` | 1 | app | explicada | timeout de 60 s de Ollama, por diseño; dentro de la corrida del 30/10 que no terminó ([I-1]) |

**Lo que no aparece y debería:** la línea `Classify: scanned …` desde el 23/10 ([I-1]).

## Alcance no mirado (lista)

- **H:** la Lambda misma, la tabla, las métricas y la factura de AWS: no hay credenciales en la
  máquina (es [H-1], y su medición es la 405).
- **I:** el consenso que trae la nube contra el de Yahoo (no hay cómo leer la nube); la muestra de
  noticias contra su fuente (no hay clasificaciones nuevas que contrastar).
- **F:** la pantalla en vivo, renderizada; Home y la cartera real más allá del invariante.
- **D:** mutaciones ejecutadas sobre los guards de la 401 y la 403 (se leyó el test que los cubre).
- **A–E:** el código sin cambios desde la tanda anterior.

## §6. Deuda de método (sólo lo que es (c-metodo) o (d))

1. **[I-1], (d): un trabajo de fondo «corriendo» se verifica por su línea de cierre, no por la de
   arranque.** La tanda del 26/10 vio la cola y la dio por buena porque la corrida había arrancado.
   Para `datos` y `operacion`: por cada job largo de la ventana, ¿escribió su línea final?
2. **[L-1], (d): la tasa de una conocida se contrasta contra lo que prometió el cierre de su tarea,
   también cuando la tanda anterior ya la clasificó.** Copiar la clasificación de la tabla anterior
   es copiar su error.
3. **[A-1], (c-metodo): una decisión que cambia un destino (Pi → AWS) se busca en todo el repo**,
   igual que la frase que una tarea corrigió.
4. **[H-1]: la exclusión de §H tenía un motivo con fecha de vencimiento («hasta que exista») y nadie
   lo re-verificó.** Va en la 405, alcance (5).

## Mapeo hallazgo → tarea

| hallazgo | tarea | verificado en el backlog |
|---|---|---|
| [I-1] classify todo-o-nada; harvest horario apagado; tooltip; `opinion_claude` | **406** | `### 406.` — los cinco impactos y las seis acciones en el enunciado |
| [H-1] AWS sin lector ni alarma; TTL Q3; paso 6; zip; exclusión de la skill | **405** (+ la fecha en la acción manual de la 356) | `### 405.` — alcances (1)–(5) |
| [L-1] barra provisional una vez por ticker en el scan | **407** | `### 407.` |
| [K-1] msgpack y pillow 12.3.0 | **399** (parte de) | línea *«Re-medido el 2026-11-05»* en el enunciado de la 399 |
| [A-1] Anaconda ×3 y la Pi | **408** | `### 408.` — los cuatro lugares en el enunciado |
