# Compras y ventas: dónde se pierde y qué falta medir — 2026-11-23

Pedido de Chapa (2026-11-23): *«buscar formas de ser más efectivo con las compras y ventas»*.

**Es descriptivo, no un veredicto** (regla 2): ninguna cifra de acá decide nada ni toca la cuenta
viva. Lo que se puede hacer sale como las tareas **456**, **457** y **458**, cada una con su
kill-criteria fijado antes de correr.

## 1. Lo que ya se probó, y no se repite

Antes de proponer, se buscó cada perilla en el backlog. Desde julio se corrieron ~30 experimentos con pre-registro sobre compras y ventas:

| familia | tareas | resultado |
|---|---|---|
| qué comprar (ranking, modelo, factores) | 9, 21, 39, 385 | el `buy_score` rinde por debajo del azar; ningún reemplazo pasa |
| señales nuevas de entrada | 11 (A y B), 12, 13, 45, 49 | NO-SHIP o sin poder |
| cuándo vender (stops, trailing, target, señal) | 7, 23, 26, 26b, 34, 37/167, 47, 51, 54, 170, 219 | la rejilla de salidas quedó **cerrada** (170) |
| cuánto poner (sizing) | 10, 122, 123 | NO-SHIP |
| exposición por régimen | 8, 20, 115, 121, 124 | el corte binario destruye; el escalado a 0,25 queda por **preferencia de riesgo** de Chapa (124) |
| drawdown de cuenta | 4 (R1) | NO-SHIP |

Este doc no propone ninguna variante de esas perillas.

## 2. La comparación que faltaba: la estrategia contra un pasivo del mismo riesgo

Todos los experimentos de arriba comparan una variante **contra la estrategia viva**. Ninguno
comparó la estrategia viva **contra no operar**. Sobre las fechas en que opera la estrategia
(2017-09-08 → 2026-09-09, después de las 250 ruedas de calentamiento del cohorte 2016-09-12 →
2026-09-09) y el mismo universo (los 126 de `data/harness_universe_live_acct2.txt`):

| | crecimiento anual | Sharpe | caída máxima | de dónde sale |
|---|--:|--:|--:|---|
| **Estrategia viva** (`soff_t2.0`, 10 slots) | **8,78%** | **0,55** | **28,4%** | T170 / T219 (`portfolio_sim`) |
| Mismas salidas y rotación, compras al azar | 10,87% | 0,64 | 28,7% | `AZAR_MISMA_TASA` de la T219 |
| Universo en partes iguales, rebalanceo mensual | 17,27% | 0,96 | 36,2% | medido hoy |
| SPY | 15,19% | 0,85 | 33,7% | medido hoy |
| **60% SPY + 40% caja** (sin interés) | **9,23%** | 0,86 | **20,9%** | medido hoy |
| **80% SPY + 20% caja** (sin interés) | **12,24%** | 0,85 | **27,4%** | medido hoy |

> **Corregido el 2026-11-23 con la tarea 456.** La primera versión de esta tabla medía SPY, el
> universo y las mezclas desde el 2016-09-12, y la estrategia recién opera desde el 2017-09-08. Con
> las mismas fechas: SPY 15,39% → 15,19%, el universo 17,73% → 17,27%, 60/40 9,33% → 9,23% y 80/20
> 12,38% → 12,24%. La fila de 80% universo + 20% caja se sacó (en la 456 el universo con caja va con
> su propia `w`). Ninguna conclusión cambia.

**Lo que dice:**

- **La estrategia queda dominada por SPY con caja.** 60/40 rinde más (9,23% contra 8,78%) con
  bastante menos caída (20,9% contra 28,4%). 80/20 rinde 3,5 puntos más por año con un punto
  menos de caída. La caja cobra 0% en el cálculo; con la tasa de las letras del Tesoro la diferencia
  sería mayor. **SPY no tiene sesgo de supervivencia**, así que esto no se lo infla el universo.
