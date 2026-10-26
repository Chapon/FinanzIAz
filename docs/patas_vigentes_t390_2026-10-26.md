# Patas de otro año — la re-medición de la 384 y la 385 (tarea 390)

**Fecha:** 2026-10-26 · **Origen:** `docs/auditoria_tanda_2026-10-23.md` [I-1] · display-only.

## El defecto

El puntaje de calidad (`analysis/calidad.py`) tomaba el **último** dato de la ganancia bruta y de
la deuda de largo plazo aunque fuera de hace una década, y lo combinaba con la ganancia neta del
último año. La tarjeta de valuación tomaba el último EPS como el de hoy. La cobertura de la 382
contaba cuántos años había, no si el último era el vigente.

Sobre el almacén de fundamentals de hoy (125 tickers con datos), los que quedaban **atrás** de su
ganancia neta por más de un año:

| Concepto | Tickers | Ejemplos (último año) |
|---|---|---|
| Ganancia bruta | **24** | T 2014, WMB 2012, TMUS/VZ/BKNG/DE 2017, C 2020, GM 2021, KMI 2022 |
| Deuda de largo plazo | **6** | JPM 2013, O 2016, GS 2018, F 2020, DE 2021, ORCL 2022 |
| EPS diluido | **2** | EXC 2021, HAL 2021 |
| Ganancia neta | 0 | — |

Coinciden con lo que contó la auditoría. La ganancia neta —contra la que se compara todo— no está
vieja en ninguno.

## El arreglo

`data/fundamentos_pit.es_vigente(fin, ganancia)`: el último dato de un concepto vale si su cierre
está a 400 días o menos del cierre de la última ganancia neta, o sea el mismo ejercicio o el
anterior (los 400 días cubren los ejercicios de 52/53 semanas sin depender de que la ganancia tenga
todos los años). Lo usan:

- **Calidad:** `rentab_bruta` y `deuda` quedan vacías si su último año no es vigente.
- **Tarjeta:** el EPS agrega el aviso *«el EPS termina en 2021 y la ganancia en 2025»*. Los números
  de la tarjeta no cambian: el aviso dice que hay que leerlos con eso.
- **Cobertura de la 382:** un concepto cuyo último año no es vigente cuenta como cero años. La
  ganancia bruta baja de **88** a **71** de 126; sigue debajo del 80%, como antes.

## La re-medición

Las dos corridas usan el mismo cohorte que la publicada (`--allow-stale-artifacts`, artefactos
hasta el 2026-09-09) y los kill-criteria congelados, que no se recalibran. **Control:** el código
viejo, corrido hoy sobre los mismos datos, reproduce al decimal los números publicados en las dos;
la diferencia de abajo es sólo del instrumento.

### 384 — ¿la calidad anticipa el retorno? **No se mueve: sigue sin relación.**

Correlación de rangos media contra el exceso sobre SPY que viene, IC95% por bloques de meses:

| Horizonte | Meses | Antes | Ahora | Tercio alto − bajo, antes | Ahora |
|---|---|---|---|---|---|
| +60 ruedas | 117 | +0,011 [−0,024, +0,048] | +0,011 [−0,025, +0,047] | −0,58% [−1,87%, +0,65%] | −0,44% [−1,77%, +0,79%] |
| +120 | 114 | +0,013 [−0,040, +0,071] | +0,012 [−0,039, +0,069] | −0,77% [−3,32%, +2,05%] | −0,48% [−2,99%, +2,29%] |
| +250 | 108 | +0,009 [−0,070, +0,097] | +0,006 [−0,071, +0,091] | −2,45% [−7,67%, +4,36%] | −1,46% [−6,38%, +5,08%] |

Los tres intervalos siguen cruzando el cero. El tercio de mejor calidad rinde un poco menos de
desventaja que antes, sin significancia.

### 385 — carteras de calidad y valor. **No se mueve: NO-SHIP.**

| Cartera | Antes | Ahora | Diferencia contra Universo, ahora |
|---|---|---|---|
| Universo | +17,60%, caída 35,1% | igual | — |
| Calidad | +16,42%, caída 34,5% | +16,42%, caída 35,6% | −1,18% [−6,44%, +4,38%] |
| Valor | +16,59%, caída 36,5% | igual | −1,01% [−6,40%, +5,50%] |
| Calidad + valor | +16,02%, caída 34,2% | +15,73%, caída 34,2% | −1,87% [−6,59%, +4,11%] |
| Azar (200 de 20) | mediana +17,39%, p90 +20,33% | igual | — |

Las tres siguen cumpliendo sólo el criterio de riesgo (C3) y fallando los otros cuatro. El
crecimiento de Calidad igual al segundo decimal es casualidad (0,164214 contra 0,164223): la
cartera cambió en algunos rebalanceos —la caída máxima lo muestra— y en el último eligió las mismas
20, en otro orden. **Valor no cambia porque el arreglo del EPS es un aviso**: EXC y HAL siguen
entrando con su EPS de 2021 en el retorno esperado. Son 2 de 126 y la cartera de Valor ya perdía
contra el universo; no se re-mide eso aparte.

## Límites

- La tolerancia es de un año: un concepto del ejercicio anterior entra, y la deuda de ese año se
  divide por la ganancia del último. Es lo que pidió el alcance de la tarea.
- Lo demás que declararon la 384 y la 385 sigue igual: universo de hoy (sesgo de supervivencia),
  una década de large caps.
