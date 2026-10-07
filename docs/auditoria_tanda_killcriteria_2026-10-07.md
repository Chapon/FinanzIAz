# Kill-criteria congelados — tanda 2026-10-07 (12 áreas), antes de abrir cualquier archivo

Tarea **335**. Pedido de Chapa: *«luego de terminar correr todas las auditorías»*. Congelado el
2026-10-07, antes de abrir el primer archivo de la corrida.

Ventana común: lo que cambió desde la tanda anterior (306, `557ae6a`) —tareas **307 a 334**— más el
estado vivo (DB copiada desde `mode=ro`, log de producción, `settings.json`, el CI de `main`).
Ninguna área se declara exhaustiva: el alcance real se escribe como LISTA en el informe.

**Conflicto declarado:** las tareas 324–334 las hizo la misma sesión que corre esta tanda. Por eso
todo hallazgo HIGH/CRITICAL pasa por el `verificador`, y las áreas que tocan esas tareas (F, G) se
contrastan contra la DB viva calculando a mano, no releyendo el código propio.

## A. claims
- Mira: `CLAUDE.md`, header y *En curso* de `BACKLOG.md`, las skills de `.claude/skills/` y los
  comandos de `.claude/commands/` (listados), `ARCHITECTURE.md`, `DB_SCHEMA.md` y
  `SETTINGS_REFERENCE.md` donde citen lo que tocaron las 307–334.
- Busca: (→) afirmación escrita que el código/DB contradice hoy; (←) la frase original de una
  corrección cerrada desde la 306 que sobreviva en otro archivo (`git grep` en todo el repo, en
  particular «sin ajustar por splits», «capital invertido neto», «no es valor de mercado»); (←) lo
  verdadero no escrito: módulos/tablas/scripts nuevos de las 320–332 (`database/lotes.py`,
  `ui/portfolio_detalle.py`, `claude_opinions`, los scripts nuevos) que un doc de referencia
  debería nombrar según la granularidad que promete.
- Afuera: docs de análisis fechados, salvo que algo vivo los cite.
- Limpio: ningún claim vivo contradice el código/DB, ninguna frase corregida sobrevive fuera de
  donde se la cita como historia, y lo nuevo está donde su doc promete.

## B. muestra
- Mira: chequeos `len()`/contadores que deciden «completo / es la muestra» en el código nuevo o
  tocado desde la 306 (`database/lotes.py`, `database/cartera_real.py`, `data/csv_importer.py`,
  `scripts/check_ci.py`, el pre-registro de la 321).
- Busca: (→) chequeo por cantidad que pasa con la ventana corrida o con datos parciales; (←)
  operación que movió la muestra desde 2026-10-05 sin re-verificar lo que invalidó (el reemplazo de
  «Mis Acciones» de la 324 movió la cartera real que mide Home y la 321).
- Afuera: tests.
- Limpio: todo chequeo de completitud compara identidad/fechas, y lo que la 324 movió está
  re-verificado.

## C. desvios
- Mira: `deviations_keyed()` contra el `settings.json` vivo, la cuenta 2 y `harness_config`.
- Busca: (→) texto de desvío que contradice el valor vivo de sus perillas o un número sin
  marco/fecha; (←) diferencia harness↔engine sin clave — en particular dividendos y splits en el
  motor paper (la 333 recién abierta) y el desvío `spinoffs` de la 311.
- Afuera: perillas de UI.
- Limpio: cada perilla viva de engine tiene clave o espejo, cada texto concuerda con el valor vivo,
  y toda diferencia de tratamiento de eventos corporativos está declarada o tiene tarea.

## D. guards
- Mira: **primero el resultado** (`check_ci.py --ultimo` contra `origin/main`, y los rojos de
  `main` desde la 306), después `scripts/check_*.py` tocados (`check_ci.py`, 307 y 318),
  `.github/workflows/ci.yml` (318 y 330) y los guards de tests nuevos de las 307–334.
- Busca: (→) guard que no puede contener el caso que describe (mutación en el sentido del falso
  positivo); (←) CI que corre menos que el done, o un rojo de `main` cerrado sin causa.
