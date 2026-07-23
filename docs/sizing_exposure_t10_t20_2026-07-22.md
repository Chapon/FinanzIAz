# Resultados — Bloque 10 + 20: sizing por riesgo (Tarea 10) + escalado por régimen (Tarea 20 / R2b)

_Corrida 2026-07-22 (fecha operativa; datos 2016-07 → 2026-07). Pre-registro congelado en `docs/sizing_exposure_prereg_t10_t20_2026-07-22.md` (commit `f24cbd4`), ANTES de codear los brazos. Runner: `scripts/run_sizing_exposure_t10_t20.py`._

## Veredicto

- **Tarea 10 (sizing por riesgo, eje nombre): NO-SHIP.** `inverse_vol` y `vol_target` cuestan ~4 puntos de CAGR sin mejora de Sharpe. → **se renombra la cuenta a `equal_weight`** (cierra la mentira de config N1).
- **Tarea 20 (R2b, escalado por régimen, eje mercado): SHIP.** El escalado a fracción del tamaño en risk-off mejora **Sharpe, CAGR y max DD a la vez**. Es lo primero de la serie T7/T8/T9/T10 que pasa. Se cablea detrás de flag (default OFF; la activación y el factor son decisión de Chapa, patrón E1b).

## Configuración (del pre-registro, sin cambios)

Simulador de cartera real (`analysis/portfolio_sim.py`): `max_positions=5`, capital 50.000, `allow_reentry_while_open=False` (engine-faithful, tarea 9 — por eso el baseline **no** es comparable número-a-número con el B0 de R2), señal PIT de la tarea 7 (41 tickers × 10y, 4025 entradas candidatas), SPY 10y para el régimen (SPY<SMA200, PIT D−1; 16.0% de días risk-off). Métricas en **CAGR/Sharpe/maxDD sobre la curva de equity** (corrige el defecto de la lápida de la tarea 8).

## Resultados

| brazo | CAGR | Sharpe | ΔSharpe | ΔCAGR | maxDD | DDx | local |
|---|---|---|---|---|---|---|---|
| **B0_equal_weight** (baseline) | 19.59% | 1.10 | — | — | 21.6% | — | — |
| S1_inverse_vol | 15.83% | 1.06 | −0.04 | −3.76pp | 20.2% | 0.93 | no |
| S2_vol_target | 15.32% | 1.09 | −0.02 | −4.27pp | 19.0% | 0.88 | no |
| **R2b_f025** | 20.08% | **1.30** | **+0.20** | +0.49pp | **17.5%** | 0.81 | **SÍ** |
| **R2b_f050** | **20.18%** | 1.22 | +0.11 | +0.59pp | 19.1% | 0.88 | **SÍ** |
| R2b_f075 | 19.97% | 1.15 | +0.05 | +0.38pp | 20.5% | 0.95 | no |
| C_S2xf050 (composición) | 15.07% | 1.18 | +0.08 | −4.52pp | 16.2% | 0.75 | no |
| **V_oracle_size** (validación) | **31.20%** | **1.68** | +0.57 | +11.61pp | 20.3% | — | val |

**Descuento por selección múltiple (7 brazos, T=2262 obs diarias):** PBO (CSCV) = **0.190**; brazo seleccionado por Sharpe = **R2b_f025**; DSR = 1.000 (SR0 esperado bajo el nulo = 0.0074).

**Invariantes (verificados ANTES de leer el veredicto):** contabilidad equity-vs-cash OK en los 7 brazos; invariante de exits OK (ninguna variante cambió la salida de una posición abierta); baseline reproduce el equal-weight actual.

## El oráculo hizo su trabajo: atrapó un bug antes del veredicto

En la **primera** corrida el oráculo de validación dio **−0.78% CAGR** — por debajo del baseline. El pre-registro (§4) dice que si el oráculo no se despega, el harness no discrimina sizing y el experimento es **inválido**. El diagnóstico mostró `corr(size_factor, retorno) = 0.999` (el oráculo *sí* sobrepesaba ganadores) pero `final_equity < inicial`: la causa era que mi bloque de sizing **rechazaba** una entrada cuando el notional deseado superaba el cash, en vez de **recortarlo al cash disponible**. Con `m` alto (oráculo=2.0, o baja σ) en el último slot con poco cash, un ganador conocido se descartaba — algo que el equal-weight nunca hace (invierte lo que tiene). Corregido (`portfolio_sim.py`: `notional = min(notional, cash)`, se rechaza solo si ≤0; no-op para el path R2 porque ahí `notional ≤ base ≤ cash` siempre). Tras el fix el oráculo pasó a **31.20% CAGR / Sharpe 1.68**, muy por encima del baseline → el harness discrimina sizing y el veredicto es leíble. **Sin el brazo oráculo, el NO-SHIP de la tarea 10 habría sido un artefacto del bug, no un resultado.**

## Tarea 10 — por qué NO-SHIP

`inverse_vol` (m = median_σ/σ) y `vol_target` (m = 0.20/σ), ambos con σ realizada 60d y recorte [0.25, 2.0]:

