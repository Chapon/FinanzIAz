# Backlog — FinanzIAs

Lista **operativa** de tareas (el qué sigue). El por qué estratégico vive en `docs/roadmap_v3_2026-06-09.md`; la causa raíz de cada hallazgo está trazada a `archivo:función` en `docs/ops_logic_deep_audit_2026-06-17.md` (auditoría profunda) y `docs/ops_logic_audit_2026-06-17.md` (data-driven). Reglas de trabajo: ver `CLAUDE.md` y la skill `finanzias-conventions`.

**Contrato para Claude Code:** al empezar una sesión, leé este archivo. Al poner una tarea en marcha, movela a *En curso* (máx 1). Al cerrarla (suite Windows verde + commit) movela a *Hecho reciente* con el hash. Toda tarea que toque decisiones de trading se valida por harness con **kill-criteria pre-registrado** (skill `backtest-replay-harness` / agente `backtest-runner`); si no supera el umbral, se documenta y NO se shipea.

**Config viva (Sim Principal, id=1):** `strategy="analyze_single"`, `mode="manual"`, `allocation_mode="signal_weighted"`, `max_positions=5`, modo kill_only. Los flags *efectivos* viven en `~/.finanzias/settings.json` (fuera del repo) — varias tareas requieren confirmarlos/setearlos en Windows.

**Política de decisión (orden de Chapa 2026-06-25):** ante una duda entre una opción rápida y una más costosa, elegir **siempre la que dé mejor calidad de datos / mayor ganancia esperada** del trading. Por eso varias tareas eligen el camino más completo (auto-fill real de stops, sizing contra cash real, validación walk-forward) en vez del parche mínimo.

_Última actualización: 2026-06-30._

---

## En curso (WIP, máx 1)

- _(vacío)_

## Acciones manuales pendientes (Chapa, en Windows — fuera del repo)

- _(vacío — `~/.finanzias/settings.json` confirmado al día 2026-06-26)_

## Próximo (priorizado — el de arriba es el siguiente)

### 1. Alinear `signal_weighted` con lo que realmente hace  ·  ref N1 · severidad MEDIA
- **Qué:** hoy la cuenta dice `allocation_mode="signal_weighted"` pero ese modo **no** está en `_VOL_SIZED_MODES` (`strategies.py:54`), así que cae al `else` = **slices iguales de cash** (equal-weight). La config miente.
- **Por qué:** Chapa cree que sizea por convicción y en realidad es equal-weight. No es catastrófico (equal-weight es más seguro que pesar por un score sin poder predictivo, ver tarea 4), pero hay que cerrar la mentira de config.
- **Dónde:** `strategies.generate_trades_analyze_single` (ramas de allocation, líneas ~409-435) + `_compute_target_weights` en `analysis/portfolio_backtest.py` + enum `AllocationMode`.
- **Decisión de calidad (mayor ganancia):** implementar sizing **basado en riesgo** real en vez de equal-weight crudo: activar `inverse_vol` o `vol_target` (peso ∝ 1/σ), que es lo que hacen los sistemas pro (risk parity / vol targeting) y NO depende del buy_score sin alpha. Validar por harness contra equal-weight antes de cambiar el modo de la cuenta. Si no mejora, renombrar la cuenta a `equal_weight` para que la config sea honesta.
- **Kill-criteria:** la variante de sizing por riesgo se adopta si mejora Sharpe/P-L sin subir DD > 1.5×; si no, se deja equal-weight (renombrado).

