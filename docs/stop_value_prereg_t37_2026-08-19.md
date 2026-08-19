# Pre-registro CONGELADO — ¿El stop duro aporta sobre el trailing y el flip de señal? (Tarea 37, STOP-VALUE)

**Fecha:** 2026-08-19 · **Estado:** congelado ANTES de codear el harness (regla 2).
**Ref:** `docs/BACKLOG.md` tarea 37 · `docs/stop_loosen_t34_2026-08-18.md` §3-§4 (de dónde sale,
y el mandato de C6) · `docs/stop_loosen_prereg_t34_2026-08-18.md` (población, walk-forward y
criterios que se reusan) · `analysis/harness_config.py` (los seis desvíos declarados).

Fija población, brazos, el test de survivorship, la regla de decisión y los sanity **ANTES de
correr**. Nada se re-decide después de ver resultados. Si el candidato no supera el umbral, se
documenta NO-SHIP y la política de salida viva queda como está.

---

## 0. Qué se miró ANTES de congelar — y qué se evitó a propósito

Auditoría del instrumento previa al congelamiento (§2 y §3 salen de acá). Lo que se corrió:

- **Mezcla de salidas real** por brazo, con retorno medio y peor trade por tipo de salida.
- **Cola** por brazo: peor trade, p1 y p5 de retorno por trade.
- **Condición de activación del trailing** y ausencia de `atr_trail_mult` en el engine
  (leído en `paper_trading/gates.py` y en `~/.finanzias/settings.json`).
- **Tasa base de eventos casi-terminales** dentro del universo (§3).

**Lo que ya era público antes de esta tarea:** el CAGR del brazo *stop duro OFF + trail 2.0*
(**9.17%**) está publicado en el §4 del veredicto de la T34, igual que la rejilla acoplada
entera. Eso es el lead y por eso existe la tarea.

**Lo que deliberadamente NO se miró:** **CAGR, Sharpe y maxDD de los brazos nuevos de la
rejilla 2-D** (todo lo que combina un stop duro *ancho* con un trailing propio: `4.0×2.0`,
`6.0×2.0`, `3.0×3.0`, etc.) y **cualquier resultado con ruina inyectada**. De los brazos
nuevos sólo se miraron contadores mecánicos (trades, mezcla de salidas, cola).

---

## 1. La pregunta, reencuadrada

La T34 midió que apagar el stop rinde mucho más que el múltiplo vivo y **no lo cabló**, porque
un máximo en el borde de una rejilla no es un óptimo: C6 mandó abrir esta tarea. Pero la
pregunta **no** es *"¿stop sí o no?"*. La T34 dejó medida la descomposición:

| brazo | CAGR |
|---|--:|
| stop 2.0 **y** trail 2.0 (lo vivo, un solo knob) | 2.01% |
| stop **off**, trail 2.0 | **9.17%** |
| stop off **y** trail off | 9.52% |

Apagar **sólo el stop duro** recupera 7.16 de los 7.51 pp. Así que la pregunta que decide
plata es:

> **¿El stop duro desde el precio de entrada aporta algo por encima del trailing desde el
> máximo y del flip de señal — o sólo convierte caídas recuperables en pérdidas realizadas?**

Es una pregunta **mucho menos radical** que "sacar el stop": el candidato conserva dos
barreras, y una de ellas (el flip) resulta ser la dominante (§2).

## 2. Lo que la auditoría del instrumento encontró (medido, pre-freeze)

**(a) La barrera dominante no es el stop — es el flip de señal.** Mezcla real de salidas,
10 slots, `touch`, gates vivos:

| salida | vivo (stop 2.0) | | stop OFF + trail 2.0 | |
|---|--:|--:|--:|--:|
| | share | ret medio | share | ret medio |
| `signal_full` (flip `analyze SELL`) | **56.9%** | +0.50% | **76.1%** | −0.84% |
| `atr_stop` | 20.1% | **−5.98%** | 0.0% | — |
| `atr_trail` | 12.4% | −0.22% | 13.2% | −0.53% |
| `atr_tp` | 10.2% | +10.18% | 10.4% | +10.20% |
| `cap_reached` | 0.3% | +5.09% | 0.3% | +4.45% |

Los **565 trades** que el stop duro corta pierden **−5.98%** promedio. Sin él, esa población
se absorbe casi entera en `signal_full`.

