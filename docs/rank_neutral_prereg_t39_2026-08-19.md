# Pre-registro CONGELADO — El ranking vivo tiene alpha negativo (Tarea 39, RANK-NEUTRAL)

**Fecha:** 2026-08-19 · **Estado:** congelado ANTES de codear el harness (regla 2).
**Ref:** `docs/BACKLOG.md` tarea 39 · `docs/ranking_t21_2026-08-12.md` (el veredicto que dejó este
candidato sin declarar) · `docs/ranking_prereg_t21_2026-08-12.md` (la población y los umbrales que se
reusan) · `docs/meta_labeling_t9_2026-07-21.md` §13.6 (el mecanismo: concentrar vs repartir) ·
`docs/fill_lookahead_t33_2026-08-16.md` §6 (la re-lectura con el fill honesto) ·
`docs/stop_loosen_t34_2026-08-18.md` (el enabler `live_gates`).

Fija población, brazos, la regla de decisión y los sanity **ANTES de correr**. Nada se re-decide
después de ver resultados. Si el candidato no supera el umbral, se documenta NO-SHIP y el engine
queda como está.

---

## 0. Qué se miró ANTES de congelar (auditoría del instrumento)

**Verificado en código, no asumido:**

- **La clave de ranking vivo ES el `buy_score`.** `strategies.py:449` toma
  `strength = _default_strength("BUY", res.ml_probability)`, y `_default_strength`
  (`strategies.py:271`) devuelve `ml_probability` clipeado a [0,1]. `ranked.sort(reverse=True)` →
  `picks = ranked[:free_slots]`. Es exactamente lo que guardan los artefactos de `data/pit_signals/`,
  así que la medición transfiere sin proxies.
- **En la cuenta viva ese score NO toca el sizing.** Leído de `paper_accounts`: la cuenta 2
  ("Sim Segundo", **la viva**) corre `analyze_single`, `auto`, **`equal_weight`**, 10 slots.
  `equal_weight` **no** está en `_VOL_SIZED_MODES` (`strategies.py:54`), así que el `strength` sólo
  (a) **ordena** y (b) se persiste como `signal_score` de la orden (display). Cambiar la clave de
  orden es un cambio acotado y verificable, no un cambio de tamaño.
- **No hay una segunda clave escondida:** el blend cross-sectional (`cross_sectional_enabled`) está
  en **default OFF** y quedó KILLED en T05 (`docs/SETTINGS_REFERENCE.md`), así que `rank_key` es el
  `strength` puro.
- **Hallazgo sobre el instrumento (regla 6 — anotado como tarea 40 en el backlog):** los brazos
  `B0r_random` de la T21 **no son una función pura de (semilla, ticker, fecha)**: el valor sale del
  **orden de las llamadas** que hace el `sorted()` del día (`run_ranking_t21.py:176-186`). Es
  determinista *dentro* de una corrida —`by_date` se arma de `entries`, que es idéntico entre
  brazos—, así que **la medición publicada de la T21 se sostiene**; pero el objeto medido **no es el
  que se cablearía en el engine**, que cada día ve otro conjunto de candidatos. Esta tarea lo
  reemplaza por la función pura del §9.2, que es la que se shipearía.
- **Costo de la corrida:** la T33 midió la T21 en **174 s por config** con 15 brazos (~12 s/brazo).
  Acá son 44 brazos a 10 slots + 21 de sensibilidad ⇒ **~13 min**. Es lo más barato del backlog en
  relación a lo que decide.

**Lo que deliberadamente NO se miró:** **ningún** resultado de **ningún** brazo con la config de esta
tarea (`eval_mode="touch"` + `live_gates=True`), ni la banda de `P_fix`, ni el brazo invertido. El eje
de esta tarea es exactamente ése.

## 1. La pregunta

Seis mediciones convergentes por métodos distintos dicen que el `buy_score` **rankea al revés**:
`corr(score, retorno) = −0.0259` (n=26.988), top-20% **0.34%** contra bottom-20% **0.57%**, AUC OOS
**0.4980**, y en la T21 el ranking vivo dio **6.48%** de CAGR contra una mediana de 10 órdenes
aleatorias de **9.71%** [6.86%, 13.15%] — **por debajo de la banda ENTERA del azar**. La re-lectura
con el fill honesto (T33) baja toda la escala y **no mueve ninguna de las seis**: 1.97% contra un
mínimo aleatorio de 2.46%.

