# Pre-registro — VOL-OVERLAY-SIN-VALIDAR (tarea 457) · 2026-11-25

**Congelado antes de escribir el runner.** Nada de lo que sigue se cambia después de correr; si
algo tiene que cambiar, va como enmienda fechada y declarada antes de leer ningún Δ.

Origen: `docs/compras_ventas_efectividad_2026-11-23.md` §4. El overlay de σ de cartera
(`vol_overlay_enabled: true`, `vol_target_portfolio_annual: 0.12`) achica **todas** las compras
nuevas de la cuenta 2 cuando la σ anualizada del libro que va a quedar pasa del 12%: en el log,
desde septiembre, 105 tandas con factor medio 0,74 (0,59 en noviembre). Sale de la T10, que cerró
NO-SHIP el sizing por volatilidad, y **nunca tuvo backtest**: la 94 lo dejó declarado como
desvío.

## 0. Lo que ya se vio, declarado

Nada del overlay: el harness no lo modelaba, así que ningún número suyo existe. Sí se vieron, y
condicionan el diseño:

- **El costo (468):** con el 0,15% por lado de `CostModel()`, el escalado por régimen daba la
  conclusión opuesta a la que da con el ~0,063% del vivo. El gate se mide con
  `live_cost_model()`.
- **La tajada (464):** con un factor < 1, el simulador de antes agrandaba cada compra del día con la
  caja que no gastaba la anterior. El overlay es un factor por scan, así que se mide con
  `tajada_del_dia=True`.
- **El escalado por régimen (459, 464, 468):** compra caída a un precio que depende del costo y del
  sizing. El overlay también es una forma de comprar caída, y por eso la vara no es sólo «con contra
  sin», sino también **la caja constante que da la misma exposición** (§3).

## 1. La pregunta

¿El overlay mejora el Sharpe de la estrategia **fuera de muestra**, y lo hace mejor que tener la
misma exposición media en caja constante?

La carga de la prueba es **a favor de apagarlo**: es un mecanismo que corre todos los días y nunca
se midió. Para que **se quede** hacen falta **las tres** condiciones del §4.

## 2. Config

La de la T170, sin cambios salvo costo y tajada: 126 tickers (`data/harness_universe_live_acct2.txt`,
huella `POPULATION_LIVE_ACCT2.tickers_fp`, verificada), ventana del cohorte `2016-09-12..2026-09-09`
(con `--allow-stale-artifacts`), entradas `analyze BUY` PIT, 10 slots, `equal_weight`,
`cap_days=250`, `eval_mode=touch`, `fill_mode=decision`, gates de re-entrada modelados, hard stop
**apagado** (`NO_STOP`), trailing 2,0 ATR, TP 4,0 ATR, la salida de la T219 (`T219_BASELINE`),
capital 50.000, caja al 0%. **Costo: `live_cost_model()`** (~0,063% por lado). **Tajada por día.**

**El overlay modelado** (`simulate_portfolio(vol_overlay=OverlayDeVolatilidad(bars_by))`): una vez
por día con compras, la σ anualizada del libro que queda —lo tenido a mercado, sin lo que sale ese
día, más las compras del día **antes** del régimen— con las funciones del motor
(`returns_frame` con 60 retornos diarios, `apply_portfolio_vol_overlay`, `compute_vol_overlay`),
objetivo `LIVE_VOL_TARGET_ANNUAL` (12%), da un factor `min(1, 0,12 / σ)` que multiplica a todas las
compras del día y se compone con el del régimen. Paridad con `_apply_vol_overlay_to_buys` fijada en
`tests/test_vol_overlay_t457.py`.

**Lo que el modelo no replica, y su dirección:**

- **Un scan por día.** El vivo escanea cada ~6 minutos y cada scan recalcula el factor con lo que
  ya compró ese día; el simulador decide una vez, al cierre. Dirección: desconocida.
- **Las compras que frena un gate.** En vivo, un pick frenado por un gate entra igual en la σ del
  scan (el overlay corre antes que los gates del motor); en el simulador, el frenado no entra y su
  lugar pasa al siguiente. Es la tarea 471.
- **La marca a mercado** es la de `_build_equity_curve`: invertido × cierre / cierre de entrada, que
  ignora las ventas parciales de la salida hasta el cierre del ciclo.
- **El Gate 6** (tarea 458) sigue sin modelarse.

## 3. Los brazos (fijos)

