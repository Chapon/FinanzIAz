# Sprint 4 / T05 — Cross-sectional ranking spec

**Status**: ❌ **KILLED 2026-06-04**. Run 2 (lookback=120) borderline +0.124 ΔSharpe debajo del
threshold +0.15. Run 3 (lookback=60) confirmó ruido (+0.103, P(Δ≤0)=36.4%). XGBoost stacking
no determinístico entre runs (kill_only baseline varió ±0.88 Sharpe en w3 entre Run 2 y Run 3).
Cerrado con disciplina del threshold congelado, código LIVE como dead-code (toggle off default).
Próximo Sprint 4: T06 alpha decay tracking.
**Build original**: spec congelado 2026-06-03. Build sobre kill_only baseline (HMM off, Stacking off).
**Owner**: Chapa / Claude
**Roadmap link**: `[[roadmap-sprint-validation]]` Sprint 4.

## Problema

El engine hoy puntúa cada ticker **en aislamiento**: `_default_strength(signal, ml_probability)` ∈ [0,1] no
mira lo que pasa con los otros tickers del universo. La consecuencia: dos `BUY`s con `ml_probability ≈ 0.6`
son indistinguibles, aunque uno tenga momentum 12-meses muy por encima del universo y el otro esté en el
percentil 30. El ranking absoluto es ciego al contexto relativo.

Cross-sectional ranking = "¿es de los top-K BUYs del día contra el universo?" — clásico de
Jegadeesh & Titman 1993 y survivors del decay literatura post-2010.

## Diseño

### 1. Métrica

**Momentum percentile sobre `lookback` días**. Para cada bar `t`:

1. Computar `return_lookback[i] = closes[i][t] / closes[i][t - lookback] - 1` para cada ticker `i` del
   universo evaluado en ese bar.
2. Convertir a percentile rank dentro del universo de ese bar: `cs_score[i] = rank(return_lookback[i]) / N`,
   con `N` = tickers válidos en el bar. Output ∈ [0,1].
3. NaN handling: tickers con menos de `lookback + 1` cierres válidos quedan fuera del ranking (no se pueden
   rankear) y reciben `cs_score = 0.5` (neutral).
4. Ties: usar `rank(method="average")` para distribuir empates de forma estable.

### 2. Combinación con strength absoluto

```
combined_score = (1 - w) * absolute_strength + w * cs_score
```

donde `w = cross_sectional_weight` ∈ [0,1]:
- `w = 0` → comportamiento legacy (solo absoluto).
- `w = 1` → ranking puro relativo (no usa `ml_probability`).
- `w = 0.5` (default propuesto) → blend equiponderado.

Mantener un dial en lugar de `replace` total deja la opción de degradar al baseline si el experimento falla
y permite tune-grid si T05 muestra alpha pero no en la magnitud máxima.

### 3. Settings (config/settings_manager.py)

| Key | Tipo | Default | Notas |
|---|---|---|---|
| `cross_sectional_enabled` | bool | **False** | Default OFF: shipping decisión depende del harness. |
| `cross_sectional_lookback` | int | 120 | Trading days. 120 ≈ 6 meses; sweet-spot Jegadeesh-Titman / Asness, robusto a ruido semanal. 60d se descartó por churn excesivo en el ranking. |
| `cross_sectional_weight` | float | 0.5 | Blend factor [0,1]. |

### 4. Sitios de inyección

Tres sitios todos rankean candidatos por `strength` y truncan a `free_slots`:

| File | Línea actual | Cambio |
|---|---|---|
| `paper_trading/strategies.py` (`generate_trades_analyze_single`) | 247 (`ranked.sort`) | Si `cross_sectional_enabled`, computar `cs_scores` sobre `watchlist`, recombinar `ranked` por `combined_score`. |
| `paper_trading/strategies.py` (`generate_trades_portfolio_engine`) | 407 (`candidates = sorted`) | Igual: computar sobre `universe`, modificar `key`. |
| `analysis/portfolio_backtest.py` (`portfolio_backtest`) | 622 (`candidates = sorted`) | Igual: computar sobre `tickers_ok`, modificar `key`. Esto es el path del harness. |

Toggle off → branch identical al actual, garantizando parity.

