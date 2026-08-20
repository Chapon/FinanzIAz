# REGIME-POWER (Tarea 46) — el criterio de régimen de la serie **rechaza al nivel del azar**

**Fecha:** 2026-08-19 · **Runner:** `scripts/run_regime_power_t46.py`
**Comandos:** `python scripts/run_regime_power_t46.py --population analyze` y `--population anomaly`
(deterministas; `--json` para la salida completa).

**No es una tarea de trading:** no toca el motor, no decide ningún flag y no necesita pre-registro
congelado. Es análisis sobre datos ya medidos, y lo que produce es **el criterio que las tareas
siguientes van a pre-registrar** — empezando por la **37**, que hoy tiene el criterio viejo congelado.

---

## 1. El resultado en una línea

> **La potencia para detectar la tolerancia de ±0.05 pts que usó C5 es 5,0-5,3% en las tres ventanas
> de stress de las dos poblaciones. α es 5%. O sea: potencia nula — el criterio rechaza al nivel del
> azar.**

Y los **cuatro rechazos que ese criterio produjo en la serie** caen todos por debajo del efecto que su
propia muestra puede resolver:

| rechazo publicado | Δ medido | detectable al 80% en esa ventana | veredicto |
|---|--:|--:|---|
| **26b** · `close_2.0` en `2018Q4` | −0.15 pts | **±1.72** | **11× más chico que el ruido** |
| **26b** · `close_2.0` en `bear_2022` | −0.08 pts | **±0.97** | **12× más chico** |
| **34** · `touch_off` en `2018Q4` | −1.18 pts | **±1.72** | por debajo (0.69×) |
| **T11b** · `A_k2.0_m1.5` en `bear_2022` | −2.01 pts | **±2.35** | por debajo (0.86×) |

*(el detectable de 26b/34 sale de la población `analyze`; el de T11b, de la población `anomaly`)*

---

## 2. Cuántos datos hay realmente en cada ventana

`detectable` = efecto medio más chico que se distingue de cero con ese `n` y esa σ, al 80% de potencia
y α=0.05 (`walkforward_power.detectable_mean_effect`).

**Población `analyze`** — eventos `analyze BUY` PIT, 127 tickers, 10 slots (la de 26b, 34, T39):

| ventana | n trades | σ (pts) | **detectable** | potencia para ±0.05 |
|---|--:|--:|--:|--:|
| `bull_normal` | 2102 | 4.89 | ±0.30 | 7,6% |
| `stress_2018q4` | **79** | 5.45 | **±1.72** | 5,1% |
| `stress_covid_2020` | **77** | 10.44 | **±3.33** | 5,0% |
| `stress_bear_2022` | **251** | 5.50 | **±0.97** | 5,2% |
| **`stress_POOLED`** | **407** | 6.82 | **±0.95** | 5,3% |

**Población `anomaly`** — detector de ruptura `A_k2.0_m1.5` (la de T11b, T38):

| ventana | n trades | σ (pts) | **detectable** | potencia para ±0.05 |
|---|--:|--:|--:|--:|
| `bull_normal` | 950 | 5.74 | ±0.52 | 5,8% |
| `stress_2018q4` | **20** | 5.48 | **±3.43** | 5,0% |
| `stress_covid_2020` | **23** | 8.10 | **±4.73** | 5,0% |
| `stress_bear_2022` | **63** | 6.66 | **±2.35** | 5,0% |
| **`stress_POOLED`** | **106** | 6.80 | **±1.85** | 5,1% |

**Un umbral de −0.05 pts sobre ventanas donde lo detectable es ±0.95 a ±4.73 no es estricto: es ruido
con nombre de criterio.** Está entre **19 y 95 veces** por debajo de lo que la muestra resuelve.

---

## 3. El criterio **no** es inservible — el umbral sí

Esto importa y conviene decirlo antes de tirar nada: cuando el efecto **es grande**, el criterio
discrimina perfectamente. Estabilidad de signo del Δ por trade entre brazos (2000 resamples):

| ventana | `anomaly`: `U_ungated` vs `G_hard` | | `analyze`: `B1_score` vs `N_rot_0` | |
|---|--:|--:|--:|--:|
| | **Δ pts** | **P(signo)** | **Δ pts** | **P(signo)** |
| `stress_2018q4` | −3.02 | **95%** | −0.37 | 65% |
| `stress_covid_2020` | −1.11 | 71% | −0.11 | 53% |
| `stress_bear_2022` | −2.54 | **96%** | +0.19 | 66% |
| `stress_POOLED` | −2.54 | **100%** | +0.04 | 55% |

Con efectos de −2,5 a −3 pts el criterio da 95-100% de estabilidad de signo. Con los efectos de
décimas que la serie venía rechazando, 53-66% — una moneda apenas cargada.

