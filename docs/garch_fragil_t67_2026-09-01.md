# GARCH-FRAGIL (tarea 67) — el no-fit, declarado y medido sobre ventana larga

**Fecha:** 2026-09-01 · **Instrumento:** `scripts/measure_garch_fragil_t67.py` (offline, reproducible)
· **Partes 1 y 2 de la tarea. La 3 (elegir un remedio) NO se hizo — y la medición explica por qué.**
· **ref** `docs/garch_intraday_t29_2026-09-01.md` §6

---

## 1. De dónde viene

La 29(c) midió que en **3 de 133** tickers (CRM, IBM, WBD) `fit_garch_forecast` devuelve `None`
para unos valores del close parcial y un forecast válido para otros — o sea que **de qué lado
cae lo decide el precio del momento**. Y eso pasa en silencio: `train_garch_signal` devuelve
`None` sin distinguir *"este ticker no tiene régimen que reportar"* de *"el fit se cayó"*, así
que la señal GARCH **entra o no entra en la mezcla de `analyze()` sin que nada lo declare**.

El enunciado fijó el orden y advirtió contra saltárselo: **(1)** declarar el no-fit, **(2)** medir
sobre una **ventana larga** —el 2,3% salía de **un** día simulado—, **(3)** recién ahí decidir si
vale un fallback. Este documento es (1) y (2).

## 2. Parte 1 — el `None` deja de ser mudo

`fit_garch_forecast` devolvía `None` por **ocho** caminos distintos, todos colapsando al mismo
valor en el borde, con los motivos sólo en `log.debug` (invisibles en operación). Ahora cada uno
declara el suyo y el engine emite **una** línea por scan, al estilo de la telemetría de la 25a:

```
GARCH sin fit=3 (no_converge=2 pocos_datos=1)
```

**El caso normal es que la línea no aparezca** (124 de 133 tickers fitean siempre). Que aparezca
es la señal.

Hay un test que falla si alguien agrega un `return None` sin declarar motivo — sin eso, ese
camino vuelve a ser mudo y la telemetría **miente por omisión**.

## 3. Parte 2 — la ventana larga

**133 tickers × ~60 sesiones = 7.980 fits**, 62 s. En cada sesión se fitea sobre el frame hasta
esa barra y se registra si fiteó y por qué no.

| | |
|---|--:|
| siempre fitean | **124** |
| nunca fitean | **0** |
| **al filo** (alternan fit ↔ no-fit) | **9** |
| alternancias totales | **88** |

**El problema es 3× más grande de lo que decía el snapshot: 9 de 133 (6,8%), no 3 de 133
(2,3%).** Y no es un temblor de borde — es persistente:

| ticker | fit | no-fit | alternancias |
|---|--:|--:|--:|
| **IBM** | 26 | 34 | **32** |
| **MLTX** | 19 | 41 | **24** |
| **WBD** | 7 | 53 | **12** |
| MDLZ | 53 | 7 | 6 |
| ABT | 27 | 33 | 5 |
| ACN | 54 | 6 | 5 |
| INTC | 59 | 1 | 2 |
| CRM | 58 | 2 | 1 |
| INTU | 54 | 6 | 1 |

**IBM alterna 32 veces en 60 sesiones**: más de la mitad de los días su señal GARCH aparece o
desaparece. El snapshot de la 29(c) lo mostraba como un caso de borde; sobre ventana larga es
un ticker que **prácticamente no tiene señal GARCH estable**.

## 4. El hallazgo que cambia qué remedio tendría sentido

Los motivos, sobre los **183** no-fits:

| motivo | n | |
|---|--:|---|
| **`no_estacionario`** (α+β ≥ 1, resto de los parámetros sano) | **181** | **98,9%** |
| `no_converge` (el optimizador falló) | **2** | 1,1% |
| `params_fuera_region` (ω≤0, α<0, β<0, no finitos) | **0** | — |

**El optimizador NO está fallando.** Converge, y lo que encuentra es **α+β ≥ 1**: en la ventana
de 2 años, la volatilidad de esas series **no revierte a una media**. El guard las rechaza —y
hace bien, porque el forecast de una GARCH no estacionaria no tiene media de largo plazo a la
cual revertir— pero el diagnóstico es **estadístico, no numérico**.

**Eso descarta el remedio que el propio enunciado floteaba** (*"más iteraciones, `rescale`, otro
solver"*): no hay nada que arreglar en el optimizador. Es exactamente por lo que la tarea insistía
en medir antes de elegir — el remedio obvio era el equivocado.

Para separar los dos casos hubo que **partir el motivo en dos**: antes los 181 caían en un
genérico *"parámetros fuera de región"* que agrupaba cuatro condiciones distintas, y con eso el
diagnóstico quedaba a medias. Ahora `no_estacionario` es el caso *"el fit convergió y ése es el
resultado"* y `params_fuera_region` queda para los degenerados de verdad — que resultaron ser
**cero**.

## 5. Lo que NO se hizo, con el argumento

**La parte (3) queda abierta a propósito.** Con lo medido, las opciones reales no son las que
parecían:

- **NO** un fallback de optimización — el optimizador converge.
- Sí, eventualmente, alguna de éstas, y cada una es una decisión con su propio pre-registro:
  **(a)** aceptar el fit no estacionario con un caveat (IGARCH: σ que no revierte es un modelo
  legítimo, sólo que sin media de largo plazo); **(b)** alargar la ventana del fit para esos
  tickers; **(c)** dejarlo como está y que la telemetría lo declare, que es lo que hay hoy.

**La opción (c) ya no es silenciosa**, que era el defecto original. Elegir entre (a) y (b) exige
medir si el forecast de un fit no estacionario **sirve para algo** — otra pregunta, otra tarea.

## 6. Alcance NO mirado

- **60 sesiones sobre el frame `2y`.** No se probó si con `5y` o `10y` los mismos tickers
  estacionarían: es justamente la opción (b) de arriba y merece su propia medición.
- **No se midió el impacto sobre las decisiones.** La 29(c) ya había establecido que en 133
  tickers **no hubo ni un flip BUY↔SELL**; lo que cambia es si la señal entra o no en la mezcla.
  Cuánto pesa eso en el `overall_signal` no se midió acá.
- **MLTX aparece entre los peores y no está en el universo vivo** (entró por tener frame `2y` en
  el cache). No se filtró a propósito: para medir la fragilidad del *fit*, más series es mejor.
