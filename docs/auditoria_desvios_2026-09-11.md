# Auditoría READ-ONLY — área `desvios` — 2026-09-11

Corrida de la tanda del **2026-09-11** (las cinco áreas). Área: **desvíos harness↔engine que
`deviations()` no declara**. Corrida anterior de esta área:
`docs/auditoria_desvios_2026-09-08.md` (dejó las tareas 128 a 135).

---

## 1. Kill-criteria — CONGELADO 2026-09-11, antes de abrir ningún archivo

> Congelado junto con los otros cuatro de la tanda.

### 1.1 Por qué ahora

Dos motivos, y el segundo es el que manda:

1. **La política de salida viva quedó apoyada en un veredicto que se dio vuelta.** El T37
   era SHIP por los nueve criterios; re-corrido sobre la muestra refrescada dio **NO-SHIP**
   (tarea 167). Chapa decidió **no mover** la política y pre-registrar la 170, que cerró
   **NO MOVER** con la rejilla **cerrada**. O sea que hoy el harness modela una política que
   el harness mismo ya no valida, y eso es exactamente el tipo de cosa que `deviations()`
   tiene que nombrar o que hay que declarar que no es un desvío.
2. **Se movieron perillas y símbolos.** La 156 sacó AVB del universo; la 158 cambió el
   default del productor PIT; la 161 y la 177 unificaron el parseo de universo; la 163
   renombró las anclas. Cada una de esas toca el contrato productor↔consumidor.

### 1.2 Qué se busca — una frase por sub-categoría

- **[D-falta]** Una perilla **viva** que el harness no modela y que `deviations_keyed()`
  **no nombra** con una clave. *(Sin ordinal, tarea 135: la pregunta es «¿falta alguno?»)*
- **[D-espejo]** Un `LIVE_*` que dejó de describir a la cuenta viva — o una perilla viva sin
  espejo (las dos mitades de la 130 / 131 / 132).
- **[D-texto]** Un desvío declarado cuyo **texto** describe mal lo que pasa, o que se
  contradice con otra línea del mismo banner (la forma de la 169).
- **[D-veredicto]** Un desvío que existía cuando se midió un veredicto publicado y que hoy
  no existe (o al revés), sin que nadie lo haya declarado al re-leer ese veredicto.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. **Bugs de código**, **re-correr harness** y **decidir política**.
2. Si un desvío **debería** cerrarse: eso es una decisión de trading, no de auditoría.
3. Las otras cuatro áreas de la tanda.
4. **El conteo de desvíos como número.** Desde la 152 cada uno tiene clave estable; se
   compara la **clave**, no la cantidad. El ordinal histórico y el conteo vivo son cosas
   distintas y confundirlas fabrica un hallazgo falso (casi pasó el 2026-09-08).

### 1.4 Qué contaría como "acá no hay nada"

Cierra limpia si, poniendo al lado la config viva (DB + `settings.json`) y la del harness:

- toda diferencia tiene su clave en `deviations_keyed()`;
- todo `LIVE_*` coincide con su fuente viva;
- ningún texto de desvío afirma algo que el código contradice;
- y se dice qué no se pudo verificar.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Mismo protocolo que el §1.5 de `docs/auditoria_claims_2026-09-11.md`.

### 1.6 Alcance — qué se mira

1. `analysis/harness_config.py` — `deviations()`, `deviations_keyed()`, los `LIVE_*`.
2. `paper_trading/engine.py` — los gates y lo que efectivamente lee.
3. `~/.finanzias/settings.json` y la cuenta viva en `finanzias.db` (lectura).
4. `analysis/portfolio_sim.py` y `replay_cycle` — qué modelan de verdad.
5. Los banners que los runners imprimen.

### 1.7 Alcance — qué NO se mira, dicho antes

- El pipeline de catalysts y el Gate 2c (está OFF y sin provider — tarea 162).
- `ui/`, `alembic/`.
- Los runners que **no** corren sobre la cuenta viva.

---

## 2. Hallazgos

_(se completa al correr)_

## 5. Deuda de método — qué le faltaba a la corrida anterior

_(se completa al correr; sólo entra lo etiquetado (c-metodo) o (d))_
