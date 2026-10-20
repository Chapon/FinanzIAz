# Auditoría — tanda completa (las 12 áreas), 2026-10-20

READ-ONLY. Skill `auditoria`. Kill-criteria **congelado el 2026-10-20, antes de abrir ningún
archivo**, para las 12 áreas juntas.

> **Estado: PENDIENTE de correr (tarea 373).** Chapa aprobó este kill-criteria el 2026-10-20 y la
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
