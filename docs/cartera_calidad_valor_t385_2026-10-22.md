# Cartera de calidad y valor de largo plazo — resultado (tarea 385), 2026-10-22

**Veredicto: NO-SHIP.** Ninguna de las tres carteras que eligen (Calidad, Valor, Calidad + valor)
le ganó a comprar el universo entero en partes iguales. Las tres rindieron entre 1,0 y 1,6 puntos
por año **menos**, y ninguna se separó de las carteras elegidas al azar. La valuación (383) y el
puntaje de calidad (384) siguen en la pantalla de Analysis como información, sin decidir nada.

Pre-registro: `docs/cartera_calidad_valor_prereg_t385_2026-10-21.md` (commit `6c5044d`, congelado
antes del runner). Runner: `scripts/run_cartera_calidad_valor_t385.py --allow-stale-artifacts`.

## Resultado

Ventana simulada: 2017-04-03 → 2026-09-09, diez rebalanceos (el primer día hábil de abril de cada
año), costo de 0,064% sobre lo operado.

| cartera | crecimiento anual | caída máxima | sub-ventanas ganadas | diferencia contra Universo, IC95% | pasa |
|---|---|---|---|---|---|
| **Universo** (la vara) | **+17,60%** | 35,1% | — | — | — |
| Calidad | +16,42% | 34,5% | 1 de 3 | −1,18% [−7,06%, +5,09%] | no |
| Valor | +16,59% | 36,5% | 0 de 3 | −1,01% [−6,40%, +5,50%] | no |
| Calidad + valor | +16,02% | 34,2% | 0 de 3 | −1,58% [−6,40%, +4,38%] | no |
| Azar, 200 carteras de 20 | mediana +17,39% · percentil 90 +20,33% | — | — | — | — |

Por criterio, las tres igual: **rendimiento** no (le pierden a Universo), **que no sea suerte** no
(el intervalo cruza el cero), **riesgo** sí (caídas parecidas), **estabilidad** no (ganan 0 o 1 de
3 sub-ventanas) y **selección** no (quedan por debajo de la mediana del azar).

## Controles (pasaron antes de leer las diferencias)

- **Sin mirar el futuro:** en cada rebalanceo, la selección de Calidad y de Valor dio exactamente lo
  mismo con el almacén recortado a lo presentado antes de la fecha.
- **Universo reproduce el promedio:** sin costos, su valor al final de cada tramo coincide con el
  promedio simple de los retornos de sus empresas (tolerancia relativa 1e-9).

## Lo que limita la lectura

- **Sesgo de supervivencia:** el universo es la watchlist de hoy. Infla a todas las carteras por
  igual; la comparación contra Universo lo neutraliza en parte, no del todo.
- **Valuación incompleta:** cada año quedaron sin retorno esperado entre 15 y 32 de las 126 (EPS
  negativo, menos de tres años de precio sobre ganancias, o extranjeras). La cartera Valor eligió
  entre las demás.
- **Una década de mega-caps:** 2017–2026 fue un período en que las más grandes subieron más que el
  resto. Un universo en partes iguales y carteras de 20 nombres compiten en las mismas condiciones,
  pero la conclusión vale para esta ventana y este universo, no para el value investing en general.
- **Un solo diseño:** 20 nombres, rebalanceo anual en abril y estas tres definiciones. El
  pre-registro las congeló a propósito; probar otras variantes después de ver este número sería
  buscar hasta encontrar.

## Qué queda de la serie de los libros

Con esto cierra la serie 382–386 (`docs/libros_inversion_analisis_2026-10-21.md`):

- **Quedan en la app, como información:** la valuación de Graham, *Buffettology* y Lynch, y el
  puntaje de calidad (Analysis, 383 y 384); el costo de rotar (Home, 386); y los fundamentals
  point-in-time de EDGAR (382), que cualquier medición futura puede usar.
- **No se cablea nada a decisiones.** Ni la calidad (384: no anticipó el retorno) ni las carteras de
  largo plazo (esta tarea) le ganaron al universo sin elegir.
- **Lo que sí coincide con los libros, y ya estaba medido:** sin ventaja de selección, lo que se
  controla es el costo. La cartera Universo rindió +17,6% anual rebalanceando una vez por año; la
  cuenta 2 rotó su capital 17 veces en cuatro meses. Esa comparación es la que muestra Home (377 y
  386).

## Re-medición de la tarea 390 (2026-10-26)

El puntaje de calidad usaba la ganancia bruta y la deuda aunque fueran de hace una década (24 y 6
tickers). Con el instrumento corregido, Calidad da +16,42% (caída 35,6%) y Calidad + valor +15,73%;
Valor y Universo no cambian. **Las tres siguen NO PASA, con los mismos criterios: el NO-SHIP no se
mueve.** El detalle, con el control de que el código viejo reproduce esta corrida, está en
`docs/patas_vigentes_t390_2026-10-26.md`.
