# Pre-registro — Bloque 10 + 20: "cuánto exponerse" (sizing por riesgo + escalado por régimen)

_Congelado 2026-07-22, ANTES de codear los brazos y de mirar un solo resultado._
_Tareas 10 (sizing por riesgo, eje **nombre**) + 20 / R2b (escalado por régimen, eje **mercado**), co-registradas como **un solo experimento** para pagar el costo de DSR una sola vez._

> **Regla del proyecto (CLAUDE.md §2):** kill-criteria upfront. Este documento fija los brazos, la composición, las métricas y los umbrales antes de correr. Si ningún brazo supera el umbral, se documenta NO-SHIP y no se cablea nada. Igual que la tarea 9 (`cb6bf85`) y R2 (`docs/market_regime_gate_r2_2026-07-20.md`).

---

## 0. Por qué estas dos juntas

R2 (tarea 8) midió sobre la cartera real que **el eje que rinde es *cuánto exponerse*, no *cuándo cortar***: apagar entradas en risk-off destruye el compounding (CAGR 12.70% vs 18.98% del baseline), pero **escalarlas a medio tamaño lo mejora en las dos puntas** (CAGR 19.55% / maxDD 19.1%). El brazo secundario R2b pasó pero, por la regla pre-registrada (un secundario no se shipea sin el primario), quedó sin shipear → es la **tarea 20**.

La **tarea 10** ataca el mismo eje desde el otro lado: la cuenta viva dice `allocation_mode="signal_weighted"` pero ese modo no está en `_VOL_SIZED_MODES` (`strategies.py:54`), así que cae a **equal-weight** — la config miente. En vez del parche mínimo (renombrar), la política de calidad manda medir **sizing basado en riesgo** (peso ∝ 1/σ, lo que hacen los sistemas pro) contra el equal-weight real.

Sizing por **nombre** (σ del ticker) y escalado por **mercado** (régimen SPY) son la misma familia. Se validan en **la misma corrida** del harness sobre `portfolio_sim.py` y **todos los brazos de las dos tareas cuentan como intentos del mismo experimento** para el DSR/PBO.

## 1. La lección de la tarea 8 que este pre-registro aplica

La lápida de la tarea 8 registró un **defecto de especificación**: sus kill-criteria estaban en **puntos de P/L acumulado** (`KILL_MIN_PL_PTS`, etc. en `run_market_regime_r2.py:57-60`). En un harness de **cartera con capital finito** eso es la métrica equivocada — una variante que retiene más tiempo o reinvierte distinto mueve el P/L acumulado por razones que no son alpha. **Acá los umbrales van en CAGR y Sharpe sobre la curva de equity terminal, más el max DD de cartera.** El P/L en puntos queda solo como descriptivo.

## 2. Harness (CONGELADO)

- **Motor:** `analysis/portfolio_sim.py` (`simulate_portfolio`) — capital y slots finitos, la entrada sin slot se pierde, el cash liberado se reinvierte. Los exits salen por `replay_cycle` (ya validado); **ninguna variante de este experimento toca exits** (invariante verificado por test, igual que R2).
- **Universo:** `data/harness_universe_41_10y.txt` (41 tickers × 10y).
- **Señal:** artefacto PIT `analyze()` de `data/pit_signals/` (enabler de la tarea 7; 92.783 evaluaciones). Sin red, sin tocar `finanzias.db`.
- **SPY:** cache 10y (`parquet_cache.read("SPY","10y","1d")`) para la serie de régimen (`build_regime_series`, ya shippeada por R2: SPY<SMA200, PIT en D−1, SMA simple 200, cero parámetros ajustados).
- **Parámetros fijos:** `max_positions=5`, `initial_capital=50_000`, `spacing=20`, `warmup=250`, `cap_days=20`, `AtrParams()` default, `ScaleOutParams()` default, `CostModel()` default (comisión + slippage en las dos puntas).
- **`allow_reentry_while_open=False`** — el default engine-faithful que introdujo la tarea 9 (el engine no reabre un ticker ya en cartera). **NOTA:** R2 pineó `True` a propósito para reproducir sus números publicados; este experimento es fresco y usa el comportamiento fiel al engine, así que **su baseline B0 se re-corre bajo `False` y NO es comparable número-a-número con el B0 de R2** (otra población — misma situación que la tarea 9, que re-corrió su propio baseline).
- **Determinismo:** todo puro/offline; el no-determinismo de XGBoost del stacking no aplica (la señal PIT ya está materializada en disco). Un mismo input da el mismo output.

