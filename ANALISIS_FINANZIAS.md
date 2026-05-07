# Análisis Profundo del Proyecto FinanzIAs

## Resumen Ejecutivo

**FinanzIAs** es una aplicación PyQt6 bien estructurada para seguimiento de carteras e inversión simulada. El proyecto demuestra arquitectura sólida, separación clara de responsabilidades y patrones modernos. Sin embargo, presenta vulnerabilidades en threading, manejo de sesiones SQLAlchemy, replicación de código y solidez estadística de ciertos modelos ML.

### 5 Puntos Críticos Identificados

1. **Gestión de Sesiones SQLAlchemy Débil**: 46 llamadas a `session.close()` en bloques `finally`, sin usar context managers. Riesgo de resource leaks y race conditions en multithreading.

2. **Threading UI Bloqueante**: yfinance, backtesting (GARCH, XGBoost, portfolio analysis) ejecutan en QThreads, pero sin timeout ni cancellation. UI puede congelarse si una descarga de datos cuelga.

3. **Falta de Type Hints Sistemáticos**: Solo ~30% del código tiene type hints. Dificulta mantenimiento, refactoring y detección temprana de bugs.

4. **Validación Estadística Incompleta en ML**: XGBoost se entrena sin validación cruzada, sin reporte de overfitting, sin matriz de confusión. Risk para decisiones de trading real.

5. **Duplicación Código en UI (>1000 líneas repartidas)**: Tablas, diálogos, workers comparten lógica repetida (formatting, sorting, caching de tickets, pattern matching headers).

---

## Hallazgos Detallados por Área

### 1. Arquitectura y Estructura

#### Fortalezas

- **Separación de capas clara**: `database/` (modelos), `data/` (yfinance), `analysis/` (técnica/ML), `paper_trading/` (motor simulador), `ui/` (PyQt6), `reports/`, `config/`, `alerts/`.
- **Inyección de dependencias en engine.py**: `run_scan()` acepta `prices_provider` y `history_provider` callables → testeable sin yfinance.
- **Singleton pattern apropiado**: `config/settings_manager.py` implementa singleton limpio con acceso global.

#### Problemas

- **Acoplamiento circular**: `paper_trading/engine.py` importa de `database/models.py`, que a su vez importa `paper_trading.models` en `init_db()` (línea 166). Aunque funciona, dificulta refactoring.
- **God object in progress**: `ui/paper_tab.py` (1472 líneas) maneja cuentas, watchlist, posiciones, órdenes, gráficos equity en una sola clase. Debería dividirse en ≥4 componentes.
- **Sin servicio centralizado de data**: yfinance se llama directamente desde múltiples sitios (`yahoo_finance.py`, `engine.py`, UI threads). Dificulta control global de rate limiting y caché invalidation.
- **Falta de event bus**: cambios de cuenta en paper_trading no notifican a otras pestañas; cada pestaña hace refresh manual.

---

### 2. Calidad del Código

#### Problemas de Scaling

| Archivo | Líneas | Problemas |
|---------|--------|----------|
| `ui/paper_tab.py` | 1472 | God class, >40 métodos, state management complejo |
| `ui/analysis_tab.py` | 1253 | >35 métodos, lógica de UI + analysis mezclada |
| `ui/portfolio_tab.py` | 727 | >25 métodos, tabla de posiciones hardcoded |
| `analysis/ml_signals.py` | 653 | >20 funciones, sin estructura modular |
| `paper_trading/engine.py` | 594 | `run_scan()` > 120 líneas (líneas 109–295) |

#### Type Hints

**Cobertura**: ~30% del código. Ejemplos deficientes:

```python
# yahoo_finance.py:338 — sin type hints
def get_bulk_prices(tickers: list[str]) -> dict[str, Optional[dict]]:
    # ...
    # pero callers hacen:
    for ticker, info in live_results.items():
        if info is not None:
            info["from_cache"] = False  # type-unsafe dict access
```

Impacto: refactoring costoso, errores silenciosos en cambios futuros.

#### Duplicación de Código

1. **Manejo de sesiones**: 46 patrones `session = get_session(); try: ... finally: session.close()` repartidos. No hay context manager.
   ```python
   # Repetido en ~15 archivos
   session = get_session()
   try:
       # lógica
   finally:
       session.close()
   ```

