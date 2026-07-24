# Pre-registro CONGELADO — Detector de anomalía precio/volumen (Tarea 11, Brazo B)

**Fecha:** 2026-07-23 · **Estado:** congelado ANTES de codear (regla 2 — kill-criteria upfront).
**Ref:** `docs/BACKLOG.md` tarea 11 (ampliación 2026-07-07, caso TSLA) · `docs/research_prediccion_2026-07-06.md` §4 · deep gap analysis A-n.

Este documento fija la **hipótesis, el detector, el contrafactual, los brazos y los kill-criteria
ANTES de escribir una línea de detector o harness**. Nada acá se re-decide después de ver resultados.
Si el detector no supera el umbral, se documenta NO-SHIP y no se cablea (misma disciplina que T7/T8/T9/T10).

---

## 1. Contexto y objetivo

La tarea 11 tiene **dos triggers** que el backlog diseñó como brazos independientes:

- **Brazo A — PEAD post-earnings honesto:** sorpresa medida contra el consenso point-in-time del día
  previo al print (`analyst_estimate_snapshots`, T-CAT-5b). **BLOQUEADO por datos:** los snapshots
  arrancaron el 2026-06-06 y hoy hay ~7 semanas (37 días, 52 tickers) → menos de una temporada de pares
  (ticker, print) con consenso previo, muy lejos de los ~40 que hacen falta para un walk-forward con
  poder. No se puede shipear con poder hasta acumular ≥1-2 temporadas más (meses).
- **Brazo B — detector de anomalía precio/volumen** (ESTE documento): el **precio/volumen mismo es el
  evento**, point-in-time por construcción, sin depender del texto ni del consenso. Se puede validar
  **ahora** con veredicto ship/no-ship real, reusando los enablers ya listos.

**Objetivo del Brazo B:** medir si una **fuente de candidatos de BUY event-driven** —"un retorno diario
positivo fuera de banda, confirmado por volumen anómalo, entra al día hábil siguiente"— **bate a entrar
al azar** en el mismo universo con el mismo capital, con la misma triple barrera de salida. Es la
primera señal event-driven de FinanzIAs y donde apunta el hallazgo acumulado de T7/T8/T9/T10: *el valor
está en de dónde salen los candidatos, no en refinar decisiones sobre los de `analyze()`*.

**Qué NO es:** no es el PEAD de earnings (Brazo A, bloqueado); no es short (solo long post-anomalía
positiva, simetría fuera de alcance, ref backlog); no es lead-sourcing de nombres nuevos (corre sobre
el universo de 41 tickers ya cacheado; el sourcing fuera de watchlist vía screen E1b es concern de
producción, no de este test).

---

## 2. El detector (CONGELADO, sin sweep de forma)

Módulo puro nuevo `analysis/anomaly_signal.py` (stdlib, sin red, sin DB — testeable offline con barras
sintéticas). Reusa el ATR ya validado de `analysis.exit_replay` (Wilder, `atr_series`).

Para cada ticker con barras diarias `Bar = (fecha, open, high, low, close)` + su serie de **volumen**
alineada, la barra `i` (con `i ≥ warmup`) **dispara una anomalía** si se cumplen **las dos** condiciones:

1. **Retorno fuera de banda (positivo):** `close[i] − close[i-1] ≥ k · ATR14[i]`
   — un movimiento diario al alza de al menos `k` ATRs. Long-only ⇒ solo el lado positivo.
2. **Volumen anómalo:** `volume[i] ≥ m · ADV20[i]`, con `ADV20[i] = media(volume[i-20 : i])`
   (las 20 ruedas **estrictamente anteriores** a `i` — la anomalía se mide contra el nivel *normal*
   previo, no contra sí misma).

- **Entrada:** al **close del día hábil siguiente**, `entry_idx = i + 1`. Point-in-time estricto: la
  anomalía queda determinada por datos hasta el close de `i` (el scan EOD), y la orden se llena en la
  rueda siguiente — exactamente cómo actuaría el engine vivo (scan post-close → fill al próximo close).
- **Período refractario:** tras una anomalía aceptada en un ticker, se saltean las siguientes en ese
  mismo ticker por `cap_days` (20) ruedas — evita clustering degenerado y espeja el `no reabrir mientras
  está en cartera` del engine.
- **Fail-safe:** requiere ≥ `max(atr_period, 20)` barras previas válidas y que exista la barra `i+1`;
  si no, no dispara (nunca mira el futuro, nunca rompe por falta de datos).

