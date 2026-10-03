# Auditoría — logs (censo) — 2026-10-02

Tarea **287**, primera corrida del área `logs` (categoría L, creada en la misma tarea a pedido de Chapa: *«una auditoría de logs, para buscar errores que no estemos viendo»*). READ-ONLY.

## 1. Kill-criteria (congelado antes de abrir el censo)

- **Ventana:** `~/.finanzias/finanzias.log` entero, **2026-09-07 → 2026-10-02**. Es el único log que queda: las rotaciones `.1`–`.3` (anteriores a la 78, contaminadas por la suite) se borraron hoy, a pedido de Chapa (276). En este archivo, las credenciales están enmascaradas desde hoy (`token=***`), lo que no cambia ninguna firma.
- **Población:** toda línea WARNING, ERROR o CRITICAL, y todo traceback.
- **Firma:** `(nivel, módulo, mensaje normalizado)`, con tickers → `TK`, números → `N`, URLs y rutas fuera. Para un traceback: `(tipo de excepción, último frame del repo)`.
- **Clasificación**, una por firma: *conocida* (con la tarea que la explica o la arregló), *explicada* (benigna, con el motivo verificado contra el código), o *desconocida* (se investiga y, si no se puede explicar, va a la cola).
- **Se busca además:** firmas que siguen apareciendo **después** del cierre de su tarea (el arreglo no arregló), y `except` de caminos de fondo que loguean a `debug` (invisibles en producción, que corre en INFO).
- **Afuera:** el contenido de los INFO, salvo que delate una falla. El log de la sesión de hoy **después** de las 18:45 (app cerrada desde entonces; los arreglos de las 262–282 todavía no corrieron en vivo).
- **Barrido limpio:** ninguna firma sin clasificar, y ninguna *conocida* que siga apareciendo después del cierre de su tarea.

## 2. El censo

**39 firmas** de WARNING o superior y **10 firmas de traceback** (1.273 tracebacks). Todas
clasificadas; el método (normalización y agrupado) está en §1.

### Conocidas: tienen tarea, y ninguna sigue apareciendo después de su cierre

| firma | n | ventana | tarea | ¿sigue después del cierre? |
|---|---|---|---|---|
| la última barra *«todavía no asentó»* (aviso por ticker) | 1.506 | 09-09 → 09-30 | consolidado en un aviso por scan el 10-01 | no: desde el 10-01 sale el aviso agrupado (8 líneas) |
| `XGBoost: unstable model` | 394 | 09-07 → 10-02 | la 25 (volumen) / *Calidad de datos* | sigue, **por diseño** (diagnóstico conocido del modelo vivo) |
| `surprise rebuild failed … ImportError PROFILES_PATH` | 389 | 09-10 → 09-11 | 197 | no (última 09-11) |
| `Error fetching price` + `database is locked` en `session_scope` | 3 + 6 tb | 09-23 → 09-28 | 234 / 237 | no (última 09-28) |
| `los frames … difieren por un factor` / `Referencia de escala … confiable` | 15 + 5 | 09-07 → 09-10 | 63 / 64 / 156 (AVB) | no (última 09-10) |
| throttle de Yahoo (abierto, escalado, recuperado), `Invalid Crumb`, `Unauthorized`, `possibly delisted` sobre tickers vivos | ~150 | 09-07 → 10-02 | NET1, B3 | sigue, **por diseño** (Yahoo; el breaker lo maneja) |
| `N/N tickers sin precio este scan` | 9 | 09-10 → 09-23 | B3 (telemetría) | sigue, por diseño |
| `ACENTURE … possibly delisted` | 3 | 10-01 | — | un ticker mal tipeado en la búsqueda; quedó en `failed_tickers` (ver `docs/auditoria_pantalla_resto_2026-10-02.md`) |

### Explicadas: benignas, con el motivo verificado

