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
   `hallazgo-a-backlog`). Sin esto la auditoría no está cerrada.

**Un barrido limpio es un resultado válido.** Si el área no tiene nada, decilo y cerrá — no
llenes el informe.

No arregles nada: la remediación es una decisión aparte y te la pido explícitamente.