**(b) La cola casi no cambia.** Es el dato que más incomoda a la hipótesis de que el stop
protege:

| brazo | peor trade | p1 | p5 |
|---|--:|--:|--:|
| vivo (stop 2.0 = trail 2.0) | −36.2% | −12.1% | −7.0% |
| stop OFF, trail 2.0 | −35.1% | −13.2% | −7.2% |
| stop 4.0, trail 2.0 | −38.4% | −13.7% | −7.6% |
| stop OFF, trail OFF | −37.6% | −13.6% | −7.7% |

El peor trade **con** stop duro (−36.2%) es **peor** que el peor trade sin él (−35.1%). En
esta muestra el stop duro no está comprando protección de cola; está cortando el medio de la
distribución.

**(c) El trailing tiene un agujero declarado:** sólo se activa cuando
`hwm > avg_cost + 1.0×ATR` (`gates.py:117`). Una posición que **nunca sube 1 ATR sobre la
entrada** no tiene trailing. Si además se apaga el stop duro, esa posición queda con **una
sola** barrera: el flip de señal (o el cap de 250 ruedas). Hay que medir cuántas son y cómo
les va — es el punto débil estructural del candidato.

**(d) Shipear cualquier brazo de esta tarea requiere un flag nuevo.** El engine tiene **un
solo** knob: `gates.py:101` y `:103` usan el mismo `stop_mult` para el stop duro y para el
trailing, y **no existe `atr_trail_mult`** en `~/.finanzias/settings.json`. El desacople es
código nuevo en la política de salida viva, y eso sube la vara (§8).

## 3. Survivorship — de caveat que invalida todo a umbral decidible (el núcleo de la tarea)

**El problema:** los 127 tickers son la watchlist **viva** en 2026 con 10 años de historia.
Por construcción **ninguno quebró, ninguno fue deslistado, ninguno fue a cero**. Apagar el
stop duro es precisamente la política que un universo así favorece de manera artificial: en
la vida real la protección se paga en el nombre que no vuelve, y en esta muestra **ese nombre
no existe**. La T34 lo declaró como la advertencia central y por eso no cabló nada.

**No se puede corregir con los datos que hay** (yfinance gratis no da deslistadas usables, y
regenerar PIT para nombres muertos cuesta horas sin garantía de cobertura). Así que en vez de
corregirlo, se lo **acota**, y la cota se vuelve criterio.

**La tasa base, medida DENTRO del universo** (cota inferior, porque son sobrevivientes):
un evento = caída ≥ *d* desde el máximo móvil de 252 ruedas que **no** recupera ni la mitad
del pico en las 252 ruedas siguientes.

| profundidad | eventos | tasa | tickers distintos |
|---|--:|--:|--:|
| ≥ 50% | 33 en 1.267 ticker-años | **2.60%/año** | 27 de 127 |
| ≥ 70% | 6 en 1.267 ticker-años | **0.47%/año** | 5 de 127 |

**El test (CONGELADO): inyección de ruina.** Se modifican **los datos**, no el motor, así que
**todos los brazos ven exactamente el mismo mundo** y la comparación sigue siendo pareada:

- Con hazard `r/252` por rueda, cada ticker puede entrar en un **evento terminal** en una
  fecha sorteada. Desde esa barra, el precio cae **linealmente en log** hasta `−d` a lo largo
  de **20 ruedas** y después queda plano hasta el final de la serie.
- **Forma `gradual` (20 ruedas) es la que decide.** Es la **más favorable al stop duro**: le
  da veinte barras para dispararse. Usar una caída de una sola barra (gap) rigearía el test a
  favor del candidato, porque ahí ninguna barrera salva nada.
- **Forma `gap` (1 rueda) se reporta como sensibilidad**, no decide.
- Las **señales PIT no se regeneran**: el evento es, por construcción, **invisible para
  `analyze()`**. Es realista para fraude/quiebra y es **conservador para el candidato**,
  porque le saca al flip de señal —su barrera dominante— la posibilidad de reaccionar.
- `seed=20260819`, tres semillas (`+0/+1/+2`) y se reporta el promedio; el criterio se aplica
  al **peor** de las tres.
- Rejilla de tasas: `r ∈ {0, 0.5, 1, 2.6, 5, 10}%/año` a `d=50%`, y `r ∈ {0, 0.47, 1, 2}%` a
  `d=70%`. Se reporta la **tasa de ruina de breakeven**: a partir de qué `r` el candidato
  deja de ganarle al baseline.

