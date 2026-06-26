# Backlog — FinanzIAs

Lista **operativa** de tareas (el qué sigue). El por qué estratégico vive en `docs/roadmap_v3_2026-06-09.md`; la causa raíz de cada hallazgo está trazada a `archivo:función` en `docs/ops_logic_deep_audit_2026-06-17.md` (auditoría profunda) y `docs/ops_logic_audit_2026-06-17.md` (data-driven). Reglas de trabajo: ver `CLAUDE.md` y la skill `finanzias-conventions`.

**Contrato para Claude Code:** al empezar una sesión, leé este archivo. Al poner una tarea en marcha, movela a *En curso* (máx 1). Al cerrarla (suite Windows verde + commit) movela a *Hecho reciente* con el hash. Toda tarea que toque decisiones de trading se valida por harness con **kill-criteria pre-registrado** (skill `backtest-replay-harness` / agente `backtest-runner`); si no supera el umbral, se documenta y NO se shipea.

**Config viva (Sim Principal, id=1):** `strategy="analyze_single"`, `mode="manual"`, `allocation_mode="signal_weighted"`, `max_positions=5`, modo kill_only. Los flags *efectivos* viven en `~/.finanzias/settings.json` (fuera del repo) — varias tareas requieren confirmarlos/setearlos en Windows.

**Política de decisión (orden de Chapa 2026-06-25):** ante una duda entre una opción rápida y una más costosa, elegir **siempre la que dé mejor calidad de datos / mayor ganancia esperada** del trading. Por eso varias tareas eligen el camino más completo (auto-fill real de stops, sizing contra cash real, validación walk-forward) en vez del parche mínimo.

_Última actualización: 2026-06-26._

---

## En curso (WIP, máx 1)

- _(vacío)_

## Acciones manuales pendientes (Chapa, en Windows — fuera del repo)

- **Setear `earnings_blackout_days: 2`** en `~/.finanzias/settings.json` (decisión data-driven 2026-06-25; dejar `earnings_blackout_block_sells: false`). Ver evidencia en *Hecho reciente* / `docs/earnings_blackout_replay_2026-06-25.md`.
- **Verificar ADV cap** en el próximo scan: el flag ya está en `0.05`; confirmar que aparece el warning de trim en un BUY ilíquido y que un BUY normal NO se recorta.
- **Limpiar la cache corrompida (bug B4):** `python scripts/purge_synthetic_cache.py --apply` (borra las 7 filas sintéticas AAPL/MSFT 1y + basura), reanalizar MSFT/AAPL, correr la suite y commitear el fix `tests/test_historical_batch.py` + `scripts/purge_synthetic_cache.py`.

## Próximo (priorizado — el de arriba es el siguiente)

### 1. Recalibrar / decidir continuidad de los stops ATR  ·  ref A1 · severidad MEDIA
- **Qué:** primero la pregunta correcta —**¿los stops ATR rinden con fills honestos, y a qué múltiplo?**— no asumir que solo falta subir el multiplicador.
- **Por qué:** el "ejecuta por debajo del nivel" es casi todo **gap de scan discreto**, no slippage (WMT abrió ~2% bajo el nivel; slippage modelado solo 5 bps). El stop es un *market-on-next-scan*, no una orden real en mercado. A menor frecuencia de scan, peor el gap.
- **Dónde:** `engine._compute_atr_forced_exits` → `gates.atr_exit_decision`; flags `atr_stops_enabled`/`atr_stop_mult`/`atr_period`/`atr_trail_enabled`.
- **Gate previo:** ✅ CONFIRMADO 2026-06-25 — `atr_stops_enabled: true`, está vivo (no es exploración). **Parámetros actuales = baseline a batir:** `atr_stop_mult=2.0`, `atr_tp_mult=4.0`, `atr_period=14`, `atr_trail_enabled=true`. La recalibración compara contra estos valores.
- **Decisión de calidad (mayor ganancia):** evaluar en el harness, todas con fill modelado, estas variantes: (a) sin stops ATR, (b) múltiplo actual, (c) múltiplo más alto en baja-vol, (d) **chequeo intradía** del stop usando datos intradía (mejor calidad de fill que el EOD; ver nota yfinance: 1m≈7d, 1h≈730d de histórico — limitado, evaluar si alcanza). Preferir la variante que más mejore el P/L neto aunque sea más trabajo.
- **Kill-criteria (pre-registrado, estilo T6.1):** se shipea la variante que mejore el P/L total **≥ +2 puntos** sobre el real **sin** empeorar el max DD más de **1.5×**. Si gana "sin stops", se apagan. Si ninguna pasa, se documenta y quedan como están.
- **Depende de:** ✅ desbloqueada — la tarea ① (auto-fill de risk-exits, commit `8ff57e1`) ya está, así que el comportamiento de los stops live coincide con lo backtesteado.

