# Auditoría de logs — 2026-10-19

Pedido de Chapa (2026-10-19): *«parece que hay errores en el log, correr auditoria»*, con el
punto de partida `main.py:95: UserWarning: This figure includes Axes that are not compatible with
tight_layout, so results might be incorrect.` Área **L (logs)**, con lo de **H (operación)** que el
censo toque. Tarea **368**.

## 1. Kill-criteria (congelados el 2026-10-19 a las 12:45 locales, antes de abrir el log)

- **Mira:** el censo de firmas WARNING+ y tracebacks de `~/.finanzias/finanzias.log` desde el cierre
  de la tanda anterior (**2026-10-10 01:00 local**) hasta ahora, separadas por origen (sin marca =
  la app; `[proceso: …]` = otro proceso). Además, lo que **no pasa por el logger** y Chapa ve en la
  consola: los `warnings` de Python, como el de `tight_layout` (por qué no llega al log es parte de
  la pregunta). Y `congelamientos.log` en la misma ventana.
- **Busca:** (→) firma **desconocida**: sin tarea y sin explicación verificada contra el código;
  (←) firma **conocida** que sigue apareciendo después del cierre de su tarea (349–364, y la 351 del
  parquet, la 340/364 de XGBoost), clasificada **con su tasa** contra la que midió el cierre; (←) lo
  que debería verse y no se ve: un aviso que la app emite fuera del log (el `UserWarning` va a
  stderr de la consola, no a `finanzias.log`).
- **Afuera:** el contenido de los INFO, salvo que delate una falla; la infraestructura de AWS (355,
  362), que todavía no escribe en este log; si una decisión de trading fue buena.
- **Limpio:** ninguna firma sin clasificar; ninguna conocida reaparece después de su cierre ni con
  una tasa mayor que la medida al cerrar; y el `UserWarning` de `tight_layout` tiene causa nombrada
  (archivo y figura) y o es benigno con el motivo verificado, o tiene tarea.
- **Conflicto declarado:** las tareas 357 y 362 de hoy las hizo esta misma sesión; las firmas que
  aparezcan de `news_sources` o del harvest se contrastan contra el código, no contra lo que dice su
  registro.

## 2. Alcance real

- **Mirado:** `~/.finanzias/finanzias.log` desde la línea del 2026-10-10 01:00 hasta las 12:51 del
  2026-10-19 (603 líneas WARNING+ en 37 firmas, 15 firmas de traceback); `congelamientos.log` en la
  misma ventana; los once widgets de matplotlib de `ui/` instanciados offscreen con el warning
  convertido en error; una copia de `finanzias.db` del 2026-10-19 (`price_cache`, `failed_tickers`,
  `paper_watchlist`, `paper_positions`, `positions`); los frames de `data/parquet/WBD__*`.
- **NO mirado:** la salida de consola (stderr) de la app más allá del warning que trajo Chapa: no se
  guarda en ningún lado ([L-4]); los logs de la Lambda (CloudWatch).
- **El instrumento, validado:** el censo normaliza los tickers a `TK`, así que una firma junta varios
  tickers. La primera lectura dio *«$MARA possibly delisted ×74»*, y MARA era sólo el ejemplo del
  grupo: contados por ticker, son 26 líneas de **WBD** (más sus `[repetido N veces]`) y 2 de cada
  ticker del throttle del 13/10. Los conteos por ticker de abajo son de un segundo barrido sin
  normalizar.

## 3. Hallazgos

