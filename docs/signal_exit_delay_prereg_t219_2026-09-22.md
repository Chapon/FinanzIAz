# Pre-registro — Tarea 219 · DEMORAR la salida por señal (Gate 2b) · 2026-09-22

**CONGELADO antes de escribir una línea de código de brazos** (regla 2). Lo que sigue no
se toca después de correr; si hiciera falta, va como **enmienda fechada**, como las dos
del T37.

---

## 0. Qué se vio ANTES de congelar — declarado

No se congela a ciegas, y eso hay que decirlo para que el lector pese el resultado:

1. **El diagnóstico de la cuenta viva** (`docs/diagnostico_pnl_cuenta2_2026-09-21.md`):
   `analyze SELL` es el **59%** de las salidas (41 de 69), pierde **$2.127** y acierta
   **27%**. Eso **motivó** esta tarea. No es evidencia de nada por sí solo: es el
   resultado *condicionado a haber salido*, con n=69 y t=0,21.
2. **La tarea 7 ya midió el extremo de este eje** y su resultado se lee completo abajo
   (§1). Se fue a buscar **antes** de pre-registrar, justamente para no re-correr un
   experimento cerrado.
3. **El alcance de la reach del Gate 2b, medido sobre las salidas vivas:** de las 41
   salidas por señal, **40 (98%)** tienen score ≥ `bypass_score=0.25`, así que el gate de
   edad **sí las alcanza**. La única por debajo es una de 0,15. Rango 0,15–0,45, mediana
   **0,39**. Si el bypass disparara seguido, esta perilla no tendría palanca; tiene.

---

## 1. La pregunta, y por qué NO es la de la tarea 7

La T7 corrió el brazo **`C_A4`** (`sell_fraction=0.0`: *«la señal no vende, sólo salen
stop / TP / cap»*) sobre 41 tickers × 10y, 4025 entradas pareadas:

| | |
|---|---|
| Δ retorno medio | **+0,54 pts** |
| IC95% (bootstrap pareado) | **[+0,410, +0,666]** |
| PBO (CSCV) · DSR | **0,000** · **1,000** (gana in-sample 252/252) |
| tenencia media | **13,0 días vs 7,5** del baseline (**+73%**) |
| **veredicto** | **NO-SHIP** |

**El efecto es real y la selección robusta.** Lo que lo mató:

- **el kill-criteria de stress:** el efecto es **indistinguible de cero** en las tres
  ventanas de stress y de **signo negativo** en bear-2022 (−0,231, p(Δ≤0)=0,86);
- y, declarado allá como **post-hoc fuera del veredicto**, la **ocupación de slot**:
  ajustado por tiempo-capital el +0,536 se cae a **+0,088**.

La T33 re-leyó la T7 con el fill honesto y **aguantó**.

> **La pregunta de acá no es «¿conviene apagar la salida por señal?» — eso tiene
> veredicto. Es: ¿existe un punto INTERMEDIO que capture parte del +0,54 sin comprar los
> 13 días de tenencia que hundieron a C_A4?**

`paper_signal_sell_min_age_bdays` (Gate 2b, vivo en **3**) **nunca se barrió**: la T7 y la
T13 lo dejaron **fijo en 3** y ningún pre-registro lo movió. Es la única perilla de la
familia sin medir. **Demorar** la salida no es lo mismo que **eliminarla**: se mueve sobre
la misma curva dosis-respuesta que la T7 dejó medida —*«el SELL de señal destruye valor,
monotónicamente»*— pero sin el salto de ocupación.

---

## 2. Población y config (CONGELADO)

| | |
|---|---|
| universo | `data/harness_universe_live_acct2.txt` — **126 tickers** (watchlist de la cuenta 2 con artefacto PIT; sin PIT: ASML) |
| fingerprint de población | **`06ab64fc6448`** (`POPULATION_LIVE_ACCT2`). Si cambia, la corrida **no** es comparable con este pre-registro |
| período | `10y` (`ARTIFACT_PERIOD`), ventana rodante |
| señal | PIT precomputada, `data/pit_signals/*__10y__w250.json` |
| slots | **10** (`LIVE_MAX_POSITIONS`) — **no** los 5 de la T7 |
| asignación | `equal_weight` |
| barreras | hard stop **OFF**, trailing **2,0** ATR, TP **4,0** ATR (la política viva tras la T37/T53, que la T170 re-decidió NO MOVER) |
| escalado por régimen | **0,25** (`LIVE_REGIME_SCALE_FACTOR`) |
| `eval_mode` / `fill_mode` | `close` / `decision` (**el fill honesto de la T33**) |
| costos | el modelo de la cuenta 2: comisión per-share, slippage 5 bps |

**Declarado: la población NO es la de la T7** (126 tickers × 10 slots contra 41 × 5). Gana
poder, pero **los Δ de acá no son comparables número a número** con los de allá. C_A4 se
re-corre en esta población justamente para tener la referencia en la misma escala (§3).

