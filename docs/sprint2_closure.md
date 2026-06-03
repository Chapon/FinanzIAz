# Sprint 2 — Cierre

**Fecha de cierre**: 2026-06-02
**Status**: ✅ CERRADO

## TL;DR

Sprint 2 cerró con **2 kills firmes (HMM, Stacking) + 0 switches implementados + 2 keeps (XGB, vol_overlay)**. La hipótesis del switching de vol_overlay régime-aware se descartó después de validación end-to-end: el switcher empeora en bears y empata-o-pierde en agregado contra `kill_only`. La hipótesis "HMM ayuda en bull-puro sostenido" se descartó después de bootstrap con 10y de data.

**Acción de producción**: setear `hmm_enabled=False` y `stacking_enabled=False` en `~/.finanzias/settings.json`. Sin otros cambios. Sprint 2 alpha esperado: **~+0.19 Sharpe anualizado** (overall 10y, P(Δ≤0) = 7.5%, al borde de sig formal).

## Veredictos finales por feature

| Feature | Decisión | Evidencia base | Confidence |
|---|---|---|---|
| **xgb_signal_enabled** | KEEP (mantener True) | 4/4 windows ayuda en bull_quiet (régime dominante), 3/4 en lateral, 10y replica | Firme |
| **stacking_enabled** | KILL (set False) | Caótico en TODOS los régimes; señal consistente solo de "hurts en bear" (2/2 obs) | Firme |
| **hmm_enabled** | KILL (set False) | 3/4 windows daña en bull_quiet; bull-pure 2021 regression refutada con 10y data | Firme |
| **vol_overlay_enabled** | KEEP always ON (no switching) | Switcher empeora en bears (P switch≤kill = 74%); kill_only > switcher en 3/4 windows 10y | Firme |

## Cronología del análisis

### T-régimen-1 (cerrado 2026-06-01)
- Detector estadístico SPY (Sharpe 60d + vol 30d), 4 buckets, threshold=1.0 calibrado contra noise floor del Sharpe rodante.
- 35 tests PASS. Validación sobre 2y proxy: 0.51 transitions/mo (no ruidoso), recupera Aug-2024 vol shock + Q1-2025 corrección + bull grind.
- Ver `docs/regime_detector_v1.md`.

### T-régimen-2 fase 1 — Walk-forward 5y × 4 windows
- Patch crítico: `bh_equity_curve.csv` persistido per variant (el fallback equity-mean ocultaba bears y bull_volatile).
- Patch crítico 2: detector corre globalmente sobre el 5y stitched, no per-window (warmup eats régimen del Q1-2025).
- Resultado por feature × régime (4×4 windows × 4 buckets): XGB keep firme, Stacking caótico, HMM 3/4 daña en bull_quiet, vol_overlay switching candidate.

### T-régimen-3 — Validación del switcher
- `paper_trading/feature_switch.py` + 16 tests PASS.
- `scripts/run_switcher_validation.py` corre baseline + kill_only + full_switcher × 4 windows × 5y.
- **5y resultado**: kill_only +0.158 mean (4/4 windows positivos), full_switcher +0.203 mean pero regresiona −0.21 en w1 bear-heavy. Switching delta +0.045.

### Análisis adicional — Calendar blocks 5y (sugerido por Chapa)

| Block | n | kill_only Δ | switcher Δ | Lectura |
|---|---|---|---|---|
| A: bull tail 2021 | 98 | −0.628 | −0.628 | kill_only y switcher AMBOS pierden |
| B: bear 2022 | 200 | **+0.340** | −0.044 | kill_only gana, switcher empata |
| C: mixto 2023-2026 | 753 | +0.267 | +0.529 | ambos ganan |

Hallazgo inicial: **el bull-puro 2021 mostraba kill_only y switcher AMBOS perdiendo**. Sugería "HMM ayuda en bull sostenido low-vol".

### Bootstrap 5y — primera ronda

| Block | kill_only P(Δ≤0) | Lectura |
|---|---|---|
| A bull pure | 96.1% | lean neg fuerte (CI casi excluye 0) |
| B bear | 8.9% | lean pos |
| C mixto | 23.2% | suggestive pos |

El bootstrap mostró que la "bull-pure regression" tenía la signal más fuerte (96% one-sided), no era pura ruido. Decisión: prefetch 10y + re-correr para confirmar.

### Bootstrap 10y — confirmación

Walk-forward 10y × 4 windows (excluyendo MLTX por history limitada):

| Block | n | kill_only Δ | CI 95% | P(Δ≤0) | Verdict |
|---|---|---|---|---|---|
| **A: bull 2016-2018** (sostenido REAL) | **~600** | **+0.131** | [−0.45, +0.68] | 34.8% | noise — **NO regresión** |
| **B: 2019 + COVID** | ~500 | **+0.464** | **[+0.08, +0.88]** | **0.6%** | **SIG POS** |
| C: 2021 bull tail (revisitado) | ~250 | +0.258 | [−0.33, +0.85] | 18.2% | noise positive |
| D: 2022 bear | 250 | +0.310 | [−0.46, +1.07] | 20.8% | noise positive |
| E: 2023-2026 mixto | ~750 | −0.024 | [−0.60, +0.50] | 51.8% | noise |
| **OVERALL** | **2310** | **+0.188** | **[−0.07, +0.45]** | **7.5%** | **borde de sig 5%** |