### [L-1] WBD dejó de cotizar el 2026-10-05 y la app lo sigue tratando como vivo
Severidad: **MEDIUM** · Confianza: **ALTA** · Categoría: logs (firma desconocida) / operación
Ubicación: `data/yahoo_finance.py:1498-1562` (`_fetch_ticker_info`: `fast_info.last_price` no vacío
cuenta como éxito y llama a `record_success`); el guardado del histórico (`Historical data for WBD: 1
rows · zero/neg={'Open': 1}` a INFO y el frame se escribe).
Evidencia: `yf.Ticker("WBD").history("5d")` vacío y `"1y"` con **una** barra (2026-10-05), medido hoy;
`yf.Search("Warner Bros Discovery")` devuelve sólo listados europeos (`J5A.*`, `4WBD.TI`) y noticias
*«What to know about the landmark Warner Bros. Discovery sale»*, *«Paramount and Warner Bros.
Discovery Are Now Skydance»*. En la DB: `price_cache` de WBD en **30,95 constante**, 272 filas del
12 al 19/10; `failed_tickers` **sin** WBD; WBD en `paper_watchlist` de la cuenta 2 y en el universo
vivo (127, el mismo que se subió a la nube el 16/10). `data/parquet/WBD__2y__1d.parquet` tiene **1
fila** (2026-10-05, `Open` 0), reescrito hoy a las 11:37; el `1y` y el `10y` siguen en el 09/09. En
el log: `$WBD: possibly delisted; no price data found (period=5d)` en 26 líneas (varias con `[repetido 25
veces]`) desde el 12/10, a nivel ERROR del logger de yfinance, y nada de la app.
Razonamiento: `fast_info` devuelve el último precio conocido aunque la serie ya no tenga barras, así
que el circuito de tickers muertos (B3/UNIV1) ve un éxito; y el histórico que trae una sola barra con
`Open` 0 pisa un `2y` de dos años, porque el QA lo registra y no lo rechaza.
Impacto: hoy chico —WBD no tiene posición y con una barra `analyze()` no compra—, pero el universo
vivo tiene un ticker muerto que nadie marca, la nube lo recolecta, y **si hubiera tenido posición**
el stop se habría evaluado contra un precio congelado que no se mueve nunca. Es la forma general:
un ticker que deja de cotizar por compra o fusión no se detecta.
Verificación: si el precio se movió (no, 30,95 en todas las lecturas); si WBD está en
`failed_tickers` o lo filtra algo (no); si Yahoo lo lista con otro símbolo en EE.UU. (no).
¿Por qué no antes? **(a)**: los errores empiezan el 2026-10-12, después de la tanda del 10/10.
Acción: (1) sacar WBD de la watchlist de la cuenta 2 y del universo (y republicar el de la nube, o
esperar a la 356 alcance 8); (2) que un ticker cuya serie diaria no avanza en N ruedas hábiles
mientras el resto sí, o cuyo precio de `fast_info` no cambia en N días, cuente como muerto y avise;
(3) que el guardado del histórico no pise un frame largo con uno de 1 fila / `Open` 0. → tarea **369**.

### [L-2] El breaker de throttle oscila: un fetch exitoso lo cierra y le resetea el nivel en medio de un throttle
Severidad: **MEDIUM** · Confianza: **ALTA** (mecanismo) / **MEDIA** (impacto) · Categoría: logs / operación
Ubicación: `data/yahoo_finance.py:258-275` (`_note_fetch_success`), llamado desde
`_fetch_ticker_info:1561` en cada fetch exitoso.
Evidencia: el 13/10, de 19:17:00 a 21:10:46, **44 aperturas y 44 cierres** del breaker; la
secuencia abre y cierra en 0–1 s (`19:28:28 abierto`, `19:28:29 cerrado`; `19:29:10` las dos); 28 de
los cierres dicen *«Yahoo se recuperó tras 0 min»*. Hubo 13 escaladas (a nivel 2 nueve veces, a 3
tres, a 4 una), y cada cierre volvió el nivel a 0, así que el incidente de dos horas se registró como
44 incidentes cortos. Dos scans con **127/127 tickers sin precio** y las posiciones sin evaluar.
Antes del 13/10, a lo sumo dos cierres de 0 min por día.
Razonamiento: con un throttle **parcial** algunos fetches que ya estaban en vuelo terminan bien; el
primero cierra el breaker aunque el lote siguiente vuelva a fallar entero. El de-bounce de
`_note_throttle` (una escalada por cooldown) queda sin efecto la mayor parte del tiempo, porque el
cooldown se borra antes de vencer.
Impacto: durante un throttle la app sigue pegándole a Yahoo en vez de frenar (el breaker existe
para eso), el aviso de outage (nivel ≥ 2) se dispara y se apaga, y el log afirma 44 veces una
recuperación que no pasó.
Verificación: el código de `_note_throttle`/`_note_fetch_success`/`_should_attempt_fetch`; que
ninguna tarea cerrada lo haya decidido así (`grep` de *«tras 0 min»*, *flapping* y del breaker en
el backlog y las tandas: nada).
¿Por qué no antes? **(a)**: el mecanismo existía, pero la manifestación de esta magnitud es del
13/10, posterior a la tanda.
Acción: que el cierre exija algo más que un éxito suelto —p. ej. sólo el probe canario cierra, o N
éxitos seguidos dentro del cooldown no lo cierran—, con un test de throttle parcial; y que el
mensaje de recuperación no diga *«tras 0 min»* cuando el incidente sigue. → tarea **370**.

