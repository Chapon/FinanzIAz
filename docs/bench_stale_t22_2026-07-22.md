# Tarea 22 — BENCH-STALE: el benchmark SPY se congelaba en silencio

_2026-07-22 · display-only / calidad de datos · gate técnico (suite verde) · **SHIP**_

## El bug (observado en vivo 2026-07-21)

La línea "SPY (normalizado)" de la curva de equity y el número **VS SPY** de
Métricas se quedaban clavados en una fecha vieja mientras la equity seguía
avanzando (equity al 21/07, SPY cortaba ~10/07). En la DB: la fila 1d más fresca
de SPY era del `fetched_at 2026-07-11` (último close 07-10) y todo el cache 1d
había quedado congelado.

**Cadena de causa raíz:** SPY entra al warm-up del scan **solo** vía el batch
(`engine.py`, `get_historical_data_batch(set(tickers) | {SPY})`) y **no** se
agrega a `tickers` — por diseño, para que no toque precios ni gates (V1). Efecto
colateral: SPY es el **único símbolo sin fallback per-ticker** (los `tickers`
reales se re-piden por `history_provider` durante estrategia/ATR/σ). Cuando el
batch falla por throttle/401 ("Invalid Crumb"), la fila vieja de SPY queda
intacta. Después:

- `load_close_series` lee la fila más nueva con `ORDER BY fetched_at DESC LIMIT 1`
  **sin TTL** → devuelve la barra stale como si fuera actual.
- `build_benchmark_overlay` dibuja la línea solo hasta donde hay barras → corta
  en silencio, sin marca.
- **Lo peor, el número:** `_benchmark_panel` compara la cuenta sobre la ventana
  **completa** contra un SPY **recortado** → `vs_spy` sesgado en silencio, justo
  el número que V1 (tarea 2) existe para producir.
- La equity sí avanza porque `record_equity_snapshot` solo usa el precio actual
  (`get_bulk_prices`, cache 5 min), no el histórico OHLCV de SPY.

## El fix (dos patas — política de calidad = las dos)

### (a) Robustez de fetch — `paper_trading/engine.py`

Warm-up extraído a `_warm_up_history_cache(tickers)`. Captura el resultado del
batch; si **SPY volvió `None`** (throttle/401, o el batch reventó entero), le da
un **fallback per-ticker**: `get_historical_data("SPY", period=...)` — un único
request, y SPY ya es el canario de NET1. Best-effort: cualquier fallo se loguea y
no corta el scan. Con esto SPY recibe el mismo re-fetch que los demás símbolos.

### (b) Honestidad del display — nunca mostrar dato stale como actual

- `analysis/metrics_panel.py`: constante `BENCHMARK_STALE_BDAYS = 3` + helper puro
  `benchmark_stale_bdays(spy_last_day, ref_day)` (`np.busday_count`, el idiom del
  repo). `_benchmark_panel` marca `stale=True` y **NO computa `vs_spy`** cuando
  SPY queda > 3 días hábiles atrás del último snapshot (el payload gana
  `stale` + `spy_end_day`). El umbral 3 tolera el lag normal de 1-2 ruedas (la
  barra 1d de hoy recién aparece tras el cierre, fines de semana/feriados).
- `ui/metrics_tab.py`: la card VS SPY muestra `SPY desactualizado (hasta DD/MM)`
  en vez de un número sesgado.
- `ui/paper/equity_chart.py`: helper puro `overlay_is_stale(...)` reusa el mismo
  umbral; con SPY stale se **suprime la línea corta** y se anota
  "SPY desactualizado" en el gráfico. `paper_tab._load_spy_overlay` devuelve
  `(overlay, stale)`.

## Decisión de alcance

Se hicieron **(a) + (b)**, no solo el parche del chart: (a) repuebla el dato
real, (b) es la red de seguridad para que nunca vuelva a mentir en silencio
aunque Yahoo throttlee. Sinergia con **ARQ3 (tarea 14)**: una cadena de providers
resolvería (a) de raíz.

**Fuera de alcance (nota):** `scripts/dashboard_data.py` (`_monthly_perf`) tiene
un consumidor de SPY parecido, pero calcula el retorno **por mes calendario** con
las barras dentro del mes — el sesgo por congelamiento ahí es acotado al mes en
curso y con un framing distinto. No estaba en el pre-registro de la tarea 22;
queda anotado como superficie relacionada.

## Kill-criteria (gate técnico) — PASÓ

Suite Windows verde: **1400 passed, 3 skipped**. Tests nuevos:

- `test_scan_history_warmup.py` (pata a): el fallback per-ticker de SPY se dispara
  cuando el batch lo saltea o revienta, y **no** cuando el batch ya lo trae.
- `test_metrics_panel.py` (pata b, el número): `_benchmark_panel` marca `stale` y
  no computa `vs_spy` con SPY 7 días hábiles atrás; no marca stale dentro de la
  tolerancia (2 días). + unit de `benchmark_stale_bdays`.
- `test_equity_overlay.py` (pata b, el gráfico): `overlay_is_stale` + smoke de que
  el chart anota "SPY desactualizado" y no dibuja la línea.

**Verificación GUI pendiente de Chapa:** tras un scan la línea SPY debería llegar
hasta ~hoy; con el cache viejo se ve el marcador de desactualizado.
