# Veredicto — ANOM-PROFILE (Tarea 45) · **NO-SHIP por C4 y C8 (corrida VÁLIDA)**

**Fecha:** 2026-08-20 · **Pre-registro congelado:** `docs/anom_profile_prereg_t45_2026-08-20.md` (`d36f22e`)
**Runner:** `scripts/run_anom_profile_t45.py` · **Comando:** `python scripts/run_anom_profile_t45.py`
(determinista; `--json` para la salida completa).

**No se cabla nada.** El detector sigue como enabler. `paper_anomaly_entries_enabled` no existe y no
se crea.

Población: **127 tickers** de la watchlist viva, candidato **congelado** `A_k2.0_m1.5` (el brazo de
decisión de la T11b), **1.236 entradas**, `portfolio_sim` con 10 slots y `cap_days=20`,
`eval_mode="touch"` + `fill_mode="decision"` + `live_gates=True`, K=500 carteras Monte Carlo
time-matched **al candidato**.

| brazo | CAGR | Sharpe | maxDD | tomadas | ofrec. |
|---|--:|--:|--:|--:|--:|
| **`A_k2.0_m1.5`** | **9.23%** | **1.02** | 12.9% | 1056 | 1236 |
| `A_k1.5_m2.0` | 8.58% | 0.93 | 16.0% | 1157 | 1344 |
| `A_k1.5_m1.5` | 8.36% | 0.76 | 26.5% | 1662 | 2325 |
| `A_k2.0_m2.0` | 7.66% | **1.04** | 9.8% | 828 | 911 |
| los otros 5 | 3.51-4.04% | 0.68-0.87 | 4.9-8.1% | | |
| `V_oracle_entry` | 102.80% | 4.46 | 6.6% | 267 | 1236 |
| `AZAR_TIME_MATCHED` | mediana **2.97%** · **p95 5.97%** | p95 0.70 | mediana 21.8% | | K=500 |

---

## 1. El titular: **el motivo publicado de la T11b se cae, y el NO-SHIP igual queda en pie — por otra
cosa**

Es el tercer caso seguido (46 → 47 → 45) del mismo patrón: **el mismo veredicto, por razones
opuestas**.

**Lo que se cae.** La T11b cerró NO-SHIP por **un solo criterio**, su §6.5 de robustez de régimen, con
el mecanismo publicado *"comprar una ruptura al alza en un bear market es, sistemáticamente, una
trampa alcista"*. Medido con potencia y **contra el control time-matched**:

| ventana | n | σ | detectable | **Δ vs el azar** | IC95% | P(signo) |
|---|--:|--:|--:|--:|---|--:|
| `bull_normal` | 950 | 5.74 | ±0.52 | **+0.55** | [+0.18, +0.90] | 100% |
| `stress_2018q4` | 20 | 5.48 | ±3.43 | **+0.36** | [−1.94, +2.65] | 62% |
| `stress_covid_2020` | 23 | 8.10 | ±4.73 | −0.66 | [−3.69, +2.58] | 67% |
| `stress_bear_2022` | 63 | 6.66 | ±2.35 | **+0.51** | [−1.06, +2.18] | 72% |
| **`stress_POOLED`** | **106** | 6.80 | **±1.85** | **+0.29** | **[−0.95, +1.64]** | 68% | ← **GATE** |

**C5′ PASA**, y no por haberse aflojado: la tolerancia **se computó** (`max(1.00, detectable)` =
**1.85**) y el Δ del agregado de stress es **positivo**. Más fuerte todavía: **en `bear_2022` —la
ventana que produjo el rechazo de la T11b— la señal le gana al azar time-matched por +0.51 pts**, y en
`2018Q4` por +0.36. **El mecanismo publicado no tiene respaldo.** La única ventana negativa es
`covid_2020` (−0.66), con n=23 y un detectable de ±4.73 — o sea, indistinguible de cero.

Nota importante sobre por qué esto no es "aflojar el umbral": el §6.5 medía el **nivel** contra cero, y
un nivel negativo en un bear habla del **mercado**, no de la política. Contra el control time-matched
—que es el que cancela el mercado— la señal está **por encima en tres de las cuatro ventanas**.

**Lo que queda en pie.** El NO-SHIP se sostiene, pero por **dos criterios que la T11b no tenía o que
cambiaron de signo**, ninguno de los cuales tiene que ver con régimen:

- **C4 — PBO pasa de 0.476 a 0.659.** La T11b lo midió al filo (0.476, *"pasa, borderline"*) sobre 41
  tickers. Sobre la población viva **se va arriba de 0.5**: la elección del brazo dentro de la grilla
  **no generaliza**.
- **C8 — la señal no le aporta al engine.** Ver §3.

