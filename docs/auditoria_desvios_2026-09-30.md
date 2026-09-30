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

---

## 2. Alcance real

**Mirado:** `git diff 614cf61 HEAD` sobre `paper_trading/engine.py`, `analysis/harness_config.py`,
`analysis/scaleout_replay.py`, `data/providers.py`, `data/yahoo_finance.py` y
`alerts/alert_manager.py`; los textos de **todas** las claves de `deviations_keyed()`; los `LIVE_*`
contra `~/.finanzias/settings.json` (corriendo `tests/test_espejos_vivos_t130.py` y
`tests/test_espejos_direccion_faltante_t185.py` contra el archivo vivo: 100 passed, sin skip) y
contra la cuenta 2 en una **copia** de la DB (id, nombre, modo, `equal_weight`, 10 slots, watchlist
127, universo 126); el ledger de dividendos contra el calendario cacheado de las 9 tenencias.

**NO mirado, y queda declarado:** `run_scan` entero (se hizo el 2026-09-27); los runners uno por uno.

**Fase adversarial: PROPIA, no independiente.** Ningún hallazgo llegó a HIGH. Refutación intentada
en [D-1]: se buscó un test que fije el marco del número a propósito (no hay) y un texto que lo
declare (el comentario del fuente dice lo contrario).

---

## 3. Hallazgos

### [D-1] El desvío `regime_scale` le presta al banner un número de OTRO marco, y en el marco de la cuenta tiene el signo contrario

Severidad: **MEDIA** · Confianza: ALTA · Categoría: [D-texto]
Ubicación: `analysis/harness_config.py:2311-2318` (el texto) y `:161-166` (el comentario)

**Evidencia.** El texto que imprime **todo** runner: *«Vale +0.93pp de CAGR y −4.5pp de maxDD (T115,
el factor vivo desde el 2026-09-07…)»*. Ese número es de la **Corrida A** de la T115: *«5 slots, 41
tickers, 4015 entradas»* (`docs/t20_killgate_t115_2026-09-07.md:29,42`). En el marco de la cuenta
—10 slots, universo vivo, gates modelados— la T121 midió para el mismo `f025` **ΔCAGR −0,34 pp** y
ΔSharpe −0,00, con maxDD 33,7% → 28,9% (**−4,8 pp**), en una corrida **VÁLIDA** que da *«no cumple»*
el criterio de la T20 (`docs/f025_validar_t121_2026-09-07.md`; sin gates, −0,47 pp). El comentario del fuente, además, lo presenta como *«re-medido hoy sobre la muestra viva del
harness»*.

**Razonamiento.** Los runners que imprimen ese banner corren, por default, sobre 10 slots y el
universo vivo. El texto les dice cuánto vale el desvío **en otro marco**, y en CAGR el signo es el
contrario. Es la clase exacta que la **119** sacó del banner (*«el banner deja de prestarle a un
harness el número de otra corrida»*) y que la **43** documentó para el ~8 pp de la T9 (*«medido a 5
slots/41 tickers»*). Además es **pre-refresh** (2026-09-07) y el runner que lo produjo
(`run_sizing_exposure_t10_t20.py`) no entra en la población de `docs/VALIDEZ_VEREDICTOS.md`, así que
ningún índice dice sobre qué muestra se midió.

**Impacto.** Quien lee el banner para decidir si el desvío no modelado puede mover su veredicto lee
*«+0,93 pp a favor del vivo»*; en su marco, lo medido es *«−0,34 pp, no cumple»*. La parte de
drawdown sí es del mismo orden en los dos marcos.

**Corrección posterior (2026-09-30, al trabajar la tarea 242) — error mío de instrumento, el
hallazgo se sostiene.** La primera versión de este informe decía *«−0,47 pp… y esa corrida quedó
**sin veredicto**»*. Las dos cosas estaban mal: las leí del **enunciado** de la tarea 121 en el
backlog, escrito **antes** de correrla, que citaba la corrida B de la T115 (sin gates, cayó por un
sanity). El doc de veredicto de la 121 dice otra cosa: corrida **válida**, −0,34 pp con gates. El
signo contrario —que es el hallazgo— no cambia. Es la forma de [[validar-el-instrumento-antes-del-numero]]:
un enunciado no es un veredicto, y el número se lee del doc que lo publicó.

**Verificación.** No hay test que fije ese texto a la Corrida A; el test de la 43 cubre la T9 y no
este número.

**¿Por qué no antes? (c-metodo)** — la corrida del 2026-09-27 leyó este texto (le corrigió el
*«0 de 62»*) y la regla que salió de ella (233) pide contrastar cada afirmación contra el **valor
vivo** y fechar los conteos. No pide contrastar el **marco** en que se midió un número contra el
marco del que lo va a leer. Ver §6.

**Acción.** Que el texto diga el marco del número, o que cite el del marco vivo (T121); corregir
el comentario de `:164`.

---

## 4. Barrido limpio en el resto del área — las dos direcciones

**Dirección 1 (lo escrito es falso).** Fuera de [D-1]: los `LIVE_*` coinciden con el settings vivo y
la cuenta 2. El texto de `second_opinion` describe la regla de tres (lo actualizó la 206) y es
condicional al espejo, que está en `False` como el vivo. `universe_screen` deriva sus patas (233).
`dividendos`: el ledger tiene 0 filas y **es correcto** — de las 9 tenencias, la única con ex-date
posterior al 2026-09-25 es LRCX (09-23), comprada el 09-28, después del ex.

**Dirección 2 (lo verdadero no está escrito).** Los cambios del motor desde el 2026-09-27: la 206
sólo existe con el flag ON y ya tiene clave condicional; el `engine.py` sólo cambió el formato del
aviso; las alertas (227/237) y el barrido de la 238 no tocan órdenes, precio, tamaño ni caja. **No
aparece ninguna conducta viva sin declarar.**

**[D-veredicto]:** no hay veredicto publicado después del 2026-09-27. Limpio.

**Relacionado, reportado en otra área:** los textos **fuera** del registro de desvíos que describen
la segunda opinión con la regla vieja van en `docs/auditoria_claims_2026-09-30.md` [C-3]; y que la
regla de tres se degrade en silencio sin keys, en `docs/auditoria_guards_2026-09-30.md` [G-2]. Con el
flag ON y sin keys, el motor se comportaría como OFF mientras el banner declara `second_opinion`:
es sobre-declarar, que es la dirección segura, y no se reporta aparte.

---

## 5. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [D-1] `regime_scale` presta un número del marco 5 slots/41 tickers | MEDIA | **242** |

---

## 6. Deuda de método

**[D-1] es (c-metodo), y es la regla de la 233 un paso más allá.** La 233 pidió contrastar cada
afirmación de un desvío contra el valor vivo y fechar los conteos. Un número **con** fuente y **con**
tarea citada pasa las dos, y puede estar medido en otro marco. Lo que faltaba: *todo número de
magnitud en un texto de desvío declara el marco (slots, universo, ventana) en que se midió, y se
contrasta contra el marco por default de los runners que lo imprimen* — la lección de la 43 y la
119, que el método de esta área no tenía escrita.
