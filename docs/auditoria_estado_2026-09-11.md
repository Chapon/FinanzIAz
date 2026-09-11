# Auditoría READ-ONLY — área `estado` — 2026-09-11

Corrida de la tanda del **2026-09-11** (las cinco áreas). Área: **estado regenerable que
nadie regenera, y estado vivo que se desalinea en silencio**. Corrida anterior de esta área:
`docs/auditoria_estado_2026-09-08.md` (dejó las tareas 142 y 143).

---

## 1. Kill-criteria — CONGELADO 2026-09-11, antes de abrir ningún archivo

> Congelado junto con los otros cuatro de la tanda.

### 1.1 Por qué ahora

**Porque esta área acaba de cobrarse algo irreversible.** El 2026-09-09, durante la
operación de la 140, se refrescó el cohorte **a mano** y con eso se pisó
`ARTIFACT_REFRESH_EXCEPTIONS`: **AVB perdió la última copia sana de su histórico** y quedó
en 27 barras. No se puede recuperar. La 155 shipeó el script que faltaba, pero el episodio
dice qué tan cerca de la superficie está el riesgo en esta área.

Y hay dos cosas nuevas que tocan estado regenerable: los **JSON del scheduler** resultaron
versionados y se re-escribían en CRLF (tarea 173 — cerrada hoy, pero **el arreglo no toma
efecto hasta que se reinicie la app**, que sigue corriendo con el código viejo en memoria), y
el **store PIT** se recomputó dos veces esta semana (157, 158).

### 1.2 Qué se busca — una frase por sub-categoría

- **[E-huerfano]** Un store o cache **sin dueño**: nadie declarado lo regenera, y no hay
  contrato de cada cuánto.
- **[E-silencio]** Un artefacto que envejece sin que nada compare su frescura contra la de
  sus pares (la forma de la 30 y la 69).
- **[E-irreversible]** Estado cuya pérdida **no se puede deshacer** y que alguna operación
  manual puede pisar (el caso AVB).
- **[E-proceso]** Un proceso vivo —la app, el scheduler— que tiene código **viejo en
  memoria** y sigue escribiendo con él.
- **[E-crece]** Estado que crece sin poda ni archivo y nadie mide cuánto.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. **Bugs de código** y **re-correr harness**.
2. **Escribir en la DB o en cualquier artefacto.** Esta corrida es de lectura: si hay que
   regenerar algo, va como tarea.
3. Las otras cuatro áreas de la tanda.
4. La calidad de los datos de Yahoo como tal.

### 1.4 Qué contaría como "acá no hay nada"

Cierra limpia si, por cada store de §1.6:

- se puede nombrar **quién** lo regenera y **cada cuánto**;
- se puede decir **qué pasa si no** se regenera;
- hay algo que compare su frescura contra sus pares, o está declarado que no hace falta;
- y se dice cuáles no se barrieron.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Mismo protocolo que el §1.5 de `docs/auditoria_claims_2026-09-11.md`.

### 1.6 Alcance — qué se mira

1. `data/pit_signals/`, `data/parquet/`, `data/harness_results/`, `data/catalyst/`.
2. `data/*universe*.txt` y `data/harness_universe_*`.
3. Las tablas de cache de `finanzias.db` (`price_cache`, `earnings_cache`, los snapshots).
4. `backups/` — rotación y contenido.
5. Los procesos vivos: la app y el scheduler, qué regeneran y con qué cadencia.
6. `~/.finanzias/` — log y settings.

### 1.7 Alcance — qué NO se mira, dicho antes

- El esquema de la DB como tal (`alembic`) — eso tuvo su corrida en la 74.
- Los artefactos de sesiones de Claude y los temporales.
- `.venv` y dependencias.

---

## 2. Hallazgos

_(se completa al correr)_

## 5. Deuda de método — qué le faltaba a la corrida anterior

_(se completa al correr; sólo entra lo etiquetado (c-metodo) o (d))_
