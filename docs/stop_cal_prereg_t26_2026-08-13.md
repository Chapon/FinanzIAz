# Pre-registro CONGELADO — Recalibrar el stop ATR (Tarea 26, STOP-CAL)

**Fecha:** 2026-08-13 · **Estado:** congelado ANTES de codear el harness (regla 2).
**Ref:** `docs/BACKLOG.md` tarea 26 · `docs/deep_analysis_2026-08-12.md` §3.1–3.2 (la evidencia viva) ·
`docs/atr_stop_recalib_2026-06-30.md` (el veredicto vigente, que se auto-declara sin poder) ·
`docs/tp_cal_prereg_t23_2026-08-11.md` (la hermana simétrica) ·
`docs/harness_cfg_t27_2026-08-12.md` (la config) · `docs/ent1_t13_2026-08-12.md` (el gate anti-overfit).

Este documento fija **población, brazos, la métrica de riesgo, los sanity del instrumento y la regla
de decisión con umbrales numéricos** ANTES de correr. Nada de acá se re-decide después de ver
resultados. Si el candidato no supera el umbral, se documenta NO-SHIP y `atr_stop_mult = 2.0` queda
intacto.

---

## 1. Contexto y objetivo

El engine cierra toda posición que caiga **`2.0 × ATR14`** por debajo del costo de entrada. Ese
número nunca se validó con un harness de cartera: viene de la config inicial y sobrevivió una sola
revisión (2026-06-30) que **no pudo decidir**.

**La evidencia viva que dispara la tarea** (cuenta 2, 53 días, 36 round-trips —
`docs/deep_analysis_2026-08-12.md` §3.1):

| familia | n | P/L | ret medio | post-salida |
|---|--:|--:|--:|---|
| `atr_tp` | 8 | +$2.978,52 | +9,39% | +2,15% @20d (n=7) |
| `analyze SELL` | 17 | +$226,91 | −0,19% | **−5,63% @20d** (n=15) |
| `atr_trail` | 2 | −$15,59 | −0,08% | +0,47% @10d |
| **`atr_stop`** | **9** | **−$2.138,30** | **−5,22%** | **+6,81% @20d (n=5)** |

Que el `atr_stop` tenga 0% de ganadoras es **tautológico** (un stop sólo dispara en pérdida) y no es
el argumento. El argumento es la última columna: **los nombres que el stop corta rebotan**, mientras
los que corta el `analyze SELL` siguen cayendo. Eso es la firma de un stop que corta ruido, no
drawdown sostenido.

**Por qué el veredicto vigente no cierra la pregunta** (`docs/atr_stop_recalib_2026-06-30.md`):
n=6 ciclos con **LRCX aportando el 63%** del efecto (el leave-one-out tumba las dos variantes
ganadoras), régimen de rebote abr–jun 2026 —*"los stops existen para el drawdown sostenido que esta
muestra no contiene"*—, cuenta 1, y contrafactual limitado a variantes **más laxas** porque
re-simular desde el entry no era posible con aquel harness. **`analysis/portfolio_sim.py` no
existía**: nació el 2026-07-20 con R2, tres semanas después.

**Objetivo:** medir sobre el simulador de cartera real, con la config de la cuenta viva, si mover
`atr_stop_mult` mejora el CAGR/Sharpe **sin comprarlo con drawdown ni romperse en los regímenes de
stress** — para decidir si se cambia el default o no.

**Qué NO es:** no toca las entradas, ni el sizing, ni el `atr_tp_mult` (la T23 lo dejó en 4.0 y no se
re-abre acá), ni el `analyze SELL`. Lo único que varía entre brazos de decisión es `stop_mult`.

---

## 2. El hallazgo de código que define los brazos (verificado, no asumido)

`paper_trading/gates.py:101-103` — el engine vivo usa **el mismo múltiplo para las dos barreras de
abajo**:

