# Auditoría — datos — 2026-10-02

Tarea **273**, primera corrida del área `datos` (categoría I, creada por la 271). READ-ONLY. Kill-criteria congelado en `docs/auditoria_tanda_killcriteria_2026-10-02.md` §4.

## 1. Alcance real

**Mirado:**
- **`news_events` desde el 2026-09-01** (31.129 filas):
  - distribución de `classified_by`, `event_type`, `sentiment`, `classifier_confidence` y `relevance`;
  - contradicciones entre `sentiment` y `sentiment_score`;
  - cobertura por ticker del universo vivo;
  - duplicados por ticker + título, separando los de otra fuente en menos de 24 h.
- **`analyst_estimate_snapshots`:**
  - cobertura del último día contra el universo, y distribución por métrica;
  - saltos de más de 5× entre días consecutivos;
  - muestra contra la fuente primaria (Yahoo en vivo) para MU y TSM.
- **Facts de EDGAR** (`data/edgar_fundamentals.py`):
  - revenue anual contra el de Yahoo en 8 tickers al azar (`random.seed(261)`);
  - cobertura de revenue y net income en los 127 tickers del universo vivo.
- **El universo:** la watchlist de la cuenta 2 contra `data/harness_universe_live_acct2.txt`.

**NO mirado:**
- `earnings_cache`. Motivo: alimenta la sorpresa de resultados, que se mide en el pipeline de catalysts.
- La muestra de noticias contra el texto original del artículo. Motivo: las URLs exigen red por cada fila. La distribución y la coherencia interna se miraron; la verdad del contenido, nota por nota, no.

El diferimiento va como tarea **280**.

## 2. Hallazgos

### [D-2] Los snapshots de consenso no se ajustan por split, y el revenue viene en la moneda de reporte: una «revisión» medida a través de un split da −90%
Severidad: **MEDIUM** · Confianza: **ALTA**

**Evidencia:**
- **KLAC**, entre el 2026-06-11 y el 06-12: EPS `0q` 9,95 → 0,995, `+1y` 49,85 → 5,03, precio objetivo 1.869 → 190,5. Son saltos de 10× en todas las métricas el mismo día, que coinciden con su split 10:1 (los precios de KLAC fuera de banda de E5 eran ~1.942 contra ~194).
- **TSM:** el revenue de consenso es de **7,3 billones** para `+1y`. Yahoo da `financialCurrency = TWD`, mientras el EPS viene por ADR en USD (4,46 para `0q`).

**Razonamiento:**
- `analyst_estimate_snapshots` guarda el valor tal como lo devuelve Yahoo cada día, sin ajuste por split ni conversión de moneda.
- Hoy **ningún consumidor** decide con esta tabla: sólo la escribe `scripts/harvest_catalysts.py`.
- Su consumidor previsto es **T-CAT-5b** (las revisiones de consenso), justo el dataset que la 196 y la 245 están tratando de acumular.

**Impacto:** si el pre-registro de T-CAT-5b mide revisiones sin ajustar por split, cada split del universo aparece como una revisión de −50% a −96%. Y una comparación entre tickers del revenue en valor absoluto mezcla monedas.

**¿Por qué no antes?** (b) FUERA DE ALCANCE: el área no existía.

**Acción:** que el pre-registro de T-CAT-5b ajuste por split (con los splits de yfinance) y trabaje en cocientes dentro de cada ticker, o lo declare.

→ tarea **279**.

### [D-1] La misma nota de Yahoo entra dos veces por dos canales (yfinance y Finnhub), porque el dedup incluye la hora de publicación
Severidad: **LOW** · Confianza: **ALTA**

**Evidencia:**
- **1.988 pares** con el mismo ticker y el mismo título, de **fuentes distintas**, a menos de 24 h entre sí, sobre las 72.677 filas de la tabla (**2,7%**). Desde el 2026-09-01 son 1.054 sobre 31.129.
- El canal dominante es `yfinance` ↔ `finnhub:Yahoo`, con una hora de diferencia en la mediana.
- `content_hash` (`data/news_sources.py:183`) es `(ticker, título, published_at)`: dos canales con distinta hora de la misma nota dan dos hashes.

**Impacto:**
- La pestaña Noticias muestra la nota dos veces.
- `historical_reaction` y las mediciones de la 255 y la 258, que no deduplican, inflan su `n` ~3%. Sus veredictos (NO PASA) no cambian con eso.

