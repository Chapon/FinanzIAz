# Tarea 27 (HARNESS-CFG) — Alinear la config de los harness con la cuenta viva · **CERRADA**

**Fecha:** 2026-08-12 · **Ref:** `docs/deep_analysis_2026-08-12.md` §1 · **Gate técnico/metodológico:
no toca decisiones de trading.**

**Resultado en una línea: la config mueve el resultado muchísimo — la tarea 28 queda disparada.**
El NO-SHIP de la T23 era **dependiente de la config**: el criterio que lo mató (`PBO 0.889`) **pasa**
con la config de la cuenta viva (`PBO 0.317`), aunque el veredicto se sostiene por **otro** criterio.

---

## 1. Qué se arregló

Los harness no leen `paper_accounts` —y está bien— pero entonces *"¿contra qué cuenta?"* se traduce
en *"¿con qué config?"*, y la que usaban era la de la **cuenta 1, pausada desde el 2026-07-01**.

- **`analysis/harness_config.py`** — fuente única de la config viva (`LIVE_MAX_POSITIONS=10`,
  cuenta 2, `auto`, `equal_weight`). Los 7 runners de cartera toman de ahí el default de
  `--max-positions`; **ya no hay literales clavados** (test de regresión que falla si vuelven).
- **`announce(...)`** — cada runner imprime su config y **nombra los desvíos** antes de simular. El
  objetivo no es que todo coincida a la fuerza, sino que **coincida o que el desvío esté escrito**.
  Si el default nuevo no reproduce el veredicto publicado, el banner lo avisa solo.
- **`data/harness_universe_live_acct2.txt`** (127 tickers) + `scripts/refresh_live_universe.py`
  (lectura `mode=ro`, mismo patrón que `refresh_sp500_fallback.py` de UNIV1).

**Dos correcciones al enunciado, medidas:**

1. **Son 7 scripts, no 8.** `run_scaleout_replay_t7.py` no usa `portfolio_sim` (corre con capital
   ilimitado; es anterior a que R2 lo creara) y por eso no tiene `--max-positions`.
2. **La pata del universo NO era cara.** El enunciado asumía que había que declarar el caveat o
   regenerar artefactos. Medido: **127 de los 128 tickers de la watchlist viva ya tienen artefacto
   PIT** (falta sólo ASML) — herencia de la corrida del S&P 500 de la T12. El universo vivo estaba
   disponible desde el principio, sin regenerar nada.

**El desvío que queda vivo y se declara** (no se corrige acá): `data/pit_signals/` se generó con
ventana **expandida** (250 → ~2.514 barras) mientras el engine le pasa a `analyze()` **504 barras
fijas** (`paper_history_period="2y"`). Cambian el train set del XGBoost, el fit de GARCH, el detector
de régimen y el warm-up de SMA200. Regenerar cuesta horas y **cuál ventana produce mejor señal es
otra pregunta, con pre-registro propio**.

---

## 2. La medición: sensibilidad de la T23 a la config

Mismo harness (`run_tp_cal_replay_t23.py`), mismos brazos, **mismos kill-criteria congelados**.
Lo único que cambia es la config de cartera.

| config | BASE CAGR | Sharpe | tomad. | ΔCAGR del candidato | **PBO** | criterio que FALLA |
|---|---|---|---|---|---|---|
| **5 slots · 41 tickers** (el publicado) | 18.60% | 0.90 | 1337 | +1.25pp | **0.889** | PBO |
| **10 slots · 41 tickers** | 12.65% | 0.74 | 2729 | **+3.75pp** | **0.460** | régimen (2018Q4 −0.17) |
| **10 slots · 127 tickers** (config viva) | 11.94% | 0.71 | 2638 | **+3.06pp** | **0.317** | régimen (2018Q4 −0.46) |

El veredicto **sigue siendo NO-SHIP en las tres**, pero **por razones distintas**, y el tamaño del
efecto **se triplica**. Tres consecuencias:

### 2.1 El PBO de la T23 era un artefacto de la config