Y la T9 midió que eso **no es gratis**: un score sin alpha que igual decide cuesta **~8 pp de CAGR**
(13.14% contra 21.18% del orden alfabético), porque un orden arbitrario **reparte** entre todo el pool
mientras un score apenas del lado equivocado **concentra** la cartera en el subconjunto malo elección
tras elección, y con slots finitos compuestos durante años el sesgo diminuto **se acumula en vez de
promediarse**.

> **¿Sacarle la decisión al `buy_score` —reemplazarlo por un orden neutro genuino— le gana al ranking
> vivo, con la config honesta y los gates del engine modelados?**

No hay que encontrar alpha nuevo: hay que **dejar de pagar alpha negativo**. Con ~55 candidatos por
slot, el ranking es la pieza del motor que más veces se ejecuta.

## 2. Brazos (CONGELADO)

Lo único que cambia entre brazos es el **orden** de los candidatos del mismo día (`rank_score` de
`portfolio_sim`). Entradas, salidas, costos, gates y capital son idénticos.

| brazo | clave de orden | qué es |
|---|---|---|
| `B1_score` | `buy_score` (desc) | **BASELINE — es lo que corre hoy.** |
| **`N_rot_k`, k=0..19** | `u = H(12345+k, fecha, ticker)` | **CANDIDATO — la política.** Orden aleatorio **rotado por fecha**: no persiste entre días. `H` es la función pura del §9.2, la misma que se cablearía. |
| `P_fix_k`, k=0..19 | permutación fija del universo, `seed = 54321+k` | **Nulo pareado en persistencia** (diagnóstico, NO promovible). El alfabético de la T21 fue **una sola realización** de esta familia; acá se mide la familia entera. |
| `I_inverted` | `−buy_score` | Diagnóstico (NO promovible). Distingue dos mecanismos — ver §4.3. |
| `ORACULO` / `ANTI_ORACULO` | retorno realizado del ciclo (y su opuesto) | Sanity del instrumento. Miran el futuro, nunca shipeables. |

**El candidato es la política, no una semilla.** Se cablea **una sola** semilla y se elige **a
ciegas**, así que la decisión se toma sobre la **distribución de las 20** (§4.1). **La semilla que se
cablearía queda declarada acá, antes de ver un solo número: `paper_ranking_seed = 12345`** (la
constante estándar del proyecto). Elegir después la semilla que mejor rindió sería exactamente el
defecto que este pre-registro existe para no cometer.

**Por qué el alfabético NO es el candidato** (la trampa que la T21 ya pisó): pasó C1/C2/C4 y **falló
el bootstrap pareado** (IC95% [−1.82, +13.56] pp, p=0.071) porque **fue suerte** — +3.10 pp sobre la
mediana de las semillas. Orden **fijo** = apostar a nombres fijos durante 10 años, que **no es "sin
información"**.

## 3. Población y config (CONGELADO)

- **Universo:** `data/harness_universe_live_acct2.txt` (**127** tickers con PIT), el de la T21.
- **Entradas:** eventos `analyze() = BUY` point-in-time (`data/pit_signals/`) — 143.096 en la T21.
- **Cartera:** `portfolio_sim`, `max_positions=10` (cuenta viva), `initial_capital=50.000`,
  **`cap_days=250`** (lección T13 §2: el engine no tiene tope de tenencia; es el de la T21),
  `CostModel()`, `allow_reentry_while_open=False`, `AtrParams()` default (stop 2.0 / TP 4.0 /
  trailing), flip `analyze SELL` con Gate 2b.
- **`eval_mode="touch"`, `fill_mode="decision"`, `live_gates=True`** — la regla viva (26b), el fill
  honesto (T33) y los gates de re-entrada del engine modelados (T34). **La T21 no tenía ninguno de los
  tres.**
- **Sin overlay de régimen T20** — igual que la T21, por atribución limpia: es ortogonal al orden de
  los candidatos, y mantenerlo afuera hace las dos corridas comparables.
- **Sensibilidad** a `--max-positions 5` sobre los brazos de decisión (`B1_score` + las 20 `N_rot`).
  El veredicto se dicta a **10**. Ojo con la dirección esperada: el ranking decide **más** cuanto peor
  es el ratio de selección, así que a 5 slots el efecto debería **crecer**, no encogerse.

## 4. Cómo se mide una política aleatoria (el núcleo metodológico)

### 4.1 La política es una distribución, no un camino

Se cablea una semilla; el resultado de esa semilla es una realización. Por eso:

- **C1 y C3 se leen sobre la mediana** de las 20 semillas (el resultado esperado de una elección a
  ciegas).
