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

_(a completar tras el run — nada escrito acá antes de correr)_

## 9. Veredicto

_(a completar: SHIP / NO-SHIP + por qué)_