`PBO 0.889 → 0.460 → 0.317` **sin tocar ni un brazo ni un criterio**: sólo cambiando cuántos slots
hay. El estadístico que decidió aquel NO-SHIP se movió 57 puntos por una variable que el
pre-registro ni siquiera declaraba. Es evidencia dura para la nota metodológica que dejó la T13:
**CSCV con pocos brazos colineales no es sólo grueso, es inestable a la config** — y refuerza que el
gate correcto para refinar un parámetro contra su baseline es el **block-bootstrap pareado**.

### 2.2 Lo que ahora falla es la robustez de régimen, y empeora con el universo vivo

Con 10 slots aparece un déficit en `stress_2018q4` (−0.17 pts con 41 tickers, **−0.46 con 127**)
que a 5 slots no existía (+0.02). O sea que el candidato sin-TP **no está limpio**: la T23 lo
mataba por sobreajuste y la config viva lo mata por comportamiento en stress. La conclusión
"no se cabla" **no cambia**; lo que cambia es qué habría que investigar si alguien lo retomara.

### 2.3 Hallazgo lateral, descriptivo y no pre-registrado: **más slots rinden menos**

El **baseline mismo** cae de **18.60% a 12.65%** de CAGR al pasar de 5 a 10 slots (Sharpe 0.90 →
0.74), con el maxDD **peor**, no mejor (36.7% → 39.1%). Con el universo vivo, 11.94%. No es
selección —no hay `rank_score`, el orden es alfabético— es **concentración**: con 5 slots cada
posición es el 20% del cash y con 10 el 10%, y sobre una población de expectativa positiva
concentrar compone más rápido. La diversificación extra **no compró reducción de drawdown**.

**Esto NO es una recomendación de bajar los slots de la cuenta 2.** Sale de una corrida de
sensibilidad sin pre-registro, sobre una población sintética, con equal-weight y sin el overlay de
régimen T20 que la cuenta viva sí tiene. Queda anotado como **tarea nueva candidata** (§4): el
número de slots nunca se validó, se heredó.

---

## 3. Kill-criteria (gate técnico) — cumplidos

| criterio | resultado |
|---|---|
| Suite Windows verde | **1557 passed, 3 skipped** (25 tests nuevos) |
| Corrida de sensibilidad a 5 y 10 slots que muestre cuánto mueve | **Hecha** — mueve mucho (§2) |
| Si mueve poco, los veredictos viejos quedan firmes; si mueve, dispara la 28 | **Dispara la 28** |

**Qué NO se re-decidió (regla 2):** la T23 cerró con su kill-criteria congelado y **no se toca**.
Esto es una medición de sensibilidad, no un re-veredicto: la T23 sigue cerrada NO-SHIP y
`atr_tp_mult=4.0` sigue como está. Re-correrla en serio con la población viva es la **tarea 28**, y
necesita **pre-registro propio**.

**Qué conclusiones de la serie se mueven y cuáles no** (confirmado por la medición): se mueven las
que dependen de escasez de slots — **T23** (medido acá), **T13(b)** (su "sin población" sale de la
tenencia del harness) y la **21** (el ranking decide más cuanto peor es el ratio de selección). **No
se mueven** las afirmaciones sobre la *señal*: T9 (AUC 0.498), T11b (robustez del detector), T12
(insider en stress), T10 (sizing por nombre).

---

## 4. Qué queda

- **Tarea 28 (TP-CAL-10) queda disparada** con evidencia concreta: el candidato pasa el PBO con la
  config viva y falla por régimen. Su pre-registro debería usar el **bootstrap pareado** como gate
  principal (§2.1) y mirar 2018Q4 de frente.
- **Idea derivada, tarea nueva:** *validar el número de slots*. `max_positions=10` en la cuenta viva
  nunca se validó — se heredó al crear la cuenta. La sensibilidad (§2.3) sugiere que cuesta ~6 pts
  de CAGR sin comprar drawdown, pero eso necesita pre-registro propio, brazo oráculo, la métrica de
  riesgo declarada al frente y el overlay T20 activo (que es como corre en vivo).
- **Anotado, sin hacer:** sumar ASML a `data/pit_signals/` para cerrar el universo vivo en 128/128
  (`python scripts/precompute_pit_signals.py --tickers ASML`).
