# Auditoría — rendimiento — 2026-10-02

Tarea **275**, primera corrida del área `rendimiento` (categoría J, creada por la 274). READ-ONLY. Kill-criteria congelado en `docs/auditoria_tanda_killcriteria_2026-10-02.md` §6.

## 1. Alcance real

**Mirado:**
- **`finanzias.log`** (del 2026-09-07 al 2026-10-02):
  - la duración de los **182 scans** con telemetría OPS1(c), contra `paper_scan_interval_minutes = 15`;
  - cada `database is locked`, fechado por la línea anterior con fecha.
- **`EXPLAIN QUERY PLAN`** de las consultas calientes, sobre la DB abierta en solo lectura. Se usaron las consultas **del código** (`fetch_news_window` de `analysis/news_digest.py:112-135` y la poda de `paper_trading/scan_candidates.py:161-163`), no las que escribí de memoria. Dos de mis versiones daban `SCAN` y la real de la poda no (§4).
- **Los guards de solapamiento** de los siete workers de `paper_trading/scheduler.py`.

**NO mirado:**
- El tiempo de render de la GUI. Motivo: es comodidad, no cambia conducta (fuera por kill-criteria).

## 2. Hallazgos

Ninguno. **Barrido limpio**, en las dos direcciones.

## 3. Lo que se midió

- **Duración de scan:** mediana **7,7 s**, p95 **132,5 s**, máximo **169 s**. **Ninguno** pasa su intervalo de 15 min. Los 15 que pasan de 120 s son el primer scan tras arrancar, con el cache frío (fetch 50-80 s).
- **Locks:** 3 `database is locked`, el 2026-09-23, el 09-27 y el 09-28, todos en `get_current_price` al escribir el cache. Son la 234 y la 237, cerradas el 09-28. **Ninguno después.**
- **Planes:**
  - las búsquedas por ticker y fecha de noticias, el dedup por `content_hash`, los pendientes de clasificar, los snapshots de equity, las órdenes por cuenta y estado, los candidatos por cuenta, la poda de la 256 y el upsert del consenso van **todos por índice**;
  - la única excepción es la ventana de la pestaña Noticias (`fetch_news_window`): hace `SCAN news_events` por el `OR` entre `published_at` y `fetched_at`. Pero tarda **0,061 s** sobre 72.677 filas (8.063 devueltas) y corre en un worker, no en el hilo de la GUI. Creciendo ~1.000 filas por día seguiría por debajo de medio segundo en un año. Queda como observación, sin tarea (no cambia conducta).
- **Solapamiento:** los siete workers (scan, surprise, catalysts diario, harvest horario, dashboard, archivo de la cinta, benchmark largo) chequean `isRunning()` antes de lanzarse (`scheduler.py:658, 707, 808, 882-884, 944, 985, 1023`). El harvest tiene techo de tiempo desde la 204.

## 4. Hallazgos rechazados

- **«La poda de `paper_scan_candidates` recorre la tabla entera»:** era mi consulta, filtrada sólo por `scan_at`. La del código filtra por `account_id` y `scan_at` y usa `ix_paper_scancand_account_scan`.

## 5. Mapeo hallazgo → tarea

Sin hallazgos; ninguna tarea.
