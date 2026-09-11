# Auditoría READ-ONLY — área `guards` — 2026-09-11

Corrida de la tanda del **2026-09-11** (las cinco áreas). Área: **guards que degradan en
silencio**. Corrida anterior de esta área: `docs/auditoria_guards_2026-09-08.md` (dejó las
tareas 139, 140 y 141).

---

## 1. Kill-criteria — CONGELADO 2026-09-11, antes de abrir ningún archivo

> Congelado junto con los otros cuatro de la tanda.

### 1.1 Por qué ahora

**Porque hoy mismo fallaron cuatro guards, y los cuatro por la misma razón.** En las tareas
173, 150, 176 y 177 apareció el mismo defecto: **el guard verifica sobre algo que no
discrimina el caso que busca** — un substring que lo satisface una línea que dice lo
contrario (173), una pertenencia a lista que no dice nada del orden que decide (150), un
`in doc` que satisface el frontmatter en vez del cuerpo (176), y una población real que no
contiene el caso que separa las dos semánticas (177).

Y el **175** es peor: el guard de la 130 —escrito precisamente para que los espejos no
mintieran— estuvo **rojo en el CI 35 corridas** y verde en la máquina de Chapa, y nadie se
enteró porque el criterio de done no mira el CI.

O sea que esta área tiene, hoy, evidencia fresca de que **la forma de fallar de los guards
de este repo es sistemática**, no anecdótica.

### 1.2 Qué se busca — una frase por sub-categoría

- **[G-mudo]** Un guard cuyo fallo no llega a nadie: `except` que traga, fail-open sin log,
  aviso que no escala si se repite.
- **[G-ciego]** Un guard que **no puede ver** el defecto que describe: su referencia sale de
  lo mismo que chequea, o compara el nombre en vez del valor.
- **[G-inerte]** Un guard **declarado y no cableado**, o cableado a algo que nadie corre
  (la forma de la 97: *«declarado» no es «cableado»*).
- **[G-bueno]** Un guard que puede estar rechazando el **dato bueno** — la pregunta que
  destapó la 63.
- **[G-entorno]** Un guard que pasa en una máquina y falla en otra por estado vivo, o al
  revés (la forma de la 175).

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. **Bugs de código** y **re-correr harness**.
2. Los guards **de trading** en cuanto a si su umbral es el correcto: eso es una decisión
   con backtest, no una auditoría.
3. Las otras cuatro áreas de la tanda.

### 1.4 Qué contaría como "acá no hay nada"

Cierra limpia si, por cada guard barrido:

- se puede nombrar quién se entera cuando falla;
- su referencia viene de un eje distinto del que chequea;
- está cableado a algo que corre de verdad (suite, `/ship`, CI, scheduler);
- y se dice cuáles no se barrieron.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Mismo protocolo que el §1.5 de `docs/auditoria_claims_2026-09-11.md`. **En esta área en
particular se espera encontrar (c-metodo)**, porque los cuatro defectos de hoy son de una
forma que la corrida del 2026-09-08 tenía en su alcance.

### 1.6 Alcance — qué se mira

1. `scripts/check_repo_health.py`, `scripts/check_backlog_integrity.py`.
2. Los `announce_*` y los chequeos de `analysis/harness_config.py`.
3. Los guards de datos: `data/quality.py`, los de split/escala, el circuito de tickers
   muertos.
4. `tests/conftest.py` — los cuatro aislamientos (red, DB, log, Slack).
5. El cableado: `.claude/commands/ship.md`, `.pre-commit-config.yaml`, `.github/workflows/`.

### 1.7 Alcance — qué NO se mira, dicho antes

- Los guards de la UI.
- Los asserts internos de los tests que no son guards de invariante vivo.
- El pipeline de catalysts.

---

## 2. Hallazgos

_(se completa al correr)_

## 5. Deuda de método — qué le faltaba a la corrida anterior

_(se completa al correr; sólo entra lo etiquetado (c-metodo) o (d))_
