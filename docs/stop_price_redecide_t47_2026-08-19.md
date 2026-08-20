# Veredicto — STOP-PRICE-REDECIDE (Tarea 47) · **NO-SHIP · corrida VÁLIDA**

**Fecha:** 2026-08-19 · **Pre-registro congelado:** `docs/stop_price_redecide_prereg_t47_2026-08-19.md`
**Runner:** `scripts/run_stop_price_redecide_t47.py` · **Enabler:** `--live-gates` en
`scripts/run_stop_price_replay_t26b.py`.
**Comando:** `python scripts/run_stop_price_redecide_t47.py` (determinista).

**No se cabla `paper_atr_confirm_at_close`.** El engine sigue decidiendo las barreras contra el precio
corriente intradía.

Población: **127 tickers**, **143.096 entradas `analyze BUY`** PIT, `cap_days=250`, `fill_mode="decision"`,
**`live_gates=True`** (nuevo), 10 slots para el veredicto y 5 para C7.

---

## 1. El titular: **el mismo NO-SHIP, por razones opuestas**

| | **26b** (2026-08-16) | **47** (esta corrida) |
|---|---|---|
| **C5 / C5′ — régimen** | **FALLA** (−0.15 y −0.08 pts) | **PASA** — y el Δ es **positivo en las cuatro ventanas** |
| **C3 — bootstrap** | pasa **al filo**: [+0.03, +6.30] p=0.024 | **FALLA**: [−0.23, +8.51] p=0.031 |
| **C7 — 5 slots** | *(no era criterio)* | **FALLA**: ΔCAGR **−0.50 pp** |
| veredicto | NO-SHIP por C5 | **NO-SHIP por C3 y C7** |

**La 26b tenía razón en el veredicto y estaba equivocada en el motivo.** El criterio que la frenó
—régimen— ahora pasa, y no porque se haya aflojado nada: pasa con el Δ del agregado de stress en
**+0.23 pts** (IC [−0.72, +1.26], tolerancia 1.00). Lo que la frena de verdad es que **el efecto no es
robusto**: no clarea su propio intervalo y **se da vuelta** al pasar a 5 slots.

Esto es exactamente lo que el §0 del pre-registro declaró como desenlace más probable, y por qué se
declaró que sería **un éxito de la tarea, no un fracaso**: el punto era decidir con un criterio que
tenga potencia, no llegar a un veredicto en particular.

---

## 2. La corrida (10 slots, con gates)

| brazo | CAGR | Sharpe | maxDD | tomadas |
|---|--:|--:|--:|--:|
| `touch_1.0` | −2.52% | −0.07 | 39.0% | 4176 |
| `touch_1.5` | −1.84% | −0.02 | 40.8% | 3218 |
| **`touch_2.0` (BASELINE — la regla viva)** | **2.01%** | **0.20** | **46.7%** | 2815 |
| `touch_2.5` | 6.12% | 0.43 | 31.5% | 2587 |
| `touch_3.0` | 8.71% | 0.55 | 35.6% | 2512 |
| `close_1.0` | 2.22% | 0.21 | 36.5% | 3376 |
| `close_1.5` | 4.39% | 0.33 | 43.1% | 2807 |
| **`close_2.0` (CANDIDATO)** | **6.12%** | **0.42** | **37.6%** | 2562 |
| `close_2.5` | 6.96% | 0.46 | 34.7% | 2470 |
| `close_3.0` | **9.31%** | 0.57 | 34.6% | 2430 |
| _ORACULO_STOP (sanity)_ | 9.32% | 0.59 | 28.4% | 2629 |
| _AZAR_MISMA_TASA (sanity)_ | 3.18% | 0.26 | 46.0% | 2706 |

**Los cuatro sanity pasan ⇒ la corrida es VÁLIDA y el veredicto vale:**

- **Contabilidad** OK en los 12 brazos.
- **El oráculo le gana al control IGUALADO en tasa por +6.14 pp** de CAGR (la lección de la T26: el
  umbral va contra el control igualado, no contra el baseline).
- **La regla muerde: 62,1%** de los trades difieren entre `touch_2.0` y `close_2.0`. No es matiz.
- **Reproducción exacta de la 26b:** con `live_gates` apagado, `touch_2.0` da **4.41%** y `close_2.0`
  **7.80%** — los dos dígitos publicados. La cañería es la misma; lo que cambia es qué se modela.

**Cross-check independiente que vale la pena anotar:** `touch_2.0` con gates da **2.01% de CAGR y
46,7% de maxDD**, que son **exactamente** los números que la **T34** midió para el múltiplo vivo con
otro runner (*"peor maxDD de toda la rejilla (46.7%) y tercer peor CAGR (2.01%)"*). Dos harness
distintos, el mismo dígito.

---

## 3. C5′ — el criterio con potencia pasa, y da vuelta el mecanismo publicado

