# Pre-registro CONGELADO — El armado del trailing (Tarea 54, TRAIL-ARM)

**Fecha:** 2026-08-28 · **Origen:** `docs/stop_value_t37_2026-08-27.md` §7 (declarado fuera de
alcance por su §9) · **Runner:** `scripts/run_trail_arm_t54.py` (a escribir)
**Medición previa (§0.3), ya corrida:** `scripts/measure_trail_arm_t54.py`
**Estado: CONGELADO.** Todo lo que sigue se decide **antes** de correr un solo brazo. Lo que no esté
acá no se puede agregar después, y lo que esté no se puede sacar (precedente T26).

---

## 0. Tres cosas que hay que corregir antes de preguntar

### 0.1 El agujero **ya no es hipotético**: la política está viva

La entrada 54 del backlog dice que *"el mecanismo está cableado pero apagado, así que el agujero
sigue siendo hipotético hasta que Chapa prenda el candidato"*. **Eso caducó el 2026-08-27**: la 53
registra que `~/.finanzias/settings.json` pasó a `atr_hard_stop_enabled=false` +
`atr_trail_mult=2.0`, o sea que la cuenta 2 **corre `soff_t2.0` en vivo desde esa fecha**. El
36,5% de posiciones con una sola barrera es la política de salida de hoy, no un escenario.

Eso sube la relevancia de la tarea. **No cambia su umbral de evidencia**: sigue siendo un cambio de
salida y se decide con el mismo molde que la 37.

### 0.2 La brecha de retorno del §7 de la 37 es **en buena parte mecánica**

El §7 midió que los trades que nunca arman el trailing rinden **−3.31 pts** contra **+2.47** de los
que sí. Leerlo como *"armar el trailing antes los habría salvado"* es un error de causalidad, y la
medición previa lo muestra con el gradiente completo (2.520 trades del brazo vivo):

| excedente máximo sobre la entrada (ATRs) | trades | retorno medio |
|---|--:|--:|
| 0.00–0.25 | 119 | **−4.49 pts** |
| 0.25–0.50 | 237 | −3.74 |
| 0.50–0.75 | 302 | −3.20 |
| 0.75–1.00 | 262 | −2.51 |
| 1.00–1.50 | 453 | −1.38 |
| 1.50–2.00 | 320 | +0.61 |
| 2.00–3.00 | 377 | +2.49 |
| ≥ 3.00 | 450 | **+7.65** |

**El excedente máximo es el techo del retorno posible**: un trade cuyo precio nunca subió más de
0,25×ATR sobre la entrada **no podía** terminar bien, arme o no arme el trailing. La relación es
monótona y casi aritmética. Así que la brecha del §7 **no es evidencia** de que el umbral esté mal
puesto, y este pre-registro **no la usa como premisa**.

### 0.3 Bajar el umbral no "agrega una barrera": **reintroduce un stop duro por la ventana**

Con `trail_mult = 2.0`, el nivel del trailing es `HWM − 2×ATR`. Para un trade cuyo HWM apenas supera
la entrada, ese nivel está **por debajo de la entrada** — a ~2 ATRs. O sea que bajar
`trail_min_excess_atrs` hacia 0 convierte al trailing, para esa población, en **un stop duro de ~2×ATR
bajo la entrada**: exactamente el brazo que la **37 apagó** después de medir que *"casi todo el valor
del stop duro está en las veces que se equivoca"* (`ORACULO_STOP` 9.32% vs candidato 9.17%).

**Predicción declarada antes de correr:** si la 37 tiene razón, los brazos de umbral **bajo**
(`0.00`, `0.25`) deberían **perder** contra el vivo, y el óptimo —si existe— debería estar **cerca**
del 1.0 actual. Si la corrida diera lo contrario, lo que quedaría en duda es la lectura de la 37, y
eso se dice **acá**, no después.

---

## 1. La pregunta

