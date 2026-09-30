# Auditoría READ-ONLY — área `guards` — 2026-09-30

Cuarta corrida de la **tanda del 2026-09-30**. Área: **guards que degradan en silencio, que no
pueden ver lo que describen, o que rechazan el dato bueno**. Corrida anterior de esta área:
`docs/auditoria_guards_2026-09-11.md` (dejó la 185, compartida con `desvios`, cerrada).

---

## 1. Kill-criteria — CONGELADO 2026-09-30, antes de abrir ningún archivo

> Congelado **junto con los otros cuatro** de la tanda y antes de empezar ninguna corrida.

### 1.1 Por qué ahora

Desde el 2026-09-11 entraron **más guards que en cualquier período anterior**, y varios de ellos
declaran en su docstring lo que **no** ven:

- el **cortafuegos de red** de la suite (209, 211, 213) — declara dos puntos ciegos (hijos sin
  `site.py`, DNS);
- el guard de **cola del backlog** (195), el de **constante de cuenta usada** (229), el de **inicio
  de la serie de SPY** (225), el **barrido AST de fetch en sesión** (238, *«el barrido es léxico»*),
  el de **archivos del 185** (231), la **ventana del guard de valores vivos** (214);
- los guards **de datos en vivo**: segunda opinión por mayoría (200/201/206), cache que no se puede
  escribir (234), y la salud de fuentes del harvest (207, 210, 217).

La skill dice que **un punto ciego declarado y no cerrado es un hallazgo**. Nunca hubo tantos
declarados a la vez.

### 1.2 Qué se busca — una frase por sub-categoría

- **[G-mudo]** Un guard cuyo fallo no llega a nadie: `except` que traga, fail-open sin log, aviso
  que no escala si se repite.
- **[G-ciego]** Un guard que **no puede ver** el defecto que describe: compara el nombre en vez del
  valor, o su población no contiene el caso distinguidor. **Se prueba mutando en el sentido del
  falso positivo**, no leyendo.
- **[G-inerte]** Un guard declarado y no cableado a nada que corra.
- **[G-bueno]** Un guard que puede estar rechazando el **dato bueno** (foco: *«sin mayoría»* de
  la 206 deja al scan sin precio).
- **[G-puntoCiego]** Un punto ciego **declarado** en un docstring, sin tarea que lo cierre ni
  argumento escrito de por qué no hace falta.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. Bugs de código y re-correr harness.
2. Si el **umbral** de un guard de trading es el correcto (decisión con backtest).
3. Las otras cuatro áreas; los guards de la UI.

### 1.4 Qué contaría como "acá no hay nada" — en las DOS direcciones

**Dirección 1 — lo escrito es falso.** Todo guard barrido hace lo que su docstring dice: una
mutación en el sentido del falso positivo lo pone rojo, y quien falla se entera (se puede nombrar).

**Dirección 2 — lo verdadero no está escrito.** Todo punto ciego **real** de los guards barridos
está declarado en su docstring **y** tiene tarea o argumento de por qué no hace falta.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Mismo protocolo. **Revisión de exclusiones:** el pipeline de catalysts estuvo **fuera de alcance**
en las dos corridas anteriores de esta área; desde entonces ganó cuatro guards de salud (207, 210,
212, 217), así que esta vez **entra**.

### 1.6 Alcance — qué se mira

1. `tests/conftest.py` y `tests/_cortafuegos/` — los cinco aislamientos.
2. `scripts/check_backlog_integrity.py` (con la cola de la 195).
3. Los guards de test nuevos desde el 2026-09-11: 185/231, 214, 225, 229, 238.
4. Guards de datos vivos: `data/yahoo_finance.py` (E5, segunda opinión, cache 234),
   `data/providers.py`.
5. Guards de salud del harvest: `scripts/harvest_catalysts.py` y lo que lo alimenta.
6. El cableado: `.claude/commands/ship.md`, `.github/workflows/`.

### 1.7 Alcance — qué NO se mira, dicho antes

- Los guards de la UI.
- Los asserts internos de tests que no son invariantes vivos.
- Los guards anteriores al 2026-09-11 que la corrida pasada ya barrió, salvo que un commit
  posterior los tocó.
