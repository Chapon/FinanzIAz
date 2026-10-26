# Auditoría — tanda completa (las 12 áreas), 2026-10-26

READ-ONLY. Skill `auditoria`. Tarea **396**. Kill-criteria **congelado el 2026-10-26 a las 16:55
locales, antes de abrir ningún archivo de código, la DB o el log**, para las 12 áreas juntas. Lo único
leído antes de congelar: el informe de la tanda anterior (`docs/auditoria_tanda_2026-10-23.md`), la
lista de commits desde ella, la cabecera del backlog y el listado de `~/.finanzias/`.

**Ventana.** Desde la tanda anterior (cerrada en `9b01cbb`, hash en `d1dba4e`) hasta hoy.
- **Código: vacía.** Desde `9b01cbb` entró un solo commit, `d1dba4e`, que sólo toca el backlog. Así
  que en las áreas que miran el repo (A, B, C, D, E en su parte de código, K) **no hay nada nuevo que
  mirar**, y eso se dice en vez de re-barrer lo mismo con la misma lente: lo que entra es el
  *alcance no mirado* de la 389 y lo que el estado vivo movió.
- **Estado vivo: tres días.** Log desde `2026-10-23 11:27` (donde cortó el censo de la 389), DB y
  backups desde la copia de las 11:05 del 23/10. Días hábiles en la ventana: el resto del vie 23/10
  y el lun 26/10 (el 24 y 25 son fin de semana).

**Base.** El criterio del 2026-10-23, que heredó el del 20/10, **sin aflojar ninguno**. Cambian (1)
el alcance, por la ventana de código vacía, y (2) el *alcance no mirado* de la 389, que entra
entero: mutaciones ejecutadas sobre la 375 y la 380, `EXPLAIN QUERY PLAN` de las consultas nuevas,
la reexpresión de comparativos en los fundamentals PIT.

**Alcance general.** Ninguna corrida es exhaustiva: cada área declara qué mira y qué no, y el
alcance real se escribe al final **como lista**. «Barrido limpio» va en las dos direcciones: *lo
escrito es falso* y *lo verdadero no está escrito*. **Las seis tareas abiertas de la 389 (390–395)
no se re-publican:** si lo que se ve es una de ellas, se cita; si es más que lo que dice su
enunciado, va como hallazgo.

**Primero, antes de cualquier área:** `check_ci.py --ultimo` con su sha contra `origin/main`, y
`git status`.

---

## A. claims

- **Se mira:** lo que cambió en el mundo y no en el repo: los claims de `CLAUDE.md` y del backlog
  que dependen del estado vivo (cuenta activa, flags, *Acciones manuales pendientes* — ¿alguna ya se
  hizo y sigue listada?, ¿la 381 sigue diciendo lo que pasa?), contra la DB, el `settings.json` y el
  log de hoy.
- **Afuera:** re-leer contra el código lo que la 389 ya contrastó (el código no cambió).
- **Limpio si:** (→) ningún claim vivo contradice la DB/settings/log de hoy; (←) nada que pasó en la
  ventana (una acción manual hecha, una conducta nueva en el log) falta donde el backlog lo declara.

## B. muestra

- **Se mira:** si alguna operación de la ventana movió la muestra (refresh de cohorte, del almacén
  PIT, del universo, de `pit_signals`): fechas de modificación de los stores contra la 389.
- **Afuera:** el código (sin cambios).
- **Limpio si:** (→) ninguna operación movió la muestra, o la que la movió tiene re-verificación;
  (←) ningún store cambió sin que la operación quede registrada.

## C. desvios

- **Se mira:** el valor vivo de cada perilla que gobierna un desvío contra el `settings.json` de hoy
  (¿cambió algo?), y la frecuencia de `barrier_eval` contra los snapshots de la ventana.
- **Afuera:** el código de `deviations()` (sin cambios).
- **Limpio si:** (→) ningún texto de desvío contradice el valor vivo o el registro de la ventana;
  (←) ninguna perilla cambió sin su desvío.

## D. guards

