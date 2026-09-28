# Tarea 235 — quién retiene el write lock en el arranque (2026-09-28)

**Veredicto:** el que retiene el lock es el **chequeo de alertas**, no el scan ni el harvest.
En el primer chequeo de cada día local, `AlertManager.check_alerts` re-arma las alertas del día
anterior con un `UPDATE` + `flush()`, que toma el write lock. Después, **con esa transacción
abierta**, pide el precio de cada ticker en serie, y cada `get_current_price` intenta escribir
`price_cache` por **otra** conexión. Esa escritura espera el lock que retiene su propio llamador
hasta agotar el `busy_timeout` de 30 s, y así con cada ticker. Mientras tanto, ninguna otra
escritura de la app puede entrar.

El kill-criteria decía *«si ninguna pasa los 30 s sola, se documenta la superposición y se cierra
sin código»*. **Una pasa, y por mucho**, así que el arreglo va como tarea aparte (**237**).

## 1. La reproducción

Sobre dos copias de `finanzias.db`, hechas con la API de backup de SQLite desde una conexión de
sólo lectura (la app estaba abierta). Las 10 alertas reales (5 tickers: AMT, CRM, LOW, MARA, PFE)
quedan activas, y el `price_cache` de esos tickers se borra para forzar el fetch. La duración del
lock se mide con listeners del `ENGINE`: desde la primera sentencia de escritura de cada conexión
hasta su `commit`/`rollback`. Script: `medir_lock.py` (scratchpad de la sesión, no versionado).

| caso | duración del chequeo | lock de la transacción de alertas | escrituras de `price_cache` |
|---|---:|---:|---|
| sin re-arme | 3,5 s | 0,00 s | 5, sin espera |
| **con re-arme** (1 alerta disparada ayer) | **163,3 s** | **163,3 s** | 5, cada una **~32 s** esperando y `database is locked` |

La diferencia entre los dos casos es **una sola fila** con `triggered_at` de ayer. El costo escala
con la cantidad de tickers de alertas cuyo precio no está en cache: 5 tickers, 163 s.

## 2. Los tres casos del log, explicados por horario

| error | contexto | por qué es el primer chequeo del día |
|---|---|---|
| CRM, 2026-09-23 18:51:31 | arranque a las 18:50:31 | la tarea 227, que agregó el re-arme, se commiteó ese mismo día a las **18:37**; antes de eso no hay ningún error |
| MARA, 2026-09-27 21:42:28 | arranque a las 21:39:51 | primer tick del timer de alertas (120 s), más 30 s de timeout ≈ 21:42:2x |
| MARA, 2026-09-28 00:02:29 | sin arranque | primer chequeo después de la **medianoche local**: el re-arme corta por día local (tarea 227) |

Y el arranque de hoy (11:29:42) **no** dio error. Encaja con lo mismo: el re-arme de las 00:02
ya había corrido para el día 28 local, y en ese mismo chequeo CRM `ABOVE` volvió a disparar
(`triggered_at` 2026-09-28 03:02:29 UTC = 00:02:29 local, leído de la copia). A las 11:29 no
quedaba nada disparado en un día anterior, así que no hubo `UPDATE` y el lock no se tomó.

El dato que la 234 no podía explicar —el scan del 27/09 commiteó a las 21:42:29, un segundo
después del timeout, con una fase `process` de sólo 22 s— también cierra: el scan estaba
**esperando este lock**, y lo obtuvo cuando el chequeo de alertas terminó.

## 3. Los otros candidatos

- **Rebuild de `surprise_profiles`:** no escribe la DB. Su docstring lo dice y el código de
  `scripts/build_surprise_profiles.py` no tiene ninguna sesión ni sentencia de escritura.
- **Scan y harvest:** **no se reprodujeron sobre la copia, a propósito.** El scan escribe el cache
  OHLCV en parquet, que se comparte con la app viva (abierta durante la medición), y dos procesos
  sobre ese cache se pisan. Quedan acotados por el log: en el arranque de hoy scan y harvest
  corrieron superpuestos (11:30:45–11:35:10) sin ningún `database is locked`, y los tres errores
  históricos quedan explicados por el mecanismo de §1 sin necesidad de ellos.
- **Classify:** no se midió (necesita Ollama). Escribe en lotes de 100 (`classify_catalysts.py`),
  y ninguno de los tres casos cae en un classify sin caer también en el primer chequeo del día.

## 4. Lo que se deriva

- **El riesgo real no es el precio de la alerta**, que desde la 234 se devuelve igual. Es que
  durante `30 s × N` tickers sin cache **no puede escribir nadie**: un scan que caiga en esa
  ventana espera 30 s y levanta `database is locked`. Con 1 ticker sin cache —el caso del 27/09—
  el scan llegó justo; con 5, no llegaría.
- **Arreglo → tarea 237:** que `check_alerts` no pida precios adentro de una transacción de
  escritura: re-armar en una sesión corta y commitear, pedir los precios **sin** transacción
  abierta, y escribir los disparos en otra sesión corta.
