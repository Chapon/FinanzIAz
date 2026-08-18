# Pre-registro CONGELADO — El múltiplo del stop ATR bajo la regla que el engine ejecuta (Tarea 34, STOP-LOOSEN)

**Fecha:** 2026-08-18 · **Estado:** congelado ANTES de codear el harness (regla 2).
**Ref:** `docs/BACKLOG.md` tarea 34 · `docs/stop_price_t26b_2026-08-16.md` §3 (de dónde sale el lead) ·
`docs/fill_lookahead_t33_2026-08-16.md` (el fill honesto que la desbloquea) ·
`docs/stop_cal_t26_2026-08-13.md` (la corrida INVÁLIDA que preguntó lo mismo con la regla equivocada) ·
`analysis/harness_config.py` (los cinco desvíos ya declarados).

Fija población, brazos, la regla de decisión y los sanity **ANTES de correr**. Nada se re-decide
después de ver resultados. Si el candidato no supera el umbral, se documenta NO-SHIP y
`atr_stop_mult` queda en 2.0.

---

## 0. Qué se miró ANTES de congelar — y qué se evitó a propósito

El pre-registro se escribió después de auditar el instrumento (lección 3 de la 26b: *"congelar los
brazos no exime de auditar el instrumento"*). Lo que se corrió y se miró:

- **Costo de corrida:** carga PIT 13,1 s + **3,9 s por brazo**. La rejilla entera y el walk-forward
  entran en minutos, así que **ninguna decisión de diseño de acá está limitada por tiempo de cómputo**.
- **Tasa de disparo del stop por múltiplo** bajo `touch` (49,6% a 1.0 → 0,0% en `off`) y **trades
  tomados** por brazo. Los de 1.0–3.0 ya estaban publicados en la 26b §1; se agregaron 3.5 y `off`.
- **La fracción de entradas que los gates 5 y 5b bloquearían en vivo** (§3). Ésta es la que justifica
  el enabler y es el motivo por el que la tarea no se pudo congelar sin auditar.

Lo que **deliberadamente NO se miró**: el **CAGR, el Sharpe y el maxDD de `touch_3.5` y `touch_off`**
— los dos brazos nuevos, o sea justo los que pueden dar vuelta la lectura de la curva vía C6. Se
miraron sólo contadores mecánicos (tomadas, share de stop, entradas bloqueadas). La rejilla 1.0–3.0
sí está publicada desde la 26b y se cita tal cual; eso es el lead, y es exactamente por eso que la
tarea existe.

---

## 1. El lead — y por qué no alcanza como resultado

La 26b midió, bajo `touch` (la regla que el engine ejecuta) y con el fill honesto, a 10 slots:

| múltiplo | 1.0 | 1.5 | **2.0 (VIVO)** | 2.5 | 3.0 |
|---|--:|--:|--:|--:|--:|
| CAGR | −0.49% | 0.76% | **4.41%** | 6.19% | **9.92%** |

El múltiplo vivo está en el tramo bajo de la curva, y la dirección que gana es **aflojar** — la
**opuesta** a la que la T26 quiso cablear. Tres razones por las que eso es lead y no hallazgo:

1. **El máximo cae en el borde de la rejilla.** 3.0 fue el brazo más suelto que se corrió. Un máximo
   en el borde no es un óptimo: es una **dirección**. Nada en la 26b distingue *"el óptimo está en 3.0"*
   de *"cuanto menos stop, mejor"*, y son dos afirmaciones muy distintas.
2. **A 5 slots la curva se desordena y no es monótona:** 3.45 / 0.48 / 3.04 / 7.10 / 6.11. El máximo
   se corre a 2.5 y 2.0 deja de estar en el peor tramo (1.5 es peor). Un brazo que gana a una config y
   se desacomoda en la otra es candidato, no hallazgo.
3. **El lead salió de la misma muestra sobre la que se lo evaluaría.** Elegir el ganador de una
   rejilla y re-testearlo contra los mismos datos no agrega información.

## 2. Lo que esta tarea NO puede ser: re-correr la rejilla de la 26b

El harness es **determinista**. Re-correr `touch_{1.0…3.0}` sobre la misma población devuelve los
mismos dígitos. Para que la 34 valga algo tiene que medir tres cosas que la 26b **no** midió:

- **(a) La forma de la curva más allá del borde** — rejilla extendida a 3.5 y `off`, que es lo único
  que puede distinguir un óptimo interior de una monotonía.
- **(b) La selección del múltiplo fuera de muestra** — un walk-forward que elija el múltiplo con datos
  pasados y lo cobre en datos que no vio. Es el gate anti-overfit que corresponde a refinar **un**
  parámetro (selección OOS + block-bootstrap pareado; PBO/CSCV es grueso con pocos brazos colineales).
- **(c) El efecto con los gates de re-entrada vivos modelados** — el §3, que es lo que apareció al
  auditar.

## 3. El SEXTO desvío harness↔engine, medido al auditar (y por eso la tarea lo modela)

`analysis/portfolio_sim.simulate_portfolio` sólo rechaza una entrada si el ticker **ya está abierto**
(`allow_reentry_while_open=False`). El engine vivo tiene además **dos gates de re-entrada** que el
harness no modela, los dos alimentados por **ciclos cerrados**:

| gate | dónde | regla viva (`~/.finanzias/settings.json`) |
|---|---|---|
| **Gate 5 — anti-whipsaw** | `engine.py:993-1003` | bloquea el re-BUY si el último ciclo cerrado del ticker dentro de **7 d** cerró con pérdida. `paper_whipsaw_min_loss_pct=0.0` ⇒ **cualquier** pérdida bloquea (es el ajuste **más estricto**, no un no-op) |
| **Gate 5b — anti-churn** | `engine.py:1013-1025` | bloquea si hay **≥3 ciclos cerrados** del ticker dentro de **10 d**, agnóstico al P/L |

**Por qué no es una nota al pie — medido sobre la rejilla, antes de congelar:**

| brazo | tomadas | %stop | bloqueadas por Gate 5 | bloqueadas por Gate 5b |
|---|--:|--:|--:|--:|
| `touch_1.0` | 4200 | 49.6% | **36.36%** | 2.64% |
| `touch_1.5` | 3241 | 33.6% | 31.16% | 0.77% |
| **`touch_2.0` (VIVO)** | 2818 | 19.9% | **28.21%** | 0.25% |
| `touch_2.5` | 2620 | 11.6% | 25.27% | 0.11% |
| `touch_3.0` | 2541 | 7.2% | 23.57% | 0.00% |
| `touch_3.5` | 2487 | 4.3% | 22.52% | 0.00% |
| `touch_off` | 2388 | 0.0% | **21.15%** | 0.00% |

Entre **un quinto y más de un tercio** de las entradas que el harness toma, el engine vivo **no las
habría tomado**. Y —esto es lo decisivo— **el share se mueve monótonamente con el eje bajo test**:
15,2 pp de brecha entre las puntas. Aplicado el criterio que dejó escrito la T33 (*"¿los brazos
disparan barreras a tasas distintas?"* — si no, el desvío es un **nivel común** y se cancela en la
comparación; si sí, no se cancela), la respuesta acá es **sí, con un factor de 7 en la tasa de stop**.
El desvío **no se cancela** y puede mover el signo, exactamente como pasó con el fill en la T23.

**Mecanismo:** un stop ajustado cierra muchos ciclos chicos en rojo; cada uno de ellos arma en vivo un
**cooldown de 7 días** sobre ese ticker que el harness ignora. O sea que el harness le regala a los
brazos ajustados re-entradas que producción les niega, y se las regala **más cuanto más ajustado el
brazo**. La dirección del sesgo es desconocida (bajo selección ~55:1 un slot bloqueado se lo lleva el
siguiente candidato, que no es obviamente peor), pero la **asimetría** no lo es.

**Decisión, congelada:** la 34 **modela los dos gates** (enabler `live_gates`, default OFF ⇒ cero
cambio para lo publicado, mismo patrón que `eval_mode` en la 26b) y **dicta el veredicto con los gates
ON**, porque la pregunta es *"¿qué pasa si muevo `atr_stop_mult` en la cuenta viva?"* y la cuenta viva
tiene los gates puestos. La rejilla con gates **OFF** se reporta al lado, para comparabilidad con la
serie publicada.

**Fuera de alcance, declarado:** los once harness publicados corren **sin** estos gates. Si eso obliga
a re-leer alguno es una pregunta con tarea propia (patrón T33) — **desde la 34 no se re-lee nada**.

---

## 4. Población y config (CONGELADO — idénticas a la 26b)

- **Universo:** `data/harness_universe_live_acct2.txt` (**127** tickers con datos PIT).
- **Entradas:** eventos `analyze() = BUY` point-in-time (`data/pit_signals/`, `10y`, `warmup=250`).
  Son **143.096**, entre **2017-07-07** y **2026-08-06**.
- **Cartera:** `portfolio_sim`, `max_positions=10`, `initial_capital=50.000`, `cap_days=250`,
  `CostModel()`, `allow_reentry_while_open=False`, `tp_mult=4.0`, `period=14`, `trail_enabled=True`,
  flip `analyze SELL` con Gate 2b, orden alfabético, sin overlay T20.
- **`eval_mode="touch"`, `fill_mode="decision"`** — la regla viva y el fill honesto (T33).
- **`live_gates=True`** (§3) para los brazos que dictan el veredicto.
- **Sensibilidad reportada** a `--max-positions 5`. El veredicto se dicta a **10**.

**Un solo knob mueve stop y trailing, y eso es fiel a producción:** `gates.py:101` calcula
`stop = avg_cost − stop_mult×ATR` y `gates.py:103` calcula `trail = hwm − stop_mult×ATR`, **el mismo**
`stop_mult`; el harness espeja esto con `AtrParams.trail_mult=None`. O sea que mover el múltiplo
afloja **las dos** barreras de abajo, en el harness igual que en vivo. No es un confound respecto de
producción: es la unidad de decisión correcta. La descomposición (aflojar sólo el stop duro) entra
como **diagnóstico descriptivo**, no como brazo shipeable.

## 5. Brazos (CONGELADO)

**Rejilla de decisión — 7 múltiplos × 2 modos de evaluación = 14 brazos**, todos con `live_gates=True`.

| | 1.0 | 1.5 | **2.0** | 2.5 | 3.0 | 3.5 | `off` |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **`touch`** (regla viva) | | | **BASELINE** | | | | |
| **`close`** (cota inferior, C8) | | | | | | | |

- **BASELINE = `touch_2.0` con `live_gates=True`.** La regla, el múltiplo y los gates vivos.
- **`off`** = `stop_mult = 1e9` (nunca dispara), igual que `S_off` de la T26. Apaga stop duro **y**
  trailing, que es lo que hace el knob.
- **CANDIDATO = `touch_M*`**, donde **`M*` lo elige el walk-forward del §6** — no se nombra acá.
  Nombrar `touch_3.0` sería elegir el ganador de la corrida de la 26b sobre la misma muestra, que es
  justo el defecto que la tarea existe para no cometer.
- **Rejilla con `live_gates=False`:** se corre y se reporta **descriptiva**, para medir cuánto vale el
  desvío del §3 y para comparar contra la 26b. **No dicta nada.**

**Diagnóstico (descriptivo, NO shipeable):** `D1_stop_only_M*` — stop duro en `M*` con
`trail_mult=2.0` fijo, para separar cuánto del efecto viene del stop y cuánto del trailing. Patrón del
`D1_stop_only_3.0` de la T26. **No entra en ningún criterio**: el desacople quedó NO-SHIP en la T7 y
el knob vivo es uno solo.

**Sanity del instrumento (miran el futuro, no shipeables):** `ORACULO_STOP` (filtro de stops con
look-ahead a 20 ruedas) y `AZAR_MISMA_TASA` (supresión aleatoria a la misma tasa, `seed=20260813`),
los dos en `touch`, `stop_mult=2.0`, `live_gates=True`. Son los de la 26b, que ya pasaron ahí.

## 6. El walk-forward de la selección (CONGELADO) — el núcleo de la tarea

No se valida un múltiplo: se valida el **procedimiento que lo elige**. Ésa es la forma correcta de
tratar "elegí el mejor de una rejilla" sin auto-engañarse.

- **5 folds anclados y expandidos**, con bloques OOS de 12 meses:

  | fold | train (entradas con `entry_date` <) | test OOS |
  |---|---|---|
  | 1 | 2020-08-01 | 2021-08-01 → 2022-07-31 |
  | 2 | 2021-08-01 | 2022-08-01 → 2023-07-31 |
  | 3 | 2022-08-01 | 2023-08-01 → 2024-07-31 |
  | 4 | 2023-08-01 | 2024-08-01 → 2025-07-31 |
  | 5 | 2024-08-01 | 2025-08-01 → 2026-07-31 |

- **Embargo de 365 días corridos** entre el fin del train y el inicio del test (≥ `cap_days=250`
  ruedas): ningún trade del train puede seguir abierto dentro de su propio test. Es el purge+embargo de
  `cpcv_splits`, aplicado a una partición secuencial.
- **Regla de selección, congelada y única:** en cada fold, `M_k` = el múltiplo con **mayor CAGR** en el
  train. Una sola métrica de selección; la variante por Sharpe se reporta **descriptiva** y no decide.
- **Equity OOS encadenada:** cada bloque OOS arranca con la equity final del bloque anterior
  (empezando en 50.000), y de esa curva sale **un** CAGR OOS y **un** maxDD OOS. Es lo que
  efectivamente habría pasado aplicando el procedimiento en el tiempo.
- **Contra qué se compara:** la misma cadena OOS corriendo el **baseline fijo `touch_2.0`**.
- **`M*`** = el múltiplo elegido por mayoría de folds (y C7 exige que esa mayoría sea real).

**Limitación declarada antes de correr:** de los tres regímenes de stress, los bloques OOS sólo
contienen **`stress_bear_2022`**; `stress_2018q4` y `stress_covid_2020` caen enteros en el train del
fold 1. Por eso el criterio de régimen (C5) se mide **in-sample sobre los cuatro**, y el OOS aporta
robustez temporal, no cobertura de regímenes.

## 7. Sanity del instrumento (si falla alguno, la corrida es INVÁLIDA y no hay veredicto)

1. **Contabilidad:** `|equity_curve[-1] − final_equity| / final_equity ≤ 1e-6` en todos los brazos.
2. **El instrumento ve CALIDAD de salida — contra el control IGUALADO, no contra el baseline**
   (lección T26): `CAGR(ORACULO_STOP) ≥ CAGR(AZAR_MISMA_TASA) + 1.50 pp` **y**
   `maxDD(ORACULO_STOP) ≤ maxDD(AZAR_MISMA_TASA) − 5.00 pp`.
3. **Control mecánico del brazo `off`:** `stop_share == 0.0` exacto (patrón `S_off` de la T26).
4. **Monotonía mecánica de la tasa de disparo:** `stop_share` no creciente a lo largo del múltiplo, en
   los dos modos. Es una invariante del eje: si se rompe, el brazo está mal construido. (Verificada
   con `live_gates=False` en la sonda del §3; se re-verifica con los gates ON.)
5. **El enabler del §3 muerde y no está roto:** la fracción de candidatos elegibles bloqueada por Gate
   5 en el BASELINE cae en **[15%, 45%]** (la sonda sin modelar midió 28,2%). 0% o ~100% significa
   enabler mal cableado, no hallazgo.
6. **Sin look-ahead en el enabler:** un ciclo cuya salida ocurre **después** de la fecha del candidato
   no puede bloquearlo. Se verifica por unit test sobre ciclos sintéticos, no en agregado.

## 8. Regla de decisión (CONGELADA)

**Candidato** = `touch_M*` (§6). **Baseline** = `touch_2.0`. Los dos con `live_gates=True`, 10 slots.
Se cabla `atr_stop_mult = M*` **sólo si pasa las ocho**:

| # | Criterio | Umbral |
|---|---|---|
| **C1** | **ΔCAGR fuera de muestra**: cadena OOS del procedimiento − cadena OOS del baseline fijo | ≥ **+1.00 pp** |
| **C2** | **Riesgo, declarado al frente:** maxDD(candidato) ≤ maxDD(baseline) + **1.00 pp**, **in-sample Y en la cadena OOS** | las dos |
| **C3** | Block-bootstrap pareado sobre Δ(retorno diario) in-sample, bloques 20 d, 2000 resamples, `seed=12345` | **IC95% inferior > 0** |
| **C4** | ΔSharpe(candidato − baseline), in-sample | ≥ **+0.05** |
| **C5** | **Robustez de régimen:** Δ(ret medio por trade) en cada uno de los **4** | ≥ **−0.05 pts** |
| **C6** | **Forma de la curva:** el máximo de CAGR in-sample de la rejilla `touch` es **interior** | máximo ∉ {`3.5`, `off`} |
| **C7** | **Estabilidad de la selección:** `M*` elegido en ≥ **4 de los 5** folds | ≥ 4/5 |
| **C8** | **Robustez de especificación:** el signo de ΔCAGR(M* − 2.0) se mantiene ≥ 0 **(a)** a 5 slots y **(b)** en modo `close` | las dos |

**Por qué C2 y C4 son más exigentes que en la 26b** (que pedía maxDD ≤ base + 2.00 pp y Sharpe ≥ base
− 0.05): allá el eje era *contra qué precio se decide*, acá el eje **es el knob de riesgo**. Aflojar un
stop compra retorno con más riesgo por construcción; si el resultado no mejora la relación
riesgo/retorno, no es una regla mejor — es apalancamiento, y para eso no hace falta tocar el stop.

**Por qué C8(b) existe:** el engine samplea cada ~15 min, así que su frecuencia de disparo está
**entre** `close` (cota inferior) y `touch` (superior). Como `touch` **sobre-dispara**, el bracket
sesga **a favor de aflojar** — que es justo la dirección del candidato. Exigir el signo en las **dos**
cotas es exigirlo en todo el intervalo que contiene al engine. Sin esto, un resultado podría ser
artefacto del techo.

**Casos partidos, resueltos ex ante:**

- **C1 pasa y C2 falla** → **NO-SHIP.** Ver arriba: más retorno con más drawdown en el knob de riesgo
  no es mejorar la regla.
- **C6 falla (el máximo cae en `3.5` o en `off`)** → **NO-SHIP, y no se cabla ningún múltiplo.** Lo que
  la corrida estaría diciendo no es *"aflojar a M*"* sino *"el stop ATR no aporta"*, que es una
  afirmación mucho más grande, mucho más dependiente del régimen y del survivorship de la muestra, y
  merece **su propia tarea con su propio pre-registro**. Se documenta como hallazgo y se abre.
- **C7 falla (el múltiplo baila entre folds)** → **NO-SHIP**, y el lead de la 26b §3 queda formalmente
  cerrado como **ruido**. Es un resultado publicable.
- **El walk-forward elige `2.0`** (el vivo) por mayoría → **NO-SHIP**, y es un resultado **positivo**:
  el múltiplo vivo está bien puesto y el lead era in-sample.
- **El walk-forward elige un múltiplo más AJUSTADO que 2.0** → se lo evalúa con **los mismos ocho
  criterios, sin descuento**. El eje es simétrico. (Ojo: es la dirección que la T26 quiso cablear y su
  hallazgo resultó artefacto del fill; eso no lo penaliza de antemano, pero tampoco lo favorece.)
- **Falla cualquier sanity del §7** → **corrida INVÁLIDA**, sin veredicto, como la T26. No se
  re-especifica nada para salvarla.

## 9. Qué se cabla si pasa / qué NO se toca

- **Si pasa las ocho:** `atr_stop_mult = M*` en `~/.finanzias/settings.json` (cuenta viva **2**,
  "Sim Segundo"). **Es un cambio de política de salida en vivo** y se avisa explícitamente en el cierre.
- **Consecuencia acoplada, declarada:** el mismo valor gobierna el **trailing** (`gates.py:103`), así
  que aflojar el stop afloja también el trailing del remanente ganador. Es lo que el brazo mide, así
  que el número es fiel — pero hay que decirlo, porque el nombre del flag no lo sugiere.
- **Consecuencia de display, declarada:** el R:R implícito que se muestra en cada BUY
  (`gates.entry_risk_levels`, = `tp_mult/stop_mult`) baja de **2.0** a `4.0/M*`. Es **display-only**
  (no filtra ni bloquea nada, regla 3), pero cambia un número que Chapa lee en la UI.
- **NO se toca:** `atr_tp_mult` (queda en 4.0 — es la T23, cerrada); el desacople trailing/stop (T7
  NO-SHIP; acá es sólo diagnóstico); `paper_atr_confirm_at_close` (la 26b lo dejó NO-SHIP y el engine
  sigue decidiendo contra el precio corriente); los gates 5/5b vivos (se **modelan** en el harness, no
  se cambian); las entradas; el sizing; el overlay T20.

## 10. Qué NO se modela (caveats antes de correr)

- **El sampleo de ~15 min del engine no se modela** — se lo **acota** entre `close` y `touch`, y por
  eso C8(b) es criterio y no comentario. Ningún brazo **es** producción.
- **Survivorship** del universo y **`auto_adjust=True`**: sesgan el nivel, no la comparación
  arm-vs-arm (las entradas son las mismas en todos los brazos). Con el brazo `off` en la rejilla el
  survivorship pesa más de lo habitual — un universo de sobrevivientes es el ambiente **más benévolo
  posible** para no tener stop. C6 existe en parte por esto.
- **Ventana de `analyze()`**: `data/pit_signals/` se generó con ventana expandida y el engine le pasa
  504 barras fijas. Desvío #3 de la T27, ya declarado, ortogonal a este eje.
- **Sin overlay T20** (escalado de exposición por régimen, **activo en la cuenta viva**) y sin
  earnings-blackout. Ortogonales al eje; el T20 escala tamaño, no niveles de salida.
- **Gate 6 (earnings blackout)** no se modela: los SELL forzados por ATR **lo bypassean** en vivo
  (`engine.py`, `_is_atr_forced_exit`), así que no toca este eje.

## 11. Plan de ejecución

1. **Enabler `live_gates`** en `analysis/portfolio_sim.simulate_portfolio` (default **`False`** ⇒ cero
   cambio para T7/R2/T9/T10-T20/T11b/T12/T23/T13/T21/T26/T26b): Gate 5 (7 d, umbral 0,0%) + Gate 5b
   (10 d, 3 ciclos), con las constantes espejando `settings.json`. El historial de ciclos cerrados se
   alimenta desde `_release_until` — **sólo** ciclos cuya salida ya ocurrió, así no hay look-ahead. El
   candidato bloqueado hace `continue` y **el slot se le ofrece al siguiente**, igual que en vivo.
   Contadores nuevos: `n_gate5_blocked`, `n_gate5b_blocked`.
2. **Runner** `scripts/run_stop_loosen_t34.py`: rejilla 7×2 con gates ON (+ la misma con gates OFF,
   descriptiva), los dos brazos de sanity, el diagnóstico `D1_stop_only_M*`, el walk-forward del §6,
   el bootstrap pareado, el AND de los ocho criterios del §8 y el banner de `harness_config.announce()`.
3. **Tests offline:** Gate 5 bloquea exactamente cuando el último ciclo cerrado dentro de 7 d tuvo
   `ret < 0` y no antes; un ciclo que cierra **después** de la fecha del candidato no bloquea (§7.6);
   el slot liberado se le ofrece al siguiente candidato; `live_gates=False` reproduce byte-por-byte el
   comportamiento previo; los folds no solapan con su train (embargo); el helper del veredicto aplica
   el AND de los ocho y **cada** caso partido del §8.
4. **Correr** (10 slots + sensibilidad a 5), sin red, sin tocar `finanzias.db`.
5. **Veredicto** en `docs/stop_loosen_t34_<fecha>.md`, con la rejilla gates-ON vs gates-OFF al lado
   para cuantificar el sexto desvío.
6. **Derivada declarada (fuera de alcance):** si el §3 resulta valer mucho, **decidir aparte** si
   obliga a re-leer harness publicados. Desde la 34 no se re-lee ninguno.

**Congelado. Cualquier cambio a §4–§8 después de ver un resultado invalida el pre-registro.**