```python
stop_level  = avg_cost - stop_mult * atr_value
trail_level = hwm      - stop_mult * atr_value if trail_enabled else None
```

`atr_exit_decision()` **no recibe un múltiplo de trailing**: `engine.py:378` lee `atr_stop_mult` y ese
único valor gobierna el stop duro *y* la distancia del trailing. El `trail_mult` de
`analysis/exit_replay.py:92` es un knob **sólo de harness**, agregado por la T7 (que cerró NO-SHIP y
no se cableó); con `trail_mult=None` cae a `stop_mult`, que es exactamente el acoplamiento vivo.

**Consecuencia congelada:** los brazos de decisión dejan `trail_mult=None`, o sea que **mueven las dos
barreras a la vez** — porque eso es lo que haría cambiar el flag en producción. Testear un stop duro
aislado mediría algo que el engine no puede ejecutar. La atribución (¿cuánto pone el stop y cuánto el
trailing?) se responde con el brazo de diagnóstico D1 (§3), que **no es promovible a decisión**.

---

## 3. Población, config y brazos (CONGELADO)

### 3.1 Población

- **Universo:** `data/harness_universe_live_acct2.txt` — **127 tickers**, la watchlist de la cuenta
  viva (T27). No los 41 históricos.
- **Entradas:** eventos `analyze() = BUY` point-in-time (`data/pit_signals/`, `period=10y`,
  `warmup=250`). La población real del engine.
- **Cartera:** `portfolio_sim` con **`max_positions=10`** (config viva), `initial_capital=50.000`,
  `allow_reentry_while_open=False`, `CostModel()` (0.1% comisión + 0.05% slippage en las dos puntas),
  `cap_days=250` (lección T13 §2: el cap 20 no es fiel al engine, que no tiene tope de tenencia),
  `tp_mult=4.0` y `period=14` fijos, flip `analyze SELL` con Gate 2b, orden alfabético dentro del día
  (sin `rank_score` — la T21 cerró que el score no está validado para rankear).
- **Sin overlay de régimen T20** (atribución limpia; es ortogonal y el candidato lo heredaría en prod).
- **Sensibilidad obligatoria:** la corrida se repite a `--max-positions 5` y se **reporta**, para saber
  si el veredicto es dependiente de la config (lo que la T27 midió que pasa). El veredicto se dicta
  con **10 slots** (la cuenta viva); los 5 slots son descriptivos.

### 3.2 Brazos

Lo único que varía entre brazos de decisión es `AtrParams.stop_mult`.

**De decisión** (5 candidatos + baseline):

| brazo | `stop_mult` | rol |
|---|:--:|---|
| `S_1.5` | 1.5 | **más estricto** — posible sólo porque este harness re-simula desde el entry |
| **`S_2.0` (BASELINE)** | 2.0 | el valor vivo — la referencia |
| `S_2.5` | 2.5 | el que salió peor en la tabla de 2026-06-30, sin explicación |
| `S_3.0` | 3.0 | |
| `S_3.5` | 3.5 | |
| `S_off` | 1e9 | **sin barrera ATR de abajo** — ver la nota |

**Nota sobre `S_off` (declarada ahora):** por el acoplamiento de §2, un múltiplo enorme desactiva el
stop **y** el trailing (los dos niveles caen a ≤0 y el guard `> 0` los apaga). Eso es exactamente lo
que haría el flag en vivo, así que el brazo es fiel; su rol es **acotar la respuesta** (¿cuánta plata
pone en total la barrera de abajo?), no proponer operar sin protección. Si ganara, tiene que pasar
igual C2 (drawdown) y C5 (régimen), que es donde un brazo sin stop debería morir.

**Diagnóstico (NO promovible a decisión sin pre-registro propio):**
- **`D1_stop_only_3.0`** — `stop_mult=3.0` con `trail_mult=2.0` **pineado**: mueve sólo el stop duro y
  deja el trailing donde está hoy. Separa las dos patas del efecto. Se fija en 3.0 **ahora**, antes de
  saber quién gana, para que no sea una elección post-hoc.

