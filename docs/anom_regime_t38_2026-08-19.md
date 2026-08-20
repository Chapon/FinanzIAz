# Veredicto — ANOM-REGIME (Tarea 38) · **CORRIDA INVÁLIDA por sanity §5.4 → sin veredicto**

**Fecha:** 2026-08-19 · **Pre-registro congelado:** `docs/anom_regime_prereg_t38_2026-08-19.md` (`8ac5459`)
**Runner:** `scripts/run_anom_regime_t38.py` · **Enablers:** `--eval-mode`/`--live-gates` en
`scripts/run_anomaly_replay_t11b.py`, `eval_mode` en `precompute_oracle_returns` (tarea 44).
**Comando:** `python scripts/run_anom_regime_t38.py` (determinista; `--json` para la salida completa).

**No se cablea nada.** La regla congelada dice que si falla un sanity **no hay veredicto** y no se
re-especifica nada para salvarlo (precedente T26; la T34 ya pagó una).

Población: **127 tickers** de la watchlist viva, señal **fija** `A_k2.0_m1.5` (el brazo de decisión de
T11b), **1.236 entradas**, `portfolio_sim` con 10 slots y `cap_days=20`, `eval_mode="touch"` +
`fill_mode="decision"` + `live_gates=True`. SPY en risk-off el **16,0%** de las ruedas.

| brazo | CAGR | Sharpe | maxDD | tomadas | qué es |
|---|--:|--:|--:|--:|---|
| `U_ungated` | **9.23%** | 1.02 | 12.9% | 1056 | **BASELINE — T11b tal cual, en config viva** |
| **`G_half`** | **8.04%** | 0.96 | 11.8% | 1056 | **CANDIDATO primario** (overlay de T20, 0.50 en risk-off) |
| `G_hard` | 5.34% | 0.72 | 15.9% | 938 | secundario (descriptivo) |
| `G_confirm` | 5.92% | 0.78 | 15.5% | 947 | secundario |
| `G_scale25` | 6.99% | 0.89 | 13.9% | 1056 | secundario |
| `V_oracle_entry` | 102.80% | 4.46 | 6.6% | 267 | sanity |
| `AZAR_TIME_MATCHED` | mediana 2.97% · **p95 5.97%** | — | — | — | Monte Carlo K=500 |

---

## 1. Por qué la corrida es inválida — y por qué la culpa es del pre-registro, no del instrumento

**Sanity §5.4 ("el gate muerde"): FALLA.** Pedía ≥10% de trades distintos **o** ≥10% del capital
desplegado. Medido: **0,0%** de trades distintos y **7,86%** de capital.

Los otros tres sanity **pasan y con margen**: contabilidad OK; el oráculo despega a 102.80% (**+93,57
pp** sobre el baseline, contra un mínimo de +20); y **el edge de T11b sobrevive a la config viva**
(9.23% contra un p95 del azar de 5.97%).

**El defecto está en cómo se especificó el criterio, y es estructural:**

- **La primera pata es imposible por construcción.** `G_half` **nunca bloquea** — su factor es 0.5, no
  0 — así que toma **exactamente los mismos 1056 tickets** que el baseline. `trade_diff ≡ 0` no es un
  resultado: es aritmética. El criterio quedó colgando de una sola pata.
- **La segunda pata es insensible por el diseño del simulador.** `portfolio_sim` **redespliega el cash
  liberado** en la próxima entrada, así que achicar una posición no reduce el capital total invertido a
  10 años: lo reasigna. Medido con el descriptivo que el runner reporta al lado: el gate **sí achicó el
  11,36% de las entradas** del candidato (7,53% del capital que desplegó), pero el agregado sólo se
  movió 7,86%.

