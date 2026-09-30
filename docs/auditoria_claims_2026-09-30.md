# Auditoría READ-ONLY — área `claims` — 2026-09-30

Primera corrida de la **tanda del 2026-09-30** (las cinco áreas, pedido de Chapa: *«hagamos todas
las auditorías nuevamente»*). Área: **afirmaciones y números que el proyecto usa HOY para decidir y
ya no son ciertos**. Corrida anterior de esta área: `docs/auditoria_claims_2026-09-11.md` (dejó las
tareas 178 a 182, las cinco cerradas).

---

## 1. Kill-criteria — CONGELADO 2026-09-30, antes de abrir ningún archivo

> Los **cinco** kill-criteria de esta tanda se congelaron **juntos, antes** de empezar ninguna
> corrida, y se commitean solos. Lo único mirado antes: los cinco informes del 2026-09-11, el de
> `desvios` del 2026-09-27, los **títulos** de `git log` desde el 2026-09-11 y la cola del backlog.

### 1.1 Por qué ahora

Desde la tanda anterior se cerraron **~60 tareas en 111 commits**. Lo que más mueve texto escrito:

- **`CLAUDE.md` se reescribió en su regla 1** (cortafuegos de red, tareas 209/211/213): es el texto
  que más se lee y el que más afirmaciones en presente hace sobre la suite.
- **La métrica VS SPY se rehízo cuatro veces** (218, 223, 224, 230) y entró un **score mensual**
  (194): todo número de alpha o de VS SPY citado antes del 2026-09-23 se midió con otra fórmula.
- **La segunda opinión** pasó de Finnhub solo a **mayoría de tres** (200, 201, 206), y *Acciones
  manuales* le pide a Chapa prenderla: es un texto que **dirige una acción**.
- **Dividendos a caja** (222) y el desvío re-descrito (221, 233).
- **El pipeline de catalysts perdió la rama RSS** (212) y ganó estados (`degraded`, `unavailable`,
  207/210/217): la skill `catalyst-pipeline` describe ese pipeline.
- **Nuevo veredicto:** T219 NO-SHIP; **T220** declara la reconciliación vivo↔harness *no decidible*.
- **La 196** cambió de destino tres veces (nube → Amazon → Pi de openHABian).

### 1.2 Qué se busca — una frase por sub-categoría

- **[C-numero]** Un número citado como vivo que hoy da otra cosa, o que se midió con una fórmula
  que ya no existe (foco: VS SPY/alpha pre-223, conteos de suite, de universo y de tickers).
- **[C-presente]** Una afirmación **en presente** que dejó de ser verdad, con foco en los textos
  que **dirigen una acción manual** (`CLAUDE.md`, *Acciones manuales*, skills, commands).
- **[C-dosLugares]** El mismo número o símbolo en dos lados con valores distintos.
- **[C-veredicto]** Un veredicto que se cita como vigente y que una re-medición posterior dio
  vuelta o dejó en duda (foco: T219, T220, y todo lo que dependa de la fórmula vieja de VS SPY).
- **[C-fundamento]** Un claim que **sostiene una regla o prioridad** y nadie re-verificó. Se
  publica como *«no se sabe»*, nunca como *«es falso»*, salvo que se mida.
- **[C-simbolo]** Un símbolo, archivo, comando o flag **retirado o renombrado** que un texto
  operativo sigue nombrando (foco: la rama RSS de la 212).

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. Bugs de código (suite, CI, `/code-review`).
2. Los docs de veredicto de tareas **cerradas**, salvo que alguien los cite como vivos.
3. Correr harness o re-medir veredictos: si uno está en duda, va como tarea de medición.
4. Las otras cuatro áreas de la tanda; si un claim toca una, se cita y no se re-reporta.

### 1.4 Qué contaría como "acá no hay nada" — en las DOS direcciones

**Dirección 1 — lo escrito es falso.** Toda afirmación en presente de `CLAUDE.md`, de las skills y
de las tareas abiertas/acciones manuales del backlog coincide con el código, la DB y el
`settings.json` **de hoy**; ningún símbolo retirado aparece en el corpus operativo.

**Dirección 2 — lo verdadero no está escrito.** Todo mecanismo **vivo** agregado desde el
2026-09-11 que cambia lo que el operador tiene que saber (una perilla nueva del `SCHEMA`, un
estado nuevo del harvest, un aislamiento nuevo de la suite) aparece en la referencia que le toca
(`SETTINGS_REFERENCE.md`, la skill del área, `CLAUDE.md`).

Si las dos se cumplen, cierra limpia y se dice. Lo que no se pudo verificar se declara aparte.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Etiquetas (a) / (b) / (c-alcance) / (c-metodo) / (d) de la skill `auditoria`. Sólo (c-metodo) y
(d) son deuda de la skill. **El cruce de cobertura se hace por contenido, no por nombre de archivo.**

### 1.6 Alcance — qué se mira

1. `CLAUDE.md` completo.
2. `docs/BACKLOG.md` — header, *Acciones manuales pendientes*, la cola vigente y las tareas
   **abiertas**; no las cerradas.
3. `.claude/skills/**/*.md` y `.claude/commands/*.md`.
4. `docs/SETTINGS_REFERENCE.md` contra el `SCHEMA` vivo, **en las dos direcciones**.
5. Los docstrings/comentarios con mediciones de los módulos tocados desde el 2026-09-11
   (métricas VS SPY, segunda opinión, dividendos, harvest).

### 1.7 Alcance — qué NO se mira, dicho antes

- Los docs de veredicto de tareas cerradas uno por uno (§1.3.2).
- `ui/` salvo el texto que muestra la métrica VS SPY; `alembic/`; el README.
- `ARCHITECTURE.md` y `DB_SCHEMA.md` **sólo en las secciones que tocan módulos cambiados**
  desde el 2026-09-11; el resto se barrió el 2026-09-11. **Si esta corrida difiere algo, entra al
  backlog como tarea**, no como *«queda para la próxima»*.