- **C2 se lee sobre el mínimo** (la política tiene que ganar con **cualquier** semilla; ver §6).
- **C4 se pairea contra la serie diaria promedio de las 20 semillas** — el retorno diario esperado de
  la política. Promediar sobre semillas saca el ruido de la realización, que es **exactamente** lo que
  hundió a C3 en la T21: allá el ΔCAGR de +6.33 pp mezclaba los ~3.2 pp que cuesta el score con los
  ~3.1 pp de suerte del alfabético, y el bootstrap se negó —correctamente— a certificar la suma.

### 4.2 El bracket de persistencia (por qué existe la familia `P_fix`)

El `buy_score` es **persistente**: un nombre bien puntuado hoy tiende a estarlo mañana. `N_rot` **no
lo es** (rota todos los días) y `P_fix` es la punta **máximamente** persistente. Las dos familias
**acotan** al score, igual que `close`/`touch` acotan al engine en la 26b.

- Si `B1_score` cae **por debajo de las dos bandas**, la conclusión no depende del supuesto de
  persistencia y es todo lo fuerte que la muestra permite.
- Si cae por debajo de `N_rot` pero **dentro** de `P_fix`, buena parte del déficit es el **costo de
  concentrar** (el mecanismo de la T9) y no evidencia de alpha negativo. Eso cambia **la lectura**,
  no el veredicto: el veredicto lo dicta el §6, que compara la política candidata contra el baseline.
- Se reporta además la **autocorrelación de rango día-a-día del `buy_score`** (descriptivo) para
  ubicar al score dentro del bracket.

`P_fix` es **diagnóstico y no promovible**: aunque gane, orden fijo sigue siendo una apuesta a nombres
fijos durante 10 años (T21 §2b).

### 4.3 Qué distingue el brazo invertido

`I_inverted` responde una pregunta de mecanismo, no de decisión:

- Si `I_inverted` ≈ la mediana de `N_rot` ⇒ el score **no tiene signo explotable**: el déficit viene
  de concentrar, no de una señal inversa.
- Si `I_inverted` supera con holgura la banda de `N_rot` ⇒ **hay** señal inversa real.

En los dos casos **no se cablea**: un `corr` de −0.026 no sostiene una apuesta direccional (backlog
§39). Si pasa lo segundo, es un lead con pre-registro propio.

## 5. Sanity del instrumento (si falla alguno, la corrida es INVÁLIDA y no hay veredicto)

1. **Contabilidad:** `|equity_curve[-1] − final_equity| / final_equity ≤ 1e-6` en todos los brazos.
2. **Reproducción de la línea publicada:** `B1_score` corrido en la config del re-read de la T33
   (`eval_mode="close"`, `fill_mode="decision"`, `live_gates=False`, 10 slots, `cap_days=250`) da
   **1.97% ± 0.05 pp** de CAGR. Es determinista y no depende de ningún RNG: si no reproduce, cambió
   algo en la población o en la cañería y **nada de lo que siga es comparable**.
3. **El instrumento ve rankings buenos:** `CAGR(ORACULO) ≥ CAGR(B1_score) + 5.00 pp`. Mismo umbral y
   mismo helper que T21 §5.2 — **no se calibra uno nuevo**.
4. **Y ve rankings malos:** `CAGR(ANTI_ORACULO) ≤ CAGR(B1_score)`.
5. **El ranking muerde:** ≥ **10%** de los trades difieren entre `B1_score` y `N_rot_0`
   (par `ticker`+`entry_date`, helper `trade_overlap`). Mismo umbral que T21 §5.4 y 26b §5.3.
6. **Las semillas son efectivas:** la mediana del solapamiento par a par entre las 20 `N_rot` deja
   ≥ **10%** de trades distintos, y sus CAGR no son idénticos. Si las semillas no mueven nada, la
   "distribución" del §4.1 es una ilusión y C2 no significa nada.
7. **La política es una función pura:** unit test de que `H(seed, fecha, ticker)` no depende del orden
   de las llamadas ni del estado de la cartera (se la llama dos veces en órdenes distintas y da lo
   mismo, bit a bit). Es el defecto que se le encontró al brazo aleatorio de la T21 (§0) y lo que
   hace que el objeto medido sea el objeto shipeable.

## 6. Regla de decisión (CONGELADA)

**Candidato** = la política `N_rot` (20 semillas, base 12345). **Baseline** = `B1_score`. 10 slots,
`touch` / `decision` / `live_gates=True`. Se cablea **sólo si pasa las seis**:

