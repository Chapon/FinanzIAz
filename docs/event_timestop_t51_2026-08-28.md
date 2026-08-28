# Veredicto — EVENT-TIMESTOP (Tarea 51) · **CORRIDA INVÁLIDA por el §5 + SIN POBLACIÓN por el §5.2 ⇒ SIN VEREDICTO**

**Fecha:** 2026-08-28 · **Pre-registro congelado:** `docs/event_timestop_prereg_t51_2026-08-28.md` (`c362f23`)
**Runner:** `scripts/run_event_timestop_t51.py` (`98540e7`) · **Comando:**
`python scripts/run_event_timestop_t51.py --cache-dir .cache/t51` (determinista; `--json` para la salida completa).

**No se cabla nada.** `paper_max_holding_days` no existe y no se crea.

| brazo (127 tickers, 10 slots, touch/decision/live_gates, baseline cap=250) | CAGR | Sharpe | maxDD | tomadas | tenencia |
|---|--:|--:|--:|--:|--:|
| **`B_base`** — el engine de hoy (sin tope efectivo) | **3.23%** | 0.28 | 41.6% | 2509 | 8.0 |
| `U_30` — tope incondicional, N* del walk-forward (5/5 folds) | 3.80% | 0.31 | 41.0% | 2510 | 8.0 |
| `E_10` — tope condicionado al evento, N* (4/5 folds) | 4.42% | 0.35 | 40.1% | 2516 | 8.0 |
| `ORACULO_cap` — sanity, igualado en tasa, **presciencia perfecta** | **2.93%** | 0.26 | 41.5% | 2512 | 8.0 |
| `ANTI_ORACULO_cap` — sanity, igualado en tasa | 3.25% | 0.28 | 42.0% | 2519 | 8.0 |
| **CONTROL igualado en tasa (20 semillas)** | min **2.04%** · mediana **3.37%** · p95 **4.32%** | | | | |

---

## 1. El resultado en una línea

> **No hay población para preguntar lo que la tarea preguntaba. La maquinaria de salida cierra sola:
> la tenencia máxima de la cuenta viva es de 37 ruedas, así que un tope de 40 o 60 es literalmente
> inerte, y el N que el walk-forward eligió con acuerdo 5/5 toca SEIS trades de 2.509.**

Y donde el tope **sí** tiene población, **cuesta plata**.

---

## 2. La distribución de tenencia, que decide toda la tarea

Baseline, 2.509 trades: media **8,0** · p25 **4** · p50 **7** · p75 **11** · p90 **16** · p95 **19**
· p99 **25** · **máx 37** ruedas.

| N | trades tocados | % | ΔCAGR `U_N` (todas) | ΔCAGR `E_N` (evento) |
|--:|--:|--:|--:|--:|
| 10 | 809 | **32,24%** | **−0.97 pp** | +1.20 pp |
| 15 | 324 | **12,91%** | **−1.12 pp** | +0.81 pp |
| 20 | 98 | 3,91% | +0.16 pp | +1.00 pp |
| 30 | **6** | **0,24%** | +0.58 pp | 0.00 pp |
| 40 | **0** | **0,00%** | **0.00 pp** | 0.00 pp |
| 60 | **0** | **0,00%** | **0.00 pp** | 0.00 pp |

**Lo que dice la tabla, y es lo más importante del documento:** la relación es **al revés** de la
hipótesis. En los dos únicos N con población de verdad —10 (32%) y 15 (13%)— el tope incondicional
**pierde casi un punto** de CAGR. Donde "ayuda" (20, 30) toca entre 98 y **6** trades. Y a partir de
40 no toca ninguno: los `Δ = 0.0000` no son "no significativo", son **el mismo brazo que el baseline**.

Mezcla de motivos de salida del baseline: `signal_full` **1.216 (48,5%)** · `atr_stop` 511 (20,4%)
· `atr_trail` 419 (16,7%) · `atr_tp` 354 (14,1%) · `cap_reached` **9 (0,36%)**. Es el mismo
diagnóstico de la **T13** —*"lo que cierra las posiciones es el flip `analyze SELL`, no los
niveles"*— **replicado en la config viva** (10 slots, 127 tickers) y con el `cap_days=250` confirmado
como no vinculante.

---

## 3. Por qué la corrida es INVÁLIDA (§5, congelado)

Dos sanity fallan, y **los dos por la misma causa**: a la tasa del evento la intervención es
demasiado chica para que el instrumento vea nada.