O sea que **el gate mordió** —y bastante: ΔCAGR −1.19 pp con un bootstrap que lo confirma— pero el
criterio que existía para detectarlo no podía verlo. Es la lección de la T34 §7.5 otra vez
(*"auditar el instrumento no exime de verificar que la métrica del sanity mida lo que la frase dice"*),
sólo que esta vez el problema se anticipó **antes de correr** (está en el docstring de `gate_bites` y
en un test) y aun así **manda el criterio congelado**: la corrida es inválida.

---

## 2. LO QUE VALE MUCHO MÁS QUE EL VEREDICTO: la premisa de la tarea no se sostiene

La tarea existía porque T11b midió que la señal **falla sólo por régimen** — `bear_2022` −2.01
pts/trade, `2018Q4` −0.30, contra `bull_normal` +1.57. **Ese perfil no es una propiedad de la señal:
es una propiedad del universo de 41 tickers con el que se midió.**

Descomposición (mismo detector, mismo `k`/`m`, cuatro configs):

| config | CAGR | `bull_normal` | `2018Q4` | `covid_2020` | `bear_2022` |
|---|--:|--:|--:|--:|--:|
| **A** 41t/5sl, regla vieja *(= T11b publicada)* | 12.77% | +1.55 (n=379) | −0.30 (n=10) | **+1.71** (n=10) | **−2.01** (n=20) |
| **B** 41t/5sl, **regla viva** | 12.40% | +1.52 (n=382) | −0.28 (n=10) | **+2.29** (n=10) | **−2.54** (n=20) |
| **C** 127t/10sl, regla vieja | 11.76% | +1.12 (n=933) | −1.15 (n=19) | **−0.92** (n=22) | **+0.46** (n=63) |
| **D** 127t/10sl, **regla viva** *(= esta corrida)* | 9.23% | +0.91 (n=950) | −1.12 (n=20) | **−1.75** (n=23) | **+0.46** (n=63) |

(retorno medio **por trade** en pts, la misma métrica con la que T11b midió su fallo de régimen. La
config **A reproduce el veredicto publicado dígito por dígito**.)

**Lo que la tabla dice, leída por columnas:**

- **Modelar la regla del engine casi no mueve el perfil.** A→B y C→D cambian `eval_mode`, `fill_mode`
  y `live_gates` de golpe, y el signo de cada régimen **se mantiene**. Baja el nivel (−0.37 pp y
  −2.53 pp de CAGR), no la forma.
- **Cambiar la población lo da vuelta.** A→C sólo cambia universo y slots, y **dos de las tres
  ventanas de stress cambian de signo**: `bear_2022` pasa de **−2.01 a +0.46** y `covid_2020` de
  **+1.71 a −0.92**. La ventana que motivó la tarea entera es la que más se mueve.
- **Y el mecanismo está a la vista en los `n`:** con 41 tickers cada ventana de stress tenía **10-20
  trades**. Con 127 tiene 19-63. Triplicar la muestra da vuelta el signo en dos de tres. Eso no es un
  régimen que cambia: es **ruido de muestra chica** que se estabiliza.

**Consecuencia directa para el candidato: el gate estaba apuntado al régimen equivocado.** En la
config viva `bear_2022` es justamente donde la señal **gana** (+2.81% de retorno de cartera), y
condicionar por risk-off —que en 2022 estuvo prendido casi todo el año— le corta la exposición ahí.
Por eso el candidato **empeora** los dos regímenes que debía arreglar:

| régimen (retorno de **cartera**, cash = 0) | `U_ungated` | `G_half` | Δ | n trades |
|---|--:|--:|--:|--:|
| `bull_normal` | +132.39% | +119.02% | **−13.38 pp** | 950 |
| `stress_2018q4` | −2.56% | −3.45% | **−0.89 pp** | 20 |
| `stress_covid_2020` | −5.13% | −5.02% | +0.11 pp | 23 |
| `stress_bear_2022` | **+2.81%** | −0.30% | **−3.10 pp** | 63 |

**La métrica no es la explicación.** Por trade y por cartera **coinciden en signo en todas las celdas
de las dos configs**, así que el vuelco no viene de haber cambiado a la medición de cartera que el §4
del pre-registro introdujo — viene de la población.

