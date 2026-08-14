# Pre-registro CONGELADO — Contra qué precio se decide la barrera (Tarea 26b, STOP-PRICE)

**Fecha:** 2026-08-14 · **Estado:** congelado ANTES de codear el harness (regla 2).
**Ref:** `docs/BACKLOG.md` tarea 26b · `docs/stop_cal_t26_2026-08-13.md` §4 (de dónde sale) ·
`docs/stop_cal_prereg_t26_2026-08-13.md` (la población y los criterios que se reusan) ·
`analysis/harness_config.py` (el desvío, declarado por la T32).

Fija población, brazos, la regla de decisión y los sanity **ANTES de correr**. Nada se re-decide
después de ver resultados. Si el candidato no supera el umbral, se documenta NO-SHIP y el engine
queda como está.

---

## 1. El problema (verificado en código, no asumido)

Las barreras ATR se deciden contra **precios distintos** en el harness y en producción:

| | quién decide | contra qué precio | dónde |
|---|---|---|---|
| **Harness** (T7/T23/T13/T21/T26) | `replay_cycle` | **close diario** | `atr_exit(current_price=close_i, …)` |
| **Engine vivo** | `run_scan` c/~15 min | **precio corriente intradía** | `get_bulk_prices` = *"current prices"*, `engine.py:627` |

Una barra cuyo **mínimo** perforó el nivel pero cuyo **close** se recuperó **no dispara en el harness
y sí en producción**. Lo que mantuvo el desvío invisible durante cinco tareas es que
`_exit_fill_price` **sí** modela el fill con open/low: está modelado el **fill**, no la **decisión**.

**Por qué esto no es una nota al pie:** la T26 midió que el stop **más ajustado** gana por +10.58 pp
de CAGR con mejor maxDD, con la curva monótona de punta a punta. Pero midió la regla del **close**,
que es más benigna, y la brecha entre las dos reglas **crece cuanto más ajustado el múltiplo** — o
sea que el resultado más fuerte de la serie está apoyado justo donde el desvío más pesa.

**La dirección del efecto es DESCONOCIDA y hay que decirlo antes de medir**, porque hay dos
argumentos opuestos y los dos son razonables:

- **A favor del close:** un stop al toque sale de nombres que cerraron **por encima** del nivel, o sea
  que realiza pérdidas en barras que se dieron vuelta. Es la definición de whipsaw.
- **A favor del toque:** en este harness **más stops = mejor** (T26: `S_1.0` con 36.7% de share es el
  mejor brazo, `S_off` con 0% el peor, y suprimir al azar costó −4.20 pp). Un stop al toque dispara
  **más** que uno confirmado al close con el mismo múltiplo, así que por esa vía podría ganar.

Cuál de los dos manda es empírico. **Objetivo:** medirlo, y de paso saber si la monotonía
"más ajustado gana" de la T26 **sobrevive bajo la regla que el engine realmente ejecuta** — que es lo
que decide si la pregunta del múltiplo queda cerrada o se reabre.

---

## 2. Población y config (CONGELADO — idénticas a la T26)

- **Universo:** `data/harness_universe_live_acct2.txt` (127 tickers).
- **Entradas:** eventos `analyze() = BUY` point-in-time (`data/pit_signals/`, `10y`, `warmup=250`).
  Son **143.096**.
- **Cartera:** `portfolio_sim`, `max_positions=10`, `initial_capital=50.000`, `cap_days=250`,
  `CostModel()`, `allow_reentry_while_open=False`, `tp_mult=4.0`, `period=14`, flip `analyze SELL`
  con Gate 2b, orden alfabético, sin overlay T20.
- **Sensibilidad reportada** a `--max-positions 5`, como en la T26. El veredicto se dicta a 10.

---

## 3. Los dos modos de evaluación (CONGELADO)

- **`close`** — lo que hacen hoy los cinco harness: la barrera dispara si el **close** cruzó el nivel.
- **`touch`** — la barrera dispara si el **extremo** de la barra cruzó el nivel: `low ≤ nivel` para
  stop y trailing, `high ≥ nivel` para el take-profit.

**Empate dentro de la misma barra (declarado ahora):** si en modo `touch` el mínimo perforó el stop
**y** el máximo perforó el TP, gana el **stop**. El OHLC no dice cuál pasó primero; se elige la
convención **adversa**, que es la conservadora.

