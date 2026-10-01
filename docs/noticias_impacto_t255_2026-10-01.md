# Tarea 255 — ¿El sentimiento de una noticia predice el retorno a 5 días? (pre-registro)

**Fecha del pre-registro:** 2026-10-01, **antes** de mirar ningún retorno. Lo que sigue se fija
acá y no se mueve después de ver el número.

## Por qué

La columna *Impacto* de la pestaña Noticias es hoy `signo(sentimiento) × EVENT_PRIORS[tipo] ×
CONF_FLOOR`: una tabla de búsqueda (±0.36 para toda noticia de resultados o FDA). Se lee como un
impacto esperado. La pregunta es si el **signo** que pone el clasificador tiene información
sobre el retorno siguiente. Si no la tiene, ninguna fórmula que parta de él puede llamarse
impacto esperado. La reacción histórica que ya existe (`historical_reaction.json`) no sirve
para esto, porque no está condicionada al sentimiento.

## Datos

- **Noticias:** `news_events` con `sentiment ∈ {positive, negative}` y ticker con frame `1y` en
  `data/parquet/` (se leen directo del parquet, sin red). `published_at` está en UTC.
- **Ventana:** publicadas desde el 2026-06-01 (antes de eso hay menos de 10 noticias no neutrales
  por mes) hasta la última fecha con las 5 ruedas de salida completas. Se descarta la barra del
  día de la corrida (sesión sin asentar, T112).
- **Lectura de la DB:** sólo lectura (`mode=ro`).

## Definiciones

- **Entrada:** la primera apertura **posterior a la publicación**, en hora de Nueva York. Si la
  noticia sale antes de las 09:30 ET de una rueda, se entra en la apertura de esa rueda; si sale
  después, en la de la rueda siguiente. Es lo que se podría capturar de verdad: el movimiento que
  la noticia describe (*«la acción salta»*) queda afuera.
- **Salida:** el cierre de la quinta rueda contando la de entrada (`Close[e+4]`).
- **Retorno en exceso:** el del ticker menos el de SPY en la misma ventana (apertura → cierre).
- **Unidad de análisis:** `(ticker, rueda de entrada)`. Una misma noticia sale hasta 14 veces
  (ACN el 2026-10-01). Por eso se cuenta `neto = #positivas − #negativas` sobre las noticias de
  esa unidad: neto > 0 es **positiva**, neto < 0 es **negativa** y los empates se descartan.

## Métrica y veredicto

**Primaria:** `Δ = media(exceso | positiva) − media(exceso | negativa)`, en todas las categorías.

**IC 95%:** bootstrap **por rueda de entrada** (se re-muestrean ruedas enteras, porque las
unidades del mismo día comparten mercado), 5.000 réplicas, semilla 255.

**PASA** —el signo tiene información y vale diseñar un impacto direccional medido— si se cumplen
las **cuatro**:

1. `Δ > 0`;
2. el límite inferior del IC 95% es mayor que 0;
3. `Δ ≥ 0,5 pp` (por debajo de eso no paga el costo de ida y vuelta del modelo de costos de la
   cuenta);
4. el signo de `Δ` es el mismo en las dos mitades: junio–julio y agosto–septiembre.

**NO PASA** si falla cualquiera. En ese caso la columna **no puede presentarse como impacto
esperado**: el cambio de la pestaña es mostrar la clasificación y su base, no un número
direccional. Qué se muestra exactamente lo decide Chapa con esta medición delante.

**Secundaria (se reporta y no cambia el veredicto):** el mismo `Δ` restringido a
`event_type = earnings_results`, que es la mayor parte de los ±0.36. Si la primaria no pasa y
esta sí, se reporta como hipótesis para una tarea aparte, sin cablear nada.

**Se reporta también:** `n` de cada grupo, cantidad de ruedas, y el efecto mínimo detectable
(≈ 2,8 × el error estándar del bootstrap) para que un NO PASA diga cuánto efecto descarta.