- **Se mira:** primero el **resultado** del CI (último run de `main`, sha contra `origin/main`).
  Después las **mutaciones ejecutadas** que la 389 sólo razonó: la bandera de cierre de la 375 y el
  vigía de la 380, construyendo el caso como **dato** en un script del scratchpad que llama a la
  función del repo, sin editar el repo. Y el estado de los guards de proceso del cierre (que
  `check_backlog_integrity.py` pase hoy).
- **Afuera:** guards ya mutados por la 389.
- **Limpio si:** (→) CI verde y del sha de `main`, y ninguna mutación pasa con el caso contrario;
  (←) ningún punto ciego declarado sin tarea.

## E. estado

- **Se mira:** frescura de `data/parquet/` (cohorte y frames de la watchlist), `data/pit_signals/`,
  `data/fundamentals_pit/`, la cinta intradía de `price_cache`, `harvest_estado.json`, contra sus
  pares y contra la 389.
- **Afuera:** los backups (H).
- **Limpio si:** (→) ningún store quedó atrás de sus pares en la ventana sin que algo lo diga;
  (←) toda operación periódica de la ventana corrió o tiene tarea.

## F. pantalla

- **Se mira:** los números de Home (curva, referencia, costo de operar) y de Paper/Métricas
  recalculados a mano sobre una copia de la DB con los fills y snapshots de la ventana; los
  snapshots de equity de la ventana contra los cierres de su día.
- **Afuera:** estética; no se lanza la app (está abierta: no se toca).
- **Limpio si:** (→) cada número coincide con su recálculo y con su rótulo; (←) ningún vacío o dato
  viejo se pinta como dato.

## G. cuentas

- **Se mira:** cuadre de caja y acciones de las cuentas 2 y 1 al centavo; `max_positions`, caja no
  negativa; dividendos que el motor **debió** acreditar en la ventana (con su propia función);
  cartera real (cantidad, `avg_buy_price` FIFO, fechas) y «Tech» si hubo movimientos.
- **Afuera:** si las decisiones fueron buenas.
- **Limpio si:** (→) todo cuadra al centavo y ningún límite se violó; (←) ningún flujo que el motor
  declara registrar falta en su ledger.

## H. operacion

- **Se mira:** el log de la ventana agrupado por frecuencia; cada job del scheduler por día hábil
  (calendario de la bolsa; log en hora local, DB en UTC) — **en particular el harvest, cuyo
  `harvest_estado.json` es del 23/10 16:54**; backups (que se toman, rotan y restauran: copia en el
  scratchpad, `integrity_check`, alembic); Slack sólo por el log.
- **Afuera:** la infraestructura de la 196/355; disparar jobs o restaurar de verdad.
- **Limpio si:** (→) ninguna firma se repite sin tope y ningún día hábil queda sin scan o sin
  harvest sin que algo lo diga; (←) el último backup restaura a un esquema que `init_db` reconoce.

## I. datos

- **Se mira:** distribución de tipo/polaridad/intensidad de las noticias de la ventana; cobertura del
  consenso por ticker de la watchlist por día hábil. **Alcance no mirado de la 389:** la
  reexpresión de comparativos en el almacén PIT —¿el valor de un año es el del filing original o el
  de un 10-K posterior?— medida sobre los registros crudos del almacén (sin red si no hace falta;
  si hace falta, se dice).
- **Afuera:** si el dato predice algo.
- **Limpio si:** (→) ningún campo degenerado ni hueco de cobertura nuevo sin tarea, y el almacén es
  point-in-time en lo que afirma serlo; (←) ningún ticker de la watchlist llega sin datos sin aviso.

## J. rendimiento

- **Se mira:** duración de los scans de la ventana contra su intervalo; `database is locked`;
  **`EXPLAIN QUERY PLAN`** de las consultas de la referencia de Home, el costo de rotar y la
  equity diaria marcada (alcance no mirado de la 389).
- **Afuera:** la optimización que no cambia conducta.
- **Limpio si:** (→) ningún scan tarda más que su intervalo, sin locks, sin `SCAN TABLE` sobre una
  tabla que crece en un camino caliente; (←) todo job de fondo tiene techo.

## K. dependencias

- **Se mira:** lo instalado en la Anaconda contra lo que vio la 389 (¿cambió algo en la ventana?).
  Lo de los techos es la 391.