### 2. Alinear `signal_weighted` con lo que realmente hace  ·  ref N1 · severidad MEDIA
- **Qué:** hoy la cuenta dice `allocation_mode="signal_weighted"` pero ese modo **no** está en `_VOL_SIZED_MODES` (`strategies.py:54`), así que cae al `else` = **slices iguales de cash** (equal-weight). La config miente.
- **Por qué:** Chapa cree que sizea por convicción y en realidad es equal-weight. No es catastrófico (equal-weight es más seguro que pesar por un score sin poder predictivo, ver tarea 4), pero hay que cerrar la mentira de config.
- **Dónde:** `strategies.generate_trades_analyze_single` (ramas de allocation, líneas ~409-435) + `_compute_target_weights` en `analysis/portfolio_backtest.py` + enum `AllocationMode`.
- **Decisión de calidad (mayor ganancia):** implementar sizing **basado en riesgo** real en vez de equal-weight crudo: activar `inverse_vol` o `vol_target` (peso ∝ 1/σ), que es lo que hacen los sistemas pro (risk parity / vol targeting) y NO depende del buy_score sin alpha. Validar por harness contra equal-weight antes de cambiar el modo de la cuenta. Si no mejora, renombrar la cuenta a `equal_weight` para que la config sea honesta.
- **Kill-criteria:** la variante de sizing por riesgo se adopta si mejora Sharpe/P-L sin subir DD > 1.5×; si no, se deja equal-weight (renombrado).

### 3. Scale-out parcial en los SELL de señal  ·  ref A4/N4 · severidad MEDIA
- **Qué:** dejar de cerrar el 100% de la posición ante cada flip de señal; vender una fracción y mantener el resto (idealmente con trailing).
- **Por qué:** 57% de las veces el precio subió tras vender (mean fwd5 **+3.92%**): el consenso de indicadores se vuelve bajista cerca de pisos de corto plazo y revierte. Cerrar todo en un flip ruidoso regala upside y amplifica el churn. Es el sesgo pesimista confirmado en SELLs.
- **Dónde:** `strategies.generate_trades_analyze_single` líneas ~306-319 (hoy `target_shares = float(pos.shares)`, posición entera).
- **Decisión de calidad:** scale-out parcial (ej. vender 1/2 al flip, mantener 1/2 con trailing stop ATR) — práctica estándar para no liquidar en el peor momento. Parametrizar la fracción.
- **Kill-criteria:** replay comparando cierre 100% vs scale-out 50%+trailing: se shipea si mejora el P/L ≥ +1.5 pts sin empeorar DD > 1.5×.
- **Sinergia:** se beneficia de la hysteresis ya activa (Gate 2b, T6.4) y del exit-veto T-CAT (sigue OFF).

### 4. Validar (o degradar a display) la `ml_probability` / buy_score  ·  ref A3 · severidad MEDIA
- **Qué:** el `buy_score` = `_default_strength("BUY", ml_probability)` = la probabilidad ML calibrada de `analyze()`. corr(score, fwd5) ≈ **0.00** (n=21): no anticipa el retorno a 5 días en esta muestra. Hoy decide *qué* nombres entran (ranking), no *cuánto* (el sizing no lo usa, ver tarea 2).
- **Por qué:** si el score no tiene alpha, rankear por él elige los nombres equivocados. El problema real no es "sacarlo del sizing" (ya está fuera) sino **si debe seguir eligiendo entradas**.
- **Dónde:** `analysis.technical.analyze` (genera `ml_probability`), `strategies._default_strength`, ranking en `generate_trades_analyze_single`.
- **Decisión de calidad (mayor ganancia):** validación **walk-forward out-of-sample** seria (no in-sample, n=21 es poco) con `scripts/harness_walkforward.py`: ¿el ranking por ml_probability bate a un ranking neutro/aleatorio en P-L? Si tiene alpha OOS → recalibrar y mantener. Si no → degradar a display-only y elegir entradas por otra señal (momentum/calidad) validada. Preferir la validación rigurosa aunque lleve más tiempo.
- **Kill-criteria:** mantener el score en selección solo si bate al baseline neutro en walk-forward por un margen pre-registrado; si no, se reemplaza la señal de selección.
- **Nota de datos:** n=21 round-trips es muestra chica → cuidado con sobreajustar. Acumular más historia mejora esta decisión (ver sección Calidad de datos).

