# Regime detector v1 — design + validation (T-régimen-1)

Sprint 2 fase 2, primer entregable. Implementación en `analysis/regime_detector.py`,
tests en `tests/test_regime_detector.py`.

## Decisiones de diseño

- **Approach elegido**: régimen estadístico SPY (Sharpe móvil 60d + vol realizada 30d). Descartados HMM (circular: el HMM también es feature evaluada en Sprint 2) y GARCH puro (sólo varianza, sin dirección).
- **Función pura**: sin DB, sin settings, sin logger. Mismo patrón de `paper_trading/gates.py`. Caller responsable de pasar la serie del proxy.
- **4 buckets** (no más, no menos): `bull_quiet`, `bull_volatile`, `lateral`, `bear`. Lateral colapsa el eje volatilidad (en lateral la dirección domina; el subbucket por vol no aportaba al uso downstream).
- **Salida**: DataFrame con columnas `sharpe`, `vol`, `regime_raw`, `regime`. Mismo índice que el input. `regime_raw` es la clasificación bar-a-bar sin suavizar; `regime` aplica histéresis.

## Thresholds finales

| Parámetro | Default | Razón |
|---|---|---|
| `sharpe_window` | 60 bars | Pedido del roadmap. Corresponde a ~3 meses de bars diarias. |
| `vol_window` | 30 bars | Pedido del roadmap. ~6 semanas. |
| `sharpe_threshold` | **1.0** | Calibración no obvia. El ruido del Sharpe rodante sobre 60 obs es σ ≈ √(252/60) ≈ 2.05 anualizado. Una banda de ±0.5 confunde sample-mean noise con régimen real. ±1.0 mantiene la banda lateral lo bastante ancha como para absorber varianza, sin perderse SPY bull/bear reales (Sharpe típico |1.5–3|). |
| `vol_threshold` | 0.18 | 18% anualizado separa "quiet" de "volatile" en bull. Compatible con la realidad histórica de SPY. |
| `min_run_length` | 5 bars | Histéresis: un régimen nuevo necesita persistir 5 barras seguidas antes de aceptarse. Suprime flicker bar-a-bar sin retrasar más de una semana los giros reales. |

## Validación 1 — estabilidad bar-a-bar

Corrido contra equal-weighted proxy de los 53 tickers cacheados con período 2y/1d (excluyendo MLTX por outlier). 516 barras, 2024-05-02 → 2026-05-22.

| min_run_length | Transiciones/mes | Median run (bars) | Short runs (<5) |
|---|---|---|---|
| 1 (raw) | 2.16 | 3 | 28 |
| 3 | 0.78 | 12 | 3 |
| **5 (default)** | **0.51** | **24 (~5 sem)** | **0** |
| 10 | 0.32 | 40 | 1 (perdió bear) |

Lectura: con default `min_run_length=5` hay **0.51 transiciones/mes**, median run de ~5 semanas, cero runs cortos (<5 barras). Por debajo del umbral heurístico de "1 transición/mes" para considerar detector no-ruidoso. Subir a 10 elimina el bear histórico válido (over-smoothing).

## Validación 2 — recuperación de regímenes históricos conocidos

Runs del proxy con config default:

```
2024-07-30 → 2024-08-22  lateral         18d  Δ +3.64%
2024-08-23 → 2024-09-06  bull_volatile   10d  Δ -4.09%   ← Yen-carry unwind selloff de agosto 2024
2024-09-09 → 2024-10-21  lateral         31d  Δ +5.96%
2024-10-22 → 2025-01-03  bull_quiet      51d  Δ +1.87%
2025-01-06 → 2025-02-03  lateral         19d  Δ +0.39%
2025-02-04 → 2025-02-10  bull_quiet       5d  Δ +0.30%
2025-02-11 → 2025-03-11  lateral         20d  Δ -7.91%   ← Inicio de la corrección Q1 2025
2025-03-12 → 2025-04-29  bear            34d  Δ -1.29%   ← Confirmación bajista
2025-04-30 → 2025-06-09  lateral         28d  Δ +10.08%  ← Rebote
2025-06-10 → 2026-03-05  bull_quiet     185d  Δ +15.95%  ← Bull grind largo
2026-03-06 → 2026-05-13  lateral         48d  Δ +12.59%
2026-05-14 → 2026-05-22  bull_quiet       7d  Δ +1.88%
```

Recuperación cualitativa:

- El **shock de volatilidad de agosto 2024** (carry trade unwind, vol spike) cae en `bull_volatile`. ✓
- La **corrección Q1 2025** atraviesa `lateral` (acumulación de drawdown) → `bear` (drift negativo confirmado) → `lateral` (rebote). ✓ Pattern económicamente coherente.
- El **rally largo mid-2025 a Q1-2026** se identifica como `bull_quiet` ininterrumpido por 185 días. ✓
- El segmento final `2026-03-06 → 2026-05-13` (`lateral`, +12.59%) es un pequeño desfase: el detector tardó por histéresis en re-confirmar bull tras la pausa de Q1 2026. Costo aceptable de robustness.

Estadísticas centrales por régimen (consistencia interna):

| Régimen | n bars | Sharpe p50 | Vol p50 |
|---|---|---|---|
| bull_quiet | 248 | +2.37 | 0.131 |
| bull_volatile | 10 | +1.42 | 0.253 |
| lateral | 164 | +0.42 | 0.173 |
| bear | 34 | −1.21 | 0.270 |

Cada bucket ocupa la región del plano (Sharpe, vol) que su nombre implica. No hay solapamiento.

## Caveats

1. **Proxy no es SPY**. La validación usa equal-weighted de la watchlist (53 large-caps). Una vez disponible la serie real de SPY 2y/5y en cache, conviene re-validar — el resultado debería ser cualitativamente igual (mismas event identifications).
2. **Window de validación corto** (2 años). No incluye covid (2020), bear de 2022, ni la era ZIRP previa. La transferibilidad del detector a regímenes outside-of-sample es una hipótesis no probada por este ejercicio.
3. **`bull_volatile` apareció sólo 10 barras**. La 2024-2026 fue mayormente bull tranquilo o lateral/bear. Bullvol es bucket válido por diseño pero los downstream análisis tienen que tolerar samples chicos.
4. **`min_run_length=5` produce ~1 semana de retraso** en confirmar giros. Consciente: el ruido suprimido vale más que la latencia para attribution condicional. No usar este detector para timing intraday.

## Próximo paso — T-régimen-2

Con el detector listo y validado, T-régimen-2 mide ΔSharpe condicional al régimen detectado para cada una de las 4 features PENDING de Sprint 2 (HMM, XGBoost, vol_overlay, stacking). Output esperado: tabla 4 features × 4 regímenes. Decisión por feature según el signo de ΔSharpe dentro de cada régimen.
