# Pre-registro — CANDIDATAS-DE-LA-REJILLA-T170 (Tarea 477) · **CONGELADO 2026-11-27, antes de codear**

**Origen:** la tarea **472**. Con el IC fuera de muestra que congeló el §7 del pre-registro de la
T170 (`docs/exit_policy_prereg_t170_2026-09-10.md`), cuatro celdas de la rejilla de salida le
ganan a la política viva con el intervalo entero positivo, a los dos costos
(`docs/exit_policy_t170_2026-09-10.md` §3, corregido). La regla congelada dice qué hacer con eso:
*«eso no la cabla: abre su propio pre-registro, porque una celda elegida entre 15 por su intervalo
necesita un gate anti-multiplicidad que esta tarea no define»*. Éste es ese pre-registro.
**Qué NO hace:** no toca el motor, no cambia ninguna perilla viva, no mueve ningún umbral existente.

---

## 0. Qué se vio ANTES de congelar — la contaminación, declarada

**Visto:** la rejilla entera fuera de muestra **con el orden alfabético de los candidatos**, al
costo del harness y al del vivo: ΔCAGR, IC95% sin corregir, p, folds ganados y Δ de caída de las
14 celdas (la 472). En ese marco no hay ceguera posible: las cuatro candidatas salieron de ahí.

**No visto, y no se va a mirar antes de correr:**

1. **La rejilla con el orden de candidatos del vivo** (`ml_probability`, la tarea 473), a ningún
   costo. La 471 mostró que con el orden del vivo un Δ entre brazos puede cambiar de signo, y la
   473 que la viva pasa de 13,72% a 9,75%. Es otro marco, y es el de la cuenta.
2. **Ninguna celda con la inyección de ruina** (el C9 de la T37) en el marco de la T170: la T170
   no lo corrió.
3. **Ningún p ajustado por multiplicidad.**

**Consecuencia:** el marco que **decide** es el que no se miró —orden del vivo y costo del vivo—.
El alfabético se corre y se reporta (tiene que reproducir la tabla de la 472), pero no decide.
Y la familia del ajuste son **las 14 celdas**, no las cuatro que marcó la 472: elegir la familia
mirando cuáles ganaron sería el mismo defecto que esta tarea viene a corregir.

**Lo que esto no arregla, dicho antes:** la serie 26 → 26b → 34 → 37 → 167 → 170 minó esta
rejilla sobre ventanas que comparten casi todas las barras con ésta (T48). La corrección por las
14 cubre la elección **dentro** de esta corrida, no la historia de la rejilla. Por eso, si alguna
celda pasa, el veredicto no se presenta como *«validada»* sino como *«pasa el gate de esta
muestra»*, y la decisión queda de Chapa.

---

## 1. La pregunta

¿Alguna celda de la rejilla stop × trailing le gana a la salida viva `soff_t2.0` (stop duro
apagado, trailing 2,0×ATR) **fuera de muestra**, en el marco de la cuenta (orden y costo del
vivo), **después de corregir por haber mirado las 14** y **con el sesgo de supervivencia
acotado**?

---

## 2. Población y config (CONGELADO)

Las de la T170, que es lo que hace comparables los números, más el marco de la cuenta:

| eje | valor |
|---|---|
| universo | `data/harness_universe_live_acct2.txt` — **126** tickers |
| ventana | `2016-09-12..2026-09-09` (**2512** barras) — los artefactos de la T170, con `--allow-stale-artifacts` (la 463) |
| entradas | `analyze BUY` PIT, **141.417** |
| slots | 10 · `equal_weight` · capital finito (`portfolio_sim`) · sin régimen |
| `cap_days` | 250 |
| eval / fill | `eval_mode=touch` · `fill_mode=decision` · gates de re-entrada modelados |
| folds | los cinco de la T37/T170 (test 2021-08-01 → 2026-07-31), con el equity compuesto entre folds |
| **orden de candidatos** | **el del vivo**: `orden_del_vivo(score_by)` (`analysis/orden_del_dia.py`), con el store de `load_bars_signals_scores` (la 473) |
| **costo** | **el del vivo**: `--costo vivo` de la T170 (~0,063% por lado, la 468) |

