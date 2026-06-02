# Régime-conditional attribution (T-régimen-2) — handoff

Sprint 2 fase 2, segundo entregable. Tool listo, validado en sandbox, **falta** correr el walk-forward fresco (en Windows) y leer los resultados reales.

## Qué está implementado

- **`analysis/harness/runner.py`** — `save_results` ahora persiste `equity_curve.csv` per variant (date, equity). Backward-compatible con runs viejos: agrega un archivo, no rompe nada existente.
- **`scripts/regime_attribution.py`** — analyzer post-hoc. Carga equity curves, computa régimen por día con `regime_detector`, slicea daily returns, produce tabla N×4 (variants × régimes) con ΔSharpe vs baseline y veredictos por feature.
- **`tests/test_regime_attribution.py`** — 21 tests, todos pasan. Cubren primitives, slicing, ΔSharpe, verdicts, IO, end-to-end con synthetic data.

## Veredictos automáticos (semántica)

Para cada ablation (no_hmm / no_stacking / no_xgb / no_vol_overlay), el script clasifica el vector de ΔSharpe = `ablation_sharpe − baseline_sharpe` por régimen:

| Veredicto | Significa | Acción |
|---|---|---|
| `keep_all` | Δ < −tolerance en TODOS los regímenes medibles (ablation peor en todos) | Feature útil siempre → keep firm, no switching |
| `kill_all` | Δ > +tolerance en TODOS los regímenes medibles (ablation mejor en todos) | Feature dañina siempre → kill firm |
| `switch` | Mismo Δ tiene signo opuesto entre regímenes | **Candidata a feature switching** (T-régimen-3) |
| `no_effect` | Todos los Δ dentro de ±tolerance | Feature es ruido — kill por simplicidad |
| `undetermined` | Demasiado pocas barras medibles | Sample chico — necesita más data |

Tolerance default: 0.05 (Sharpe units anualizadas). Editable en el código.

## Cómo correr (Windows side)

**Paso 1 — Prefetch cache** (si no está actualizada):

```cmd
python scripts/prefetch_harness_cache.py data/harness_universe_42.txt -p 2y
```

**Paso 2 — Walk-forward fresco**. Importante: el patch a `save_results` debe estar mergeado. Verificar con:

```cmd
git diff analysis/harness/runner.py
```

(debería incluir el bloque que escribe `<variant>.equity.csv`).

Luego:

```cmd
python scripts/harness_walkforward.py data/harness_universe_42.txt --n-windows 2 --suite all
```

~70 minutos. Output bajo `data/harness_walkforward/<timestamp>/early_12m/` y `late_12m/`.

**Paso 3 — Attribution post-hoc**:

```cmd
python scripts/regime_attribution.py data/harness_walkforward/<timestamp>/
```

(O con SPY explícito si está disponible: `--proxy-csv data/spy_close.csv`.)

Output:
- A consola: tabla por window con per-variant per-régime Sharpe + ΔSharpe + veredicto.
- A disco: `data/harness_walkforward/<timestamp>/regime_attribution.json` con todo el report estructurado.

## Cómo interpretar (T-régimen-3 input)

Después de correr ambas windows, comparar veredictos:

| Caso | Significa | Próximo paso |
|---|---|---|
| Veredicto consistente en ambas windows (ej. `switch` en early + `switch` en late) | El patrón cross-régimen es estable | Implementar switching de esa feature |
| Veredictos opuestos entre windows | Patrón inestable también dentro de régimen | Probablemente kill |
| Veredictos diferentes pero coherentes (ej. `keep_all` early + `kill_all` late) | Régimen-detection no captura todo el contexto | Considerar agregar VIX o breadth al detector (v2) |

## Caveats heredados de T-régimen-1

- **Proxy fallback ≠ SPY real**. Si no se pasa `--proxy-csv`, el script construye un proxy equal-weighted desde las equity curves de las variants. Es coarse pero funciona; lo correcto cuando SPY esté en cache es pasarlo explícito.
- **bull_volatile sample chico**. Sobre 2y de SPY-proxy en T-régimen-1 sólo apareció 10 barras. Las celdas de bull_volatile probablemente sean NaN o demasiado ruidosas para juzgar. Decisión: tolerar y mirar bull_quiet + bear + lateral como las 3 dimensiones principales.
- **Tolerance=0.05 es heurística**. Si los Δ reales son muy chicos (por ejemplo |Δ|<0.05 todos), revisar si el harness está realmente ejerciendo las features (ver gap documentado en sprint 1: harness signal_fn bypass).

## Próximo paso después de T-régimen-2

T-régimen-3: implementar el feature switching para las que dieron `switch` veredicto. Lógica esperada:

```python
def feature_switch(regime: str) -> dict[str, bool]:
    return {
        "hmm_enabled":       <ON/OFF basado en attribution>,
        "stacking_enabled":  <ON/OFF basado en attribution>,
        "xgb_signal_enabled": <ON/OFF basado en attribution>,
        "vol_overlay_enabled": <ON/OFF basado en attribution>,
    }[...]
```

Luego validar walk-forward con switching ON vs baseline. Si Sharpe consolidado > baseline por +0.3 con confianza, es el alpha real del Sprint 2.

Las features con veredicto `keep_all` o `kill_all` (no switch) se ejecutan en Sprint 3 (poda firme), no pasan por el switcher.
