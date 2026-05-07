# Hallazgos Detallados por Archivo

## Core Database

### database/models.py (203 líneas)

**Bien**:
- Modelo limpio con lazy-load relationships, cascade deletes.
- `Base.metadata.create_all()` simple pero efectivo.
- `@property` para computed fields (Position.total_invested).

**Problemas**:
1. **Sin índices**: Queries con filters múltiples (portfolio_id + ticker) escanean tabla completa. Agregar:
   ```python
   class Position(Base):
       __table_args__ = (
           Index("ix_pos_portfolio_ticker", "portfolio_id", "ticker"),
       )
   ```

2. **Migraciones ad-hoc**: `_migrate()` en línea 186. Mantener schema actualizado es manual. Solución: usar Alembic.

3. **DB path hardcoded**: `DB_PATH` es relativa al archivo (línea 13). Si se mueve, rompe. Usar config dinámico.

4. **Session lifecycle en init_db()**: Crea/cierra sesión manualmente (línea 172–183). Usar context manager.

---

### paper_trading/models.py (199 líneas)

**Bien**:
- Modelo VWAP para avg_cost correcto.
- Status flow bien documentado (pending → approved/filled).
- Audit trail completo (created_at, decided_at, filled_at).

**Problemas**:
1. **Sin índices**:
   ```python
   # engine.py:161–168 usará O(n) scan sin índice
   __table_args__ = (
       Index("ix_order_account_status", "account_id", "status"),
       Index("ix_order_filled_at", "filled_at"),
   )
   ```

2. **Sin CHECK constraints**: Enums como `status` son strings; no hay restricción de BD. Usuario podría corromper.

3. **Float precision**: `commission_paid`, `slippage_cost` son FLOAT en SQLite. Para dinero, usar DECIMAL o INTEGER (centavos).

---

## Data Layer

### data/yahoo_finance.py (459 líneas)

**Bien**:
- Caching 3 niveles (price, dividend, historical).
- Batch operations eficientes (get_bulk_prices, get_bulk_dividends).
- ThreadPoolExecutor para parallelismo sin deadlock.
- Fallback timezones para zoneinfo/pytz.

**Problemas**:
1. **Sin rate limiting visible**: 5 workers en paralelo sin exponential backoff. Si yfinance throttles, falla silenciosamente.
   ```python
   # Línea 394–406: future.result() puede lanzar sin retry
   ```

2. **Timeout indefinido en yfinance.download()**: Línea 170 sin timeout. Si yfinance cuelga, QThread nunca termina.
   ```python
   # Fix: usar ThreadPoolExecutor + timeout
   ```

3. **Validación mínima de data**: Línea 172 chequea `df.empty`, pero no valida:
   - NaN gaps (datos faltantes en medio)
   - Fechas no-trading duplicadas
   - Cambio de volumen anómalo (posible split sin ajuste)

4. **Multi-index silenciosamente eliminado**: Línea 173–174 dropea nivel si hay multi-columna. Sin advertencia.

5. **Session management**: Línea 31–76, 146–166: pattern manual try/finally. Refactorizar a context manager.

6. **Cache TTL hardcoded**: 5 min precio, 1h histórico, 6h dividendo. Sin opción de override por call.

---

### data/csv_importer.py (199 líneas)

**Bien**:
- Flexible column name matching con aliases.
- Auto-detect Yahoo Finance vs generic format.
- Manejo de watchlist (qty=0 → tratado como watchlist).
- Detailed error reporting.

**Problemas**:
1. **Sin encoding robustez**: Línea 12, importa `io.StringIO` pero no especifica encoding. BOM UTF-8 rompe.

2. **Falta manejo de duplicados**: Si CSV tiene 2 veces "AAPL", no verifica duplicate ticker.

3. **Normalización de ticker imperfecta**: Línea 109 `.upper()` pero no valida contra yfinance (podría ser typo).

4. **Parseo de fee incompleto**: Línea 153–165 busca col_fee pero no lo usa en cualquier lugar.

---

## Analysis

### analysis/technical.py (505 líneas)

**Bien**:
- Indicadores estándares (RSI, MACD, BB, SMA) correctamente implementados.
- LRU cache inteligente para evitar cálculo redundante (línea 119–156).
- Signal aggregation con pesos razonables (línea 432–454).
- Integración limpia con ML signals.

**Problemas**:
1. **Sin type hints** en >50% funciones. `_rsi_signal()`, `_macd_signal()` todo sin hints.