| brazo | qué es | rol |
|---|---|---|
| `sin_overlay` | la config del §2 | **el del gate** (base) |
| `con_overlay` | la config del §2 con el overlay modelado | **el del gate** (candidato) |
| `caja_equivalente` | `sin_overlay` mezclado con caja al 0% a proporción constante `w`, rebalanceado el primer día hábil de cada mes (`mezcla_constante` de la 456, con el costo del vivo sobre lo operado), con **`w = exposición media de con_overlay / exposición media de sin_overlay`** (`exposicion_media` de la 456, sobre la muestra completa) | **el del gate** (la vara) |
| `sin_overlay_regimen`, `con_overlay_regimen` | los dos primeros más el escalado por régimen a ×0,25 (`make_entry_filter(mode="scale")` sobre `SPY__max__1d`): el segundo es **lo que corre la cuenta 2** | descriptivo |
| `sin_overlay_harness` | `sin_overlay` con `CostModel()` | sanity de reproducción (§5) |

El gate se mide **sin régimen** porque así lo fija la tarea (*«el resto como la T170»*) y porque la
decisión del factor de régimen está pendiente con Chapa. El marco de la cuenta, con régimen, va en
el descriptivo, y si contradice al gate se dice.

Los brazos se corren una sola vez, de punta a punta, y se cortan: no hay nada que entrenar.

## 4. El gate (fuera de muestra: los cinco folds de test de la T170, 2021-08-01 → 2026-07-31)

| | condición |
|---|---|
| **C1** | ΔSharpe OOS (`con_overlay` − `sin_overlay`) **≥ +0,05**, con `sharpe_annual` sobre cada curva cortada al tramo |
| **C2** | bootstrap pareado por bloques sobre los retornos diarios OOS (bloque 20, 2.000 resamples, semilla 12345; `paired_block_bootstrap(stat=sharpe_compuesto)`): **IC95% inferior del ΔSharpe > 0** |
| **C3** | Sharpe OOS de `con_overlay` **>** Sharpe OOS de `caja_equivalente` |

Las dos curvas del gate se comparan sobre **las fechas que comparten** dentro del tramo.

**Lectura, congelada:**

- **«EL OVERLAY SE QUEDA»**: C1, C2 y C3 juntas. Se documenta y no se toca nada.
- **«NO-SHIP: EL OVERLAY RESTA»**: ΔSharpe OOS **≤ −0,05** e IC95% superior **< 0**.
- **«NO-SHIP: NO SE DISTINGUE»**: cualquier otra combinación.
- Con cualquiera de los dos NO-SHIP, **apagarlo lo decide Chapa** (`vol_overlay_enabled=false`, con
  la app cerrada): pasa a *Acciones manuales* con los números, y no se toca `settings.json`.

**Lo que se espera, escrito antes de correr.** Escalar todas las compras por el mismo factor no
debería mover el Sharpe por sí solo: lo mueve sólo si la σ alta de hoy anticipa retornos peores por
unidad de riesgo. La caja constante, en cambio, deja el Sharpe casi igual por construcción. Lo más
probable es **«NO SE DISTINGUE»**: un ΔSharpe chico con un IC que cruza el cero.

## 5. Sanity (si uno falla, la corrida es INVÁLIDA y no hay veredicto)

1. **Reproducción:** `sin_overlay_harness` da **8,78% / 0,55 / 2.531** (la T170), con las
   tolerancias de la T219 (`reproduce_t170`). Es una referencia **externa** a esta corrida.
2. **Las compras previstas son las tomadas:** en `con_overlay` y `con_overlay_regimen`,
   `n_overlay_desalineado` es a lo sumo el **1%** de los días con compras. Si no, el factor se
   calculó sobre otro libro.
3. **El overlay muerde y no siempre igual:** en `con_overlay`, la fracción de días con compras con
   factor < 1 está entre el **5%** y el **100%**, y el factor no es el mismo todos los días.
4. **`w` queda adentro:** `0 < w < 1`. Con `w = 1` el overlay no achicó nada y no hay vara.
5. **Calendario:** las fechas comunes cubren al menos el **99%** de cada curva en el tramo OOS.

## 6. Descriptivo obligatorio (no decide)

Muestra completa (crecimiento, Sharpe, caída, exposición media, trades) de todos los brazos; los
cinco folds, ΔSharpe y ΔCAGR uno por uno; el bootstrap del ΔCAGR OOS (el `stat` de siempre); el
factor del overlay —media, percentiles 10/50/90, fracción de días con factor < 1, por año— al lado
del 0,74 del log en vivo (que es otro período, y no se compara como número); el marco de la cuenta
(con régimen); y el overlay contra la caja constante **a la misma caída** (`caja_hasta_la_caida` de
la 464), que es la otra forma de preguntar si compra caída barata.

## 7. Lo que no hace

No toca la cuenta viva ni ningún setting. No re-decide la T10, el régimen ni la salida. No elige
otro objetivo de σ después de ver el resultado: un barrido del 12% sería otra tarea, con su propio
pre-registro.
