# Auditoría READ-ONLY — área `desvios` — 2026-09-30

Tercera corrida de la **tanda del 2026-09-30**. Área: **desvíos harness↔engine que
`deviations_keyed()` no declara, o declara mal**. Corrida anterior de esta área:
`docs/auditoria_desvios_2026-09-27.md` (dejó las tareas 231 a 233, las tres cerradas).

---

## 1. Kill-criteria — CONGELADO 2026-09-30, antes de abrir ningún archivo

> Congelado **junto con los otros cuatro** de la tanda y antes de empezar ninguna corrida.

### 1.1 Por qué ahora

La corrida anterior es de hace **tres días**, pero en esos tres días el motor cambió dos veces:

1. **La segunda opinión pasó a mayoría de tres** (206, 2026-09-28): votan Yahoo, Finnhub y Tiingo;
   hay un caso *«sin mayoría»* que deja al scan sin precio. La 231 la dejó **espejada antes de
   prenderse** con la regla de dos fuentes; la 206 cambió la regla **después**. El encendido sigue
   pendiente en *Acciones manuales*, y ahora con Tiingo presente en esta máquina.
2. **Las alertas** (227, 237) y el **fetch fuera de la sesión** (238) tocaron el camino de precio.
3. **Los textos de desvío se reescribieron** (233): textos nuevos que nadie releyó con ojos ajenos.
4. **El Gate 2b del harness lee los espejos** (232): el harness cambió también.

### 1.2 Qué se busca — una frase por sub-categoría

- **[D-falta]** Una conducta **viva** del engine que cambia qué/cuándo/a qué precio/cuánto se opera,
  o cuánta caja hay, que el harness no modela y que ninguna clave de `deviations_keyed()` nombra.
- **[D-latente]** Un flag hoy OFF con encendido pendiente cuyo desvío, al prenderse, nada declara
  **con la regla vigente** (foco: la segunda opinión post-206).
- **[D-espejo]** Un `LIVE_*` que dejó de describir a la cuenta viva, o una perilla leída en una
  decisión sin espejo ni excepción con motivo **que nombre lo que dice cubrir**.
- **[D-texto]** Un texto de desvío que contradice al código **o al valor vivo de cada sub-perilla**,
  o un número presentado como estado actual sin fecha ni derivación (regla de la 233).
- **[D-veredicto]** Un veredicto publicado después del 2026-09-27 leído sin el desvío vigente.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. Bugs de código, re-correr harness y decidir política (si un desvío **debería** cerrarse).
2. El conteo de desvíos como número: se compara la **clave**.
3. Las otras cuatro áreas; el Gate 2c / catalyst (OFF), `ui/`, `alembic/`; la cuenta 1 (cerrada).

### 1.4 Qué contaría como "acá no hay nada" — en las DOS direcciones

**Dirección 1 — lo escrito es falso.** Ningún texto de `deviations_keyed()` afirma algo que el
engine o el valor vivo de sus perillas contradiga; todo `LIVE_*` coincide con `settings.json` y la
cuenta 2.

**Dirección 2 — lo verdadero no está escrito.** Recorriendo los **cambios del motor desde el
2026-09-27** (206, 227, 237, 238), toda diferencia con `portfolio_sim`/`replay_cycle` que mueva
órdenes, precio, tamaño o caja tiene su clave o su espejo con motivo; y la segunda opinión,
prendida hoy con la regla de tres, quedaría declarada por lo que ya existe.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Mismo protocolo. Con una corrida de hace tres días, se espera que casi todo sea **(a)**; un
**(c-metodo)** acá sería grave.

### 1.6 Alcance — qué se mira

1. `analysis/harness_config.py` — `deviations_keyed()`, textos, `LIVE_*`.
2. Los diffs del motor desde `614cf61`: `data/providers.py` y `data/yahoo_finance.py` (206),
   `paper_trading/engine.py`, `alerts/alert_manager.py`.
3. `~/.finanzias/settings.json` y la cuenta 2 — **lectura, sobre copia de la DB**.
4. Los guards de espejos (130, 185/231) en lo que toque a la segunda opinión.

### 1.7 Alcance — qué NO se mira, dicho antes

- `run_scan` de punta a punta: se recorrió entero el 2026-09-27; acá sólo los diffs posteriores.
- Los runners uno por uno.
