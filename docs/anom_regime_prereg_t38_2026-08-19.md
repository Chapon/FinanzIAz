# Pre-registro CONGELADO — La ruptura de momentum condicionada a régimen (Tarea 38, ANOM-REGIME)

**Fecha:** 2026-08-19 · **Estado:** congelado ANTES de codear el harness (regla 2).
**Ref:** `docs/BACKLOG.md` tarea 38 · `docs/anomaly_signal_t11b_2026-07-23.md` §"Idea derivada"
(de dónde sale) · `docs/anomaly_signal_prereg_t11b_2026-07-23.md` (la población y los criterios que
se reusan) · `docs/sizing_exposure_t10_t20_2026-07-22.md` (T20, el overlay shipeado y **activo**) ·
skill `backtest-replay-harness` §"Brazos condicionados a régimen".

Fija población, brazos, la regla de decisión y los sanity **ANTES de correr**. Nada se re-decide
después de ver resultados. Si el candidato no supera el umbral, se documenta NO-SHIP y no se cablea
ninguna fuente de entradas nueva.

---

## 0. Por qué esta tarea y no otra — el cambio de criterio que la habilita

**Decisión de Chapa, 2026-08-19:** un candidato **puede ser una política condicionada a régimen**, y
eso cuenta como candidato de primera clase. El criterio C5 de la serie (signo estable en los cuatro
regímenes) seguía exigiendo **una sola regla incondicional**, y así mató a las tres tareas más
prometedoras — entre ellas **la única con alpha medido**. Lo que cambia es **qué puede ser un
candidato**, no el umbral, y **no** se saca ningún período de la muestra (skill
`backtest-replay-harness`, §"Brazos condicionados a régimen").

**Qué se miró ANTES de congelar** (auditoría del instrumento):

- **Se re-estableció el nivel de T11b con las correcciones posteriores.** Su 12.89% publicado se
  midió con el **fill legacy (look-ahead)**, **5 slots** y **41 tickers** — antes de T27, T33 y T34.
  Re-corrido con el fill honesto y la config de la cuenta viva (10 slots, 127 tickers):

  | config | `A_k2.0_m1.5` CAGR | Sharpe | maxDD | azar (mediana / p95) |
  |---|--:|--:|--:|--:|
  | publicada (legacy) | 12.77% | 1.22 | 12.0% | 3.8% / 6.9% |
  | **honesta + cuenta viva** | **10.24%** | **1.06** | 12.9% | 3.0% / 6.5% |

  **El edge sobrevive las dos correcciones que hundieron o dieron vuelta a todo lo demás de la
  serie**, aunque encoge −2.53 pp. Sigue por encima del **p95** del azar, y LOTO (sacando AMD) da
  8.85%. **Y el brazo ganador es el mismo (`k2.0_m1.5`) en las dos configs** — eso es evidencia de
  robustez, no de selección.
- **El detector de régimen es point-in-time y no mira el futuro:** `RegimeSeries.is_risk_off` busca
  la última fecha **estrictamente menor** que la pedida (`market_regime.py:56`) y hace fail-open
  (risk-on) sin historia suficiente. Verificado en código.
- **`live_gates` NO está cableado en el runner de T11b** — es un desvío que esta tarea corrige (§4).

**Lo que deliberadamente NO se miró:** **ningún resultado de ningún brazo con el gate puesto.** El
eje de esta tarea es exactamente ése.

## 1. La pregunta

T11b midió que el detector de ruptura **tiene alpha real** (le gana al azar con holgura, sobrevive
LOTO, PBO 0.476) y que **falla sólo por régimen**: pierde comprando rupturas al alza en mercados
bajistas — `bear_2022` **−2.01 pts/trade**, `2018Q4` **−0.30**, contra `bull_normal` **+1.57** y
`covid_2020` **+1.71**. Es el crash-risk documentado del momentum.

> **¿Condicionar la señal al régimen —con el mismo detector que la cuenta ya usa— convierte un edge
> con crash-risk en uno robusto?**