---

## Bugs / robustez de datos (del log de runtime 2026-06-25)

### B2. Símbolos muertos en el universo no se saltean (K / Kellanova) · severidad MEDIA
- **Síntoma:** `Quote not found for symbol: K` y `$K: possibly delisted (period=2y)` repetido varias veces en una sola corrida.
- **Causa probable:** K falla pero se reintenta dentro de la misma corrida — el skip de `failed_tickers` no lo cubre, o K está en una lista que lo bypassea, o el símbolo está mal (Kellanova cotiza como K en NYSE pero yfinance lo 404ea).
- **Fix:** garantizar que un 404 se registre en `failed_tickers` y se saltee en el resto de la corrida (y en bulk fetch); revisar si K se remueve del universo o se mapea. Verificar el flujo de skip end-to-end.

### B3. El scan no consigue precio de large-caps reales + cascada de hard-timeouts · severidad ALTA (investigar)
- **Síntoma (scan 02:45):** `$JPM/$KLAC/$LOW/$LMT: possibly delisted; no price data found (period=1y/5d)` —NO están deslistadas— seguido de varios `Hard timeout (15.0s) running _do_fetch`.
- **Riesgo:** si el scan diario corre con precios faltantes de tickers reales, las decisiones de trading operan sobre datos incompletos/stale. Es lo más peligroso del log.
- **Hipótesis a investigar:** (a) rate-limiting de Yahoo tras el harvest+classify largo (01:31-02:10) justo antes del scan; (b) fallout del KeyError de B1 ensuciando la sesión yfinance; (c) crumb/401 resurgiendo. Con 52 tickers × 15s de timeout el scan se vuelve lentísimo además.
- **Acción:** loguear cuántos tickers fallan por scan; hacer el scan resiliente (saltear fallidos rápido, no 15s c/u); reproducir y ubicar la causa. Evaluar bajar el timeout y/o paralelizar con cap. Para decisiones de trading: si faltan precios de tickers con posición, NO operar a ciegas.

### B4. Conftest guard: ningún test debe escribir la `finanzias.db` real · severidad MEDIA (prevención)
- **Contexto:** `tests/test_historical_batch.py` escribió frames sintéticos (rampa 100→104, 2026-01-01..05, vol 1.000.000) en la DB de producción → rompió **AAPL/MSFT 1y** en la pestaña Análisis (2026-06-25). Fix puntual ya aplicado (mock de `_write_historical_cache` en su fixture `_isolate`) + `scripts/purge_synthetic_cache.py` para limpiar las 7 filas. **Sin commitear (pendiente desde Windows).**
- **Tarea:** red de seguridad **autouse** en `tests/conftest.py` que impida a CUALQUIER test escribir la `finanzias.db` real (apuntar `ENGINE` a DB temporal por sesión salvo opt-in explícito, o no-op de los writers de cache por default). Previene toda la clase de bug. Validar que no rompe tests que dependen de leer/escribir cache real.

### Observaciones (ruido de log, no crashes)
- **XGBoost inestable:** el warning `val_acc std >8% > 8%` se dispara para la mayoría de los tickers en cada arranque → el modelo es ampliamente inestable. Refuerza la **tarea 4** (validar/degradar la `ml_probability`). Considerar bajar el ruido del log (a debug) o revisar el umbral.
- **GARCH out-of-valid-region (α+β=1, borde IGARCH):** fits degenerados frecuentes → estimaciones de vol poco confiables que alimentan el vol_overlay (que escaló buys ×0.56 con σ=21.3% vs target 12%). Revisar si el overlay sizea con vol basura; al menos bajar el log a debug.

---

## Track paralelo — Fair value en Analysis (DISPLAY, no a sizing/gates)