### 2. Scale-out parcial en los SELL de señal  ·  ref A4/N4 · severidad MEDIA
- **Qué:** dejar de cerrar el 100% de la posición ante cada flip de señal; vender una fracción y mantener el resto (idealmente con trailing).
- **Por qué:** 57% de las veces el precio subió tras vender (mean fwd5 **+3.92%**): el consenso de indicadores se vuelve bajista cerca de pisos de corto plazo y revierte. Cerrar todo en un flip ruidoso regala upside y amplifica el churn. Es el sesgo pesimista confirmado en SELLs.
- **Dónde:** `strategies.generate_trades_analyze_single` líneas ~306-319 (hoy `target_shares = float(pos.shares)`, posición entera).
- **Decisión de calidad:** scale-out parcial (ej. vender 1/2 al flip, mantener 1/2 con trailing stop ATR) — práctica estándar para no liquidar en el peor momento. Parametrizar la fracción.
- **Kill-criteria:** replay comparando cierre 100% vs scale-out 50%+trailing: se shipea si mejora el P/L ≥ +1.5 pts sin empeorar DD > 1.5×.
- **Sinergia:** se beneficia de la hysteresis ya activa (Gate 2b, T6.4) y del exit-veto T-CAT (sigue OFF).

### 3. Validar (o degradar a display) la `ml_probability` / buy_score  ·  ref A3 · severidad MEDIA
- **Qué:** el `buy_score` = `_default_strength("BUY", ml_probability)` = la probabilidad ML calibrada de `analyze()`. corr(score, fwd5) ≈ **0.00** (n=21): no anticipa el retorno a 5 días en esta muestra. Hoy decide *qué* nombres entran (ranking), no *cuánto* (el sizing no lo usa, ver tarea 2).
- **Por qué:** si el score no tiene alpha, rankear por él elige los nombres equivocados. El problema real no es "sacarlo del sizing" (ya está fuera) sino **si debe seguir eligiendo entradas**.
- **Dónde:** `analysis.technical.analyze` (genera `ml_probability`), `strategies._default_strength`, ranking en `generate_trades_analyze_single`.
- **Decisión de calidad (mayor ganancia):** validación **walk-forward out-of-sample** seria (no in-sample, n=21 es poco) con `scripts/harness_walkforward.py`: ¿el ranking por ml_probability bate a un ranking neutro/aleatorio en P-L? Si tiene alpha OOS → recalibrar y mantener. Si no → degradar a display-only y elegir entradas por otra señal (momentum/calidad) validada. Preferir la validación rigurosa aunque lleve más tiempo.
- **Kill-criteria:** mantener el score en selección solo si bate al baseline neutro en walk-forward por un margen pre-registrado; si no, se reemplaza la señal de selección.
- **Nota de datos:** n=21 round-trips es muestra chica → cuidado con sobreajustar. Acumular más historia mejora esta decisión (ver sección Calidad de datos).

---

## Bugs / robustez de datos (del log de runtime 2026-06-25)

### `database is locked` al escribir `earnings_cache` (delete-then-insert)  ·  severidad BAJA · robustez
- **Síntoma:** `sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) database is locked` en `DELETE FROM earnings_cache WHERE earnings_cache.ticker = ?` (visto con `DUK`).
- **Dónde:** `data/yahoo_finance.py` → `get_next_earnings_date`, paso 3 (cache write, líneas ~906-911): hace `session.query(EarningsCache).filter(ticker==...).delete()` seguido de `session.add(...)` dentro de un `session_scope()`.
- **No es crash:** el bloque está en `try/except Exception: log.exception(...)` → **fail-open**. El gate de earnings (T08 blackout) defaultea a no bloquear y el traceback que aparece es lo que imprime `log.exception`, no una excepción que sube. Por eso no rompe el scan.
- **Causa raíz:** contención de escritura sobre SQLite pese a que el engine ya tiene WAL + `busy_timeout=30000` + `timeout=30` (`database/models.py:52-79`). WAL permite muchos lectores pero **un solo escritor**; el lock persiste cuando: (a) corren dos procesos escribiendo a la vez —típicamente el scan de la app escribiendo `earnings_cache`/`price_cache` mientras el Task Scheduler diario corre `harvest_catalysts.py` escribiendo `news_events`—, o (b) un upgrade read→write donde SQLite devuelve `SQLITE_BUSY` de inmediato sin respetar `busy_timeout` (lo hace a propósito para no deadlockear). El patrón delete+insert mantiene el lock de escritura más tiempo que un upsert.
- **Impacto:** bajo. Se pierde la escritura de cache de ese ticker → el próximo scan re-pega a Yahoo por su calendario de earnings (llamada redundante) + ruido de log. Sin impacto en decisiones de trading ni corrupción (la lectura es SELECT, no toca esto).
- **Fix propuesto (orden de menor a mayor):** (1) tratar el lock como transitorio y reintentar con backoff —reusar `_is_transient`/`_run_with_timeout` que ya existen para el 401 crumb— en vez de solo loguear; (2) reemplazar el delete+insert por un **upsert** (`INSERT ... ON CONFLICT(ticker) DO UPDATE`) para acortar la ventana de lock y evitar el ciclo borrar/insertar; (3) bajar el log a `debug`/`warning` (no `exception`) ya que es fail-open esperable bajo contención. Validar que no se pisen escrituras concurrentes legítimas.
- **Kill-criteria:** suite Windows verde + el warning desaparece (o baja a debug) bajo un scan concurrente con el harvest corriendo.