**Parámetros de forma CONGELADOS (no se barren):** `atr_period = 14`, `adv_window = 20`, entrada `D+1`,
refractario `= cap_days = 20`, dirección long-only positiva. Lo único que barre la grilla (§4) es
`(k, m)`, el par umbral — y ese barrido se contabiliza como intentos en el DSR (§6).

**Caveat de datos (anotado):** el volumen de yfinance/parquet puede no estar ajustado por splits →
un split podría inflar el volumen. Mitigación estructural: la condición (1) exige además un **salto de
precio** de `k·ATR`, y los splits **sí** están ajustados en precio → un split (volumen alto, precio sin
salto) **no** dispara. El `AND` ret+volumen protege contra ese artefacto por diseño.

---

## 3. Contrafactual / baseline (CONGELADO)

La pregunta del kill-criteria del backlog: *"la cartera de eventos anomalía bate al baseline (mismo
capital, entradas aleatorias del universo screeneado)"*. Un solo sorteo al azar es ruidoso, así que el
baseline es una **distribución Monte Carlo**, no un punto:

- **B_random (benchmark primario):** `K = 500` carteras de entradas aleatorias. Cada sorteo toma
  `N_anom` pares `(ticker, entry_idx)` al azar de la grilla operable (todas las barras `i+1` con
  `i ≥ warmup`, `i+1 ≤ n-2`), donde `N_anom` = nº de entradas que produjo el **brazo PRIMARIO** (§4).
  - **Control de confusión temporal (clave):** cada sorteo respeta la **distribución por mes calendario**
    de las entradas de la anomalía (mismo nº de entradas por mes que el brazo anomalía). Las anomalías se
    concentran en meses volátiles, que tienen retornos forward sistemáticamente distintos; sin
    time-matching el benchmark mediría *timing de régimen*, no *selección*. Con él, la comparación aísla
    el valor de la señal.
  - Semillas fijas y ordenadas (reproducible). Mismo `simulate_portfolio`, mismo capital, mismos exits.
  - Se reporta la **distribución** (p5 / mediana / p95) de CAGR, Sharpe y maxDD de las 500 carteras.
- **B_datematched (robustez secundaria, NO gatea):** mismas fechas de disparo, ticker aleatorio en cada
  fecha → separa selección cross-sectional de timing. Se reporta como diagnóstico; el ship no depende de
  él (el backlog gatea contra "aleatorias del universo", que es B_random).

---

## 4. Brazos pre-registrados

Grilla del par umbral `(k, m)`. Todo lo demás fijo (§2). El resto del pipeline es idéntico entre brazos.

| brazo        | k (ret/ATR) | m (vol/ADV20) |
|--------------|-------------|---------------|
| A_k1.5_m1.5  | 1.5         | 1.5           |
| A_k1.5_m2.0  | 1.5         | 2.0           |
| A_k1.5_m3.0  | 1.5         | 3.0           |
| A_k2.0_m1.5  | 2.0         | 1.5           |
| **A_k2.0_m2.0 (PRIMARIO)** | **2.0** | **2.0** |
| A_k2.0_m3.0  | 2.0         | 3.0           |
| A_k2.5_m1.5  | 2.5         | 1.5           |
| A_k2.5_m2.0  | 2.5         | 2.0           |
| A_k2.5_m3.0  | 2.5         | 3.0           |

- **Brazo PRIMARIO (titular):** `A_k2.0_m2.0` — el par central, elegido por ser el punto medio de la
  grilla, **no** por performance. Es el que fija `N_anom` para el benchmark y el que se reporta como
  referencia.
- **Brazo de decisión:** el de mejor Sharpe anualizado **entre los que pasan el filtro local** (§6),
  convención T10; sobre él se aplican DSR/PBO. Los **9 brazos** cuentan como intentos para el DSR.
- **Oráculo de validación:** un brazo que rankea las entradas por el retorno realizado (look-ahead
  deliberado) — igual que en T9/T10, confirma que el harness **tiene** sensibilidad para detectar una
  señal buena (si el oráculo no despega, el harness está roto y el NO-SHIP no vale). No es candidato.

---

## 5. Métricas

Sobre el simulador de cartera real `analysis/portfolio_sim.py` (`max_positions = 5`,
`initial_capital = 50.000`, `allow_reentry_while_open = False` engine-faithful, `cap_days = 20`,
`AtrParams()` default = stop 2×ATR / TP 4×ATR / trailing, `CostModel()` = comisión 0.1% + slippage
0.05% en las dos puntas):

- **CAGR**, **Sharpe anualizado** y **maxDD de cartera** sobre la curva de equity (`risk_sizing.cagr` /
  `sharpe_annual`) — **NO** puntos acumulados (corrige el defecto de especificación de la lápida de T8).