- Cuestan **~4 puntos de CAGR** (15.83% y 15.32% vs 19.59%) y **no** mejoran el Sharpe (−0.04, −0.02). Bajan el max DD un poco (20.2% / 19.0% vs 21.6%), pero el kill-criteria pide beneficio en Sharpe **o** CAGR — no hay ninguno.
- La composición C_S2×f050 hereda el costo de CAGR del sizing (−4.52pp) y no lo compensa.
- **El oráculo prueba que no es el harness:** con sizing perfecto (mira el futuro) el mismo mecanismo saca +11.6pp de CAGR. El espacio para explotar sizing existe; la vol realizada por nombre no lo captura.

**Interpretación:** cuarta pieza de la serie que apunta a lo mismo — la **señal disponible por nombre no predice** el resultado suficientemente como para pesar mejor que equal-weight (buy_score sin alpha ref A3; scale-out T7; meta-labeling T9; ahora sizing por σ). Pesar por σ no usa el buy_score, pero σ tampoco separa ganadores de perdedores en este universo/estrategia. Equal-weight es la elección honesta.

**Acción de la tarea 10:** como quedó NO-SHIP, **se renombra el `allocation_mode` de la cuenta a `equal_weight`** para que la config deje de mentir (hoy dice `signal_weighted`, que cae a equal-weight por no estar en `_VOL_SIZED_MODES`). Es un cambio de la DB viva → **acción manual de Chapa** (regla 5).

## Tarea 20 (R2b) — por qué SHIP

Escalar las BUYs a fracción del tamaño en risk-off (SPY<SMA200, PIT D−1):

- **R2b_f025** (0.25× en risk-off): Sharpe **1.30 (+0.20)**, CAGR 20.08% (+0.49pp), maxDD **17.5%** (baja 4.1pp). **R2b_f050** (0.50×): Sharpe 1.22 (+0.11), CAGR **20.18%** (+0.59pp), maxDD 19.1%. Las dos mejoran **las tres** métricas a la vez.
- **R2b_f075** (0.75×) queda marginal (ΔSharpe +0.05, ΔCAGR +0.38pp) → por debajo del umbral; tiene sentido: escalar poco casi no de-riskea.
- Pasa el kill-criteria congelado: beneficio (ΔSharpe ≥ +0.10) **y** riesgo (maxDD **no** sube, baja) **y** PBO 0.19 < 0.5. Reproduce el hallazgo secundario de R2 (medio tamaño: CAGR +0.57pp / DD 19.1% en su corrida con reentry=True) bajo el setting engine-faithful.

**Honestidad sobre el DSR:** el DSR=1.000 (SR0=0.0074) está **saturado** por la granularidad diaria (T=2262) — es el mismo caveat de la tarea 9 ("con n grande casi todo da significativo"); no aporta evidencia. El peso real lo llevan: (1) mejora simultánea de Sharpe+CAGR+DD, (2) PBO=0.19 (estable en los cortes temporales del CSCV), (3) reproducción independiente de R2, (4) respuesta suave al factor (0.25 y 0.50 pasan, 0.75 marginal — no es un valor de filo).

**Honestidad sobre la magnitud:** la ventaja de **CAGR es modesta** (+0.5–0.6pp); el efecto robusto y grande es la **reducción de max DD** (21.6% → 17.5–19.1%) sin costo de retorno — porque en esta estrategia de momentum estar plenamente invertido durante los risk-off fue net-improductivo. Es exactamente lo que el eje "cuánto exponerse" prometía: de-riskear la caída sin pagar el compounding.

**Nota sobre el desglose por régimen:** el retorno medio **por trade** es idéntico entre brazos (el sizing no cambia el retorno por-share de un ciclo, solo el notional) — la diferencia vive en la curva de equity (compounding/DD), que es donde la miden CAGR/Sharpe/maxDD. La tabla por-régimen por-trade es, por eso, descriptiva y no discrimina brazos.

## Qué se shipea

**Enablers (medición, no tocan decisiones vivas):**
- `analysis/risk_sizing.py` — vol realizada 60d, `make_size_weight` (equal/inverse_vol/vol_target/oracle), `precompute_oracle_returns`, métricas CAGR/Sharpe.
- `analysis/portfolio_sim.py` — hook `size_weight` + tope por nombre (`max_weight`) + fix del recorte a cash. Default = comportamiento actual.
- `analysis/market_regime.py` — modo `scale` en `make_entry_filter` (sweep del factor).
- `scripts/run_sizing_exposure_t10_t20.py` + tests offline (`tests/test_sizing_exposure.py`).

**Cableado a decisiones (Tarea 20, SHIP):** el escalado por régimen se cablea en el engine detrás de un flag, **default OFF** — la activación y el **factor** (f025 vs f050) son decisión de Chapa (toca el sizing de las BUYs vivas; mismo patrón que E1b, que shipeó PASS pero OFF-by-default). f025 domina en Sharpe y DD; f050 da el mejor CAGR y es el valor que R2 ya había testeado.

## Reproducir

```
python scripts/run_sizing_exposure_t10_t20.py          # tabla + veredicto
python scripts/run_sizing_exposure_t10_t20.py --json    # payload completo
```
Read-only sobre `data/pit_signals/` + SPY 10y en `parquet_cache`; no toca `finanzias.db`.