| sanity | resultado |
|---|---|
| contabilidad en todos los brazos | OK |
| **reproducción `B_base` = 3.23%** (la 49 §0 / T39) | **OK — exacto** |
| **reproducción `alpha_cap20` = 3.71%** (la 45 vía 49 §5.2) | **OK — exacto** |
| *(cross-check no pedido)* `alpha_cap250` = 2.01% (`A_alpha` de la 49 §0) | **OK — exacto** |
| el tope muerde ≥10% | OK — 12,43% de trades distintos |
| **el instrumento ve topes BUENOS** (oráculo > p95 del control) | **FALLA — 2.93% vs 4.32%** |
| el instrumento ve topes MALOS (anti-oráculo < mediana) | OK — 3.25% vs 3.37% |
| **las semillas del control son efectivas ≥10%** | **FALLA — 8,40%** |

**El oráculo con presciencia perfecta pierde contra el baseline** (2.93% vs 3.23%). Capa, sabiendo el
futuro, exactamente las posiciones que peor terminan, a la misma tasa que el candidato — y aun así no
puede ganar. Cuando el techo de la intervención está por debajo del piso, **no hay nada que medir a
esa tasa**: el resultado del candidato, sea cual sea, no es interpretable.

Y el **§5.2 (el sanity de población de la T13, reusado tal cual)** falla para los dos brazos:

| brazo | trades tocados | población | umbral |
|---|--:|--:|--:|
| `U_30` (incondicional) | **6** de 2.509 | **0,24%** | ≥5% |
| `E_10` (evento) | **12** de 2.509 | **0,48%** | ≥5% |

Que es exactamente el diagnóstico que la T13 publicó (0,5%) y que el enunciado de esta tarea había
leído al revés (**tarea 57**): el brazo está **sin poder, no refutado**.

---

## 4. Lo que igual se puede afirmar (y no depende de los sanity que fallaron)

### 4.1 Fuera de muestra el tope no hace nada, o hace daño

El walk-forward eligió `N=30` en **5/5 folds** — un acuerdo perfecto. Cobrado en los tests:

| familia | picks por fold | CAGR OOS del procedimiento | CAGR OOS del baseline |
|---|---|--:|--:|
| `U` (incondicional) | 30, 30, 30, 30, 30 | **1.89%** | **1.89%** |
| `E` (evento) | 10, 10, 10, 10, 30 | **1.55%** | 1.89% |

**El acuerdo 5/5 no vale nada:** fuera de muestra el brazo incondicional da **el mismo dígito** que
el baseline, porque en las ventanas de test el tope de 30 casi nunca dispara. Y el condicionado al
evento queda **−0.34 pp por debajo**.

### 4.2 Ningún intervalo clarea el cero

| bootstrap pareado (bloque 20, 2.000 resamples) | Δ | IC95% | p |
|---|--:|---|--:|
| `U_30` vs baseline (C4 de B) | +0.58 pp | **[−0.13, +1.72]** | 0.084 |
| `E_10` vs baseline (C4 de A) | +1.20 pp | **[−0.65, +3.37]** | 0.126 |
| `E_10` vs el control igualado (C5) | +1.05 pp | **[−0.58, +2.98]** | 0.121 |
| `E_10` vs `U_30` (C9) | +0.62 pp | **[−1.57, +2.96]** | 0.312 |

Y a **5 slots** (C7) el efecto del evento **se da vuelta**: baseline 4.52%, `U_30` 5.09%,
`E_10` **3.83%** — o sea **−0.69 pp** contra el baseline.

### 4.3 **El lead de la 49 queda cerrado: el `+1.70 pp` del cap era del FONDO, no de la tenencia**

Es el 2×2 que la 49 no pudo hacer (§2 del pre-registro, declarado como **descriptivo**). Tres de las
cuatro celdas son números ya publicados, y **reproducen exacto**:

| fondo de orden | `cap_days=20` | `cap_days=250` | **Δ del cap** |
|---|--:|--:|--:|
| **alfabético** | **3.71%** *(la 45)* | **2.01%** *(`A_alpha` de la 49)* | **+1.70 pp** |
| **`buy_score`** (el vivo) | 3.38% | **3.23%** *(`B1_score`)* | **+0.15 pp** |

**El mismo cambio de tope vale +1.70 pp bajo el fondo alfabético y +0.15 pp bajo el fondo que corre
en producción.** No es un efecto de la tenencia con un nivel distinto: es una **interacción** con un
orden de entrada que nadie ejecuta. La hipótesis que abrió esta tarea —*"el +4.21 pp de la 45 vivía
en el `cap_days=20`"*— **es falsa como estaba enunciada**: vivía en la **combinación** de `cap_days=20`
**con** el desempate alfabético.

*(Esta lectura no se apoya en los sanity que fallaron: los cuatro brazos del 2×2 no usan el evento ni
los controles, y su validez descansa en las tres reproducciones exactas del §3.)*

---

## 5. Los dos candidatos, contra el §6

Se listan por completitud. **No dictan veredicto** — la corrida es inválida y los dos brazos están
sin población.

