# Veredicto — Detector de anomalía precio/volumen (Tarea 11, Brazo B) · **NO-SHIP**

**Fecha:** 2026-07-23 · **Pre-registro congelado:** `docs/anomaly_signal_prereg_t11b_2026-07-23.md` (`57976bc`).
**Harness:** `scripts/run_anomaly_replay_t11b.py` · **Detector:** `analysis/anomaly_signal.py`.
**Corrida:** 41 tickers × 10y, `max_positions=5`, capital 50k, K=500 carteras Monte Carlo, sin red, sin tocar `finanzias.db`.

## Veredicto

**NO-SHIP.** El detector **tiene señal real** (le gana a entrar al azar con holgura), pero **falla el
kill-criteria de robustez de régimen** (§6.5, congelado): pierde plata comprando rupturas en mercados
bajistas. No se cablea. El detector queda como **enabler** (disponible para una variante regime-gated y
como feature del meta-modelo futuro).

## Resultados (K=500)

Baseline random time-matched (K=500): **CAGR mediana 3.9% · p95 7.3% · Sharpe mediana 0.57 · p95 1.00 · maxDD mediana 12.7%**.

| brazo (k, m)        | CAGR   | Sharpe | maxDD | tomadas | ofrec. | expos | pasa local |
|---------------------|-------:|-------:|------:|--------:|-------:|------:|:----------:|
| A_k1.5_m1.5         | 13.41% | 1.11   | 16.7% | 661     | 843    | 89%   | SI |
| A_k1.5_m2.0         | 11.57% | 1.15   | 12.4% | 466     | 512    | 76%   | SI |
| A_k1.5_m3.0         |  4.29% | 0.75   |  9.6% | 189     | 191    | 46%   | no |
| A_k2.0_m1.5 **(decisión)** | **12.89%** | **1.24** | 12.0% | 420 | 467 | 72% | **SI** |
| A_k2.0_m2.0 (primario) |  8.57% | 1.00 | 12.6% | 340   | 360    | 64%   | SI |
| A_k2.0_m3.0         |  3.93% | 0.75   |  9.6% | 157     | 159    | 42%   | no |
| A_k2.5_m1.5         |  5.68% | 0.90   |  7.6% | 222     | 234    | 51%   | no |
| A_k2.5_m2.0         |  4.51% | 0.76   |  8.6% | 201     | 212    | 48%   | no |
| A_k2.5_m3.0         |  4.00% | 0.85   |  6.1% | 123     | 124    | 35%   | no |
| **V_oracle_entry**  | **61.37%** | **3.45** | 7.5% | 77 | 360 | 26% | validación |

- **Brazo de decisión** (mejor Sharpe entre los que pasan local): **A_k2.0_m1.5** — CAGR 12.89% / Sharpe 1.24.
- **PBO (CSCV) = 0.476** (< 0.5, pasa, borderline) · **DSR = 0.998** (SR0=0.0181, T=2257 obs).
- **LOTO** (sacando AMD, el de mayor aporte): CAGR 10.22% → **el edge sobrevive**.
- **Régimen — ret medio por trade (pts):** bull_normal **+1.57** (n=380), covid_2020 **+1.71** (n=10),
  2018Q4 **−0.30** (n=10), **bear_2022 −2.01** (n=20). **Signo NO estable → falla §6.5.**

## Por qué NO-SHIP (y por qué igual es un hallazgo)

1. **La señal es real, no ruido.** El brazo de decisión da CAGR 12.89% / Sharpe 1.24 contra un baseline
   de **entradas aleatorias time-matched** (mediana 3.9% / p95 7.3% / Sharpe p95 1.00). Le gana al azar
   por mucho, sobrevive LOTO y tiene PBO < 0.5. **A diferencia de la tarea 9** (buy_score, AUC 0.498 = sin
   alpha), acá **sí hay edge** de selección/timing. El oráculo (CAGR 61%, Sharpe 3.45) confirma que el
   harness detectaría una señal robusta si existiera — el veredicto es real, no un artefacto de potencia.

2. **Pero es un edge direccional de bull, no robusto.** El kill-criteria §6.5 (congelado ANTES de correr)
   exige signo positivo o neutro en **cada** régimen. El brazo de decisión **pierde en bear_2022
   (−2.01 pts/trade) y 2018Q4 (−0.30)**: comprar una ruptura al alza en un bear market es, sistemáticamente,
   una **trampa alcista**. Es el crash-risk documentado del momentum (research §3). Honrando la disciplina
   de kill-criteria upfront (no se relaja tras ver el resultado), **NO-SHIP**.

3. **El volumen no aporta — la "anomalía" es momentum de precio.** El eje `m` (múltiplo de volumen sobre
   ADV20) es **monótonamente neutro-a-dañino**: subir `m` recorta la muestra y **baja** el CAGR
   (m1.5→13.4% … m3.0→4.3% con k fijo en 1.5). El trabajo lo hace la ruptura de **precio** (`k`); exigir
   más volumen solo tira buenas entradas. O sea: el "detector de anomalía precio/volumen" se comporta como
   un **detector de ruptura de momentum**, y hereda su virtud (edge sobre el azar) y su defecto (colapsa en
   régimen bajista). Coherente con el research §3 (momentum es el factor robusto, con crash-risk que se
   mitiga con vol-scaling / régimen).

## Idea derivada (para el backlog) — variante regime-gated

El hallazgo apunta a un cierre natural con lo ya shipeado: **la ruptura de momentum solo pierde en
risk-off**, y **T20 (escalado por régimen, ACTIVO) ya sabe detectar risk-off**. Una variante
**`anomalía × gate de régimen`** (disparar el candidato solo en risk-on, o escalarlo con el mismo
overlay T20) podría convertir un edge con crash-risk en uno robusto — exactamente lo que la evidencia de
momentum predice (vol-scaling/regime corta el crash a la mitad). **Es una variante NUEVA:** requiere su
propio pre-registro y paga su costo de DSR (no se retrofitea acá). Encolar detrás del Brazo A honesto.

## Estado del Brazo A (PEAD earnings honesto)

Sigue **bloqueado por datos**: `analyst_estimate_snapshots` tiene ~7 semanas (2026-06-06..07-22, 37 días,
52 tickers) < 1 temporada de pares (ticker, print) con consenso previo. Se desbloquea con T-CAT-5b
(≥1–2 temporadas más, meses). El harness y el detector de este Brazo B quedan listos para reusar.

## Qué queda como enabler

- `analysis/anomaly_signal.py` — detector puro (16 tests, `tests/test_anomaly_signal.py`).
- `scripts/run_anomaly_replay_t11b.py` — harness reutilizable (baseline MC time-matched, oráculo de
  entrada, CPCV/DSR/PBO; 6 tests, `tests/test_anomaly_runner.py`).
- El dato de anomalías acumulado sirve como **feature del meta-modelo** futuro (mismo criterio que T9).

**Serie T7/T8/T9/T10/T11b:** T7 (aflojar SELL) sin señal, T8 (régimen hard) dañino, T9 (ranking) sin alpha,
T10 (sizing) sin alpha, **T20 (escalado por régimen) el que pasó**, T11b (anomalía) **edge real pero no
robusto por régimen**. El eje que rinde sigue siendo *cuánto/cuándo exponerse por régimen*, no la señal
por-nombre — y la anomalía podría sumar si se la subordina a ese eje (variante regime-gated).