- Descriptivos (no deciden): win rate, payoff, retorno medio por trade, exposición, mezcla de salidas,
  desglose por régimen, nº de entradas.

**Invariantes que se chequean ANTES de leer el veredicto** (si fallan, el run se descarta): integridad
contable (curva de equity termina en la equity final), y el oráculo despega claramente sobre el baseline.

---

## 6. Kill-criteria (CONGELADOS)

El brazo de **decisión** shipea **si y solo si se cumplen TODOS**:

1. **Significancia estadística:** su **CAGR y su Sharpe** superan el **percentil 95** de la distribución
   B_random (§3) → p empírico unilateral < 0.05 en las dos métricas.
2. **Significancia económica:** `ΔCAGR ≥ +2.0 pp` sobre la **mediana** de B_random. Un edge
   estadísticamente real pero trivial no justifica una fuente de señal nueva con su costo operativo.
3. **Riesgo:** `maxDD ≤ 1.5 ×` la **mediana** del maxDD de B_random.
4. **Anti-overfitting (selección múltiple sobre 9 brazos):** `DSR > 0.5` **y** `PBO < 0.5`
   (`walkforward_power.deflated_sharpe_ratio` / `pbo_cscv`, matriz de retornos diarios de equity
   alineados a calendario común, patrón T10).
5. **Robustez de régimen:** el retorno medio por trade es **positivo o neutro en cada régimen**
   (`bull_normal` + los 3 de stress: 2018Q4, COVID-2020, bear-2022) — el signo no puede colgar de un
   solo régimen.
6. **Robustez por nombre (leave-one-ticker-out):** sacar el ticker que más aporta al edge **no invierte
   el signo** del ΔCAGR — la señal no puede ser un solo TSLA/NVDA disfrazado.

Si el brazo de decisión falla **cualquiera** → **NO-SHIP**, se documenta el hallazgo y el detector queda
como enabler/dead-code (como `dd_breaker.py` de R1). El dato acumulado igual sirve como feature futura
para el meta-modelo.

**Si PASA:** se cablea detrás de un flag propio **default OFF** (regla 3: display/opción nueva no
prendida por default), inyectando los candidatos en `generate_trades_analyze_single` por el mismo
pipeline de gates/screen que cualquier BUY; hereda en producción el escalado por régimen T20 (ya activo)
y el earnings-blackout (Gate 6). El valor validado de `(k, m)` queda como default del flag.

---

## 7. Qué NO se modela (caveats declarados antes de correr)

- **Overlay de régimen T20 (activo en prod):** el harness mide la señal **sin** el escalado risk-off
  ×0.5 para atribución limpia. En producción el candidato lo hereda (orthogonal, ya shipeado). Anotado.
- **Screen de universo E1b:** el test corre sobre los 41 tickers líquidos ya cacheados (in-universe).
  El sourcing de nombres fuera de watchlist es concern de producción, no de este veredicto.
- **Salida:** no es "ATR puro" — es la triple barrera completa del engine (ATR stop/TP/trail **más** el
  flip `analyze SELL` vía `sigs_by`), idéntica a la de todos los BUYs. Es fiel e intencional ("misma
  triple barrera de salida", ref backlog).
- **Márgenes, apalancamiento, dividendos, intradía:** fuera de alcance (limitaciones de `portfolio_sim`).

---

## 8. Plan de ejecución

1. `analysis/anomaly_signal.py` — detector puro (§2) + `build_anomaly_entries(bars_by, vol_by, k, m)`.
2. `scripts/run_anomaly_replay_t11b.py` — harness: carga barras+volumen del parquet, arma entradas
   anomalía + B_random (Monte Carlo time-matched) + oráculo, corre `simulate_portfolio`, computa
   CAGR/Sharpe/maxDD, DSR/PBO sobre los 9 brazos, aplica §6. Sin red, sin tocar `finanzias.db`.
3. Tests offline (`tests/test_anomaly_signal.py`): disparo/no-disparo, PIT (no mira `i+1`+), refractario,
   fail-safe, artefacto de split (volumen sin salto de precio → no dispara), determinismo del baseline.
4. Correr vía agente `backtest-runner` sobre el backup limpio + parquet precargado.
5. Escribir veredicto en `docs/anomaly_signal_t11b_2026-07-23.md` (ship/no-ship + por qué).
6. Si SHIP: cablear detrás de flag default OFF + tests de engine + suite Windows verde. Si NO-SHIP:
   documentar y dejar el detector como enabler.

**Congelado. Cualquier cambio a §2–§6 después de ver un resultado invalida el pre-registro.**