### [L-3] El `UserWarning` de `tight_layout` es del gráfico de Análisis, y su causa es una línea, no matplotlib
Severidad: **LOW** · Confianza: **ALTA** · Categoría: logs (fuera del logger) / claims caducados
Ubicación: `ui/chart_widget.py:68` (`Figure(..., tight_layout=True)`) + `ui/chart_widget.py:102`
(`add_gridspec(3, 1, height_ratios=[3, 1, 1], hspace=0.08)`), en `plot_price_with_indicators`.
Evidencia: los once widgets de `ui/` instanciados offscreen con `warnings.simplefilter("error")`:
sólo `ChartWidget.plot_price_with_indicators` lo dispara. Mínimo, con matplotlib 3.11.0 (Anaconda y
`.venv`): `Figure(tight_layout=True)` + `add_gridspec(..., hspace=0.08)` → warning; sin `hspace` →
nada. Los tres ejes tienen `subplotspec`: lo incompatible es el `hspace` explícito.
Razonamiento: `tight_layout` no puede respetar un espaciado fijado a mano y lo avisa.
Impacto: cosmético (el layout del gráfico de precio puede no ajustarse), pero el claim que lo
explica dirige mal: la revisión de arquitectura (`docs/architecture_review_2026-07-07.md` §5) lo
atribuye a *«matplotlib embebido»* y la idea de *Ideas* (*«pyqtgraph para el chart de Analysis … mata
el warning `tight_layout`»*) propone una migración para algo que es una línea.
Verificación: los otros diez widgets (Home, Métricas con `twinx`, dona, sparkline, Paper); el `grep`
del warning en el backlog (sólo la idea y la [K-2] de una tanda, que no lo trata).
¿Por qué no antes? **(b)**: va a stderr, no al log; ninguna corrida de `logs` mira la consola.
Acción: sacar el `hspace` (o pasar a `layout="constrained"`), verificarlo con el mismo instrumento, y
corregir la idea y el §5 de la revisión. → tarea **371**.

### [L-4] Los `warnings` de Python no llegan al log: el censo es ciego a ellos
Severidad: **LOW** · Confianza: **ALTA** · Categoría: logs (lo que no aparece y debería)
Ubicación: `main.py`, `config/logging_config.py`: ningún `logging.captureWarnings(True)` ni
`filterwarnings` (`grep` sin resultados en `main.py`, `config/` y `ui/main_window.py`).
Evidencia: el `UserWarning` de [L-3] lo vio Chapa en la consola, y no está en `finanzias.log`.
Razonamiento: `warnings.warn` escribe en stderr, que la app no persiste; un `FutureWarning` de pandas
o un `UserWarning` de sklearn —el aviso típico de un cambio de conducta al subir una dependencia— no
queda en ningún archivo.
Impacto: el censo de logs, por construcción, no ve una familia entera de avisos; el único registro
es la consola si alguien la mira.
Verificación: si el `.bat` redirige stderr a un archivo (no se encontró ninguna redirección en
`main.py`; el `.bat` no se miró línea por línea → MEDIA para esa pata, ALTA para el código Python).
¿Por qué no antes? **(c-metodo)**: el método de L pregunta por *«un `except` que loguea a `debug`»*
como lo invisible, y no por lo que nunca pasa por el logger.
Acción: `logging.captureWarnings(True)` al configurar el log (con un filtro para no repetir la misma
línea en cada redraw), y agregar al método L de la skill `auditoria` la pregunta por stderr y los
`warnings`. → tarea **372**.