### 5. Módulo nuevo: `analysis/ranking.py`

API puro, testeable, sin DB ni settings:

```python
def momentum_percentile(
    closes_by_ticker: dict[str, pd.Series],
    lookback: int,
) -> dict[str, float]:
    """Compute cross-sectional momentum percentile per ticker.

    For each ticker with >=lookback+1 closes, compute return over lookback bars.
    Then rank these returns and return percentile in [0,1] for each ticker.
    Tickers with insufficient history get 0.5 (neutral).
    """

def combine_score(absolute: float, relative: float, weight: float) -> float:
    """Blend absolute strength with cross-sectional percentile."""
```

Tests cubren: empty input, all-NaN, single ticker (debe ser 0.5 — sin universo no hay ranking), ties,
lookback más grande que la serie, valor exacto en casos pequeños hand-computed.

### 6. Harness wiring

Agregar `cross_sectional_enabled` a `analysis/harness/runner.py:_HARNESS_TOGGLE_KEYS`. Esto asegura que los
ablations del harness respeten el toggle (mismo bug pattern que Sprint 1 tuvo que evitar).

`ExperimentConfig.as_settings_dict()` ya itera sobre los toggles; agregar el campo correspondiente en
`config.py`.

## Kill criteria (congelados upfront — Sprint 2 lesson)

Misma filosofía que `docs/sprint2_kill_criteria.md`: thresholds escritos ANTES del run.

**Setup del experimento**:
- Universe: `data/harness_universe_41_10y.txt` (41 tickers, 10y cache disponible).
- Walk-forward: 4 ventanas de 2.5y cada una sobre 10y data (mismo schema que switcher validation).
- Baseline: `kill_only` = HMM off, Stacking off, vol_overlay on, XGB on, **cross_sectional off**.
- Treatment: igual + `cross_sectional_enabled=True`, `weight=0.5`, `lookback=120`.
- **`max_positions = 5`** — CRÍTICO. Igual a Sim Principal production. Si max_positions ≥ universe
  size, la truncación del ranking nunca se ejerce y el toggle ON/OFF da Δ=0 (mismo bug que mató al
  correlation_gate en Sprint 2). Primer run 20260603_151616 corrió con max_positions=41 por default
  y arrojó Δ=0.000 en las 4 ventanas — resultado inválido. Script v2 (2026-06-03) fuerza
  `--max-positions 5` por default.

**Decisión** (mean OVERALL ΔSharpe = treatment - baseline sobre 4 ventanas):

| ΔSharpe overall | P(Δ≤0) bootstrap 5k | Decisión |
|---|---|---|
| ≥ +0.15 | < 15% | **SHIP** con `cross_sectional_enabled=True` |
| +0.05 to +0.15 | < 25% | Borderline → tune-grid `weight ∈ {0.3, 0.7}` y `lookback ∈ {20, 120}` antes de decidir |
| < +0.05 OR P(Δ≤0) ≥ 25% | — | **KILL** — feature off por default, doc el resultado |
| < 0 en ≥ 3/4 ventanas | — | **KILL firme** (anti-cherry-pick rule de Sprint 2) |

**Guardrails extra**:
- Si **turnover** sube > 50% relativo (cross-sectional puede generar churn por rerank), penalizar 0.05
  Sharpe del treatment antes de comparar — porque costs reales se subestiman en el backtester.
- Si **max DD** del treatment > baseline + 2pp, kill incluso si Sharpe gana — sprint 4 no debe regresar
  el risk profile.

## Lo que NO se incluye en T05

- **Sector RS**: requiere mapping sector → tickers que no existe en datos hoy. Si momentum percentile pasa,
  considerar en sprint 5.
- **Z-score vs watchlist**: equivalente formal a percentile rank si los retornos son aprox normales —
  redundante con momentum percentile.
- **Volatility scaling cross-sectional**: ya lo hace el T10 vol_overlay a nivel portfolio.
- **Cambiar la magnitud del trade** (Kelly cross-sectional): Kelly sigue bloqueado por T07, ortogonal a T05.

## Cierre

Si ship: settings.set("cross_sectional_enabled", True), update memory con resultado y nueva baseline.
Si kill: doc el experimento, considerar T06 (alpha decay tracking) como siguiente Sprint 4 item.