**¿El umbral de armado del trailing (`trail_min_excess_atrs = 1.0`) está bien puesto para la política
de salida que hoy corre en vivo (`soff_t2.0`)?**

Dos subpreguntas, en este orden:

- **Q1 — ¿La curva tiene forma?** ¿El ΔCAGR contra el brazo vivo tiene un gradiente en el umbral, o
  todo el rango es indistinguible (que sería decir *"el armado no es un knob que importe"*)?
- **Q2 — ¿El movimiento que produce es el que se cree?** El umbral no crea salidas nuevas de la nada:
  **adelanta** salidas que hoy resuelve el flip de señal. La corrida tiene que reportar la mezcla de
  motivos de salida por brazo, y un brazo que sólo cambia *quién* cierra la posición sin cambiar el
  resultado es un **NO-SHIP** aunque el CAGR se mueva dentro del ruido.

---

## 2. Brazos (CONGELADO), con su población medida

**Grilla:** `k ∈ {0.00, 0.25, 0.50, 0.75, 1.00, 1.50}` — el umbral en ATRs. **`k = 1.00` es el
BASELINE**: es la config viva.

**La grilla sale de la distribución medida (regla de la tarea 58), no de una intuición.** Sobre los
2.520 trades del brazo vivo, el excedente máximo sobre la entrada tiene media **1.78**, p25 **0.72**,
p50 **1.35**, p75 **2.46**, p90 **3.91**, p95 **4.62**, p99 **6.07**, máx **12.02** ATRs. La
población **diferencial** —los trades que **cambian de comportamiento** respecto del vivo— es:

| `k` | trades que cambian | población | ¿pasa el ≥5% de la T13? |
|--:|--:|--:|:--|
| 0.00 | 919 | **36,47%** | sí |
| 0.25 | 801 | **31,79%** | sí |
| 0.50 | 564 | **22,38%** | sí |
| 0.75 | 262 | **10,40%** | sí |
| 1.00 | — | — | *baseline* |
| 1.50 | 453 | **17,98%** | sí (sube el umbral: **desarma** trades que hoy arman) |

**Ningún brazo es inerte y ninguno queda sin población**, que es lo que la 51 no pudo decir de la
suya. No se agregan valores arriba de 1.50: el `1.50` ya desarma al 18% y sirve para ver el otro
lado de la curva.

**La población que manda es la DIFERENCIAL, no la acumulada.** La acumulada (cuántos trades tendrían
el trailing armado con umbral `k`) va del 100% al 45% y **sobrestima** lo que un brazo puede mover:
los trades por encima del umbral viejo ya armaban y no cambian. Medir sobre la acumulada sería el
mismo error de la 51 por el otro eje.

**Brazos de sanity, igualados en tasa** (el molde de la 49, reusado):

- **`ORACULO_arm`** — arma el trailing sólo en los trades que **peor** terminan, en la misma cantidad
  por día que el brazo candidato. Tiene que despegar.
- **`ANTI_ORACULO_arm`** — lo arma en los que **mejor** terminan, misma tasa. Tiene que hundirse.
- **`CONTROL_k_j`** — 20 semillas: arma el trailing en un subconjunto **aleatorio** de entradas, con
  la **misma cantidad por día** que el candidato. Es el que separa *"el umbral"* de *"tocar esa
  cantidad de posiciones"*.

---

## 3. Población y config (CONGELADO)

- **Universo:** `data/harness_universe_live_acct2.txt` (**127 tickers**). Otro ⇒ smoke, sin veredicto.
- **Slots:** `max_positions=10`, capital 50.000, `allow_reentry_while_open=False`, `cap_days=250`.
- **Regla de salida base:** **`soff_t2.0`** — `stop_mult = NO_STOP` (stop duro apagado) y
  `trail_mult = 2.0`, que es **la política viva desde el 2026-08-27**, con
  `eval_mode="touch"` (26b) · `fill_mode="decision"` (T33) · `live_gates=True` (T34).
  **Esto cambia el baseline respecto de toda la serie anterior**, que corría `s2.0_t2.0`, y es
  deliberado: se mide sobre lo que la cuenta hace hoy.