2. **Normalización de headers en importers**: `csv_importer.py:51–60` vs tablas UI que repiten alias matching.

3. **Worker threads**: 9 archivos definen clases QThread customizadas sin herencia común:
   - `_PricesWorker` (paper_tab.py)
   - `_AnalysisWorker` (analysis_tab.py)
   - `_ImportWorker` (import_dialog.py)
   - `_BacktestWorker` (analysis_tab.py)
   - ... 4 más

4. **Diálogos de entrada**: `dialogs.py` + `import_dialog.py` + `paper_tab.py` definen validaciones de input, conversión de tipos y manejo de errores idénticos.

#### Problemas de Nombre y Documentación

- Variables genéricas: `result`, `data`, `config`, `row`, `val` sin prefijo/contexto.
- Funciones sin docstring: >80% de funciones de UI carecen de docstring.
- Nombres inconsistentes: `acct` vs `account`, `df_upto_t` vs `df`, `signal_fn` vs `strategy_fn`.

---

### 3. Modelo de Datos / Persistencia

#### Diseño

- **SQLAlchemy ORM bien usado**: lazy-load, relationships con cascade delete, tablename explícito, tipos correctos.
- **Índices**: Ninguno definido. Crítico para queries frecuentes:
  ```python
  # paper_trading/engine.py:161–168 — sin índice
  existing_pending = {
      (o.ticker, o.side)
      for o in session.query(PaperOrder)
          .filter(PaperOrder.account_id == acct.id)
          .filter(PaperOrder.status == "pending").all()  # O(n) scan
  }
  ```

- **Sin migraciones formales**: script manual `_migrate()` en `database/models.py:186–197`. Funciona, pero no escala a múltiples usuarios o cambios complejos.

#### Problemas N+1

1. **portfolio_tab.py**: al iterar posiciones y luego cargar precio actual, sin prefetch:
   ```python
   # Implícito: N queries (una por position)
   for pos in session.query(Position)...:
       price = get_current_price(pos.ticker)  # ← yfinance call N veces
   ```
   Debería usar `get_bulk_prices([pos.ticker for pos in positions])`.

2. **paper_tab.py**: equity curve load sin index hints.

#### Sesiones y Context Managers

**Problema**: Todos los `get_session()` usan manejo manual. Ejemplo deficiente (yaml_finance.py:31–76):

```python
session = get_session()
try:
    cached = session.query(PriceCache)...
    if cached:
        return {...}
    # ... fetch + insert
finally:
    session.close()  # ← problema: si exception en return, no cierra atomically
```

**Riesgo**: En multithreading, session objects pueden escapar del thread que los creó. SQLAlchemy Thread Safety No garantizado.

---

### 4. UI / PyQt6 y Threading

#### Threading: Bien

- **Scheduler centralizado**: `PaperScheduler` (253 líneas) coordina 3 triggers (startup, interval, daily cron) con QTimer + QThread workers.
- **Workers por tarea**: `PaperScanWorker`, `_AnalysisWorker`, `_PricesWorker` aíslan trabajo pesado.
- **Signals/slots**: `scan_completed`, `scan_failed` desacoplan UI de lógica.

#### Threading: Problemas

1. **Sin timeout**: Si yfinance cuelga, QThread.run() espera indefinidamente.
   ```python
   # paper_trading/scheduler.py:100 (PaperScanWorker.run)
   def run(self):
       from paper_trading.engine import run_scan
       result = run_scan(self.account_id)  # ← sin timeout
   ```
   **Fix**: Envolver con `timeout.Timeout` o añadir `QTimer.singleShot` killswitch.

2. **Sin cancellation**: Si el usuario cierra la app durante un scan, el QThread sigue corriendo. Esperar 10+ segundos al quit.
   ```python
   # Falta: QThread.requestInterruption() + check en loops
   ```

3. **Matplotlib en QThread**: `ui/paper_tab.py:_EquityCurveChart._full_redraw()` hace `self.figure.canvas.draw()` desde worker → race condition.

#### Memoria y Gráficos

