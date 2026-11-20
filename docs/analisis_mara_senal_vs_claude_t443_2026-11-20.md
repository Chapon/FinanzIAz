# MARA: la señal general dice «Comprar» y Claude «Vender» — análisis (tarea 443, 2026-11-20)

Origen: la opinión de MARA del 2026-11-20 03:57Z (`version_datos` 7), reportada por Chapa. Read-only: no
cambia código; lo que hay que hacer sale como tareas (445–448).

## Resumen

- **La etiqueta y el número salen de las mismas señales con dos reglas distintas.** «Comprar» es *quién
  gana* entre compra y venta, por poco que sea; el «Consenso 48/100» es *por cuánto* gana sobre el total
  (los neutrales incluidos), menos una penalidad por volatilidad. Divergen cada vez que la compra gana
  por poco. Y la etiqueta pinta igual una compra débil que una moderada.
- **No es sólo lo que se ve: es la regla de entrada de la cuenta 2.** La estrategia `analyze_single`
  toma como candidata toda señal de compra, también la débil. Desde el 2026-10-02 registró 20.981
  candidatas: **el 36 % (7.528) con el consenso neutral y 44 con el consenso bajista**. Las 33 compras
  hechas tenían todas el consenso en 0,55 o más, porque el ranking ordena por ese puntaje y sobran
  candidatas (el 2026-11-20: 32 para 3 lugares). Hoy el desacuerdo no llegó a ninguna compra.
- **(2) No se puede medir:** de 19 opiniones guardadas, una sola contradice la señal (MARA).
- **(3) No hace falta cambiar el prompt:** ya le dice que las señales no tienen poder predictivo
  demostrado, y en MARA explicó por qué la descartaba.
- **Los faltantes:** la 440, la 441 y la 442 (que entraron el mismo día) cubren parte; salen cuatro tareas nuevas, de la 445 a la 448.

## (1) De dónde sale cada uno, y en cuántos divergen

**La señal general** es `aggregate_signals` (`analysis/technical.py:577`): cada indicador pesa según su
fuerza y el régimen; se suman los pesos de compra y los de venta, y **gana el mayor**. La fuerza es la
parte del ganador sobre **todo** lo emitido, neutrales incluidos: 0,60 o más es fuerte, 0,40 o más
moderada, y si no, débil. `to_yahoo_level` (`technical.py:79`) pinta *Comprar* tanto la compra débil
como la moderada; sólo la fuerte cambia de rótulo. En MARA: RSI y MACD en compra débil, el cruce de
medias en venta, los otros cuatro neutrales → compra débil → **«Comprar»**.

**El consenso** es `compute_signal_probability` (`analysis/ml_signals.py:1268`), con los mismos pesos:
`(compra − venta + total) / (2 · total) − riesgo × 0,08`. Con cuatro neutrales en el total, un margen
chico queda cerca de 0,5, y el régimen BEAR de MARA (riesgo 0,86) le resta 0,07 → **48, neutral**.

**¿Es lo que se quiere mostrar?** La etiqueta dice más que la señal: *«Comprar»* arriba de *«2 alcistas
· 1 bajistas · 4 neutrales, consenso neutral»*. Lo honesto es rotular la fuerza (*«Comprar (débil)»*),
que sigue diciendo lo que el motor hace con esa señal → **tarea 448** (display).

**En el motor**, en cambio, no se toca sin backtest (regla 2): la cuenta 2 usa `analyze_single`
(`paper_trading/strategies.py:450`, `if res.overall_signal == "BUY"`) y ordena las candidatas por el
consenso (`_default_strength`). En `paper_scan_candidates` (cuenta 2, desde el 2026-10-02):

| | candidatas BUY | consenso ≥ 0,55 | 0,45–0,55 | < 0,45 |
|---|---:|---:|---:|---:|
| todas | 20.981 | 13.409 | 7.528 | 44 |
| compradas | 33 | 33 | 0 | 0 |
| último scan (2026-11-20 13:34Z) | 32 | 16 | 16 | 0 |

Un piso de consenso para la entrada no habría cambiado ninguna de las 33 compras. El caso en que
importaría —menos candidatas alcistas que lugares libres— no pasó en la ventana; si se quiere
cerrarlo, es un experimento de trading con su pre-registro, no un arreglo de display.

## (2) Cuando la señal y Claude se contradicen, ¿quién acertó?

Las 19 filas de `claude_opinions` hasta la de MARA (no hay reemplazadas; la de NVDA llegó después, ver la 449): Claude dijo **MANTENER en 17**; en 13 la señal
decía comprar o vender y Claude, mantener; **una sola contradicción directa, MARA** (señal BUY débil,
Claude VENDER 55). Con n = 1 no hay nada que medir. Dos cosas para la 321, que es la que mide: que Claude
casi no toma partido (17 de 19) y que las cuatro del 2026-11-20 salieron con WIP en el árbol
(`codigo_wip`, la 433). Las cuatro con el ticker contaminado del 2026-10-06 ya están declaradas (la 337).

## (3) ¿Hay que decirle a Claude que explique por qué contradice la señal?

No. El prompt ya dice que ninguna señal tiene poder predictivo demostrado, y en MARA la descartó con
argumentos (tendencia −44,6 % en 60 ruedas, flujo operativo negativo y creciente, dilución). Agregar la
instrucción cambiaría el instrumento de la 321 sin un caso que lo pida.

## Los faltantes que anotó

| Faltante | Qué se puede conseguir | Tarea |
|---|---|---|
| Noticias | MARA no tiene ninguna fila: no está en el universo que se cosecha. La 442 las baja al pedir la opinión. Además, **14 tickers de las carteras reales** («Mis Acciones» y «Tech») no están en el universo del harvest: 2357.TW, AAPL, BIDU, DELL, DLO, EA, EMBJ, GOOG, MARA, MDB, MLTX, SNOW, TEAM y UBER. | 442 (entró el 2026-11-20) y **445** |
| Deuda, caja, acciones y emisiones | La deuda, las acciones por año (la dilución, directa) y los múltiplos: la 440. Caja, capex y flujo libre: la 441. La pata de deuda de la calidad falta porque la ganancia del último año es negativa, por diseño (`analysis/calidad.py`). | 440 y 441 (entraron el 2026-11-20) y la 444, que dejó la 441 (verificarla contra el 10-K) |
| Bitcoin y las tenencias | La app no tiene ninguna serie de cripto, y Yahoo pone a MARA en *Capital Markets*: los «pares» de la 420 serían **MS, GS y SCHW**, bancos de inversión. | **446** |
| Margen bruto de 2025 | El almacén de MARA tiene `ganancia_bruta` y `costo_ventas` hasta 2024 y ninguno en 2025. **No es sólo MARA:** de los 126 almacenes us-gaap, 55 no tienen margen bruto en su último año, y **25 lo tenían en uno anterior** (AMT, BKNG, BKR, C, DE, DUK, FDX, GE, GM, HAL, INTU, KMI, MARA, NOC, ORCL, OXY, PSA, RTX, SBUX, SLB, T, TMO, TMUS, VZ y WMB). Parte son empresas que dejaron de presentarlo (bancos, eléctricas, telecos: el docstring de `fundamentos_pit` ya lo declara), parte pueden ser tags que `CONCEPTOS` no lee. Afecta también a la pata `rentab_bruta` de la calidad, que desde la 390 sólo usa un año vigente. Para ver los tags hay que pedirle el `companyfacts` a la SEC con el `User-Agent` de Chapa: **espera su permiso**, como la 437. | **447** |
| La etiqueta «Comprar» con el consenso neutral | Rotular la fuerza en la pestaña. | **448** |