- **Entradas:** `analyze BUY` PIT, fondo de orden `buy_score`.
- **Costos:** `CostModel()` (0,1% comisión + 0,05% slippage por punta).
- **Ventana y población** declaradas con `artifact_window` + `cfg.population(...)` (48 y 52), y la
  **población de la grilla** con `announce_grid` (58) **antes** de correr los brazos.

---

## 4. Dosis-respuesta (CONGELADO)

Sobre `k ∈ {0.00, 0.25, 0.50, 0.75, 1.50}` (todos menos el baseline), la curva de **ΔCAGR vs el
brazo vivo** tiene que cumplir:

1. **Monótona o unimodal** al recorrer `k` (empates dentro de **±0.20 pp** no cuentan como cambio de
   dirección).
2. **Sin pico aislado:** los vecinos de `k*` en la grilla conservan **≥50%** del ΔCAGR de `k*`.

Un efecto que exista sólo en un `k` y desaparezca en sus dos vecinos es sobreajuste, no un knob.

---

## 5. Sanity del instrumento (si falla alguno, la corrida es INVÁLIDA y no hay veredicto)

1. **Contabilidad** OK en todos los brazos.
2. **Reproducción** (tri-estado consciente de ventana y población, 48 y 52), tolerancia ±0.05 pp:
   - el brazo vivo `soff_t2.0` = **9.17%** de CAGR (T37 §7.7, `D1` de la T34);
   - la fracción que **nunca arma** con el umbral vivo = **36,5%** (T37 §7) — medida de nuevo acá en
     **36,47%** sobre 2.520 trades, que es el mismo número al redondeo publicado.

   **Las dos ya reprodujeron en la medición previa, antes de congelar este documento:** el brazo vivo
   dio **CAGR 9.17% · Sharpe 0.57 · maxDD 28.2% · 2.520 tomadas · tenencia 8,0 ruedas**, o sea los
   **dos** dígitos que la 37 publicó para `soff_t2.0` (9.17% / 28.2%). El instrumento parte de una
   cañería verificada, que es lo que la 51 no pudo decir hasta el final.
3. **Población diferencial ≥ 5%** (T13) en el `k*` que dicte el veredicto. Si no llega, ese brazo se
   reporta **«sin población» — sin poder, NO refutado**. *(Por §2 los seis la pasan, así que este
   sanity sólo puede fallar si la muestra cambia.)*
4. **El instrumento ve armados BUENOS y MALOS:** `ORACULO_arm` > **p95** del control igualado y
   `ANTI_ORACULO_arm` < **mediana** del control.
5. **El umbral muerde:** ≥**10%** de trades distintos entre el baseline y el brazo candidato.
6. **Las semillas del control son efectivas:** ≥**10%** de trades distintos entre pares (mediana).

---

## 6. Regla de decisión (CONGELADA)

**`k*` se elige por walk-forward** sobre los cinco folds de la T37 (2020-08→2026-07), maximizando
CAGR en train y cobrando en test; **la grilla que recorre el walk-forward es la que pasa el §5.3**
(la lección de la 58: mirar la población antes que el acuerdo). Se reporta la concordancia entre
folds **y** la población del `k` elegido.

