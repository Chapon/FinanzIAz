# Pre-registro CONGELADO — El turno del día decidido por un EVENTO (Tarea 49, PRIO-EVENT)

**Fecha:** 2026-08-20 · **Estado:** congelado ANTES de codear.
**Ref:** `docs/BACKLOG.md` tarea 49 · `docs/anom_profile_t45_2026-08-20.md` §3 (de dónde sale el
+4.21 pp) · `docs/rank_neutral_prereg_t39_2026-08-19.md` (la metodología de medir una política de
orden: pureza de la clave, control como distribución, bracket; se **reusa**) ·
`docs/rank_neutral_t39_2026-08-19.md` y `docs/ranking_t21_2026-08-12.md` (el baseline vivo) ·
`docs/regime_power_t46_2026-08-19.md` §4 (el criterio de régimen) ·
`docs/stop_cal_t26_2026-08-13.md` (la lección del control **igualado en tasa**) ·
`docs/BACKLOG.md` tareas 48 y 50 (los dos desvíos que obligan a los sanity de reproducción).

---

## 0. La parte incómoda, primero

**Conozco el número que motiva la tarea al escribir esto.** La 45 midió, como **descriptivo**, que
darle prioridad al candidato de anomalía en el desempate del día vale **+4.21 pp de CAGR** (7.92% vs
3.71%) y **−3.4 pp de maxDD**, con IC95% [−0.25, +8.47] y el 73,9% de los trades distintos. Y sé que
el propio veredicto de la 45 declaró que ese número **está confundido** con *"cualquier cosa menos
alfabético"*.

Los cuatro recaudos:

