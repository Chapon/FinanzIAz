# Auditoría READ-ONLY — área `estado` — 2026-09-30

Quinta corrida de la **tanda del 2026-09-30**. Área: **estado regenerable que nadie regenera**.
Corrida anterior de esta área: `docs/auditoria_estado_2026-09-11.md` (dejó las tareas 186 a 188,
las tres cerradas).

---

## 1. Kill-criteria — CONGELADO 2026-09-30, antes de abrir ningún archivo

> Congelado **junto con los otros cuatro** de la tanda y antes de empezar ninguna corrida.

### 1.1 Por qué ahora

1. **Tres semanas desde el último refresh del cohorte** (2026-09-09) y dos y media desde el último
   re-precómputo del store PIT de riesgo (2026-09-12, tarea 192). Es el intervalo más largo sin
   regenerar desde que el área existe.
2. **Stores nuevos o que cambiaron de forma**: el ledger de dividendos (`paper_dividend_credits`,
   222), el registro de la segunda opinión (206), el consenso con *una fila por día* en el esquema
   (203), `surprise_profiles.json` —hoy **modificado sin commitear** en el árbol de trabajo—, y la
   rotación de backups que la 187/193 cambió.
3. **La 196** va a mover la recolección a otra máquina: todo store que hoy se regenera por un
   proceso de esta máquina puede quedar sin dueño en el traspaso.
4. **La 236**: la suite sin estado dejaba el cache de yfinance **en el repo**.

### 1.2 Qué se busca — una frase por sub-categoría

- **[E-huerfano]** Un store o cache **sin dueño** ni contrato de frescura.
- **[E-silencio]** Un artefacto que envejece sin que nada compare su frescura con la de sus pares.
- **[E-irreversible]** Estado cuya pérdida no se deshace y que una operación manual puede pisar.
- **[E-proceso]** Un proceso vivo con código viejo en memoria que sigue escribiendo.
- **[E-crece]** Estado que crece sin poda y nadie mide cuánto.
- **[E-versionado]** Un archivo **versionado** que un proceso vivo reescribe, dejando el árbol sucio
  (forma de la 173 y del `surprise_profiles.json` de hoy).

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. Bugs de código y re-correr harness.
2. **Escribir en la DB o en cualquier artefacto.** La DB se lee **sobre una copia**.
3. Las otras cuatro áreas; la calidad de los datos de Yahoo; el esquema como tal.

### 1.4 Qué contaría como "acá no hay nada" — en las DOS direcciones

**Dirección 1 — lo escrito es falso.** Todo contrato de frescura escrito (docstring, skill,
checklist de la 192) coincide con la edad real del store.

**Dirección 2 — lo verdadero no está escrito.** Todo store de §1.6 tiene nombrado **quién** lo
regenera, **cada cuánto** y **qué pasa si no**, o está declarado que no hace falta; y lo que se
regenera con proceso de esta máquina tiene previsto su dueño en el traspaso de la 196.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Mismo protocolo.

### 1.6 Alcance — qué se mira

1. `data/pit_signals/`, `data/parquet/`, `data/harness_results/`, `data/catalyst/`.
2. Los archivos de universo.
3. Las tablas de cache/registro de `finanzias.db` (**copia**): `price_cache`, `earnings_cache`,
   consenso, dividendos, segunda opinión, alertas.
4. `backups/` — rotación real contra la que la 187/193 declara.
5. Los procesos vivos (app, scheduler) y qué regeneran.
6. `~/.finanzias/` — log y settings; y la raíz del repo (residuos de la 236).

### 1.7 Alcance — qué NO se mira, dicho antes

- `alembic` y el esquema como tal; `.venv`; temporales de sesión.
