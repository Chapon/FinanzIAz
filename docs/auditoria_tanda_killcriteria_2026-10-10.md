# Kill-criteria congelados — tanda 2026-10-10 (12 áreas), antes de abrir cualquier archivo

Tarea **349**. Pedido de Chapa: *«correr todas las auditorías»*. Congelado el 2026-10-10, antes de
abrir el primer archivo de la corrida.

Ventana común: lo que cambió desde la tanda anterior (335, `f281d7b`) —tareas **336 a 348**— más el
estado vivo (DB copiada con la API de backup desde `mode=ro`, log de producción, `settings.json`, el
CI de `main`) y la operación del 2026-10-09 (el CSV de Yahoo reimportado con
`reemplazar_cartera_csv.py`: META y PYPL nuevas). Ninguna área se declara exhaustiva: el alcance real
se escribe como LISTA en el informe.

**Conflicto declarado:** las tareas 336–348 las hizo la misma sesión (o la anterior inmediata) que
corre esta tanda; la 338, 345, 347 y 348, en esta misma conversación. Por eso todo hallazgo
HIGH/CRITICAL pasa por el `verificador`, y las áreas que tocan esas tareas (F, G, I) se contrastan
contra la DB viva calculando a mano, no releyendo el código propio.

## A. claims
- Mira: `CLAUDE.md`, header y *En curso* de `BACKLOG.md` (recién reescritos por la 338), las skills
  de `.claude/skills/` y los comandos de `.claude/commands/` (listados en el informe),
  `ARCHITECTURE.md`, `DB_SCHEMA.md`, `SETTINGS_REFERENCE.md` donde citen lo que tocaron las 336–348,
  y las memorias que el proyecto cita como vigentes.
- Busca: (→) afirmación escrita que el código/DB/entorno contradice hoy —en particular lo que dicen
  del `.venv`, del lock, de `platformdirs`, `lxml` y `pyarrow` después de las 346–348, y del flujo de
  cierre después de la 338—; (←) la frase original de una corrección cerrada desde la 335 que
  sobreviva en otro archivo (`git grep` en todo el repo: «movida a *En curso*», «le faltan
  `platformdirs`», «sin parser HTML», «213 ítems», «un solo frame»); (←) lo verdadero no escrito: el
  script nuevo `limpiar_barra_rellenada.py` (344), el selector de Home (334), el eje 6 del guard
  (338) donde su doc promete nombrarlos; (↔) los procesos declarados en varios lugares (cierre de
  tarea, done) comparados lugar contra lugar.
- Afuera: docs de análisis fechados, salvo que algo vivo los cite.
- Limpio: ningún claim vivo contradice el código/DB/entorno, ninguna frase corregida sobrevive fuera
  de donde se cita como historia, lo nuevo está donde su doc promete, y los lugares que declaran el
  mismo proceso dicen lo mismo.

## B. muestra
- Mira: chequeos `len()`/contadores que deciden «completo / es la muestra» en el código nuevo o
  tocado desde la 335 (`database/cartera_real.py` de la 336, `paper_trading/dividends.py` de la 333,
  `data/quality.py` de la 344, `analysis/ml_signals.py` de la 340, `scripts/check_backlog_integrity.py`
  de la 338).
- Busca: (→) chequeo por cantidad que pasa con la ventana corrida o con datos parciales; (←)
  operación que movió la muestra desde el 2026-10-07 sin re-verificar lo que invalidó (la
  reimportación del CSV del 09/10, el `limpiar_barra_rellenada` de la 344, el cache `5y` de TEAM/EMBJ
  de la 343, la limpieza de las opiniones de la 337 para la muestra de la 321).
- Afuera: tests.
- Limpio: todo chequeo de completitud compara identidad/fechas, y lo que esas operaciones movieron
  está re-verificado o tiene tarea.

## C. desvios
- Mira: `deviations_keyed()` contra el `settings.json` vivo, la cuenta 2 y `harness_config`.
- Busca: (→) texto de desvío que contradice el valor vivo de sus perillas, o un número sin
  marco/fecha; (←) diferencia harness↔engine sin clave — en particular el cobro de dividendos con
  splits/spin-offs (333) y el descarte de la barra final sin Close (344), que cambian lo que el motor
  ve frente al harness.
- Afuera: perillas de UI.
- Limpio: cada perilla viva de engine tiene clave o espejo, cada texto concuerda con el valor vivo, y
  las conductas nuevas de la 333 y la 344 están declaradas, son idénticas en los dos lados, o tienen
  tarea.

## D. guards
- Mira: **primero el resultado** (`check_ci.py --ultimo` contra `origin/main`, y los rojos de `main`
  desde la 335 con su causa), después `scripts/check_backlog_integrity.py` (eje 6, 338),
  `.github/workflows/ci.yml` (qué instala: `requirements.txt` sin lock), y los guards de tests nuevos
  de las 336–348.
- Busca: (→) guard que no puede contener el caso que describe (mutación en el sentido del falso
  positivo); (←) CI que corre algo distinto del entorno donde corre la app, de modo que un rojo o un
  verde no signifique lo mismo (la 348 lo mostró con pyarrow); (←) skip que tapa un rojo.