### Precio de Yahoo ~10× corrupto ejecutó un round-trip entero (KLAC)  ·  severidad MEDIA · robustez
- **Síntoma:** el ciclo KLAC de la cuenta 1 se abrió y cerró en escala **~$1942–1987** (BUY 2026-06-01 @ 1942.70 ×2, SELL 2026-06-05 @ 1987.83 por `atr_trail`) cuando el precio real de KLAC en junio 2026 era **~$190–210** (factor ~10×). Detectado al recalibrar los stops ATR (A1): el fill difería del close del cache en +930%.
- **Impacto:** el notional del trade quedó ~10× inflado ($3.885 en vez de ~$388) → distorsiona el peso en el portfolio y el sizing de los ciclos vecinos (el cash "ocupado" fue 10× el real). El P/L en % del ciclo es coherente internamente (+2.3%), pero el $ absoluto y todo lo que dependa del notional (DD, exposición, ADV cap) están sesgados. No es crash.
- **Causa raíz (a confirmar):** precio basura de Yahoo en el momento del scan (familia del "Invalid Crumb"/401 que `bec78e6`/`3f833bb` mitigaron para el fetch, pero acá el valor corrupto **pasó el filtro y se usó como precio de entrada/salida**). El ATR del reason (93.85 sobre ~$1987 ≈ 4.7%, plausible; sobre ~$200 sería absurdo) confirma que todo el ciclo corrió en la escala inflada.
- **Fix propuesto:** sanity-check de precio antes de fillar una orden — rechazar/marcar un fill cuyo precio difiera del último close cacheado (o de un EOD de referencia) por > X% (p.ej. 50%), igual que la higiene que ya hace el harness A1 (`partition_atr_events`). Evaluar también un guard en `get_current_price`/`get_bulk_prices` que descarte cotizaciones fuera de banda vs el histórico reciente. Revisar si hay otros ciclos contaminados además de KLAC.
- **Kill-criteria:** suite Windows verde + un fill con precio fuera de banda (>50% vs último close) se rechaza/marca en vez de ejecutarse; barrido de la DB viva sin otros round-trips con notional fuera de escala.

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