- **Afuera:** el código (sin imports nuevos).
- **Limpio si:** (→) lo instalado no cambió, o el cambio está declarado; (←) —.

## L. logs

- **Se mira:** el censo de toda firma WARNING+/traceback de la ventana, normalizada, separada por
  origen (`[proceso: …]`), clasificada conocida (con su tarea y su **tasa** contra la del cierre),
  explicada o desconocida. Las firmas de la 375 (cierre de la instancia, que la 389 no pudo juzgar):
  ¿se ven ahora? `py.warnings`; `congelamientos.log`.
- **Afuera:** el contenido de los INFO.
- **Limpio si:** (→) ninguna firma sin clasificar y ninguna conocida por encima de su tasa;
  (←) ningún camino de fondo traga a `debug` lo que debería verse.

---

**Fase adversarial:** todo HIGH/CRITICAL va al `verificador` con el mandato de **refutarlo**,
atacando primero el **instrumento**. Si no puede correr, se dice.

**Cierre:** la tabla `hallazgo → tarea`, verificada de a una contra `docs/BACKLOG.md`.

---

# Corrida

**2026-10-26, de 16:55 a 17:15 locales**, con la app **abierta** (arrancó a las 16:52, con la PC
encendida a las 16:50). Antes de cualquier área: `check_ci.py --ultimo` → `d1dba4e` **VERDE**, el
sha de `origin/main`; `git status` limpio salvo el registro de la 396 y este informe. El criterio
de arriba no se tocó.

**Instrumentos.** La DB es una copia hecha con la API de backup desde `mode=ro` a las 16:55
(`integrity_check ok`, alembic `0020`). Lo que se calculó con funciones del repo corrió con
`FINANZIAS_DB_PATH` apuntando a esa copia, `FINANZIAS_LOG_FILE` a un archivo del scratchpad y
`FINANZIAS_DISABLE_SLACK=1`: ninguna lectura tocó la DB viva, y el log de producción no tiene
ninguna línea de los procesos de esta corrida (verificado por su marca `[proceso: …]`). Lo único
que esta corrida dejó en disco fuera del scratchpad son los `-shm`/`-wal` vacíos que crea SQLite al
abrir en `mode=ro` el backup de hoy (base en WAL); la rotación los borra junto con el backup
(`database/backup.py:179`).

**Un instrumento mío que dio un número falso y se corrigió antes de publicar:**

- **«11 casos del almacén PIT ven el futuro».** Para medir la reexpresión comparé el valor que
  devuelve `Fundamentos.serie()` contra los valores de **un** tag, y `serie()` elige por período el
  tag más preferido. En los 11, el valor venía de otro tag (o del mismo, de otro filing) presentado
  **antes** de la fecha y coincidía con uno posterior. Recontado mirando el registro que lo
  produjo: **0**.
- **Y una explicación mía que el propio log refutó:** el aviso de `tight_layout` de [L-1] lo di
  primero por *«del cierre de la app»* (las dos líneas del viernes son de las 18:10 y la app murió
  después); a los minutos apareció de nuevo **con la app abierta**. Por eso va como tarea de
  medición y no como *explicada*.

## [I-1] Una respuesta vacía de `get_earnings_dates` borra el perfil de surprise de un ticker por una semana, sin aviso — **BAJA** → tarea **397**

Severidad: BAJA · Confianza: ALTA · Categoría: datos (y guards: un vacío tratado como dato)

- **Ubicación.** `data/news_sources.py:551` (`collect_yfinance_earnings_history`: DataFrame vacío
  ⇒ `return []`, sin log) y `scripts/build_surprise_profiles.py:106-132` (`run_build` escribe lo que
  haya).
- **Evidencia.** El rebuild semanal de hoy escribió `surprise ACN: n=0` (16:53:44); el del 19/10,
  `n=24`. `git diff data/catalyst/surprise_profiles.json`: ACN sale de `profiles` y entra a
  `insufficient_history: {"ACN": 0}`. A las ~17:00, `yf.Ticker("ACN").get_earnings_dates(limit=16)`
  devolvió **25 filas**: el vacío fue transitorio. El único aviso es el INFO final
  *«125/127 usable quarters≥min»*.