**Sanity del instrumento (nunca shipeables — miran el futuro):**
- **`ORACULO_STOP`** — el stop duro dispara **sólo cuando la caída era real**: se permite el
  `atr_stop` únicamente si `close[i+20] < close[i]` (look-ahead de 20 ruedas, el mismo horizonte de la
  evidencia viva). Es el contrafactual exacto de la hipótesis: un stop que distingue ruido de caída.
- **`ANTI_ORACULO_STOP`** — al revés: el `atr_stop` dispara sólo si `close[i+20] ≥ close[i]`, o sea
  sólo cuando corta un rebote.

Los dos oráculos requieren un hook nuevo en `scaleout_replay.replay_cycle` (`stop_filter`, default
`None`), del mismo patrón que el `time_stop_days` que agregó la T13: con el default **no puede
cambiar ningún resultado de T7/T23/T13/T21**.

---

## 4. Métricas (CONGELADO)

Sobre la curva de equity de `portfolio_sim` (lección de la lápida R2/T8 — umbrales en métricas **de
cartera**, no en puntos acumulados por trade):

- **CAGR**, **Sharpe anualizado**, **maxDD de cartera**.
- **p5 de trade** (cola de pérdidas por posición) — descriptivo acá, no criterio: aflojar el stop
  **tiene** que empeorar el p5 por construcción, así que usarlo de gate sería tautológico. La cola que
  importa en esta tarea es la de **cartera**, y esa es el maxDD (C2).
- **Retorno medio por trade por régimen** (`bull_normal` + 2018Q4 + COVID-2020 + bear-2022).
- **Mezcla de salidas** por brazo (`atr_stop` / `atr_trail` / `atr_tp` / `signal_*` / `cap`).
- Descriptivos: win rate, payoff, hold medio, nº tomadas, exposición, DSR/PBO.

---

## 5. Sanity del instrumento (si falla alguno, la corrida es INVÁLIDA — no hay veredicto)

1. **Contabilidad:** `|equity_curve[-1] − final_equity| / final_equity ≤ 1e-6` en todos los brazos.
2. **Monotonía mecánica:** el `%` de salidas por `atr_stop` es **estrictamente decreciente** en
   `stop_mult` a lo largo de `S_1.5 → S_2.0 → S_2.5 → S_3.0 → S_3.5`, y **=0** en `S_off`. Es una
   invariante de mecánica pura (un stop más lejos dispara menos), no una hipótesis sobre retornos: si
   falla, el harness está mal cableado.
3. **El stop tiene población:** en el baseline, **≥5%** de las salidas son `atr_stop`. Es la lección
   del brazo (b) de la T13 —*NO-SHIP por sin población, no por ineficacia*—: si el stop casi no
   dispara en el harness, no hay nada que recalibrar y hay que decirlo así.
4. **Los brazos muerden:** **≥10%** de los trades difieren (par `ticker`+`entry_date`) entre el
   baseline y el candidato. Si el cambio de múltiplo casi no cambia quién entra ni cuándo sale, no hay
   efecto que medir.
5. **El instrumento ve stops buenos:** `CAGR(ORACULO_STOP) ≥ CAGR(S_2.0) + 5.00 pp`. Si un stop con
   presciencia perfecta no despega, un resultado nulo entre brazos no significa nada (el oráculo
   validó el harness en T9/T10/T11b/T12/T21).
6. **Y ve stops malos:** `CAGR(ANTI_ORACULO_STOP) ≤ CAGR(S_2.0)`.

---

## 6. Regla de decisión (CONGELADA)

**Candidato** = el brazo con **mejor Sharpe anualizado** entre los 5 candidatos
{`S_1.5`, `S_2.5`, `S_3.0`, `S_3.5`, `S_off`}. **Baseline** = `S_2.0`. Se **cambia el default sólo si
pasa las seis**:

