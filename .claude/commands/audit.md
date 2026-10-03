---
description: Auditoría profunda READ-ONLY por área (claims / muestra / desvios / guards / estado / pantalla / cuentas / operacion / datos / rendimiento / dependencias / logs)
---

Invocá la skill `auditoria` y corré una auditoría READ-ONLY del área: **$ARGUMENTS**

Si no te pasé área, mostrame las áreas y **preguntame cuál** antes de empezar — no arranques
un barrido de todas juntas.

| área | qué busca |
|---|---|
| `claims` | afirmaciones y números que el proyecto usa hoy y ya no son ciertos |
| `muestra` | chequeos por cantidad que son ciegos a la ventana/población |
| `desvios` | desvíos harness↔engine que `deviations()` no declara |
| `guards` | guards que fallan en silencio o rechazan el dato bueno (el CI incluido) |
| `estado` | caches y artefactos regenerables que nadie regenera |
| `pantalla` | números de la UI que no son lo que el rótulo dice, o que pintan un vacío como dato |
| `cuentas` | la cartera (paper o real) viola un límite que declara, o órdenes/posiciones/caja no cuadran |
| `operacion` | jobs de fondo que fallan, se repiten o no corren; avisos que no llegan; backups y restore |
| `datos` | el contenido de una fuente (noticias, consenso, fundamentals, universo) no dice lo que se cree |
| `rendimiento` | algo tarda tanto que cambia lo que pasa (locks, índices, jobs sin techo) |
| `dependencias` | lo que corre no es lo que se declara (imports, entornos, pines) |
| `logs` | el censo: cada firma de error del log clasificada (conocida / explicada / desconocida) |

El orden de la corrida:

1. **Escribí el kill-criteria ANTES de abrir un archivo** — qué se mira, qué queda afuera, y
   qué contaría como *"acá no hay nada"*. Mostrámelo antes de seguir.
2. Barré el área. READ-ONLY: no toques código, config, esquemas ni tests.
3. Pasá los hallazgos **HIGH y CRITICAL** por el agente `verificador`, con el mandato de
   **refutarlos**. Lo que no sobrevive se borra, no se degrada.
4. Escribí `docs/auditoria_<área>_<fecha>.md` con lo que sobrevivió, lo que se rechazó y con
   qué motivo, y el alcance que **no** se miró.
5. Anotá cada hallazgo accionable como tarea en `docs/BACKLOG.md` (skill
   `hallazgo-a-backlog`).
6. **Cerrá con la tabla de mapeo `hallazgo → tarea`**, una fila por hallazgo publicado y
   **ninguna vacía**. Verificala de a una contra el backlog, no de memoria. Ojo con los dos
   casos que se escapan: un hallazgo agrupado como *"parte de"* otro tiene que aparecer en el
   **enunciado** de esa tarea, y un hallazgo que **no pudiste verificar** igual va a la cola
   si lo accionable es *"nadie lo re-chequeó"* (eso se verifica con `git log`, no midiendo).
   **Sin esta tabla la auditoría no está cerrada** — en la primera corrida se publicaron 7
   hallazgos con 3 tareas y dos quedaron sueltos.

**Un barrido limpio es un resultado válido.** Si el área no tiene nada, decilo y cerrá — no
llenes el informe.

No arregles nada: la remediación es una decisión aparte y te la pido explícitamente.