---

## 3. Lo que sí sobrevive, y lo que queda en pie de la T11b

**Sobrevive el edge.** `U_ungated` da **9.23%** contra un p95 del azar time-matched de **5.97%**
(K=500). El sanity §5.3 —*"si el edge no está, no hay nada que condicionar y la tarea se cae sola"*—
**pasó**. La señal le sigue ganando al azar en el universo y la config vivos.

**No sobrevive el motivo publicado de su NO-SHIP.** T11b cerró NO-SHIP porque su criterio de robustez
de régimen exigía signo positivo o neutro en cada ventana y el brazo perdía en `bear_2022`. En la
config viva **ya no pierde ahí** — pierde en `covid_2020` y `2018Q4`. Sigue habiendo dos ventanas
negativas, pero **son otras**, y esa inestabilidad es el hallazgo: un criterio de régimen evaluado
sobre 10-63 trades por ventana **no tiene potencia para distinguir señal de ruido**.

Nota de corrección agregada a `docs/anomaly_signal_t11b_2026-07-23.md`. Abre las tareas **45**
(qué queda del veredicto de T11b) y **46** (el criterio de régimen no tiene potencia con señales de
baja frecuencia — y la **37**, que está en la fila, usa ese mismo criterio).

---

## 4. Los números del candidato, para que queden (descriptivos, sin veredicto)

Aunque la corrida es inválida, lo medido apunta en una sola dirección y conviene dejarlo escrito para
que nadie lo vuelva a correr esperando otra cosa:

| # | Criterio | Resultado |
|---|---|---|
| C1 | ΔCAGR ≥ 0.00 pp | **FALLA** — −1.19 pp |
| C2 | régimen: ≥ −0.50 pp en los 4 **y** estricto en bear/2018Q4 | **FALLA** — −3.10 y −0.89 pp |
| C3 | maxDD no empeora | pasa — −1.07 pp (*mejora*) |
| C4 | Sharpe ≥ base y > p95 del azar | **FALLA** — −0.059 |
| C5 | bootstrap pareado, IC95% inferior > −0.005 | **FALLA** — [−2.13, −0.44] pp, p=0.999 |
| C6 | PBO < 0.5 | pasa — 0.151 |
| C7 | C1 y el bear de C2 aguantan a 5 slots | **FALLA** — −0.92 pp y −3.27 pp |

Cinco de siete fallan, y el bootstrap dice con p=0.999 que el gate **destruye valor**. A 5 slots es
igual o peor. Los tres secundarios están todos por debajo del baseline (`G_hard` 5.34%, `G_confirm`
5.92%, `G_scale25` 6.99%), con dosis-respuesta monótona: **cuanto más agresivo el gate, peor** — que
es lo que se espera cuando se apaga exposición en el régimen donde la señal gana.

**Nada de esto es un veredicto.** Con el sanity fallado no se decide; se reporta.

---

## 5. Qué deja

- **El runner** `scripts/run_anom_regime_t38.py` con los cinco brazos de gate, el retorno de cartera
  por ventana de régimen, la métrica por trade al lado, el bootstrap, el PBO y el AND de los siete
  criterios (22 tests).
- **`--eval-mode` / `--live-gates` en el runner de T11b**, con defaults que preservan su veredicto.
- **Tarea 44 (ORACLE-EVALMODE)**, encontrada al cablearlo y arreglada: `precompute_oracle_returns`
  tenía `fill_mode` (T33) pero no `eval_mode` (26b), así que un harness con los brazos en `touch`
  tenía el oráculo puntuando al `close`. Ningún veredicto publicado afectado — la 38 es el primero
  que corre en `touch`.
- **La lección del §1** en la skill `backtest-replay-harness`: cómo especificar *"el brazo muerde"*
  cuando el brazo **escala** en vez de bloquear.