- Afuera: guards ya mutados en tandas previas sin cambios posteriores.
- Limpio: el CI de `main` en verde, todo rojo desde la 306 con causa nombrada, los guards nuevos se
  ponen rojos con el caso contrario.

## E. estado
- Mira: `data/parquet` (cierres de la cartera real), `dividend_calendar_cache`,
  `company_info_cache`, `price_cache`/cinta, artefactos de cohorte, `claude_opinions` (320) y los
  archivos de `~/.finanzias/`.
- Busca: (→) store sin dueño que quedó atrás de sus pares o del que depende una pantalla nueva
  (Home 332, desplegable 325); (←) operación manual periódica sin disparador, o algo que crece sin
  techo.
- Afuera: backups (van a operacion).
- Limpio: cada store tiene regenerador y está alineado con sus pares; nada crece sin techo.

## F. pantalla
- Mira: Home (332: valor y ganancia), Portfolio (325: desplegable, cerradas, realizada) y la
  opinión de Claude en Análisis (320), contra la DB viva calculando a mano.
- Busca: (→) número o curva que no es lo que el rótulo dice; (←) vacío o dato faltante pintado
  como dato.
- Afuera: estética, layout.
- Limpio: cada número trazado coincide con el cálculo a mano y lo que falta se rotula.

## G. cuentas
- Mira: cuadre de caja y acciones de las cuentas 1 y 2; reglas `max_positions`/caja/cuenta
  cerrada; la cartera real reconstruida (324): `positions` contra el FIFO de sus `transactions`,
  y cada fecha de transacción contra el rango de precio de ese día (la regla de la 308).
- Busca: (→) descuadre; (←) violación de límite desde 2026-10-05, o una fecha/precio imposible.
- Afuera: si las decisiones fueron buenas.
- Limpio: cuadre al centavo, ningún límite violado, cada transacción real con un precio posible
  para su fecha (con el split de NVDA ajustado).

## H. operacion
- Mira: log de producción desde 2026-10-05, snapshots por día hábil, `backups/` y su rotación,
  el backup de la 324, Slack.
- Busca: (→) retry sin tope o aviso que no escala; (←) día hábil sin scan o job que no corrió.
- Afuera: la infraestructura de la 196.
- Limpio: cada día hábil con scan, ningún retry sin tope, backups tomados y rotados.

## I. datos
- Mira: el CSV de Yahoo de Chapa contra la DB (324), `dividend_calendar_cache` (ajuste por
  splits, la 331), `company_info_cache` (329), y una muestra de `claude_opinions`.
- Busca: (→) dato que dice otra cosa que su fuente; (←) cobertura faltante sin aviso.
- Afuera: si el dato predice algo.
- Limpio: la muestra concuerda con la fuente y los huecos avisan.

## J. rendimiento
- Mira: del log, duración de scans y `database is locked` desde 2026-10-05; `EXPLAIN QUERY PLAN`
  de las consultas nuevas en caminos calientes (Home `resumen_home`/`ganancias_diarias`,
  `_armar_libros` de Portfolio, `calendario_del_cache`).
- Busca: (→) consulta nueva con `SCAN TABLE` sobre una tabla que crece, o un cálculo cuadrático
  en el render; (←) job de fondo sin techo de tiempo.
- Afuera: optimización que no cambia conducta.
- Limpio: nada nuevo bloquea ni escala mal.

## K. dependencias
- Mira: imports de terceros nuevos de las 307–334 (la 320 lanza `claude` como subproceso) contra
  `requirements*.txt` y la Anaconda.
- Busca: (→) import no declarado; (←) dependencia externa no-Python de la que la app depende sin
  que se diga (el CLI de Claude Code).
- Afuera: actualizar versiones.
- Limpio: todo lo importado está declarado, y lo externo está documentado.

## L. logs
- Mira: censo de firmas WARNING+/traceback desde 2026-10-05 en `~/.finanzias/finanzias.log*`,
  separadas por origen (`[proceso: …]`).
- Busca: (→) firma desconocida; (←) firma conocida que sigue apareciendo después del cierre de su
  tarea (323, 322, 330).
- Afuera: el contenido de los INFO.
- Limpio: ninguna firma sin clasificar, ninguna conocida reaparece tras su cierre.