**Y la versión de cartera no rescata nada.** El Δ de retorno de cartera por ventana (bootstrap de
bloques pareado, que es lo que la T38 y la T39 usan) da P(signo) de **58% a 92%** según la ventana y la
población: mejor que por trade en algunos casos, peor en otros, y **nunca cerca del 95%** que haría
falta para que un criterio de signo signifique algo.

Ojo con una lectura fácil: a nivel cartera el **nivel** de la ventana sí es estable (P(signo) 90-100%
en `analyze`), pero eso no es el criterio — *"la cartera perdió en el bear"* habla del **mercado**, no
de la política. Lo que decide es el **Δ entre brazos**, y ése es el que no aguanta.

---

## 4. Qué se hace con esto (la recomendación operativa)

1. **La tolerancia se computa, no se elige.** Antes de congelar un criterio de régimen hay que
   calcular `detectable_mean_effect(σ, n)` de cada ventana y **declarar el umbral por encima de ese
   número**. Es una línea de código y evita escribir un criterio que no puede fallar por otra cosa que
   ruido.
2. **El gate va sobre el agregado de las tres ventanas de stress** (`stress_POOLED`), que es donde hay
   `n` suficiente (407 en `analyze`, 106 en `anomaly`), y **con IC declarado**: falla sólo si el IC95%
   del Δ está **enteramente** del lado malo de la tolerancia material. Rechazar por el punto estimado
   cuando el IC cruza cero es exactamente lo que la serie venía haciendo.
3. **Las ventanas individuales pasan a descriptivo obligatorio** — se reportan siempre, con `n`, IC y
   P(signo) al lado, para que se vea *de qué tamaño de muestra* sale cada número. Nunca solas como
   motivo de rechazo.
4. **El peso de la decisión vuelve a donde hay potencia:** el bootstrap pareado sobre la serie diaria
   **completa** (T≈2.280 obs), el maxDD, y el walk-forward. Esos criterios sí resuelven efectos del
   orden de un punto de CAGR.

**Lo que esto NO es:** aflojar umbrales para que pasen cosas. Es lo contrario — un criterio con
potencia 5% **no es conservador**: acepta y rechaza arbitrariamente, y en esta serie **rechazó cuatro
veces**, incluida la única señal con alpha medido. Un test que no puede detectar el efecto que dice
vetar no está protegiendo nada.

---

## 5. La re-lectura: dos veredictos colgaban enteros de un criterio sin potencia

| tarea | criterios que fallaron | ¿se sostiene el NO-SHIP sin C5/§6.5? |
|---|---|---|
| **26b** (STOP-PRICE) | **sólo C5** a 10 slots (−0.15 y −0.08 pts) | **NO** — pasaba C1-C4 y C6 con +3.39 pp de CAGR, maxDD −4.88 pp y bootstrap [+0.03, +6.30] p=0.024 |
| **34** (STOP-LOOSEN) | **C6** (máximo en el borde) **y** C5 | **SÍ** — C6 no depende de la potencia de régimen |
| **T11b** (ANOM) | **sólo §6.5** (−2.01 pts en `bear_2022`) | **NO** — pasaba todo lo demás, con el edge sobre el p95 del azar |
| **38** (ANOM-REGIME) | sanity §5.4 | n/d — la corrida es inválida por otra cosa |

**Dos de los cuatro veredictos de salida/entrada de la serie se decidieron por un criterio que no
aportó información.** Eso **no** significa que debieran haber shipeado: significa que **hay que
re-decidirlos con un criterio que tenga potencia**, y eso necesita pre-registro propio.

- La **T11b** ya está cubierta por la **tarea 45**.
- La **26b** abre la **tarea 47**: es la de mayor plata esperada del backlog ahora mismo (+3.39 pp de
  CAGR con el bootstrap ya pasado), y su único obstáculo publicado acaba de perder validez.
- La **37** tiene el criterio viejo **congelado en su pre-registro** y todavía no corrió: necesita
  **enmienda antes de correr**, no re-lectura después.

---

## 6. Qué deja de instrumento

- **`walkforward_power.detectable_mean_effect(sd, n)`** — el efecto detectable en las unidades del
  dato, que es el número que faltaba para poder declarar una tolerancia honesta.
- **`sign_stability(values)`** — bootstrap i.i.d. de la media con `p_same_sign`: la lectura directa de
  *"¿este criterio de signo está tirando una moneda?"*.
- **`block_sign_stability(rets)`** y **`block_delta_sign_stability(rets_a, rets_b)`** — las versiones
  de cartera, con bloques móviles y composición, la segunda **pareada** (mismos bloques a los dos
  brazos, así el ruido de mercado común se cancela).
- **`scripts/run_regime_power_t46.py`** — las cuatro lecturas del mismo eje sobre las dos poblaciones,
  con el agregado de stress como candidato de reemplazo.
