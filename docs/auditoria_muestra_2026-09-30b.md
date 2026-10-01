# Auditoría READ-ONLY — área `muestra` — 2026-09-30 (segunda tanda)

Área: **chequeos por cantidad o por población, ciegos a lo que importa**. Corrida anterior de esta área: `docs/auditoria_muestra_2026-09-30.md` (esta mañana).

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

- **[M-poblacion]** Una población nueva de los arreglos de hoy (el corpus derivado de `CLAUDE.md`,
  los tramos de la 242, las filas de la tabla de la 189 en la 240, los tickers del lote de la 243)
  que se puede vaciar o recortar sin que el guard se entere.
- **[M-ventana]** Un umbral nuevo atado al reloj (los 90 días del frame largo, el día calendario de
  los jobs 8 y 9, los 7 días del archivo) que es verdad hoy y deja de serlo cuando la ventana rueda.
- **[M-now]** La deuda que dejó la [M-2] de la mañana: tests que siembran fechas relativas a
  `now()` combinadas con un corte por mes, día o ventana — **en todo `tests/`**, no sólo en la t81.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. Bugs de código que no sean de esta área; re-correr harness; decidir política.
2. Las otras cuatro áreas de la tanda.

### 1.4 Qué contaría como "acá no hay nada" — en las DOS direcciones

**Dirección 1.** Todo guard nuevo tiene una contraprueba que falla si su población queda vacía, y
todo umbral nuevo atado al reloj está fijado por los dos lados.

**Dirección 2.** Ningún test de `tests/` depende del día en que corre sin fijar el reloj.

### 1.6 Alcance — qué se mira, como LISTA

1. Los guards y tests nuevos de los commits `f13e8a6..HEAD`.
2. `tests/` entero, buscando `now()`/`today()` con cortes de calendario, con el instrumento
   **validado contra la t81 vieja**, que es el caso conocido.

### 1.7 Alcance — qué NO se mira, dicho antes

- El motor vivo y `ui/`.
