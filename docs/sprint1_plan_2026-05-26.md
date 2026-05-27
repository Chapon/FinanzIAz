# Sprint 1 — Plan de implementación (v2, scope-ajustado)

**Estado**: cerrado, listo para ejecutar. Fecha: 2026-05-26.
**Dependencia**: Sprint 0 cerrado (✅), data audit (✅), baseline frozen (✅).
**Bloquea**: Sprint 2 (attribution + calibration).
**Estimación total**: **5-6 días reales** (½ dashboard + ½ refactor gates + 3 harness + 1-2 debug fidelity). Walk-forward **fuera** de Sprint 1.

**v2.1 (post-crítica)**: tres ajustes contra el plan inicial — (1) criterio de validación realista (fidelity 31d + structural 2y), (2) gate logic extraída a módulo compartido en vez de wrappers paralelos, (3) estimación bumpeada de 4 → 5-6 días para reflejar el debug realista.

---

## Hallazgos del audit pre-plan (30 min)

### A. `analysis/portfolio_backtest.py` no tiene NINGUNA T-feature integrada

`grep` directo sobre el backtester: **0 matches** para atr_stop, atr_trail, earnings_blackout, correlation, vol_target_portfolio, stacking, hmm, xgb. Lo único que el backtester sabe es:

- Allocation modes: EQUAL_WEIGHT, SIGNAL_WEIGHTED, INVERSE_VOL, FIXED_AMOUNT, VOL_TARGET (T06 per-name), KELLY_FRACTIONAL (T06).
- Rebalance triggers: signal change, drift, monthly.
- Strategy injection vía `signal_fn: Callable[[pd.DataFrame], str]` que retorna "BUY"/"HOLD"/"SELL".

Todas las demás T-features (T01 ATR stops, T08 earnings blackout, T09 correlation gate, T10 vol portfolio overlay) viven SOLO en `paper_trading/engine.py:_compute_atr_forced_exits` y dentro de `run_paper_scan`.

**Consecuencia**: portear el motor de gates al backtester es refactor pesado (3-5 días extra). La alternativa pragmática **NO es wrappers paralelos** — eso lleva a divergencia entre motor y harness en 3 meses. La alternativa es **extract-to-shared-module**.

### B. Approach: extract gates a módulo compartido

Refactor chico de ~½ día:

1. Crear `paper_trading/gates.py` con funciones puras:
   - `is_near_earnings(ticker, date, days_window) -> bool`
   - `check_correlation_gate(ticker, candidate_book, max_avg_corr) -> bool`
   - `should_force_atr_exit(position, df_slice, mult, period) -> tuple[bool, str]`
   - `vol_overlay_scale(book_vol, target_vol) -> float`
2. Refactorear `paper_trading/engine.py` para llamar a esas funciones (en vez de tener la lógica inline). Tests existentes del motor deben seguir pasando — esto es regression-safe por construcción si el extract es puro.
3. `analysis/harness/gates.py` llama exactamente a las mismas funciones. Cero duplicación.
4. Para T01 (ATR stops) — agregar al backtester un parámetro opcional `forced_exit_fn: Callable[[ticker, df_slice, position_state], (bool, str)]` que se evalúa en cada step. ~20 líneas en `portfolio_backtest.py`.

**Costo total**: ~½ día refactor + ½ día tests + ½ día wiring en backtester. Beneficio: **una sola fuente de verdad** para gate logic, drift entre motor y harness imposible por construcción.

### C. Fees y slippage exactos del motor live

Verificado en `finanzias.db` con 10 fills reales de Sim Principal:

- **Slippage**: exactamente **0.05% (5 bps)** uniforme. Coincide con `paper_accounts.slippage = 0.0005`.
- **Commission**: **NO** es una % flat. Usa IBKR Pro tiered model (`paper_trading._broker_costs.get_active_commission_model()`). Varía: 0.004% en trades grandes ($25k), 0.32% en trades chicos ($100). Min ~$0.35/trade + ~$0.0035/share.

**Implicación para el harness**: NO usar el `commission=0.001` del backtester como rate flat. En su lugar, importar `get_active_commission_model()` y pasarlo como callable al backtester. Eso requiere también un cambio menor en `portfolio_backtest.py` para aceptar commission como callable, no solo float.

**Alternativa simple**: para Sprint 1, usar commission flat 0.10% (matches `acct.commission`) y slippage 0.05%. Sí va a haber drift entre harness y baseline en trades chicos, pero el patrón promedio se mantiene. Refinement en Sprint 2 si la primera corrida no matchea.