---

## 3. Brazos (CONGELADO)

| brazo | `min_age_bdays` | rol |
|---|---:|---|
| `age3` | **3** | **baseline** — la política viva |
| `age5` | 5 | desafiante |
| `age10` | 10 | desafiante |
| `age20` | 20 | desafiante (≈ el `cap_days` global: cota superior útil del eje) |
| `C_A4_repl` | — (`sell_fraction=0`) | **referencia, NO desafiante** — re-corrida de la T7 en esta población, para saber cuánto del +0,54 hay disponible acá |
| `ORACULO_SALIDA` | — | sanity: el instrumento tiene que ver calidad, no cantidad |
| `AZAR_MISMA_TASA` | — | sanity: control igualado en tasa de diferimiento (la forma de la T164) |

**Brazos del gate anti-overfit: 4** (`age5`, `age10`, `age20`, y `C_A4_repl` cuenta porque
se mira su Δ). `bypass_score` queda **fijo en 0,25** en todos: mover dos perillas a la vez
haría indecidible cuál movió el resultado.

**Ningún brazo se agrega, se saca ni se re-nombra después de congelar.**

---

## 4. Regla de decisión (CONGELADA)

Sobre Δ = brazo − `age3`, y hacen falta **las cuatro**:

1. **ΔSharpe ≥ +0,10 o ΔCAGR ≥ +1 pp** de cartera (no en puntos acumulados — la lección
   de la lápida de la T8).
2. **maxDD no sube.**
3. **HEREDADO DE LA T7, y es el que mató a C_A4:** el efecto **no se apaga en las ventanas
   de stress** y **no cambia de signo en ninguna**. Sin esta mitad se estaría midiendo con
   una regla más laxa que la que ya rechazó al brazo vecino, que es la forma más barata de
   shipear un artefacto.
4. **PBO < 0,5** sobre los 4 brazos.

**Y se reporta la tenencia media de cada brazo AL LADO del Δ**, siempre, porque es la
variable que explicó el veredicto de la T7. Un brazo que gane Δ comprando +70% de
tenencia se lee distinto de uno que lo gane con +10%.

**DSR se reporta pero NO decide**, por el caveat de saturación por granularidad diaria que
la T9 dejó escrito y que la T20 volvió a ver (DSR=1,000 saturado).

---

## 5. Sanity del instrumento (si falla alguno ⇒ INVÁLIDA, sin veredicto)

1. **`ORACULO_SALIDA` tiene que ganar holgado.** Si un brazo que elige la salida mirando
   el futuro no se separa, el harness no ve diferencias de salida y nada de lo demás
   significa algo. Es la lección de la T9 y la T10, donde el oráculo atrapó un bug real.
2. **`AZAR_MISMA_TASA` tiene que dar ~0.** Difiere la misma **cantidad** de salidas que el
   mejor brazo, elegidas al azar. Si gana, lo que se está midiendo es *diferir*, no
   *diferir bien*.
3. **Monotonía esperada, declarada ANTES:** por la dosis-respuesta de la T7, el Δ debería
   ser **no decreciente** de `age3` a `C_A4_repl`. Si sale en U o desordenado, se sospecha
   del instrumento antes que del hallazgo — es exactamente lo que le pasó a la T23 con la
   curva del TP.
4. **Integridad de cartera:** equity-vs-cash cierra a 0,00% y el invariante de exits pasa
   en todos los brazos.

---

## 6. Qué NO se modela (caveats antes de correr)

- **Los dividendos los cobra el harness y no el motor vivo** — desvío `dividendos`
  (tarea 220/221, **2,54%/año** medido). Acá es **común a todos los brazos** y se cancela
  en el Δ, **salvo** por el tiempo en mercado: un brazo que retenga más cobra más
  dividendo. **Por eso la tenencia media va al lado del Δ** y no en un apéndice.
- **El blackout de earnings** (Gate 6, ±2d) no se modela — desvío `earnings_blackout`.
- **Los gates de re-entrada** (Gate 5 anti-whipsaw, 5b anti-churn) no se modelan — desvío
  `reentry_gates`.
- **El cap de liquidez por ADV** no se modela — desvío `adv_cap` (inerte a este capital).
- **El overlay de volatilidad** no se modela — desvío `vol_overlay`.

Los cinco los emite `deviations_keyed()` y van al banner de la corrida.

---

## 7. Qué se cablea si pasa / qué NO se toca

**Si pasa:** se cablea **sólo** `paper_signal_sell_min_age_bdays` al valor ganador, como
flag con default explícito y espejo `LIVE_*` (que es lo que le faltaba a `atr_tp_mult` y
dejó al harness modelando 4.0 por casualidad — tarea 185). Nada más.

**Si no pasa:** se documenta y **NO se shipea**, y el resultado negativo **vale igual**:
cierra el último eje sin medir de la familia de salidas y deja de ser una pregunta abierta
que vuelve cada vez que alguien mira el P&L por tipo de salida.

