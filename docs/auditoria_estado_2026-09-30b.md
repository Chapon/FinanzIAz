# Auditoría READ-ONLY — área `estado` — 2026-09-30 (segunda tanda)

Área: **estado regenerable que nadie regenera, o que alguien pisa**. Corrida anterior de esta área: `docs/auditoria_estado_2026-09-30.md` (esta mañana).

---

## 1. Kill-criteria — CONGELADO 2026-09-30, antes de abrir ningún archivo de código

> Los **cinco** kill-criteria de esta tanda se congelaron **juntos, antes** de abrir código, y se
> commitean solos. Lo único mirado antes: los informes de la tanda de la mañana
> (`docs/auditoria_*_2026-09-30.md`), sus secciones *NO mirado*, y los **títulos** de `git log
> f13e8a6..HEAD`.

### 1.1 Por qué ahora

Es la **segunda tanda del día**, pedida por Chapa después de cerrar las tareas de la primera (239 a
248, salvo la 245). Esas tareas cambiaron **39 archivos** en 11 commits, y un arreglo nuevo es
exactamente el sustrato que esta skill existe para auditar: texto recién escrito que nadie releyó con
otros ojos, guards nuevos que nadie intentó engañar, y **jobs nuevos que escriben estado** (el
archivo diario de la cinta, 244; el refresh del frame largo de SPY, 246). La corrida de la mañana no
pudo verlos: no existían.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Etiquetas (a) / (b) / (c-alcance) / (c-metodo) / (d). Con una corrida de **esta mañana**, se espera
que casi todo sea **(a)** —introducido por los arreglos—; un (a) acá es **deuda de la tarea que lo
introdujo**, no de la skill, y se dice cuál.

### 1.2 Qué se busca

- **[E-pisa]** Un job nuevo que reescribe estado que otro consumidor trata como **congelado** (el
  frame largo de SPY del job 9; el Parquet de la cinta del job 8).
- **[E-irreversible]** El primer arranque del job 8 borra ~200k filas: ¿qué lo respalda si el
  Parquet sale mal y la verificación lo da por bueno?
- **[E-crece]** `data/price_tape/` sin poda: ¿alguien mide cuánto crece?
- **[E-excluido]** El esquema (`alembic`), que la mañana dejó afuera, en lo que toque a las tablas
  que ahora se escriben de otra forma.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. Bugs de código que no sean de esta área; re-correr harness; decidir política.
2. Las otras cuatro áreas de la tanda.

### 1.4 Qué contaría como "acá no hay nada" — en las DOS direcciones

**Dirección 1.** Todo contrato de frescura o de respaldo escrito por los arreglos de hoy coincide con
lo que el código hace.

**Dirección 2.** Todo archivo que un job nuevo reescribe tiene nombrado quién más lo lee, y ninguno
de esos lectores lo trata como congelado sin saberlo.

### 1.6 Alcance — qué se mira, como LISTA

1. `data/parquet/SPY__*`, `data/price_tape/`, y sus escritores y lectores.
2. `database/backup.py` contra el primer arranque del job 8.
3. `alembic/versions/` en lo que toque a `price_cache`.

### 1.7 Alcance — qué NO se mira, dicho antes

- `.venv`; temporales de sesión.