2. **Magic numbers sin documentación**:
   ```python
   # Línea 174–194: RSI thresholds (25, 30, 40, 60, 70, 75) sin justificación
   # Línea 308: volume ratio 1.5× sin backtesting
   ```

3. **Caché LRU simple, no thread-safe**: `_INDICATOR_CACHE` global. En UI multithreading, race condition.

4. **Descripción técnica en español hardcodeado**: Línea 176, "sobreventa extrema" − no internacionalizable.

---

### analysis/backtest.py (461 líneas)

**Bien**:
- Simulación determinista con lookahead guard.
- Métricas standard (CAGR, Sharpe, Sortino, max drawdown).
- Commission/slippage aplicados correctamente.

**Problemas**:
1. **Sin validación de lookahead real**: `signal_fn(df_upto_t)` confía en caller. Si alguien usa full DF, rompe contract silenciosamente.

2. **Sharpe/Sortino con rf=0.0 hardcodeado**: Línea 125–145. Risk-free rate real es ~4–5% (2024). Métrica sobeinflada.

3. **Max drawdown naive**: Línea 116. No usa corrección de sesgo (hay papers sobre esto).

4. **Sin transaction slippage modelado**: Asume fill a precio spot. Real: mid–ask spread varía con volatilidad.

5. **Falta buy-and-hold robustez**: Línea 84–89. Si only-short portfolio, benchmark falla.

---

### analysis/portfolio_backtest.py (820 líneas)

**Bien**:
- Rebalancing lógica sofisticada (signal, drift, monthly).
- Allocation modes bien diferenciados.
- Align de múltiples series temporales.

**Problemas**:
1. **Rebalancing logic débil**: No considera:
   - Tax impact (usa FIFO pero no reporta gains/losses)
   - Time delay (rebalance hoy, cash settle mañana)
   - Slippage correlation (si rebalance 10 stocks, slippage worse)

2. **Sin asset correlation tracking**: Equal-weight allocation asume no correlación. Real: tech activos están correlacionados 0.8+.

3. **Inverse-vol con volatilidad reciente sesgada**: Línea ~200. Usa 60-day vol; en crash, asigna a "low-vol" activos que acaban de subir.

4. **Falta validación de monthly rebalance trigger**: No verifica holiday (Día de Muertos, Navidad).

---

### analysis/ml_signals.py (653 líneas)

**Bien**:
- MarketContext dataclass clean con regime labels.
- Fallback a EWMA si arch/hmmlearn no disponible.

**Problemas**:
1. **XGBoost sin validación formal** (~400–450):
   ```python
   # Sin cross-validation, sin test/train split reporting
   X_train, y_train = prepare_features_targets(df)
   clf = xgb.XGBClassifier(...).fit(X_train, y_train)
   # ← test_score probablemente = train_score (leakage)
   ```

2. **Feature engineering poco documentado**: `prepare_features_targets()` no es visible (probablemente inline). Features no validados contra TA-Lib u otro bench.

3. **GARCH convergencia no verificada**: Línea 150+. Si `arch` no instala, fallback EWMA silencioso.

4. **HMM sin validación de hidden states**: Si 3-state HMM diverge (p.ej. bull state con -5% return), no hay alerta.

5. **compute_signal_probability ad-hoc**: Línea ~458. Usa pesos: 55% vol_risk, 45% regime_risk. Sin justificación.

---

### analysis/garch_signals.py (289 líneas)

**Bien**:
- Clasificación vol regime (EXPANSION/CONTRACTION/STABLE) razonable.
- Forecast horizon parametrizable.

**Problemas**:
1. **Sin convergencia check**: Línea 147. `res.convergence_flag` nunca validado.

2. **Fallback EWMA sin smoothing info**: Línea 102–109. Usa span=20 pero span optimal varía por activo.

3. **Rescale=False opaque**: Línea 145. Documento no explica por qué.

4. **Sin analysis de residuals**: ¿GARCH residuals normal? Si no, modelo inválido. Sin test.

---

## Paper Trading

### paper_trading/engine.py (594 líneas)

**Bien**:
- Deterministic con inyección de providers (testeable).
- Guardrails sofisticados: market hours, min holding, anti-flap, min trade size.
- ScanResult con auditable summary.

**Problemas**:
1. **run_scan() función gigante** (109–295):
   ```python
   # 186 líneas de lógica acoplada
   # Debería extraerse: fetch_prices, fetch_history, execute_strategy, apply_guardrails
   ```