**Acción:** deduplicar por ticker + título normalizado dentro de una ventana corta, entre fuentes.

→ tarea **280**.

### [D-3] SPG llega al screen con revenue y **sin** net income, y la cobertura declarada por la 149 sólo cuenta a los que no tienen ningún fact
Severidad: **LOW** · Confianza: **ALTA**

**Evidencia:** sobre los 127 del universo vivo, `get_fundamental_facts` da:
- sin ningún fact: ASML, TSM y XOM, ya declarados por la 149 y la 156;
- sin revenue: ninguno;
- **sin net income: SPG**, que está en cartera.

**Razonamiento:** con el fail-open del screen, la pata de rentabilidad no juzga a SPG. Un hueco **parcial** no entra en el conteo de *«sin facts»*.

**Acción:** que la cobertura declarada cuente por pata (revenue, net income), no por ticker.

→ tarea **280**.

**Corregido al cerrar la 280: el razonamiento de este hallazgo era falso.** La cobertura de la 149 (`scripts/run_universe_screen_validation.py`) **no** cuenta por *«algún fact»*: cuenta por `net_income_recent`, que es la pata que decide en el screen. SPG **sí** aparece, en la lista de *«SIN facts»*. Lo único engañoso era el rótulo (SPG tiene revenue); se cambió a *«SIN net income (la pata que decide)»*.

## 3. Barrido limpio en lo demás

- **Clasificación:**
  - 30.920 de 31.129 noticias por `ollama`, 83 por la heurística y 126 sin clasificar. Las 126 son de **hoy**: están en cola, no trabadas.
  - La confianza de 0,1 (la más frecuente, 27%) corresponde a `event_type = other` con relevancia 0,1: noticias irrelevantes, por diseño.
  - `sentiment` y `sentiment_score` se contradicen en **1** fila de 31.129.
- **Cobertura de noticias:** los 127 tickers del universo vivo tienen noticias desde el 2026-09-01.
- **Consenso:**
  - los 127 tickers tienen snapshot el 2026-10-02;
  - `eps` y `revenue` tienen valores distintos en todas las filas, sin nulos;
  - el EPS de MU (+1y = 204,8), que parecía un error, **coincide con Yahoo en vivo** (precio USD 1.074, forward EPS 205,3).
- **EDGAR contra Yahoo:** 7 de 8 coinciden exacto; WELL difiere 1,6% (concepto contable distinto); XOM no tiene revenue en EDGAR (la 149).
- **Universo:** la watchlist (127) contra el archivo del harness (126): la diferencia es ASML, declarada en el propio archivo (*«Sin PIT: ASML»*).

## 4. Hallazgos rechazados

- **«El EPS de MU es un dato roto»:** retirado antes de publicar, contrastándolo con la fuente primaria (§3).
- **El primer barrido de EDGAR** dio `TypeError` en los 8 tickers. Era el instrumento (`revenue_latest` es una property y se llamó como función), no la fuente. Se corrigió y se repitió.

## 5. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| D-1 | 280 |
| D-2 | 279 |
| D-3 | 280 |
| diferimiento (`earnings_cache`, muestra de noticias contra el original) | 280 |


## 6. Lo diferido, corrido al cerrar la 280

- **`earnings_cache`:** 55 tickers de 127 del universo, y **11 filas** con una *«próxima»* fecha ya pasada (la más nueva: MU, bajada el 08-12 para su reporte del 09-23). **Limpio:** el cache se llena a demanda —sólo con los candidatos que llegan al Gate 6—, y `get_next_earnings_date` sirve únicamente filas con `fetched_at` dentro de `EARNINGS_CACHE_HOURS = 24`; una fila vieja no se sirve nunca como próxima.
- **Muestra de 14 noticias clasificadas (no `other`, desde el 09-15, `random.seed(280)`), leídas a mano:** 12 razonables y **2 errores claros**. *«Why The Market Is Undervaluing Micron, Again (Earnings Preview)»* quedó `earnings_results`, cuando es un adelanto. Una nota de **Boeing** (*«Boeing Stock Rises After Pentagon Picks It for Navy Fighter»*) quedó asignada a **NOC** como `mna` positiva: es un contrato, y para NOC, que perdió, es más bien negativa. Como la 255 y la 258 midieron que el tono no predice, no abre tarea propia: va al enunciado de la **259** (el prompt de qwen).