- **Se puede descomponer, aproximadamente, dónde se va el rendimiento:**
  - **Comprar** con la señal en vez de al azar cuesta ~2,1 puntos por año (8,78% contra 10,87%), lo
    mismo que midieron la 21 y la 39.
  - **Vender y rotar** con las reglas vivas (trailing de 2 ATR, target de 4 ATR, venta por señal a
    los 3 días, tenencia media de 7,9 días) cuesta ~6,4 puntos más, contra quedarse con el universo
    (10,87% contra 17,27%).

  El grueso de la pérdida está en **las ventas y la rotación**, no en las compras. Este número
  compara dos simuladores distintos, así que es una cota y no una medición; la 456 lo mide dentro
  de uno solo.
- **Por qué no apareció antes.** Los experimentos que bajaban la rotación (T7 `C_A4`, la 219 con
  `age10`/`age20`, la 170 con `soff_toff`) subían el crecimiento entre 3 y 8 puntos y morían por
  el mismo criterio: *caída máxima no peor que la viva*. Ese criterio protege una ventaja de
  caída que **se consigue más barata con caja**. Esto no reabre esos veredictos (regla 2: no se
  re-decide con números ya vistos). Es una pregunta nueva y se pre-registra aparte: la 456.

## 3. Cómo está la cuenta hoy

- **60% en caja** ($29.912 sobre $49.523). Desde el 2026-11-20 el mercado está en risk-off (SPY
  por debajo de su media de 200 ruedas). Cada compra nueva entra a ×0,25 por el régimen y, encima,
  a ×0,59 promedio de noviembre por el overlay de volatilidad: ~15% de un slot normal. Con los 10
  slots ocupados por posiciones de $517 a $6.065, la caja queda quieta hasta que algo se venda.
- **En vivo le va mejor que a SPY:** desde el alta (2026-06-20), la cuenta va **−0,91%** y SPY
  **−3,00%**. Con el mercado cayendo, la caja protegió, que es lo que el escalado tiene que hacer. Son
  cinco meses y no alcanzan para afirmar nada en ninguna dirección.
- **Lo de la semana que no es un defecto:** LRCX se compró a las 14:47 del 20/11 y se vendió a las
  15:47 porque la venta tenía puntaje 0,18, menor al `paper_signal_sell_bypass_score` de 0,25, que se
  saltea el freno de 3 días a propósito. Las ventas de las 03:43 UTC son el `False` deliberado de
  `paper_enforce_market_hours` (tarea 292, decisión de Chapa, sin ventaja de mirar el futuro). Que
  el tamaño dependa de la caja dividida por los slots libres es lo que modela el harness, y la
  auditoría del 2026-09-02 ([D-4]) ya lo había descartado como desvío.

## 4. Dos frenos prendidos que nunca se midieron

- **El overlay de volatilidad de cartera** (`vol_overlay_enabled: true`,
  `vol_target_portfolio_annual: 0.12`). Achica **toda** compra nueva cuando la σ del libro pasa de
  12% anual. En el log desde septiembre se aplicó en **105** tandas, con un factor medio de
  **0,74** (0,78 en septiembre, 0,89 en octubre, 0,59 en noviembre). La 94 lo **declaró** como
  desvío porque el harness no lo modela, pero **nadie lo midió**. Sale de la T10, que cerró NO-SHIP
  el sizing por volatilidad. Es una regla que decide tamaños todos los días sin backtest, o sea lo
  contrario de la regla 2. → **457**.
- **El bloqueo de compras cerca de los balances** (Gate 6, `earnings_blackout_days: 2`). Frena una
  compra dentro de los 2 días de un balance. El 15,8% de los round-trips caen cerca de uno (2026-06-25).
  La literatura apunta en contra (*earnings announcement premium*: Frazzini y Lamont 2007, Barber y
  otros 2013 encuentran que las acciones rinden de más alrededor del anuncio), así que el bloqueo
  puede estar costando. **La 96 lo dejó sin medir porque «no hay fechas de earnings point-in-time a
  10 años», y eso es falso:** `yf.Ticker(t).get_earnings_dates(limit=48)` devuelve **49
  trimestres** de KO (desde 2014-10-21) y de NVDA (desde 2014-11-06), probado hoy. La fecha de un
  balance es un dato duro, que no se revisa, y la empresa la anuncia semanas antes. → **458**.

## 5. Las tareas, en orden

