# Kill-criteria congelados — tanda 2026-10-04 (12 áreas), antes de abrir cualquier archivo

Ventana común: lo que cambió desde la tanda anterior (2026-10-03) + re-chequeo de los claims
que esa tanda dejó corregidos. Ninguna área se declara exhaustiva: el alcance real se escribe
como LISTA en cada informe.

## A. claims
- Mira: CLAUDE.md, header y "Hecho reciente" de BACKLOG.md, skills de .claude/skills/ (todas las
  que haya en disco, listadas), DB_SCHEMA/SETTINGS_REFERENCE donde citen estado vivo.
- Busca: (→) afirmación escrita que el código/DB contradice hoy; (←) frase original de una
  corrección cerrada en las últimas tandas que sobreviva en otro archivo (grep en todo el repo).
- Afuera: docs de análisis fechados (son fotos, no claims vivos), salvo que algo vivo los cite.
- Limpio: ningún claim vivo contradice el código/DB, y ninguna frase corregida sobrevive en el repo.

## B. muestra
- Mira: chequeos `len()`/contadores que deciden "completo / es la muestra" en scripts/ y analysis/.
- Busca: (→) chequeo por cantidad que pasa con la ventana corrida; (←) operación que movió la muestra
  desde 2026-10-03 sin re-verificación de lo que invalidó.
- Afuera: tests.
- Limpio: todo chequeo de completitud compara identidad/fechas, y no hubo operación de muestra sin re-verificar.

## C. desvios
- Mira: deviations_keyed() vs settings vivo + cuenta 2 + harness_config.
- Busca: (→) texto de desvío que contradice el valor vivo de sus perillas; (←) diferencia harness↔engine sin clave.
- Afuera: perillas de UI.
- Limpio: cada perilla viva de engine tiene clave o espejo, y cada texto concuerda con el valor vivo.

## D. guards
- Mira: scripts/check_*.py, guards de tests nuevos desde 2026-10-03, .github/workflows/.
- Busca: (→) guard que no puede contener el caso que describe (mutación en sentido del falso positivo);
  (←) CI que corre menos que el done de CLAUDE.md.
- Afuera: guards ya mutados en tandas previas sin cambios posteriores.
- Limpio: los guards nuevos se ponen rojos con el caso contrario, y el CI corre los 4 comandos.

## E. estado
- Mira: data/parquet, data/pit_signals, earnings_cache, universo, price_cache, artefactos de cohorte.
- Busca: (→) store sin dueño que quedó atrás de sus pares; (←) operación manual periódica sin disparador.
- Afuera: backups (van a operacion).
- Limpio: cada store tiene regenerador y está alineado con sus pares a la fecha.

## F. pantalla
- Mira: los números de Home/Paper/Métricas para la cuenta 2, contrastados contra la DB (mode=ro).
- Busca: (→) número que no es lo que el rótulo dice; (←) vacío pintado como dato.
- Afuera: estética, layout.
- Limpio: cada número trazado coincide con el cálculo a mano y los vacíos se rotulan.

## G. cuentas
- Mira: cuadre de caja y acciones de cuentas 1 y 2; reglas max_positions/caja/cuenta cerrada; cartera real.
- Busca: (→) descuadre; (←) violación de límite declarada en órdenes/snapshots desde 2026-10-02.
- Afuera: si las decisiones fueron buenas.
- Limpio: cuadre al centavo y ningún límite violado.

## H. operacion
- Mira: log de producción desde 2026-10-02, snapshots por día hábil, backups/ rotación, Slack.
- Busca: (→) job que falla/se repite/no corre; (←) aviso que debería salir y no sale.
- Afuera: infra 196.
- Limpio: cada día hábil tiene scan, el backup diario existe y rota, ningún mensaje se repite sin tope.

## I. datos
- Mira: distribución de clasificación de noticias recientes, cobertura de facts/consenso del universo vivo.
- Busca: (→) campo degenerado o hueco de cobertura sin aviso; (←) inconsistencia entre fuentes.
- Afuera: poder predictivo.
- Limpio: sin campo degenerado nuevo y sin ticker vivo sin cobertura no avisada.

## J. rendimiento
- Mira: duración de scans en el log vs intervalo, `database is locked`, EXPLAIN de consultas calientes.
- Busca: (→) scan > intervalo o lock; (←) job de fondo sin techo de tiempo.
- Afuera: optimización que no cambia conducta.
- Limpio: ningún scan excede su intervalo, ningún lock, sin SCAN TABLE en tabla creciente del camino caliente.

## K. dependencias
- Mira: imports de terceros vs requirements*, instalado en Anaconda/.venv, pines.
- Busca: (→) import no declarado; (←) declarado distinto de lo instalado.
- Afuera: actualizar versiones.
- Limpio: todo import declarado y Anaconda coincide con el lock.

## L. logs
- Mira: censo de firmas WARNING+ del log de producción desde 2026-10-03 (cierre de la tanda anterior).
- Busca: (→) firma desconocida; (←) firma conocida que sigue después del cierre de su tarea.
- Afuera: contenido de INFO.
- Limpio: toda firma clasificada y ninguna conocida post-cierre.
