# Sprint 1 — Validation Infrastructure (2026-05-27)

## Status: WIP — 3.5/5 items shippable, harness wiring still required for Sprint 2

Items 1–4 are done and integrated. Item 5 (harness) ships the infrastructure but
**the 5 toggles it ablates are not yet wired into the engine**, so until the
wiring lands in Sprint 2 every ablation will produce identical results to
baseline. That wiring is the gate for any attribution work.

---

## 1. Dashboard vivo de Sim Principal — DONE

- **Artifact**: `finanzias-sim-principal-dashboard`
- **Pattern**: snapshot embedded in HTML, refresh via `sendPrompt()` (artifact-bash is blocked, per `feedback_artifact_bash_paths.md`).
- Cache-only: no live `yfinance` fetch on reload — historical monitoring view.

## 2. Gates extracted to `paper_trading/gates.py` — DONE

Four pure functions, no settings/DB/logger dependencies:

- `atr_exit_decision()`
- `is_within_earnings_blackout()`
- `select_uncorrelated_picks()`
- `compute_vol_overlay()`

Engine and strategies use thin wrappers. 40 new + 2 parity tests added in the
gates commit (commit `682c993`). Full test suite was not re-run in this audit
because the sandbox lacks pytest; counts in the prior summary are unverified.

## 3. YFinance fetch errors resolved — DONE

`dashboard_data.py` is 100% cache-only. The dashboard JSON ships off
`finanzias.db` + `historical_data_cache`; no Yahoo fetch is attempted on
reload. Blocker cleared.

## 4. 5 Feature toggles + forced_exit_fn hook — DONE

### Toggles (`config/settings_manager.py`)

Five `bool` settings, all default `True`:

```
hmm_enabled
stacking_enabled
xgb_signal_enabled
correlation_gate_enabled
vol_overlay_enabled
```

Test: `tests/test_settings.py::test_feature_toggles_sprint1_persist`.

**Caveat**: these are declared but not yet read anywhere outside the harness.
`grep -r hmm_enabled --include="*.py"` returns hits only in
`config/settings_manager.py` and `analysis/harness/*`. Wiring each one to the
relevant engine site (`analyze_single`, allocation, gates) is Sprint 2 work.

### `forced_exit_fn` hook (`analysis/portfolio_backtest.py`)

```python
forced_exit_fn: Callable[[str, pd.DataFrame, _PositionState], tuple[bool, str]] | None
```

Called every iteration for each open position. Returning `True` adds the
ticker to `forced_exits` for that bar and propagates the custom `exit_reason`
into the `PortfolioTrade`. Exceptions in the hook are swallowed with a
warning, the position stays open.

**Re-entry fix (this audit)**: previously, a ticker flagged for forced exit
would be re-added to `new_entries` on the same bar if its signal was `BUY`,
silently turning the exit into a same-bar rebalance and dropping the custom
`exit_reason`. The candidate filter now excludes `forced_exits`, so the exit
actually closes the position and the reason reaches `trades_log`. Tests in
`tests/test_forced_exit_fn.py` (4 tests) verify the round trip end-to-end.

## 5. T-harness infrastructure — DONE as code, NOT YET useful for attribution

### Files

- `analysis/harness/__init__.py`
- `analysis/harness/config.py` — `ExperimentConfig` (baseline + 5 ablation variants)
- `analysis/harness/metrics.py` — `ComputedMetrics` + `compute_metrics()`
- `analysis/harness/runner.py` — `HarnessRunner`
- `scripts/harness.py` — CLI entrypoint
- `tests/test_harness.py` — 17 unit tests (all pass via stub-pytest harness)

### What works

- `ExperimentConfig.baseline()` / `ablation_variants()` produce 1 + 5 configs.
- `compute_metrics()` derives 8 metrics from a backtest result.
  - turnover is computed as round trips per year (the underlying result has
    no dollar-volume turnover field).
- `HarnessRunner.run_suite()` snapshots the 5 toggles before mutating and
  restores them in `finally`, so the user's production `settings.json` is left
  exactly as it was found.
- `scripts/harness.py --help` runs cleanly; subcommands `baseline`,
  `ablations`, `all` exist.

### Known gap (BLOCKING for Sprint 2 attribution)

The 5 toggles are not consumed by any engine code, so running ablations
through the harness produces 6 statistically identical results. Until the
following sites read their respective toggle, attribution data is fake:

| Toggle                       | Engine site to wire                                  |
|------------------------------|-------------------------------------------------------|
| `hmm_enabled`                | `analyze_single` HMM regime branch                    |
| `stacking_enabled`           | scan loop / slot logic (T05)                          |
| `xgb_signal_enabled`         | allocation `_compute_target_weights` / signal weight  |
| `correlation_gate_enabled`   | `select_uncorrelated_picks` call site                 |
| `vol_overlay_enabled`        | `compute_vol_overlay` call site                       |

### CLI usage

```
python3 scripts/harness.py baseline                  # baseline only
python3 scripts/harness.py ablations                 # baseline + 5 ablations
python3 scripts/harness.py all -p 2y -t AAPL,MSFT    # custom tickers/period
python3 scripts/harness.py all -q                    # quiet
```

### Output

`data/harness_results/{timestamp}/`:
- `index.csv` — one row per experiment with the 8 metrics + `n_trades`
- `results/{exp}.json` — full config + metrics per experiment

### Validation

- `validate_fidelity(baseline_metrics, tolerance=0.02)`: baseline experiment
  must match frozen baseline within ±2% on period_return and ±0.5 on Sharpe.
- `validate_structure()`: plausibility checks per experiment
  (period_return ∈ [-50, 100]%, Sharpe ∈ [-2, 5], win_rate ∈ [20, 80]%,
  max_drawdown ∈ [0, 50]%).

---

## Test status

Sandbox lacks `pytest`; tests were exercised by stub-importing each module
with a fake `pytest` and calling each `test_*` function directly.

| File                          | Tests | Result                              |
|-------------------------------|-------|--------------------------------------|
| `tests/test_settings.py`      | 9     | imports OK, not exercised in audit   |
| `tests/test_forced_exit_fn.py`| 4     | 4/4 PASS (after re-entry fix)        |
| `tests/test_harness.py`       | 17    | 17/17 PASS                           |

The previous summary claimed "test_harness.py 35 tests ✅" and a full-suite
"343 passing" — neither was verifiable in this sandbox. Numbers above are
the actual ones.

---

## What's next (Sprint 2)

1. **Wire the 5 toggles** to their engine sites (table above). This is the
   blocker for any attribution work.
2. Run `python3 scripts/harness.py ablations` and check that no_xxx variants
   actually diverge from baseline.
3. T04-attribution: ΔSharpe per feature, rank, decide kill criteria.
4. T07-calibration: isotonic regression on `ml_probability`, fix Brier score.

Kill criteria upfront (example): "T05 stacking dies if OOS ΔSharpe < +0.15
with 95% CI".

---

## Files touched in this sprint

### Created
- `analysis/harness/{__init__,config,metrics,runner}.py`
- `scripts/harness.py`
- `tests/test_harness.py`
- `tests/test_forced_exit_fn.py`
- `docs/SPRINT_1_SUMMARY.md` (this file)

### Modified
- `config/settings_manager.py` — `SCHEMA` extended with 5 toggles
- `analysis/portfolio_backtest.py` — `forced_exit_fn` param + same-bar re-entry block
- `tests/test_settings.py` — toggle persistence test

---

Generated: 2026-05-27, audited and revised 2026-05-28