**El bracket, declarado antes de correr:** el engine vivo samplea cada ~15 min, así que **no** ve el
mínimo exacto de la barra pero ve mucho más que el close. Su comportamiento real está **entre los dos
modos y más cerca de `touch`**. Ninguno de los dos ES el engine: `close` es la cota inferior de
frecuencia de disparo y `touch` la superior. **No se va a afirmar que un brazo reproduce producción**
— se afirma que la acotan. Modelar el sampleo de 15 min pediría datos intradía de 10 años que
yfinance no da (~60 días de 15m), y una interpolación tipo puente browniano metería un supuesto de
path que no se puede validar acá.

---

## 4. Brazos (CONGELADO)

**Rejilla de decisión — 2 modos × 5 múltiplos = 10 brazos.** Todo lo demás fijo.

| | 1.0 | 1.5 | 2.0 | 2.5 | 3.0 |
|---|:--:|:--:|:--:|:--:|:--:|
| **`touch`** | | | **BASELINE** | | |
| **`close`** | | | **candidato principal** | | |

- **BASELINE = `touch_2.0`.** Es la regla que el engine ejecuta hoy (múltiplo vivo, decisión al
  extremo). **No** es `close_2.0`, que es lo que midieron T7/T23/T13/T21/T26 — ése pasa a ser un brazo
  más. Éste es el cambio de referencia que la tarea introduce.
- **Candidato principal = `close_2.0`**: aislar el efecto de **la regla**, con el múltiplo vivo fijo.
- Los otros ocho responden la segunda pregunta: **¿sobrevive la monotonía de la T26 bajo `touch`?**

**Sanity del instrumento (no shipeables, miran el futuro):** se reusan los brazos de la T26 con el
sanity **corregido según su propia lección** —
- **`ORACULO_STOP`** (`stop_filter` con look-ahead a 20 ruedas) y
- **`AZAR_MISMA_TASA`** (supresión aleatoria a la misma tasa, `seed=20260813`),
ambos en modo **`touch`** y `stop_mult=2.0`.

---

## 5. Sanity del instrumento (si falla alguno, la corrida es INVÁLIDA)

1. **Contabilidad:** `|equity_curve[-1] − final_equity| / final_equity ≤ 1e-6` en todos los brazos.
2. **El instrumento ve CALIDAD de salida — contra el control igualado, no contra el baseline.**
   Ésta es la corrección directa del defecto que invalidó la T26 (§2 de su veredicto):
   `CAGR(ORACULO_STOP) ≥ CAGR(AZAR_MISMA_TASA) + 1.50 pp` **y**
   `maxDD(ORACULO_STOP) ≤ maxDD(AZAR_MISMA_TASA) − 5.00 pp`.
   Los umbrales salen de lo ya medido en la T26 en modo `close` (+2.33 pp y −11.1 pp) con margen
   holgado, porque acá se corre en modo `touch` y el efecto puede achicarse.
   **No se compara el oráculo contra el baseline:** ese fue exactamente el error de la T26 y no se
   repite.
3. **La regla muerde:** ≥ **10%** de los trades difieren (par `ticker`+`entry_date`) entre
   `touch_2.0` y `close_2.0`.
4. **Dominancia de disparo (invariante mecánica, se verifica por unit test sobre ciclos sintéticos,
   no en agregado):** para una misma posición abierta en una misma barra, todo disparo bajo `close`
   implica disparo bajo `touch` (`low ≤ close ≤ high`). En agregado **no** se exige monotonía: con
   slots finitos el path cambia y el share de cartera no tiene por qué ordenarse — se reporta como
   descriptivo.

---

## 6. Regla de decisión (CONGELADA)

**Candidato** = `close_2.0`. **Baseline** = `touch_2.0`. Se **cabla la confirmación al close sólo si
pasa las seis**:

| # | Criterio | Umbral |
|---|---|---|
| C1 | ΔCAGR = CAGR(close_2.0) − CAGR(touch_2.0) | ≥ **+0.50 pp** |
| C2 | **Riesgo, declarado al frente:** maxDD(close_2.0) | ≤ maxDD(touch_2.0) **+ 2.00 pp** |
| C3 | Block-bootstrap pareado sobre Δ(retorno diario), bloques 20d, 2000 resamples, `seed=12345` | **IC95% inferior > 0** |
| C4 | Sharpe(close_2.0) | ≥ Sharpe(touch_2.0) − **0.05** |
| C5 | **Robustez de régimen:** Δ(ret medio por trade) en cada uno de los 4 | ≥ **−0.05 pts** |
| C6 | **Consistencia a través del múltiplo:** el signo de `ΔCAGR(close − touch)` se mantiene ≥ 0 en **al menos 3 de los 5** múltiplos | ≥ 3/5 |