| # | Criterio | Umbral |
|---|---|---|
| C1 | ΔCAGR = CAGR(cand) − CAGR(base) | ≥ **+0.50 pp** |
| C2 | **Riesgo — declarado al frente:** maxDD(cand) | ≤ maxDD(base) **+ 2.00 pp** |
| C3 | Anti-overfit: block-bootstrap pareado sobre Δ(retorno diario de equity), bloques 20d, 2000 resamples, `seed=12345` | **IC95% inferior > 0** |
| C4 | Sharpe(cand) | ≥ Sharpe(base) − **0.05** |
| C5 | **Robustez de régimen (prueba central):** Δ(ret medio por trade) en **cada uno** de los 4 regímenes | ≥ **−0.05 pts** |
| C6 | **Coherencia dosis-respuesta:** el brazo **adyacente** al candidato en el orden de múltiplos (al menos uno de los dos vecinos) | ΔCAGR ≥ **0** |

**Justificación de los umbrales (se declara ahora, no después):**

- **C1 = +0.50 pp** (y no el +0.30 de la T23): el stop es una barrera que dispara mucho más seguido
  que el TP y toca el downside, así que el cambio tiene que pagar más que un refinamiento
  "DD-neutral". Es además el orden de magnitud de lo que está en juego (−$2.138 en 53 días de una
  cuenta de ~$50k).
- **C2 = +2.00 pp de maxDD.** Éste es **el** criterio de esta tarea: aflojar un stop compra retorno
  con riesgo, y el número que separa "mejora" de "apalancamiento disfrazado" hay que fijarlo antes de
  verlo. El baseline mide ~39% de maxDD a 10 slots (T27), así que +2.00 pp es aceptar ~5% relativo de
  deterioro. Es el defecto que dejó abierta la T21 durante ocho meses (T9 no había declarado el
  maxDD y quedó un empate retórico) y no se repite.
- **C5 es la prueba central, no un accesorio.** El stop es un **guardrail de riesgo**: si aflojarlo
  sólo funciona en bull, es exactamente el error que mató a T11b (momentum roto en bear) y a T12
  (insider roto en bull). Un stop que se rompe en 2018Q4 / COVID / bear-2022 no shipea aunque el CAGR
  de 10 años sea mejor.
- **C6 es nuevo y existe por la T21.** Con 5 candidatos sobre un eje monótono, el ganador puede ser un
  pico de ruido —que es literalmente cómo el alfabético "ganó" en la T21 (+3.10 pp sobre la mediana de
  las semillas aleatorias, por suerte)—. Exigir que un vecino acompañe convierte "el mejor de 5" en
  "una región del parámetro que funciona". Es más informativo que un Bonferroni sobre brazos
  colineales.
- **Por qué C3 es bootstrap pareado y no PBO:** la T13 mostró que el PBO con pocos brazos colineales
  es grueso y la T27 midió que **además es inestable a la config** (0.889 → 0.317 en la T23 sin tocar
  un brazo). DSR/PBO se computan y se reportan como **descriptivos**, no como gate.

**El caso partido, resuelto de antemano:**
- Si **C1 pasa y C2 falla** (más CAGR comprado con drawdown) → **NO-SHIP**. El stop es un guardrail:
  su recalibración no puede justificarse subiendo el riesgo de cartera.
- Si **C2 pasa y C1 falla** → **NO-SHIP** (no se cambia un default que no mejora el retorno).
- Si el candidato es **`S_1.5`** (o sea, el stop óptimo es *más estricto*) y pasa las seis → **SHIP
  igual**, y el informe tiene que decir explícitamente que **la evidencia viva apuntaba al revés** y
  que la muestra de 53 días leyó mal el problema.
- Si **falla el §5.3** (el stop no tiene población en el harness) → **NO-SHIP por sin población**, con
  el mismo lenguaje que la T13(b): no es que el stop sea inocuo, es que este harness no lo ejercita y
  la pregunta queda sin responder por otra vía.

