# Kill-criteria congelados — tanda 2026-10-05 (12 áreas), antes de abrir cualquier archivo

Tarea **306**. Pedido de Chapa: *«correr todas las auditorías nuevamente»*. Congelado el
2026-10-05, antes de abrir el primer archivo de la corrida.

Ventana común: lo que cambió desde la tanda anterior (299, `d9f2e00`) —tareas **300, 301, 302,
298, 304, 305, 303** y el refresh de `surprise_profiles.json` (`2f09a0a`)— más el estado vivo
(DB copiada con la API de backup desde `mode=ro`, log de producción, `settings.json`, el CI de
`main`). Ninguna área se declara exhaustiva: el alcance real se escribe como LISTA en el informe.

## A. claims
- Mira: `CLAUDE.md` (la regla 7 nueva incluida), header y *Hecho reciente* de `BACKLOG.md`, las
  skills de `.claude/skills/` y los comandos de `.claude/commands/` (todos los que haya en disco,
  listados), `ARCHITECTURE.md`, `DB_SCHEMA.md` y `SETTINGS_REFERENCE.md` donde citen estado vivo o
  lo que tocaron las 300–305.
- Busca: (→) afirmación escrita que el código/DB contradice hoy; (←) la frase original de una
  corrección cerrada desde la 299 que sobreviva en otro archivo (`git grep` en todo el repo), y un
  proceso declarado en dos lugares (cierre de tarea, done, arranque de sesión) que se contradiga
  lugar contra lugar; (←) lo verdadero no escrito: un módulo/tabla/script nuevo de las 303–305 que
  un doc de referencia debería nombrar según la granularidad que promete y no nombra.
- Afuera: docs de análisis fechados (son fotos), salvo que algo vivo los cite.
- Limpio: ningún claim vivo contradice el código/DB, ninguna frase corregida sobrevive, los
  procesos declarados en varios lugares coinciden, y lo nuevo está donde su doc promete.

## B. muestra
- Mira: chequeos `len()`/contadores que deciden «completo / es la muestra» en el código nuevo o
  tocado desde la 299 (`database/cartera_real.py` de la 305, `paper_trading/spinoffs.py`,
  `scripts/check_ci.py`, `ui/vigia_interfaz.py`).
- Busca: (→) chequeo por cantidad que pasa con la ventana corrida (p. ej. «la serie termina donde
  la tienen todos» de la 305); (←) operación que movió la muestra desde 2026-10-04 sin
  re-verificación de lo que invalidó.
- Afuera: tests.
- Limpio: todo chequeo de completitud compara identidad/fechas, y no hubo operación de muestra sin
  re-verificar.

## C. desvios
- Mira: `deviations_keyed()` contra el `settings.json` vivo, la cuenta 2 y `harness_config`.
- Busca: (→) texto de desvío que contradice el valor vivo de sus perillas o un número sin marco/
  fecha; (←) diferencia harness↔engine sin clave — en particular el ajuste de spin-off a mano (303):
  el harness reinvierte (`auto_adjust`) y la cuenta acredita caja.
- Afuera: perillas de UI.
- Limpio: cada perilla viva de engine tiene clave o espejo, cada texto concuerda con el valor vivo,
  y toda diferencia de tratamiento de eventos corporativos está declarada o no puede ocurrir hoy.

## D. guards
- Mira: **primero el resultado** (`check_ci.py --ultimo` y los runs recientes de `main`), después
  `scripts/check_*.py` nuevos o tocados (`check_ci.py`), los guards de tests nuevos desde la 299
  (300, 302, 303, 304, 305) y `.github/workflows/`.
- Busca: (→) guard que no puede contener el caso que describe (mutación en el sentido del falso
  positivo, sobre `check_ci.py` en particular: ¿puede decir VERDE de un commit que no es el
  pusheado, o de un run de otra rama?); (←) CI que corre menos que el done.
