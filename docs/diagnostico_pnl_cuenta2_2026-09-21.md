# Por qué la cuenta no gana plata — diagnóstico de la cuenta 2 al 2026-09-21

**Pedido de Chapa:** *«necesito un análisis de por qué no estamos ganando dinero; mirando el
score estamos en casi cero de ganancia en los últimos meses»*.

Todo lo de acá sale de `finanzias.db` (abierta **read-only**) y de SPY bajado de yfinance.
Nada se escribió. Los round-trips se reconstruyeron por **FIFO** sobre `paper_orders`.

---

## 0. La validación del instrumento, antes de los números

Un diagnóstico de P&L es exactamente el caso donde un número limpio puede ser falso, así que
el instrumento se validó primero:

- **Reconciliación:** `50.000 + realizado 521,38 + no-realizado 725,26 = 51.246,64` contra
  `total_equity = 51.559,67` de la DB → **desvío 0,61%**, atribuible a que `price_cache` es
  spot con `fetched_at` viejo. La reconstrucción FIFO cierra.
- **Contraste de posiciones:** la cartera reconstruida orden a orden da **exactamente** los
  mismos 10 tickers y los mismos shares que `paper_positions` hoy (AVGO 9, BMY 115, CSCO 117,
  DHR 15, GS 1, KLAC 17, KMI 174, MO 134, SPG 27, TSM 1).

O sea que el reconstructor reproduce el estado final sin error. Lo que sigue se le puede creer.

---

## 1. La corrección de encuadre: no es cero, y tampoco es «la estrategia se rompió»

| tramo | cuenta | SPY | diferencia |
|---|---:|---:|---:|
| 2026-06-20 → 2026-06-30 | +1,06% | +0,00% | **+1,06pp** |
| 2026-06-30 → 2026-07-24 | +3,41% | −1,05% | **+4,46pp** |
| 2026-07-24 → 2026-08-31 | −2,15% | +3,81% | **−5,95pp** |
| 2026-08-31 → 2026-09-21 | +0,84% | +1,09% | −0,25pp |
| **total desde el inicio** | **+3,12%** | **+3,84%** | **−0,72pp** |

**Desde el inicio la cuenta casi empata al mercado** (+3,12% contra +3,84%, ~13% anualizado).
Eso no es «cero».

> **Corrección del 2026-09-23 (tarea 223): la corrección de abajo estaba al revés, y la tabla
> vuelve a sus números originales.** El 2026-09-21 cambié SPY de **+3,84%** a **+4,17%** con este
> argumento: *«el panel ancla en la primera barra ≥ el inicio, que es lo correcto»*. **El panel
> estaba mal.** El 20-jun fue sábado (el 19 fue feriado), así que la equity de la cuenta ese día
> está marcada con el close del **18-jun** (744,89) y anclar SPY en el **22-jun** (742,55) compara
> dos instantes distintos. La 223 arregló el panel —ahora ancla con `_close_on_or_before`, la
> misma regla que ya usaba para el final— y con eso el número de arriba vuelve a ser el bueno.
>
> **Lo que falló no fue la aritmética sino el criterio:** tomé el comportamiento del código como
> definición de lo correcto en vez de preguntarme qué instante representaba cada lado. Toca dos
> filas —la primera y el total, las únicas con un extremo fuera de rueda— y vale **0,33pp**, que
> es lo mismo que midió la 223 sobre la ventana de hoy. **El signo y la conclusión no se mueven**
> en ninguna de las dos versiones: la cuenta le pierde a SPY desde el inicio.
>
> **Corrección anterior, del 2026-09-21 (tarea 218) — la parte que SÍ valía.** Las filas de julio
> y agosto se recalcularon y ésas no se tocan: la ventaja de julio era **mayor** de lo que decía
> la primera versión (+4,46pp, no +3,37pp) y la pérdida de agosto también (−5,95pp, no −4,83pp),
> porque SPY **bajó** −1,05% en el tramo de julio en vez de subir +0,03%. Los dos extremos de esos
> tramos son ruedas hábiles, así que el anclaje nunca los tocó. La del pico (−6,26pp) tampoco
> cambia, por lo mismo.