- **Cuánto pasa.** En los siete rebuilds del log (11/09 → 26/10), es la **primera** caída a menos
  del mínimo que no fue un deslistado (WBD, 19/10, sí lo fue).
- **Impacto.** El perfil no tiene consumidor vivo (`make_surprise_loader` sólo lo usa
  `scripts/run_catalyst_exit_veto_backtest.py`), así que hoy no mueve nada en la app. Pero el
  archivo está **versionado** y `/ship` commitea su refresh (la 286): el próximo cierre versiona el
  perfil sin ACN, y cualquier corrida del runner en esta semana lo lee así.
- **Verificación.** Se buscó otro consumidor (`grep` de `surprise_loader`, `make_surprise_loader`,
  `surprise_profiles` en `analysis/`, `ui/`, `paper_trading/`, `data/`, `main.py`): no hay.
- **¿Por qué no antes?** (a) NO EXISTÍA la instancia: el mecanismo es de la T-CAT-5a, pero hasta
  hoy ningún rebuild había tenido un vacío transitorio. Es la forma de la 388 en otro endpoint.
- **Acción.** Conservar el perfil anterior (o reintentar) ante un vacío de un ticker que tenía
  perfil, con WARNING que lo nombre; que el INFO final diga qué cambió de usable a corto.

## [L-1] Un `UserWarning` de `tight_layout` que no es el de la 371 aparece una vez por sesión, sin causa conocida — **BAJA** → tarea **398**

Severidad: BAJA · Confianza: ALTA (que aparece) / BAJA (la causa) · Categoría: logs

- **Evidencia.** `py.warnings`, 4 líneas: 23/10 18:10:22 (`main.py:104`, `app.exec()`) y 18:10:34
  (`ui/dashboard_charts.py:286`, `_Sparkline.set_series`); 26/10 16:57:06 y 16:57:18, los mismos
  dos lugares. Texto: *«Tight layout not applied. The bottom and top margins cannot be made large
  enough to accommodate all Axes decorations»*. La 371 era *«not compatible with tight_layout»*,
  por el `hspace` del gráfico de Análisis: es otra firma, y no está en ningún doc ni tarea.
- **Lo que se midió.** Offscreen, `_Sparkline` avisa sólo con el lienzo por debajo de ~58 px de
  alto (20 y 5 px avisan; 58 px con 40 a 300 de ancho, no). No avisa dibujado sin mostrar ni en una
  pestaña oculta. Su `setFixedHeight(58)` impide achicarlo en un layout normal, así que algo en vivo
  lo achica, y no se encontró qué.
- **¿Por qué no antes?** (a) NO EXISTÍA en el log: la captura de `py.warnings` es de la 372
  (19/10), y la tanda del 23/10 contó cero. La primera aparición es del 23/10 a las 18:10, después
  de esa tanda.
- **Acción.** Medir qué achica el lienzo e identificar la figura del aviso de `main.py:104`;
  arreglar o decidir que es benigno, con el motivo verificado.

## Barridos limpios (con lo que se miró)

- **A. claims.** `CLAUDE.md` contra la copia y el `settings.json`: cuenta 2 `auto`,
  `analyze_single`, 10 posiciones, activa; la 1 cerrada; `hmm_enabled` y `stacking_enabled` en
  `False`; `settings.json` sin cambios desde el 13/09. *Acciones manuales pendientes*: WBD sigue en
  la watchlist (1/127 sin precio en cada scan) y no existe `~/.aws/credentials` (la app lo avisa en
  cada arranque), así que la 369 y la 356 siguen bien listadas como abiertas. La 381 dice *«sigue
  esperando»*: `congelamientos.log` no cambia desde el 21/10 12:03, con un arranque más sin volcado.
- **B. muestra.** Ninguna operación movió la muestra: `data/pit_signals/` sigue en el 09/09 (el
  cohorte, por diseño de la 251), `data/fundamentals_pit/` en el 21/10 (la 394), y `data/parquet/`
  se actualiza sólo con los frames que piden los scans.
