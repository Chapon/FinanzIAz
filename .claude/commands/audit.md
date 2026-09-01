---
description: Auditoría profunda READ-ONLY por área (claims / muestra / desvios / guards / estado)
---

Invocá la skill `auditoria` y corré una auditoría READ-ONLY del área: **$ARGUMENTS**

Si no te pasé área, mostrame las cinco y **preguntame cuál** antes de empezar — no arranques
un barrido de las cinco juntas.

| área | qué busca |
|---|---|
| `claims` | afirmaciones y números que el proyecto usa hoy y ya no son ciertos |
| `muestra` | chequeos por cantidad que son ciegos a la ventana/población |
| `desvios` | desvíos harness↔engine que `deviations()` no declara |
| `guards` | guards que fallan en silencio o rechazan el dato bueno |
| `estado` | caches y artefactos regenerables que nadie regenera |

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
