# Pre-registro CONGELADO — Recalibrar el take-profit ATR (Tarea 23, TP-CAL)

**Fecha:** 2026-08-11 · **Estado:** congelado ANTES de codear el harness serio (regla 2).
**Ref:** `docs/BACKLOG.md` tarea 23 · análisis exploratorio `docs/tp_mult_analysis_2026-07-22.md`
(+ `scripts/tp_mult_sweep_2026-07-22.py`) · gap A4 · lección de especificación de la lápida R2/T8.

Este documento fija la **hipótesis, la población, los brazos, la mecánica de salida y los
kill-criteria (con umbrales numéricos) ANTES de correr el harness de cartera**. El barrido del
2026-07-22 fue exploratorio (entradas neutras, capital ilimitado, salidas ATR-only) — sirvió para
**decidir testear en serio**, no para cablear. Nada de acá se re-decide después de ver resultados.
Si el candidato no supera el umbral, se documenta NO-SHIP y el `atr_tp_mult=4.0` queda como está.

---

## 1. Contexto y objetivo

El take-profit está fijo en **`atr_tp_mult = 4.0`** (R:R 2:1 contra el stop 2.0): toda posición
ganadora se cierra en +2R. El TP **solo toca el upside** — el hard-stop y el trailing gobiernan el
downside — así que truncar la cola derecha de los ganadores **no compra ninguna reducción de riesgo**.
La estrategia `analyze_single` es momentum-ish de **skew positivo medido** (T7: el 69% de la ganancia
bruta vino de 4 runners de 12–27 días); un TP fijo en 2R está peleado con ese edge (corta justo a los
pocos que pagan). El barrido exploratorio dio una mejora **monótona, DD-neutral y régimen-consistente**
al subir el múltiplo (4.0→6.0 = +0.165 pts/trade [IC95% +0.10,+0.23]; p5 y maxDD idénticos).

**Objetivo:** medir sobre el **simulador de cartera real** (`portfolio_sim`, capital finito,
`max_positions=5`, entradas del engine real) si **subir el TP a 6.0 o quitarlo** mejora el CAGR/Sharpe
de cartera **sin empeorar el maxDD ni la cola de pérdidas y sin depender de un solo régimen** — para
decidir si se cabla (detrás de flag, default = valor validado) o no.

**Qué NO es:** no toca el trailing (eje downside, que T7 dio NO-SHIP); no toca las entradas ni el
sizing; no re-abre el barrido de forma del stop. Lo único que varía entre brazos es `tp_mult`.

---

## 2. Población / entradas (CONGELADO)

- **Universo:** `data/harness_universe_41_10y.txt` (41 tickers, 10y EOD en Parquet) — el mismo de T7/E4,
  para continuidad con la población validada.
- **Entradas:** los **eventos `analyze() = BUY`** point-in-time (`data/pit_signals/`, señal `analyze()`
  completa con XGBoost, `overall_signal == "BUY"`). Es la **población real del engine** (a diferencia
  del barrido exploratorio, que usó entradas neutras cada 20 barras). Determinista.
- **Exit con flip de señal:** la triple barrera completa del engine — ATR stop/TP/trail **+ flip
  `analyze SELL`** (Gate 2b vigente), idéntica en todos los brazos. El flip usa la misma señal PIT.
- **Cartera:** `portfolio_sim` con `max_positions=5`, `initial_capital=50.000`,
  `allow_reentry_while_open=False` (engine-faithful), `cap_days=20`, `CostModel()` (comisión 0.1% +
  slippage 0.05% en las dos puntas). Sin `rank_score` (orden alfabético dentro del día, como el baseline
  de R2). Sin overlay de régimen T20 (atribución limpia; en prod el candidato lo heredaría, ortogonal).

---

## 3. Brazos (CONGELADO)

Lo único que varía es `AtrParams.tp_mult`. Todo lo demás fijo: `stop_mult=2.0`, trailing default
(`trail_mult=None` ⇒ cae a 2.0, `trail_min_excess_atrs=1.0`), `period=14`, `cap_days=20`.

| brazo | `tp_mult` | rol |
|---|:--:|---|
| **TP_4.0 (BASELINE)** | 4.0 | el valor vivo actual — la referencia contra la que se mide |
| TP_6.0 (candidato) | 6.0 | el múltiplo que el exploratorio señaló |
| TP_off (candidato) | 1e9 (sin-TP) | quitar el TP, dejar mandar stop+trail+cap |
| _TP_2.0 (SANITY, no candidato)_ | 2.0 | **debe** rendir claramente peor que 4.0 → confirma que el harness detecta el efecto del TP (análogo al oráculo de T9/T11b). Si 2.0 ≥ 4.0, el harness es sospechoso y el veredicto se anula. |

- **Brazo de decisión:** el **mejor por Sharpe anualizado** entre los dos candidatos {TP_6.0, TP_off}.
- **DSR/PBO:** sobre los **3 brazos de decisión** {TP_4.0, TP_6.0, TP_off} como intentos (el sanity
  TP_2.0 queda fuera del conteo de intentos, igual que el oráculo).

---

## 4. Métricas (CONGELADO)

Sobre la curva de equity de `portfolio_sim` (corrige el defecto de la lápida R2/T8 — umbrales en
CAGR/Sharpe **de cartera**, NO en puntos acumulados por trade):

- **CAGR**, **Sharpe anualizado** y **maxDD de cartera** (`risk_sizing.cagr` / `sharpe_annual`).
- **p5 de trade** (percentil 5 del retorno por trade) — la cola de pérdidas por posición, la métrica
  que el exploratorio mostró invariante (−7.28%). "No empeorar el p5" del backlog.