**Pero tenés razón en lo que ves, y el número exacto es éste:** el pico de equity fue
**$52.252,05 el 2026-07-24**. Desde ahí:

> **cuenta −1,33% · SPY +4,94% · brecha −6,26pp en dos meses**

Toda la ganancia se hizo en las primeras cinco semanas. Desde entonces la cuenta devolvió
plata mientras el mercado subía.

**Y sin embargo no alcanza para decir que la estrategia se rompió.** El desvío por trade es
**$303,32**; desde el pico se cerraron **44** trades, así que el desvío de la suma es
**$2.012** (3,85% de la equity). La brecha de −6,26pp son **$3.271**, o sea **1,63 sigmas**.
Está **dentro del ruido**: no se puede distinguir de mala suerte. Eso corta para los dos
lados — tampoco había base para llamar «buenas» a las primeras cinco semanas.

---

## 2. La razón de fondo: no hay edge medible, y el sistema no lo esconde

69 round-trips cerrados, 148 fills, del 2026-06-20 al 2026-09-21.

| métrica | valor |
|---|---:|
| P&L bruto (sin costos) | **+$918,97** |
| costos de esos trades | **−$397,59** |
| **P&L neto realizado** | **+$521,38** |
| aciertos | 25/69 = **36,2%** |
| ganador promedio | +$306,86 |
| perdedor promedio | −$162,50 |
| **expectativa por trade** | **+$7,56** |
| desvío por trade | $303,32 |
| **t** | **0,21** |
| **IC95% por trade** | **[−$64,01, +$79,13]** |

**El intervalo contiene el cero con amplitud.** Con n=69 el resultado es indistinguible de no
tener ninguna ventaja: hace falta |t|>2 y estamos en 0,21.

**Y la concentración lo confirma:**

| | P&L | % del total |
|---|---:|---:|
| mejor 1 trade (HAL) | +$811,48 | 156% |
| mejores 3 | +$2.350,46 | 451% |
| mejores 5 | +$3.288,49 | 631% |
| **sin los 3 mejores** | **−$1.829,08** | — |

El resultado entero de tres meses son **tres operaciones**: HAL +811, AMD +808, INTC +731.
Sacá esas tres y la cuenta pierde $1.829. Eso no es un sistema rindiendo; es una muestra chica.

---

## 3. Dónde se va la plata: la anatomía por tipo de salida

| salida | n | P&L neto | promedio | retorno medio | aciertos |
|---|---:|---:|---:|---:|---:|
| `atr_tp` (take-profit +4 ATR) | 11 | **+$4.842,25** | +$440,20 | +11,30% | 100% |
| `atr_trail` | 8 | −$55,39 | −$6,92 | −0,35% | 38% |
| **`analyze SELL` (la señal se da vuelta)** | **41** | **−$2.127,17** | −$51,88 | −0,79% | **27%** |
| `atr_stop` (−2 ATR) | 9 | −$2.138,30 | −$237,59 | −5,22% | 0% |

Leído derecho: **el take-profit por ATR paga todo** (+$4.842 en 11 salidas) y **el resto lo
devuelve**. El `atr_tp` al 100% y el `atr_stop` al 0% de aciertos son tautológicos —un TP sólo
dispara en ganadores y un stop sólo en perdedores—, así que el renglón que informa es el otro:

> **`analyze SELL` es el 59% de las salidas (41 de 69), pierde $2.127 y acierta 27%.**

Es la salida por señal: el score baja y el motor cierra. En promedio cierra en **−0,79%**.

**Ojo con la conclusión fácil.** Esto **no** demuestra que convenga sacar la salida por señal:
lo que se ve es el resultado *condicionado a haber salido*, no lo que habría pasado
quedándose, y esa diferencia es justamente lo que un replay mide y una tabla no. La **tarea
170** re-decidió la política de salida el 2026-09-10 con un gate sin selección y el veredicto
fue **NO MOVER** (D1 pasa, +1,76pp). Así que esto entra como **tarea para medir**, no como
cambio. Reglas 2 y 3 del proyecto.