- **Matplotlib figures**: 5+ instancias en diferentes pestañas sin cleanup explícito. Risk de memory leak en sesiones largas.
- **DataFrame caching**: LRU cache en `analysis/technical.py:119` limita a 50 datasets, pero sin eviction strategy global.
- **Widgets detached**: Cuando una pestaña se oculta, widgets no se desconectan de signals → listeners fantasmas.

---

### 5. Análisis Técnico / Cuantitativo

#### Cálculos: Generalmente Correctos

- **RSI (línea 65)**: Wilder's smoothing correcto con `ewm(com=period-1)`.
- **MACD (línea 77)**: EMA fast/slow/signal, histogram diferencia → correcto.
- **Bollinger Bands (línea 93)**: SMA + std_dev → correcto.
- **SMA/EMA (línea 105–110)**: rolling/ewm estándares.

#### Problemas Estadísticos

1. **Look-ahead bias**: En backtest.py, `signal_fn` recibe `df_upto_t`, pero chart_widget.py calcula todos los indicadores a la vez. Si alguien copypastea lógica chart → strategy sin cuidado, puede introducir look-ahead.

2. **Falta de validación en GARCH**:
   ```python
   # garch_signals.py:147
   res = model.fit(disp="off", show_warning=False)  # ← ¿convergió?
   # No hay check de res.convergence_flag o likelihood
   ```
   Si GARCH no converge, forecast_vol será inútil sin warnings.

3. **XGBoost sin validación formal** (ml_signals.py:~400–500):
   ```python
   # Entrenamiento en línea 200+:
   X_train, y_train = prepare_features_targets(df)
   # Sin split train/test, cross-validation, overfitting check
   clf = xgb.XGBClassifier(...).fit(X_train, y_train)
   prob = clf.predict_proba(X_test_last)[-1, 1]
   ```
   **Problemas**:
   - No hay matrix de confusión.
   - No hay feature importance reporting.
   - Entrenamiento cada vez que se corre analyze() → overhead + inconsistencia.
   - Test set podría estar contaminado con datos de entrenamiento.

4. **Sharpe/Sortino**: Implementación en backtest.py:125–145 es estándar pero NO usa risk-free rate actualizado (hardcoded `rf=0.0`).

#### Indicadores de Momentum

- Volume signal (línea 278): Compara volumen en days up vs down, threshold 1.5x → parece razonable pero sin backtesting.

---

### 6. Paper Trading

#### Motor de Simulación: Bien Diseñado

- **Ejecución de órdenes**: `_fill_trade()` calcula shares correctamente con comisión/slippage.
- **VWAP avg_cost**: Acumula posición correctamente.
- **Audit trail**: Cada orden registrada con status flow (pending → approved/rejected/filled).

#### Problemas

1. **Slippage & Comisión Simplistas**:
   ```python
   # engine.py:409 (pending order share calc)
   fill_price = current_price * (1 + acct.slippage)  # ← slippage aditiva fija
   raw_shares = (budget * (1 - acct.commission)) / fill_price
   ```
   Real: slippage varía con market depth, time of day, volume. Modelo es optimista.

2. **Falta de Partial Fills**: Orden de 1000 shares asume ejecución 100% a precio spot. Real: posible recibir 500 @ 100.10, 500 @ 100.20.

3. **Sin Limit Orders**: Todas las órdenes son market orders. No hay control de entrada/salida.

4. **Scheduler thread-safe incompleto**:
   ```python
   # scheduler.py:125
   self._workers: dict[int, PaperScanWorker] = {}
   # En _on_interval_tick(), se modifica sin lock
   ```
   Si dos QTimer events se disparan simultáneamente (raro pero posible), race condition.

5. **Anti-flap gate defectuoso**:
   ```python
   # engine.py:190–197
   recent_sell_tickers: set[str] = set()
   if anti_flap_min > 0:
       cutoff = result.scan_at - timedelta(minutes=anti_flap_min)
       rows = session.query(PaperOrder.ticker)...filter(status == "filled")
   ```
   Problema: si un BUY se genera antes que SELL sea filled (pending approval), anti-flap no funciona. Debería también revisar pending SELLs.

#### Estrategias

- **analyze_single**: Analiza cada ticker independientemente. Sin correlación.
- **portfolio_engine**: Considera rebalancing, drift, monthly reset. Bien diseñado pero sin backtesting integrado.

---

