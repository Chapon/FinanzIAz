# E4 — Poder estadístico: harness walk-forward PIT + CPCV/DSR/PBO

**Estado: enabler cerrado (SHIP del harness).** Planificado 2026-07-02; harness
corrido y documentado **2026-07-07**. Kill-criteria base **PASA** y la ampliación
metodológica (CPCV + DSR/PBO, research de predicción §7) quedó implementada y
ejercida sobre datos reales.

Módulos: `analysis/walkforward_power.py` (núcleo puro), `scripts/run_walkforward_power.py`
(runner con `analyze()` PIT, resumable), `tests/test_walkforward_power.py` (57 tests
offline). Corridas persistidas en `data/walkforward_power/{ts}/summary.{json,txt}`.

---

## 1. Qué es E4 y por qué

Casi toda decisión de trading del proyecto venía sub-potenciada: A1 (stops ATR) se
decidió sobre **n=6** salidas ATR limpias, la Tarea 3 (buy_score) sobre **n=27**
pares score↔fwd. Con esas muestras se estaba decidiendo sobre ruido. E4 **no cambia
ninguna decisión ni flag vivo** — es un enabler puro que genera el poder estadístico
faltante: un **sampler point-in-time** sobre el cache 10y que emite cientos de
entradas sintéticas no-solapadas, etiquetadas por régimen (incluyendo ventanas de
stress reales), de las que salen las dos re-evaluaciones potenciadas (A1 y Tarea 3)
más el power analysis.

## 2. Método

- **Universo:** `data/harness_universe_41_10y.txt` (41 tickers, cache 10y limpio;
  MLTX excluido por historia corta). Cargado por `get_historical_data_batch` desde
  el cache (mismo camino que produce E5-limpio, sin lookahead nuevo).
- **Grilla PIT:** por ticker, entradas cada `spacing=20` barras desde `warmup=250`
  (≥200 para que `analyze()`/SMA200/XGBoost sean válidos). `spacing ≥ fwd_long=20`
  ⇒ las ventanas forward de entradas consecutivas del mismo ticker **no se solapan**
  (independencia temporal; con spacing menor el n pooled sobreestima el poder).
- **Regímenes:** cada entrada se tagea por fecha. Ventanas de stress con drawdown
  real: `stress_2018q4` (2018-10..12), `stress_covid_2020` (2020-02-15..04-30),
  `stress_bear_2022` (2022-01..10). Todo lo demás = `bull_normal`.
- **A1 potenciado:** por cada entrada, replay stop(2.0)-vs-sin-stops reusando el
  motor ATR puro de `analysis.exit_replay` (mismo orden intradía que el engine: ATR
  con el HWM previo al close, fills gap/touch). Δ = ret_no_stops − ret_with_stops.
- **Tarea 3 potenciado:** corr(buy_score, fwd) pooled + IC cross-sectional, con el
  `analyze().ml_probability` computado PIT por entrada (resumable, cacheado en disco).
- **Power analysis:** N para 80% de potencia vía Fisher-z (corr) y d de Cohen (Δ
  pareado); potencia lograda con el N generado.

### Ampliación 2026-07-07 — CPCV + DSR/PBO (research §7)

La grilla por spacing da **una** estimación puntual del efecto. Contra el backtest
overfitting se agregó:

- **CPCV (Combinatorial Purged Cross-Validation, López de Prado):** los samples se
  ordenan por fecha, se reparten en `n_groups` bloques temporales contiguos, y por
  cada combinación de `k_test` grupos como test se arma un par (train, test) con el
  train **purgado** (se sacan los samples cuya etiqueta [entry, entry+fwd_long]
  solapa la de algún test) y con **embargo** (el end del test se extiende N días
  antes de purgar, matando autocorrelación serial). El `label_end` de cada entrada
  hace el purging point-in-time. Produce C(n_groups, k_test) caminos → una
  **distribución** del efecto, no un punto.
- **PBO (Probability of Backtest Overfitting, CSCV):** matriz config×observación;
  por cada forma de partir las obs en in-sample / out-of-sample se elige el config
  con mejor Sharpe IS y se mide su rango OOS. PBO = fracción de particiones donde el
  ganador IS quedó **por debajo de la mediana** OOS. PBO ≈ 0.5 ⇒ la selección es
  puro ruido; PBO baja ⇒ el ganador aguanta fuera de muestra.
- **DSR (Deflated Sharpe Ratio):** deflacta el Sharpe del ganador por el **máximo
  esperado bajo el nulo** dado el número de variantes probadas y su dispersión
  (corrige skew/kurtosis de los retornos). DSR = P(Sharpe verdadero > 0) tras
  contabilizar los intentos.