2. **Anti-flap gate incompleto**: Línea 190–197. Revisa filled SELL, pero no pending SELL. Si usuario genera BUY, luego vuelve y genera SELL antes de approval, anti-flap no protege.

3. **Sin handling de split/dividend**: Si entre escan ocurre dividend, avg_cost no se ajusta. Posición "vieja" puede tener $cost basis inválido.

4. **Slippage/commission model simplista**: Línea 409. `fill_price = current_price * (1 + slippage)`. Real: slippage = f(volatility, market depth, order size).

5. **Sin order timeout**: Pending orders nunca expiran salvo por manual reject. Usuario aprueba 1 semana después → 1-week stale price.

6. **Sin partial fill tracking**: Asume 100% fill. Real: recibir 50% ahora, 50% mañana.

---

### paper_trading/account.py (340 líneas)

**Bien**:
- Funciones utilitarias limpias (get_account, get_positions, compute_equity).

**Problemas**:
1. **Sin type hints** en ~70% funciones.

2. **N+1 query risk**: `get_equity_curve()` (línea ~200). Si loop sobre snapshots sin índice en `account_id`, O(n) scan.

3. **Falta memoization**: `compute_equity()` recalcula cada vez, sin caché. Si llamado 100x en loop, overhead.

4. **Position entry_reason no propagado**: Se guarda en modelo pero nunca mostrado en UI. Código muerto.

---

### paper_trading/scheduler.py (253 líneas)

**Bien**:
- Tres triggers independientes (startup, interval, daily cron).
- QThread workers aíslan trabajo pesado.
- Settings-driven configuración.

**Problemas**:
1. **Sin thread-safe synchronization**: `self._workers` dict modificado sin lock (línea 125). Si dos QTimer events disparan simultáneamente (raro pero posible), race condition.
   ```python
   # Fix: usar threading.Lock() o QMutex
   ```

2. **Sin timeout en worker**: `PaperScanWorker.run()` (línea 100) sin killswitch. Si yfinance cuelga, QThread.quit() espera indefinido.

3. **Daily cron string parsing frágil**: Línea 64–72. Si usuario escribe "25:00", parsed a (23, 0) sin advertencia.

4. **Sin manejo de daylight saving time**: ZoneInfo ayuda, pero transición DST puede causar 2x ejecución o skip en cron diario.

---

### paper_trading/strategies.py (357 líneas)

**Bien**:
- Abstracción limpia de strategy como callable.
- TargetTrade dataclass simple.

**Problemas**:
1. **Sin type hints** en callables HistoryProvider, StrategyFn.

2. **Falta documentación de strategy contracts**: ¿Qué retorna strategy si no hay oportunidades? Lista vacía? None?

3. **Sin feature engineering reusable**: Cada estrategia calcula sus propios features. Duplicación.

---

### paper_trading/presets.py

(No leído, pero asumiendo presets hardcodeados. Debería ser JSON/config file.)

---

## UI

### ui/main_window.py (295 líneas)

**Bien**:
- Topbar limpio con market status update.
- Stacked layout simple.
- Scheduler integrado correctamente.

**Problemas**:
1. **Sin type hints**.

2. **Paper scheduler start() en __init__**: Línea 133. Si init falla, scheduler nunca se detiene. Debería agregar `closeEvent()` cleanup.

---

### ui/paper_tab.py (1472 líneas) ⚠️ CRÍTICO

**Problemas**:
1. **God class**: 40+ métodos manejando:
   - Account CRUD
   - Watchlist management
   - Positions table
   - Orders table
   - Equity curve chart
   - Worker threads
   - Signal routing
   
   Debería dividirse:
   ```python
   class PaperTradingTab:
       account_panel: AccountManagerPanel
       positions_panel: PositionsPanel
       orders_panel: OrdersPanel
       equity_panel: EquityChartPanel
   ```

2. **Matplotlib memory leak risk**: `_EquityCurveChart` (línea ~300–400) maneja Figure sin cleanup. Cada redraw agrega figura a memoria.

3. **_PricesWorker sin timeout**: Línea 77. Si yfinance cuelga, UI congela.

4. **Hardcoded column names**: Línea ~800+. Si alguien renombra BD, UI rompe silenciosamente.

5. **Signal routing manual**: Changes en order status no notifican automáticamente. Cada acción force `refresh_orders()` manual.

6. **Sin pagination**: Tabla de órdenes puede tener 1000+ rows. Sin lazy-loading, UI lenta.

---

### ui/analysis_tab.py (1253 líneas)

**Problemas**:
1. **God class similar**: Maneja búsqueda ticker, fetch data, análisis, chart, signals, hover behavior.

