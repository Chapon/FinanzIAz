# Tarea 7 — Scale-out parcial + trailing del remanente · **PRE-REGISTRO**

_Escrito 2026-07-20, **antes** de correr ningún replay. Kill-criteria congelados acá
(regla 2 de `CLAUDE.md`). Los resultados y el veredicto se completan al final; si no
supera el umbral, se documenta y NO se shipea._

Backlog: tarea 7 (ref A4/N4 + §4 + gap A4 + research#2 §C1). Depende de **E4**
(cerrado, `docs/walkforward_power_e4_2026-07-02.md`) para el poder estadístico.

---

## 1. La pregunta

Hoy un `analyze SELL` cierra el **100%** de la posición
(`strategies.generate_trades_analyze_single`: `target_shares = float(pos.shares)`).
Dos evidencias dicen que eso regala plata:

- **Lado perdedor:** la mitad de las veces el precio sigue subiendo tras vender
  (`sell_calibration` 2026-06-30: n=32, up_after 50.0%, mean fwd5 **+2.94%**).
- **Lado ganador:** el payoff ratio es **1.14** (avg win +4.57% vs avg loss −3.21%)
  y **el 69% de la ganancia bruta viene de 4 trades** (MU/TSLA/TJX/AAPL) que
  corrieron **12–27 días**. La asimetría solo existe si se deja correr al ganador.

Pregunta: ¿vender una fracción en el flip y dejar el resto bajo trailing ATR
mejora el resultado, y con qué múltiplo de trailing?

## 2. Población y datos

**Fuente primaria (potenciada, decide):** grilla PIT sintética estilo E4 sobre el
cache **10y de 42 tickers en parquet** (`data/parquet/*__10y__1d.parquet`; se excluye
**MLTX** por historia corta → 41 tickers, mismo universo que E4
`data/harness_universe_41_10y.txt`).

- Warmup 250 barras (SMA200 + XGBoost válidos), entradas cada **spacing 20** barras.
- **Condición de entrada:** `analyze()` da `BUY` en la barra `t` (espeja el engine:
  los BUYs nacen de un `analyze BUY`). La posición abre al close de `t`.
- Etiquetas no solapadas (spacing ≥ cap) → independencia temporal, requisito del
  CPCV.
- Régimen taggeado por fecha (`bull_normal` + las 3 ventanas de stress de E4:
  2018Q4, COVID-2020, bear-2022).

**Fuente secundaria (confirmatoria, NO decide):** los **32 SELLs de señal reales**
de la cuenta viva vía `analysis/exit_replay.py`. Es la población exacta que el
cambio afecta, pero n=32 no alcanza para concluir (es justamente el motivo por el
que existe E4). Se reporta como sanity check de dirección; **si contradice a la
fuente primaria, se documenta y gana el NO-SHIP.**

### 2.1 Señal PIT — decisión de costo/calidad (medida, no asumida)

El evento que define toda la población es el **flip a `analyze SELL`**, así que
necesitamos la señal PIT en cada barra mientras la posición está abierta. Se midió
el costo real antes de elegir (2026-07-20, `.venv`, frame de 2513 barras):

| variante | costo | barrido 41×10y | acuerdo con el engine |
|---|---|---|---|
| `analyze(enable_xgboost=False)` | **2.7 ms**/call | ~4 min | **75.0%** (n=300) |
| `analyze(enable_xgboost=True)` — la del engine | **235 ms**/call | **~5.5 h** | 100% (es la real) |

Sobre el evento que importa, el proxy barato tiene **recall 74.1%** (pierde 1 de
cada 4 SELLs reales) y **precisión 86.9%** (13% de SELLs fantasma). Para un harness
cuya población *es* el evento SELL, eso distorsiona la muestra de entrada, no solo
el ruido.

**Decisión: se usa el `analyze()` completo (XGBoost ON), el mismo del engine.** Es
la opción cara y la de mayor calidad de datos — política de Chapa 2026-06-25. El
barrido es **denso** (una evaluación por barra desde el warmup), **cacheado a disco
y resumable** keyed por `(ticker, fecha)`, mismo patrón que el brazo T3 de E4. Costo
único ~5.5 h de background; el artefacto queda **reusable por las tareas 8, 9, 11,
12 y 13** (todas necesitan la señal PIT), así que se amortiza fuera de esta tarea.

> **Control descartado:** se sospechaba no-determinismo de XGBoost (lección T05).
> Medido: **100% de auto-acuerdo** corriendo `analyze()` dos veces sobre el mismo
> input in-process (n=300). El no-determinismo de T05 era del **stacking**
> (`stacking_enabled=False` en esta cuenta), no de este path. El argumento contra
> usar la señal real se cae; queda solo el costo, que se paga.

### 2.2 Configuración viva que el baseline espeja

Leída de `~/.finanzias/settings.json` + `paper_accounts` id=1 el 2026-07-20:

```
atr_period=14  atr_stop_mult=2.0  atr_tp_mult=4.0  atr_trail_enabled=True
paper_signal_sell_min_age_bdays=3   paper_signal_sell_bypass_score=0.25
commission=0.001 (0.1% notional)    slippage=0.0005 (0.05%)
initial_capital=50000   max_positions=5
```

## 3. Contrafactual exacto (congelado)

Punto sensible del veredicto — se deja escrito (paso 2 de la skill
`backtest-replay-harness`):

1. **La fracción vendida** sale al **close de la barra del flip**, con comisión y
   slippage completos.
2. **El remanente** queda gobernado por la maquinaria ATR real
   (`gates.atr_exit_decision`, espejada en `analysis/exit_replay.py`): hard stop
   desde el `avg_cost` **original**, trailing desde el HWM, TP, en ese orden; fills
   modelados gap/touch (`_exit_fill_price`).
3. **Cap de 20 días hábiles**; al cap el remanente sale al close.
4. **El HWM del remanente NO se resetea** en el scale-out (sigue el del ciclo). Un
   reset lo haría inmune al trailing por varios días — sería hacer trampa.
5. **El cash liberado NO se reinvierte** en ninguno de los brazos (tampoco en el
   baseline, que libera el 100%). Evita modelar el pipeline de BUYs; es simétrico
   entre brazos, y **conservador para el scale-out** (el baseline libera más capital
   y tampoco cobra por ello).
6. **Costos:** comisión 0.1% + slippage 0.05% sobre el notional, en las dos puntas
   (el modelo de la cuenta viva). Ver la **enmienda 1** de §4.1: contra la intuición,
   esto **no** penaliza partir la salida en dos.
7. **Gate 2b vigente en todos los brazos:** un SELL de señal con edad < 3 días
   hábiles se difiere salvo score < 0.25 (T6.4, ya shipeado). El scale-out actúa
   sobre el SELL *efectivo*, no sobre el suprimido.

## 4. Brazos pre-registrados

**Baseline B0** — el engine de hoy: el SELL de señal efectivo cierra el 100%;
stop 2.0 / trail 2.0 / TP 4.0; cap 20d.

| brazo | qué cambia | rol |
|---|---|---|
| **A₅₀** | SELL de señal vende **50%**, remanente con trailing 2.0 | **PRIMARIO** |
| B₂.₅ | A₅₀ + trailing del remanente a **2.5**×ATR (stop inicial sigue 2.0) | pre-registrado |
| B₃.₀ | A₅₀ + trailing del remanente a **3.0**×ATR (stop inicial sigue 2.0) | pre-registrado |
| C_A4 | **la señal no vende nada** (`sell_fraction=0`): solo salen stop / TP / cap | pre-registrado |
| A₃₃ / A₆₇ | fracción 33% / 67% | **exploratorios** (costo DSR) |

**Total de brazos contabilizados para el DSR: 6** (A₅₀, B₂.₅, B₃.₀, C_A4, A₃₃, A₆₇).
No se agregan brazos después de ver resultados. El sweep del trailing es sobre el
**trailing del remanente**, NO sobre el stop inicial 2×ATR (eso fue A1, cerrado
NO-SHIP con poder — no se toca).

> **Hallazgo de implementación:** hoy `atr_exit()` usa `p.stop_mult` para el hard
> stop **y** para el trailing (`trail_level = hwm − p.stop_mult × atr`). Un solo
> knob mueve los dos. Los brazos B requieren **separar `trail_mult` de `stop_mult`**
> en `AtrParams`, con `trail_mult=None → stop_mult` para no cambiar el
> comportamiento de ningún harness existente ni del engine.

### 4.1 Enmiendas al pre-registro (hechas **antes** de correr ningún brazo)

Las dos salieron de escribir los tests de la lógica pura, con cero resultados a la
vista. Se dejan asentadas para que el registro sea auditable.

**Enmienda 1 — el scale-out NO paga fricción extra (§3.6 corregida).** El
pre-registro afirmaba que partir la salida en dos cuesta un fill adicional que el
brazo "tiene que superar". Es **falso** con el modelo de costos de la cuenta viva,
que es **proporcional al notional**: `0.15%·X + 0.15%·Y = 0.15%·(X+Y)`. Partir una
venta en dos tramos cuesta exactamente lo mismo que venderla de una. La intuición de
"un fill más = más fricción" solo vale con **comisión fija por ticket o mínimo por
operación** (p.ej. el mínimo de $1 de IBKR Pro), que esta cuenta no usa. Queda como
test explícito (`test_proportional_costs_do_not_penalise_splitting_the_exit`) para
que no se re-introduzca la creencia. **Consecuencia:** el scale-out no arranca con
una desventaja de costos — el veredicto se juega puramente en el precio. Si la cuenta
pasara a comisión con mínimo por ticket, este supuesto hay que re-visitarlo.

**Enmienda 2 — el brazo C_A4 se redefine (era inalcanzable como estaba escrito).**
Se había pre-registrado como *"el SELL de señal cierra parcial solo mientras el
precio esté entre stop y TP; stop y TP cierran entero"*. Al implementarlo resultó ser
**código muerto**: el replay evalúa los niveles ATR **antes** que la señal y un
stop/TP siempre cierra el remanente **entero**, así que cuando la señal se evalúa el
precio ya está, por construcción, dentro de la banda `(stop, TP)`. La cláusula no se
ejecutaba nunca — y su otra mitad ("los niveles cierran entero") ya está en el
baseline de todos los brazos.

La forma **separable** de lo que el gap A4 realmente propone (*"hay dos sistemas de
salida en conflicto y gana el pesimista"*) es que la señal **no preempte** al nivel:
`sell_fraction = 0.0` ⇒ el flip de señal no vende nada y la posición solo sale por
stop / TP / cap. Ese es C_A4 de acá en adelante — el extremo del mismo eje que A₅₀,
no un mecanismo aparte. Bonus: el eje queda ordenado (`1.0` baseline → `0.67` →
`0.5` → `0.33` → `0.0`), así que el sweep mide una **curva dosis-respuesta** en vez
de brazos heterogéneos, que es bastante más difícil de fabricar por azar.

## 5. Métricas

- **ΔP/L (pts):** `mean(ret_brazo) − mean(ret_B0)` sobre las entradas, en puntos
  porcentuales de la posición. Con entradas equal-notional equivale a puntos sobre
  capital (se declara el supuesto).
- **Max DD:** curva compuesta equal-weight (media diaria de las posiciones abiertas,
  compuesta cronológicamente) → `max_drawdown`. Se reporta `dd_ratio = DD_brazo / DD_B0`.
- **Payoff ratio** (avg win / avg loss) y **win rate** — la tarea existe para subir
  el payoff, así que se reporta explícito.
- **MAE/MFE** por posición (percentiles) — informan si el trailing más laxo se come
  el retroceso que V1 ya midió.
- Desglose **por régimen** (bull_normal + 3 stress).

## 6. Kill-criteria (congelados — del backlog, sin aflojar)

> Se shipea el brazo que **mejore el P/L ≥ +1.5 pts** sobre B0 **sin empeorar el
> max DD más de 1.5×**.

Más el estándar de robustez que E4 dejó montado (sin esto, un ΔP/L lindo sobre 6
brazos es data mining):

- **PBO ≤ 0.5** (CSCV) — la probabilidad de que el brazo ganador in-sample sea
  mediocre out-of-sample.
- **DSR > 0** contabilizando los **6 brazos** como intentos.
- El signo del efecto **no puede depender de un solo régimen**: si el ΔP/L total es
  positivo solo por `bull_normal` y es negativo en las 3 ventanas de stress, es
  NO-SHIP (es el error que R1 documentó desde el otro lado).

**Reglas de decisión:**

- Si **ningún** brazo pasa → NO-SHIP, se documenta acá y la tarea se cierra sin
  tocar `strategies.py`.
- Si pasa un brazo **exploratorio** (A₃₃/A₆₇) pero no el primario → **no se shipea**;
  se reporta como hipótesis para un pre-registro futuro con su propia muestra.
- Si pasan varios, se shipea **el primario** si está entre los que pasan; si no, el
  de mayor DSR.
- Lo que se shipee entra **detrás de un flag, default OFF**, y con el valor validado
  como default del flag.

## 7. Limitaciones documentadas (antes de ver resultados)

- **`auto_adjust=True`** en el cache introduce lookahead en backtests largos (sesgo
  conocido, `data_audit_2026-05-26`). Aplica igual a todos los brazos → afecta el
  nivel, no el ranking. Se declara.
- **Survivorship:** los 41 tickers están vivos hoy. El backtest sobreestima. Igual
  para todos los brazos.
- **Entradas sintéticas ≠ entradas del engine vivo:** la grilla entra en *todo*
  `analyze BUY`, sin los gates de universo/liquidez/earnings ni el ranking por
  `buy_score` ni `max_positions=5`. Es una población más ancha y más neutra que la
  viva — deliberado (el `buy_score` no tiene alpha medido, ref A3), pero significa
  que el ΔP/L es el efecto **de la política de salida**, no una predicción del P/L
  de la cuenta.
- **Sin intradía:** todo es EOD, los stops se evalúan al close con fills gap/touch
  modelados. Es la misma limitación estructural que A1 (raíz del gap de stops).

## 8. Resultados

Corrido el 2026-07-20 sobre **41 tickers × 10y**, señal `analyze()` PIT completa
(92.783 evaluaciones precomputadas), **4025 entradas BUY** no solapadas
(spacing 20 = cap 20). Todos los brazos comparten exactamente las mismas entradas
(comparación pareada).

| brazo | ret medio | **Δ pts** | IC95% (bootstrap pareado) | win% | payoff | DD ratio | días | PASS |
|---|---|---|---|---|---|---|---|---|
| B0 baseline | 0.54% | — | — | 46.2% | 1.56 | — | 7.5 | — |
| **A₅₀ (primario)** | 0.61% | **+0.07** | [+0.032, +0.106] | 47.5% | 1.52 | 1.02 | 9.2 | **no** |
| B trail 2.5 | 0.57% | +0.03 | [−0.012, +0.079] | 46.8% | 1.53 | 1.02 | 9.4 | no |
| B trail 3.0 | 0.55% | +0.02 | [−0.036, +0.068] | 46.5% | 1.53 | 1.05 | 9.5 | no |
| C_A4 (señal no vende) | 1.07% | **+0.54** | [+0.410, +0.666] | 49.7% | 1.55 | 1.12 | 13.0 | no |
| A₃₃ | 0.63% | +0.09 | [+0.043, +0.143] | 47.6% | 1.52 | 1.03 | 9.2 | no |
| A₆₇ | 0.58% | +0.05 | [+0.021, +0.070] | 47.2% | 1.53 | 1.01 | 9.2 | no |

Robustez: **PBO (CSCV) = 0.000**, **DSR = 1.000** (SR 0.163 vs SR0 0.029, 6 intentos,
n=4025). O sea: la *selección* del ganador es robusta — C_A4 gana in-sample en
252/252 combinaciones. Lo que falla no es la robustez, es la **magnitud**.

### 8.1 Curva dosis-respuesta: el SELL de señal destruye valor, monotónicamente

El hallazgo limpio del run. Ordenando por cuánto se le obedece a la señal:

| fracción vendida en el flip | 1.00 (B0) | 0.67 | 0.50 | 0.33 | 0.00 (C_A4) |
|---|---|---|---|---|---|
| Δ pts vs baseline | 0.00 | +0.046 | +0.069 | +0.092 | **+0.536** |

**Monótono y sin excepciones: cuanto menos se le hace caso al SELL de señal, mejor
el resultado.** Es exactamente lo que predice el gap A4 (*"hay dos sistemas de salida
en conflicto y gana el pesimista"*) y es consistente con la evidencia previa
(`sell_calibration` 2026-06-30: 50% up_after, mean fwd5 +2.94%). El efecto es
estadísticamente sólido (p < 0.0001 en los extremos), no ruido.

**Por qué el scale-out captura tan poco de eso:** la fracción **no cambia el timing
de las salidas, solo el peso entre dos precios de salida**. Se ve en la mezcla de
salidas — A₃₃/A₅₀/A₆₇ tienen rutas de salida *idénticas* (2053 `signal_partial+
signal_full`, 505 `atr_stop`, 355 `atr_trail`, 337 `atr_tp`), solo cambian las
cantidades. El techo del scale-out es el spread entre el precio del flip y el precio
de salida del remanente, escalado por la fracción: chico por construcción. Todo el
valor está en **no vender ante la señal**, no en vender menos.

### 8.2 El efecto vive en bull_normal y se apaga en stress

Desglose de C_A4, el único brazo con efecto no trivial:

| régimen | n | Δ pts | IC95% | p(Δ≤0) |
|---|---|---|---|---|
| bull_normal | 3448 | **+0.618** | [+0.485, +0.757] | 0.0000 |
| stress_2018q4 | 120 | +0.104 | [−0.716, +0.991] | 0.4254 |
| stress_bear_2022 | 352 | **−0.231** | [−0.647, +0.197] | 0.8591 |
| stress_covid_2020 | 105 | +0.886 | [−0.201, +2.103] | 0.0580 |

El efecto es **indistinguible de cero en las tres ventanas de stress** y de signo
negativo en bear-2022. El kill-criteria §6 lo prohíbe explícitamente.

### 8.3 Ajuste por ocupación de slot (post-hoc, **no** pre-registrado)

Métrica agregada **después** de ver los resultados — se declara como tal y **no
participa del veredicto**, que ya se decide con los criterios pre-registrados. Es
diagnóstica: explica *por qué* ni siquiera el mejor brazo ayudaría en la cuenta viva.

El harness le da a cada entrada capital ilimitado. La cuenta viva tiene
`max_positions=5`: retener más tiempo significa **entrar menos veces**. C_A4 sostiene
las posiciones **13.0 días vs 7.5** del baseline (+73%). Normalizando el retorno por
unidad de tiempo-capital:

| brazo | Δ pts crudo | días | **Δ pts ajustado por slot** |
|---|---|---|---|
| A₅₀ | +0.069 | 9.2 | **−0.041** |
| B trail 2.5 | +0.033 | 9.4 | **−0.082** |
| B trail 3.0 | +0.016 | 9.5 | **−0.099** |
| C_A4 | +0.536 | 13.0 | **+0.088** |
| A₃₃ | +0.092 | 9.2 | **−0.022** |
| A₆₇ | +0.046 | 9.2 | **−0.061** |

**Los cinco brazos de scale-out pasan a negativo** y C_A4 se desploma de +0.536 a
+0.088. El poco upside que había se lo come el costo de oportunidad del slot.

## 9. Veredicto

### **NO-SHIP — ningún brazo se cablea. `strategies.py` queda intacto.**

El veredicto se apoya **solo en los criterios pre-registrados**, y falla en tres de
ellos de forma independiente:

1. **Magnitud (el criterio principal):** el umbral era **Δ ≥ +1.5 pts**. El brazo
   primario A₅₀ dio **+0.07** (21× por debajo). El mejor brazo, C_A4, dio **+0.54**
   (3× por debajo). Nada se acerca.
2. **Dependencia de régimen:** el §6 exige que el signo no dependa de un solo
   régimen. El efecto de C_A4 es enteramente `bull_normal`; en las tres ventanas de
   stress es indistinguible de cero y **negativo en bear-2022**.
3. **El sweep del trailing (research#2 §C1) no sobrevive:** 2.5× dio +0.033 y 3.0×
   dio +0.016, **ambos con IC95% cruzando cero**, y ambos claramente negativos en
   stress (−0.47 y −0.66 en 2018Q4). La hipótesis de que el trailing está
   "parametrizado para day-trading" y que 2.5–3.0×ATR es lo canónico para swing
   **no se verifica en estos datos**. Es el segundo NO-SHIP del eje de stops, después
   de A1 — y por el mismo motivo: aflojar la salida ayuda en la subida y cobra caro
   en la caída.

Nótese que **PBO=0.000 y DSR=1.000 no salvan nada**: dicen que el ganador es
consistente, no que el efecto sea grande. Es justamente la distinción que el
kill-criteria pre-registrado existe para hacer cumplir — un efecto real de +0.5 pts
que se apaga fuera de bull y que se evapora al pagar el slot no es una mejora
shipeable, por más significativo que sea estadísticamente (n=4025 hace significativo
casi cualquier cosa).

### Lo que sí queda aprendido (y vale más que la feature)

- **El SELL de señal destruye valor de forma monótona** (§8.1). No es un problema de
  *cuánto* vender: es que la señal de salida de `analyze()` es peor que dejar actuar
  a los niveles ATR. Esto apunta a la **tarea 9** (rediseño predictivo), no a la
  política de salida: es el mismo síntoma que el `buy_score` sin alpha (ref A3),
  ahora medido del lado de las ventas y con n=4025.
- **El scale-out es estructuralmente incapaz** de capturar ese valor: no cambia el
  timing, solo repondera entre dos precios (§8.1). Cualquier intento futuro por este
  eje tiene el mismo techo.
- **La idea C_A4 no está muerta, pero necesita su propio pre-registro** y un harness
  que modele `max_positions` y la competencia por capital — sin eso, cualquier
  variante que retenga más tiempo se ve artificialmente bien (§8.3). Si se retoma,
  el kill-criteria tiene que estar en Δ **ajustado por slot**, no crudo.

### Efectos colaterales que sí se conservan

El código shipeado es todo enabler medible, nada cableado a decisiones:
`AtrParams.trail_mult` (separa trailing de stop, default = comportamiento actual),
`analysis/scaleout_replay.py`, `scripts/precompute_pit_signals.py` (el artefacto de
señal PIT, ~3 h de CPU, **reusable por las tareas 8/9/11/12/13**) y
`scripts/run_scaleout_replay_t7.py`.