- [x] **A1 — Recalibrar / decidir continuidad de los stops ATR** (severidad MEDIA). **Veredicto: NO-SHIP, los stops quedan en mult 2.0** (`docs/atr_stop_recalib_2026-06-30.md`). Harness nuevo `scripts/run_atr_stop_recalib.py` + motor `replay_atr_recalib` (`analysis/exit_replay.py`, re-evalúa el ciclo ATR desde el día del exit real bajo params alternativos, fills modelados) + `tests/test_atr_stop_recalib.py`. Resultado sobre 6 exits ATR limpios (KLAC excluido por precio corrupto, ver abajo): `no_stops` (+5.38 pts) y `mult_3.0` (+4.46 pts) **pasan el umbral numérico pero NO son robustos** — leave-one-out sin LRCX (que aporta 63% del efecto) los tumba a +1.99/+1.07 pts, bajo el umbral. Muestra n=6 en régimen de rebote sin drawdown (survivorship) → apagar/aflojar un guardrail de riesgo sería especulativo. Re-evaluar con ≥1 período de stress o n≥~20. Commit `a75deda` (suite Windows 950 passed, 1 skipped).
- [x] **Bug B2 — símbolos muertos en el universo no se salteaban (K / Kellanova)** (severidad MEDIA). Dos partes: (1) el flujo de skip end-to-end quedó cerrado por `e38f751` — `get_historical_data_batch` ahora honra el `failing` set igual que `get_bulk_prices`, así un símbolo muerto no se re-consulta cada scan; (2) K (Kellanova) se confirmó **delistada** tras la adquisición de Mars (Yahoo ya no la lista), así que se removió del preset "Consumo defensivo" y del universo S&P 500 fallback en `2c9587c`. La watchlist viva en la DB que aún la tenga la saltea sola (delisting genuino → `failing` set). Suite Windows 940 passed, 1 skipped.
- [x] **Bug B3 — el scan operaba sin precio de large-caps reales por throttle de Yahoo** (severidad ALTA). Un throttle/timeout transitorio durante el warm-up batch envenenaba el `failing` set con tickers **reales** (clasificados como "deslistados") y `get_bulk_prices` después los salteaba → scan sin precio de JPM/KLAC/LOW/LMT. Fix: estado `transient` en `failed_tickers` (no entra al `failing` set; `override` para degradar wholesale, nunca pisa `ignored`), circuit-breaker de throttle (`_note_throttle`/`_is_throttled`/`reset_throttle` + `NETWORK_THROTTLE_COOLDOWN_SECONDS=90s`, fail-fast bajo throttle), `_record_miss` throttle-aware, `get_historical_data_batch` honra el `failing` set (**cierra B2**) + wholesale→transient, `get_bulk_prices` detección wholesale, telemetría `prices_requested`/`prices_missing` en `ScanResult` + warning fuerte si una posición abierta quedó sin precio (stop no corrido), etiqueta "Transitorio" en la pestaña de fallidos. Commit `e38f751` (suite Windows 940 passed, 1 skipped).
- [x] **Acciones manuales cerradas (2026-06-26)** — confirmado en `~/.finanzias/settings.json` vivo: `earnings_blackout_days=2` + `earnings_blackout_block_sells=false` (ya estaban seteados) y `paper_adv_cap_pct=0.05`. **Verificación del ADV cap:** los tests de integración `tests/test_adv_cap.py` (driven sobre `run_scan` con el flag en 0.05) confirman que un BUY ilíquido (>5% ADV$) se recorta con el warning "recortado por ADV" y uno normal NO se toca — los dos casos que pedía la acción manual. No hubo cambios en el repo (los flags viven fuera de él).
- [x] **Bug B4 — red de seguridad autouse contra escrituras a la `finanzias.db` real** (prevención MEDIA). Fixture `_guard_real_db` en `tests/conftest.py` que rebindea `ENGINE`/`SessionLocal` a una SQLite in-memory por test (`StaticPool` + `check_same_thread=False` para aislar también las escrituras de cache desde el ThreadPool de yfinance); opt-out `@pytest.mark.real_db`. Previene toda la clase de bug que el 2026-06-25 corrompió AAPL/MSFT 1y. Incluye `tests/test_db_guard.py` (valida el guard), el fix puntual de `test_historical_batch` y `scripts/purge_synthetic_cache.py` (DB real ya verificada limpia). Commit `828dcd8` (suite 932 passed). **Toda la deuda de infra de testing/deps de esta tanda quedó cerrada.**
- [x] **Coherencia requirements ↔ `.venv`** + tarea de upgrade. `.venv` recreado (estaba con binarios cp313 sobre Python 3.12); `requirements.txt` capeado al stack validado (numpy `<2.0`, scikit-learn `<1.8`, PyQt6 `<6.8`, xgboost declarado) y `requirements.lock` regenerado desde el venv sano. Commit `eeff335`.
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
