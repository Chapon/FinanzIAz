# E5 — Sanity de precios fuera de banda + re-auditoría de ciclos contaminados

_2026-07-01 · backlog E5 (ref `docs/effectiveness_deep_analysis_2026-06-30.md` §5)._

## Problema

El ciclo **KLAC** (Sim Principal, id=1) se abrió y cerró un round-trip entero en
escala ~10× corrupta: BUY 2026-06-01 @ **1942.70** ×2 y SELL 2026-06-05 @
**1987.83** (`atr_trail`), cuando el precio real de KLAC era ~$194/$193. Familia
del "Invalid Crumb"/401 que `bec78e6`/`3f833bb` mitigaron para el *fetch*, pero
acá el valor corrupto **pasó el filtro y se usó como precio de entrada/salida**.
El ATR del reason (93.85 sobre ~$1987 ≈ 4.7%, plausible; sobre ~$200 sería
absurdo) confirma que todo el ciclo corrió inflado.

**Impacto:** notional ~10× inflado ($3.885 vs ~$388) → distorsiona peso en el
portfolio, DD, exposición, ADV cap, y aparece como un `atr_trail` "ganador"
(+$89.44) que ensucia hasta la muestra de salidas ATR de A1. Es la **base de
calidad de datos**: un dataset walk-forward (E4) sobre precios corruptos hereda
la corrupción → E5 es prerequisito de E4.

## Kill-criteria (pre-registrado)

1. Suite Windows verde.
2. Un fill con precio fuera de banda (>50% vs último close) se **rechaza/marca**
   en vez de ejecutarse.
3. Barrido de la DB **sin otros** round-trips con notional fuera de escala.

## Solución — tres capas de defensa

1. **Guard prospectivo en el fetch** (`data/yahoo_finance.py`): tras un fetch en
   vivo, `_reject_if_out_of_band` compara el precio contra `reference_close`
   (último close diario del cache OHLCV). Si `is_price_out_of_band` (desvío >
   `price_sanity_band_pct`, default 0.5) → se descarta como miss, **no se cachea
   ni se devuelve**, log de warning. NO envenena el `failing` set (la corrupción
   es transitoria → el próximo scan reintenta). Aplicado en `get_current_price`
   y `get_bulk_prices`.
2. **Sanity-check antes de fillar** (`paper_trading/engine.py`): belt-and-braces.
   `_price_out_of_band(ticker, fill_px)` en el path de fill del scan (skip +
   warning) y en `approve_order` (expira la orden). Cubre precios corruptos que
   esquiven la capa 1 (provider inyectado, cache viejo). Fail-open sin referencia.
3. **Auditoría retroactiva** (`scripts/audit_price_contamination.py`): barre las
   órdenes `filled` comparando `fill_price` vs el close cacheado **en la fecha
   del fill** (misma higiene que `run_atr_stop_recalib.partition_atr_events`, más
   precisa que el último close → no marca falsamente a movers legítimos tipo
   MLTX). `--apply --yes` anula (void) los round-trips **cerrados** contaminados y
   revierte su efecto neto de caja; hace backup en `backups/` antes de escribir.

La banda por defecto es 50% **día-a-día vs el último close**: un salto de esa
magnitud es un halt raro, no lo normal → buen discriminador de basura de escala
sin falsos positivos sobre tendencias/caídas legítimas multi-día.

## Resultado

- **Barrido (2026-06-30/07-01):** de **120 órdenes filled**, el único round-trip
  contaminado es **KLAC (orders 73/77)** — desvíos +901% / +930% vs close real.
  Sin otros notionals fuera de escala. ✔ (kill-criteria 3)
- **Remediación (decisión de Chapa: void):** orders 73/77 → `status='voided'`
  con nota de auditoría; caja de Sim Principal revertida **−$89.44**
  ($7202.22 → $7112.79). Backup: `backups/finanzias_pre_e5_20260701_035340.db`.
  El ciclo es un fantasma nacido de datos corruptos (la señal `analyze()` y el
  ATR corrieron sobre OHLCV podrido) → excluirlo es lo honesto; así lo trata ya
  el harness A1. Métricas y harness filtran `status='filled'` → KLAC queda fuera.
  Re-sweep posterior: **DB limpia**. ✔
- **Suite Windows:** 967 passed, 1 skipped. ✔ (kill-criteria 1)
- **Tests:** `tests/test_price_sanity.py` (17) — predicado puro, `reference_close`,
  rechazo en `get_bulk_prices`/`get_current_price`, no-cacheo del corrupto,
  fail-open sin referencia, sanity del engine, y la auditoría (detección, efecto
  de caja, void, skip de posición abierta). ✔ (kill-criteria 2)

## Flag nuevo

`price_sanity_band_pct` (default `0.5`; `0` desactiva). Ver `docs/SETTINGS_REFERENCE.md`.

## Caveat

Si el histórico de referencia estuviera **simultáneamente** corrupto con el mismo
factor que el precio en vivo, el guard no podría juzgar la escala (fail-open). Es
un residual acotado: precio y histórico se traen por paths separados (rara vez
corruptos a la vez con el mismo factor), y la auditoría retroactiva + el backup
son el backstop. Las capas 1 y 2 usan el último close; la auditoría usa el close
del día del fill (más preciso para lo ya ejecutado).
