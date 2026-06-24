---
name: backtest-replay-harness
description: Cómo correr y crear backtests/replays de exits y estrategia en FinanzIAs, con kill-criteria upfront. Usar al validar una feature de trading antes de shipear, reproducir el comportamiento histórico del motor sobre ciclos reales, o medir el impacto de una variante de salida/entrada.
---

# Backtest / Replay harness

Acá se valida si una feature **mejora las decisiones** antes de cablearla. Regla: **kill-criteria definidos ANTES de correr** (ver skill `finanzias-conventions`). Si no supera el umbral, se documenta en `docs/` y no se shipea.

## Harnesses existentes (`scripts/`)

- `run_exit_replay_t61.py` — replay de exits sobre los ciclos reales. Base del T6.1. Infra en `analysis/exit_replay.py`.
- `run_catalyst_exit_veto_backtest.py` — backtest del exit-veto por catalyst (T-CAT-6); reusa `analysis/exit_replay.py`.
- `harness.py`, `harness_walkforward.py` — backtest de estrategia (walk-forward).
- `run_switcher_validation.py`, `run_cross_sectional_validation.py` — validación de variantes de régimen / cross-sectional.
- `prefetch_harness_cache.py` — precarga el cache histórico (flag `-b` usa `get_historical_data_batch`) para no pegarle a Yahoo durante el backtest.

## Datos

- Correr **read-only sobre un backup limpio** de `finanzias.db` (carpeta `backups/`), NO sobre la DB viva. No escribir la DB desde Linux (ver `finanzias-conventions`).
- Precargar cache con `prefetch_harness_cache.py` antes de correr, para evitar 401 de Yahoo y resultados no-deterministas.
- Los harness deben ser **deterministas**. Ojo: el stacking XGBoost NO es determinístico entre runs (descubierto en T05) — está en modo kill_only justamente por eso.

## Patrón para una variante nueva

1. **Definir kill-criteria upfront** en un doc `docs/<nombre>_<fecha>.md`: métrica (p.ej. ΔP/L total en puntos), umbral, y restricción de riesgo (p.ej. max DD no sube > 1.5×).
2. Elegir el **contrafactual** explícito (p.ej. "la posición vetada sale al próximo scan con ATR activo"). El veredicto suele ser sensible a esto — dejarlo escrito.
3. Reusar `analysis/exit_replay.py` para no reimplementar el motor.
4. Correr sobre el backup + cache precargado.
5. Escribir resultados en el doc, incluyendo el veredicto (ship / no-ship) y por qué.
6. Tests offline del harness (ver `tests/` por convención de naming).

## Lecciones registradas

- Cross-sectional ranking (T05): **KILLED**, +0.124 ΔSharpe < umbral +0.15 → ruido. Quedó como dead-code.
- Exit-veto catalyst (T-CAT-6): flag OFF por razón **medida** (ΔP/L −0.25 < +1.5), no por ceguera.
- min_holding 3d (T6.1): única variante pre-registrada que PASÓ (+3.18 pts, DD 0.92) → shipeada en T6.4.