## 4. Firmas clasificadas (sin hallazgo)

| firma (origen app salvo aclaración) | n | clase | motivo |
|---|---|---|---|
| XGBoost *unstable model* | 157 | conocida (340/364) | tasa por scan en baja: ~10 el 07/10, 3 el 16/10, y **hoy 12 en el primer scan y 0 en los 7 siguientes**: es la evidencia en vivo de la 364 (su (3) sigue abierto hasta un día entero). |
| `$TK possibly delisted` del 13/10 (2 por ticker) y `N Failed downloads` | ~40 | explicada | el throttle del 13/10 ([L-2]); la línea vacía de yfinance es la cabecera multilínea del lote. |
| `['JNJ', 'INTU'] possibly delisted (2y)` hoy | 1 | explicada | fallo transitorio de un lote del build de surprise; los dos perfiles salieron con n=24 a los 15 s. |
| `MARAMLTX` (price/analyst) | 4 | conocida (366) | typo de la pestaña Análisis; la limpieza de fallidos es la 366. |
| Throttle detectado / persiste / recuperó (13–14/10) | 103 | → [L-2] | 46 aperturas, 44 cierres, 13 escaladas |
| news_sources caídas del 14/10 22:11 (yfinance, SEC, Finnhub ×32 c/u) | 96 | conocida (353) | red caída al volver de una suspensión de 6.531 s (el Vigía lo dice); la 353 (reintento) cerró el 16/10. |
| `fetch_cik_map failed` 13/10 | 1 | explicada | timeout a `www.sec.gov` durante el incidente de red. |
| `yfinance news fetch failed for ON` (*YAHOO! FINANCE IS CURRENTLY DOWN*) 14/10 | 1 | explicada | Yahoo caído; `failed` como corresponde. |
| Harvest `FUENTES MUDAS: yfinance_news 0/127` | 12 | conocida (354 → 357) | la 357 lo arregló hoy (`fd09118`); la app corre el código de antes hasta reiniciarse. |
| Slack *send failed (fail-open)* + tracebacks de `slack.com` | 5 + 16 | explicada | timeouts y DNS de los mismos dos incidentes; fail-open por diseño. |
| *cachean la barra de la sesión de HOY* | 14 | conocida (112) | una línea por lote, por diseño. |
| Vigía *trabada 2.0 s* / *no latió N s* | 7 | explicada | umbral de aviso del vigía; las dos largas son suspensiones del equipo. |
| `Nube — FUENTE NO DISPONIBLE` | 1 | conocida (356) | falta el perfil `[finanzias-lector]` (Acciones manuales). |
| `N/127 tickers sin precio` (10/10 y hoy) | 2 | **sin identificar del todo** | el mensaje no nombra los tickers cuando no hay posiciones afectadas; no se pudo saber cuáles son (WBD no: tiene precio congelado). Queda como limitación, no como hallazgo. |
| `[proceso: medir364]`, `[proceso: python -c]` | 26 | explicada | mediciones a mano de la 364 y un dry-run de la 357; el origen está marcado. |

**`congelamientos.log`:** en la ventana sólo están las dos suspensiones del 14/10. Nada nuevo.

## 5. Rechazados

Ninguno publicado. Se corrigieron en el camino, antes de publicar: el *«MARA possibly delisted ×74»*
de la primera lectura (era la normalización del censo, no MARA; ver §2), y en [L-2] dos números del
primer borrador —*«47 aperturas»* (eran 44) y *«el nivel nunca pasó de 2»* (llegó a 4)—, recontados
por día y por nivel con `Select-String`.

## 6. Limitaciones y deuda de la skill

- No hubo hallazgos HIGH/CRITICAL, así que no pasó por el `verificador`.
- [L-4] es **(c-metodo)**: al método L le faltaba preguntar por lo que nunca pasa por el logger
  (stderr, `warnings`). La mejora concreta va en la 372.
- La consola de la app no se guarda: lo que Chapa vio es el único registro de [L-3].

## 7. Hallazgo → tarea

| hallazgo | tarea |
|---|---|
| [L-1] | 369 |
| [L-2] | 370 |
| [L-3] | 371 |
| [L-4] | 372 |