## 3. Métricas (CONGELADAS — se computan sobre la curva de equity diaria `res.equity_curve`)

Sea la curva `(fecha, equity)` diaria que ya arma el simulador (`_build_equity_curve`, cash + MTM de posiciones abiertas):

- **CAGR** = `(equity_final / equity_inicial) ** (252 / n_días_curva) − 1`. (Anualización por ruedas, consistente con la señal EOD.)
- **Sharpe anualizado** = `mean(r_d) / std(r_d) · √252`, con `r_d` los retornos diarios simples de la curva y `rf = 0`. Se reporta `std=0 → Sharpe indefinido` (no se fuerza a 0).
- **max DD de cartera** = `res.max_dd` (peak-to-trough sobre la curva diaria completa — el DD de cartera real, NO el intra-ventana-de-stress que fue el espejismo de R2a).
- **Descriptivos (no deciden):** P/L total en puntos, exposición (fracción de días invertidos), p5 del retorno diario, desglose por régimen (`bull_normal` + ventanas de stress), n_taken / n_filtered / n_no_slot, peso medio y máximo por nombre.

## 4. Brazos (CONGELADOS — todos cuentan como intentos del MISMO experimento para DSR/PBO)

**Sizing (`size_weight(ticker, date) → m ≥ 0`, multiplicador de riesgo sobre el slice equal-weight):**

| brazo | eje | `m` (peso de riesgo relativo) |
|---|---|---|
| **B0_equal_weight** (baseline) | — | `m = 1.0` (slice igual = lo que hace la cuenta viva hoy) |
| **S1_inverse_vol** | nombre | `m = median_σ / σ_ticker` |
| **S2_vol_target** | nombre | `m = vol_target_annual / σ_ticker` con `vol_target_annual = 0.20` |

- **σ_ticker (CONGELADO):** volatilidad **realizada** anualizada de los **60 días hábiles** previos a la entrada (log-returns del cache 1d PIT, ×√252). **Realizada simple, NO GARCH** (el caveat del backlog: GARCH degenera con α+β≈1). `σ` desconocida/≤0 → fallback a la **mediana** de las σ conocidas del día (igual que `_compute_target_weights`).
- **Clamp del multiplicador (CONGELADO):** `m` se recorta a `[0.25, 2.0]` para que una σ diminuta no dispare una apuesta gigante.
- **Tope por nombre (CONGELADO):** el notional de cualquier posición se capea a `max_weight = 0.25` de la equity corriente (`DEFAULT_MAX_POSITION_WEIGHT`), y nunca supera el cash disponible.

**Régimen (`regime_factor(date) → g ∈ (0,1]`, sweep pre-registrado de la tarea 20):**

| brazo | `g` en risk-off (SPY<SMA200 D−1) | `g` en risk-on |
|---|---|---|
| **R2b_f025** | 0.25 | 1.0 |
| **R2b_f050** | 0.50 | 1.0 |
| **R2b_f075** | 0.75 | 1.0 |

Detector de régimen **fijo** (SPY/SMA200), sin sweep del detector — para no inflar brazos. Los brazos de régimen corren con sizing `B0_equal_weight` (`m=1`).

**Composición (CONGELADA — regla: el factor de régimen MULTIPLICA al peso de riesgo):** son ejes ortogonales (uno es por-nombre, otro es por-día-de-mercado), así que el tamaño final es `notional = clamp_maxweight( (cash/free_slots) · m · g )`. Se pre-registra **UNA** composición para no elegir el ganador post-hoc:

| brazo | sizing | régimen |
|---|---|---|
| **C_S2xf050** | S2_vol_target (`m = 0.20/σ`) | R2b factor 0.50 en risk-off |

(`vol_target` es el sizing canónico pro; `0.50` es el factor que R2 ya midió positivo. Cualquier otra combinación S×f es **exploratoria** y se reporta marcada, sin participar del veredicto.)

**Total: 7 brazos candidatos** (1 baseline + 2 sizing + 3 régimen + 1 composición).