- Afuera: guards ya mutados en tandas previas sin cambios posteriores.
- Limpio: CI de `main` en verde, todo rojo desde la 335 con causa nombrada, los guards nuevos se
  ponen rojos con el caso contrario, y ninguna dependencia sin techo puede cambiar el CI sin que nada
  lo diga —o eso está declarado como decisión—.

## E. estado
- Mira: `data/parquet` (frames `1y`/`2y`/`5y` de la cartera real y del universo, barras finales sin
  Close de la 344), `price_cache`/cinta, `dividend_calendar_cache`, `company_info_cache`,
  `claude_opinions`, el cache en memoria de XGB (340), y `~/.finanzias/`.
- Busca: (→) store que quedó atrás de sus pares o del que depende Home/Portfolio; barras rellenadas
  que la 344 debía limpiar y siguen ahí; (←) operación manual periódica sin disparador (la acción
  manual de la 344, el refresh de frames largos de la 343), o algo que crece sin techo.
- Afuera: backups (van a operacion).
- Limpio: cada store tiene regenerador y está alineado con sus pares; no quedan barras rellenadas;
  nada crece sin techo.

## F. pantalla
- Mira: Home (336 cierres unidos, 334 selector de tres vistas: valor / ganancia / invertido) y
  Portfolio después del CSV del 09/10, el panel de dividendos paper (333), y la opinión de Claude en
  Análisis (337), contra la DB viva calculando a mano.
- Busca: (→) número o curva que no es lo que el rótulo dice (en particular: el último punto de la
  curva contra el KPI, y «invertido» contra el costo abierto FIFO); (←) vacío o dato faltante pintado
  como dato.
- Afuera: estética, layout.
- Limpio: cada número trazado coincide con el cálculo a mano y lo que falta se rotula.

## G. cuentas
- Mira: cuadre de caja y acciones de las cuentas 1 y 2 (con el fill de LRCX de la 345 declarado);
  reglas `max_positions`/caja/cuenta cerrada desde el 2026-10-07; los créditos de dividendos después
  de la 333; la cartera real después del CSV del 09/10: `positions` contra el FIFO de sus
  `transactions`, y cada fecha contra el rango de precio de ese día (regla de la 308).
- Busca: (→) descuadre; (←) violación de límite, un dividendo cobrado con las acciones en la escala
  equivocada, o una fecha/precio imposible.
- Afuera: si las decisiones fueron buenas.
- Limpio: cuadre al centavo (salvo lo declarado), ningún límite violado, dividendos en escala, cada
  transacción real con precio posible para su fecha.

## H. operacion
- Mira: log de producción desde 2026-10-07, snapshots por día hábil, `backups/` y su rotación, los
  backups de la 343/344/CSV, Slack.
- Busca: (→) retry sin tope o aviso que no escala; (←) día hábil sin scan o job que no corrió (el
  09/10 sin scans en la rueda ya se vio: se mide si es un hueco de la app cerrada o de otra cosa).
- Afuera: la infraestructura de la 196.
- Limpio: cada día hábil con scan o con el motivo nombrado, ningún retry sin tope, backups tomados y
  rotados.

## I. datos
- Mira: el CSV del 09/10 contra la DB, las opiniones de Claude tras la 337 (ticker limpio), los
  frames `5y` de TEAM/EMBJ (343) contra otra fuente de precio del mismo día, y la barra final de los
  frames del cache después de la 344.
- Busca: (→) dato que dice otra cosa que su fuente; (←) cobertura faltante sin aviso.
- Afuera: si el dato predice algo.
- Limpio: la muestra concuerda con la fuente y los huecos avisan.

## J. rendimiento
- Mira: del log, duración de scans y `database is locked` desde 2026-10-07 (el scan del 09/10 tardó
  274 s con 126 re-entrenamientos); el costo de `valor_diario` con los frames unidos (336) en el
  render de Home; `EXPLAIN QUERY PLAN` de lo nuevo en caminos calientes.
- Busca: (→) scan que tarda más que su intervalo, consulta nueva con `SCAN TABLE` sobre tabla que
  crece, cálculo cuadrático en el render; (←) job de fondo sin techo de tiempo.
- Afuera: optimización que no cambia conducta.
- Limpio: ningún scan excede su intervalo sin que se sepa por qué, nada nuevo bloquea ni escala mal.

## K. dependencias
- Mira: `requirements.txt`, `requirements-dev.txt`, `requirements.lock` contra Anaconda, `.venv` y el
  CI después de las 346–348; los pines (motivo vigente) y las dependencias sin techo.
- Busca: (→) import no declarado, versión instalada fuera de lo declarado; (←) dependencia sin techo
  cuya próxima versión mayor rompe con los pines existentes (la forma de la 348: pyarrow 26 + numpy<2).
- Afuera: actualizar versiones.
- Limpio: todo lo importado está declarado, lo instalado cumple lo declarado en los tres entornos, y
  ninguna dependencia sin techo choca hoy con un pin.

## L. logs
- Mira: censo de firmas WARNING+/traceback desde 2026-10-07 en `~/.finanzias/finanzias.log*`,
  separadas por origen (`[proceso: …]`).
- Busca: (→) firma desconocida; (←) firma conocida que sigue apareciendo después del cierre de su
  tarea (336, 337, 340 parte 1, 344), clasificada **con su tasa**.
- Afuera: el contenido de los INFO.
- Limpio: ninguna firma sin clasificar, ninguna conocida reaparece tras su cierre ni con tasa mayor
  que la de su cierre.