| # | Criterio | Umbral |
|---|---|---|
| **C1** | ΔCAGR = mediana(`N_rot`) − `B1_score` | ≥ **+0.50 pp** (el mismo umbral de T21 C1) |
| **C2** | **Robustez a la semilla:** CAGR de **cada una** de las 20 semillas | **> CAGR(`B1_score`)**, las 20 |
| **C3** | **Riesgo, declarado al frente:** mediana de maxDD(`N_rot`) | ≤ maxDD(`B1_score`) **+ 3.00 pp** (el mismo umbral de T21 C2) |
| **C4** | **Anti-overfit:** block-bootstrap pareado sobre Δ(retorno diario) de la **serie promedio** de las 20 vs `B1_score`, bloques 20 d, 2000 resamples, `seed=12345` | **IC95% inferior > 0** |
| **C5** | **Régimen:** retorno de **cartera** de la política (serie promedio) en **cada uno** de los 4 regímenes vs `B1_score` | ≥ **−0.50 pp** en los cuatro (el umbral de T38 C2) |
| **C6** | **Sensibilidad:** el signo de C1 **y** el resultado de C2 se mantienen a **5 slots** | los dos |

**Por qué C2 pide las 20 y no la mediana:** se cablea **una** semilla y se elige **a ciegas**. Si el
resultado depende de cuál toca, no hay política validada — hay una apuesta. Y no es un umbral nuevo:
es **la afirmación central de la T21 promovida a criterio** (*"el ranking vivo rinde por debajo de la
banda entera del azar"*), que ya se cumplió 10/10 en las dos configs de fill (6.48 < 6.86 legacy;
1.97 < 2.46 honesto). Acá se la exige sobre 20 semillas y con los gates puestos.

**Por qué el PBO/DSR no son gate:** con 20 semillas de la **misma** política los brazos son
intercambiables por construcción, así que el PBO mide otra cosa. Además la T27 midió que es inestable
a la config (0.889 → 0.317 sin tocar un brazo) y la T13 que es grueso con brazos colineales. Se
reportan **descriptivos**, igual que en la T21.

**Casos partidos, resueltos ex ante:**

- **C1 pasa y C3 falla** (la política rinde más pero con drawdown materialmente peor) → **NO-SHIP**, y
  el cierre documenta **cuánto** drawdown compra el score. La dirección es genuinamente desconocida:
  en la T9 el score tenía **6,1 pts menos** de maxDD y en la T21 **4,2 pts más**. Por eso el umbral
  está declarado antes.
- **C1 pasa y C2 falla por 1-2 semillas** → **NO-SHIP.** Se reporta la fracción de semillas que ganan
  como **lead**: si la política es mejor en expectativa pero no siempre, eso es material para un
  pre-registro propio con la fracción declarada como criterio — no para cablearlo desde acá.
- **C1, C2, C3 pasan y C4 falla** → **NO-SHIP.** Precedente directo y del mismo harness: es
  exactamente lo que le pasó al alfabético en la T21 (p=0.071 legacy, 0.090 honesto).
- **`I_inverted` le gana a todo** → **NO se cablea nada de eso** (§4.3). Lead con pre-registro propio.
- **`P_fix` le gana a `N_rot`** → **no cambia el veredicto**: no es candidato (§2). Se reporta, y se
  reporta qué significa para la lectura del §4.2.
- **`B1_score` cae DENTRO de las dos bandas y C1 falla** → **NO-SHIP**, y el hallazgo es que **el
  déficit del score no sobrevive a la config honesta con gates**. Se documenta como caducidad parcial
  de la sexta medición convergente y el ranking queda como está. Es un cierre, no una postergación.
- **Falla cualquier sanity del §5** → **corrida INVÁLIDA**, sin veredicto. No se re-especifica nada
  para salvarla (precedente T26; la T34 ya pagó una).

## 7. Qué se cablea si pasa / qué NO se toca

**Si pasa las seis:**

- Flag `paper_ranking_mode` ∈ {`score`, `neutral_random`} con **default `neutral_random`** (el valor
  validado, mismo criterio que el §6 del pre-registro de la T21) + `paper_ranking_seed` con **default
  12345**, declarado en el §2 **antes** de correr.
- Cableado **como clave de orden únicamente**, en **las dos** estrategias que rankean candidatos —
  `generate_trades_analyze_single` (`strategies.py:449-456`, la que corre la cuenta viva) y
  `portfolio_engine` (`strategies.py:641-664`)— porque el defecto es idéntico y dejar una sin cablear
  crea el próximo desvío.
