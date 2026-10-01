# Auditoría READ-ONLY — área `guards` — 2026-09-30 (segunda tanda)

Área: **guards que no ven lo que describen, que fallan mudos, o que rechazan el dato bueno**. Corrida anterior de esta área: `docs/auditoria_guards_2026-09-30.md` (esta mañana).

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

- **[G-ciego]** Los guards **nuevos de hoy** (corpus único de la 239, marco en pp de la 242,
  lecciones del harness de la 240, aviso de key de la 241): **mutar en el sentido del falso
  positivo** —la declaración que dice lo contrario— y exigir rojo.
- **[G-mudo]** Los jobs nuevos (8 y 9): cuando fallan, ¿quién se entera?
- **[G-excluido]** Lo que la mañana dejó sin mirar: `scripts/check_backlog_integrity.py` y
  `scripts/check_repo_health.py` **por dentro**.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. Bugs de código que no sean de esta área; re-correr harness; decidir política.
2. Las otras cuatro áreas de la tanda.

### 1.4 Qué contaría como "acá no hay nada" — en las DOS direcciones

**Dirección 1.** Cada guard nuevo se pone rojo con una mutación en el sentido del falso positivo, y
cada falla de un job nuevo deja rastro nombrable.

**Dirección 2.** Todo punto ciego real de esos guards está declarado en su docstring.

### 1.6 Alcance — qué se mira, como LISTA

1. `tests/corpus_operativo.py` y sus tres consumidores; `tests/test_marco_de_los_desvios_t242.py`;
   `tests/test_skill_harness_registra_veredictos_t240.py`; `data/providers.py` (aviso de key).
2. Los jobs 8 y 9 de `paper_trading/scheduler.py`.
3. `scripts/check_backlog_integrity.py` y `scripts/check_repo_health.py`.

### 1.7 Alcance — qué NO se mira, dicho antes

- Los guards de la UI.