Mostrar **precio actual / fair value propio / target consenso** lado a lado para juzgar upside. 6 sub-tareas en la skill `fair-value-feature`. Entra como display-only; NO se cablea a sizing ni gates (misma razón que la tarea 4: no meter señales sin validar en decisiones).

**Decisión de datos (calidad sobre comodidad):** para el fair value propio usar **EDGAR XBRL** (estados financieros — hechos contables duros, point-in-time) como fuente primaria de EPS/márgenes, NO los snapshots móviles de yfinance que pueden estar stale. El target de consenso de yfinance se muestra solo como referencia, marcado como dato de menor confiabilidad (es un snapshot, no histórico point-in-time). Evitar DCF completo en v1 (inputs forward-looking de baja calidad gratis; mismo muro que T-CAT-5b).

---

## Calidad de datos — restricción transversal (yfinance gratis)

Todo lo de arriba se construye sobre datos gratuitos con límites conocidos; tenerlos presentes en cada tarea:

- **Precio EOD + scan discreto:** la raíz del gap de los stops (tarea 1). Datos intradía de yfinance son acotados (~7d a 1m, ~730d a 1h) — alcanza para chequeo de stops recientes, no para backtests largos intradía.
- **`auto_adjust=True`:** introduce lookahead en backtests largos (sesgo conocido, `data_audit_2026-05-26`). Tenerlo en cuenta al interpretar resultados del harness.
- **Survivorship:** la watchlist son 52/52 vivos (MLTX el único −89.9%). El backtest sobreestima por nombres que no quebraron.
- **Consenso no point-in-time:** yfinance da el consenso/estimate **actual**, no el del día previo al print → sesgo de revisión. Por eso T-CAT-5b está bloqueada y el surprise score es bootstrap. Lo que hace avanzar el reloj: el scheduler diario que acumula `analyst_estimate_snapshots`.
- **Fundamentals stale/faltantes:** `trailingEps`/`trailingPE` de yfinance pueden faltar o estar atrasados por ticker → para fair value preferir EDGAR XBRL (hecho duro) y degradar con gracia cuando falte el dato (card silenciosa).
- **401 "Invalid Crumb":** mitigado con batch + retry (commits `bec78e6`/`3f833bb`); usar `get_historical_data_batch` y precargar cache en backtests para reproducibilidad.
- **Regla general:** cuando una tarea pueda usar un dato más confiable a costa de más trabajo, elegir el de mayor calidad (orden de Chapa 2026-06-25). Para decisiones de trading, ningún número entra al sizing/gates sin validación walk-forward.

---

## Bloqueado (esperando datos/condiciones)

- **T-CAT-5b — consenso point-in-time** — reemplazar la fuente del surprise score por `analyst_estimate_snapshots` leídos el día antes de cada earnings. Desbloqueo: ≥1 temporada capturada (~40 pares), estimado **~fines jul 2026**. Mientras tanto: mantener el scheduler diario corriendo.

## Backlog / ideas (sin priorizar)

- **Filtro de universo por liquidez/calidad** — excluir microcaps por ADV$ mínimo, además del ADV cap (que limita tamaño, no exclusión). Ataca la raíz del riesgo tipo MLTX. Definir umbral de ADV$ mínimo y validar que no saca nombres buenos.
- **Experimento T-CAT-6 "hold hasta cap_days"** — variante del exit-veto en el harness donde entraría el MRVL +52% (mediana de capture del rally 20d +5.99% → hay alpha sobre la mesa).
- **Subir la frecuencia de scan** — atacaría la raíz del gap de stops (tarea 1) sin tocar lógica; evaluar costo de red yfinance vs beneficio.
- **Documentar el estado efectivo de los flags** en `docs/SETTINGS_REFERENCE.md` (los valores leídos de `~/.finanzias/settings.json` el 2026-06-25).
- **Hueco residual anti-churn (N5):** un flip-flop *ganador* único sell→buy en scans separados por >30 min y que no llega al 3er ciclo pasa todos los gates. Impacto bajo.
- **Actualizar dependencias a las últimas versiones** (numpy 2.x · scikit-learn ≥1.8 · PyQt6 ≥6.8 · scipy/statsmodels). Hoy `requirements.txt` capea **numpy `<2.0`**, **scikit-learn `<1.8`** y **PyQt6 `<6.8`** para reproducir el entorno real validado (suite verde con numpy 1.26.4 / sklearn 1.4.2 / PyQt6 6.7.1 — ver `requirements.lock`). Para subir hace falta: (a) migrar `analysis/ml_signals.py` `_build_calibrator` de `CalibratedClassifierCV(cv="prefit")` a `FrozenEstimator` (sklearn 1.8 removió `cv="prefit"`); (b) confirmar que PyQt6 ≥6.8 cargue en Windows (6.11.0 daba `DLL load failed importing QtCore`); (c) revisar warnings de deprecación de numpy 2.5 (hmmlearn `a_sum.shape=`) y sklearn (`penalty` en LogisticRegression). **Kill-criteria:** suite Windows verde con el stack nuevo. Cerrar regenerando el lock (`python scripts/lock_requirements.py`).

