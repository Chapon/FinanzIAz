# Auditoría — desvíos — 2026-10-02

Tarea **275**. READ-ONLY. Kill-criteria congelado en `docs/auditoria_tanda_killcriteria_2026-10-02.md` §8–12 (`desvios`).

## 1. Alcance real

**Mirado:**
- **`run_scan` entero** (`paper_trading/engine.py:792-1570`), que la 2026-09-30b dejó afuera: cada paso y cada gate (horario de mercado, holding mínimo, histéresis 2b, veto de catalysts 2c, anti-flap, tope ADV 3b, operación mínima, anti-whipsaw, anti-churn 5b, blackout de earnings, segunda opinión, dividendos, la 256) y **cada perilla que lee**. Contra eso:
  - las **20 claves** de `deviations_keyed`, sacadas en ejecución con `inspect` (un primer `grep` de una línea veía 5 y no las multilínea);
  - la clasificación del guard de la 185 (`tests/test_espejos_direccion_faltante_t185.py`), que descubre por AST cada clave del camino vivo y exige espejo o motivo.
- **La 256:** el colector es un `ContextVar` que, sin colector abierto, no hace nada, así que el harness no cambia.

**NO mirado:**
- El precio de **entrada** del harness contra el vivo, re-derivado desde cero. Motivo: es el eje de la T33 (look-ahead del fill) y de seis corridas previas del área. Se miró sólo que `portfolio_sim` recorta la entrada por los fees (la 123).

## 2. Hallazgos

Ningún hallazgo **nuevo** en esta corrida. Dos desvíos sin declarar salieron hoy en otras áreas y ya tienen tarea:
- **Splits:** el motor vivo no ajusta posiciones, y el harness corre sobre series split-neutrales → la **262** (`docs/auditoria_cuentas_2026-10-02.md` [G-1]).
- **Frecuencia de evaluación:** `barrier_eval` afirma ~15 min «más cerca de touch», y hubo 22 días hábiles sin scan → la **265** (`docs/auditoria_operacion_2026-10-02.md` [H-1]).

## 3. Barrido limpio en lo demás

- **Perillas de `run_scan`:**
  - las de los gates 2b (histéresis: `LIVE_SIGNAL_SELL_MIN_AGE_BDAYS`, `LIVE_SIGNAL_SELL_BYPASS_SCORE`, espejadas desde la 232 y modeladas por `scaleout_replay`), 5/5b (`reentry_gates`), 3b (`adv_cap`), 6 (`earnings_blackout`) y la segunda opinión (`second_opinion`) tienen espejo o clave;
  - `paper_min_holding_minutes`, `paper_anti_flap_minutes` y `paper_enforce_market_hours` están clasificadas *«NO_MODELABLE: intradía»* en el guard de la 185, con motivo;
  - `paper_min_trade_dollars` (en vivo **$250**) tiene su clasificación escrita en el mismo guard (`:141`).
- **Dividendos:** clave `dividendos`, con el par motor↔harness desde la 222.
- **La 256:** sin efecto del lado del harness.

## 4. Mapeo hallazgo → tarea

Sin hallazgos nuevos. Los dos de esta forma ya tienen tarea: la 262 y la 265.