- **Lo que explícitamente NO cambia:** la clave de **sizing**. Una cuenta `vol_target` o
  `kelly_fractional` sigue dimensionando por `buy_score` (`strategies.py:502`); el flag toca el
  **orden**, no el **tamaño**. Está escrito así para que no se filtre. (La cuenta viva es
  `equal_weight`, así que ni siquiera usa el score para sizing — §0.)
- El `buy_score` **sigue computándose, mostrándose y persistiéndose** como `signal_score` de cada
  orden (regla 3): deja de **decidir**, no de existir.
- **Cambia comportamiento vivo** ⇒ se avisa explícitamente en el cierre, entra con tests de las dos
  estrategias, y el rollback es una línea (`paper_ranking_mode="score"`).

**Si no pasa:** NO-SHIP documentado, el engine intacto, y el `buy_score` queda anotado como
**no-validado para ranking** — que es donde ya lo dejó la T21.

**Fuera de alcance (declarado):** retirar la `vol_penalty` de la selección (idea derivada 2 de la
T21, vale ~1.6 pp/año, **pre-registro propio**); rediseñar el score; rankings alternativos (vol,
momentum, fuerza de entrada); el blend cross-sectional (KILLED en T05); la opción (b) de **invertir**
el score; sizing, gates de entrada, salidas y el overlay T20.

## 8. Qué NO se modela (caveats antes de correr)

- **Survivorship:** 127 sobrevivientes. Infla el nivel de **todos** los brazos por igual y no afecta
  la comparación, que es lo que decide. Pesa menos acá que en la T37: no se está sacando un guardrail.
- **Ventana de `analyze()`:** los artefactos PIT usan ventana expandida (250 → ~2.514 barras) contra
  las **504 fijas** del engine. **Matiz que sí importa acá:** es el único desvío que **no** aplica por
  igual a todos los brazos — si la ventana cambia el score, cambia el **baseline**; los brazos
  aleatorios no dependen del score. O sea que el nivel de `B1_score` es el único que lo hereda.
  Declarado, no corregido: regenerar cuesta horas y cuál ventana da mejor señal es otra pregunta.
- **Sampleo de ~15 min:** `touch` **sobre-dispara** respecto del engine y `close` **sub-dispara**; el
  engine queda entre los dos y más cerca de `touch` (26b). Es un nivel común a todos los brazos, y la
  T33 midió que cuando los brazos disparan barreras a la **misma** tasa —acá cambian el *orden*, no la
  regla de salida— el subsidio **se cancela en la comparación** y sólo mueve la escala.
- **El universo es la watchlist de hoy aplicada a 10 años** (T27) y el ratio de selección real (~55:1)
  es lo que hace que el ranking importe. Con ratios muy distintos el resultado no transfiere.
- **Sin overlay T20** (§3): el sizing por régimen que la cuenta **sí** corre no está en el harness.

## 9. Plan de ejecución

1. **Enabler en `scripts/run_ranking_t21.py`:** `--eval-mode` y `--live-gates`, con defaults que
   **preservan el veredicto publicado** (`close`, OFF) — mismo patrón con el que la T33 agregó
   `--fill-mode`.
2. **Helper de la política** (`analysis/rank_policy.py`): `neutral_rank(seed, fecha, ticker) -> float`
   en [0,1), **función pura** (hash `blake2b` de `f"{seed}|{fecha}|{ticker}"`), que es **la misma que
   se cablearía en el engine**. Tests: pureza e independencia del orden de llamada (§5.7),
   estabilidad entre corridas y uniformidad gruesa.
3. **Runner** `scripts/run_rank_neutral_t39.py`: los brazos del §2, la serie diaria promedio de la
   política (§4.1), el bootstrap pareado, el **retorno de cartera por ventana de régimen** (§6 C5 —
   **el mismo helper que la tarea 38 va a reusar**, así se escribe una vez), el AND de los seis
   criterios, cada caso partido del §6 y el banner de `harness_config.announce()`.
4. **Tests offline:** el helper del veredicto aplica el AND de los seis y **cada** caso partido; el
   sanity de reproducción (§5.2); el retorno por ventana de régimen cuadra con la curva de equity.
5. **Correr** a 10 slots + sensibilidad a 5, sin red, sin tocar `finanzias.db`.
6. **Veredicto** en `docs/rank_neutral_t39_<fecha>.md`, con **las dos bandas y el baseline al frente**
   — es el número que resume la tarea, se shipee o no.

**Congelado. Cualquier cambio a §2–§7 después de ver un resultado invalida el pre-registro.**
