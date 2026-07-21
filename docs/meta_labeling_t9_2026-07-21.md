# Tarea 9 — Rediseño del modelo predictivo: meta-labeling + triple barrera + pooled · **PRE-REGISTRO**

_Escrito 2026-07-21, **antes** de codear el etiquetado, el modelo y el harness, y
antes de correr ningún brazo. Todo lo que dice "CONGELADO" queda fijado acá y no se
toca después de ver un solo número. Resultados y veredicto se completan al final._

Backlog: tarea 9 (ref A3 + §3 + research §1-§2 + arch review §3), severidad **ALTA**.
Depende de **E4** (CPCV/DSR/PBO, `analysis/walkforward_power.py`) y de los enablers ya
shippeados por las tareas 7 y 8 (`data/pit_signals/`, `analysis/portfolio_sim.py`).

---

## 1. La pregunta

El `buy_score` que decide **qué nombres entran** es
`_default_strength("BUY", ml_probability)` (`paper_trading/strategies.py:271-275`), o
sea la probabilidad calibrada de `analyze()`. Ese número sale de un XGBoost
**entrenado por ticker, dentro del scan**, sobre la etiqueta
`close[t+5] > close[t]` (`analysis/ml_signals.py:551-561`).

Tres cosas medidas, no supuestas:

- **`corr(buy_score, fwd5) ≈ −0.08` (n=27)**, auditoría 2026-06-30. No anticipa el
  retorno a 5 días. El signo es negativo pero el n no alcanza para afirmar nada más
  que "no hay señal detectable".
- **El val set es de ~40 muestras** por ticker → la calibración isotónica degrada al
  modelo crudo y el log tira `large train-val gap (99% vs 55%)` (sobreajuste) y
  `val_acc std >8%` en casi todos los tickers (inestabilidad).
- Las tareas 7 y 8 llegaron acá desde dos lados distintos. La 7 encontró una **curva
  dosis-respuesta monótona**: cuanto menos se le hace caso al SELL de `analyze()`,
  mejor el resultado (fracción vendida 1.00 → +0.00 pts … 0.00 → +0.536, p<0.0001).
  La 8 encontró que la información de régimen **estaba bien** y el problema era qué se
  hacía con ella. Las dos apuntan al mismo lugar: **la señal**, no la política.

Con `max_positions=5` y 41 tickers, hay días con más candidatos BUY que slots. El
ranking **decide cuáles se toman y cuáles se pierden**. La pregunta de esta tarea no es
"¿el score sirve para sizear?" (ya está fuera del sizing) sino:

> **¿Debe el `buy_score` seguir eligiendo las entradas, o hay algo mejor — incluso
> algo que no predice nada?**

## 2. Qué NO toca (invariante duro)

Los brazos difieren **solo en el orden de prioridad entre candidatos BUY que compiten
por el mismo slot**. Ninguno cambia:

- **Cuándo aparece un candidato** — la señal primaria BUY de `analyze()` es idéntica en
  los cuatro brazos y es la que ya está precomputada PIT.
- **Ninguna salida** — stops, trailing, take-profit, SELL de señal y Gate 2b son
  idénticos. Una posición abierta en dos brazos con el mismo ticker y la misma fecha de
  entrada **tiene que salir en la misma fecha y al mismo precio**. Se verifica con el
  mismo chequeo que usó R2 (`check_exit_invariant`). Si no se cumple, es un bug, no un
  resultado.
- **El tamaño de la posición** — sizing igual en todos (slice de cash / slots libres).
  El eje "cuánto exponerse" es de las tareas 10 y 20, y se mide aparte a propósito.

## 3. La etiqueta (CONGELADA)

Para cada barra `i` donde la señal primaria dice **BUY**:

> **`y = 1` si el precio toca el take-profit ANTES que el stop, dentro de los 20 días
> hábiles siguientes. `y = 0` en cualquier otro caso** (stop primero, o ninguna de las
> dos barreras dentro de la ventana).

Los tres lados de la barrera, con los parámetros **vivos del engine**, sin barrer nada:

| barrera | valor | de dónde sale |
|---|---|---|
| stop (inferior) | `entry − 2.0 × ATR(14)` | `AtrParams.stop_mult`, el valor vivo (A1 lo re-confirmó NO-SHIP con poder: n=4674, PBO=0.004) |
| take-profit (superior) | `entry + 4.0 × ATR(14)` | `AtrParams.tp_mult` |
| vertical (tiempo) | 20 días hábiles | `cap_days` del harness = el mismo N que la tarea 13 (ENT1) usará para el time stop |

Cuatro decisiones de etiquetado, congeladas con su razón:

1. **`entry` = close de la barra de la señal.** Es donde entra `replay_cycle` y donde
   entra el engine (scan EOD). No se usa el open del día siguiente.