**C6 es el análogo de la coherencia dosis-respuesta de la T26**, adaptado a esta rejilla: si la
confirmación al close sólo ayuda en `2.0` y no en los otros cuatro múltiplos, es un punto de suerte y
no una propiedad de la regla. Se mide sobre los 5 pares, no sobre brazos vecinos.

**Casos partidos, resueltos ex ante:**
- **C1 pasa y C2 falla** → **NO-SHIP.** Confirmar al close retrasa la salida: si eso compra retorno
  con drawdown, es asumir más riesgo, no mejorar la regla.
- **C2 pasa y C1 falla** → **NO-SHIP** (no se cambia mecánica de salida por nada).
- **Si gana `touch` (ΔCAGR < 0 y significativo)** → también **NO-SHIP**, y es un resultado **positivo
  y publicable**: el engine ya está en la regla correcta, y **el desvío de la T32 pasa de "caveat" a
  "el harness mide peor de lo que opera"** — lo que reabre la pregunta del múltiplo de la T26 bajo la
  regla correcta, con pre-registro propio.

---

## 7. La segunda pregunta (descriptiva — NO decide, pero es el motivo por el que la tarea vale)

**¿Sobrevive bajo `touch` la monotonía "más ajustado gana" que midió la T26 bajo `close`?**

Se reporta la curva de CAGR/maxDD por múltiplo en los dos modos. Tres lecturas posibles, todas
declaradas ahora para que ninguna se acomode después:

- **Sobrevive** → el hallazgo de la T26 es real y la recalibración del stop merece re-abrirse (tarea
  nueva, pre-registro propio, ya con la regla correcta).
- **Se aplana o se invierte** → el `+10.58 pp` de la T26 era **artefacto del desvío**, la tarea 26
  queda cerrada del todo y la moraleja es que ningún harness de salida de esta serie puede leerse sin
  corregir el precio de evaluación.
- **Queda ambigua** → se documenta así y no se deriva nada.

Esto **no** es un criterio de ship. No se cabla ningún múltiplo desde esta tarea.

---

## 8. Qué se cablea si pasa / qué NO se toca

- **Si pasa:** flag `paper_atr_confirm_at_close` (default = el valor validado) en
  `paper_trading/gates.py` + `engine.py`: la barrera se evalúa contra el **último close diario
  cerrado** en vez del precio corriente. Toca la política de salida viva, así que se avisa
  explícitamente en el cierre. **La 26b no cambia `atr_stop_mult`** — sigue en 2.0 pase lo que pase.
- **Fuera de alcance (declarado):** desacoplar el trailing del stop (sigue sin `atr_trail_mult`, y la
  26 mostró que separarlo antes de resolver esto repetiría el error); el múltiplo; el TP; las
  entradas.

---

## 9. Qué NO se modela (caveats antes de correr)

- **El sampleo de 15 min del engine no se modela** — se lo acota (§3). Cualquier conclusión vale
  para el bracket, no para un punto.
- **`touch` sobre-dispara respecto del engine** (ve el mínimo exacto); **`close` sub-dispara**. Si el
  candidato gana, gana contra la cota **más exigente**, lo que es conservador; si pierde, parte de la
  pérdida puede ser artefacto de que `touch` es un techo — y hay que decirlo.
- **Survivorship** y **`auto_adjust=True`**: sesgan el nivel, no la comparación arm-vs-arm (mismas
  entradas en todos).
- **Sin overlay T20**, sin earnings-blackout: ortogonales.

---

## 10. Plan de ejecución

1. **Enabler:** `eval_mode ∈ {"close","touch"}` en `scaleout_replay.replay_cycle` (default
   `"close"` ⇒ **cero cambio** para T7/T23/T13/T21/T26) + paso por `simulate_portfolio`.
2. **Harness** `scripts/run_stop_price_replay_t26b.py`: rejilla 2×5 + los dos brazos de sanity,
   métricas de §4-§5, bootstrap pareado, aplica §6, banner de `harness_config.announce()`.
3. **Tests offline**: la invariante de dominancia §5.4 sobre ciclos sintéticos; el empate
   stop-vs-TP en la misma barra resuelve a favor del stop; `eval_mode="close"` reproduce byte-por-byte
   el comportamiento previo; el helper de veredicto aplica el AND de los 6 y los casos partidos.
4. **Correr** (10 slots + sensibilidad a 5), sin red, sin tocar `finanzias.db`.
5. **Veredicto** en `docs/stop_price_t26b_2026-08-14.md`.

**Congelado. Cualquier cambio a §2–§6 después de ver un resultado invalida el pre-registro.**
