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

## Resultado

*(se completa después de correr el script; el pre-registro de arriba no se toca)*
