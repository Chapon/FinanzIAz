# Auditoría PROFUNDA de lógica de compras/ventas — 2026-06-17

Continuación de `docs/ops_logic_audit_2026-06-17.md`. Aquella fue *data-driven* (los
round-trips reales). Ésta traza cada hallazgo hasta el **código** del engine, confirma la causa
raíz a nivel `archivo:función` y suma problemas nuevos detectados leyendo la implementación.

Cuenta: *Sim Principal* (id=1), `strategy="analyze_single"`, `mode="manual"`,
`allocation_mode="signal_weighted"`, `max_positions=5`.

---

## Parte A — Causa raíz de los hallazgos previos

### A1. Los stops ATR ejecutan por debajo del nivel → es el peor exit
**Código:** `engine._compute_atr_forced_exits` → `gates.atr_exit_decision`; fill vía `engine._fill_trade`.

El stop se evalúa con `current_price = prices.get(ticker)` (el precio **vivo del scan**,
`_default_prices_provider` → `get_bulk_prices`), y la orden se llena al **mismo precio del scan**
(`_fill_trade(..., price=px)`), no en `stop_level`. `stop_level = avg_cost − stop_mult×ATR` solo se
usa como *gatillo* y queda escrito en el `reason`. Como el scan es discreto (corre after-hours /
una vez al día), cuando el precio ya está por debajo del nivel al momento de escanear, se sale a ese
precio más bajo.

Descomposición de los 3 `atr_stop` (gatillo vs fill; el slippage modelado es solo 5 bps):

| Trade | Nivel gatillo | Precio scan | Fill | Gap nivel→scan | Slippage |
|---|---|---|---|---|---|
| WMT #49 | 124.46 | 121.99 | 121.93 | **−1.98%** | −0.05% |
| KO #88 | 80.78 | 80.28 | 80.24 | −0.62% | −0.05% |
| MO #87 | 69.92 | 69.59 | 69.56 | −0.47% | −0.04% |

La pérdida "por debajo del stop" es casi toda **gap del scan discreto** (WMT abrió ~2% bajo el
nivel), no slippage. **Conclusión afinada:** no es un problema de slippage sino de que el stop no es
una orden real en mercado; es un *market-on-next-scan*. A menor frecuencia de scan, peor el gap.

### A2. (NUEVO, agrava A1) En modo manual el stop ni siquiera fija el precio del scan
**Código:** `engine.run_scan` (rama `acct.mode == "manual"` → `_create_pending_order`) + `engine.approve_order`.

En manual, **todas** las señales —incluidas las salidas ATR— se crean como orden **pending** y solo
se llenan cuando Chapa las **aprueba**. `approve_order` vuelve a pedir el precio actual
(`prices_provider([order.ticker])`) y llena ahí. Un "stop loss" que requiere aprobación manual y
llena al precio de la aprobación **no es un stop loss**: el objetivo (cortar la pérdida en
`avg_cost − 2×ATR`) queda a merced del lag de aprobación. En los 3 casos de A1 el fill ≈ precio del
scan (Chapa aprobó pronto), así que el lag no dominó *esta vez*, pero el mecanismo es un riesgo
latente y vuelve el `reason` engañoso (muestra el nivel del gatillo, no el precio real de salida).

### A3. El `buy_score` no predice el timing — y además NO escala el sizing
**Código:** `strategies.generate_trades_analyze_single` + `strategies._default_strength` + `analysis.technical.analyze`.

`buy_score = scores.get(t)`, que sale de `_default_strength("BUY", ml_probability)` = la
`ml_probability` calibrada de `analyze()` (clamp 0–1). corr(score, fwd5) ≈ 0.00 (n=21): la
probabilidad ML no anticipa el retorno a 5 días en esta muestra.

**Corrección al informe previo:** el informe decía "el score pondera el sizing". **No es así en esta
config.** `_VOL_SIZED_MODES = {VOL_TARGET, KELLY_FRACTIONAL}` (strategies.py:54). `signal_weighted`
**no** está en ese set, así que cae al `else` (strategies.py:428-431) = **slices iguales de cash**.
El score solo decide *qué* nombres entran (ranking), no *cuánto* recibe cada uno. Ver N1.

### A4. SELLs de señal sesgados al pesimismo — y cierran la posición ENTERA
**Código:** `strategies.generate_trades_analyze_single` líneas 306-319.

El SELL dispara cuando `analyze().overall_signal == "SELL"` (consenso ponderado de indicadores
técnicos, `technical.py`) y cierra `target_shares = float(pos.shares)` (**posición completa**, sin
scale-out). El número en `"analyze SELL (0.32)"` es `ml_probability`, no un "sell score" aparte.
Dato: 57% de las veces el precio subió tras vender (mean fwd5 +3.92%). El consenso de indicadores se
vuelve bajista cerca de pisos de corto plazo y revierte. La hysteresis (Gate 2b, T6.4) solo demora 3
días hábiles salvo score < 0.25; el exit-veto T-CAT-6 sigue OFF. Cerrar el 100% en un flip ruidoso
amplifica el costo (ver N4).

### A5. Churn — los gates nuevos lo cubren parcialmente
**Código:** Gate 3 anti-flap (engine.py:726), Gate 5 anti-whipsaw (765), Gate 5b anti-churn (778).

