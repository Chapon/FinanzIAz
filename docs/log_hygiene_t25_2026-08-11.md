# Tarea 25 — LOG-HYGIENE: el spam de WARNING/ERROR tapaba los errores reales

**Fecha:** 2026-08-11 · **Tipo:** gate técnico (NO toca decisiones de trading) · **Resultado:** SHIP
**Ref:** triage del log de runtime 2026-07-22 · `docs/BACKLOG.md` tarea 25

---

## 1. El problema

Dos fuentes de ruido enterraban los errores accionables del log:

- **(a)** el WARNING `XGBoost: unstable model` disparaba en ~la mitad de los
  tickers de cada scan, sumado a una línea INFO de `val_acc` por ticker
  entrenado → cientos de líneas por scan.
- **(b)** el ERROR `<TICKER>: Yahoo web request for share count failed` de
  yfinance, transitorio y ya manejado, compitiendo visualmente con fallos reales.

## 2. (a) El umbral estaba clavado en la mediana — medido, no asumido

El backlog afirmaba que `WALKFORWARD_STD_WARN=0.08` caía "en la mediana (~8%)"
del std observado entre folds. **Se midió sobre los 134 frames 2y/1d del cache
Parquet vivo** en vez de asumirlo:

| percentil | val_std |
|---|---|
| p5 | 0.0311 |
| p10 | 0.0493 |
| p25 | 0.0606 |
| **p50 (mediana)** | **0.0760** |
| p75 | 0.0971 |
| **p90 (decil superior)** | **0.1105** |
| p95 | 0.1168 |
| p99 | 0.1259 |
| max | 0.1317 |

La afirmación **se confirma**: 0.08 cae justo arriba de la mediana y dispara en
**55/134 = 41%** de los tickers. Un umbral en la mediana marca a la mitad de la
población *por construcción* — no discriminaba nada.

| umbral | dispara en |
|---|---|
| 0.08 (viejo) | 55/134 = **41.0%** |
| 0.10 | 30/134 = 22.4% |
| 0.11 | 14/134 = 10.4% |
| **0.12 (nuevo)** | **6/134 = 4.5%** |
| 0.13 | 1/134 = 0.7% |

Se eligió **0.12**: cae entre p95 y p99, o sea claramente en la cola, y es el
valor que el backlog ya había estimado a ojo (el decil superior real resultó ser
0.1105, no 0.12 — la estimación del enunciado erraba por poco).

**Hallazgo lateral:** el `val_acc` medio de esos mismos 134 tickers da **0.5076**
— un coin flip. Es la confirmación de la tarea 9 (AUC OOS 0.498) sobre el
universo real completo. Por eso la inestabilidad **no es un bug a arreglar**:
es inherente a una señal sin alpha, y por eso esto es higiene de log y no una
alerta de calidad de modelo.

## 3. (a) Qué se hizo

1. `WALKFORWARD_STD_WARN`: **0.08 → 0.12**, con la distribución medida citada en
   el comentario del código para que no vuelva a la mediana sin argumento.
2. La línea `val_acc=X% ± Y%` per-ticker pasó de **INFO a DEBUG** — era la mitad
   del volumen y solo sirve cuando se diagnostica un ticker puntual.
3. **Resumen agregado por scan**, al estilo de la telemetría OPS1(c): `ml_signals`
   acumula los entrenamientos y `drain_training_summary()` devuelve una línea que
   el engine agrega a `ScanResult.summary()`:

   ```
   XGB entrenados=134 val_acc medio=51% inestables=6
   ```

   El acumulador cuenta entrenamientos *desde el último drain*, así que un
   análisis ad-hoc de Analysis/Leads entre dos scans se suma al resumen del scan
   siguiente. Es telemetría de log, no contabilidad — preferible a acoplar
   `ml_signals` con el ciclo de vida del scan.

## 4. (b) Share count: degradado, no descartado

El mensaje sale de `yfinance/base.py` (dos sitios, `logger.error`), que devuelve
`None` y sigue — o sea que **ya está manejado**. Se sumó al filtro existente
`data/yf_noise.py` (el patrón de UNIV1).

**Decisión: degradar a DEBUG en vez de descartar.** El ERROR no es informativo
pero el evento sí — correlaciona con los eventos de throttle, así que sirve para
diagnosticar. Es la diferencia con los 404 de `quoteSummary`, que no aportan nada
y se tiran. Cualquier otro mensaje de yfinance pasa intacto y con su nivel
original: el filtro existe para **destapar** errores reales, no para taparlos.

## 5. Kill-criteria (gate técnico) — PASÓ

| Criterio | Resultado |
|---|---|
| Suite Windows verde | ✅ **1507 passed, 3 skipped** (8 tests nuevos) |
| El log baja de cientos de líneas XGB a un puñado | ✅ **189 → 7** (ver abajo) |
| `share count failed` no aparece a nivel ERROR | ✅ verificado contra el logger real instalado |
| No toca decisiones de trading | ✅ solo niveles de log y un umbral de warning |

### Volumen de log medido (134 tickers reales)

| | líneas ≥INFO por scan |
|---|---|
| **Antes** | **189** (134 INFO `val_acc` + 55 WARNING inestables), en **todos** los scans |
| **Después — 1er scan del día** | **7** (6 WARNING outliers + 1 resumen) |
| **Después — scans siguientes** | **0** |

El "en todos los scans" del antes no es retórico: hasta la tarea 24 el cache no
sobrevivía, así que las 189 líneas se repetían cada ~15 min. Las dos tareas se
componen — la 24 bajó la *frecuencia* del entrenamiento y la 25 el *volumen* de
cada uno.

Verificación de (b) end-to-end: con el filtro instalado, dos `share count failed`
no llegan a un handler de nivel INFO, mientras un error nuevo pasa a ERROR intacto.

## 6. Anotado, fuera de alcance

- El WARNING de inestabilidad sigue en WARNING (no se bajó a DEBUG): con 4.5% de
  disparo ahora es raro y marca un outlier real, así que conviene que se vea.
- El umbral se calibró contra un snapshot de 134 tickers de **un** momento. 0.12
  cae entre p95 y p99, con margen suficiente para que la elección no dependa del
  día; si el universo cambiara mucho, re-medir con el mismo script.