- **C. desvíos.** Ninguna perilla cambió (settings del 13/09). La cobertura de scan, re-medida con
  `scripts/medir_cobertura_de_scan_t265.py` sobre la copia: 38 de 82 días hábiles sin scan en sesión
  (01/07 → 26/10), contra los 34 de 66 que el texto de `barrier_eval` declara **con fecha** (02/10):
  el texto no es falso, es un número fechado (y los feriados de 2027 son la 395).
- **D. guards.** CI **verde** en `d1dba4e`, el sha de `origin/main`. **Mutaciones ejecutadas** que la
  389 sólo razonó: la bandera de cierre de la 375, en un proceso aparte con `QApplication`
  offscreen: cierre normal (`shutdown()`) → 0 avisos con la variable vacía, `0` o `1`; sin pasar por
  el cierre → 1 aviso con vacía o `0`, y 0 con `1` (la suite, por diseño). El vigía de la 380:
  `tests/test_vigia_interfaz_t304.py` 8 de 8, con su control de falso positivo
  (`test_CONTROL_sin_traba_no_vuelca_nada`). `check_backlog_integrity.py` OK.
- **E. estado.** La cinta intradía de `price_cache` se archivó sola al arrancar (19.626 filas a
  Parquet). `harvest_estado.json` se reescribió hoy, no degradado. El backup diario de hoy se tomó,
  rotó (7 guardados, uno suelto de más de 30 días borrado) y abre: `integrity_check ok`, alembic
  `0020`. `historical_reaction.json` es del 11/09: lo construye sólo un script manual y no lo lee
  la app (ya escrito en la 255 y en el [A-3] de la tanda del 02/10).
- **F. pantalla.** El último snapshot de cada día contra los cierres de ese día, con las posiciones
  reconstruidas desde los fills: 23/10 −0,008%, 26/10 −0,012%. El costo de operar de la cuenta 2:
  **$591,05 en 197 fills**, idéntico a la suma a mano de comisión más slippage (era $565,77 el
  23/10). La referencia: 126 con WBD afuera (la 393).
- **G. cuentas.** Cuentas 1 y 2 **al centavo** en caja (4.673,98 y 4.041,00) y en acciones; 7
  fills de la cuenta 2 en la ventana; 9 posiciones de 10; caja mínima de la ventana 585,40.
  Dividendos con `creditos_pendientes` sobre la copia desde `PISO_DIVIDENDOS`: **0 pendientes**;
  ninguna posición sin calendario. La venta de BKNG a $156,81 no es un error: se compró a $159,57
  el 02/10, ya después de su split. Cartera real: sin transacciones nuevas desde el 07/10.
- **H. operación.** Viernes 23/10: harvest horario de 11:47 a 16:54, todos 127/127; scans cada 15
  min hasta las 17:05. **La app murió con el apagado de Windows** (evento 1074 a las 18:57; ningún
  `APPCRASH` de `python.exe`; los del lunes son de `LightingService.exe` y Nahimic). Lunes 26/10: la
  PC arrancó a las 16:50 y la sesión pasó casi entera sin app (**un** snapshot en sesión, 19:54Z):
  lo miden la 245 y el desvío `barrier_eval`, no es nuevo. Al arrancar: backup, rebuild de surprise
  (ver [I-1]), harvest diario 127/127 con el consenso del día (+1.270) y la clasificación corriendo.
  Slack: sin errores en el log.
- **I. datos.** Noticias de la ventana: 906, **todas sin clasificar todavía** (la clasificación
  diaria arrancó a las 16:52, como en la 389); por fuente, `yfinance:search` 476, Finnhub 430.
  Consenso: los 127 de la watchlist el 21, 22 y 23/10, y el del 26/10 entrando con el harvest de
  hoy. **Almacén PIT, la reexpresión** (alcance no mirado de la 389): de 12.111 períodos de
  ganancia neta, ventas y EPS, 1.089 (9,0%) tienen un valor distinto en un filing posterior; en las
  1.089, `serie()` el día siguiente al primer filing devuelve un valor presentado antes de esa fecha
  (ver *instrumentos*). Lo de ACN va en [I-1].