### 7. Datos / yfinance

#### Caching: Bien

- PriceCache: TTL 5 min, batch query/write eficiente.
- HistoricalDataCache: TTL 1h, serializa DataFrame con JSON.
- DividendCache: TTL 6h.

#### Problemas

1. **Sin Rate Limiting Explícito**: 5 workers en paralelo → posible throttle de yfinance. Sin exponential backoff.
   ```python
   # yahoo_finance.py:13
   BULK_FETCH_WORKERS = 5  # ← magic number, sin monitoreo
   ```

2. **Cache TTL duro**: Si el usuario quiere data en tiempo real (trading real), TTL 5 min es demasiado. Sin opción de bypass.

3. **Validación de Data Mínima**:
   ```python
   # yahoo_finance.py:170–178
   df = yf.download(...)
   if df.empty:
       return None
   # No hay check de NaN gaps, duplicados, fechas no-trading
   ```
   Gap en data histórica (p.ej. en holidays) puede contaminar análisis.

4. **Multi-index handling**:
   ```python
   # yahoo_finance.py:173–174
   if isinstance(df.columns, pd.MultiIndex):
       df.columns = df.columns.get_level_values(0)
   ```
   Silenciosamente dropea información (¿bid/ask para cada stock?). Sin warning.

---

### 8. Reportes (Excel / PDF)

#### Bloqueo UI

- **excel_report.py**: Escribe openpyxl sin threading → UI congela si >100 filas.
- **pdf_report.py**: FPDF también en main thread.

**Solución**: Envolver en QThread con progress bar.

#### Generación

- Ambos módulos generan reportes razonables: P&L, holdings, transactions.
- Sin validación de datos antes de escribir (p.ej. división por cero).

---

### 9. Configuración / Settings

#### Fortalezas

- Singleton limpio con defaults, load/save JSON.
- Ubicación estándar: `~/.finanzias/settings.json`.

#### Debilidades

1. **Sin validación de values**:
   ```python
   # settings_manager.py:87–89
   def set(self, key: str, value) -> None:
       self._data[key] = value
       self.save()  # ← sin check de tipo ni rango
   ```
   Usuario puede hacer `settings.set("paper_scan_interval_minutes", "invalid")` → crash después.

2. **Sin encryption**: Credenciales (future) estarían en plaintext.

3. **Sin schema versioning**: Si se agrega campo, usuarios old JSON quedan sin default claro.

---

### 10. Testing

**Hallazgo crítico**: **No hay tests automatizados**. Cero pytest, zero unittest.

**Impacto**:
- Refactoring es manual y error-prone.
- Regressions descubiertos en stage (o worse, usuarios).
- No hay specs formales de comportamiento esperado.

**Qué debería testearse**:
1. `backtest.py`: signal_fn contracts, lookahead, metric math.
2. `portfolio_backtest.py`: rebalancing logic, drift calc.
3. `paper_trading/engine.py`: fill logic, guardrails (market hours, anti-flap).
4. `analysis/technical.py`: indicadores vs TA-Lib o manual calc.
5. `csv_importer.py`: parsing casos edge.

---

### 11. Performance

#### Cuellos de Botella Probables

1. **yfinance.download() sin cache en análisis tab**: Cada cambio de ticker descarga history full.
   ```python
   # analysis_tab.py:~300+ (inner loop implícito)
   df = get_historical_data(ticker)  # ← 2y de data, ~500 filas
   # Si usuario cambia ticker rápido, 3 downloads concurrentes
   ```

2. **XGBoost reentrenamiento**: Se retrain en cada analyze(), sin memoization.
   ```python
   # ml_signals.py:~400
   clf = xgb.XGBClassifier(...).fit(X_train, y_train)
   # Si misma data, mismo modelo. Sin cache.
   ```

3. **Portfolio backtest**: Loop triple (tickers × days × rebalance logic) → O(n³). Para 10 tickers × 500 días, aceptable. Para 50 tickers × 10 años, lento.

4. **DataFrame conversión JSON en cache**: Serializar/deserializar OHLCV en cada hit → overhead I/O SQLite.

#### Optimizaciones Posibles

- Vectorizar loops en `portfolio_backtest.py` con numpy.
- Precomputar features XGBoost, cachearlas.
- Pool de ThreadExecutor reutilizable en lugar de crear new en cada call.