**Decisión cerrada**: Sprint 1 usa commission flat 0.10% + slippage 0.05%. Si el harness baseline-run no matchea ± 1% del baseline frozen, refinement a callable en Sprint 2.

---

## Decisiones cerradas (D1-D5)

- **D1 universo**: ✅ mismos 52 tickers de Sim Principal + disclaimer survivorship.
- **D2 período**: ✅ default 2y, parametrizable. 1y para iteración local.
- **D3 fees/slippage**: ✅ commission 0.10% flat + slippage 5 bps. Revisión condicional en Sprint 2.
- **D4 auto_adjust**: ✅ aceptar + disclaimer (consistente con el audit).
- **D5 dashboard refresh**: ✅ on-load + reload button.

---

## Piezas en orden de ejecución

### Pieza 0 — Dashboard vivo (½ DÍA, primero, paralelo)

**Por qué primero**: empieza a capturar telemetría desde ya. Mientras el harness se codea, el dashboard acumula datos que sirven al Sprint 2.

**Qué es**: artifact HTML vía `mcp__cowork__create_artifact` que lee `finanzias.db` y muestra para Sim Principal:

1. Equity curve desde `paper_equity_snapshots` (Chart.js line).
2. Trade tape: last 50 fills con ticker, side, signal_score, P&L si cerrado.
3. Histogram de `paper_orders.signal_score` (BUYs vs SELLs).
4. KPIs: win rate, profit factor, expectancy, holding promedio — usa logica de `scripts/baseline_metrics.py`.
5. Status counts: approved / filled / expired + top-10 notas de expired.
6. Posiciones abiertas con MTM actual.

**Out of scope dashboard**:
- Gate-skip telemetría (no persistida hoy, requiere `paper_scan_log` que es Sprint 2).
- Comparación contra baseline (Sprint 2).

**Entregable**: artifact HTML con Reload button. Lee DB directo vía `window.cowork.callMcpTool` o equivalent.

**Test**: verificación manual + cross-check con `python scripts/baseline_metrics.py` (mismos win rate, PF, expectancy).

---

### Pieza 1 — T-harness mínimo (3 DÍAS, core)

**Estructura**:

```
scripts/harness.py                       # CLI entry
analysis/harness/
    __init__.py
    config.py                            # ExperimentConfig dataclass + JSON load
    gates.py                             # gate wrappers (earnings, correlation, vol)
    forced_exits.py                      # ATR stop/trail forced_exit_fn
    runner.py                            # orchestrates portfolio_backtest + gates
    metrics.py                           # 8-metric calculation post-run
experiments/
    baseline_sim_principal.json          # primer experiment, debe matchear baseline
data/harness_runs/
    {ts}_{name}.json                     # full result per run
    index.csv                            # one row per run for diff
tests/test_harness.py                    # ~20 tests
```

**ExperimentConfig**:

```json
{
  "name": "baseline_sim_principal",
  "universe": "sim_principal_watchlist",
  "period": "2y",
  "allocation_mode": "signal_weighted",
  "max_positions": 8,
  "initial_capital": 100000,
  "commission": 0.001,
  "slippage": 0.0005,
  "gates": {
    "atr_stops_enabled": false,
    "atr_trail_enabled": false,
    "atr_stop_mult": 2.0,
    "atr_period": 14,
    "earnings_blackout_days": 0,
    "earnings_blackout_block_sells": false,
    "max_avg_correlation": null,
    "vol_target_portfolio_annual": null
  },
  "signals": {
    "xgb_signal_enabled": true,
    "stacking_enabled": true,
    "hmm_enabled": true
  }
}
```

**Cambios necesarios fuera del harness**:

1. `analysis/portfolio_backtest.py`: agregar parámetro opcional `forced_exit_fn` (~20 líneas).
2. `config/settings_manager.py`: agregar 5 toggles nuevos (`hmm_enabled`, `stacking_enabled`, `xgb_signal_enabled`, `correlation_gate_enabled`, `vol_overlay_enabled`) con defaults que preserven comportamiento actual.
3. `analysis/ml_signals.py`: introspect en `compute_signal_probability` los toggles y devolver fallback heurístico si están off.

**8 métricas computadas en `metrics.py`**:
- sharpe_annual, sortino, cagr, total_return
- max_drawdown, turnover (Σ|Δweight|/equity anualizado)
- exposure (% días con ≥1 posición), win_rate
- profit_factor — bonus, 9 métricas, idéntico a baseline_metrics