---

## 2. La corrida es VÁLIDA, y con reproducción exacta en las dos puntas

Los cuatro sanity del §5 pasan:

| sanity | resultado |
|---|---|
| contabilidad en todos los brazos | OK |
| el oráculo despega ≥ +20 pp | **+93.57 pp** (102.80% vs 9.23%) |
| **reproducción config viva** — `A_k2.0_m1.5` = 9.23% ±0.05 pp | **OK** (el `U_ungated` de la 38) |
| **reproducción config legacy** — 41t/5sl/`resting`/`close` = 12.77% / Sharpe 1.22 | **OK** |

La segunda reproducción merece una línea, porque **el número esperado no es el que publicó la T11b**
(12.89% / 1.24): es el que dan **los artefactos de hoy**. Los parquet se refrescaron el 2026-08-09 y el
`10y` es una **ventana rodante**, así que los nueve brazos perdieron 1-3 entradas. Está anotado como
**tarea 48** y el valor esperado se midió **antes** de congelar el pre-registro, justamente para no
congelar un sanity que no podía pasar.

---

## 3. LO QUE VALE MÁS QUE EL VEREDICTO: **la prioridad vale +4.21 pp; la señal, agregada sin
prioridad, no vale nada**

C8 pregunta lo que el ship realmente plantea y que la T11b **nunca preguntó**: su contrafactual era
*entrar al azar*, y nadie opera contra eso — el engine ya tiene una fuente de candidatos y los slots
son 10.

| brazo (127 tickers, 10 slots, `cap_days=20`) | CAGR | Sharpe | maxDD | tomadas | trades distintos |
|---|--:|--:|--:|--:|--:|
| **`E_analyze`** — la fuente que el engine usa hoy | **3.71%** | 0.30 | 42.7% | 2832 | — |
| **`E_analyze+anom`** — unión, mismo pipeline | **3.44%** | 0.28 | 42.4% | 2845 | **25,4%** |
| `E_analyze+anom_PRIO` — la anomalía gana el slot | **7.92%** | 0.52 | 39.3% | 2793 | **73,9%** |

- **C8 FALLA:** ΔCAGR **−0.27 pp**, bootstrap pareado **[−2.16, +1.52] pp, p=0.626**. Agregar la
  anomalía al stream de candidatos, por el mismo pipeline, **no hace nada**.
- **Y no es que no consiga slots:** el **25,4%** de los trades cambian. Los consigue, y no ayuda.
- **Pero cuando se le da prioridad, el CAGR se duplica:** **+4.21 pp** (7.92% vs 3.71%), IC95%
  **[−0.25, +8.47]** — al filo de clarear cero—, con el **73,9%** de los trades distintos.

**Cómo hay que leer eso, con el caveat adelante.** El brazo priorizado **no es un gate** (está
declarado como descriptivo en el §2 del pre-registro) y **está confundido**: cambia el desempate del
día, así que parte del +4.21 pp puede ser *"cualquier cosa menos alfabético"* y no *"la anomalía"*.
**Lo que empuja en contra de esa lectura fácil** es la T21: ahí el orden **alfabético** le ganó a la
mediana de diez órdenes aleatorios por **+3.10 pp** — o sea que desordenar, en promedio, **empeora**.
Si desordenar empeora y este desorden en particular mejora 4.21 pp, el candidato natural para explicar
la diferencia es la señal. **Pero no está probado**, y cerrarlo necesita un control **igualado en
tasa** (prioridad aleatoria a la misma frecuencia), que es la lección de la T26 aplicada acá. Queda
como **tarea 49**.

**Lo que sí queda establecido sin caveat:** el cuello de botella de esta señal **no es la señal, es el
turno**. Con 143.096 candidatos `analyze BUY` para 10 slots (~50:1), quién entra lo decide el
desempate, y hoy ese desempate es alfabético. Es la misma familia de la 21/39, con una diferencia
importante: acá la clave de orden **no es un score** —que es lo que la serie midió cinco veces y
siempre dio en el azar o debajo— sino **un evento que ocurrió ese día**.

---

## 4. Los ocho criterios

