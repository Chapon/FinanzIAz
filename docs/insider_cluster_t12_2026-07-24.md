# Veredicto — Insider cluster buys (Form 4) como fuente de leads (Tarea 12, FORM4)

**Fecha corrida:** 2026-08-11 · **Estado:** **CERRADO NO-SHIP.**
**Pre-registro CONGELADO:** `docs/insider_cluster_prereg_t12_2026-07-24.md` (kill-criteria fijados ANTES de codear).
**Harness:** `scripts/run_insider_cluster_replay_t12.py` · **detector:** `analysis/insider_cluster.py` · **ingester:** `scripts/ingest_form345.py`.

---

## 1. Veredicto

**NO-SHIP.** Ningún brazo pasa el filtro local → `selected_arm = null`, `ship = false`. El
brazo primario `CLU_C3_W15` termina **por debajo de la mediana del baseline aleatorio**
(CAGR −1.05% vs +1.06%): una cartera cuyos BUYs nacen de clusters de compra de insiders,
entrando D+1 con la triple barrera del engine, **rinde peor que entrar al azar** en el mismo
universo con el mismo capital y el mismo exit.

El resultado está **bien powered**: el brazo oráculo (rankea por retorno realizado, look-ahead
deliberado) despega a **CAGR 107.9% / Sharpe 2.93** — el harness detecta calidad de entrada con
enorme sensibilidad, así que el nulo es real y no un harness roto (misma validación que T9/T10/T11b).

Nada se cablea al engine (regla 3). El detector + ingester + harness quedan como **enablers**.

---

## 2. Qué se corrió (fiel al pre-registro)

- **Universo:** S&P 500 (503 símbolos del fallback UNIV1), 10y EOD vía el cache Parquet.
  Precios precargados 503/503 (`prefetch_harness_cache.py -p 10y`).
- **Dato de insiders:** SEC Form 345 quarterly datasets, **2016q1–2026q1** (41 trimestres;
  2026q2 aún no publicado por SEC → 404, sin efecto). 642.133 transacciones no-derivativas sobre
  496 tickers; 17.111 compras open-market `P/A`. Point-in-time por `FILING_DATE` (§3.1).
- **Modo de exit: `analyze_flip`** — la triple barrera completa **con flip `analyze SELL`**, fiel a
  §7. Precómputo PIT de las señales `analyze()` del universo entero: **500 tickers con señal
  (99% cobertura)**, ~1,01 M evaluaciones XGBoost walk-forward (10,76 h). El exit se aplica
  **idéntico** al brazo y al baseline, así que **no confunde** la comparación ΔCAGR (§7).
- **Gate de conteo mínimo (§3.3): PASÓ.** 381 eventos crudos del primario → **289 entradas** tras
  el mapeo al calendario + refractario de 20 ruedas + warmup; 123 tickers distintos. En el rango de
  poder de T11b (340–660). No hubo que escalar a small/mid.
- **Baseline:** Monte Carlo K=500 time-matched por mes calendario al primario (§4.1). Semillas fijas.

---

## 3. Resultados

Baseline random (K=500): **CAGR** mediana 1.06% · p95 4.63% | **Sharpe** mediana 0.16 · p95 0.53 |
**maxDD** mediana 23.8%.

| brazo | CAGR | Sharpe | maxDD | tomadas | expos | local |
|---|---:|---:|---:|---:|---:|:--:|
| **CLU_C3_W15** (primario) | **−1.05%** | −0.05 | 32.8% | 280 | 60% | no |
| CLU_C2_W15 | 0.24% | 0.09 | 42.2% | 577 | 82% | no |
| **CLU_C4_W15** (mejor) | **1.75%** | 0.24 | 16.7% | 187 | 49% | no |
| CLU_C3_W10 | −0.50% | 0.00 | 25.8% | 262 | 59% | no |
| CLU_C3_W30 | −0.18% | 0.04 | 33.4% | 306 | 61% | no |
| CLU_C3_W15_senior | **−3.26%** | −0.30 | 30.7% | 208 | 49% | no |
| **V_oracle_entry** | **107.9%** | 2.93 | 11.0% | 56 | 17% | val |

**El brazo primario (289 entradas) es negativo y peor que el azar.** El mejor brazo, `CLU_C4_W15`
(4 insiders), es el único por encima de la mediana (1.75% vs 1.06%) pero **muy por debajo del p95**
(4.63%). El brazo **senior** (exige ≥1 officer en el cluster) es **el peor de todos** (−3.26%) —
requerir un CEO/CFO en el cluster **empeoró** la señal, en contra de la intuición.

---

## 4. Kill-criteria (§6) — cada uno

Evaluado sobre el **mejor** brazo por Sharpe (`CLU_C4_W15`), que es el candidato natural:

| # | criterio | umbral | resultado | |
|---|---|---|---|:--:|
| 1 | CAGR y Sharpe > p95 random | CAGR>4.63% ∧ Sharpe>0.53 | CAGR 1.75%, Sharpe 0.24 | **FALLA** |
| 2 | ΔCAGR ≥ +2.0 pp vs mediana | +2.0pp | +0.69pp (primario: −2.11pp) | **FALLA** |
| 3 | maxDD ≤ 1.5× mediana | ≤35.7% | 16.7% | pasa |
| 4 | DSR>0.5 ∧ PBO<0.5 (6 brazos) | — | **PBO 0.56** (>0.5); DSR n/d | **FALLA** |
| 5 | signo ≥0 en cada régimen | los 4 | falla (ver §5) | **FALLA** |
| 6 | LOTO no invierte el signo | — | n/d (ningún brazo pasa local) | — |