| ventana | n | σ | detectable | **Δ pts** | IC95% |
|---|--:|--:|--:|--:|---|
| `bull_normal` | 2359 | 5.08 | ±0.29 | +0.13 | [−0.19, +0.41] |
| `stress_2018q4` | 90 | 5.65 | ±1.67 | **+0.05** | [−1.67, +1.67] |
| `stress_covid_2020` | 80 | 12.56 | ±3.94 | **+0.72** | [−3.14, +4.64] |
| `stress_bear_2022` | 286 | 5.66 | ±0.94 | **+0.12** | [−0.90, +1.11] |
| **`stress_POOLED` ← GATE** | **456** | 7.43 | **±0.98** | **+0.23** | **[−0.72, +1.26]** |

Tolerancia efectiva **1.00 pts** = `max(material 1.00, detectable 0.98)` — computada, no elegida.

**Y acá hay una corrección al veredicto de la 26b que va más allá de la potencia.** La 26b no sólo
rechazó con un criterio sin potencia: **publicó un mecanismo para explicar ese rechazo** —*"confirmar
al close retrasa la salida y el precio de ese retraso se paga justo donde las barras malas
encadenan"*—. Con los gates modelados **el signo se da vuelta**: −0.15 → **+0.05** en 2018Q4 y −0.08 →
**+0.12** en `bear_2022`. **El mecanismo publicado no se sostiene.** No es que fuera indetectable: es
que apuntaba para el otro lado. Nota de corrección agregada a `docs/stop_price_t26b_2026-08-16.md`.

**Segundo descriptivo (versión de cartera, pareada — no es gate):** el Δ del agregado de stress es
**+8.19%** con IC [−5.4%, +19.2%] y P(signo) 88%. Coincide en signo con la de por trade, y tampoco
alcanza el 95%.

---

## 4. Lo que sí frena al candidato

**C3 — el bootstrap ya no clarea el 95%.** A 10 slots el ΔCAGR observado es **+4.11 pp** —más grande
que el +3.39 de la 26b— pero el IC95% pasa de **[+0.03, +6.30]** a **[−0.23, +8.51]** (p=0.031). La
26b pasaba **al filo**, con el IC inferior en +0.03; modelar los gates lo empuja a **−0.23** y el
criterio se cae. Es un buen recordatorio de qué significa "al filo".

**C7 — a 5 slots el efecto se da vuelta.** ΔCAGR **−0.50 pp** con IC [−6.64, +5.19]: fallan C1 y C3.
El pre-registro lo declaró como gate duro **sabiendo que la 26b ya fallaba ahí**, y la regla de
decisión dice por qué: *"si el efecto sólo existe con 10 slots, es frágil, y una regla de salida
frágil no se cabla en la cuenta viva"*.

**Los otros cinco criterios pasan:** C1 (+4.10 pp), C2 (maxDD **−9.07 pp**, casi el doble de la mejora
que midió la 26b), C4 (+0.218 de Sharpe), C5′ y C6 (**5/5** múltiplos consistentes, contra 4/5 en la
26b).

---

## 5. Qué significa, y qué NO significa

**Significa** que la pregunta *"¿contra qué precio se decide la barrera?"* queda cerrada por ahora con
la respuesta *"no hay evidencia suficiente para cambiar"*, y esta vez el motivo es sólido: el efecto
puntual es grande y persistente en la rejilla, pero **no sobrevive a su propio intervalo ni al cambio
de slots**.

**No significa** que la regla viva sea buena. `touch_2.0` da **2.01%** de CAGR con **46,7%** de maxDD:
es el **peor drawdown de los diez brazos de la rejilla**. Casi todo lo demás rinde más, en los dos
modos — y eso vuelve a apuntar a lo que ya dijeron la 34 y la 37: **el problema no es contra qué
precio se evalúa la barrera, es el múltiplo (y quizás la existencia misma del stop duro)**. Esa es la
tarea **37**, no ésta.

**Tampoco significa que la 26b se equivocó en no shipear.** Acertó el veredicto. Lo que esta corrida
corrige es **el motivo** y **el mecanismo publicado**, que es lo que otras tareas iban a heredar.

---

## 6. Qué deja

- **`--live-gates` en el runner de la 26b**, con default OFF (preserva su corrida publicada) — y el
  sanity de reproducción que lo demuestra al dígito.
- **`scripts/run_stop_price_redecide_t47.py`** con **C5′ implementado**: la tolerancia se computa con
  `detectable_mean_effect`, el gate va sobre el agregado de stress con IC, y las ventanas
  individuales son descriptivo que **no puede bloquear** (13 tests, incluido el caso *"una ventana fea
  no bloquea"*, que es el defecto exacto de la 26b).
- **El segundo caso concreto para la tarea 36:** modelar los gates de re-entrada **movió un hallazgo,
  no la escala** — dio vuelta el signo del Δ por régimen y cruzó el IC inferior de C3. El primero fue
  la T21/T39. Con dos, el criterio de la T33 (*"¿los brazos disparan barreras a tasas distintas?"*)
  queda confirmado como el correcto para decidir cuándo importa: acá **difieren mucho** (19,9% vs
  13,4% de stops) y por eso movió.
- **C5′ como plantilla para la enmienda de la 37**, que hoy tiene congelado el criterio viejo.