## 4. Población y config (CONGELADO — idénticas a la T34)

- **Universo:** `data/harness_universe_live_acct2.txt` (127 tickers con PIT).
- **Entradas:** `analyze() = BUY` point-in-time (`data/pit_signals/`, `10y`, `warmup=250`) —
  **143.096**, entre 2017-07-07 y 2026-08-06.
- **Cartera:** `portfolio_sim`, `max_positions=10`, `initial_capital=50.000`, `cap_days=250`,
  `CostModel()`, `allow_reentry_while_open=False`, `tp_mult=4.0`, `period=14`,
  `trail_min_excess_atrs=1.0`, flip `analyze SELL` con Gate 2b, orden alfabético, sin overlay T20.
- **`eval_mode="touch"`, `fill_mode="decision"`, `live_gates=True`** — la regla viva, el fill
  honesto y los gates de re-entrada del engine modelados (T33 + T34).
- **Sensibilidad** a `--max-positions 5`. El veredicto se dicta a **10**.

## 5. Brazos (CONGELADO)

**Rejilla 2-D — stop duro × trailing, desacoplados. 5 × 3 = 15 brazos.**

| stop duro ↓ / trail → | 2.0 | 3.0 | `off` |
|---|:--:|:--:|:--:|
| **2.0** | **BASELINE (= lo vivo)** | | |
| 3.0 | | | |
| 4.0 | | | |
| 6.0 | | | |
| **`off`** | | | |

- **BASELINE = `stop 2.0 / trail 2.0`**, que es exactamente la config viva (un solo knob).
- **`off` en el eje del stop duro es un brazo legítimo, no un artefacto de borde.** Ésta es
  la diferencia con la T34: allá el borde señalaba una pregunta sin responder, y la pregunta
  **es ésta**. Por eso **C6 de la T34 (máximo interior) NO se reusa**; su función —evitar que
  el survivorship regale el resultado— la cumple ahora **C9**, que ataca la causa en vez del
  síntoma.
- **`off` en el eje del trailing** se corre para tener el control de "sin ninguna barrera
  ATR", pero **no es shipeable**: dejaría la política de salida colgando de un solo mecanismo.
- **CANDIDATO = el brazo que elige el walk-forward** del §6, no se nombra acá.

**Descriptivos (no deciden):** por brazo se reporta la fracción de trades que **nunca activan
el trailing** (§2c) y su retorno medio — la población que quedaría con una sola barrera.

## 6. Walk-forward de la selección (CONGELADO — idéntico a la T34 §6)

5 folds anclados y expandidos, embargo de 365 días corridos, selección por **mayor CAGR en el
train**, equity OOS **encadenada**, comparada contra el baseline fijo sobre los mismos bloques.

| fold | train (entradas con `entry_date` <) | test OOS |
|---|---|---|
| 1 | 2020-08-01 | 2021-08-01 → 2022-07-31 |
| 2 | 2021-08-01 | 2022-08-01 → 2023-07-31 |
| 3 | 2022-08-01 | 2023-08-01 → 2024-07-31 |
| 4 | 2023-08-01 | 2024-08-01 → 2025-07-31 |
| 5 | 2024-08-01 | 2025-08-01 → 2026-07-31 |

Se reusa tal cual —mismos folds, mismo embargo, misma regla— para que el resultado sea
comparable con el de la T34 y para no re-especificar nada que ya funcionó. **Limitación
heredada y declarada:** de los tres regímenes de stress, los bloques OOS sólo contienen
`stress_bear_2022`; por eso C5 se mide **in-sample sobre los cuatro**.

## 7. Sanity del instrumento (si falla alguno, la corrida es INVÁLIDA y no hay veredicto)

1. **Contabilidad:** `|equity_curve[-1] − final_equity| / final_equity ≤ 1e-6` en todos los brazos.
2. **El instrumento ve calidad de salida — contra el CONTROL IGUALADO, no contra el baseline**
   (lección T26): `CAGR(ORACULO_STOP) ≥ CAGR(AZAR_MISMA_TASA) + 1.50 pp` **y**
   `maxDD(ORACULO_STOP) ≤ maxDD(AZAR_MISMA_TASA) − 5.00 pp`. Mismos brazos que la 26b/T34.