- **2026-09-21, red caída:** `collect_finnhub_news`/`_sec_8k`/`yfinance news fetch failed` (362 ERROR) con **1.202 tracebacks** de `ConnectionError`/`DNSError` (`NameResolutionError`). Un solo día, sin internet. El harvest terminó con techo (la 204). **Lo benigno es la causa; el volumen es un hallazgo** (L-2).
- **2026-09-30 21:23, `Parallel fetch failed` ×48 + `RuntimeError: cannot schedule new futures after shutdown` ×48:** la app se cerró con un `get_bulk_prices` en vuelo. Al salir, Python apaga `_TIMEOUT_POOL` y los hilos que seguían no pudieron encolar. Después hay un hueco de 11 minutos y sólo líneas de `numexpr`. No se escribió nada a medias, pero **cada cierre así escribe ERRORES con traceback** (L-2).
- **2026-09-15, `Ollama backend failed` + 3 `ConnectionError` en `catalyst_classifier`:** Ollama caído; el clasificador cayó a la heurística, como está diseñado.
- **2026-09-23, `Slack notify: send failed` + 5 `ConnectTimeout`:** corte de red al mandar; *fail-open*, el scan siguió. El aviso de ese scan se perdió y quedó en el log como ERROR, que es lo correcto.
- **`yfinance:` con mensaje vacío ×2:** es la primera línea del encabezado de dos líneas `1 Failed download:` de yfinance.
- **Los `debug` con `exc_info` en caminos de fondo** (los avisos de salud de Slack en `yahoo_finance`, `scheduler` y `cuadre`; la escritura de `company_info`; dos warm-ups de Métricas): lo que loguean es lo que falla **fuera** del envío o en un cache best-effort. Si el envío a Slack falla, `post_to_slack` escribe su propio ERROR (el del 09-23).

### Desconocidas → investigadas → hallazgos

Dos firmas **no son de la app**:
- `cuadre: no se pudo cuadrar la cuenta N` ×2 (2026-10-02 20:36), con traceback en `paper_trading/cuadre.py`: **las escribió mi corrida a mano** del cuadre contra la DB real, durante la tarea 266.
- `stooq: no se pudo normalizar la respuesta de AAPL` + `KeyError: 'Date'` (2026-09-07 21:23): el traceback pasa por **`.venv\Lib\site-packages`**, y la app corre en la Anaconda. Es una prueba de stooq corrida a mano en la época de la 202.

Más líneas de `numexpr` a las 21:34 y 23:54 del 09-30, con la app cerrada. Las dos cosas llevan a L-1.

## 3. Hallazgos

### [L-1] Cualquier script que importe un módulo del proyecto escribe en el log de producción, mezclado con la app y sin nada que los distinga
Severidad: **MEDIUM** · Confianza: **ALTA**

**Ubicación:** `config/logging_config.py:233-241`. `get_logger` llama a `setup_logging()` si nadie lo hizo, y el default es `~/.finanzias/finanzias.log`.

**Evidencia:** las tres corridas a mano de §2 (cuadre, stooq desde el `.venv`, `numexpr` con la app cerrada) están en el log de producción con el mismo formato que la app. El formato (`%(asctime)s [%(levelname)-7s] %(name)s: %(message)s`) no lleva ni proceso ni script.

**Razonamiento:** la 78 cortó esto para la **suite** (`FINANZIAS_LOG_FILE` vacío en el `conftest`). Los runners de medición, las verificaciones a mano y los scripts de la app siguen escribiendo ahí.

**Impacto:** el log es evidencia de auditoría (`operacion`, `rendimiento`, este censo), y un error de una prueba a mano se lee como un error de la app. Este mismo censo tuvo que investigar dos firmas que resultaron ser eso. Y al revés: una verificación a mano puede *«confirmar»* que algo corrió en vivo cuando corrió en un script.

**Acción:** que cada línea diga de qué proceso viene (el nombre del script, o `app`). O que un script fuera de `main.py` escriba en su propio archivo salvo que lo pida explícitamente.

→ tarea **288**.

### [L-2] Dos casos benignos escriben cientos de tracebacks: la red caída (1.202 en un día) y cerrar la app con un fetch en vuelo (48)
Severidad: **LOW** · Confianza: **ALTA**

**Evidencia (§2):**
- El 2026-09-21 cada `ticker × fuente` del harvest escribió un `log.exception` completo.
- El 2026-09-30, cada ticker del `get_bulk_prices` en vuelo escribió `Parallel fetch failed` con traceback.

**Impacto:** es el mismo daño de la 25 y la 197. Un día así entierra cualquier otro error del log: cualquier triage tiene que atravesar mil tracebacks idénticos.

**Acción:**
- **Red caída:** un traceback por fuente y por corrida, y un resumen con el conteo.
- **Cierre con fetch en vuelo:** reconocer el `cannot schedule new futures after shutdown` y loguearlo como un INFO de cierre.

→ tarea **289**.

## 4. Barrido limpio en lo demás

Ninguna firma queda sin clasificar, y ninguna *conocida* sigue apareciendo después del cierre de su tarea. Las que siguen apareciendo lo hacen por diseño: el diagnóstico de XGBoost, el throttle de Yahoo y la telemetría de precios faltantes.

## 5. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| L-1 | 288 |
| L-2 | 289 |