Todo es lógica pura (numpy + stdlib), testeada offline con propiedades conocidas
(conteo de splits = C(N,k), invariante de purga, PBO=0 para un config genuinamente
bueno / PBO=1 en anticorrelación construida, monotonía del DSR en el nº de intentos).

## 3. Kill-criteria

> El harness produce ≥N muestras independientes / una ventana de stress utilizable,
> con power analysis documentado, suficiente para re-correr A1 y la Tarea 3 con
> potencia adecuada, cubriendo ≥1 régimen de drawdown; DSR/PBO como métrica de
> veredicto contabilizando los intentos. Suite Windows verde.

**PASA.** Corrida 2026-07-07 (`data/walkforward_power/20260707_181204/`):

- **4674 entradas · 114 fechas distintas** (vs n=6 / n=27 previos).
- Regímenes: `bull_normal=3977`, `stress_2018q4=123`, `stress_covid_2020=123`,
  `stress_bear_2022=451` → **3 ventanas de drawdown** cubiertas.
- Potencia A1 ≥ 0.80 en todos los regímenes (ver tabla). Detectable |ρ| para T3 baja
  a ~0.041 (vs ~0.53 con n=27).
- PBO/DSR computados sobre las 4 variantes de stop-mult.
- Suite Windows: **1084 passed, 1 skipped**.

## 4. Resultados A1 (stops ATR) — el hallazgo

### 4.1 Potencia y Δ por régimen

`Δ = ret_no_stops − ret_with_stops` (retorno por-share). Δ>0 ⇒ *sacar* los stops
habría ayudado en ese régimen.

| régimen | n | ret_stop | ret_nost | Δ mean | d | potencia | Δ LOO |
|---|---:|---:|---:|---:|---:|---:|---:|
| all | 4674 | +1.43% | +1.68% | +0.24% | 0.041 | 0.81 | +0.21% |
| bull_normal | 3977 | +1.56% | +2.15% | **+0.60%** | 0.118 | 1.00 | +0.55% |
| stress_2018q4 | 123 | −2.39% | −0.79% | +1.60% | 0.256 | 0.81 | +1.65% |
| **stress_covid_2020** | 123 | +4.65% | −2.32% | **−6.96%** | −0.463 | 1.00 | −6.70% |
| **stress_bear_2022** | 451 | +0.51% | −0.78% | **−1.30%** | −0.203 | 0.99 | −1.20% |

**El signo del Δ se da vuelta según régimen** y es robusto al leave-one-ticker-out
(la columna Δ LOO no lo tumba — a diferencia del n=6 original de A1, que colgaba de
LRCX). Sacar los stops "ayuda" solo en el rebote (bull +0.60%), pero en drawdown es
**catastrófico** (COVID −6.96 pts, bear-2022 −1.30 pts). La muestra viva de la cuenta
(survivorship, puro rebote 2024-2026) nunca vio los regímenes donde el stop se gana
el lugar.

### 4.2 Robustez CPCV + PBO/DSR sobre las variantes de stop-mult

Variantes del eje "cuán apretado" (loosear `stop_mult` afloja también el trailing;
**no** es el stop inicial aislado). Sharpe por-observación, n_obs=4674:

| variante | Sharpe por-obs |
|---|---:|
| no_stops | +0.1770 |
| loose_3.0 | +0.1934 |
| loose_2.5 | +0.2026 |
| **baseline_2.0** (vivo) | **+0.2113** |

- **PBO (CSCV, S=10, 252 combos) = 0.004 (≈0).** El config elegido best-IS aguanta
  OOS. `baseline_2.0` fue el mejor in-sample en **238/252** particiones y no colapsa
  fuera de muestra → la ventaja **no es un artefacto de selección**.
- **DSR del mejor (baseline_2.0): 1.000** (SR0 máx-esperado-bajo-H0 = 0.0154; PSR sin
  deflactar = 1.000). El Sharpe del stop apretado es genuinamente > 0 tras
  contabilizar las 4 variantes.

### 4.3 Distribución CPCV del Δ (no_stops − baseline) por régimen

15 caminos (C(6,2)); `%Δ>0` = fracción de caminos donde sacar stops ayudó:

| régimen | paths | Δ mean | Δ std | %Δ>0 |
|---|---:|---:|---:|---:|
| all | 15 | +0.24% | 0.41% | 80% |
| bull_normal | 15 | +0.60% | 0.20% | 100% |
| stress_2018q4 | 15 | +1.61% | 1.60% | 93% |
| **stress_covid_2020** | 15 | −6.88% | 8.05% | 33% |
| **stress_bear_2022** | 15 | −1.30% | 1.67% | 27% |