Es la hipótesis que la evidencia de momentum predice (vol-scaling / régimen corta el crash), y es la
**versión legítima** de "aislar los períodos malos": el sistema los **detecta en vivo y reacciona**,
en vez de que se los borre del examen.

## 2. Brazos (CONGELADO)

Señal fija en **`A_k2.0_m1.5`** (el brazo de decisión de T11b) para **todos** los brazos: el eje de
esta tarea es el **gate**, no la calibración del detector. Fijarla no es selección post-hoc — es el
brazo que T11b pre-registró como decisión **y** el que gana en las **dos** configs (§0).

| brazo | gate | qué es |
|---|---|---|
| `U_ungated` | ninguno | **BASELINE.** El brazo de T11b tal cual, en config viva. Es contra quien se mide el gate. |
| **`G_half`** | `half` (factor **0.50** en risk-off) | **CANDIDATO PRIMARIO.** Reusa **exactamente** el overlay de T20, ya validado y **activo** en la cuenta viva: no pide flag nuevo ni mecanismo nuevo. |
| `G_hard` | `hard` (0.0 en risk-off) | Secundario. Es lo que la idea derivada de T11b nombró, y lo que en R2 fue **catastrófico** para el pipeline principal. |
| `G_confirm` | `confirm` (0.0 con `confirm_days=5`) | Secundario. Evita whipsear con el detector. |
| `G_scale25` | `scale` (factor 0.25) | Secundario, para ver la dosis-respuesta del factor. |
| `AZAR_TIME_MATCHED` | — | Sanity: baseline Monte Carlo de entradas aleatorias time-matched, K=500, `seed=12345` (el de T11b). |
| `V_oracle_entry` | — | Sanity: oráculo de entrada (mira el futuro). Valida que el instrumento vea calidad de entrada. |

**El candidato primario está declarado de antemano y por un motivo ajeno al resultado:** es el único
que se shipea **sin código nuevo en el gate**, porque el factor 0.50 en risk-off ya está cableado y
activo. Los otros tres son descriptivos y **no pueden ganarle el lugar al primario después de ver
los números** — si `G_half` falla, la tarea es NO-SHIP aunque otro brazo pase (§6, caso partido).

## 3. Población y config (CONGELADO)

- **Universo:** `data/harness_universe_live_acct2.txt` (**127** tickers con PIT). *No* el de 41 con
  el que corrió T11b.
- **Cartera:** `portfolio_sim`, `max_positions=10` (cuenta viva), `initial_capital=50.000`,
  `cap_days=20` (el de T11b — la señal es de horizonte corto), `CostModel()`,
  `allow_reentry_while_open=False`, ATR con los parámetros vivos (`stop_mult=2.0`, `tp_mult=4.0`,
  `period=14`, trailing on).
- **`eval_mode="touch"`, `fill_mode="decision"`, `live_gates=True`** — la regla viva, el fill honesto
  (T33) y los gates de re-entrada del engine modelados (T34). **T11b no tenía ninguno de los tres.**
- **Régimen:** `build_regime_series` sobre barras de SPY, `SMA_WINDOW=200`, el mismo objeto que usa
  T20 en vivo.
- **Sensibilidad** a `--max-positions 5`. El veredicto se dicta a **10**.

## 4. Cómo se mide la robustez de régimen — C5 reformulado (el núcleo del cambio)

**El problema:** un gate que deja de operar en el bear tiene ~cero trades ahí, así que el
Δ(ret medio **por trade**) es vacío y el brazo **pasaría el criterio sin hacer nada**. Medir por
trade premiaría a cualquier cosa que se apague.

**La regla congelada:** para cada uno de los cuatro regímenes se mide el **retorno de la CARTERA
durante los días de ese régimen** (con el cash contando como 0), no el retorno por trade. Así:

- No operar en el bear **se premia** si evita la caída,
- y **se castiga** si el costo es perderse la recuperación.