- **J. rendimiento.** Scans de 3,6 a 153 s contra 15 min; ningún `database is locked`. **`EXPLAIN
  QUERY PLAN`** de lo que emiten `costo_de_rotar_de_cuenta`, `equity_diaria_marcada` y
  `referencia_de_cuenta` (capturado con un listener del engine sobre la copia): las cuatro consultas
  usan índice (`ix_paper_orders_account_filled`, `ix_paper_equity_account_at`,
  `ix_paper_watchlist_account`, la PK). En caliente, `equity_diaria_marcada` 0,006 s; la referencia
  ~1,5 s (la 392, que lee frames, no la DB).
- **K. dependencias.** Nada en `site-packages` de la Anaconda modificado después del 23/10. Los
  techos son la 391.
- **L. logs.** Ventana `2026-10-23 11:26:04` → `2026-10-26 17:05:44`: **112 WARNING+ en 7 firmas y
  1 traceback** (encadenado, tres bloques), todas de la app (ninguna con `[proceso: …]`). Todas
  clasificadas:

| Firma (normalizada) | Líneas | Origen | Clase | Motivo |
|---|---|---|---|---|
| `cachean la barra de la sesion de HOY` (de 1, 10 y 121 tickers) | 69 + 2 | app | conocida (112, 243) | Una línea por lote, por diseño. |
| `Scan … 1/127 tickers sin precio` | 25 | app | conocida (369) | WBD; acción manual pendiente. |
| `XGBoost TK: unstable model` | 9 | app | conocida (364), con su tasa | 1 el 23/10 a las 11:26 (la cola del scan que ya contó la 389) y 8 el 26/10 en el primer scan después de arrancar, que la 364 manda re-entrenar: como en la 389 (9 a 12 por arranque). |
| `Tight layout not applied … margins` | 4 | app | **desconocida** → [L-1] | |
| `collect_sec_8k failed for GOOGL (falla de red…)` + 1 tb | 1 | app | conocida (289, 353) | Un traceback por fuente. |
| `Nube — FUENTE NO DISPONIBLE` | 1 | app | conocida (356) | Una por arranque. |
| `WBD: la serie diaria (2y) termina …` | 1 | app | conocida (369) | |

  **La 375, juzgable por primera vez con un cierre real:** no, tampoco. El viernes la app no se
  cerró: la apagó Windows, sin pasar por el intérprete (ni la línea de cierre ni el aviso de
  *«sin pasar por el cierre»*, que es lo esperable con un proceso terminado desde afuera). Lo que sí
  se verificó es la conducta, por mutación (D). **(←)** El camino de fondo que traga sin log es el
  de [I-1]: `collect_yfinance_earnings_history` no escribe nada ante un vacío.

## Fase adversarial

**No hubo HIGH ni CRITICAL**, así que el `verificador` no corrió (regla de la skill). La refutación
fue **propia y no independiente**, y tumbó dos cosas antes de publicar: los 11 casos de *«el almacén
PIT ve el futuro»* (instrumento) y la explicación *«del cierre de la app»* de [L-1] (el log de hoy).
[I-1] se atacó por el lado del impacto —buscando un consumidor vivo del perfil—, y el impacto quedó
más chico: de *«el motor usa un perfil vacío»* a *«un archivo versionado y un runner»*.

## Alcance no mirado (lista)

- **F:** la pantalla en vivo (la app no se tocó); la tarjeta de valuación renderizada.
- **H:** Slack, sólo por el log; la infraestructura de la 196/355.
- **I:** las noticias de la ventana **clasificadas** (la clasificación estaba corriendo); la muestra
  contra EDGAR bajando los filings (la reexpresión se midió sobre el almacén, no contra la fuente).
- **L:** la causa de [L-1] (va como tarea).
- **A–E, K:** el código, porque no cambió desde la 389.

## Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| [I-1] | 397 |
| [L-1] | 398 |

## Deuda de la skill

Ninguna etiqueta (c-metodo) ni (d) en esta corrida. Una observación, no una deuda: la mitad de los
números de un área viva (I, L) se mueven con jobs que están corriendo durante la auditoría (la
clasificación, el rebuild); cuando un job de la ventana está en curso, el informe lo dice y no da
su resultado por mirado.
