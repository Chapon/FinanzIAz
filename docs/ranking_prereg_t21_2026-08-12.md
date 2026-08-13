# Pre-registro CONGELADO — Decisión sobre el ranking vivo (Tarea 21)

**Fecha:** 2026-08-12 · **Estado:** congelado ANTES de codear el harness (regla 2).
**Ref:** `docs/BACKLOG.md` tarea 21 · `docs/meta_labeling_t9_2026-07-21.md` (T9, la medición
original) · `docs/deep_analysis_2026-08-12.md` §2 (la re-medición sobre el universo vivo) ·
`docs/harness_cfg_t27_2026-08-12.md` (config) · `docs/ent1_t13_2026-08-12.md` (el gate anti-overfit).

Este documento fija población, brazos, **la métrica de riesgo** y la **regla de decisión con el caso
partido resuelto de antemano** ANTES de correr. Nada se re-decide después de ver resultados.

---

## 1. Contexto y objetivo

El engine rankea los candidatos BUY del día por `buy_score` y se queda con los mejores hasta llenar
los slots. **Verificado en código** (no asumido): `strategies.py:449` toma
`strength = _default_strength("BUY", res.ml_probability)`, y `_default_strength` devuelve
`ml_probability` clipeado a [0,1] → **la clave de ranking ES el score**, y es exactamente lo que
guardan los artefactos de `data/pit_signals/` (`precompute_pit_signals.py` persiste
`res.ml_probability`). La medición transfiere sin proxies.

**Cinco mediciones independientes dicen que ese score no tiene alpha de ranking:** T9 brazo B1
−2.17 pts de CAGR; T9 §13.7 corr −0.0259 (n=26.988); T9 AUC OOS 0.4980; T25 `val_acc` medio 0.5076
sobre los 134 tickers vivos; y la re-medición 2026-08-12 sobre el universo de la cuenta 2
(141.794 eventos) −2.90 pts anuales contra elegir al azar. **Ninguna es, por sí sola, concluyente
al 95%** — la de agosto tiene IC que cruza cero. Lo que las hace accionables es que convergen.

**Objetivo:** decidir, con una regla congelada, si se pasa el ranking a **no-predictivo** (opción
(b) del backlog) o se deja como está documentando el score como no-validado (opción (a)). La opción
(c) —esperar a que 11/12 traigan una fuente con alpha— ya no aplica: la 12 cerró NO-SHIP y el Brazo
A de la 11 está bloqueado hasta ~oct-nov 2026.

**Por qué la T9 no cerró esto y este pre-registro sí puede:** la regla de T9 se escribió sobre
**una sola métrica** (CAGR) asumiendo que las demás se moverían con ella. No se movieron: B1 rendía
menos CAGR pero con **6,1 pts menos de maxDD**. La regla no decía qué hacer con eso, así que no
decidió. Acá el **maxDD se declara al frente como criterio propio y el caso partido se resuelve
ex ante** (§4).

---

## 2. Población y config (CONGELADO)

- **Universo:** `data/harness_universe_live_acct2.txt` — **127 tickers**, la watchlist de la cuenta
  viva (T27). No los 41 históricos: el ratio de selección es la variable que hace que el ranking
  importe (6,4:1 vivo vs 4,8:1 en T9).
- **Entradas:** eventos `analyze() = BUY` point-in-time (`data/pit_signals/`).
- **Cartera:** `portfolio_sim` con **`max_positions=10`** (config viva, T27), `initial_capital=50.000`,
  `allow_reentry_while_open=False`, `CostModel()`, `cap_days=250` (lección T13 §2: el cap 20 no es
  fiel al engine, que no tiene tope de tenencia), `AtrParams()` default (stop 2.0 / TP 4.0 / trail),
  flip `analyze SELL` con Gate 2b. **Sin overlay de régimen T20** (atribución limpia; es ortogonal
  al orden de los candidatos).
- **Desvío declarado que queda vivo (T27):** los artefactos PIT usan ventana **expandida**
  (250 → ~2.514 barras) contra las **504 fijas** del engine. Aplica **igual a todos los brazos**, así
  que no puede favorecer a ninguno; afecta el nivel absoluto, no la comparación.

---

## 3. Brazos (CONGELADO)

Lo único que cambia entre brazos es el **orden** de los candidatos del mismo día (`rank_score` de
`portfolio_sim`). Entradas, salidas, costos y capital son idénticos.

**De decisión:**
- **`B1_score` — BASELINE, es lo que corre hoy.** `rank_score = buy_score` (descendente).
- **`B0_neutral` — CANDIDATO.** `rank_score = None` → orden alfabético dentro del día, o sea
  **ranking sin información**. Es la opción (b) del backlog.