| # | Criterio | Umbral |
|---|---|---|
| **C1** | ΔCAGR vs `soff_t2.0` | ≥ **+0.50 pp** |
| **C2** | CAGR > **p95** de los 20 controles igualados en tasa | el criterio que mató a la 49 |
| **C3** | maxDD | ≤ base **+3.00 pp** |
| **C4** | block-bootstrap pareado vs el baseline (bloque 20, 2000 resamples, semilla 12345) | IC95% inferior > **0** |
| **C5** | block-bootstrap pareado vs la serie **promedio** del control | IC95% inferior > **0** |
| **C6** | dosis-respuesta (§4) | las dos condiciones |
| **C7** | sensibilidad a **5 slots** | C1 y C4 se sostienen |
| **C8** | régimen con potencia (§4 de la 46): Δ en `stress_POOLED` | IC95% **no entero** por debajo de **−1.00 pt** |
| **C9** | **el cambio no es sólo de etiqueta**: el brazo tiene que mover el **resultado**, no sólo el motivo de salida — ΔCAGR ≥ +0.50 pp **y** el desplazamiento de la mezcla de motivos (`atr_trail` ↑ contra `signal_full` ↓) tiene que venir con una mejora del retorno medio por trade **de la población diferencial** | si el retorno de los trades que cambian no mejora, el brazo sólo cambió quién firma la salida |

**Qué shipea:**

- **Pasa todo** ⇒ el candidato es `trail_min_excess_atrs = k*`, y el ship es **el mecanismo, apagado**
  (§7), como la 37→53.
- **Falla C1 o C4** ⇒ **NO-SHIP**, y queda publicado que el umbral vivo **no está mal puesto** — que
  es información útil sobre una política que hoy corre en vivo.
- **Falla sólo C9** ⇒ NO-SHIP con el hallazgo *"el umbral mueve el motivo, no el resultado"*.

**Descriptivos que NO son gate:** la mezcla de motivos de salida por brazo, la tenencia media, el
retorno medio por tramo de excedente (§0.2) y la fracción que nunca arma por brazo.

---

## 7. Qué se cabla si pasa / qué NO se toca

- **No se cabla nada en esta tarea.** Si hay candidato, el ship es una tarea propia: exponer
  `paper_atr_trail_min_excess_atrs` en los settings con **default `1.0`** (el valor de hoy, o sea sin
  cambio de comportamiento), con tests del gate. Prenderlo es decisión de Chapa.
- **`paper_trading/gates.py` ya acepta el parámetro** (`trail_min_excess_atrs`, línea 91): lo que
  falta es leerlo de los settings. O sea que el enabler del engine es chico — pero **no se toca hasta
  tener veredicto**.
- No se toca `engine.py`, `strategies.py` ni la DB viva.

---

## 8. Qué NO se modela (caveats antes de correr)

- Los **desvíos declarados** del harness (`analysis/harness_config.py`): ventana de `analyze()`,
  precio de decisión de las barreras, fill, gates de re-entrada y la ventana **rodante**.
- **El HWM del harness es el máximo de los `high` diarios** desde la entrada; el engine vivo actualiza
  el HWM con el precio del scan (~15 min), así que el harness es una **cota superior** de qué tan
  rápido se arma el trailing. Eso favorece a los brazos de umbral bajo, y hay que leerlo así.
- La aproximación `avg_cost ≈ close de la barra de entrada` (sin costos ni scale-out), la misma que
  declaró el §7 de la 37.
- **No se modela** que adelantar salidas libera slots antes: el efecto de cascada existe y está
  dentro del resultado, pero no se lo aísla. Es la lección de la 51: una diferencia de CAGR puede ser
  reordenamiento de la ocupación de slots, y por eso el **control igualado en tasa** (C2/C5) es gate.

---

## 9. Plan de ejecución

1. ~~**Medición previa** de la distribución del excedente y de la población de la grilla~~ — **hecha**
   (`scripts/measure_trail_arm_t54.py`), y es la que fija el §2.
2. **Runner** `scripts/run_trail_arm_t54.py` — determinista, `--json`, con `announce(...)`,
   `announce_grid(...)`, ventana y población declaradas, cache reanudable, y la guarda de
   **corrida INVÁLIDA** (tarea 60) desde el principio.
3. **Smoke** sobre universo chico para validar la cañería. **No se leen umbrales del smoke.**
4. **Corrida completa** sobre los 127 tickers, y veredicto contra el §6 sin re-especificar nada.
