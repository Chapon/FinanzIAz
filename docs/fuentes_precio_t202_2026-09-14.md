# T202 — ¿Cuál es la tercera fuente de precio?

**Fecha:** 2026-09-14 · **Tipo:** análisis, sin código de producción · **Decide:** Chapa.

La regla ya está fijada (decisión de Chapa, 2026-09-13): **tres fuentes, manda la
mayoría**; sin mayoría, aprobación manual; si ninguna externa contesta, vende. Hoy hay
dos: Yahoo (el precio) y Finnhub (la segunda opinión). Esto elige **cuál es la tercera**,
antes de dar de alta ninguna key.

---

## 0. Veredicto contra el kill-criteria

Fijado antes de mirar: una fuente es candidata **sólo si** (a) su plan gratuito cubre el
uso **medido** —consultas del camino de excepción, más el refresh del cohorte si se usa
para histórico—; y (b) es **independiente de Yahoo**, o sea no revende sus datos,
verificado en su documentación.

| Fuente | (a) cubre el uso medido | (b) independiente de Yahoo | Veredicto |
|---|---|---|---|
| **Tiingo** | **SÍ** — 1.000/día y 50/h contra 1-2/día medidos; el cohorte entero en ~2,5 h | **SÍ, documentado** — cross-connect directo a IEX + 3 exchanges para EOD | **RECOMENDADA** (§6) |
| **Twelve Data** | **SÍ** — 800/día, 8/min; el cohorte en ~16 min | **SÍ**, con reserva: US equities de venues que suman **~5% del volumen** | **candidata**, segunda |
| **Alpha Vantage** | **NO** — **25 requests/DÍA** | no se verificó (ya falla (a)) | **descartada** |
| Stooq (ya integrada) | — | — | **inutilizable** — proof-of-work, **re-verificado hoy** |
| Finnhub (ya es la #2) | — | — | no aplica: es la fuente que hay que acompañar |

**Recomiendo Tiingo, y el argumento más fuerte no está en la tabla: ya está
implementada.** `TiingoProvider` vive en `data/providers.py` con sus tests; lo único que
falta es la key. Las otras dos piden un provider nuevo. Y es la única que devuelve
**`splitFactor` y precios ajustados por CRSP**, que es exactamente lo que el caso AVB
pide para arbitrar la *referencia* (§5.2).

---

## 1. El uso medido — el denominador del criterio (a)

El camino de excepción no es "cada scan": es `scale_is_disputed()`, o sea **los frames
`1d` cacheados no coinciden sobre el precio**. En el log se reconoce por *«escala en
disputa»*. Medido sobre los cuatro logs (2026-08-14 a 2026-09-14):

| Día | Disparos | Consultas reales (cota) |
|---|---:|---:|
| 2026-08-31 | 217 | 16 |
| 2026-09-01 | 130 | 17 |
| 2026-09-02 | 62 | 8 |
| 2026-09-03 | 1 | 1 |
| 2026-09-04 | 1 | 1 |
| 2026-09-07 | 2 | 2 |
| 2026-09-08 | 2 | 2 |
| 2026-09-09 | 1 | 1 |
| **Total** | **416** | **48** |

**Un disparo no es una consulta, y la diferencia es 8,7×.** `independent_price()`
memoiza por ticker con `_SECOND_OPINION_TTL_S = 900` s — **exactamente el
`paper_scan_interval_minutes` de 15**, así que un ticker en disputa cuesta **una**
consulta por scan, no una por evaluación.

**Los 416 disparos son de UN solo ticker: AVB.** No hay ningún otro en todo el historial
de log disponible.

Y hay **dos regímenes**, que es lo que la nota de *acciones manuales* (*«5 veces en la
última semana»*) no distingue:

- **Régimen normal (desde el 2026-09-03): 1-2 consultas/día.** El "~5 por semana" es
  cierto **para esta semana**.
- **Régimen de incidente (2026-08-31 a 09-02): hasta 17 consultas/día**, 10× más. Fue la
  ventana de AVB. Un plan gratuito hay que dimensionarlo contra **el pico**, no contra la
  mediana, porque el pico es justo cuando el guard tiene que funcionar.

**La cota patológica, que no pasó pero el diseño permite:** si los 127 tickers entraran
en disputa a la vez, son 127 consultas por scan × ~26 scans de RTH = **~3.300/día**. Es
el número que descarta cualquier plan de dos dígitos diarios.

**La otra mitad, si además se usa para histórico:** el refresh del cohorte son **126
tickers** (`data/harness_universe_live_acct2.txt`), en una ráfaga, de forma ocasional.
Ahí no manda el límite diario sino el **de minuto o de hora**.

---

## 2. El reencuadre que decide casi todo: la banda es ±50%

`arbitrate()` compara con `band = price_sanity_band_pct`, **verificado en vivo: 0.5**.
O sea que la tercera fuente no tiene que decir *cuánto* vale la acción: tiene que decir
si vale **68 o 184** — el caso AVB fue un desvío del **170%**.

**La pregunta es de escala, no de precisión.** Y eso cambia el peso de un criterio que
el enunciado listaba como discriminante:

> *«si da precio intradía o sólo cierre diario, y con cuánto retraso»*

Con una banda del 50%, **un cierre diario alcanza de sobra**: ninguna acción se mueve
50% intradía en condiciones normales, y si lo hiciera, el guard entero ya está en un
régimen anormal. Una fuente **EOD-only deja de ser un compromiso** y pasa a ser
candidata de primera — que es lo que habilita a Tiingo.

**La dependencia, declarada:** esto vale **mientras la banda sea ancha**. Si algún día se
angosta `price_sanity_band_pct` a, digamos, 5%, una fuente EOD empezaría a producir
veredictos `ninguno` falsos durante el día, y ahí sí haría falta intradía. **Angostar la
banda y quedarse con una fuente EOD son incompatibles**, y conviene que quede escrito
antes que alguien mueva la perilla.

---

## 3. Lo que ya hay, re-verificado en vivo (no heredado del docstring)

`data/providers.py` afirma tres cosas fechadas el 2026-09-07. Las tres se volvieron a
medir hoy en vez de creerles:

| Afirmación | Verificación 2026-09-14 | ¿Se sostiene? |
|---|---|---|
| Finnhub `/quote` funciona con la key existente | **HTTP 200** en 0,3 s (`AAPL`: c=334.55) | **Sí** |
| Las velas de Finnhub son premium | `/stock/candle` → **HTTP 403** *«You don't have access to this resource»* | **Sí** |
| Stooq devuelve proof-of-work en vez del CSV | HTTP 200 con `<noscript>This site requires JavaScript to verify your browser</noscript>` | **Sí**, sigue roto |
| Tiingo requiere `TIINGO_API_KEY`, que no está | `TIINGO_API_KEY` no seteada en el entorno | **Sí** |

**Una nota sobre las fuentes de terceros.** Varios sitios de reseñas dicen que el plan
gratuito de Finnhub incluye *«30+ años de datos diarios»*. **Para nuestra key eso es
falso**, y lo dice un 403 de hoy, no una opinión. Es la razón por la que el kill-criteria
pide verificar contra documentación vigente — y por la que acá se verificó además contra
el servicio.

---

## 4. Las candidatas, lado a lado

| | **Tiingo** | **Twelve Data** | **Alpha Vantage** |
|---|---|---|---|
| Límite gratuito | **50/hora · 1.000/día** · 500 símbolos únicos/mes | **8/min · 800/día** | **5/min · 25/día** |
| ¿Cubre 1-2/día? | sí, 500× de margen | sí, 400× | sí, 12× |
| ¿Cubre el pico de 17/día? | sí, 59× | sí, 47× | sí, **1,5×** — margen fino |
| ¿Cubre la cota patológica (3.300/día)? | no (1.000) | no (800) | no |
| ¿Cubre el cohorte (126 en ráfaga)? | **sí, ~2,5 h** (50/h) | **sí, ~16 min** (8/min) | **NO — 6 días** |
| Intradía | no, EOD | sí, US real-time | sí |
| Histórico ajustado por splits | **sí** — CRSP, con `adjClose` **y `splitFactor`** | no documentado en el free | sí |
| Términos del free | *Internal Use Only* — no mostrar ni compartir los datos | *Internal non-display usage* | uso personal |
| Código nuevo | **CERO** — `TiingoProvider` ya está escrito y testeado | provider nuevo | provider nuevo |

**Ninguna cubre la cota patológica**, y está bien: ese escenario (los 127 tickers en
disputa simultánea) significa que el cache de históricos se corrompió entero, y ahí el
problema no es el rate limit. Lo que hay que garantizar es el **pico real medido**, y las
tres lo cubren — Alpha Vantage con un margen de 1,5×, que es el que no aguanta un
incidente un poco peor que el de AVB.

---

## 5. Los dos criterios que separan

### 5.1 Independencia de Yahoo — el criterio (b)

No alcanza con *«no menciona a Yahoo»*: eso es ausencia de evidencia. Lo que se buscó es
que **documenten su propia procedencia**.

- **Tiingo — la mejor documentada.** Conexión física directa (cross-connect) a la
  **bolsa IEX** en el datacenter Equinix NY5, o sea el feed top-of-book de origen y no
  un revendido de un agregador; y para EOD, **3 exchanges** más un feed enterprise
  adicional, con un framework propio de limpieza y chequeo cruzado. Es exactamente lo
  contrario de depender de Yahoo.
- **Twelve Data — documentada, con una reserva que importa.** Para US equities, los
  precios salen de **venues que no requieren licencia adicional, que suman ~5% del
  volumen total**. Es su propio feed, no Yahoo — criterio (b) cumplido. Pero un
  compuesto de venues finos puede apartarse del tape consolidado. **A una banda del 50%
  da igual**; si la banda se angostara, empezaría a importar.
- **Alpha Vantage** — no se investigó: ya falla (a).

### 5.2 El caso AVB, que es el que motivó todo

El incidente no fue un precio raro: fue que **la referencia histórica quedó fuera de
escala** (184 contra 68, un 170%), y el guard no podía arbitrar porque los frames
cacheados se contradecían entre sí. Para resolver *eso* no alcanza con un precio de hoy:
conviene poder mirar **el histórico ajustado y el factor de split**.

**Tiingo es la única de las tres que expone `splitFactor`** junto con `adjClose`,
`adjOpen`, `adjHigh`, `adjLow`, `adjVolume` y `divCash`, con metodología CRSP declarada.
Con eso, un split fantasma se arbitra directamente contra un tercero en vez de
inferirse. Es la diferencia entre *«alguien más dice que el precio es 68»* y *«alguien
más dice que no hubo split»*.

---

## 6. Recomendación

**Tiingo.** Cuatro razones, en orden de peso:

1. **No pide código nuevo.** `TiingoProvider` ya está escrito, con tests, en
   `data/providers.py`. Las otras dos piden un provider desde cero. Dar de alta la key es
   una acción de 5 minutos contra una tarea de implementación.
2. **Es la única que sirve para el caso que motivó todo** (§5.2): `splitFactor` +
   ajuste CRSP arbitran la *referencia*, no sólo el precio.
3. **Su independencia es la mejor documentada** (§5.1): cross-connect a IEX, no un
   agregador.
4. **Una key desbloquea dos cosas, no una.** Además del rol de tercera fuente, destraba
   la mitad "histórico" de **ARQ3** —la cadena de fallback EOD— que según el propio
   docstring de `providers.py` está bloqueada **por la falta de esta key, no por
   código**. Hoy *«no hay un proveedor EOD de fallback sin dar de alta una key nueva»*;
   con Tiingo deja de ser cierto.

**Lo que se resigna, dicho claro:** Tiingo free es **EOD, no intradía**. Por §2 eso no
molesta a la banda actual del 50%, pero **ata una decisión futura**: si alguna vez se
angosta `price_sanity_band_pct`, hay que revisar esto. Y su límite de **50/hora** hace
que un refresh completo del cohorte tarde ~2,5 h — está bien para un batch ocasional, no
para algo interactivo.

**Si preferís intradía igual, la segunda es Twelve Data**: 800/día y 8/min cubren todo
con holgura y el cohorte entero sale en 16 minutos. El costo es un provider nuevo y un
feed de ~5% del volumen.

**Alpha Vantage queda descartada** por 25 requests/día: le alcanza para el día normal,
no para el pico medido con margen sano, y no puede tocar el cohorte.

### Una restricción de licencia que conviene no pisar

El free de Tiingo es **"Internal Use Only": no se puede mostrar ni compartir los datos
con otra persona u organización.** Para una app de escritorio personal eso está bien.
**Pero este proyecto publica un artifact de dashboard** (`scripts/refresh_dashboard.py`
inyecta `const DATA` en un `index.html`). Mientras Tiingo se use sólo como **árbitro**
—un veredicto, no una serie— no hay nada de Tiingo que mostrar. Si algún día se
enciende la cadena de fallback EOD y esos precios terminan en el dashboard, **y el
dashboard se comparte**, eso sí quedaría fuera del término. Vale la pena que quede
escrito ahora, que es barato, y no después.

---

## 7. Qué falta, y qué es acción tuya

1. **Dar de alta `TIINGO_API_KEY`** (gratis, sin tarjeta) y setearla en Windows con
   `setx TIINGO_API_KEY "..."` para que la vea la app y los jobs. Es acción tuya.
2. **Integrarla como tercera fuente va como tarea aparte** y depende de la **201**, que
   ya está cerrada. Lo que hay que escribir es poco: `second_opinion()` hoy es
   Finnhub-only (`QUOTE_SOURCE = "finnhub"`), así que la regla de mayoría de tres
   necesita que consulte **dos** externas y compare. `arbitrate()` es de dos fuentes y
   pasaría a ser de tres.
3. **No hace falta re-evaluar Stooq** salvo que quite el proof-of-work; queda en el
   código con su evidencia, ahora re-verificada.

---

## 8. Hallazgos laterales (regla 6)

1. **`arbitrate()` implementa la regla de DOS fuentes, no la de tres que decidiste.**
   Devuelve `price` / `reference` / `ninguno` / `sin_opinion` a partir de **una** sola
   opinión independiente. La regla que fijaste el 2026-09-13 —*«manda la mayoría; sin
   mayoría, aprobación manual»*— necesita **dos** externas para que haya mayoría que
   contar. No es un bug: es alcance que todavía no se escribió, y esta tarea lo deja
   dimensionado. Va como tarea (**206**).
2. **El «~5 por semana» de *Acciones manuales pendientes* describe el régimen normal y
   no el pico.** Medido: 1-2/día en régimen normal, **17/día** en el incidente de AVB —
   10×. El número no está mal, está incompleto, y es el que se usaría para dimensionar
   un plan gratuito. Corregido en esa nota.

---

## Anexo — cómo se midió

- **Uso del camino de excepción:** líneas *«escala en disputa»* de
  `~/.finanzias/finanzias.log{,.1,.2,.archivo_pre_t78_20260907}` (2026-07-12 a
  2026-09-14, sin hueco). Las consultas reales se acotan por **(ticker, balde de 15
  min)** distintos, que es lo que el memo de 900 s permite; contar los disparos
  sobrestima **8,7×**.
- **Banda y flag:** leídos con el loader real (`settings.get`), no del schema:
  `price_sanity_band_pct = 0.5`, `price_second_opinion_enabled = False`.
- **Cohorte:** 126 tickers, del header de `data/harness_universe_live_acct2.txt`.
- **Finnhub y Stooq:** una petición real a cada uno hoy, con la key que existe. Los
  códigos de respuesta están en §3.
- **Límites gratuitos:** de las páginas de precios de cada proveedor, consultadas hoy.

## Fuentes

- [Tiingo — pricing](https://www.tiingo.com/about/pricing) — 50/h, 1.000/día, 500 símbolos/mes, *Internal Use Only*
- [Tiingo — documentación EOD](https://www.tiingo.com/documentation/end-of-day) — ajuste CRSP, `adjClose`, `splitFactor`
- [Tiingo — perfil de proveedor](https://londonstrategicedge.com/directory/data-providers/tiingo/) — cross-connect a IEX, 3 exchanges para EOD
- [Twelve Data — pricing](https://twelvedata.com/pricing) — plan Basic: 800/día, 8/min, *internal non-display*
- [Twelve Data — US equities market data](https://support.twelvedata.com/en/articles/9935903-us-equities-market-data) — venues que suman ~5% del volumen
- [Alpha Vantage — premium](https://www.alphavantage.co/premium/) — *«25 API requests per day»*
- [Finnhub — pricing](https://finnhub.io/pricing) — free 60/min, no comercial