2. **Las barreras se evalúan sobre el CLOSE diario, no sobre High/Low.** El engine es
   un scanner EOD: no puede actuar sobre un toque intradía que revierte antes del
   cierre. Etiquetar con High/Low mediría una capacidad que el sistema no tiene.
3. **El trailing NO participa de la etiqueta.** La triple barrera es stop duro / TP /
   tiempo. El trailing es un refinamiento de la *política de ejecución*, path-dependent,
   y meterlo convertiría la etiqueta en "¿qué hace mi política de salida?" en vez de
   "¿este candidato va para arriba o para abajo?". **El simulador sí usa el trailing**
   (usa la maquinaria de salida completa y viva), así que la evaluación no se ablanda:
   solo el *target de aprendizaje* se mantiene limpio.
4. **Timeout cuenta como 0.** Es la forma accionable de la pregunta: con un slot
   ocupado y `max_positions=5`, un candidato que en 20 ruedas no llegó a ningún lado es
   un slot desperdiciado. No se usa el signo del retorno en la barrera vertical.

**Nota de honestidad sobre el balance de clases:** con TP a 4×ATR y stop a 2×ATR el
TP es el doble de lejos, así que se espera que `y=1` sea **minoritario**. Eso es un
hecho del problema, no un defecto. Se reporta la tasa base observada y el modelo se
evalúa por AUC/precisión en el top del ranking, no por accuracy.

## 4. Las features (CONGELADAS)

Se reusan las de `_build_features` (`analysis/ml_signals.py:482-548`) porque ya están
testeadas y son PIT por construcción, **con dos correcciones obligatorias para poder
poolear** (una feature en unidades de precio no es comparable entre AAPL a $200 y F a
$12):

| feature | tratamiento |
|---|---|
| `ret_1d/3d/5d/10d/20d` | tal cual (log-retornos, ya adimensionales) |
| `rsi`, `rsi_delta5` | tal cual (acotadas 0-100) |
| `macd_hist`, `macd_hist_chg` | **divididas por el close** — están en unidades de precio (corrección para poolear) |
| `bb_position`, `bb_width` | tal cual (ratios) |
| `volume_ratio` | tal cual (ratio vs SMA20 del propio ticker) |
| `volatility_20` | tal cual (anualizada, adimensional) |
| `price_sma20`, `price_sma50` | tal cual (ratios) |
| **`atr_rel` = ATR(14) / close** | **agregada** — la escala de la barrera relativa al precio es la variable que hace comparables los targets entre tickers |

**`ml_probability` NO entra como feature.** Razón: el meta-modelo tiene que responder
una pregunta *distinta* con datos *pooled*; si además se le da de comer el score
actual, deja de ser posible atribuir la diferencia a la pregunta nueva y hereda el
ruido que la tarea vino a diagnosticar. La señal primaria ya está presente en el
diseño de otra forma — **la población son exclusivamente las barras donde el primario
dijo BUY**, que es precisamente el setup de meta-labeling de López de Prado.

**No se agregan features nuevas de otra fuente** (catalysts, sorpresas, régimen,
insiders). Cada una sería un experimento aparte con su propio costo de DSR y su propia
tarea en el backlog (11, 12).

## 5. Protocolo de entrenamiento (CONGELADO)

- **Pooled cross-ticker:** un solo modelo sobre las barras BUY de los 41 tickers
  juntas. Es el fix estructural del `val_acc std >8%` y del gap 99/55: en vez de 41
  modelos con ~40 muestras de validación, uno con miles.
- **Arquitectura:** exactamente `_make_raw_xgb()` (shallow, `max_depth=3`,
  `n_estimators=120`, regularizado, `random_state=42`). **No se tunea ningún
  hiperparámetro.** Usar la misma arquitectura que el baseline aísla la variable que se
  está midiendo (la pregunta + el pooling), y cualquier tuneo sería un sweep sobre la
  misma muestra.
- **Calibración isotónica** sobre el fold de validación, que pooled sí supera las 100
  muestras que el path per-ticker nunca alcanzaba.
- **Walk-forward por año calendario, expandiendo:** entrenar con todo lo anterior al
  año `Y`, predecir el año `Y`. Primer año de test = el quinto de la muestra (≥4 años
  de entrenamiento inicial). Todas las predicciones que consume el simulador son
  **estrictamente out-of-sample**: cada barra la puntúa el fold que no la vio.
- **Purge + embargo (López de Prado):** de cada ventana de entrenamiento se **eliminan**
  las muestras cuya ventana de etiqueta (20 días hábiles) se solapa con el período de
  test, más un **embargo de 20 días hábiles** después del corte. Sin esto el
  solapamiento de etiquetas filtra futuro y el AUC sale inflado.
- **Sin re-entrenamiento intra-año** y sin ninguna decisión tomada mirando el
  resultado del test.