---

## 4. Los costos se comen el 43% del bruto — y no son las comisiones

| concepto | monto |
|---|---:|
| comisiones | $92,96 |
| **slippage** | **$335,85** |
| total | $428,81 |

**El slippage es el 78% del costo.** Sobre el bruto de los cerrados ($918,97), los costos
atribuidos se llevan **el 43%**.

El driver es la rotación: **69 round-trips en 3 meses sobre 10 slots**, holding **mediana 9
días** (media 12,1). Cada vuelta paga ~0,13% de ida y vuelta contra un retorno bruto medio de
0,29% por operación. Con un edge de ese tamaño la fricción no es un detalle de segundo orden:
es la mitad del problema.

---

## 5. El `signal_score` no predice el retorno — en vivo, igual que en los backtests

`paper_orders` guarda el `signal_score` de las 79 compras (rango 0,720–0,881, media 0,782).
Contra el retorno realizado de cada round-trip:

> **corr(signal_score, retorno) = +0,006 · n=69 · IC95% [−0,23, +0,24]**

**No se detecta relación** — y hay que decir lo que eso *no* dice: con n=69 el test sólo
detectaría |r| > 0,24, así que esto **no prueba** que el score no sirva. Pero apunta en la
misma dirección que todo lo demás:

- **tercil bajo de score: +1,14% · tercil alto: +0,50%** — ordena levemente **al revés**.
- La **tarea 9** midió lo mismo con n=26.988 (poder de verdad): `corr(score, retorno) = −0,0259`,
  top-20% 0,34% contra bottom-20% 0,57%. Mismo signo.
- La **tarea 73** re-midió `corr(buy_score, fwd5) = −0,05`, n=85, IC95% [−0,26, +0,17].

Tres mediciones independientes, dos sin poder y una con mucho, **todas del mismo lado**.

### Y esto no es un descubrimiento nuevo de este análisis

El repo ya lo probó sistemáticamente, con pre-registro, y el resultado fue negativo cada vez:

| tarea | qué probó | veredicto |
|---|---|---|
| 7 | scale-out + trailing + jerarquía de salidas | **NO-SHIP** |
| 8 / 10 | sizing por riesgo (inverse-vol, vol-target) | **NO-SHIP** (−4pp de CAGR) |
| 9 | meta-labeling + triple barrera (ranking) | **NO-SHIP** (AUC OOS 0,4980) |
| 11 | PEAD post-earnings | **NO-SHIP / sin poder** |
| 12 | insider cluster buys (FORM4) | **NO-SHIP** |
| 170 | re-decidir política de salida | **NO MOVER** |
| **20** | **escalado por régimen** | **SHIP** — y baja el drawdown, no sube el retorno |

**Lo único que pasó un kill-criteria en toda la serie reduce el riesgo; nada aumentó el
retorno.** La cuenta viva se está comportando exactamente como esa evidencia predice. La
conclusión que la tarea 9 dejó escrita sigue en pie: *el valor está en de dónde salen los
candidatos, no en refinar decisiones sobre los que `analyze()` produce* — y las dos apuestas
de candidatos que se probaron (11 y 12) también dieron negativo.

---

## 6. El hallazgo operativo: no podés ver VS SPY, y por eso la pregunta llega así

**`_benchmark_panel(cuenta 2)` hoy devuelve `available=False`, `spy_return=None`,
`vs_spy=None`.** Verificado corriendo la función real contra la DB viva.

La causa es una cadena de dos pasos, cada uno deliberado por separado:

1. **2026-07-12** — ARQ1 activó el backend **Parquet**. `yahoo_finance` dejó de escribir
   `historical_data_cache`; la última fila quedó del **2026-07-11**.
2. **2026-09-02** — la migración **0011** **vació** la tabla a propósito (288 filas / 22,7 MB,
   el 24% del archivo de DB), porque ese rollback ya había caducado.

