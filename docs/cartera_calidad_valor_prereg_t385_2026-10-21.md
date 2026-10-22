# Pre-registro — cartera de calidad y valor de largo plazo (tarea 385), 2026-10-21

**Congelado antes de correr.** Este documento se commitea antes de que exista el runner y antes de
ver ningún número de la cartera. Lo único que ya se conoce es la medición de la 384 (el puntaje de
calidad solo no anticipó el retorno en este universo), y por eso se escribe acá: el criterio no se
relaja por ella ni se endurece por ella.

## La pregunta

¿Una cartera de largo plazo que compra negocios de calidad con descuento, y los mantiene un año, le
gana al **mismo universo comprado en partes iguales**, neto de costos? Es la propuesta de fondo de
`docs/libros_inversion_analisis_2026-10-21.md` §3 (palancas B y C). **No toca la cuenta 2.** Si una
cartera pasa, el paso siguiente es una cuenta paper nueva, en una tarea propia.

## Datos

- **Universo:** el de la cuenta 2 (`LIVE_UNIVERSE_FILE`), 126 tickers. **Sesgo de supervivencia
  declarado:** es la watchlist de hoy; las que quebraron o salieron no están. Infla a todas las
  carteras por igual, y por eso la comparación es siempre contra la cartera **Universo**, que tiene
  el mismo sesgo.
- **Precios:** el cohorte de 10 años (`load_bars_signals`, cierres ajustados por dividendos, o sea
  retorno total), con los guards de la 76 y la 86. **Ventana: 2016-09 → 2026-09.** El borrador de
  la tarea decía «~2011–2026»: EDGAR llega más atrás, pero los precios del cohorte no. Se declara.
- **Fundamentals:** el almacén point-in-time de la 382, con lo presentado **antes** de cada fecha.
- **Valor:** el retorno anual esperado de la 383 (*Buffettology*), con los cierres de Yahoo **sin**
  ajuste por dividendos y los splits (`get_cierres_sin_ajuste_por_dividendos`, `get_split_events`),
  cortados a lo anterior a cada fecha para el precio sobre ganancias histórico.
- **Calidad:** el puntaje de la 384, con la población del universo en cada fecha.

## Mecánica

- **Rebalanceo:** el **primer día hábil de abril** de cada año (cuando ya salieron los 10-K de los
  años fiscales a diciembre), de 2017 a 2026. Entre rebalanceos, la cartera se mantiene: no hay
  stops, ni señales, ni ventas intermedias.
- **Peso:** partes iguales entre los elegidos, en cada rebalanceo.
- **Costo:** **0,064%** de cada peso operado (compras y ventas del rebalanceo). Es el costo medido de
  la cuenta 2 al 20/10: $542,76 de comisión y slippage sobre $853.648 operados (tarea 386).
- **Un ticker sin precio** en un rebalanceo no entra ese año; uno que deja de cotizar en el medio se
  mantiene a su último cierre hasta el rebalanceo siguiente.
- **20 nombres** en las carteras que eligen.

## Las cinco carteras

| cartera | qué compra |
|---|---|
| **Universo** | todo el universo con precio, en partes iguales: la vara contra la que se miden las demás (el benchmark de la 377 llevado a la ventana) |
| **Calidad** | las 20 de mejor puntaje de calidad del negocio (384) |
| **Valor** | las 20 de mayor retorno anual esperado (383) |
| **Calidad + valor** | entre la mitad de mejor calidad, las 20 de mayor retorno esperado |
| **Azar** | 200 carteras de 20 nombres al azar (semilla 385), con los mismos rebalanceos: muestra cuánto gana una cartera de 20 sin elegir |

## Criterios de corte (congelados)

Una de las tres carteras que eligen —**Calidad**, **Valor** o **Calidad + valor**— **pasa sólo si
cumple los cinco criterios**, siempre contra la cartera **Universo**:

1. **Rendimiento:** su crecimiento anual compuesto neto de costos (CAGR, *Compound Annual Growth
   Rate*) es **al menos 1 punto por año mayor** que el de Universo.
2. **Que no sea suerte del período:** remuestreo por bloques pareado sobre la diferencia de retorno
   diario (`paired_block_bootstrap`, bloques de 20 días, 2000 remuestreos). El intervalo de confianza
   del 95% de la diferencia de crecimiento anual **no cruza el cero** (`ci_low > 0`).
3. **Riesgo:** su caída máxima, de un pico al piso siguiente (maxDD, *maximum drawdown*), **no es
   peor que la de Universo en más de 3 puntos**.
4. **Estabilidad:** le gana a Universo en **al menos 2 de 3** sub-ventanas: 2016-09 → 2019-12,
   2020-01 → 2022-12 y 2023-01 → 2026-09.
5. **Que sea selección y no tamaño:** su crecimiento anual queda **por encima del percentil 90** de
   las 200 carteras de Azar. Si no, lo que gana es tener 20 nombres, no haberlos elegido bien.

**Tres carteras, una sola oportunidad cada una:** no se agregan carteras, no se cambian los 20
nombres, ni la fecha de rebalanceo, ni el costo después de ver un número. Si ninguna pasa: **NO-SHIP**
documentado, y la 383 y la 384 siguen como display. Si pasa alguna: tarea nueva para una cuenta paper
en `auto` con su propio benchmark; con más de una, la de mayor límite inferior en el criterio 2.

## Controles antes de leer las diferencias

- **Universo reproduce el universo:** su retorno sin costos tiene que coincidir con el promedio de
  los retornos anuales de los tickers, rebalanceo por rebalanceo (control interno).
- **Sin mirar el futuro:** en cada rebalanceo, ningún fundamental usado tiene `filed` en o después de
  la fecha, y ningún cierre del precio sobre ganancias histórico es posterior. El runner lo verifica
  y aborta si no.