1. **456 — ACTIVO-CONTRA-PASIVO-DE-IGUAL-RIESGO.** Dentro de `portfolio_sim`, la estrategia viva
   contra SPY + caja con la proporción fijada **antes** (misma caída máxima en la primera mitad,
   evaluada en la segunda; y en los cinco folds de la T170). Va primera porque decide si las
   otras dos importan: si el pasivo gana, la pregunta pasa a ser qué hacer con la cuenta 2, y eso
   **lo decide Chapa** (cuenta pasiva nueva al lado, convertir la 2, o seguir igual sabiendo el
   costo).
2. **457 — VOL-OVERLAY-SIN-VALIDAR.** Modelar el overlay en el simulador y medirlo prendido contra
   apagado y contra su equivalente en caja constante. Va antes que la 458 porque recorta **todas**
   las compras, todos los días.
3. **458 — EARNINGS-BLACKOUT-SIN-MEDIR.** Corregir el texto de la 96, juntar las fechas de los 126 y
   modelar el Gate 6. Muestra grande: unos 5.000 balances en diez años.

## Límites

- **Una sola década, y alcista.** 2016–2026 premió a quien se quedó comprado. En un mercado de
  lado, la ventaja del pasivo se achica. La 456 lo mide por folds anuales para ver si depende de un
  año.
- **El universo es el de hoy:** las cifras del universo en partes iguales tienen sesgo de
  supervivencia, y el comprar-y-mantener lo aprovecha más que una estrategia que rota cada 8 días.
  Por eso la comparación central es contra **SPY**.
- **Dos simuladores.** La estrategia sale de `portfolio_sim` (con costos, fill honesto y gates de
  re-entrada). El pasivo sale de la función `simular` de la T385 (costo de 0,064% sobre lo
  operado) y de una mezcla con caja rebalanceada a fin de mes. Los dos usan cierres ajustados por
  dividendos. La 456 lo pone todo en un mismo simulador.
- **El harness no modela el overlay ni el Gate 6**, que en vivo bajan todavía más la exposición.
  La estrategia real está más lejos del pasivo que lo que dice la tabla, no más cerca.

## Instrumento

- Cohorte: `load_bars_signals(LIVE_UNIVERSE_FILE, "10y", 250)`, 126 tickers, 2.512 barras
  (2016-09-12 → 2026-09-09), con los artefactos atrasados al 2026-09-09 igual que en la T170 y la
  T219.
- Universo en partes iguales: `simular()` de `scripts/run_cartera_calidad_valor_t385.py`, con el
  último cierre arrastrado. Rebalanceo mensual, anual y nunca: 17,73%, 18,14% y 21,86%.
- SPY: `data/parquet/SPY__10y__1d.parquet` (arranca el 2016-10-03).
- Mezclas: proporción constante en SPY o en el universo, caja al 0%, rebalanceo el primer día hábil
  de cada mes, con el mismo 0,064% sobre lo operado.
- **Validación del instrumento:** la caída máxima de SPY da 33,7%, la del COVID. El universo con
  rebalanceo anual da 18,14%, cerca del +17,60% de la T385, que arranca en abril de 2017 y
  rebalancea en abril.
- Cuenta viva: copia de `finanzias.db` con la API de backup desde `mode=ro`
  (`paper_equity_snapshots`, `paper_orders`, `paper_positions` de la cuenta 2). Overlay: las líneas
  `portfolio vol overlay (analyze_single)` de `~/.finanzias/finanzias.log` (cubre desde septiembre).

## Resultado de la 456 (2026-11-23): NO DECIDIBLE

`docs/activo_pasivo_t456_2026-11-23.md`. En un solo simulador y fuera de muestra (2021-08 →
2026-07), la estrategia de la cuenta 2 (con el escalado por régimen) rinde **2,06%** anual y SPY +
caja con la misma caída (w = 0,65, fijada antes del test) rinde **8,45%**: +6,40 pp, el pasivo gana
4 de 5 años y cae menos (16,4% contra 22,8%). **El intervalo del bootstrap pareado va de −1,61 a
+14,76 pp**, así que el criterio congelado no se cumple y no se cambia nada. Deja la **459**: el
escalado por régimen cuesta 1,46 pp de CAGR bajo la política viva, y la preferencia de la 124 se
declaró con 0,29 pp.