## Lo que esto NO es

Display. No se cablea nada a sizing ni a gates (regla 3), pase lo que pase.

## Resultado (2026-10-01) — **NO PASA**

Corrida: `python scripts/measure_news_sentiment_fwd5_t255.py`. El pre-registro de arriba no se
tocó. 25.554 noticias no neutrales, 131 tickers con frame `1y`.

| | n+ | n− | ruedas | exceso + | exceso − | **Δ** | IC 95% | MDE | jun–jul | ago–sep |
|---|---|---|---|---|---|---|---|---|---|---|
| **Primaria** | 1.652 | 880 | 81 | −0,33 pp | +0,09 pp | **−0,42 pp** | [−0,93, +0,10] | 0,73 pp | −0,75 | −0,07 |
| `earnings_results` | 547 | 268 | 76 | −0,49 pp | +0,18 pp | **−0,66 pp** | [−1,59, +0,28] | 1,34 pp | −0,75 | −0,59 |

**Desvío declarado: los frames `1y` estaban atrasados.** Al agregarle al script un reporte de
frescura (los guards del cohorte no miran estos frames), salió que **123 de 131 frames `1y`
terminan el 2026-09-09**: la app viva mantiene al día los `2y`, no los `1y`. Con `1y` se perdió
casi todo septiembre, el mes con más noticias. El pre-registro fijó `1y` y por eso la tabla de
arriba es la corrida pre-registrada; abajo, la misma medición con `--period 2y` (4 frames
atrasados: AAPL, AVB, MLTX, TEAM), que no cambia ninguna definición, sólo la cobertura:

| `--period 2y` | n+ | n− | ruedas | exceso + | exceso − | **Δ** | IC 95% | MDE | jun–jul | ago–sep |
|---|---|---|---|---|---|---|---|---|---|---|
| **Primaria** | 2.485 | 1.235 | 81 | −0,70 pp | −0,41 pp | **−0,29 pp** | [−0,72, +0,13] | 0,61 pp | −0,64 | −0,07 |
| `earnings_results` | 740 | 339 | 77 | −0,68 pp | −0,20 pp | **−0,48 pp** | [−1,35, +0,38] | 1,24 pp | −0,57 | −0,46 |

**El veredicto es el mismo con las dos coberturas.** En las dos corridas fallan tres de las
cuatro condiciones: Δ no es positivo, el IC incluye el 0 y Δ < 0,5 pp. La
cuarta (mismo signo en las dos mitades) se cumple, pero con signo **negativo**.

**Qué dice y qué no:**

- **El signo del clasificador no predice el retorno siguiente en la dirección que la columna
  muestra.** Y no es sólo falta de muestra: el límite superior del IC (+0,10 pp; +0,13 con `2y`) está por
  **debajo** del umbral de +0,5 pp, así que un efecto positivo del tamaño que importa **queda
  descartado** con esta muestra. Es distinto de la 73, que no detectaba nada pero no descartaba.
- **La estimación puntual es negativa**: después de una noticia positiva el ticker rinde algo
  menos que SPY, y después de una negativa, algo más. Encaja con que la noticia **describe** un
  movimiento que ya pasó (el *«la acción salta»* queda antes de la entrada) y después revierte.
  **No es significativo** (el IC incluye el 0), así que es hipótesis, no hallazgo, y no se cablea.
- **La secundaria tampoco pasa**, así que no queda ni una hipótesis por categoría para abrir otra
  tarea.

**Límites:** una sola ventana (junio–septiembre 2026, 81 ruedas, un único régimen de mercado);
las neutrales quedan afuera por diseño; el clasificador es casi todo `ollama` (66.460 de 68.181
filas clasificadas).

**Consecuencia, según lo pre-registrado:** la columna **no puede presentarse como impacto
esperado**. Qué se muestra en su lugar lo decide Chapa.