**Brazo de validación del harness (NO candidato):** `V_oracle_size` — `m ∝ retorno realizado del ciclo` (mira el futuro). Igual que el brazo oráculo de la tarea 9: si el harness tiene poder para distinguir sizings, el oráculo tiene que dar un CAGR muy por encima de todos. Si el oráculo NO se despega, el harness no discrimina sizing y el experimento entero es inválido (se aborta y se documenta). Solo valida la maquinaria; no se cablea jamás.

## 5. Kill-criteria (CONGELADOS)

Baseline = **B0_equal_weight** (lo que la cuenta hace realmente hoy). Un brazo candidato **se adopta** solo si cumple TODO:

1. **Beneficio:** mejora **Sharpe anualizado ≥ +0.10** **o** **CAGR ≥ +1.0 punto porcentual** sobre B0.
2. **Restricción de riesgo:**
   - Brazos de **régimen (tarea 20):** el **max DD de cartera NO sube** respecto de B0 (la lección de R2a: un guardrail que empeora el DD de cartera no cumple su propósito; ojo, es el DD de cartera terminal, no el intra-stress).
   - Brazos de **sizing (tarea 10):** el max DD de cartera **no sube más de 1.5×** el de B0 (umbral del backlog para el eje de sizing).
3. **Robustez OOS:** mantiene la ventaja con **DSR > 0** y **PBO < 0.5**, contabilizando **los 7 brazos candidatos como intentos** del mismo experimento (CPCV con purge+embargo, maquinaria de E4 `analysis/walkforward_power.py`). Un brazo que gana IS pero no sobrevive el descuento por selección múltiple NO se adopta.
4. **No depende de un solo régimen:** el signo del beneficio no puede venir enteramente de una sola ventana (bull_normal / 2018Q4 / COVID-2020 / bear-2022). Si el efecto es positivo solo en un régimen y negativo o nulo en el resto, NO-SHIP (misma trampa que mató al scale-out de la tarea 7).

**Si pasa:** se cablea **detrás de flag, default = valor validado**, y se corrige la mentira de config de la cuenta (activar el modo de sizing validado, o el factor de régimen). **Si no pasa:** se documenta NO-SHIP; para la tarea 10, además, se **renombra la cuenta a `equal_weight`** para que la config deje de mentir (cierre del hallazgo N1 pase lo que pase con el harness).

## 6. Invariantes que se verifican ANTES de leer resultados (si fallan, es bug, no resultado)

- **Integridad contable:** curva de equity vs contabilidad de cash con **0.000% de desvío** (como R2 y la tarea 9).
- **Invariante de exits:** ninguna variante de sizing/régimen cambia la salida de una posición que igual se abrió (mismo ticker+fecha → misma fecha y retorno de salida). El sizing solo mueve el **notional**, no el timing.
- **Sanidad del baseline:** B0_equal_weight reproduce el sizing equal-weight actual del simulador (`m=1`, `g=1`) exactamente.

## 7. Qué se shipea como enabler (independiente del veredicto)

- Extensión de `portfolio_sim.py`: hook `size_weight` (peso de riesgo por nombre) además del `entry_filter` de régimen ya existente, con el clamp y el tope por nombre de §4. Default = comportamiento actual (`m=1`).
- `analysis/risk_sizing.py` (puro): σ realizada 60d + `make_size_weight(mode)` (equal/inverse_vol/vol_target/oracle), reusando la matemática de `_compute_target_weights`.
- Generalización de `market_regime.make_entry_filter` para aceptar el factor del sweep (0.25/0.5/0.75) además de "half" (0.5).
- Runner `scripts/run_sizing_exposure_t10_t20.py` + métricas CAGR/Sharpe + CPCV/DSR/PBO.
- Tests offline del harness (naming por convención `tests/`).

Nada de esto cambia flags vivos ni el motor hasta que el veredicto lo autorice (regla 3: display/medición antes que cableado).

## 8. Procedencia de datos y reproducibilidad

- Read-only sobre el cache PIT (`data/pit_signals/`) + SPY 10y en `parquet_cache`; **no se escribe `finanzias.db`**.
- Semilla no aplica (todo determinístico). El comando exacto y el hash de este pre-registro quedan citados en el doc de resultados.