- Afuera: guards ya mutados en tandas previas sin cambios posteriores.
- Limpio: el CI de `main` en verde, los guards nuevos se ponen rojos con el caso contrario, y el CI
  corre los cuatro comandos.

## E. estado
- Mira: `data/parquet`, `data/pit_signals`, `earnings_cache`, universo, `price_cache`/cinta,
  artefactos de cohorte, `surprise_profiles.json`, y el archivo nuevo de la 304
  (`~/.finanzias/congelamientos.log`).
- Busca: (→) store sin dueño que quedó atrás de sus pares; (←) operación manual periódica sin
  disparador, o un archivo que crece sin rotación.
- Afuera: backups (van a operacion).
- Limpio: cada store tiene regenerador y está alineado con sus pares a la fecha; nada crece sin techo.

## F. pantalla
- Mira: la curva nueva de Home (305) contra la DB y el cache, y la equity de Paper de la cuenta 2.
- Busca: (→) número o curva que no es lo que el rótulo dice; (←) vacío o ticker faltante pintado
  como dato.
- Afuera: estética, layout.
- Limpio: cada número trazado coincide con el cálculo a mano y lo que falta se rotula.

## G. cuentas
- Mira: cuadre de caja y acciones de cuentas 1 y 2 (independiente de `cuadre.py`), reglas
  `max_positions`/caja/cuenta cerrada, la cartera real, y el esquema vivo (¿la 0017 aplicada?).
- Busca: (→) descuadre; (←) violación de límite en órdenes/snapshots desde 2026-10-04.
- Afuera: si las decisiones fueron buenas.
- Limpio: cuadre al centavo y ningún límite violado.

## H. operacion
- Mira: log de producción desde 2026-10-04, snapshots por día hábil, `backups/` y su rotación, el
  rebuild semanal de surprise (10-05), el vigía de la 304 en vivo.
- Busca: (→) job que falla, se repite o no corre; (←) aviso que debería salir y no sale.
- Afuera: infra de la 196; el canal de Slack (sin acceso desde la sesión).
- Limpio: cada día hábil con app abierta tiene scan, el backup diario existe y rota, nada se repite
  sin tope.

## I. datos
- Mira: distribución de las clasificaciones desde la 302 (rótulo vs nivel), cobertura de consenso
  y facts del universo vivo.
- Busca: (→) campo degenerado o hueco de cobertura sin aviso; (←) inconsistencia entre fuentes o
  entre campos de la misma fila.
- Afuera: poder predictivo (la 290).
- Limpio: sin campo degenerado nuevo, ningún rótulo contra el signo del nivel después de la 302, y
  ningún ticker vivo sin cobertura no avisada.

## J. rendimiento
- Mira: duración de scans contra el intervalo, `database is locked`, el costo de la curva de Home
  (305) al abrir, el `QTimer` del vigía (304).
- Busca: (→) scan > intervalo, lock, o un cálculo en el hilo de la GUI que tarde lo bastante para
  que el propio vigía lo registre; (←) job de fondo sin techo de tiempo.
- Afuera: optimización que no cambia conducta.
- Limpio: ningún scan excede su intervalo, ningún lock nuevo, nada en la GUI cerca del umbral del vigía.

## K. dependencias
- Mira: imports de terceros de los archivos nuevos o tocados desde la 299 contra `requirements*`, y
  lo que usa `check_ci.py` (red, `urllib`/`requests`).
- Busca: (→) import no declarado; (←) declarado distinto de lo instalado.
- Afuera: actualizar versiones; la divergencia lock↔Anaconda que decidió la 284.
- Limpio: todo import declarado.

## L. logs
- Mira: censo de firmas WARNING+ y tracebacks del log de producción desde el cierre de la tanda
  anterior (2026-10-04), separadas por origen (`[proceso: …]`).
- Busca: (→) firma desconocida; (←) firma conocida que sigue después del cierre de su tarea.
- Afuera: contenido de INFO.
- Limpio: toda firma clasificada y ninguna conocida post-cierre.
