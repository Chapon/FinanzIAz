# Auditoría READ-ONLY — área `muestra` — 2026-09-11

Corrida de la tanda del **2026-09-11** (las cinco áreas). Área: **chequeos por CANTIDAD,
ciegos a la identidad de la muestra**. Corrida anterior de esta área:
`docs/auditoria_muestra_2026-09-08.md` (dejó las tareas 144 y 145).

---

## 1. Kill-criteria — CONGELADO 2026-09-11, antes de abrir ningún archivo

> Congelado **junto con los otros cuatro** de la tanda y antes de empezar ninguna corrida,
> para que el criterio de un área no se calibre con lo que apareció en otra.

### 1.1 Por qué ahora — y es la razón más fuerte de las cinco

**El sustrato de esta área se movió de verdad, no de a poco.** El 2026-09-09 se refrescó el
cohorte y eso cambió **la muestra misma**: la ventana pasó a `2016-09-12..2026-09-09`, las
17 constantes de reproducción se re-anclaron (157), la watchlist bajó de 128 a 126, y **AVB
perdió su histórico** quedando como miembro **inerte** de 27 barras (156).

Y hay un precedente exacto de lo que esta área existe para cazar, **de esta semana**: la
tarea **164** encontró que el brazo de control se sorteaba por **índice de barra**, así que
cualquier refresh lo re-sorteaba entero — y eso **invalidó al T37 y al T47** sin que ningún
control lo dijera. O sea: un chequeo que miraba la cantidad de barras y no **cuáles**.

### 1.2 Qué se busca — una frase por sub-categoría

- **[M-cantidad]** Un invariante decidido contando (`len(...) >= n`, un conteo de filas, un
  `n_tickers`) donde lo que importa es **cuáles** elementos, no cuántos.
- **[M-ventana]** Un chequeo que sigue siendo verdad con la ventana vieja y falso con la
  rodada, sin que nada lo declare.
- **[M-poblacion]** Una población derivada de una **lista** o de una convención de nombre en
  vez de de la **propiedad** que al chequeo le importa (la familia 133 / 141 / 147 / 161).
- **[M-inerte]** Un miembro que cuenta como sano para algún conteo pero no aporta nada
  —el caso AVB— y algún chequeo lo toma como evidencia.
- **[M-vacio]** Un chequeo que pasa **por población vacía** y se lee como *«no hay
  violaciones»* (el defecto de la 174, cerrado hoy).

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. **Bugs de código** y **re-correr harness**.
2. **Los guards** en cuanto a si degradan en silencio — eso es el área `guards` de esta
   misma tanda.
3. **Los desvíos harness↔engine** — área `desvios`.
4. **Los artefactos y su frescura** como problema de regeneración — área `estado`. Acá sólo
   interesa si un **chequeo** los lee mal.

### 1.4 Qué contaría como "acá no hay nada"

Cierra limpia si, habiendo barrido los sustratos de §1.6, se verifica que:

- todo `len(...)`/conteo que decide *«la muestra es ésta»* tiene al lado una comparación de
  identidad (fechas, claves o huella), o está declarado por qué no hace falta;
- ninguna población viva sale de una lista hardcodeada donde existe un predicado;
- los conteos pinneados en tests y runners coinciden con lo que el cohorte mide hoy;
- y se dice qué no se pudo verificar.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Mismo protocolo que el §1.5 de `docs/auditoria_claims_2026-09-11.md`: etiquetas **(a) NO
EXISTÍA**, **(b) FUERA DE ALCANCE**, **(c-alcance)**, **(c-metodo)** y **(d) SE DESCARTÓ
MAL**, y sólo **(c-metodo)** y **(d)** cuentan como deuda de la skill.

### 1.6 Alcance — qué se mira

1. `analysis/harness_config.py` — los chequeos de población, ventana, frescura y store.
2. `analysis/portfolio_sim.py`, `analysis/scaleout_replay.py`, `analysis/exit_replay.py`.
3. `scripts/run_*.py` y `scripts/measure_*.py` — sus sanity y sus constantes pinneadas.
4. `scripts/precompute_pit_*.py` — las guardas de completitud.
5. Los tests que **pinnean conteos** como invariante de muestra.

### 1.7 Alcance — qué NO se mira, dicho antes

- El motor vivo (`paper_trading/engine.py`) salvo donde comparta un chequeo con el harness.
- `ui/`, `data/news_sources.py`, el pipeline de catalysts.
- La calidad de los datos de Yahoo en sí.

---

## 2. Hallazgos

_(se completa al correr)_

## 5. Deuda de método — qué le faltaba a la corrida anterior

_(se completa al correr; sólo entra lo etiquetado (c-metodo) o (d))_
