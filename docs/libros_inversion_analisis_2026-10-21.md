# Diez libros de inversión contra lo que la app ya midió — 2026-10-21

Pedido de Chapa (2026-10-21): analizar diez libros y buscar formas de mejorar lo que gana la app,
convertirlas en tareas y después armar un plan de implementación. Este doc es el análisis. Las
tareas son de la **382** a la **386** en `docs/BACKLOG.md`, y el plan se arma aparte.

**Fuentes.** No se descargaron los libros: tienen copyright vigente. Las ideas van resumidas con
palabras propias, y se cruzan con fuentes abiertas: los memos de Howard Marks, que Oaktree publica
gratis; la literatura académica sobre los mismos efectos (Novy-Marx 2013 sobre rentabilidad bruta;
Asness, Frazzini y Pedersen 2014 sobre *quality minus junk*; Barber y Odean 2000 sobre rotación y
costos); y la documentación de la API de EDGAR. **Una aclaración sobre el n.º 6:** el *Little Book of
Value Investing* que conozco es el de Christopher Browne. Si el de la lista es otro, las ideas que
se le atribuyen abajo son las del de Browne.

## 1. Primero, lo que la app es y lo que ya se sabe de ella

Los libros hablan de **otra forma de invertir** que la de la app, y conviene decirlo antes de
proponer nada.

- **Qué hace hoy:** swing trading técnico y de ML sobre 127 large caps, con tenencia media de 12
  días. Entre el 20/06 y el 20/10 rotó el capital **17 veces** y pagó **$542 de costos**, un tercio
  de lo ganado (`docs/rendimiento_app_vs_cartera_2026-10-20.md`).
- **Lo que se midió:**
  - las compras no se distinguen del universo del mismo día (§2 del doc anterior; la **39**; la
    regla 3 con la 73);
  - la venta por señal no suma en 10 años (la **379**, ayer);
  - demorar la venta no pasa el gate (la **219**);
  - la política de salida está cerrada (la **170**).
- **El benchmark que ya existe:** la curva *«universo sin elegir»* de Home (la **377**). La cuenta
  2 da +3,2% contra +4,5% de su propio universo en partes iguales.

O sea: **hoy la selección no agrega y la rotación cuesta.** Es exactamente el diagnóstico que
repiten casi todos estos libros sobre el inversor que opera mucho.

## 2. Los diez libros, uno por uno

En cada uno: la idea central, qué dice de la app y si se puede medir con datos que tenemos.

**1. *Buffettology* (Mary Buffett, David Clark).** Comprar negocios con ventaja duradera, que la
autora llama *monopolios de consumo*: marca fuerte, rentabilidad sobre el patrimonio alta y estable
por muchos años, poca deuda y ganancias que crecen parejo. El precio de compra se juzga como una
tasa de retorno: se proyecta la ganancia por acción a diez años con su crecimiento histórico, se le
aplica el múltiplo histórico y se compara con el precio de hoy. → **Medible** con los estados
contables de EDGAR (ROE y EPS por año). Da dos piezas: un **puntaje de calidad** y un **retorno
anual esperado**.

**2. *The Intelligent Investor* (Benjamin Graham).** El precio y el valor son cosas distintas, y se
compra sólo con **margen de seguridad**. El mercado es un socio de humor cambiante al que se
aprovecha, no se le hace caso. Para el inversor defensivo propone criterios simples: tamaño,
solidez financiera, dividendos sin cortes, crecimiento de ganancias y múltiplos moderados (precio
sobre ganancias y sobre valor libro). → **Medible**: los criterios defensivos y el *número de
Graham* (√(22,5 · EPS · valor libro por acción)) salen de EDGAR.

**3. *One Up on Wall Street* (Peter Lynch).** Invertir en lo que uno entiende y clasificar cada
empresa: crecimiento lento, empresas firmes, crecimiento rápido, cíclicas, recuperaciones y
empresas con activos ocultos. Cada tipo se compra y se vende por razones distintas. Herramienta
estrella: el **PEG**, precio sobre ganancias dividido por el crecimiento. → **Medible**: el PEG y
una **categoría de Lynch** automática por crecimiento y ciclicidad.

**4. *Value Investing for Dummies* (Sander, Haley).** Manual práctico: leer balances, calcular el
valor intrínseco por varios caminos y armar una lista de chequeo antes de comprar. → No agrega una
señal nueva. Es el **checklist** que ordena las piezas de los demás en la pantalla de Analysis.

**5. *Financial Modeling & Valuation* (Paul Pignataro).** Cómo armar el modelo de tres estados y un
DCF, con valuación por múltiplos comparables. → El DCF completo **choca con el muro de datos** que
ya documentó la skill `fair-value-feature`: proyecciones *forward* gratis no confiables. Lo que sí
sirve: los **múltiplos** y un DCF simple como **banda de sensibilidad**, nunca como un número.

**6. *The Little Book of Value Investing*.** Comprar barato contra el valor contable o las
ganancias, diversificar y tener paciencia, porque el valor tarda en reconocerse. → Lo mismo que
Graham, más un punto que importa acá: **el horizonte es de años**, no de semanas.

**7. *The Most Important Thing* (Howard Marks).** Pensar en segundo nivel (qué espera el mercado, y
no sólo qué va a pasar), respetar los **ciclos** y el péndulo entre euforia y miedo, y entender el
riesgo como **pérdida permanente**, no como volatilidad. Sus memos son gratis. → La app ya detecta
el régimen. Lo nuevo sería una **temperatura del mercado** de valuación (cuánto del universo cotiza
sobre su valor estimado), como **contexto** y no como gatillo.

