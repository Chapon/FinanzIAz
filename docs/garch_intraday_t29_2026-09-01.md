# GARCH intradía (tarea 29c) — por qué la clave del cache NO se keyea a día

**Fecha:** 2026-09-01 · **Instrumento:** `scripts/measure_garch_intraday_t29.py` (offline, reproducible)
· **Veredicto: NO se toca la clave.** El criterio pre-declarado falla en 3 de 133 tickers.

---

## 1. La propuesta que se evaluó

La huella del cache de GARCH incluye `close[-5:]`, y el último close se mueve toda la rueda ⇒ **miss
garantizado en cada scan**: ~8,3 ms de fit × 128 tickers ≈ **1,1 s por scan**, ~26 refits por hora y
por ticker. El enunciado de la 29 proponía la solución de la **T24**: keyear a granularidad **diaria**
y fitear una vez por día.

## 2. Por qué no se podía copiar el argumento de la T24

La T24 pudo hacerlo con una prueba, no con una intuición: el XGBoost **descarta** las últimas
`PREDICTION_HORIZON` filas por no tener label, así que la barra parcial es *demostrablemente*
irrelevante para lo que entrena — el modelo salía **byte-idéntico**.

El fit de GARCH **sí usa el último retorno**, y su salida alimenta `train_garch_signal`, que entra en
la mezcla de BUY/SELL. Congelarla al primer scan sería servir una decisión vieja toda la rueda. El
propio enunciado marcaba el matiz: *"primero medir la distribución del Δforecast; si es despreciable,
keyear a granularidad diaria"*.

## 3. Criterio de aceptación, declarado ANTES de correr

> Se keyea a granularidad diaria **sólo si la señal emitida (dirección + fuerza) es idéntica entre el
> primer y el último scan del día en el 100% de los tickers.**

Es la única pregunta que decide algo —el Δ en puntos de vol es descriptivo— y **no necesita un umbral
inventado**: si aunque sea un ticker cambia, la variación intradía es relevante para la decisión.

## 4. Cómo se simula la rueda sin datos intradía

La barra diaria **ya trae** el recorrido: al primer scan del día el close parcial vale ≈ el **Open** y
al último vale el **Close**; el **High** y el **Low** son los extremos que efectivamente tocó. Se
refitea el mismo frame con el close de la última barra reemplazado por cada uno de los cuatro. No es
una aproximación optimista: es el **envolvente real** de lo que cualquier scan del día pudo ver.

## 5. El resultado

**133 tickers del universo vivo, 0 errores, 6,3 s.**

| medida | valor |
|---|--:|
| señales que **cambian** entre el primer y el último scan | **3 / 133 (2,3%)** — CRM, IBM, WBD |
| regímenes que cambian | 3 (los mismos) |
| \|Δ forecast_vol\| p50 / p90 / máx (pts de vol anual) | 0,200 / 0,900 / **3,000** |
| spread del día completo (O/H/L/C) p50 / p90 / máx | 0,500 / 2,900 / **6,500** |

**⇒ El criterio falla. La clave se queda como está, y el 1,1 s por scan se documenta como costo
aceptado** — es el **0,9%** de un scan de ~125 s, y el fetch sigue siendo ~el 90%.

## 6. Lo que el detalle agrega, y es más incómodo que el veredicto

Los tres "cambios" **no son flips de dirección**. Son el fit que **converge o no** según el valor del
close parcial:

| ticker | Open (1er scan) | Low | High | Close (último) |
|---|---|---|---|---|
| **CRM** | *no emite* | HOLD/WEAK | HOLD/WEAK | HOLD/WEAK |
| **IBM** | HOLD/WEAK | *no emite* | *no emite* | *no emite* |
| **WBD** | HOLD/WEAK | *no emite* | HOLD/WEAK | *no emite* |

O sea: en 133 tickers **no hubo ni un solo cambio de BUY↔SELL**, y el forecast se mueve poco (p50 de
0,2 pts). Pero un **2,3%** del universo está **al filo de la convergencia** del fit, y de qué lado cae
lo decide el precio del momento.

**Eso refuerza el NO, no lo debilita.** Con una clave diaria, *si CRM emite señal GARCH durante toda
la rueda* quedaría decidido por el precio arbitrario del primer scan a las 9:30 — y sería estable e
invisible todo el día, en vez de oscilar de forma visible. Es peor que el problema que se quería
resolver.

**Y deja un hallazgo aparte (regla 6): la fragilidad del fit no es un problema de cache.** Que un
2,3% del universo alterne entre "emite" y "no emite" según el tercer decimal del último close es una
propiedad del fit de GARCH(1,1) sobre esas series, y hoy se traduce en una señal que aparece y
desaparece sin que nada lo declare. Queda como **tarea 67 (GARCH-FRAGIL)**.

## 7. Qué SÍ se shipeó de la 29

Las patas (a), (b) y (d) — el cache de indicadores, que es donde el defecto era real y el fix seguro.
Ver el backlog. La (c) queda **medida y cerrada en NO**, con el instrumento en el repo para que
re-abrir la pregunta cueste un comando.