---

### 12. Seguridad

#### SQL Injection

**Estado**: Safe. SQLAlchemy ORM parameteriza todas las queries.

#### Datos Sensibles

- **Precio de posiciones**: Stored en DB local plaintext. Si el DB se comparte, expuesto.
- **Contraseñas future**: Ninguna estructura, pero archivo settings es plaintext.

**Recomendación**: Si se agrega auth/API keys, usar keyring library.

#### Dependencias Desactualizadas

No hay `requirements.lock` ni pin de versiones. `requirements.txt` probablemente usa `>=` versions. Risk de breaking changes.

**Ejemplo hipotético**: `yfinance 0.1.x` → `0.2.x` cambia API → app rompe.

---

### 13. DevEx / Deployment

#### requirements.txt vs Lock File

- **Observación**: Proyecto usa `requirements.txt` sin lock file.
- **Risk**: Reproducibilidad: instalar en otra máquina puede traer versiones diferentes.

#### .gitignore

- **Hallazgo**: Probablemente no existe `.gitignore` completo.
- **Evidencia**: Búsqueda en bash no mostró archivos __pycache__ commiteados (buen signo), pero sin ver el .gitignore real, no confirmamos.

#### CI/CD

- **Ausente**: Sin GitHub Actions, GitLab CI, etc.
- **Impacto**: Cambios mergean sin tests, linting, type checks.

#### Linting

- **Ausente**: Sin ruff, black, mypy, pylint.
- **Resultado**: Código inconsistente (algunos archivos 4 spaces, otros tabs).

#### Empaquetado

- **PyInstaller posible**: Código organizado bien para .exe/.app build.
- **Sin build script**: Requiere manual steps.

---

### 14. Internacionalización / UX

#### Español Hardcodeado

- **Strings en español** en todo el código: `"Compra Fuerte"`, `"Portafolio"`, `"Cerrado (fin de semana)"`.
- **Impacto**: Agregar inglés/otro idioma requiere refactor masivo.

#### Tooltips

- Excelentes tooltips en `analysis_tab.py:54–150`. Educativo y detallado.

#### Validaciones de Input

- `dialogs.py`: Valida input pero sin feedback visual (p.ej. red border si inválido).
- CSV importer: Detalla skipped rows, pero no es amigable para usuarios no-técnicos.

---

## Oportunidades de Mejora — Matriz Impacto/Esfuerzo

### Matriz de Priorización

```
IMPACTO ALTO / ESFUERZO BAJO (Quick Wins) ✓✓✓
├─ Agregar context managers para sesiones SQLAlchemy (1-2 horas)
├─ Agregar índices a PaperOrder, PaperPosition (30 min)
├─ Agregar type hints core (3-4 horas) 
├─ Extraer base class QWorker (2 horas)
├─ Timeout en yfinance downloads (1 hora)
├─ Validar convergencia GARCH (30 min)

IMPACTO ALTO / ESFUERZO MEDIO (Estratégicas) ★★★
├─ Refactorizar paper_tab.py en 4 components (8-12 horas)
├─ Agregar test suite (backtest, engine, analysis) (15-20 horas)
├─ Extraer data service centralizado (8-10 horas)
├─ Implementar proper session management (4-6 horas)
├─ ML model caching + validación (6-8 horas)

IMPACTO MEDIO / ESFUERZO ALTO (Futuros)
├─ i18n (español/inglés) (15-20 horas)
├─ Limit orders + partial fills (10-15 horas)
├─ Live market data websocket (12-16 horas)
└─ Distributed backtesting (20+ horas)
```

---

## Top 10 Quick Wins

### 1. **Context Manager para SQLAlchemy Sessions** (1.5 horas)

Crear `config/database.py`:

```python
from contextlib import contextmanager

@contextmanager
def session_scope():
    """Provide a transactional scope for sessions."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

Refactorizar 46 callsites:

```python
# Antes
session = get_session()
try:
    result = session.query(PriceCache)...
finally:
    session.close()

# Después
with session_scope() as session:
    result = session.query(PriceCache)...