- **Retorno medio por trade por régimen** (`bull_normal` + 2018Q4 + COVID-2020 + bear-2022) — para el
  gate de robustez de régimen (§5.5).
- Descriptivos (no deciden): win rate, payoff, hold medio, mezcla de salidas, %salida-por-TP, nº tomadas.

**Invariantes que se chequean ANTES de leer el veredicto** (si fallan, el run se descarta): integridad
contable (la curva de equity termina en la equity final), invariante de exits, y el **sanity TP_2.0**
rinde claramente por debajo de TP_4.0.

---

## 5. Kill-criteria (CONGELADOS)

Sea `cand` el brazo de decisión (mejor Sharpe entre {TP_6.0, TP_off}) y `base` = TP_4.0. Se **shipea si
y solo si se cumplen TODOS**:

1. **Significancia económica (CAGR):** `ΔCAGR = CAGR(cand) − CAGR(base) ≥ +0.30 pp`. Umbral modesto a
   propósito (es un refinamiento DD-neutral, "dinero gratis", no una fuente de alpha nueva como T11b/+2pp),
   pero positivo y no trivial para no cablear ruido.
2. **No-inferioridad en Sharpe:** `Sharpe(cand) ≥ Sharpe(base) − 0.02`. La mejora de CAGR no puede venir
   a costa del Sharpe.
3. **DD-neutral (la tesis entera):** `maxDD(cand) ≤ maxDD(base) + 0.5 pp`. Si aflojar el TP empeora el
   drawdown de cartera, se cae — contradiría el fundamento ("el TP no toca el downside").
4. **Cola de pérdidas no peor:** `p5_trade(cand) ≥ p5_trade(base) − 0.5 pp`.
5. **Robustez de régimen (lección R2 — la que hundió al trailing sweep de T7):** en cada uno de los 4
   regímenes, `Δ(ret medio por trade) = cand − base ≥ −0.05 pts`. O sea: subir/quitar el TP **no
   empeora meaningfully ningún régimen**. (No se exige que cada régimen sea positivo —el 2018Q4 puede ser
   negativo en los dos brazos—; se exige que el **cambio** no dañe un régimen.)
6. **Anti-overfitting:** `DSR > 0.5` **y** `PBO < 0.5` (`walkforward_power.deflated_sharpe_ratio` /
   `pbo_cscv` sobre la matriz de retornos diarios de equity alineados de los 3 brazos de decisión).

Si `cand` falla **cualquiera** → **NO-SHIP**, se documenta y el `atr_tp_mult=4.0` queda intacto.

**Si PASA:** se cabla detrás de un flag propio con **default = el valor validado de `cand`**
(`tp_mult` 6.0 o sin-TP). Como es un cambio de la **política de salida viva** (no display-only), no cae
bajo la regla 3 de "display antes que sizing" —es una recalibración de un parámetro de salida existente,
validada por harness—; entra directo detrás del flag con el default validado. Hereda en prod todo lo
demás (Gate 2b, earnings-blackout, escalado por régimen T20).

---

## 6. Qué NO se modela (caveats declarados antes de correr)

- **Survivorship** (41 tickers vivos) y **`auto_adjust=True`** (lookahead transversal): sesgan el
  **nivel** absoluto de CAGR, no el **ranking** entre brazos (aplican igual a los cuatro). Como la
  comparación es arm-vs-arm sobre las **mismas** entradas, el sesgo se cancela en el ΔCAGR.
- **Sin intradía:** stops/TP al close con fills gap/touch modelados (misma limitación estructural que A1).
- **Overlay de régimen T20** (activo en prod): el harness mide sin el ×0.5 risk-off para atribución
  limpia; el candidato lo heredaría en prod (ortogonal, ya shipeado).
- **Sin baseline aleatorio:** a diferencia de T11b/T12 (fuentes de señal nuevas vs azar), acá la pregunta
  es arm-vs-arm (¿6.0/sin-TP le gana a 4.0?), así que la significancia sale del ΔCAGR + DSR/PBO sobre las
  mismas entradas, no de un Monte Carlo.

---

## 7. Plan de ejecución

1. **Harness** `scripts/run_tp_cal_replay_t23.py` — carga barras + señal PIT de los 41, arma las
   entradas `analyze BUY`, corre `simulate_portfolio` por brazo variando `AtrParams(tp_mult=…)`, computa
   CAGR/Sharpe/maxDD/p5/régimen, DSR/PBO sobre los 3 brazos de decisión, aplica §5. Sin red, sin tocar
   `finanzias.db`.
2. **Tests offline** (`tests/test_tp_cal_replay_t23.py`): entradas BUY bien extraídas de la señal;
   `tp_mult` mayor ⇒ ≥ %salida-por-TP menor y ret ≥ (monotonía en un caso sintético); sanity 2.0 < 4.0;
   determinismo; el helper de veredicto aplica bien el AND de los 6 criterios.
3. **Correr** sobre el cache Parquet + PIT ya existentes (sin bajar dato).
4. **Veredicto** en `docs/tp_cal_t23_2026-08-11.md` (ship/no-ship + por qué).
5. Si SHIP: cablear el flag `paper_atr_tp_mult` (default = valor validado) en el engine + tests + suite
   Windows verde. Si NO-SHIP: documentar y dejar el harness como enabler.

**Congelado. Cualquier cambio a §2–§5 después de ver un resultado invalida el pre-registro.**