## 6. Brazos pre-registrados

| brazo | cómo ordena los candidatos que compiten por un slot | rol |
|---|---|---|
| **B0_neutral** | **alfabético** dentro del mismo día — cero información predictiva | **baseline honesto** |
| **B1_buy_score** | por `ml_probability` de `analyze()` (descendente) | **el engine de hoy** |
| **M1_meta_pooled** | por `P(TP antes que stop)` del meta-modelo pooled, OOS | **PRIMARIO** |
| **F1_mom121** | por **momentum 12-1** (retorno de los 12 meses previos excluyendo el último mes), percentil cross-sectional del día | plan B factor-based |

**4 brazos**, contabilizados como 4 intentos para el DSR.

Notas:

- **B0 no es "no hacer nada"**: es el contrafactual honesto de "el ranking no aporta".
  El orden alfabético es determinista y no tiene ninguna relación con el retorno futuro.
- **B1 es el sistema vivo.** La comparación `B1 vs B0` es, por sí sola, la respuesta a
  "¿el score se gana el derecho a elegir entradas?" — y tiene su propia regla de
  decisión en §9.
- **F1 usa momentum 12-1 puro, sin la pata de "delta de revisiones de analistas"** que
  el backlog nombraba. Razón medida: las revisiones **no son reconstruibles
  point-in-time hacia atrás** (yfinance sirve snapshots móviles del consenso actual; el
  histórico PIT recién se está acumulando en `analyst_estimate_snapshots` desde
  T-CAT-5b). Backtestearlas con el consenso de hoy tendría sesgo de revisión — el mismo
  muro que bloquea T-CAT-5b. Se deja anotado como ampliación futura cuando haya
  temporadas acumuladas. **El 12-1 es el estándar académico y no se barre** (no se
  prueban 6-1, 9-1, 12-2).
- **No hay brazo de umbral/abstención.** El gate conformal es la ampliación declarada
  en el backlog *después* de que el meta-modelo base pase; meterlo ahora infla los
  intentos y encarece el DSR de todos.

## 7. Harness

**`analysis/portfolio_sim.py`** (enabler de R2): `max_positions=5`, capital finito
$50.000, la entrada que llega sin slot **se pierde**, el cash liberado se reinvierte,
costos 0.1% comisión + 0.05% slippage en las dos puntas, salidas con `replay_cycle`
(la maquinaria viva completa, trailing incluido).

Requiere **dos extensiones**, ambas necesarias para que la pregunta sea contestable y
las dos declaradas acá antes de escribirlas:

1. **Hook de ranking.** Hoy el simulador procesa las entradas en orden cronológico y
   desempata alfabéticamente — que es exactamente B0. Se agrega un score inyectable por
   candidato para que, **entre los candidatos del mismo día**, entren primero los de
   score más alto. Sin esto no hay forma de medir un ranking. R2 declaró esta ausencia
   en su §9 como "no modelado"; acá es *la variable bajo estudio*.
2. **Un ticker no se abre dos veces mientras está abierto.** El engine saltea los
   tickers ya en cartera (`strategies.py`: `if t in held_tickers and t not in
   forced_exits: continue`). El simulador de R2 no lo hacía porque con `spacing=20` el
   solapamiento era raro; con la población de esta tarea (§8) deja de serlo.

> **Consecuencia declarada de antemano:** las dos extensiones **cambian los números
> absolutos del baseline** respecto de los publicados por R2 (CAGR 18.98% / DD 21.6%).
> Los de R2 **no** se usan como referencia. B0 se re-corre en esta población y es el
> único baseline válido para esta tarea. Cualquier comparación con los números de R2
> sería una comparación entre poblaciones distintas.

## 8. Población

Todas las barras con señal primaria **BUY** de los 41 tickers × 10 años del artefacto
PIT (`data/pit_signals/`, 92.783 evaluaciones de `analyze()` con XGBoost real,
generado por la tarea 7).

**Sin el `spacing=20` de las tareas 7 y 8.** Ese espaciado existía para garantizar
independencia entre eventos en un test por-trade; acá **borraría justamente el fenómeno
que se quiere medir** (la competencia entre candidatos del mismo día por un slot). La
independencia que el CPCV necesita se recupera de otra forma: los brazos comparten
exactamente la misma población de candidatos ofrecidos, y el CPCV se corre sobre los
bloques temporales de la curva de equity, no sobre trades individuales.

Ventanas de régimen de E4: `bull_normal` + `stress_2018q4` + `stress_covid_2020` +
`stress_bear_2022`.

## 9. Kill-criteria (CONGELADOS)

**Métrica primaria: CAGR sobre el equity terminal de `portfolio_sim`.** No P/L
acumulado en puntos — es el defecto de especificación que la tarea 8 detectó post-hoc
(sobre 9 años de compounding, un umbral de "+1.5 pts acumulados" es ruido y lo pasa
cualquier cosa). El costo de oportunidad se mide sobre equity terminal.