**Pero `analysis/metrics_panel.py` nunca se migró a Parquet.** `load_close_series` y
`load_ohlc_series` siguen leyendo `historical_data_cache` — que ahora tiene **0 filas**. El
módulo no tiene una sola referencia a Parquet.

Consecuencia: `load_close_series` devuelve `None` para **todo** ticker, y con eso se apagaron

- **la tarjeta VS SPY** (la métrica V1, la que existe para separar sistema de mercado),
- **MAE/MFE** (`load_ohlc_series`, misma tabla),
- **el retorno forward a 5 días** del panel.

Y hay una ironía que vale anotar: la **tarea 22** construyó un detector de SPY stale
justamente para que el benchmark no mintiera en silencio. Ese detector cubriría la fase 1
(tabla congelada en julio → *«SPY desactualizado»*); lo que no cubre es la fase 2, donde la
tabla queda **vacía** y el panel pasa a `available=False`, que se muestra como *no hay dato*
en vez de *esto se rompió*.

**Esto es lo que más importa de todo el análisis**, porque es la razón de que la pregunta
llegue como llega: sin VS SPY el único número visible es la equity cruda, y +3,1% a ojo parece
«casi nada» cuando en realidad es *casi empatarle al mercado*. Con la tarjeta prendida habrías
visto que el problema real no es el nivel, es la brecha desde el 24 de julio.

---

## 7. Lo secundario: la cuenta vive sin caja

- **Cash mediano: 1,95% de la equity.** El **35%** de los snapshots están por debajo del 0,5%.
- El sizing hace `budget = min(target_dollars, acct.cash)` (`engine.py:1984`) y el único piso
  es `shares_got < 1.0`. O sea que con la caja en cero **compra lo que entre**, hasta 1 acción.
- **7 entradas** quedaron muy por debajo de su target. La peor: **KMI, target $5.747, entró con
  $31,95 — una acción, el 0,6%.**

El costo directo es trivial ($4,56 de comisiones entre las 7), así que **no es acá donde se
pierde la plata** — lo digo explícito porque es fácil confundirlo con una causa. Lo que sí pasa
es que un slot de 10 queda ocupado por una posición que no puede mover la aguja.

**Lo que NO es un problema:** el exceso sobre `max_positions=10` (la cuenta llegó a 12) ya
estaba encontrado y **arreglado** — el comentario en `strategies.py:485` documenta los 9
episodios, y la reconstrucción confirma que **el último fue el 2026-09-02** y no hubo más
desde entonces. El fix aguantó.

---

## 8. Qué se sigue de esto

Ordenado por lo que cambia las cosas:

1. **Prender de nuevo VS SPY** (tarea **218**). Es un arreglo de lectura, no de estrategia, y
   sin él estás decidiendo a ciegas sobre la única pregunta que importa: ¿esto le gana al
   mercado?
2. **Medir la salida por señal antes de tocarla** (tarea **219**). 41 de 69 salidas y −$2.127
   la hacen la candidata obvia, pero el número de la tabla no prueba que convenga sacarla: eso
   lo dice un replay contra el contrafáctico, y la 170 ya dijo NO MOVER una vez.
3. **Bajar la rotación** es la palanca con mejor relación evidencia/costo: no necesita alpha
   nuevo, sólo dejar de pagar 0,13% por vuelta 69 veces. Entra dentro de la 219.
4. **Aceptar el resultado de la serie.** Ocho experimentos pre-registrados, un solo SHIP y es
   de riesgo, no de retorno. Con esa evidencia, seguir refinando la capa de decisión tiene
   rendimiento esperado bajo. Si el objetivo es ganarle al mercado, lo honesto es que la
   próxima apuesta sea una **fuente de candidatos** distinta — y que se le ponga kill-criteria
   y poder suficiente **antes**, que es donde la 11 se quedó sin poder decidir.

**Lo que este análisis NO puede decir:** si la estrategia pierde plata. n=69 y t=0,21 no
alcanzan para eso. Lo que sí queda establecido es que **no hay evidencia de que gane**, y que
eso es consistente con todo lo que el repo midió antes con muestras mucho más grandes.