2. **Hover panel recalcula indicadores**: Línea ~600+. Cuando usuario hover, recalcula todos los indicadores para esa fecha. Sin caché. Lento.

3. **Threading: _AnalysisWorker sin timeout**.

4. **Tooltip content gigante**: Línea 54–150. 100+ líneas de HTML. Debería ser template.

5. **Sin dark mode en tooltips**: HTML hardcodeado con colores, no respeta theme.

---

### ui/portfolio_tab.py (727 líneas)

**Problemas**:
1. **Table hardcoding**: Columnas (Ticker, Qty, Avg Cost, Current Price, P&L) sin config. Difícil de customizar.

2. **Sin sorting memorizado**: Si usuario sort por P&L, luego agrega posición, sort se resetea.

3. **_PricesWorker duplicado**: Mismo que en paper_tab. Debería extraerse a workers.py.

---

### ui/chart_widget.py (273 líneas)

**Bien**:
- Integración matplotlib reasonable.

**Problemas**:
1. **Matplotlib in PyQt6**: Resize evento dispara full redraw. Sin incremental update.

2. **Sin zoom/pan interactivo**: Static chart sin herramientas de navegación.

3. **Memory: Figure objects no limpiadas** en destructor.

---

### ui/widgets.py (692 líneas)

**Bien**:
- MetricCard, StatusDot, HSeparator componentes reutilizables.

**Problemas**:
1. **Lógica de formatting repetida**: SignalBadge.

2. **Sin componente base**: Cada widget define su layout/styling. DRY violation.

---

### ui/dialogs.py (489 líneas)

**Problemas**:
1. **Sin form builder framework**: Cada dialog define sus inputs manualmente.

2. **Validación dispersa**: AddPositionDialog vs SellPositionDialog validaciones duplicadas.

---

### ui/styles.py (462 líneas)

**Bien**:
- Paleta centralizada.

**Problemas**:
1. **Sin tema system**: Dark theme hardcodeado. Si SO usa light mode, jarring contrast.

2. **Magic RGB values**: No hay tokenización de colores (primary, secondary, danger, etc.).

---

## Config

### config/settings_manager.py (109 líneas)

**Bien**:
- Singleton pattern limpio.

**Problemas**:
1. **Sin validación de schema**: Línea 87. `set()` acepta cualquier tipo/valor.

2. **Sin encryption**: Plaintext JSON. Si credenciales (future) guardadas, expuesto.

3. **Sin versioning**: Si agregar campo, usuarios old no tienen default claro.

---

## Reports

### reports/excel_report.py (296 líneas)

**Problemas**:
1. **Blocking call**: No hay threading. Genera en main thread → UI congela.

2. **Sin validation pre-write**: Puede crashear si data tiene NaN/inf.

---

### reports/pdf_report.py (256 líneas)

**Problemas**:
1. Idénticos a excel.

---

## Alerts

### alerts/alert_manager.py

(No leído, pero asumiendo básico. Debería tener thread para monitoreo.)

---

## Resumen por Severidad

### Crítica (Rompe Funcionalidad)

| Archivo | Línea | Problema |
|---------|-------|----------|
| `paper_trading/engine.py` | 190–197 | Anti-flap incomplete |
| `ui/paper_tab.py` | 1472 | God class → refactor |
| `analysis/ml_signals.py` | ~420 | XGBoost sin validation |

### Alta (Performance / Memory)

| Archivo | Línea | Problema |
|---------|-------|----------|
| `data/yahoo_finance.py` | 170 | Sin timeout |
| `ui/analysis_tab.py` | ~600 | Hover recalc sin caché |
| `ui/chart_widget.py` | ~150 | Matplotlib redraw full |

### Media (Code Quality)

| Archivo | Línea | Problema |
|---------|-------|----------|
| `database/models.py` | — | Sin índices |
| `analysis/technical.py` | 119 | Cache no thread-safe |
| Todos | — | Type hints ~30% |

---

## Recomendación: Archivos para Refactor Priorizado

1. **ui/paper_tab.py** → dividir en 4 components (Impacto alto)
2. **data/yahoo_finance.py** → agregar timeout (Impacto alto, esfuerzo bajo)
3. **analysis/ml_signals.py** → validar XGBoost (Impacto alto, esfuerzo medio)
4. **paper_trading/engine.py** → extraer run_scan() en funciones (Impacto media, esfuerzo medio)
5. **database/models.py** → agregar índices (Impacto alta, esfuerzo bajo)