> **Se shipea el brazo ganador solo si cumple las cuatro condiciones:**
>
> 1. **CAGR ≥ CAGR(B0_neutral) + 1.5 puntos porcentuales.**
> 2. **max DD de la cartera ≤ 1.5 × max DD(B0_neutral)** (el DD de la cartera entera,
>    no el DD dentro de las ventanas de stress — ese fue el espejismo de R2a).
> 3. **DSR > 0** contabilizando los **4 brazos** como intentos.
> 4. **PBO ≤ 0.5** (CSCV).
>
> Y como gate de integridad, previo a leer cualquier resultado:
> **invariante de exits verificado** (§2) y **desvío de la curva de equity vs la
> contabilidad de cash < 0.01%**, el mismo chequeo que R2 corrió antes de mirar sus
> números.

Métricas secundarias que **se reportan pero no deciden**: Sharpe de la curva diaria,
exposición, número de trades, AUC y precisión OOS del meta-modelo, desglose por
régimen. Se declaran secundarias de antemano para que no haya metric-shopping.

### Tabla de decisión (congelada)

| resultado | qué se hace |
|---|---|
| **M1 pasa las 4 condiciones** | **SHIP** con el ciclo de vida offline de §11 (es parte del done, no una tarea aparte). |
| **M1 no pasa pero F1 sí** | **NO se shipea** — regla ya usada en R2b: un brazo secundario que pasa sin el primario no se cablea. Se documenta y se abre tarea propia con pre-registro nuevo. |
| **Ninguno pasa, y `B1 < B0 − 1.5 pts` de CAGR** | El score **está eligiendo peor que el azar**. Se shipea la **simplificación**: el ranking pasa a no-predictivo y el `buy_score` queda **display-only**. Es un cambio de decisiones de trading y por eso está pre-registrado acá con su umbral, no decidido después. |
| **Ninguno pasa y `\|B1 − B0\| ≤ 1.5 pts`** | **No hay diferencia medible.** No se cambia nada en el engine (cambiar sin evidencia es tan malo como no cambiar con evidencia). Se documenta que el ranking por score no se distingue del azar en esta muestra y el score se anota como no-validado. |
| **Ninguno pasa y `B1 > B0 + 1.5 pts`** | El score sí aporta pese al `corr(score,fwd5)≈−0.08`. Se documenta el hallazgo (el ranking relativo puede tener valor aunque el nivel absoluto no correlacione) y no se toca nada. |

## 10. Lo que se declara de antemano que NO se mide

- **No se mide sizing.** Todos los brazos sizean igual. El eje "cuánto exponerse" es de
  las tareas 10 y 20, co-registradas entre sí, y mezclarlo acá haría inatribuible el
  resultado.
- **No se mide el umbral de abstención** (conformal / selective prediction): ampliación
  posterior declarada en el backlog.
- **No se mide la señal primaria.** Los cuatro brazos reciben los mismos candidatos.
  Que el primario genere buenos o malos candidatos es otra pregunta (tareas 11 y 12,
  fuentes de leads nuevas).
- **El universo son 41 tickers grandes y líquidos, sobrevivientes.** Hay sesgo de
  supervivencia en el universo (el mismo que arrastran todos los harness del proyecto
  desde E4). No se corrige acá; se anota como limitación de todo lo que se concluya.
- **El harness no modela el screen E1b** (`paper_universe_screen_enabled` sigue false en
  el schema vivo).

## 11. Definición de "done" si el resultado es SHIP (ARQ2 — serving)

El brazo ganador **no se cablea entrenando dentro del scan**. Hoy
`train_xgboost_signal` entrena 52 modelos por arranque, in-memory, sin trazabilidad.
Si M1 pasa, se shipea con ciclo de vida offline y eso es parte de esta tarea:

- Entrenamiento **programado** (mismo patrón que el rebuild de `surprise_profiles`).
- Artefacto **persistido y versionado**: joblib + fingerprint de los datos + métricas en
  `models/model_registry.json`.
- El scan **solo hace inferencia** sobre el artefacto cargado → scans deterministas.
- Cada orden registra `model_version` en `notes` → "qué modelo decidió esta orden" queda
  auditable.
- Flag propio, **default OFF** hasta la verificación operacional.

## 12. Cierre oportunista (no afecta el veredicto)

Al tocar `analysis/ml_signals.py` se cierra la observación cosmética del backlog: el
warning `val_acc std 8% > 8%` (línea ~725) compara sin redondear y formatea con `%.0f`
→ imprime una desigualdad falsa. Fix: `%.1f` en el mensaje.

---

## 13. Resultados

_(a completar después de correr — nada de esta sección existe al momento de congelar
lo de arriba)_
