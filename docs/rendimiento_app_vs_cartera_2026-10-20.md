# ¿Por qué Sim Segundo no sube y «Mis Acciones» sí? — 2026-10-20

Pregunta de Chapa (2026-10-20), mirando Home con las dos curvas: *«la gráfica de paper - sim
segundo permanece prácticamente en los mismos valores, mientras que mis inversiones suben alrededor
de un 40%. ¿Por qué son tan malas las compras y ventas de la app? ¿Hay algo que podamos hacer?»*

**Es descriptivo, no un veredicto** (regla 2): ninguna de estas cifras decide nada. Lo que se
puede hacer sale en las tareas **377** y **378**, cada una con su kill-criteria.

## Instrumento

- Ventana: **2026-06-20** (alta de la cuenta 2, $50.000) → **2026-10-20**.
- DB: copia con la API de backup desde `mode=ro`, a las 16:20 del 20/10.
- Cierres: los frames `2y` de `data/parquet/`. Para validarlos, se buscó el salto diario más
  grande desde junio en los extremos (MPC, ACN, VLO, PSX, CRM, NOW, KLAC, ON, AMAT, LRCX, INTC): el
  mayor es 23,7% (ON, 26/06), un movimiento por resultados y no un cambio de escala.
- «Mis Acciones»: `resumen_home` → `ganancia_diaria`, la misma serie que pinta la vista *Sólo
  ganancias* de Home. EMBJ y MARA no tienen frame `2y` y quedan fuera de la contribución por ticker.

## 1. La comparación pareja

| | Retorno en la ventana |
|---|---|
| Sim Segundo (equity 49.977 → 51.599) | **+3,2%** |
| SPY | +3,2% |
| Los 127 de la watchlist, comprados el 19/06 en partes iguales y mantenidos (125 con frame) | +5,2% (mediana +0,6%) |
| «Mis Acciones»: ganancia total 14.370 → 25.862 = +11.491, sobre un costo promedio de 42.649 | **+26,9%** |

- **El gráfico *Valor de mercado* exagera la diferencia:** sus escalones son compras (plata nueva),
  no rendimiento. La vista *Sólo ganancias* es la que compara.
- **El +26,9% es casi todo MSFT:** contribución por ticker del 18/06 al 20/10, con la tenencia de
  cada día: MSFT **+7.668**, META +779, NVDA +766, MO +330, PYPL +190, KO +112, INTC −161. Es una
  posición de ~$20.000 en un nombre que subió ~40%: una apuesta concentrada que salió bien. Con
  10 posiciones del mismo peso, la cuenta 2 no tiene ese riesgo, ni a favor ni en contra.

## 2. Las compras: no se distinguen del universo del mismo día

Cada compra de la cuenta 2 se comparó contra el **promedio del universo el mismo día**, con el exceso
sobre SPY de los dos:

| horizonte | compra − universo, media | mediana | n |
|---|---|---|---|
| +5 ruedas | +0,32% | +0,31% | 88 |
| +10 ruedas | +0,06% | −0,12% | 86 |
| +20 ruedas | −0,54% | −1,60% | 78 |

Con esta muestra no hay ventaja medible, y es lo mismo que ya midió el repo: la regla 3 de
`CLAUDE.md` (`corr(buy_score, fwd5) = −0,05`, IC que cruza el cero, tarea 73) y la **39** (el
ranking no tiene alpha medible).

## 3. Las ventas por señal: lo vendido sigue cayendo

Exceso sobre SPY de lo vendido con `analyze SELL`, desde el día de la venta:

| horizonte | media | mediana | n | le ganó a SPY |
|---|---|---|---|---|
| +5 ruedas | −0,55% | +0,42% | 47 | 25 |
| +10 ruedas | −2,01% | −1,46% | 45 | 16 |
| +20 ruedas | −3,58% | −2,48% | 41 | 11 |

O sea que esa venta **no regala rebotes**. Las 51 ventas por señal suman −$3.416 realizados y las
salidas ATR (stop, target y trailing) +$3.801. **Eso no dice que la señal venda mal:** la señal se
da vuelta sobre posiciones que ya venían perdiendo, y el target sólo salta en las que ganan. Es
selección, no causa.

## 4. La rotación

184 fills (97 compras, 87 ventas), un volumen de $853.648, o sea **17,1 veces el capital en cuatro
meses**, y una tenencia media de **12,3 días**. Comisiones $115,95 + slippage $426,81 = **$542,76**,
un tercio de lo que ganó la cuenta. Todo eso con los frenos que ya tiene: `paper_signal_sell_min_age_bdays
= 3`, anti-whipsaw de 7 días y anti-churn de 3 ciclos en 10 días. Con una selección que no le gana
al azar, cada vuelta es costo sin un beneficio esperado.

## Límites

- Son **cuatro meses y ~80 operaciones**. Alcanza para decir que **no hay evidencia de ventaja**, no
  para decir que la app sea mala ni que lo vaya a seguir siendo.
- La comparación con el universo usa los cierres de cada día. El motor llena intradía, con el
  slippage modelado.

## Lo que ya se probó y no se repite

- Invertir el ranking u ordenar al azar: **39**, NO-SHIP.
- Mover la política de salida: **170**, NO MOVER, y la rejilla quedó cerrada.
- **Demorar la venta por señal (la palanca de la rotación): 219, NO-SHIP**
  (`docs/signal_exit_delay_t219_2026-09-22.md`). `min_age` en 5, 10 y 20 días sube el CAGR, pero
  el 61% es operar menos (un brazo que demora al azar gana casi lo mismo), los que más ganan suben
  el maxDD y los tres se dan vuelta en las ventanas de stress. **Este doc lo omitía en su primera
  versión**, y la tarea 378 que salió de acá se cerró sin correr por eso. Junto con T7, la serie de
  stops, T23, T170 y T51, la familia de salidas está cerrada.

## Un número que no cierra (→ tarea 379)

El §3 dice que en la cuenta viva **lo vendido por señal le pierde a SPY** (−3,58% a 20 ruedas), y
lo comprado en su lugar, −0,90% (§2). O sea que vender **sumó**. El harness de la T7 y la 219 dice
lo contrario: obedecer a la señal resta. Puede ser la ventana (cuatro meses, ventas superpuestas) o
un desvío entre el harness y el motor. Se mide en la **379**.

**Medido (2026-10-21, `docs/venta_senal_vivo_vs_harness_t379_2026-10-21.md`): es la ventana.** En el
mismo recorte, cada giro a SELL del universo también le perdió a SPY (−0,79% a 20 ruedas), y en diez
años da +0,15%. 28 de las 33 ventas del vivo coinciden con la señal del harness, y son las peores.
El −3,6% es el extremo de una ventana mala, con 3 bloques de 20 ruedas, y no un desvío.