| # | Criterio | Umbral | Resultado |
|---|---|---|---|
| C1 | CAGR **y** Sharpe > p95 del azar | los dos | **pasa** — 9.23% vs 5.97% · 1.02 vs 0.70 |
| C2 | ΔCAGR vs la mediana del azar | ≥ +2.00 pp | **pasa** — +6.26 pp (9.23% vs 2.97%) |
| C3 | maxDD ≤ 1.5× la mediana del azar | ≤ 32.7% | **pasa** — 12.9% |
| **C4** | **DSR > 0.5 y PBO < 0.5** | los dos | **FALLA** — DSR 0.993 pasa, **PBO 0.659** no |
| C5′ | régimen con potencia: IC95% del Δ en `stress_POOLED` | no entero < −1.85 | **pasa** — +0.29 [−0.95, +1.64] |
| C6 | LOTO (sacando AMD) | > mediana azar | **pasa** — 8.11% vs 2.97% |
| C7 | sensibilidad a 5 slots: C1 y C2 | los dos | **pasa** — 12.50% vs p95 8.78% |
| **C8** | additividad sobre el engine | ΔCAGR ≥ +0.50 pp **y** IC inferior > 0 | **FALLA** — −0.27 pp, [−2.16, +1.52] |

**Seis de ocho pasan.** Los dos que fallan son **los dos que la T11b no había medido** (C8) o que
**cambiaron al mudarse a la población viva** (C4).

**C7 conviene mirarlo dos veces, porque va en la dirección contraria a la intuición:** a **5** slots el
candidato da **12.50%** contra un p95 del azar de 8.78% y una mediana de 2.95% — o sea que el edge es
**más fuerte con menos slots**, no menos. Es exactamente lo que predice el mecanismo del §3: cuanto
más escaso el slot, más decide **quién entra**.

---

## 5. El otro hallazgo: la elección del brazo **no es estable**

La regla de la T11b (*"mejor Sharpe entre los que pasan el filtro local"*) **re-seleccionaría
`A_k2.0_m2.0`** sobre la población viva, no `A_k2.0_m1.5`. El candidato **no cambió** (está congelado
por el §0.4 del pre-registro, y esa era la mitad del punto: sobre la población viva la elección del
brazo es fuera de muestra).

Lo informativo es **por cuánto** se da vuelta: **0.02 de Sharpe** (1.04 vs 1.02). Una regla de
selección que se decide por dos centésimas es exactamente lo que un **PBO de 0.659** describe desde el
otro lado. **Las dos mediciones son la misma cosa vista dos veces**, y las dos dicen que la grilla
`(k, m)` está sobre-ajustada a la muestra con la que se la barre.

---

## 6. Lo que este veredicto **no** dice

- **No dice que la señal no sirva.** C1-C3, C6 y C7 pasan con holgura y el edge sobre el azar es
  grande y estable a los dos niveles de slots. Lo que dice es que **no generaliza en la elección del
  par `(k, m)`** (C4) y que **no aporta si entra sin turno** (C8).
- **No dice que la T11b se haya equivocado de veredicto.** Acertó el NO-SHIP. **Erró el motivo**, igual
  que la 26b (`docs/stop_price_redecide_t47_2026-08-19.md`). Nota de corrección agregada a
  `docs/anomaly_signal_t11b_2026-07-23.md`.
- **No dice que priorizar la anomalía sea bueno.** Ese brazo es descriptivo y está confundido con
  *"no-alfabético"* (§3). Necesita su control igualado en tasa — **tarea 49**.
- **Los niveles de C8 no son comparables con los de la serie de salidas.** `E_analyze` da **3.71%**
  acá y `touch_2.0` dio **2.01%** en la T47 con la misma config de universo, slots, `eval_mode`,
  `fill_mode` y `live_gates`: la diferencia es **`cap_days`** (20 acá, heredado del marco congelado de
  la T11b; 250 allá). Los dos brazos de C8 comparten el 20, así que **el Δ es limpio**, pero el
  **nivel** no es el del engine. Anotado como **tarea 50**.

---

## 7. Qué deja

- **`scripts/run_anom_profile_t45.py`** — el marco de la T11b sobre la población viva, con C5′
  (tolerancia computada + gate sobre el agregado de stress **contra el control**), C7, la población B
  de additividad con su descriptivo priorizado, y los dos sanity de reproducción. 27 tests
  (`tests/test_anom_profile_t45.py`).
- **`random_baseline(..., regime_pts=...)`** en el runner de la T11b: el Monte Carlo ahora puede
  devolver los retornos por trade **por régimen**, que es el control que faltaba para poder medir un
  criterio de régimen contra algo que no sea cero. Default `None` ⇒ cero cambio para T11b y T38.
- **Tres tareas nuevas:** **48** (la ventana rodante — encontrada al armar el sanity y anotada antes de
  correr), **49** (el mecanismo de prioridad, con el control igualado en tasa que este veredicto no
  tiene) y **50** (re-medir la additividad con la tenencia del engine).
- **La confirmación de que el patrón 46→47→45 es sistemático:** tres veredictos seguidos donde el
  motivo publicado no sobrevive y el veredicto sí. En los tres casos lo que falló la primera vez fue
  **el criterio de régimen sin potencia**, y en los tres el rechazo verdadero estaba en otro lado.
