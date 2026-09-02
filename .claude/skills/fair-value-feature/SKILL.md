---
name: fair-value-feature
description: Guía para implementar el "valor estimado" (fair value) en la pestaña Analysis de FinanzIAs — mostrar precio actual / fair value propio / target de consenso lado a lado, con upside y precio máx. de entrada. Usar al trabajar cualquiera de las 6 tareas de esta feature.
---

# Feature: fair value en Analysis

**Objetivo**: mostrar tres números lado a lado —**precio actual / fair value propio / target de consenso**— para que el usuario triangule el upside esperado y un precio máximo de entrada. Decidido 2026-06-24, profundidad "Fase 1" (múltiplos, sin DCF completo).

**Restricción dura**: entra como **feature de DISPLAY**, NO cableada a sizing ni a los gates hasta backtestear. La razón **no es un coeficiente**: es que no se cablea lo que no se backtesteó. La evidencia que se citaba (*«`buy_score` no predice el fwd5»*, auditoría 2026-06-17, **n=21**) se re-midió en la tarea 73 y **no alcanzaba para afirmar eso** — con n=21 sólo se detecta |r| > 0.58. Hoy, con n=85: `r = −0.05`, IC95% [−0.26, +0.17], sin relación detectada pero **sin poder para descartar |r| = 0.15**. La restricción sigue igual de dura. Ver skill `finanzias-conventions`.

## Lo que YA existe (no reconstruir)

- `data/yahoo_finance.py`:
  - `get_company_info()` ya devuelve `trailingPE`, `trailingEps`, `beta`, `dividend_yield`.
  - `get_analyst_data()` ya devuelve `price_targets` (targetMean/low/high) y `recommendations`.
- `ui/analysis/recommendations_card.py` (`RecommendationsCard`) ya muestra recos + price targets en la pestaña Analysis. Patrón a imitar: **card silenciosa cuando faltan datos**.
- `ui/analysis/worker.py` (`AnalysisWorker`) ya trae df + price_data + company_info + analyst_data y emite `done(df, result, price_data, company_info, analyst_data)`.
- NO existe `analysis/valuation.py` todavía.

## Plan (6 tareas, en orden)

1. **Diseño + criterios upfront** (`docs/`): decidir el **ancla del múltiplo** (PE_ancla): mediana histórica del propio ticker, múltiplo sectorial estático, o clamp del trailingPE a una banda. Definir manejo de EPS negativo/faltante (→ fair value None, card oculta), % de margen de seguridad (MoS) default, y criterio de aceptación (razonable vs consenso en N tickers, nunca rompe la UI). Dejar explícito: NO se cablea a sizing/gates.
2. **`analysis/valuation.py`** — funciones puras, deterministas, **sin red**: `fair_value_by_multiples(eps, pe_anchor)`, `margin_of_safety(price, fair)`, `max_entry_price(fair, mos_pct)`, `upside_vs_target(price, target_mean)`. Devuelven None ante inputs inválidos (EPS≤0, anchor None, target None). Estilo: ver `analysis/leads.py`, `analysis/metrics_panel.py`.
3. **PE_ancla en la capa de datos** — según el diseño. Si es mediana histórica: computar PE desde el df de precios (ya disponible) + serie EPS (puede requerir un fetch nuevo en `data/yahoo_finance.py` con cache + timeout guard como el resto). Si es sectorial/clamp: tabla estática o derivación del trailingPE. No romper el contrato de `get_company_info`/`get_analyst_data`.
4. **Tests** — `tests/test_valuation.py` offline: EPS válido, EPS negativo→None, anchor faltante→None, sin target→upside None, upside +/−, precio máx entrada con MoS, bordes. Determinístico. Estilo `tests/test_leads.py`.
5. **UI** — los 3 números lado a lado en Analysis + upside% + precio máx. entrada. Card silenciosa si faltan datos. `AnalysisWorker` computa la valuación con lo que ya trae + el anchor nuevo y lo pasa por `done`; `ui/analysis_tab.py` renderiza. Decidir: extender `RecommendationsCard` o card nueva.
6. **Verificación** — suite Windows verde + revisión visual con 2-3 tickers borde (uno con EPS negativo, uno sin target de consenso, uno normal) + commit + actualizar memoria.

## Por qué NO DCF (todavía)

El DCF completo (WACC, terminal, proyecciones) es el camino con más código y el output **menos confiable gratis** — choca con el mismo muro de datos forward-looking que bloquea T-CAT-5b. Si algún día entra, va como banda de sanity bull/base/bear, nunca como punto único.