---

## 7. Qué se cablea si pasa / qué pasa si no

- **Si pasa:** es una **recalibración, no una feature** — se cambia el default de `atr_stop_mult` al
  valor validado (SCHEMA de settings + `docs/SETTINGS_REFERENCE.md`, que hoy lo documenta como
  *"(ver código)"*) + tests. Toca la política de salida viva, así que **no** cae bajo la regla 3
  (display antes que sizing): es un parámetro de salida existente validado por harness. Se avisa
  explícitamente a Chapa en el cierre, con la nota de que el flag mueve **stop y trailing juntos**.
- **Si no pasa:** NO-SHIP documentado en `docs/stop_cal_t26_2026-08-13.md`, `atr_stop_mult=2.0` queda
  como está, y el harness queda como enabler (`scripts/run_stop_cal_replay_t26.py`).
- **En los dos casos** el informe reporta `D1_stop_only_3.0`: si el efecto vive en una sola de las dos
  patas, eso es una tarea nueva (desacoplar el trailing del stop en el engine) con pre-registro
  propio — **no se shipea desde acá**.

---

## 8. Qué NO se modela (caveats declarados antes de correr)

- **Ventana de `analyze()`:** los artefactos PIT usan ventana **expandida** (250 → ~2.514 barras)
  contra las **504 fijas** del engine vivo (T27 §"sigue vivo"). Aplica **igual a todos los brazos**:
  afecta el nivel absoluto, no la comparación arm-vs-arm.
- **Survivorship** (universo de tickers vivos) y **`auto_adjust=True`**: sesgan el nivel de CAGR, no el
  ranking entre brazos — las entradas son idénticas en todos.
- **Sin intradía:** stop/trail/TP se evalúan al close con fills gap/touch modelados
  (`_exit_fill_price`, espejo de `gates.model_exit_fill_price`). Un stop **más estricto** es el que más
  sufre esta limitación (más gatillos intradía no vistos) → si `S_1.5` gana, el resultado es
  conservador; si pierde, parte de la pérdida puede ser artefacto y hay que decirlo.
- **Sin overlay T20** ni earnings-blackout: ortogonales, el candidato los heredaría en prod.
- **Sin baseline aleatorio Monte Carlo:** como en T23, la pregunta es arm-vs-arm sobre las mismas
  entradas, no "¿esta fuente de señal le gana al azar?".

---

## 9. Plan de ejecución

1. **Enabler:** hook `stop_filter` en `scaleout_replay.replay_cycle` (default `None` ⇒ sin cambio de
   comportamiento) + tests que lo prueban.
2. **Harness** `scripts/run_stop_cal_replay_t26.py` (fork de `run_tp_cal_replay_t23.py`): carga barras
   + señal PIT de los 127, arma las entradas `analyze BUY`, corre `simulate_portfolio` por brazo,
   computa §4, aplica §5 y §6, imprime el banner de `harness_config.announce()`.
3. **Tests offline** (`tests/test_stop_cal_replay_t26.py`): monotonía mecánica del `%atr_stop` en un
   caso sintético; el `stop_filter` sólo suprime el `atr_stop` (no toca trail/TP); `S_off` no emite
   ninguna salida ATR de abajo; el helper de veredicto aplica bien el AND de los 6 criterios y el caso
   partido; determinismo.
4. **Correr** sobre el cache Parquet + PIT existentes (sin red, sin tocar `finanzias.db`), a 10 slots y
   a 5 de sensibilidad.
5. **Veredicto** en `docs/stop_cal_t26_2026-08-13.md`.
6. Si SHIP: cambiar el default + tests + suite Windows verde. Si NO-SHIP: documentar y cerrar.

**Congelado. Cualquier cambio a §3–§6 después de ver un resultado invalida el pre-registro.**