Las 7 re-compras ≤7d son de **mayo**, previas a T6.5 (anti-churn, 2026-06-10). Hoy: Gate 5 bloquea
re-BUY tras un ciclo perdedor; Gate 5b tras 3 ciclos en 10d; Gate 3 tras un SELL en los últimos
`anti_flap_minutes` (default 30 min). **Hueco residual (N5):** un único flip-flop *ganador* sell→buy
en scans separados por más de 30 min y que no llega al 3er ciclo **pasa todos los gates**. Confirmar
además que los flags estén ON en el `settings.json` de producción (no son verificables desde el repo).

### A6. MLTX domina las pérdidas — ADV cap OFF
**Código:** Gate 3b (engine.py:741) gobernado por `paper_adv_cap_pct` (default **0.0 = OFF**).

MLTX solo: −$2.642 (sin él, +$1.078 → +$3.720). Con `paper_adv_cap_pct=0` el recorte por liquidez
(Gate 3b) nunca corre, así que nada limitó comprar 1.457 acciones de un microcap en derrumbe.
Activar el cap > 0 y/o un filtro de calidad de universo.

---

## Parte B — Problemas NUEVOS detectados leyendo el código

### N1. `signal_weighted` se comporta como equal-weight (footgun de configuración) — MEDIA
La cuenta está configurada `allocation_mode="signal_weighted"` (valor válido del enum,
`AllocationMode.SIGNAL_WEIGHTED`), pero `analyze_single` solo trata como vol-sized a `vol_target` y
`kelly_fractional`. `signal_weighted`, `equal_weight` e `inverse_vol` caen todos al mismo `else` =
slices iguales. Resultado: Chapa cree que sizea por convicción y en realidad es equal-weight. No es
catastrófico (equal-weight es hasta más seguro que pesar por un score sin poder predictivo), pero la
config miente. **Fix:** o implementar la rama `signal_weighted`/`inverse_vol`, o validar/renombrar el
modo en la cuenta para que refleje lo que hace.

### N2. En manual, los BUY se dimensionan con plata que todavía no existe → expiran — MEDIA/ALTA
**Código:** `strategies.generate_trades_analyze_single` líneas 386-392: `available = account.cash +
est_proceeds`, donde `est_proceeds` son las **ventas estimadas de este mismo scan**.

En **auto** las SELL se llenan primero (orden `SELLs first`, engine.py:534) y la plata se libera
antes de las BUY → consistente. En **manual** SELL y BUY quedan ambas pending; si Chapa aprueba una
BUY antes que su SELL financiadora (o deja expirar la SELL), al aprobar la BUY no hay cash →
`_fill_trade` devuelve None → `approve_order` la marca **expired** (engine.py:1072-1076). Esto explica
parte de los **12 BUYs expirados**. Además, `est_proceeds` usa precios del scan, que pueden
sobreestimar al momento de aprobar → BUYs sobredimensionadas. **Fix:** en manual, sizear las BUY solo
contra `account.cash` real (sin contar proceeds de SELL no ejecutadas), o encadenar la aprobación
(aprobar SELL libera presupuesto para las BUY dependientes).

### N3. El "stop" es pending y puede expirar sin proteger — ALTA (consecuencia de A2)
Si una salida ATR (pending) no se aprueba en 24h, `reconcile_account` la marca **expired**
(engine.py:1379-1414) y la posición sigue abierta y cayendo. Un stop de protección que puede expirar
por inacción es un agujero de gestión de riesgo. **Fix:** auto-aprobar (auto-fill) las salidas de
riesgo aun en cuentas manuales, o alertar con prioridad.

### N4. Cierre 100% en flip de señal, sin scale-out — MEDIA
`analyze_single` siempre vende la posición entera ante `overall_signal=="SELL"`. Combinado con A4
(sesgo pesimista) y N1 (entradas equal-weight), un único flip ruidoso liquida toda la posición en su
peor momento. Un scale-out parcial (ej. vender 1/2 y mantener el resto con trailing) suavizaría tanto
el churn como el upside regalado.

### N5. Flip-flop ganador único pasa los gates anti-churn — BAJA
Ver A5: Gate 5 solo frena perdedores; Gate 5b recién al 3er ciclo; Gate 3 es de minutos. Un sell→buy
ganador en scans separados por >30 min no se bloquea. Bajo impacto, pero es el patrón que más
ensucia las métricas de timing.

---

## Severidad y orden sugerido

1. **N3 / A2** (ALTA) — las salidas de riesgo no protegen de verdad en manual. Auto-fill de exits ATR.
2. **A6** (ALTA por cola de pérdidas) — activar ADV cap / filtro de universo.
3. **N2** (MEDIA/ALTA) — sizear BUY contra cash real en manual; arregla BUYs expirados.
4. **A1** (MEDIA) — modelar el gap del stop / subir `atr_stop_mult` en baja-vol, o stop intradía.
5. **N1** (MEDIA) — alinear `signal_weighted` con lo que realmente hace.
6. **A4 / N4** (MEDIA) — scale-out parcial en los SELL de señal; reduce sesgo pesimista y churn.
7. **A3** (MEDIA) — validar o recalibrar la `ml_probability`; hoy no predice a 5d.

## Nota de método
Trazas verificadas leyendo `paper_trading/{engine,strategies,gates}.py`,
`analysis/technical.py`, `analysis/portfolio_backtest.py` (enum) y `config/settings_manager.py`.
Los valores *default* de los flags se leyeron del schema; los **efectivos** viven en
`~/.finanzias/settings.json` (fuera del repo) y conviene confirmarlos en Windows.