3. **Control mecánico:** los brazos con `stop off` tienen `atr_stop` share **== 0.0** exacto,
   y los de `trail off` tienen `atr_trail` share **== 0.0** exacto.
4. **El desacople muerde:** ≥ **10%** de los trades difieren (par `ticker`+`entry_date`) entre
   `stop 2.0 / trail 2.0` y `stop off / trail 2.0`. Mismo umbral y mismo helper
   (`trade_overlap`) que la 26b §5.3 y la T34 — **no** se calibra uno nuevo.
5. **La inyección de ruina hace daño y es monótona:** a `d=50%`, el CAGR del **baseline** cae
   de forma **no creciente** al subir `r` en la rejilla de tasas, y en `r=10%` cae al menos
   **2.00 pp** respecto de `r=0`. Si inyectar ruina no lastima, la inyección está mal cableada
   y el test del §3 no mide nada.
6. **La inyección es idéntica para todos los brazos:** las series modificadas se generan
   **una vez** por `(r, d, forma, seed)` y se comparten. Se verifica por hash de las barras.

## 8. Regla de decisión (CONGELADA)

**Candidato** = el brazo del §6. **Baseline** = `stop 2.0 / trail 2.0` (lo vivo). 10 slots.
Se cablea **sólo si pasa las nueve**:

| # | Criterio | Umbral |
|---|---|---|
| **C1** | ΔCAGR **fuera de muestra** (cadena OOS) | ≥ **+1.00 pp** |
| **C2** | maxDD, **in-sample Y** en la cadena OOS | ≤ base + **1.00 pp** |
| **C3** | Block-bootstrap pareado sobre Δ(retorno diario), bloques 20 d, 2000 resamples, `seed=12345` | **IC95% inferior > 0** |
| **C4** | ΔSharpe | ≥ **+0.05** |
| **C5** | **Régimen:** Δ(ret medio por trade) en cada uno de los **4** | ≥ **−0.05 pts** |
| **C6** | **COLA:** Δ(peor trade) **y** Δ(p1 de retorno por trade) | ≥ **−2.00 pp** cada uno |
| **C7** | Estabilidad: mismo brazo en ≥ **4 de 5** folds | ≥ 4/5 |
| **C8** | Especificación: signo de ΔCAGR ≥ 0 **(a)** a 5 slots y **(b)** en modo `close` | las dos |
| **C9** | **RUINA:** ΔCAGR(candidato − baseline) ≥ **0** con inyección `gradual` a **`r=2.60%`/`d=50%`** **y** a **`r=0.47%`/`d=70%`**, en la **peor** de las tres semillas | las dos |

**C6 reemplaza al C6 de la T34** (máximo interior) y mide otra cosa: acá el borde es un
candidato legítimo, así que lo que hay que proteger no es la forma de la curva sino **la
cola**, que es para lo que existe un stop. El umbral de −2.00 pp es holgado a propósito: la
auditoría ya mostró que las colas están dentro de ~1,5 pp entre brazos, así que C6 no puede
pasar "de casualidad" ni bloquear por ruido.

**C9 es el criterio central de la tarea.** Los umbrales **no son inventados**: son las tasas
medidas **en el propio universo** (§3), y son **cotas inferiores** de la tasa real porque la
muestra es de sobrevivientes. Exigir que el candidato aguante ahí es exigir que aguante en un
mundo **al menos tan malo** como el que la propia muestra ya muestra.

**Casos partidos, resueltos ex ante:**

- **Todo pasa menos C9** → **NO-SHIP**, y es el resultado más informativo posible: significa
  que la ventaja del candidato **es** el survivorship. Se publica la **tasa de ruina de
  breakeven** como el número que resume la tarea.
- **C1 pasa y C2 o C6 fallan** → **NO-SHIP.** Más retorno con más drawdown o con peor cola
  en el knob de riesgo es asumir riesgo, no mejorar la regla.
- **El walk-forward elige el BASELINE** (`2.0/2.0`) → **NO-SHIP** y resultado **positivo**: el
  stop duro se gana su lugar y la serie 26→26b→34→37 queda cerrada.
- **El walk-forward elige `trail off`** → **NO-SHIP por construcción** (§5: no es shipeable),
  y se reporta como evidencia de que el instrumento premia no tener barreras, lo que refuerza
  la lectura de survivorship.