| # | criterio | `U_30` (B) | `E_10` (A) |
|---|---|---|---|
| C1 | ΔCAGR ≥ +0.50 pp | OK (+0.58) | OK (+1.20) |
| C2 | > p95 del control | *n/a* | OK (4.42% vs 4.32%) |
| C3 | maxDD ≤ base +3.00 pp | OK | OK |
| C4 | bootstrap vs base, IC>0 | **FALLA** | **FALLA** |
| C5 | bootstrap vs control, IC>0 | *n/a* | **FALLA** |
| C6 | dosis-respuesta | **FALLA** (pico aislado en 30: los vecinos conservan **0%**) | OK |
| C7 | sensibilidad a 5 slots | **FALLA** | **FALLA** (se da vuelta) |
| C8 | régimen con potencia | OK (IC [−0.90, +0.93]) | OK (IC [−0.87, +0.97]) |
| C9 | A le gana a B | *n/a* | **FALLA** |

---

## 6. Qué deja

- **La pregunta de la tarea queda respondida por el lado del instrumento, no del veredicto:** en la
  cuenta viva **no hay población** para un tope de tenencia. La salida por flip de señal (48,5%) y
  las barreras ATR (51,2%) cierran todo antes: p95 = 19 ruedas, **máximo 37**.
- **Y donde hay población, el tope cuesta:** −0.97 pp a 10 ruedas (32% de los trades), −1.12 pp a 15
  (13%). Eso **no** es "sin población" — es evidencia real, en la dirección contraria a la hipótesis,
  y es lo más informativo que produjo la corrida.
- **El lead de la 49 se cierra** (§4.3): el `+1.70 pp` del `cap_days` es una interacción con el fondo
  alfabético; con el `buy_score` vivo vale **+0.15 pp**.
- **`cap_days_of`** — el cap duro **por posición** en `simulate_portfolio` (`3a12261`), enabler puro y
  reusable, con el default `None` que no cambia ningún harness previo.
- **Tres lecciones metodológicas**, que van a la skill `backtest-replay-harness` y a tareas propias:
  1. **La grilla de un tope se fija desde la distribución de tenencia, medida ANTES de congelar.** Un
     tercio de la grilla pre-registrada (40, 60) era **inerte**: cero trades tocados (**tarea 58**).
  2. **Un acuerdo perfecto de walk-forward no es evidencia si la regla casi no se ejecuta.** Acá dio
     5/5 sobre **seis trades**, y fuera de muestra empató al dígito con el baseline. Mirar la
     **población antes que el acuerdo** (**tarea 58**).
  3. **El oráculo acota lo medible.** Con presciencia perfecta a la tasa del evento el oráculo
     **pierde** contra el baseline: el techo de la intervención está por debajo del piso. Es la
     familia de la lección de la 49 (*el poder del oráculo escala con la tasa de la intervención*),
     ahora con el caso extremo.

---

## 7. Hallazgos anotados como tarea (regla 6)

- **58 — `GRIDPOP`** (abierta): la grilla se congeló sin mirar la distribución de tenencia, así que
  un tercio de ella era inerte y el walk-forward "acordó" 5/5 sobre seis trades. Es el §2 y el §4.1
  de este documento. Se le sumó un matiz: el Δ **negativo** del tramo con población se publicó **sin
  intervalo** —el bootstrap del pre-registro corre sólo en el `N*`—, así que *"donde hay población el
  tope cuesta"* es evidencia descriptiva, **todavía no un NO-SHIP con poder**.
- **59 — `HARNESS-CONCURRENT`** (abierta): al retomar esta tarea, la corrida cortada de la sesión
  anterior **seguía viva** y las dos escribieron el mismo `--cache-dir` y los mismos
  `docs/_t51_run.*`. `SimCache` usa un `.tmp` de **nombre fijo por tag**, así que dos procesos
  simultáneos sobre el mismo tag pueden publicar un pickle mezclado, y nada lo detecta después. Se
  descartó el cache (`.cache/t51_dirty_20260828`) y se re-corrió de cero con **un solo proceso**: la
  corrida limpia dio **idéntica campo por campo**, así que este veredicto **no está contaminado**.
- **60 — `T51-VALIDGUARD`** (cerrada al encontrarla): `outcome_of` no consultaba `sanity["valid"]`,
  así que podía imprimir un `SHIP` sobre una corrida que el §5 declara INVÁLIDA — la guarda que sí
  tienen los runners de la 45, la 47 y la 49. Ahora `sanity_valid` es **keyword obligatorio**, con
  tres tests. **Por eso el título de este documento dice INVÁLIDA y no sólo «sin población»**: el
  runner lo imprime. La re-corrida con el parche salió `122 reusadas · 0 nuevas` — no movió un
  número.
