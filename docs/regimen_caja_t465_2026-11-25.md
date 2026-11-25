# REGIMEN-CONTRA-SU-CAJA (tarea 465) — resultado · 2026-11-25

**Veredicto: DEPENDE DEL TRAMO.** Corrida **VÁLIDA** (los cinco sanity en OK). Con la `w` de una caja
constante calibrada en una mitad de la muestra para que caiga lo mismo que el escalado, el escalado
**pierde** en 2021-08 → 2026-07 y **gana** en 2017 → 2021, el tramo con las caídas rápidas. En los
dos tramos el IC del ΔSharpe cruza el cero. Por el pre-registro, el escalado sigue siendo una
**preferencia de riesgo**, como lo dejó la 124, y no se toca nada. El factor lo decide Chapa.

Pre-registro: `docs/regimen_caja_prereg_t465_2026-11-25.md`, congelado antes del runner. Runner:
`scripts/run_regimen_caja_t465.py`. La salida completa queda local (`docs/_t465_run.*`, fuera de git) y
se rehace con el comando del runner.

## 1. Qué se midió

El escalado por régimen (×0,25 en las compras cuando SPY está bajo su SMA200) compra caída. La forma
más simple de comprar la misma caída es tener caja constante. La 464 y la 468 compararon las dos
**sobre la muestra entera**, eligiendo la `w` de la caja mirando esa misma muestra; con el costo del
vivo, el escalado rendía 1,60 pp más y tenía 0,03 menos de Sharpe.

La 124 había medido que un hold-out en un solo sentido deja el test sin caídas rápidas. Por eso se
midió **en los dos sentidos**: la `w` se calibra en un tramo (la más alta que no cae más que el
escalado ahí) y se mide en el otro, y después al revés. Gate por tramo: el escalado tiene Sharpe
≥ el de la caja **y** una caída no peor que la de la caja + 1 pp. El criterio es el que la tarea
propuso antes de que el costo del vivo diera vuelta el CAGR; no se cambió.

## 2. Sanity (§5)

| | resultado | |
|---|---|---|
| 1. al costo del harness | sin régimen 8,78% / 0,55 / 2.531 (la T170); régimen 6,41% (la 464) | OK |
| 2. al costo del vivo, muestra completa | 13,72% / 0,79 / 29,5% y 11,35% / 0,77 / 21,4% (la 468) | OK |
| 3. el escalado muerde | 18,0% de las entradas con factor < 1 | OK |
| 4. `w` existe | A 0,67 · B 0,96 | OK |
| 5. calendario común | 100% | OK |

## 3. El gate (§4)

| tramo | calibra `w` en | test | `w` | escalado | caja | S | D |
|---|---|---|--:|---|---|---|---|
| **A** | 2017 → 2021-07 | **2021-08 → 2026-07** | 0,67 | 5,52% / **0,46** / **21,4%** | 6,30% / **0,62** / **15,2%** | no | no |
| **B** | 2021-08 → 2026-07 | **2017-09 → 2021-07** | 0,96 | 21,76% / **1,20** / **20,4%** | 21,45% / **1,08** / **28,4%** | sí | sí |

(CAGR / Sharpe / caída máxima en el test.)

Bootstrap pareado (escalado − caja), descriptivo:

| tramo | ΔSharpe | IC95% | ΔCAGR | IC95% |
|---|--:|---|--:|---|
| A | −0,163 | [−0,387, +0,030] | −0,78 pp | [−4,96, +3,26] |
| B | +0,124 | [−0,212, +0,398] | +0,31 pp | [−5,35, +6,73] |

Pasa B y no pasa A: **DEPENDE DEL TRAMO**.

## 4. De dónde viene el alivio (descriptivo)

Retorno de cartera en las ventanas de estrés, escalado contra la estrategia sin escalar (la medida de
la 121 y la 124):

| ventana | escalado | sin escalar | Δ | la T121 (otro marco) |
|---|--:|--:|--:|--:|
| `2018Q4` | −14,20% | −10,18% | **−4,02 pp** | +3,93 pp |
| `covid_2020` | −2,59% | −6,87% | **+4,28 pp** | +4,27 pp |
| `bear_2022` | −16,98% | −15,60% | **−1,38 pp** | −0,07 pp |

**Con la config, la salida, el sizing y el costo del vivo, el alivio viene de una sola caída, la de
2020.** En `2018Q4` el escalado cae más que sin escalar. La T121 había medido +3,93 pp ahí, con el stop
duro prendido, la salida de antes del 2026-08-27, el sizing secuencial y el costo del harness. Los
textos del flag (`config/settings_manager.py` y `docs/SETTINGS_REFERENCE.md`) citaban esa atribución
como vigente, y ahora la declaran de otro marco.

Una sola caída es muy poca muestra para un mecanismo que corre en todo risk-off. Es lo que hace que
el tramo B pase: el escalado cae 20,4% donde la caja calibrada en el tramo tranquilo (`w` = 0,96)
cae 28,4%.

## 5. El marco de la cuenta (overlay de σ prendido), descriptivo

| tramo | `w` | escalado | caja | S | D |
|---|--:|---|---|---|---|
| A | 0,69 | 6,28% / 0,56 / 19,2% | 5,23% / 0,56 / 16,5% | no (−0,001) | no |
| B | 0,80 | 19,16% / 1,29 / 15,7% | 17,10% / 1,25 / 17,9% | sí | sí |

La misma lectura daría **DEPENDE DEL TRAMO**. Con el overlay prendido, el escalado contra la
estrategia sin escalar da −1,72 pp en `2018Q4`, −2,29 pp en `covid_2020` y +4,66 pp en `bear_2022`:
con los dos mecanismos prendidos, lo que el escalado agrega está en 2022, y en las dos caídas rápidas
resta. Por qué no se midió aparte.

## 6. Qué significa para la cuenta

- **No hay evidencia fuera de muestra de que el escalado compre la caída mejor que la caja, ni de que
  la compre peor.** Cada tramo dice una cosa, y ninguna se distingue del ruido.
- **Su alivio, con la config de hoy, sale de una sola caída (2020)**, no de dos como se creía.
- La lectura de la 124 sigue en pie: el factor es una **preferencia de riesgo**, no un criterio. Lo
  que cambia es la evidencia con que se lo elige, y eso va a la acción manual del factor, que sigue
  siendo de Chapa.

## 7. Lo que el diseño no saca de muestra

El factor (0,25) y la SMA200 se eligieron mirando la muestra entera (T115, T121). Lo que se calibró
fuera de cada test es la `w` de la caja, no el régimen. Que el escalado gane en B no prueba que vaya a
ganar en la próxima caída; prueba que, con la de 2020, compró la caída mejor que una caja calibrada
en otro lado.