- **Falla cualquier sanity del §7** → **corrida INVÁLIDA**, sin veredicto. No se re-especifica
  nada para salvarla (precedente T26, y T34 ya pagó una).

## 9. Qué se cablea si pasa / qué NO se toca

- **Si pasa las nueve:** flag nuevo **`atr_trail_mult`** en `paper_trading/gates.py` +
  `engine.py` (hoy `stop_mult` gobierna las dos barreras) y, si el candidato lleva el stop
  duro apagado, **`atr_hard_stop_enabled`**. Default = el valor validado, en la cuenta viva 2.
  **Es un cambio de política de salida EN VIVO y código nuevo en el gate**, así que se avisa
  explícitamente en el cierre y se shipea con tests del gate, no sólo del harness.
- **Consecuencia de display, declarada:** el R:R implícito de cada BUY
  (`gates.entry_risk_levels` = `tp_mult/stop_mult`) queda **indefinido** si el stop duro se
  apaga. Hay que decidir qué mostrar — probablemente el nivel del trailing proyectado o
  ningún R:R — y eso es parte del alcance del ship. **Display-only**, no filtra (regla 3).
- **NO se toca:** `atr_tp_mult` (4.0, cerrado en T23); `trail_min_excess_atrs` (1.0 — mueve el
  agujero del §2c y es **otra** pregunta, con pre-registro propio); `paper_atr_confirm_at_close`
  (NO-SHIP en 26b); los gates 5/5b (se modelan, no se cambian); entradas; sizing; overlay T20.

## 10. Qué NO se modela (caveats antes de correr)

- **El sampleo de ~15 min del engine** — acotado entre `close` y `touch`, por eso C8(b).
  `touch` sobre-dispara, así que sesga **a favor** de apagar barreras: el candidato tiene que
  ganar en las **dos** cotas.
- **Survivorship** — no se corrige, se **acota** (§3) y la cota es C9. Sigue siendo el
  supuesto más fuerte de la tarea y hay que decirlo en el veredicto pase lo que pase.
- **La ruina inyectada es sintética.** Su forma (log-lineal en 20 ruedas), su profundidad y su
  independencia entre nombres son supuestos. En una crisis real la ruina **correlaciona**, y
  eso perjudicaría al candidato más que este modelo — o sea que el test es, también por ese
  lado, optimista respecto de apagar el stop.
- **Ventana de `analyze()`** — desvío #3 de la T27, ortogonal a este eje.
- **Sin overlay T20** y sin earnings-blackout (los SELL forzados por ATR lo bypassean en vivo).

## 11. Plan de ejecución

1. **Enabler `inject_ruin`** (módulo nuevo, lógica pura): dada `bars_by`, una tasa, una
   profundidad, una forma y una semilla, devuelve `bars_by` modificado + el registro de
   eventos. Determinista. **No toca el motor**, así que todos los brazos comparten mundo.
2. **Enabler `trail_mult` de punta a punta:** ya existe en `AtrParams` (`effective_trail_mult`)
   y `replay_cycle` lo respeta; verificar que `portfolio_sim` lo pase sin recortarlo y dejar
   test.
3. **Runner** `scripts/run_stop_value_t37.py`: rejilla 5×3, los dos brazos de sanity, el
   walk-forward del §6, el barrido de ruina del §3, el bootstrap, el AND de los nueve
   criterios y el banner de `harness_config.announce()`.
4. **Tests offline:** la inyección es determinista y reproducible por semilla; el evento cae
   dentro del rango de fechas del ticker; la forma `gradual` llega a `−d` exactamente en 20
   ruedas; `r=0` devuelve las barras **idénticas**; todos los brazos reciben el mismo objeto;
   el helper del veredicto aplica el AND de los nueve y **cada** caso partido del §8; el
   desacople `trail_mult` no se pisa con `stop_mult`.
5. **Correr** (10 slots + sensibilidad a 5), sin red, sin tocar `finanzias.db`.
6. **Veredicto** en `docs/stop_value_t37_<fecha>.md`, con la **tasa de ruina de breakeven**
   al frente pase lo que pase — es el número que resume la tarea aunque el veredicto sea
   NO-SHIP.

**Congelado. Cualquier cambio a §4–§9 después de ver un resultado invalida el pre-registro.**