Se reporta **`n_trades` por régimen** al lado del retorno, para que se vea si el brazo pasó porque le
fue bien o porque no jugó. Es descriptivo, no criterio.

## 5. Sanity del instrumento (si falla alguno, la corrida es INVÁLIDA y no hay veredicto)

1. **Contabilidad:** `|equity_curve[-1] − final_equity| / final_equity ≤ 1e-6` en todos los brazos.
2. **El instrumento ve calidad de ENTRADA:** `CAGR(V_oracle_entry) ≥ CAGR(U_ungated) + 20.00 pp`.
   T11b midió el oráculo en 61.37% contra 12.89% del brazo; el umbral se pone muy por debajo de esa
   brecha porque acá se corre en otra config, pero si el oráculo no despega el harness no discrimina.
3. **El baseline reproduce el edge de T11b:** `U_ungated` tiene CAGR **> p95** del Monte Carlo
   aleatorio time-matched. Si el edge no está, no hay nada que condicionar y la tarea se cae sola.
4. **El gate muerde:** `G_half` y `U_ungated` difieren en ≥ **10%** de los trades
   (par `ticker`+`entry_date`, helper `trade_overlap`) **o** en ≥10% del capital desplegado. Mismo
   umbral y mismo helper que 26b §5.3, T34 y T37 — **no** se calibra uno nuevo.
5. **El detector es PIT:** un test sobre serie sintética verifica que `is_risk_off(d)` **no** depende
   de la barra de `d` ni de ninguna posterior. Se verifica por unit test, no en agregado.
6. **El gate no toca salidas:** invariante de R2 (§2 de su pre-registro), re-verificada — el
   `entry_filter` jamás se consulta para salir.

## 6. Regla de decisión (CONGELADA)

**Candidato** = `G_half`. **Baseline** = `U_ungated`. 10 slots. Se cablea **sólo si pasa las siete**:

| # | Criterio | Umbral |
|---|---|---|
| **C1** | ΔCAGR(`G_half` − `U_ungated`) | ≥ **0.00 pp** (no puede costar retorno) |
| **C2** | **Lo que la tarea existe para arreglar:** retorno de cartera en **cada uno** de los 4 regímenes, `G_half` vs `U_ungated` | ≥ **−0.50 pp** en los cuatro, **y estrictamente mejor en `bear_2022` y `2018Q4`** |
| **C3** | maxDD(`G_half`) | ≤ maxDD(`U_ungated`) — **no puede empeorar** |
| **C4** | Sharpe(`G_half`) | ≥ Sharpe(`U_ungated`) **y** > p95 del Monte Carlo aleatorio |
| **C5** | Block-bootstrap pareado sobre Δ(retorno diario) vs `U_ungated`, bloques 20 d, 2000 resamples, `seed=12345` | **IC95% inferior > −0.005** (no destruye valor) |
| **C6** | **PBO (CSCV)** sobre la rejilla de gates | < **0.5** |
| **C7** | Sensibilidad: el signo de C1 y la mejora de C2 en `bear_2022` se mantienen a **5 slots** | las dos |

**Por qué C1 pide sólo ≥ 0 y C2 hace el trabajo:** el gate **no existe para agregar retorno**, existe
para sacar el crash-risk. Pedirle además que gane CAGR sería pedirle que resuelva dos problemas y
condenarlo por el que no le toca. Lo que sí se le exige es que **no cueste** retorno agregado (C1),
que **mejore donde el brazo sangraba** (C2, con la exigencia estricta en los dos regímenes malos) y
que **no empeore el riesgo** (C3).

**Casos partidos, resueltos ex ante:**

- **C1 pasa y C2 falla** → **NO-SHIP.** Si el gate no arregla el bear, no sirve para nada: ése era el
  único motivo por el que T11b no shipeó.
- **C2 pasa y C1 falla** (el gate arregla el bear pero cuesta demasiado retorno) → **NO-SHIP**, y se
  reporta **cuánto** cuesta: es el precio del seguro, y con el número se puede volver con otro factor
  en un pre-registro propio.