Falla **1, 2, 4 y 5**. Basta el 1 para el NO-SHIP; el resto lo confirma.

---

## 5. El hallazgo — la señal contraria aparece en el stress, pero solo en el cluster estricto

Desglose por régimen del retorno medio por trade (pts) — **la prueba clave del pre-registro (§6.5)**:

| régimen | CLU_C3_W15 (primario) | CLU_C4_W15 (estricto) |
|---|---:|---:|
| bull_normal | +0.18 (n=217) | **−0.37** (n=149) |
| stress_2018q4 | +0.87 (n=14) | **+2.23** (n=8) |
| stress_covid_2020 | **−4.40** (n=21) | **+6.20** (n=13) |
| stress_bear_2022 | +0.55 (n=28) | **+2.89** (n=17) |

Dos lecturas, ambas fatales para el ship pero informativas:

- **El primario se hunde en el crash rápido** (COVID-2020: −4.40). Buscar dips con ≥3 insiders atrapa
  demasiado dip-buying que siguió cayendo; el ATR stop lo saca en la continuación bajista. En bull su
  retorno es trivial (+0.18) — debajo de lo que da el azar.
- **El cluster estricto (C4) SÍ muestra la hipótesis pre-registrada**: es **positivo en los tres
  buckets de stress** (2018Q4 +2.23, COVID +6.20, bear-2022 +2.89) y **negativo en bull** (−0.37).
  La conducta contraria/de-valor —ganar en las caídas, ceder en el bull— **existe**, pero (a) queda
  tapada por la masa de trades de bull (149 de 187), (b) no clarea el p95, (c) el n de stress es
  finísimo (~38 trades en total) y (d) elegir C4 entre 6 brazos es overfitting (PBO 0.56).

**Es el espejo exacto de T11b.** La anomalía de ruptura (T11b, momentum) tenía edge en bull y **se
rompía en bear**; el insider-cluster (FORM4, contrario) tiene edge en el stress y **se rompe en bull**.
Ninguna de las dos fuentes event-driven es robusta a través de los regímenes con la **misma** estructura
de salida (triple barrera / momentum): un exit trend-following pelea con una entrada contraria, igual que
peleaba con una de ruptura en el otro sentido.

---

## 6. Caveats (declarados)

- **Exit `analyze_flip` aplicado simétricamente** a brazo y baseline → la comparación mide la **entrada**
  (cluster vs random), no el exit; el NO-SHIP relativo es robusto a la elección de exit. Un follow-up
  `--signals-mode atr_only` es barato (sin precómputo) si se quiere confirmar el nivel absoluto, pero no
  cambiaría que la entrada de cluster no le gana a la selección aleatoria con el exit fijo.
- **Survivorship** (§3.2): membresía S&P 500 actual → CAGR absoluto sobreestimado en los dos brazos; se
  cancela en el ΔCAGR contra el baseline del mismo universo.
- **n de stress finísimo** (14/21/28 primario; 8/13/17 C4): cualquier lectura por régimen cuelga de pocas
  decenas de trades. Anotado como en T11b.
- **`auto_adjust=True`** y el lookahead transversal habitual de backtests largos: presente al leer niveles.

---

## 7. Decisión y enablers

- **NO-SHIP.** No se cablea nada al engine (regla 3). Sin flag, sin gate, sin sizing.
- **Enablers que quedan** (útiles como feature futura del meta-modelo, mismo criterio que T9/T11b):
  `analysis/insider_cluster.py` (detector, 24 tests) + `scripts/ingest_form345.py` (ingester Form 345)
  + `scripts/run_insider_cluster_replay_t12.py` (harness, 12 tests) + `data/sp500_universe.txt`.
- **Collector vivo `insider_transactions` (tabla alembic):** decisión **aparte** del veredicto del brazo
  (§6 del pre-registro). Como el brazo no cablea, no hay urgencia de acumular el dato point-in-time hacia
  adelante; queda como idea, no como acción.
- **Idea derivada (backlog, requiere pre-registro propio):** una variante `cluster estricto (C≥4) ×
  entrada solo en risk-off` — el único bolsillo donde la señal aparece (positiva en los 3 stress) es el
  cluster estricto en régimen bajista. Choca con la masa de bull que la tapa; habría que **gatear la
  entrada por régimen** (reusa T20) y aceptar que sería una señal de nicho, no de todo tiempo. Encolar
  detrás de lo que haya, con su propio kill-criteria — igual que la `anomalía × gate de régimen` de T11b.

---

## 8. Reproducción

```
python scripts/ingest_form345.py --start 2016q1 --end 2026q1 --universe data/sp500_universe.txt --dest data/form345
python scripts/prefetch_harness_cache.py data/sp500_universe.txt -p 10y -b 20
python scripts/precompute_pit_signals.py --universe data/sp500_universe.txt --period 10y --warmup 250
python scripts/run_insider_cluster_replay_t12.py --signals-mode analyze_flip
```

Suite offline (detector + harness): **1477 passed, 3 skipped** (Windows/Anaconda). Los datos bajados
(Form 345 + precios + señales PIT) son gitignored y se cachean una única vez.