**Marco secundario (se reporta, no decide):** orden alfabético, a los dos costos. Tiene que
reproducir la tabla de la 472.

---

## 3. Brazos (CONGELADO)

| brazo | rol |
|---|---|
| `soff_t2.0` | **referencia**: la salida viva |
| las otras **14** celdas de la rejilla | **la familia**: las que fijó el pre-registro de la T170, todas, sin elegir |
| `ORACULO_STOP`, `AZAR_MISMA_TASA` | sanity, como en la T170 |

**Ningún brazo se agrega, se saca ni se renombra después de congelar.** Si hiciera falta, va
como enmienda fechada.

---

## 4. Regla de decisión (CONGELADA)

Todo en el **marco primario**, sobre Δ = celda − `soff_t2.0`. Una celda **pasa** si cumple
**las seis**:

| id | criterio | umbral |
|---|---|---|
| **M1** | **multiplicidad:** p ajustado por **Romano-Wolf** (stepdown, unilateral, sobre las 14), con el ΔCAGR compuesto de las curvas fuera de muestra encadenadas | **< 0,05** |
| **D1** | ΔCAGR fuera de muestra (los cinco folds encadenados) | ≥ **+1,00 pp** |
| **D2** | folds en que la celda gana (Δ del fold > 0) | ≥ **4 de 5** |
| **D3** | cola por trade, muestra completa: Δ(peor) **y** Δ(p1) | ≥ **−2,00 pp** |
| **D5** | caída máxima de cartera, muestra completa **y** fuera de muestra | ≤ viva **+1,00 pp** |
| **C9** | **ruina** (T37): ΔCAGR(celda − viva) con inyección `gradual` a **r = 2,60% / d = 50%** **y** a **r = 0,47% / d = 70%**, en la **peor** de las tres semillas, muestra completa | ≥ **0** en los dos puntos |

**El bootstrap de M1:** bloques móviles de **20** ruedas, **2000** resamples, semilla **12345**
—los de la T170—, con **los mismos índices para las 15 series** (pareado). Estadístico: el
ΔCAGR compuesto sin estudentizar, el mismo de `paired_block_bootstrap`. Procedimiento: Romano y
Wolf (2005), algoritmo de p ajustados — se ordenan las celdas por Δ observado de mayor a menor, y
el p ajustado de la j-ésima es el máximo entre el de la anterior y la fracción de resamples en que
el **máximo** de los Δ bootstrapeados **centrados** de las celdas j…14 alcanza su Δ observado.
Controla la probabilidad de **al menos un** falso positivo entre las 14 en 5%.

**Por qué éstos y no otros:** D1, D2, D3 y D5 son los de la T170 (y antes los C1, C7, C6 y C2 de
la T37), sin tocar un umbral. **El D4 de la T170 —el IC del bootstrap sobre la muestra completa—
no se usa:** M1 es su versión fuera de muestra y corregida, que es lo que el §7 pidió. **C9 vuelve
de la T37**, con sus umbrales: el universo son los 126 que sobrevivieron diez años, y la T37
anticipó (su §5 y su §8) que si el instrumento elegía `trail off` eso era evidencia de
supervivencia, no de una regla mejor. Tres de las cuatro candidatas de la 472 son `trail off`.

**Veredicto:**

- **Ninguna pasa** ⇒ la salida viva queda como está, y la rejilla **queda cerrada** hasta que haya
  muestra nueva: lo que la T170 publicó, esta vez con el instrumento que su §7 congeló.
- **Alguna pasa** ⇒ **nada se cablea.** Se le presentan a Chapa las que pasan, con lo que esta
  tarea **no decide**: (a) la T37 declaró el trailing `off` **no shipeable** porque *«dejaría la
  política de salida colgando de un solo mecanismo»* (su §5); es un criterio de riesgo y no una
  medición, así que lo decide él; (b) el cambio en vivo, con la app cerrada: sin trailing
  es `atr_trail_enabled=false` —`atr_trail_mult=0.0` **no** lo apaga, sigue a `atr_stop_mult`
  (T53)—; `s4.0_t3.0` es `atr_hard_stop_enabled=true`, `atr_stop_mult=4.0`, `atr_trail_mult=3.0`.