- **`G_half` falla y otro brazo pasa** → **NO-SHIP igual.** El primario está declarado en §2 y no se
  reemplaza después de ver resultados. El brazo que pasó se reporta como **lead** y necesita su
  propio pre-registro (patrón T34 → T37).
- **`U_ungated` no le gana al azar** (sanity 3) → **corrida INVÁLIDA**: el edge de T11b no sobrevivió
  a la config viva y **la premisa de la tarea se cayó**. Es publicable y cierra la línea.
- **Falla cualquier otro sanity del §5** → **corrida INVÁLIDA**, sin veredicto. No se re-especifica
  nada para salvarla (precedente T26; T34 ya pagó una).

## 7. Qué se cablea si pasa / qué NO se toca

- **Si pasa las siete:** el detector de anomalía entra como **fuente de leads adicional** en el
  pipeline de entradas, **con el overlay de régimen de T20 ya aplicado** (que es el que la cuenta ya
  corre). Es una **fuente de entradas nueva en vivo**, así que: se avisa explícitamente, se shipea
  con tests del pipeline y **entra apagada detrás de un flag** hasta que Chapa la prenda.
- **Qué NO se decide acá aunque pase:** cómo se **mezclan** los leads de anomalía con los de
  `analyze()` cuando compiten por el mismo slot. Esta tarea mide la señal **standalone**; la
  integración (ranking entre fuentes, cupo por fuente) es **otra pregunta con pre-registro propio** —
  y ojo, porque la T9/T21 ya mostraron que rankear mal es **activamente caro**.
- **NO se toca:** la calibración del detector (`k`, `m` quedan en 2.0/1.5); el factor de T20 (0.50,
  ya validado); las salidas; el sizing; el `buy_score`.

## 8. Qué NO se modela (caveats antes de correr)

- **Survivorship:** 127 sobrevivientes. Acá pesa **menos** que en T37 (no se está sacando un
  guardrail) pero infla igual el nivel de todos los brazos. No afecta la comparación gated-vs-ungated,
  que es lo que decide.
- **El detector de régimen es un único indicador** (SPY vs SMA200). Es el que la cuenta usa, así que
  medir con él es medir la política real — pero su calibración **no** se re-abre acá.
- **Sampleo de ~15 min**, **ventana de `analyze()`**, **overlay T20 de sizing**: desvíos ya declarados
  en `harness_config`, ortogonales a este eje.
- **`cap_days=20`** (no 250, como el resto de la serie): es el horizonte que T11b pre-registró para
  esta señal y se mantiene para que el resultado sea comparable con su veredicto.

## 9. Plan de ejecución

1. **Cablear `live_gates` y el universo/slots vivos en el runner de T11b** (`--live-gates`,
   `--universe` ya existe). Default OFF para no mover el veredicto publicado.
2. **Runner** `scripts/run_anom_regime_t38.py`: los cuatro brazos de gate + `U_ungated` + los dos de
   sanity, el retorno de cartera **por ventana de régimen** (§4), el bootstrap pareado, el PBO sobre
   la rejilla de gates, el AND de los siete criterios y el banner de `harness_config.announce()`.
3. **Tests offline:** el detector es PIT sobre serie sintética (§5.5); el `entry_filter` no se
   consulta para salir (§5.6); el retorno por ventana de régimen cuadra con la curva de equity; el
   helper del veredicto aplica el AND de los siete y **cada** caso partido del §6.
4. **Correr** (10 slots + sensibilidad a 5), sin red, sin tocar `finanzias.db`.
5. **Veredicto** en `docs/anom_regime_t38_<fecha>.md`, con el **retorno por régimen de los dos
   brazos** al frente — es el número que resume la tarea, se shipee o no.

**Congelado. Cualquier cambio a §2–§7 después de ver un resultado invalida el pre-registro.**