El sign-flip es **estable** entre caminos: en stress, 67-73% de los caminos muestran
Δ<0 (sacar stops perjudica), con varianza alta (la cola izquierda que el stop corta).

### 4.4 Veredicto A1

**NO-SHIP confirmado con poder real, y más fuerte que antes:** no es solo "no aflojes
los stops" — es que **el stop apretado vivo (2.0) es la mejor variante en
riesgo-ajustado (Sharpe), y PBO=0 dice que ese ranking es robusto, no suerte**. La
lectura por retorno medio ("sacá stops en bull") ignora la cola izquierda del stress;
el Sharpe la captura y por eso gana `baseline_2.0`. **Los stops se quedan en 2.0.**
Esto reemplaza la conclusión sub-potenciada de `atr_stop_recalib_2026-06-30.md`
(n=6) por una con 4674 muestras y 3 regímenes de drawdown.

## 5. Resultados Tarea 3 (buy_score) — poder, no veredicto

E4 entrega el **poder** para la Tarea 3; el veredicto (validar/degradar/rediseñar el
score) es la Tarea 3 / tarea 9 del backlog, no E4.

- La grilla ofrece **4674 pares potenciales** score↔fwd (vs n=27). A ese n el |ρ|
  detectable a 80% cae a **~0.041** (Fisher-z), contra ~0.53 que permitía el n=27.
- N para 80% potencia: ρ=0.05→3138, ρ=0.10→783, ρ=0.15→347, ρ=0.20→194.
- Pipeline de scoring PIT **validado** (resumable, cacheado): produce
  `analyze().ml_probability` por entrada sin tocar red. El log confirma la
  inestabilidad ya conocida del XGBoost (`val_acc std >8%`) → refuerza que el score
  entra a la Tarea 3 con la sospecha de siempre.
- La re-eval completa (corr/IC pooled sobre las 4674, con DSR/PBO multi-brazo) es la
  Tarea 3 potenciada / tarea 9; E4 dejó la maquinaria (`pooled_correlation`,
  `cross_sectional_ic`, `pbo_cscv`, `deflated_sharpe_ratio`) lista para consumirla.

## 6. Caveats de datos (sección Calidad de datos del backlog)

- **Survivorship:** 41/41 vivos → el backtest sobreestima; las ventanas de stress
  mitigan el sesgo del régimen actual pero no lo eliminan.
- **`auto_adjust=True`:** introduce lookahead en backtests largos (sesgo conocido);
  se interpreta el nivel de los retornos con cuidado, no su magnitud absoluta.
- **DSR con n_obs=4674:** el escalado √(n−1) del DSR asume retornos ~iid; con
  spacing=fwd_long el solapamiento es mínimo pero no nulo → el DSR es levemente
  optimista. El PBO (basado en bloques temporales) corrobora el veredicto de A1 sin
  ese supuesto, así que la conclusión no cuelga del DSR.
- **CPCV para A1:** A1 no ajusta un modelo, así que el purge/embargo importa menos
  que en un backtest de estrategia entrenada; acá CPCV se usa como generador de una
  distribución del efecto por bloques (robustez temporal), y PBO/DSR como el chequeo
  anti-selección sobre las variantes de stop-mult.

## 7. Qué destraba

- **A1:** cerrado NO-SHIP con poder (reemplaza al n=6). Los stops quedan 2.0.
- **Tarea 3 / tarea 9 (rediseño predictivo):** el harness + la maquinaria CPCV/DSR/PBO
  son la precondición metodológica; ahora la re-eval del score corre sobre n=4674 con
  DSR multi-brazo.
- **Tarea 7 (scale-out + trailing chandelier), tarea 8 (R2 régimen), 11 (PEAD), 12
  (FORM4):** todas pre-registran su kill-criteria contra este harness con las ventanas
  de stress y reportan DSR/PBO contabilizando los intentos acumulados por hipótesis.
- **R1 (circuit breaker):** las ventanas de stress (2018Q4/COVID/2022) son
  exactamente el banco de prueba de ese guardrail.

## 8. Reproducir

```
python scripts/prefetch_harness_cache.py data/harness_universe_41_10y.txt -p 10y
python scripts/run_walkforward_power.py --only a1        # A1 + robustez CPCV/PBO/DSR (rápido, puro)
python scripts/run_walkforward_power.py --only t3        # Tarea 3, largo, resumable (XGBoost PIT)
```