1. **El control que faltaba es el gate.** C2 y C5 comparan el candidato contra **20 brazos de
   prioridad ALEATORIA igualada en tasa** —mismos días, misma cantidad de prioridades por día, mismo
   pool— con el mismo `buy_score` de fondo. Es la lección de la **T26** (*"el umbral va contra el
   control igualado, no contra el baseline"*) aplicada al eje del turno. Si el +4.21 pp fuera
   *"desordenar ayuda"*, los 20 controles lo replicarían y el candidato no despegaría.
2. **El candidato es MÁS chico que el brazo que dio el +4.21 pp.** Aquel usaba el pool **unido**
   (`analyze BUY` ∪ anomalía), así que mezclaba *"prioriza 1.236"* con *"agrega ~316 candidatos
   nuevos"*. Acá el candidato es una **re-ordenación pura** del pool que el engine **ya tiene**: sólo
   pueden ser priorizadas las entradas que son `analyze BUY` **y** anomalía. Se le saca a propósito la
   parte que aportaba candidatos nuevos.
3. **Se corrige la tenencia hacia la del engine.** El +4.21 pp se midió con `cap_days=20` (heredado
   del marco de la T11b), que es un time-stop de 20 días que el engine **no tiene**. Acá se decide con
   **`cap_days=250`**, el de la familia T21/T23/T26/T39. Es un cambio adverso conocido: no hay ninguna
   garantía de que el efecto sobreviva a la tenencia larga. Cierra de paso la **tarea 50**.
4. **El baseline es el del engine, no el que dio el número.** El +4.21 pp era contra **alfabético**;
   acá el baseline es **`B1_score`**, que es lo que el engine ejecuta. Eso hace el umbral **más fácil**
   (la T21/T39 midieron que el score rinde *por debajo* del alfabético), y por eso mismo el alfabético
   entra como **descriptivo obligatorio** y el confound queda cubierto por C2/C5, no por la elección
   del baseline.

**Está escrito de antemano que es plausible que esto cierre NO-SHIP**, y sería un éxito de la tarea.

---

## 1. La pregunta

Con **143.096 candidatos `analyze BUY` para 10 slots** (~50:1), la pieza del motor que más veces se
ejecuta es el **desempate del día**. La serie midió **seis veces** que la clave que se usa hoy —el
`buy_score`— no tiene alpha (`corr −0.0259`, AUC 0.498, por debajo de la banda **entera** del azar en
la T21), y la **39** cerró NO-SHIP al reemplazarla por un orden neutro: sacarle la decisión al score no
alcanzó.

La 45 abre una posibilidad distinta, y es la primera de la serie que **no es un score**:

> **¿Darle el turno del día al candidato sobre el que ocurrió un EVENTO —una ruptura de momentum
> confirmada por volumen ese mismo día— le gana al desempate que corre hoy, y le gana a priorizar al
> azar a la misma tasa?**

No es una predicción sobre el futuro del nombre: es un hecho del día. Y no cuesta candidatos nuevos —
es un cambio de **clave de orden**, la intervención más barata y más reversible del motor.

---

## 2. Brazos (CONGELADO)

Lo único que cambia entre brazos es el **orden de los candidatos del mismo día** (`rank_score` de
`portfolio_sim`). Entradas, salidas, costos, gates y capital son idénticos.

Sea `ANOM` = las entradas del detector `A_k2.0_m1.5` (`AnomalyParams(k=2.0, m=1.5)`, warmup 250) que
**además** son `analyze BUY`, y `n_d` = cuántas hay en la fecha `d`.

| brazo | clave de orden | qué es |
|---|---|---|
| **`B1_score`** | `buy_score` (desc) | **BASELINE — es lo que corre hoy** |
| **`E_prio_anom`** | `10 + buy_score` si ∈ `ANOM`, si no `buy_score` | **CANDIDATO — re-ordenación PURA del pool del engine** |
| **`R_rand_k`, k=0..19** | idem, pero las `n_d` prioridades del día van a los tickers con mayor `neutral_rank(60000+k, d, t)` **entre los candidatos de ese día** | **CONTROL IGUALADO EN TASA** — mismos días, misma cantidad, mismo pool |
| `A_alpha` | ninguna (alfabético) | **descriptivo obligatorio** — el baseline contra el que se midió el +4.21 pp |
| `E_merged_prio` | idem `E_prio_anom`, pero sobre el pool **unido** | **descriptivo** — el brazo de la 45, para el puente con su número |
| `ORACULO_PRIO` | prioridad, a la misma tasa, al candidato de mejor **retorno realizado** del día | sanity (mira el futuro) |
| `ANTI_ORACULO_PRIO` | idem al peor | sanity |

**El control es una distribución, no un camino** (metodología de la T39 §4.1): C2 se lee contra el
**p95** de las 20 semillas y C5 contra su **serie diaria promedio**. El candidato, en cambio, es
**determinístico** — no hay semilla que elegir, y por eso no hay ningún grado de libertad que ajustar
después de ver los números.

**La clave es pura** (T39 §5.7): `neutral_rank(seed, fecha, ticker)` ya es una función pura y el
conjunto de candidatos del día sale de `entries`, que es **idéntico entre brazos**. Así que "los `n_d`
de mayor `neutral_rank` del día" es determinístico y no depende del orden de las llamadas ni del estado
de la cartera.

---

## 3. Población y config (CONGELADO)

- **Universo:** `data/harness_universe_live_acct2.txt` (**127** tickers con PIT).
- **Entradas:** eventos `analyze() = BUY` point-in-time — 143.096 (el pool del engine, sin agregar
  nada). El descriptivo `E_merged_prio` es el único que corre sobre el pool unido.
- **Cartera:** `portfolio_sim`, `max_positions=10`, `initial_capital=50.000`, **`cap_days=250`**,
  `CostModel()`, `allow_reentry_while_open=False`, `AtrParams()` default.
- **`eval_mode="touch"`, `fill_mode="decision"`, `live_gates=True`** — la regla viva (26b), el fill
  honesto (T33) y los gates de re-entrada (T34), igual que la 39, la 45 y la 47.
- **Sin overlay de régimen T20** — ortogonal al orden; afuera por atribución limpia.
- **Sensibilidad a 5 slots** sobre `B1_score` + `E_prio_anom` + los 20 controles (C7). Dirección
  esperada, declarada antes: el turno decide **más** cuanto peor es el ratio de selección, así que a 5
  slots el efecto debería **crecer**. Si se encoge, es evidencia en contra del mecanismo (es la
  predicción que la 39 hizo y le falló, y fue lo más informativo de aquella corrida).
- **Se reporta el solapamiento `ANOM` ∩ `analyze BUY`** — cuántas de las 1.236 entradas de anomalía ya
  eran candidatas del engine. Del aritmética de la 45 salen **920**; si no da eso, algo cambió.

---

## 4. El criterio de régimen (CONGELADO) — el del §4 de la 46

**C6** usa el instrumento que dejó la 46 y que la 47 y la 45 ya aplicaron:

1. `tol = max(TOL_MATERIAL, detectable_mean_effect(σ, n))` sobre los trades del **candidato** en la
   ventana, con **`TOL_MATERIAL = 1.00 pts`** — el mismo valor que congelaron la 47 y la 45.
2. El gate va sobre el **agregado de las tres ventanas de stress** (`stress_POOLED`) y **contra el
   control igualado en tasa** (los trades de las 20 semillas `R_rand` agrupados), no contra cero.
   **Falla sólo si el IC95% del Δ está enteramente por debajo de −tol** (2000 resamples, `seed=12345`).
3. Las cuatro ventanas individuales son **descriptivo obligatorio**, con `n`, σ, detectable, IC95% y
   `P(signo)`. **No pueden por sí solas producir un rechazo.**

---

## 5. Sanity del instrumento (si falla alguno, la corrida es INVÁLIDA y no hay veredicto)

1. **Contabilidad:** `|equity_curve[-1] − final_equity| / final_equity ≤ 1e-6` en todos los brazos.
2. **Reproducción de la 45:** con `cap_days=20`, pool **unido** y prioridad binaria con desempate
   alfabético, `E_analyze` da **3.71%** y `E_merged_prio` **7.92%** (±0.05 pp). Es el puente con el
   número que motivó la tarea: si no reproduce, el candidato de acá no es el descriptivo de allá.
3. **Reproducción de la línea publicada:** `B1_score` en la config del re-read de la T33
   (`eval_mode="close"`, `fill_mode="decision"`, `live_gates=False`, 10 slots, `cap_days=250`) da
   **1.97% ± 0.05 pp**. Mismo sanity que congeló la 39.
4. **El instrumento ve turnos BUENOS:** `CAGR(ORACULO_PRIO) ≥ CAGR(B1_score) + 5.00 pp`. Umbral
   reusado de la T21 §5.2 / T39 §5.3 — **no se calibra uno nuevo**. Ojo: el oráculo está **igualado en
   tasa**, o sea que tiene exactamente las mismas `n_d` prioridades por día que el candidato; es un
   sanity duro a propósito.
5. **Y ve turnos MALOS:** `CAGR(ANTI_ORACULO_PRIO) ≤ CAGR(B1_score)`.
6. **El turno muerde:** ≥ **10%** de los trades difieren entre `B1_score` y `E_prio_anom`
   (par `ticker`+`entry_date`, helper `trade_overlap`). Mismo umbral que T21 §5.4 / 26b §5.3.
7. **Las semillas del control son efectivas:** la mediana del solapamiento par a par entre las 20
   `R_rand` deja ≥ **10%** de trades distintos. Si las semillas no mueven nada, la "distribución" de
   C2 es una ilusión.
8. **La clave es pura:** test unitario de que la prioridad de un `(seed, fecha, ticker)` no depende del
   orden de las llamadas ni del estado de la cartera (defecto de la T21, tarea 40).

**Ojo con la ventana rodante (tarea 48):** los dos sanity de reproducción valen **mientras no se
refresquen los parquet**. La ventana efectiva queda escrita en el veredicto.

---

## 6. Regla de decisión (CONGELADA)

**Candidato** = `E_prio_anom`. **Baseline** = `B1_score`. 10 slots, `cap_days=250`. Se cablea **sólo
si pasa las siete**:

| # | Criterio | Umbral |
|---|---|---|
| C1 | ΔCAGR vs `B1_score` | ≥ **+0.50 pp** |
| **C2** | **CAGR del candidato vs el control igualado en tasa** | **> p95 de las 20 semillas `R_rand`** |
| C3 | maxDD | ≤ base + **3.00 pp** |
| C4 | bootstrap pareado sobre Δ(retorno diario) vs `B1_score`, bloques 20 d, 2000 resamples | **IC95% inferior > 0** |
| **C5** | **idem vs la serie diaria PROMEDIO de las 20 `R_rand`** | **IC95% inferior > 0** |
| C6 | régimen con potencia (§4): IC95% del Δ vs el control en `stress_POOLED` | **no enteramente < −tol** |
| C7 | **sensibilidad a 5 slots: C1 y C2 se mantienen** | **los dos** |

**Casos partidos, resueltos ex ante:**

- **Pasa C1 y C4 pero falla C2 o C5** → **NO-SHIP**, y es el desenlace que la tarea existe para poder
  distinguir: querría decir que el +4.21 pp de la 45 era **desordenar**, no **el evento**. Se reporta
  con la banda entera de las 20 semillas al lado.
- **Pasa todo menos C7** → **NO-SHIP.** Un efecto que sólo existe con 10 slots es frágil (precedente
  47 y 45). Y si además **se encoge** al bajar a 5, se reporta como evidencia **contra el mecanismo**
  declarado en el §3.
- **Pasa todo menos C6** → **NO-SHIP**, y el rechazo significa algo (la tolerancia se computa).
- **C6 pasa pero una ventana individual se ve fea** → **no bloquea** (§4.3).
- **El candidato le gana a `B1_score` pero NO a `A_alpha`** → **no cambia el veredicto** (el gate es
  C2/C5, que ya controla el confound), pero **se reporta al frente**: querría decir que buena parte de
  la ventaja es el déficit del score, que es la pregunta de la 39 y ya cerró NO-SHIP.
- **`E_merged_prio` le gana a `E_prio_anom` con holgura** → se reporta como lead con pre-registro
  propio (*"la anomalía además aporta candidatos nuevos"*), **no** se promueve acá: el candidato está
  congelado y el pool unido es otra intervención.
- **Falla cualquier sanity del §5** → **corrida INVÁLIDA**, sin veredicto, y no se re-especifica nada
  (precedente T26; T34, 38 ya pagaron una cada una).

---

## 7. Qué se cablea si pasa / qué NO se toca

- **Si pasa las siete:** flag `paper_event_priority_enabled` (default **OFF**) + `paper_anomaly_k` /
  `paper_anomaly_m` (2.0 / 1.5), que en `generate_trades_analyze_single` **ordena primero** a los
  candidatos con anomalía del día y deja al resto con el `strength` de siempre. **No agrega candidatos
  nuevos** y no toca el sizing: en la cuenta viva (`equal_weight`) la clave de orden sólo decide
  **quién entra**, no cuánto. **Toca decisiones vivas de ENTRADA**, así que **prenderlo es decisión de
  Chapa**. El rollback es una línea.
- **Qué NO se toca aunque pase:** el `buy_score` como clave de fondo (sacarlo es la 39, cerrada); el
  pool de candidatos (la anomalía **no** entra como fuente — eso es lo que la 45 rechazó por C8); el
  sizing; las salidas; el overlay T20.
- **Si no pasa:** NO-SHIP documentado, el engine intacto, y queda escrito **cuál** criterio lo frenó —
  en particular si fue C2/C5, que es la pregunta que la 45 dejó abierta.

---

## 8. Qué NO se modela (caveats antes de correr)

- **El detector de anomalía necesita volumen**, que en producción llega por el mismo path de datos que
  el precio. Si se cablea, hay que verificar que el volumen del día esté disponible **al momento del
  scan**; el harness lo tiene por construcción (barra cerrada).
- **Survivorship:** 127 tickers que sobreviven hoy y que son la watchlist de hoy. Común a todos los
  brazos; sesga el nivel, no el orden.
- **Ventana de `analyze()`** expandida (250 → ~2.514 barras) vs 504 fijas en vivo. Común a todos.
- **Ventana rodante de los artefactos (tarea 48).**
- **El bracket de `eval_mode`:** el engine samplea c/15 min; `touch` es la cota superior de frecuencia
  de disparo. Común a todos los brazos.
- **Sin overlay T20** — en producción el candidato lo heredaría.
- **Márgenes, apalancamiento, dividendos, intradía:** fuera de alcance de `portfolio_sim`.

---

## 9. Plan de ejecución

1. **Enabler:** `analysis/rank_policy.py` gana `rate_matched_priority(keys_by_date, rank_fn)` —
   dado el conjunto de candidatos por fecha y cuántas prioridades lleva cada una, devuelve el conjunto
   priorizado. Pura, testeable offline.
2. **Runner** `scripts/run_prio_event_t49.py`: reusa `load_bars_signals_scores`,
   `precompute_realized`, `trade_overlap` y `summarise` de la T21, `neutral_rank` de la T39,
   `aligned_daily` / `policy_series` de la 39, y `regime_criterion` de la 45; arma los siete tipos de
   brazo del §2, los tres legs (veredicto a 250, reproducción a 20, reproducción T33) y el AND de los
   siete.
3. **Tests offline:** el AND de los siete y **cada** caso partido del §6; que el control queda
   **igualado en tasa** día por día; que la prioridad es **pura** (dos órdenes de llamada, mismo bit);
   que el candidato **no** puede priorizar una entrada que no esté en el pool del engine; que la
   tolerancia de C6 se computa.
4. **Correr** los tres legs + la sensibilidad a 5 slots, sin red y sin tocar `finanzias.db`.
5. **Veredicto** en `docs/prio_event_t49_<fecha>.md`, con **el candidato contra la banda de las 20
   semillas al frente** — que es el número que la 45 no tenía.

**Congelado. Cualquier cambio a §2–§7 después de ver un resultado invalida el pre-registro.**