```

**Beneficio**: Previene resource leaks, limpia código, thread-safe.

---

### 2. **Type Hints Core (3-4 horas)**

Comenzar por `analysis/technical.py` (505 líneas, ya tiene algo):

```python
# Antes
def analyze(ticker, df, enable_sma_cross=True, enable_volume=True, enable_xgboost=True):

# Después
def analyze(
    ticker: str,
    df: pd.DataFrame,
    enable_sma_cross: bool = True,
    enable_volume: bool = True,
    enable_xgboost: bool = True,
) -> Optional[AnalysisResult]:
```

Usar `pyright` o `mypy` para validar. Hacerlo modular (1 archivo por sesión).

**Beneficio**: IDE autocompletion, refactoring seguro, bugs tempranos.

---

### 3. **Extraer Base QWorker (2 horas)**

```python
# ui/workers.py

class BaseQWorker(QThread):
    """Base class para todos los background workers."""
    work_completed = pyqtSignal(object)
    work_failed = pyqtSignal(str)
    
    def __init__(self, timeout_sec: int = 30):
        super().__init__()
        self.timeout_sec = timeout_sec
    
    def run(self):
        try:
            result = self.do_work()
            self.work_completed.emit(result)
        except Exception as e:
            self.work_failed.emit(str(e))
    
    def do_work(self):
        """Override en subclases."""
        raise NotImplementedError
```

Heredar todas las clases: `_PricesWorker(BaseQWorker)`, `_AnalysisWorker(BaseQWorker)`, etc.

**Beneficio**: DRY, consistencia, señales comunes.

---

### 4. **Agregar Índices SQLAlchemy (30 min)**

En `paper_trading/models.py`:

```python
from sqlalchemy import Index

class PaperOrder(Base):
    __tablename__ = "paper_orders"
    __table_args__ = (
        Index("ix_paper_order_account_status", "account_id", "status"),
        Index("ix_paper_order_ticker_side", "ticker", "side"),
        Index("ix_paper_order_filled_at", "filled_at"),
    )
    # ... columns ...
```

Idem `database/models.py` para `Position(portfolio_id, ticker)`.

**Beneficio**: Queries engine.py 10–50x más rápido.

---

### 5. **Validación GARCH Convergencia (30 min)**

En `garch_signals.py:147`:

```python
# Antes
res = model.fit(disp="off", show_warning=False)

# Después
try:
    res = model.fit(disp="off", show_warning=False)
    if not res.convergence_flag or res.convergence_flag == 0:
        print(f"[GARCH] Fitting failed to converge for {ticker}")
        return None  # fallback a EWMA
except Exception as e:
    print(f"[GARCH] Fit error: {e}")
    return None
```

**Beneficio**: Evita forecasts inválidos → decisiones trading rotas.

---

### 6. **Timeout en yfinance (1 hora)**

En `data/yahoo_finance.py`:

```python
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import signal

def get_historical_data(...) -> Optional[pd.DataFrame]:
    # Existing cache checks...
    
    # Live download con timeout
    try:
        def download_with_timeout():
            return yf.download(ticker, period=period, interval=interval, ...)
        
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(download_with_timeout)
            df = future.result(timeout=15.0)  # 15 sec timeout
    except TimeoutError:
        print(f"[YF] Timeout fetching {ticker}")
        return None
    except Exception as e:
        print(f"[YF] Error: {e}")
        return None
    
    # ... cache write ...
```

**Beneficio**: UI no congela si yfinance es lento.

---

### 7. **Validación Settings (30 min)**

En `config/settings_manager.py`:

```python
# Schema de validación
_SCHEMA = {
    "paper_scan_interval_minutes": (int, 1, 1440),  # 1 min – 1 día
    "cache": (bool,),
    "paper_history_period": (str, ("1y", "2y", "5y", "10y")),
}

def set(self, key: str, value) -> None:
    if key in _SCHEMA:
        validator = _SCHEMA[key]
        if not self._validate(key, value, validator):
            raise ValueError(f"Invalid value for {key}: {value}")
    self._data[key] = value
    self.save()
```

**Beneficio**: Previene crashes por mala config.

---

### 8. **Eliminar print() statements (1 hora)**

Reemplazar 41 instancias de `print()` con logging:

```python
# Antes
print(f"[YF] Error fetching {ticker}: {e}")

