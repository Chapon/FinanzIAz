# Auditoría READ-ONLY — área `desvios` — 2026-09-30 (segunda tanda)

Área: **desvíos harness↔engine que `deviations_keyed()` no declara, o declara mal**. Corrida anterior de esta área: `docs/auditoria_desvios_2026-09-30.md` (esta mañana).

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

- **[D-falta]** Una conducta nueva del motor o de sus datos, de los arreglos de hoy, que el harness
  no tiene y nada declara.
- **[D-sustrato]** Un job nuevo que **reescribe un archivo que el harness lee** como parte de su
  muestra congelada (foco: el frame largo de SPY que refresca el job 9, y si algún runner lo lee).
- **[D-texto]** Los textos reescritos por la 242: que cada número diga su marco **y** que el número
  sea el del doc de veredicto, no el de un enunciado.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. Bugs de código que no sean de esta área; re-correr harness; decidir política.
2. Las otras cuatro áreas de la tanda.

### 1.4 Qué contaría como "acá no hay nada" — en las DOS direcciones

**Dirección 1.** Ningún texto de `deviations_keyed()` afirma algo que el código, el valor vivo o el
doc de veredicto que cita contradiga.

**Dirección 2.** Ningún artefacto que lea un runner es reescrito por un proceso vivo sin que el
runner lo declare o lo excluya.

### 1.6 Alcance — qué se mira, como LISTA

1. `analysis/harness_config.py` (textos) contra los docs de veredicto que citan.
2. Quién lee `data/parquet/SPY__*` entre los runners y `analysis/`, contra lo que escribe el job 9.

### 1.7 Alcance — qué NO se mira, dicho antes

- `run_scan` entero; la cuenta 1.