**Diagnóstico (NO promovible a decisión sin pre-registro propio):**
- **`B2_no_volpen`.** `ml_signals.py:1147` resta `vol_penalty = market_context.risk_score * 0.08`.
  Verificado que `risk_score` se computa del **df del propio ticker** (`detect_market_regime`:
  GARCH/EWMA + régimen sobre sus barras), o sea que **varía entre tickers del mismo día y sí afecta
  el orden** — no es una constante diaria. Este brazo rankea por `raw_prob = score + 0.08·risk_score`
  (reconstruido con un precómputo PIT de `risk_score`). Responde una pregunta de diseño concreta:
  **¿alcanza el parche quirúrgico de una línea, o el problema es el score entero?**
- **`B0r_random` (10 semillas).** El alfabético es *una* realización de "sin información"; el azar
  da la distribución. Sirve para saber si `B0_neutral` está en el centro de esa nube o fue suerte.
  Se reporta como media ± rango, no como brazo de decisión.

**Sanity del instrumento (nunca shipeables, miran el futuro):**
- **`ORACULO`** — rankea por el retorno **realizado** del ciclo.
- **`ANTI_ORACULO`** — al revés.

---

## 4. Regla de decisión (CONGELADA) — con el caso partido resuelto ex ante

Candidato = `B0_neutral`. Baseline = `B1_score`. **Se shipea el ranking no-predictivo sólo si pasa
las cuatro:**

| # | Criterio | Umbral |
|---|---|---|
| C1 | ΔCAGR = CAGR(B0) − CAGR(B1) | ≥ **+0.50 pp** |
| C2 | **Riesgo — declarado al frente:** maxDD(B0) | ≤ maxDD(B1) **+ 3.00 pp** |
| C3 | Anti-overfit: block-bootstrap pareado sobre Δ(retorno diario), bloques 20d, 2000 resamples | **IC95% inferior > 0** |
| C4 | Sharpe(B0) | ≥ Sharpe(B1) − **0.05** |

**Justificación del umbral de riesgo (se declara ahora, no después):** T9 midió a 5 slots que el
ranking no-predictivo costaba **+6,1 pts de maxDD**. `+3.00 pp` = **se acepta como mucho la mitad de
ese deterioro**. Es el número que convierte "menos retorno pero menos riesgo" de un empate retórico
en una decisión.

**El caso partido, resuelto de antemano (esto es lo que le faltó a T9):**
- Si **C1 pasa y C2 falla** (B0 rinde más pero con un drawdown materialmente peor) → **NO-SHIP**, y
  la tarea 21 **cierra en la opción (a)**: el engine queda como está y el `buy_score` se documenta
  como **no-validado para ranking**. No es un juicio nuevo, es esta regla.
- Si **C2 pasa y C1 falla** → **NO-SHIP** (no hay razón para cambiar algo que no mejora el retorno).
- Si falla C3 → **NO-SHIP**: la convergencia de cinco mediciones justifica *testear*, no *shipear*
  sin que el efecto sobreviva su propio intervalo.

**Por qué C3 es bootstrap pareado y no PBO:** la T13 mostró que el PBO con pocos brazos colineales
es grueso, y la **T27 midió que además es inestable a la config** (0.889 → 0.317 en la T23 sin tocar
un solo brazo, sólo cambiando slots). DSR/PBO se calculan y se reportan como **descriptivos**.

---

## 5. Sanity checks (si fallan, la corrida es inválida — no hay veredicto)

1. **Contabilidad:** `|equity_curve[-1] − final_equity| / final_equity ≤ 1e-6` en todos los brazos.
2. **El instrumento ve rankings buenos:** `CAGR(ORACULO) ≥ CAGR(B1) + 5.00 pp`. Si el oráculo no
   despega, un resultado nulo entre B0 y B1 no significa nada (validó el harness en T9/T10/T11b/T12).
3. **Y ve rankings malos:** `CAGR(ANTI_ORACULO) ≤ CAGR(B1)`.
4. **El ranking muerde:** al menos el **10%** de los trades tomados difiere entre `B0` y `B1`. Si el
   orden casi no cambia quién entra, no hay nada que medir (pasaría si sobraran slots).

---

## 6. Qué se cablea si pasa / qué pasa si no

- **Si pasa:** flag nuevo `paper_ranking_mode` ∈ {`score` (actual), `neutral`}, con **default =
  `neutral`** (el valor validado), cableado en `strategies.generate_trades_analyze_single`. Toca
  decisiones vivas, así que se avisa explícitamente a Chapa en el cierre. El `buy_score` **sigue
  computándose y mostrándose** (display-only, regla 3): deja de *decidir*, no de existir.
- **Si no pasa:** se documenta NO-SHIP en `docs/ranking_t21_2026-08-12.md`, el engine queda intacto y
  la tarea 21 cierra en la opción **(a)** con el score anotado como no-validado para ranking — que es
  un cierre, no una postergación.
- **En los dos casos** el informe reporta `B2_no_volpen`: si el parche de una línea recupera el
  terreno, eso es una tarea nueva con pre-registro propio (no se shipea desde acá).

**Fuera de alcance (declarado):** rediseñar el score; el gate conformal de abstención; rankings
alternativos (vol, momentum) — los exploratorios del análisis profundo son diagnóstico, y la T9 ya
mostró que un ranking elegido post-hoc necesita oráculo y cartera antes de creerle.
