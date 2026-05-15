# Auditoría del 7 de mayo de 2026

Snapshot histórico de la auditoría profunda que se hizo sobre el proyecto el
2026-05-07. **No es la guía actual de trabajo** — varios de los hallazgos ya
están atendidos en commits posteriores. Se conserva como referencia.

Contiene tres documentos:

- [`ANALISIS_FINANZIAS.md`](./ANALISIS_FINANZIAS.md) — análisis general,
  arquitectura, 5 puntos críticos.
- [`HALLAZGOS_POR_ARCHIVO.md`](./HALLAZGOS_POR_ARCHIVO.md) — desglose por
  archivo con problemas puntuales.
- [`EJEMPLOS_REFACTOR.md`](./EJEMPLOS_REFACTOR.md) — código de ejemplo
  para las correcciones recomendadas.

## Estado de los hallazgos al 2026-05-15

Verificación contra el código de la rama `main` ocho días después.

### Resueltos

| Hallazgo (2026-05-07)                                 | Estado actual                                                                 | Commit(s)                                  |
| ----------------------------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------ |
| 46 `session.close()` en bloques `finally`             | 0 llamadas en producción; `session_scope` se usa en 20 archivos               | `e545935`, `3a06a5b`                       |
| Tablas sin índices declarativos                       | 7 índices en `database/models.py` + 6 en `paper_trading/models.py`            | `e545935`                                  |
| Migraciones ad-hoc en `_migrate()`                    | Alembic adoptado (`alembic.ini`, `alembic/versions/0001_baseline.py`)         | `3a06a5b`                                  |
| Sin lint configurado de forma estricta                | `ruff` + `pyproject.toml` con reglas E/W/F/I/B/UP/SIM/RUF; pre-commit         | `3a06a5b`, `b791370`                       |
| Sin suite de tests                                    | 104 tests (94 originales + 10 nuevos en `test_real_portfolio.py`)             | `3a06a5b`, `064f9bc`, `af888ff`            |
| Compatibilidad rota con yfinance 1.x / pandas 2.x     | Pins y adaptaciones en `requirements.txt` y código                            | `55761eb`                                  |
| Duplicación en `ui/paper_tab.py` y `ui/analysis_tab.py` | Extraídos a submódulos `ui/paper/` y `ui/analysis/`                         | `27b02df`, `4e9dfb8`                       |

### Mejorados pero no cerrados

- **Type hints**: subieron de ~30 % (mayo 7) a **~62 %** (419 de 672
  funciones tienen alguna anotación). Queda ~38 % sin anotar — sobre todo
  en `ui/`.

### Aún válidos

- **`DB_PATH` hardcodeado** relativo al archivo en `database/models.py`. Si
  el módulo se reubica, la ruta rompe. Mover a `config/settings_manager`
  como ruta configurable.
- **Threading sin timeout/cancellation uniforme**: los QThread workers
  (PriceWorker, DividendWorker, SignalWorker, RsiScanWorker, ReportWorker,
  AnalysisWorker, …) siguen sin un patrón común para cancelar / time-out.
  Ver `ui/workers.py` (`BaseWorker` definido pero adopción parcial).
- **Validación estadística del modelo ML** en `analysis/ml_signals.py`:
  sin cross-validation, sin matriz de confusión, sin reporte de
  overfitting. Sigue siendo riesgo para decisiones de trading real.

## Por qué se archivó

Los tres documentos describen problemas que en su mayoría ya están
atendidos. Dejarlos en la raíz del repo confundía a quien abre el
proyecto por primera vez ("¿estos problemas son actuales?"). Moverlos
a `docs/auditoria_2026-05-07/` preserva el trabajo como referencia
histórica y deja claro su contexto temporal.