**Resultado esperado, escrito ANTES de correr: NINGUNA PASA.** Las tres sin trailing, por **C9**:
sin barrera ATR, una caída gradual inyectada sólo la corta la señal, y la viva tiene el trailing.
`s4.0_t3.0`, por **M1** o **D2**: su p sin corregir era 0,015–0,021 en el marco alfabético. Es una
apuesta, no un supuesto: el orden del vivo es un marco que nadie miró, y las celdas están muy
correlacionadas entre sí, así que el umbral de Romano-Wolf queda bastante más cerca del p sin
corregir que el de Bonferroni (0,05/14 ≈ 0,0036).

**Si algún criterio no se puede medir, la corrida es INVÁLIDA y no hay veredicto.** No se
re-especifica nada para salvarla.

---

## 5. Sanity del instrumento (si falla alguno ⇒ INVÁLIDA, sin veredicto)

1. **Contabilidad** ≤ 1e-6 en todos los brazos.
2. **Oráculo contra control igualado**, en el marco primario: ΔCAGR ≥ +1,50 pp **y** ΔmaxDD ≤
   −5,00 pp (los de la T170).
3. **Reproducción, marco primario:** `soff_t2.0` da **9,75%** de CAGR con **2.325** trades tomados
   (la 473: orden y costo del vivo, sin régimen), tolerancia 0,0005.
4. **Reproducción, marco secundario:** con el orden alfabético, las anclas de la T170 (`soff_t2.0`
   0,0878 al costo del harness y 0,1372 al del vivo) y, celda por celda, el ΔCAGR fuera de
   muestra de la tabla de la 472 (tolerancia 0,0005).
5. **Control mecánico:** en las celdas `off`, la barrera apagada no dispara nunca (T37 §7).
6. **Determinismo de la ruina:** re-inyectar con la misma terna da el mismo digest de las barras
   (T37 §7.6).
7. **Romano-Wolf**, en la suite y no en la corrida: el p ajustado nunca es menor que el p sin
   corregir de la misma celda; con una sola hipótesis coincide con el de `paired_block_bootstrap`
   (mismos índices); y con 14 series idénticas a la referencia más ruido simétrico, no rechaza.

---

## 6. Qué NO se modela (caveats antes de correr)

Los desvíos que `deviations()` declara en el banner, salvo los dos que este marco corrige (el
orden de candidatos y el costo): ventana de `analyze()` expandida, barreras al toque (cota),
ventana rodante de los artefactos, overlay de volatilidad, escalado por régimen, screen de
universo E1b, cap de liquidez, blackout de earnings, el pick frenado que en vivo se queda con su
lugar (la 471) y los dividendos reinvertidos. Y el supuesto de la T37 §10 que sigue en pie: la
ruina inyectada es independiente entre nombres, y en una crisis real correlaciona; eso favorece a
los brazos sin barrera, o sea que C9 es una cota **optimista** para ellos.

---

## 7. Plan de ejecución

1. `romano_wolf_stepdown` en `analysis/walkforward_power.py`, con los tests del §5.7, antes de
   tocar el runner.
2. Runner `scripts/run_candidatas_t477.py`, sobre las funciones de la T170: la rejilla fuera de
   muestra con `rank_score` (y el orden dentro de la huella del cache), M1, D1–D5 por celda y C9
   con la viva como base (el `ruin_sweep` de la T37 tiene la base fija en `s2.0_t2.0`: se
   parametriza). Opciones `--orden` y `--costo`; el default es el marco primario.
3. Tests offline del runner, corrida completa (2000 resamples) y veredicto en
   `docs/candidatas_rejilla_t477_<fecha>.md`.
4. La fila de la T170 en `docs/VALIDEZ_VEREDICTOS.md` y la sección de la rejilla en la skill
   `backtest-replay-harness` se actualizan con el veredicto, sea cual sea.