**Hipótesis HMM-helps-bull-puro REFUTADA por 10y data:**
- Block A (2016-2018, bull sostenido REAL, 2.5 años): kill_only ganó +0.131. Era el test exacto de la hipótesis. Falló.
- Block C revisitado con 10y windowing: kill_only ahora gana +0.258 (vs −0.628 del 5y windowing). **El −0.628 era artifact de cómo el 5y dividió en windows**, no signal real.
- Block B (2019 bull + COVID): kill_only ganó +0.464 con SIGNIFICANCIA FORMAL (única significativa de todo el análisis).

### Switcher: descartado

Con 10y data:
- Switcher mean Δ vs baseline: +0.103 (peor que 5y +0.203)
- Switcher vs kill_only: −0.088 mean, P(switch≤kill) = 74.2%
- 3 de 4 windows el switcher es PEOR que kill_only

No hay evidencia para implementar el switching. `vol_overlay_enabled` queda True permanente (default).

## Lessons learned

1. **El régime detector v1 (Sharpe 60d + vol 30d) no distingue sub-régimes dentro de bull**. La "regression" inicial en bull-puro 2021 fue artifact de windowing chico (98 bars), no evidence de sub-régime. Con bull period largo (2016-2018), kill_only ganó. Esto es information valiosa para futuro v2 del detector: la dimensión Sharpe + vol parece suficiente al nivel de 4 buckets.

2. **5y data fue insuficiente para validar HMM en bull-puro**. La hipótesis se sostuvo con 5y porque el único bull-puro disponible era 2021 H2 (98 bars). Necesitamos 10y data y ~600 bars de bull sostenido (2016-2018) para refutarla rigurosamente.

3. **Switching vol_overlay régime-aware perdió contra kill_only consistentemente**. La policy `vol_overlay_enabled = (regime in {bull_quiet, bear})` derivada del attribution se vio bien sobre 5y pero degradó con 10y. El switching agrega complejidad sin upside.

4. **El bootstrap es indispensable para distinguir señal de ruido con N < 200 bars**. La regression bull-pure que parecía sería con eyeball-Sharpe (−0.628) tenía CI [-1.36, +0.06] — casi incluyendo 0. Sin bootstrap habríamos shippeado decisiones equivocadas.

5. **`bh_equity_curve` es el proxy correcto, no equity-mean**. Las strategies se desinvierten durante shocks → el proxy de equity curves suprime bear y bull_volatile. Persistir bh_equity_curve.csv per variant fue critical para que el régime detector vea el mercado real.

6. **Régimen debe computarse globalmente**, no per-window. Per-window el warmup de 60 bars come régimes que ocurren al inicio de cada window (Q1-2025 bear cayó en warmup del w4 5y).

## Cambios al código operativo durante Sprint 2

- `analysis/regime_detector.py` — nuevo, 4 buckets, función pura.
- `paper_trading/feature_switch.py` — nuevo, policy régime-aware (queda como infraestructura no activada).
- `analysis/harness/runner.py` — patches: persist equity_curve.csv + bh_equity_curve.csv per variant; opcional régime-aware vol_overlay closure.
- `scripts/regime_attribution.py` — nuevo, post-hoc analyzer.
- `scripts/run_switcher_validation.py` — nuevo, validación end-to-end de 3 variants.
- `data/harness_universe_41_10y.txt` — universe sin MLTX para experimentos 10y.
- Tests: `test_regime_detector.py` (35), `test_regime_attribution.py` (21), `test_feature_switch.py` (16) — 72 tests nuevos.

## Datos persistidos

- `data/proxy_eqw.csv` — proxy CSV de 53 tickers, útil como `--proxy-csv` cuando bh_equity no esté disponible.
- `data/harness_walkforward/20260601_095031/` — primer walkforward 2y × 2 windows (proxy bug).
- `data/harness_walkforward/20260601_155840/` — walkforward 5y × 4 windows (attribution definitiva).
- `data/switcher_validation/20260602_100845/` — switcher validation 5y × 4 windows.
- `data/switcher_validation/20260602_123206/` — switcher validation 10y × 4 windows.

## Próximo paso — Sprint 4 (cross-sectional ranking)

Per el roadmap original, la siguiente palanca más prometedora era cross-sectional ranking: el sistema hoy piensa absoluto ("¿este ticker es BUY?") y debería pensar relativo ("¿es de los top 3 de los BUYs del día?"). Métricas candidatas: momentum percentile, RS sectorial, z-score vs watchlist.

Construir sobre el sistema podado (kill_only): sin HMM/Stacking contaminando, el cross-sectional debería surface alpha de la dimensión relativa más limpiamente.

## Cambios para producción

Single change en settings:

```python
# Setear desde Python (en Windows):
from config.settings_manager import settings
settings.set("hmm_enabled", False)
settings.set("stacking_enabled", False)
# xgb_signal_enabled y vol_overlay_enabled quedan en True (default)
```

O directamente editar `~/.finanzias/settings.json`:

```json
{
  ...
  "hmm_enabled": false,
  "stacking_enabled": false,
  "xgb_signal_enabled": true,
  "vol_overlay_enabled": true
}
```

Reiniciar el engine para que los toggles surtan efecto.

## Caveats heredados

- `paper_trading/feature_switch.py` queda como dead-code de infraestructura — no se activa pero el wiring está listo si en el futuro se reabre el switching con régime detector v2 (VIX, market breadth, etc).
- El régime detector v1 está calibrado contra US large-caps 2016-2026. Out-of-sample para sectores chicos o non-US es no probado.
- `data/harness_universe_41_10y.txt` es ad-hoc — no usar para attribution / production. Universo canónico sigue siendo `harness_universe_42.txt`.