**CLI**:
```bash
python scripts/harness.py run --config experiments/baseline_sim_principal.json
python scripts/harness.py compare --runs ts1,ts2,...
python scripts/harness.py list
```

**Validación de la primera corrida (DOS chequeos, no uno)**:

**Chequeo 1 — Fidelity (31 días, sin features)**: correr el harness sobre la misma ventana del live (2026-04-24 → 2026-05-26), mismos 52 tickers, gates todos OFF. Debe matchear `[[baseline-sim-principal-2026-05-26]]` ± 2% en P&L cumulativo, win rate, n round-trips. Si no matchea, el simulador difiere del motor y hay que debug ANTES de declarar el harness funcional. Tolerancia más amplia (2% en vez de 1%) porque commission flat vs tiered introduce drift conocido.

**Chequeo 2 — Structural sanity (2 años, sin features)**: correr el harness sobre 2024-05-23 → 2026-05-22, mismos 52 tickers, gates OFF. No matchea nada por construcción (es nuevo). Pero las métricas deben ser plausibles: Sharpe entre 0 y 3 (no 10, no -5), max DD entre 5% y 40%, win rate entre 40% y 65%. Si los números son grotescos, el simulador tiene bugs distintos a los del chequeo 1.

Solo cuando AMBOS pasan, el harness se declara listo para Sprint 2 attribution. **El "match baseline ± 1%" del plan original era conceptualmente incorrecto** — comparaba 31 días live contra 2 años backtest.

**Tests (~20)**:
- Config parse + JSON roundtrip.
- Determinismo (mismo config + mismo seed → mismas métricas).
- Gate wrappers: ATR stop forza exit, earnings blackout bloquea BUY.
- Métricas: turnover anualizado correcto sobre dataset sintético.
- Comparación de runs (`compare` CLI).

---

### Pieza 2 — Walk-forward (NO va en Sprint 1)

Movida a Sprint 2 alongside attribution. Razón:
- Solo aplica a XGB + stacking.
- Sprint 2 va a necesitar walk-forward para validar que las contribuciones de features ML no sean overfit.
- Hacerla en Sprint 1 sin attribution implica trabajo aislado que no se usa hasta Sprint 2.

**Decisión registrada**, no se vuelve a discutir hasta Sprint 2.

---

## Definition of done — Sprint 1 (v2.1)

- ✅ `paper_trading/gates.py` extraído del motor. Suite existente sigue verde (regression-safe).
- ✅ `scripts/harness.py` corre `--config experiments/baseline_sim_principal.json` y produce JSON + CSV row.
- ✅ **Chequeo 1 (fidelity)**: harness sobre 31d matchea baseline live ± 2% en P&L, win rate, n round-trips.
- ✅ **Chequeo 2 (structural)**: harness sobre 2y produce métricas plausibles (Sharpe 0-3, max DD 5-40%, win rate 40-65%).
- ✅ 5 toggles nuevos en SCHEMA, defaults preservan comportamiento actual.
- ✅ Dashboard HTML artifact creado, captura datos en vivo de Sim Principal.
- ✅ Suite full verde (272 + ~20 nuevos = ~292 tests passing).
- ✅ Memory `[[sprint-1-cerrado-YYYY-MM-DD]]` con resultados de ambos chequeos + ancla nueva del backtest 2y.

---

## No-objetivos explícitos (recordatorio)

- **No** walk-forward (movida a Sprint 2).
- **No** medir contribución por feature (Sprint 2).
- **No** matar features (Sprint 3).
- **No** features nuevas — solo toggles.
- **No** corregir auto_adjust ni survivorship.
- **No** tocar la UI principal — el dashboard es artifact separado.
- **No** activar Kelly hasta T07 calibration (Sprint 2).

---

## Plan de arranque inmediato

1. **Hoy / próxima sesión**: dashboard vivo (½ día). Empieza a capturar telemetría desde ya.
2. **Después**: refactor extract `paper_trading/gates.py` + tests existentes verdes (~½ día). Regression-safe.
3. **Después**: 5 toggles en SCHEMA + hook `forced_exit_fn` en `portfolio_backtest.py` (~½ día).
4. **Después**: harness core — CLI + ExperimentConfig + runner + metrics + tests (~2 días).
5. **Validación final**: chequeo 1 fidelity (31d) + chequeo 2 structural (2y). Si fidelity falla, debug — puede tomar 1-2 días extra. Total esperado: 5-6 días.