## Hecho reciente

- [x] **Bug B1 — `get_current_price` crasheaba con `KeyError: 'exchangeTimezoneName'`** (robustez ALTA). Las props lazy de `fast_info` (`last_price`/`previous_close`/…) pueden lanzar en símbolos con metadata incompleta/deslistados; `getattr(..., None)` solo cae al default ante `AttributeError`, así que el KeyError se filtraba → `log.exception` ruidoso + posible cascada a hard-timeouts (B3). Fix: helper `_safe_fast_info` que degrada el fallo estructural a "dato ausente" (`price=None` → path "sin precio" + `record_failure`), pero **re-lanza los transitorios** (401/crumb/429 vía `_is_transient`) para que el retry los siga reintentando. 5 tests nuevos (`tests/test_yahoo_finance.py`). Commit `8791303` (suite 930 passed).
- [x] **Tarea ② — Aprobación encadenada de BUY/SELL en cuenta manual** (N2). `approve_order`: una BUY sin cash no expira si hay una SELL pendiente que la financia → queda `pending`; aprobar la SELL libera cash y re-aprobar la BUY la llena al budget real, sin sobre-apalancar (`_fill_trade` topa en cash). Validado (`docs/chained_approval_validation_2026-06-25.md`): 6/8 de las BUYs expiradas por cash se recuperan bajo encadenado (~$96.625 de entradas), las 2 sin SELL co-pendiente siguen expirando — **SHIP**. Commit `cf58a6d` (suite 925 passed).
- [x] **Tarea ① — Auto-fill de risk-exits (`atr_*`/`vol_trim`) en cuenta manual** (N3/A2). `engine.run_scan` bifurca: en manual los risk-exits se llenan directo con el `fill_price_override` modelado, el resto sigue `pending`. Validado por replay (`docs/risk_exit_autofill_replay_2026-06-25.md`): ΔP/L +3.95 pts vs pending-expira (peor caso), max DD 7.40%→14.98% si expiran — **SHIP**. Commit `8ff57e1` (suite 921 passed).
- [x] Harness de earnings blackout + decisión **restaurar `earnings_blackout_days=2`** (BUYs near-earnings −3.45%/17% win vs +1.1% normales; Δ ~+$4.200) — commit `dfd1dd5` (suite Windows 914 passed). Falta solo setear el flag (ver Acciones manuales).
- [x] Tarea 8 (flags de guardrail) — confirmados ON en `~/.finanzias/settings.json` (2026-06-19): ADV cap `0.05`, anti-churn `3/10`, anti-flap `30`, min-holding `60`, hysteresis `3`, anti-whipsaw `lookback 7`/`min_loss 0.0` (ON y estricto). `vol_overlay_trim` off por diseño.
- [x] Tarea original "Activar ADV cap" — el flag ya estaba en `0.05` en producción (solo queda verificar el trim, ver Acciones manuales).
- [x] Backlog reescrito con causa raíz del deep audit + política de calidad/ganancia — commit `dfd1dd5`
- [x] Normalización EOL global a LF en `.gitattributes` (cierra el churn de CRLF) — commit `e0d57f1`
- [x] Tooling de Claude Code: CLAUDE.md + docs de referencia + skills + commands + agents + guard — commit `ba6366e`
- [x] Fill realista (gap/touch) en salidas ATR + avisos de riesgo no expiran — commit `e5c2ff2`
- [x] Pestaña Métricas (efectividad del modelo) + auditoría buy/sell 2026-06-17 — commit `1af89be`