**8. *El arte de invertir* (Alejandro Estebaranz).** Value con calidad: negocios con ventajas
competitivas y buenos gestores, comprados con descuento y mantenidos mucho tiempo, con la mente
puesta en controlar el comportamiento propio. → Converge con 1 y 2: **calidad + precio + tiempo**.

**9. *The Millionaire Next Door* (Stanley, Danko).** No es un libro de bolsa: la riqueza se arma
gastando menos de lo que se gana, con disciplina y durante mucho tiempo. → Para la app, la lección
transferible es **no perder plata en fricción**: los costos y las vueltas.

**10. *The Four Pillars of Investing* (William Bernstein).** Teoría, historia, psicología y
negocio: el mercado es difícil de batir, los costos son la variable que uno sí controla, y para la
mayoría conviene diversificar en índices y rebalancear. → Es el libro que **mejor describe lo que
midió la app**: sin ventaja de selección, la rotación sólo suma costo. Su propuesta medible ya está
como benchmark (la 377).

## 3. Lo que tienen en común: cinco palancas

| palanca | libros | qué haría la app | evidencia fuera de los libros |
|---|---|---|---|
| **A. Menos fricción** | 9, 10, 7 | mostrar lo que cuesta rotar, y medirlo contra el benchmark | Barber y Odean: los hogares que más operan rinden peor, sobre todo por costos |
| **B. Margen de seguridad** | 2, 1, 5, 6, 8, 4 | un valor estimado propio, con el descuento al precio | la prima de value existe en la historia larga, pero fue débil entre 2010 y 2020 |
| **C. Calidad del negocio** | 1, 8, 2 | un puntaje de ROE estable, márgenes, deuda y crecimiento parejo | Novy-Marx y QMJ: la rentabilidad predice, y complementa al value |
| **D. Crecimiento a precio razonable** | 3 | PEG y categoría de Lynch | más débil como factor aislado; útil como contexto |
| **E. Ciclos y riesgo** | 7, 10 | temperatura de valuación del universo; riesgo como pérdida permanente | contexto, no un factor con evidencia propia |

**El punto incómodo que los libros comparten:** todos operan a **años**. La app opera a **días**.
Pegar un filtro de calidad o de valor a un swing de 12 días mezcla horizontes: el value tarda años
en pagar, y en dos semanas es ruido. Por eso la propuesta de fondo **no es ajustar la cuenta 2**.
Es probar, con backtest, una **estrategia distinta de largo plazo**. Si pasa, va como **cuenta paper
nueva** al lado de la 2, contra el mismo benchmark.

## 4. Con qué datos, y qué limita

- **Fundamentals point-in-time: SÍ hay.** Verificado hoy contra el payload real de EDGAR: cada dato
  de `companyfacts` trae su fecha de presentación (`filed`). Para KO, `NetIncomeLoss` tiene 233
  datos desde 2009, igual que `StockholdersEquity`, `GrossProfit` y `LongTermDebt`. Eso permite
  saber qué se sabía en cada fecha, sin look-ahead, y da **~15 años** de muestra (2011–2026), más
  que el cohorte de 10 de los harness.
- **Los tags cambian por empresa.** KO tiene sólo 4 datos de `EarningsPerShareDiluted`, y la **150**
  ya mostró que GS reporta el revenue con otro tag. Hace falta una cascada de conceptos
  alternativos y medir la cobertura antes de usar nada.
- **El universo es el de hoy.** Un backtest de 15 años sobre la watchlist actual tiene
  **survivorship bias**: las que quebraron o salieron del índice no están. Infla cualquier
  estrategia de largo plazo, y se declara en el pre-registro. Se mitiga comparando siempre contra
  el **mismo universo en partes iguales**, que tiene el mismo sesgo.
- **Large caps.** La evidencia de calidad y value es más débil en large caps que en small caps. El
  kill-criteria tiene que poder decir NO.
- **Lo que no se repite:** la 39 (el ranking actual no tiene alpha), la 219 (demorar la venta), la
  170 (la política de salida) y la T7. Ninguna propuesta de abajo toca esas perillas.

## 5. Las tareas

Siguen las reglas del repo: lo nuevo entra **display-only** (regla 3) y lo que toque decisiones
pasa por **backtest con kill-criteria congelado antes** (regla 2).

| tarea | qué | tipo | depende de |
|---|---|---|---|
| **382** | almacén **point-in-time** de fundamentals desde EDGAR, con cobertura medida | enabler (no decide nada) | — |
| **383** | **valuación en Analysis**: número de Graham, retorno esperado de *Buffettology*, margen de seguridad, PEG y categoría de Lynch, al lado del consenso | display | 382 |
| **384** | **puntaje de calidad** (ROE estable, margen bruto, deuda, crecimiento parejo) en Analysis y Leads, con su poder predictivo medido | display + medición | 382 |
| **385** | **cartera de largo plazo** calidad + valor, rebalanceo anual, contra el universo en partes iguales | backtest (regla 2) | 382, 384 |
| **386** | **lo que cuesta rotar**, visible en Home: costos y rotación acumulados al lado del benchmark | display | — |

La **temperatura del mercado** de Marks (palanca E) no va como tarea propia: sale gratis de la 383
(el porcentaje del universo sobre su valor estimado) y se agrega ahí si la 383 la deja barata.