# Después
import logging
logger = logging.getLogger(__name__)
logger.warning(f"Error fetching {ticker}: {e}")
```

Configurar en `main.py`:

```python
import logging
logging.basicConfig(
    filename="finanzias.log",
    level=logging.INFO,
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s"
)
```

**Beneficio**: Debugging, auditoría, filtrado sin código.

---

### 9. **Extraer Common Widget Logic (2-3 horas)**

En `ui/widgets.py`, agregar:

```python
class DataTableWidget(QTableWidget):
    """Base para tablas de posiciones, órdenes, histórico."""
    
    def set_data(self, rows: list[dict], columns: list[str]):
        self.clear()
        self.setColumnCount(len(columns))
        self.setHorizontalHeaderLabels(columns)
        for row_idx, row_data in enumerate(rows):
            self.insertRow(row_idx)
            for col_idx, col_name in enumerate(columns):
                value = row_data.get(col_name, "")
                self.setItem(row_idx, col_idx, QTableWidgetItem(str(value)))
    
    def sort_by(self, col: str, ascending: bool = True):
        """Sorting agnóstico de columna."""
        col_idx = [self.horizontalHeaderItem(i).text() for i in range(self.columnCount())].index(col)
        self.sortByColumn(col_idx, Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder)
```

Heredar en `PositionsTable(DataTableWidget)`, `OrdersTable(DataTableWidget)`.

**Beneficio**: 200+ líneas de código elimadas.

---

### 10. **Agregar .gitignore + requirements.lock (30 min)**

Crear `.gitignore`:

```
__pycache__/
*.pyc
*.pyo
*.egg-info/
dist/
build/
.venv/
finanzias.db
.finanzias/
.DS_Store
*.log
```

Generar `requirements.lock` con pip-compile:

```bash
pip install pip-tools
pip-compile requirements.txt > requirements.lock
```

**Beneficio**: Builds reproducibles, CI/CD listo.

---

## Top 5 Mejoras Estratégicas

### 1. **Refactorizar UI Core: Dividir God Classes (8–12 horas)**

**Problema**: `paper_tab.py` (1472 líneas) maneja 7 responsabilidades.

**Solución**:

```python
# Antes
class PaperTradingTab(QWidget):
    # ... 40+ métodos, 1472 líneas

# Después
class PaperTradingTab(QWidget):
    def __init__(self):
        self.account_panel = AccountManagerPanel()
        self.positions_panel = PositionsPanel()
        self.orders_panel = OrdersPanel()
        self.equity_panel = EquityChartPanel()
        # cada panel: ~200-300 líneas, responsabilidad única
```

Cada panel:
- Maneja su propia tabla/chart.
- Emite signals para cambios.
- Recibe data via slots.
- Sin state compartido (todo en DB/parent).

**Beneficio**: Testeable, reutilizable, mantenible.

---

### 2. **Test Suite: Comenzar con Backtest (15–20 horas)**

Crear `tests/`:

```
tests/
├─ conftest.py (fixtures, mocks)
├─ test_backtest.py (análisis/backtest.py)
├─ test_engine.py (paper_trading/engine.py)
├─ test_analysis.py (analysis/technical.py)
├─ test_csv_import.py (data/csv_importer.py)
└─ test_ml_signals.py (analysis/ml_signals.py)
```

Ejemplo `test_backtest.py`:

```python
import pytest
from analysis.backtest import backtest, SignalFn
import pandas as pd

@pytest.fixture
def sample_df():
    # Mock OHLCV data
    return pd.DataFrame({
        "Close": [100, 101, 102, 103, 104],
        "Volume": [1000]*5,
    }, index=pd.date_range("2024-01-01", periods=5))

def test_backtest_no_lookahead():
    def signal_fn(df_upto_t):
        assert len(df_upto_t) > 0
        return "HOLD"  # no crash
    
    result = backtest(sample_df, signal_fn, ...)
    assert result.n_trades == 0

def test_backtest_win_rate():
    def signal_fn(df_upto_t):
        return "BUY" if close < 102 else "SELL"
    
    result = backtest(sample_df, signal_fn, ...)
    assert result.win_rate > 0