**No se toca en ninguno de los dos casos:** `sell_fraction` (tiene veredicto), las
barreras ATR (la T170 dijo NO MOVER), el escalado por régimen (T20, cableado) y
`bypass_score`.

---

## Enmienda 1 — 2026-09-22, ANTES de leer ningún Δ: se corre con artefactos atrasados

**Qué pasó.** El primer intento de corrida **abortó** por el guard de continuidad del
cohorte (tarea 140): los **126** frames `10y` terminan el **2026-09-09** mientras un frame
hermano del mismo ticker (`2y`) llega al **2026-09-21** — **8 sesiones** de atraso, sobre
una tolerancia de 5. El guard hizo exactamente su trabajo.

**Qué se decide, y por qué NO se refresca.** Se corre con `--allow-stale-artifacts` y la
ventana **queda la que este pre-registro congeló**. Refrescar el cohorte movería el
`start` y el `end` de la ventana, y con eso:

* habría que **re-anclar las constantes de reproducción**, que el propio guard avisa;
* y —más de fondo— **la población dejaría de ser la que acá se congeló**. El pre-registro
  fija la huella `06ab64fc6448`; correr sobre otra ventana hace que los Δ no sean
  comparables con lo que se pre-registró, que es justo lo que el pre-registro existe para
  evitar.

**Por qué es inmaterial acá, y no una excusa.** La ventana es de **10 años**. Perder las
últimas **8 sesiones** cambia el extremo derecho en ~0,3% del período. No hay ningún brazo
cuyo efecto viva en esas 8 ruedas: el eje que se mide es la **edad mínima de la salida por
señal**, con horizontes de 3 a 20 días sobre miles de ciclos repartidos en una década.

**Lo que esto sí cuesta, declarado:** las 8 ruedas que faltan son **las más recientes**, o
sea las más parecidas al presente. Si alguien quisiera leer este veredicto como *«y esto
vale para el mercado de esta semana»*, no puede. Vale para la década medida.

**Y lo que NO se toca:** el refresh, cuando se haga, va **sólo** por
`scripts/refresh_cohort.py`. A mano se pisan las `ARTIFACT_REFRESH_EXCEPTIONS` — ya costó
el histórico de AVB, irreversible.

---

## Enmienda 2 — 2026-09-22, tras un primer intento INVÁLIDO: entra un quinto sanity

**Qué pasó.** El primer intento corrió con `stop_mult=0.0` creyendo que era *«stop
apagado»*. El centinela es `NO_STOP = 1e9`; `0.0` pone el stop **en el precio de entrada**
y dispara ante cualquier baja. Resultado: **8.838** trades, tenencia **1,6 días**, CAGR
**−17,89%** y Sharpe **−1,76** en los **siete** brazos.

**Por qué esto obliga a una enmienda y no alcanza con arreglar el bug.** Los cuatro sanity
de §5 **pasaban**: el oráculo se separaba, la contabilidad cerraba y la curva seguía siendo
**monótona**. Los Δ entre brazos seguían pareciendo razonables. **El veredicto habría
salido sin que nada lo marcara**, sobre una cartera que perdía el 18% anual.

**El quinto sanity, y es DURO:** el baseline `age3` **es** el brazo `soff_t2.0` que la
**T170** publicó sobre esta **misma** población, misma ventana y misma config viva
(`ScaleOutParams()` por default es `min_age_bdays=3`). Así que tiene que reproducir su fila
publicada: **CAGR 8,78% · Sharpe 0,55 · 2531 tomados**, con tolerancias 0,5 pp / 0,05 /
2%. Si no reproduce ⇒ **INVÁLIDA, sin veredicto**.

**Y la referencia es EXTERNA a propósito.** Un sanity derivado de esta misma corrida habría
sido **ciego al defecto**, porque el bug afectaba a los siete brazos por igual — es
exactamente el defecto que las tareas **101** y **110** dejaron documentado (*«si la
referencia del guard sale de la misma población que chequea, es ciega al defecto
mayoritario»*). Los tres números van **clavados del doc publicado**, no derivados.

**Esta enmienda se declara ANTES de leer los Δ de la corrida válida.** Lo único que se vio
del primer intento son los números del baseline, que es lo que disparó la sospecha.

---

## 8. Plan de ejecución

1. Runner nuevo y chico que reuse `simulate_portfolio` + `cohort_bars` + el store PIT, con
   los brazos de §3 y los sanity de §5. **Tests offline del runner antes de correr.**
2. Verificar el fingerprint de población `06ab64fc6448` **antes** de leer cualquier Δ.
3. Correr, volcar el resultado a `docs/signal_exit_delay_t219_<fecha>.md` con el banner de
   desvíos completo.
4. Leer los sanity **primero**. Si alguno falla, no hay veredicto.