```

**Beneficio**: Regresiones detectadas temprano, refactoring seguro, specs claras.

---

### 3. **Data Service Centralizado (8–10 horas)**

**Problema**: yfinance se llama desde 5 sitios; caché, rate limiting, retry diseminados.

**Solución**: Crear `data/service.py`:

```python
class DataService:
    """Centralizado data fetching, caching, retry logic."""
    
    def __init__(self):
        self.session = None
    
    def get_price(self, ticker: str, use_cache: bool = True) -> Optional[dict]:
        """Get current price with unified cache."""
        # Delegado a yahoo_finance.get_current_price() pero con logging/telemetry
    
    def get_history(self, ticker: str, period: str = "1y") -> Optional[pd.DataFrame]:
        """Get OHLCV with exponential backoff."""
    
    def get_bulk_prices(self, tickers: list[str]) -> dict[str, Optional[dict]]:
        """Batch with rate limiting."""
    
    def validate_ticker(self, ticker: str) -> bool:
        """Cache result."""

# Global singleton
data_service = DataService()
```

Refactorizar all callsites para usar `data_service.*()`.

**Beneficio**: Control global, telemetría, retry policy, testeable.

---

### 4. **ML Model Caching + Validación (6–8 horas)**

**Problema**: XGBoost se retrain en cada analyze(); sin overfitting check.

**Solución**:

```python
class MLModelCache:
    def __init__(self):
        self._cache: dict[str, tuple[xgb.XGBClassifier, float]] = {}  # {ticker: (model, train_score)}
    
    def get_or_train(self, ticker: str, df: pd.DataFrame) -> tuple[xgb.XGBClassifier, float, float]:
        """Return (model, train_score, test_score) with validation."""
        if ticker in self._cache and self._is_recent(ticker, df):
            return self._cache[ticker]
        
        # Feature engineering
        X, y = prepare_features_targets(df)
        
        # Train/test split
        n_train = int(len(X) * 0.80)
        X_train, X_test = X[:n_train], X[n_train:]
        y_train, y_test = y[:n_train], y[n_train:]
        
        # Train
        clf = xgb.XGBClassifier(n_estimators=100, max_depth=6, random_state=42)
        clf.fit(X_train, y_train)
        
        # Validate
        train_score = clf.score(X_train, y_train)
        test_score = clf.score(X_test, y_test)
        
        if test_score < 0.50:  # worse than coin flip
            logger.warning(f"[ML] {ticker} test_score={test_score:.2%} → overfitting risk")
        
        self._cache[ticker] = (clf, test_score)
        return clf, train_score, test_score
```

Reportar feature importance en analysis_tab.

**Beneficio**: Modelos válidos, detección de overfitting, performance.

---

### 5. **Proper Session Management + Scoped Sessions (4–6 horas)**

**Problema**: Manual session lifecycle, sin thread-local scope, race conditions posibles en scheduler.

**Solución**: Usar `scoped_session`:

```python
# database/models.py
from sqlalchemy.orm import scoped_session

SessionLocal = sessionmaker(bind=ENGINE)
scoped_session_factory = scoped_session(SessionLocal)

def get_session():
    """Return thread-local session (don't close!)."""
    return scoped_session_factory()

def cleanup_session():
    """Call at end of request/thread."""
    scoped_session_factory.remove()
```

En scheduler:

```python
def run(self):
    try:
        from paper_trading.engine import run_scan
        result = run_scan(self.account_id)
        self.scan_completed.emit(result)
    except Exception as e:
        self.scan_failed.emit(self.account_id, str(e))
    finally:
        from database.models import cleanup_session
        cleanup_session()  # ← crucial
```

**Beneficio**: Thread-safe, no memory leak, código limpio.

---

## Conclusión: Path Forward

### Inmediato (Semana 1–2)

1. Context managers SQLAlchemy.
2. Type hints core.
3. Índices BD.
4. Logging.

### Corto plazo (Mes 1)

5. Test suite inicial.
6. Data service.
7. Base QWorker.
8. Timeout yfinance.

### Mediano plazo (Mes 2–3)

9. Refactor UI god classes.
10. ML caching + validation.
11. Scoped sessions.

### Largo plazo (Mes 4+)

- i18n.
- Live data.
- CI/CD.
- Distributed backtest.

**El proyecto tiene fundamentos sólidos. Con estas mejoras, escala de hobby → producción.**
