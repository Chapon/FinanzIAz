# RELECTURA-POR-COSTO (tarea 469) — los veredictos de salida, con el costo del vivo · 2026-11-25

**Ningún veredicto cambia.** La T170 (la salida viva, `soff_t2.0`) sigue en **NO MOVER**, y la 219
(demorar la salida por señal) sigue en **NO-SHIP: ningún brazo pasa**. Las dos re-lecturas son
válidas, y al costo del harness las dos reproducen lo publicado al decimal. No se re-decide nada y
no se tocó ningún setting.

Origen: `docs/compra_venta_rendimiento_2026-11-24.md` §1 y la 468 (`docs/costos_t468_2026-11-25.md`):
el harness cobra 0,15% por lado y el vivo ~0,063%, y un costo más alto favorece al brazo que opera
menos.

## 1. Qué veredictos podían darse vuelta

**La regla que ordena el listado:** bajar el costo sólo ayuda al brazo que mueve más capital. Un
veredicto puede darse vuelta únicamente si el brazo que **perdió** es el que más rota, o si el que
**ganó** es el que menos rota. En los otros casos, el costo del vivo refuerza lo que ya se decidió.

| tarea | qué decidió | rotación de los brazos | ¿puede darse vuelta? |
|---|---|---|---|
| **T170** | NO MOVER (`soff_t2.0`) | desafiante `s2.0_t2.0` **+11%** de trades (2.808 contra 2.531) | **sí**: el que perdió rota más ⇒ **releída (§3)** |
| **T219** | NO-SHIP | los candidatos rotan **menos** (de 2.531 a 546 trades) | en principio no, pero su §4.1 atribuye el efecto a operar menos ⇒ **releída (§2)** |
| T37 / la 167 | NO-SHIP en el rerun de la 167 | la misma rejilla stop × trailing | la re-decidió la T170, y su rejilla va en el §3 |
| T34, T47 | NO-SHIP | variantes del stop duro | el stop duro está apagado en vivo desde el 2026-08-27; la rejilla de la T170 cubre esas variantes |
| T115, T121 | el factor del régimen | mismos trades, otro tamaño | ya releídos con el costo del vivo por la 468 y la 465 |
| T39, T45, T49, T21 | NO-SHIP | ranking o prioridad entre candidatos: los mismos lugares y la misma salida | no: la rotación es la misma por construcción, salvo el camino |
| T7 | NO-SHIP | por trade, sin cartera | no: el costo es proporcional a lo operado en cada tramo, y no hay rotación de cartera |
| T51, T54, T38, T26, T26b | sin veredicto | — | corridas inválidas |

## 2. La 219 releída — sigue NO-SHIP

`python scripts/run_signal_exit_delay_t219.py --allow-stale-artifacts --costo vivo` (la opción es
nueva; sin ella, el costo del harness de siempre).

| brazo | harness: CAGR / Sharpe / caída / trades | vivo: CAGR / Sharpe / caída / trades |
|---|---|---|
| `age3` (la viva) | 8,78% / 0,55 / 28,4% / 2.531 | **13,72% / 0,79 / 29,5% / 2.531** |
| `age5` | 12,21% / 0,71 / 28,1% / 2.193 | 14,77% / 0,83 / 27,7% / 2.187 |
| `age10` | 13,99% / 0,75 / 34,4% / 1.613 | 16,38% / 0,87 / 32,0% / 1.641 |
| `age20` | 14,72% / 0,77 / 33,8% / 1.205 | 16,86% / 0,87 / 33,4% / 1.199 |
| `AZAR_MISMA_TASA` | 10,87% / 0,64 / 28,7% / 2.264 | 15,31% / 0,85 / 28,4% / 2.276 |

- **Sanity:** al costo del vivo, el baseline reproduce el ancla de la 468 (13,72% / 0,79 / 2.531);
  oráculo − azar +25,35 pp; contabilidad OK; monotonía sí. **VÁLIDA.** Al costo del harness,
  todo idéntico a lo publicado.
- **El efecto se achica a la mitad:** `age20` pasa de +5,94 pp a **+3,13 pp**, y `age5` de +3,43 pp a
  **+1,05 pp**. Ningún brazo pasa las cuatro condiciones: `age5` y `age10` fallan en las ventanas de
  estrés, y `age10` y `age20`, en la caída.
- **Su §4.1 se refuerza.** Decía que el 61% del efecto de `age5` era *«salir menos»*: el azar
  igualado en tasa ganaba +2,09 pp contra +3,43 pp. Con el costo del vivo, el azar gana **+1,59 pp**
  y `age5` **+1,05 pp**. Todo el efecto de `age5` se explica por operar menos.

## 3. La T170 releída — sigue NO MOVER

`python scripts/run_exit_policy_t170.py --allow-stale-artifacts --costo vivo` (con otro costo, el
tag del cache cambia).

| | harness (lo publicado) | vivo |
|---|---|---|
| `soff_t2.0` (la viva), muestra completa | 8,78% / 0,55 / 28,4% / 2.531 | **13,72% / 0,79 / 29,5% / 2.531** |
| `s2.0_t2.0` (el desafiante) | 4,98% / 0,36 / 44,2% / 2.808 | 10,77% / 0,66 / 41,5% / 2.789 |
| **D1** ΔCAGR OOS ≥ +1 pp | +1,76 pp, pasa | **+2,11 pp, pasa** |
| **D2** el desafiante gana ≥ 4/5 folds | 3/5, falla | **3/5, falla** |
| **D3** cola ≥ −2 pp | −2,12 / +1,19, falla | **+12,82 / +1,37, pasa** |
| **D4** IC95% inferior > 0 | [−10,97, +2,11], falla | **[−9,05, +2,50], falla** |
| **D5** caída ≤ viva + 1 pp | +15,82 / +0,49, falla | **+12,04 / −3,01, falla** |

Folds al costo del vivo (viva / desafiante / Δ): −3,47% / 2,73% / +6,19 · 5,90% / 6,09% / +0,20 ·
12,09% / 9,52% / −2,58 · 3,88% / 14,84% / +10,96 · 27,61% / 21,78% / −5,83.

- **Sanity:** contabilidad, oráculo contra azar (+3,12 pp, −8,53 pp de caída) y reproducción de la
  viva contra la 468 (13,72%): OK. **VÁLIDA.** Al costo del harness reproduce las tres celdas de
  la T34 y el veredicto publicado.
- **El costo mejora al desafiante** (D1 +1,76 → +2,11 pp, y D3 pasa a cumplirse), como predice la
  regla del §1, pero no alcanza: sigue ganando sólo 3 de 5 folds, el intervalo cruza el cero y la
  caída dentro de muestra sube 12 pp.

**La rejilla (§7, descriptiva) tiene un defecto de lectura que el costo del harness no dejaba ver.**
Al costo del vivo, una celda queda marcada *«excluye el cero»*: `s2.0_t3.0`, con ΔCAGR OOS
**+1,40 pp** y un IC95% de **[−12,59, −0,07]**. El punto es positivo y el intervalo es entero
negativo porque salen de dos muestras distintas: el ΔCAGR de las curvas fuera de muestra y el IC
del bootstrap sobre la **muestra completa**. Y la regla cuenta como *«decidible»* un intervalo
entero negativo, que en todo caso diría que esa celda es **peor** que la viva. No cambia el
veredicto (la rejilla es descriptiva), y queda como la tarea **472**.

> **La 472, 2026-11-27: con el IC fuera de muestra, `s2.0_t3.0` da [−3,66, +7,31] y cruza el
> cero, y son otras cuatro las que lo excluyen, por arriba.** El IC de cada celda sale ahora de
> las mismas curvas fuera de muestra que su ΔCAGR, como congeló el §7, y la lectura separa el
> intervalo entero positivo (candidata) del entero negativo (peor que la viva). Al costo del
> vivo (`--costo vivo`, la misma muestra; el gate no cambia):

| celda | ΔCAGR OOS | IC95% OOS | p | folds ganados | Δ caída OOS |
|---|--:|---|--:|--:|--:|
| **`soff_toff`** | +4,16 pp | [+0,69, +8,82] | 0,009 | 3/5 | −3,6 pp |
| **`s4.0_toff`** | +4,14 pp | [+0,66, +8,57] | 0,011 | 4/5 | −3,4 pp |
| **`s6.0_toff`** | +4,00 pp | [+0,49, +8,63] | 0,011 | 3/5 | −3,6 pp |
| **`s4.0_t3.0`** | +3,68 pp | [+0,31, +8,13] | 0,015 | 4/5 | +0,7 pp |
| `s3.0_t3.0` | +3,41 pp | [−0,57, +8,55] | 0,048 | 4/5 | +0,7 pp |
| `soff_t3.0` | +2,80 pp | [−0,61, +7,46] | 0,053 | 4/5 | +1,4 pp |
| `s6.0_t3.0` | +2,79 pp | [−0,66, +7,49] | 0,052 | 4/5 | +1,4 pp |
| `s2.0_t2.0` | +2,11 pp | [−2,63, +7,09] | 0,193 | 3/5 | −3,0 pp |
| `s2.0_toff` | +1,94 pp | [−3,25, +8,22] | 0,212 | 2/5 | −0,9 pp |
| `s3.0_toff` | +1,54 pp | [−2,80, +6,60] | 0,216 | 3/5 | +3,8 pp |
| `s2.0_t3.0` | +1,40 pp | [−3,66, +7,31] | 0,245 | 2/5 | +1,8 pp |
| `s6.0_t2.0` | +0,36 pp | [−1,11, +2,08] | 0,332 | 3/5 | −0,6 pp |
| `s4.0_t2.0` | −0,35 pp | [−2,42, +1,68] | 0,651 | 2/5 | +3,2 pp |
| `s3.0_t2.0` | −1,54 pp | [−5,43, +2,18] | 0,793 | 2/5 | +3,0 pp |

> Son las mismas cuatro que al costo del harness (`docs/exit_policy_t170_2026-09-10.md` §3):
> `soff_toff`, `s4.0_toff`, `s6.0_toff` y `s4.0_t3.0`. Cada una abre su propio pre-registro,
> con gate de multiplicidad: la tarea **477**. Nada se cabla.

## 4. Lo que queda

- **Para la cuenta:** nada cambia. La salida viva se sostiene con el costo real, y demorar la venta
  por señal sigue sin valer lo que cuesta en tenencia y en estrés.
- **El instrumento:** la opción `--costo` de los dos runners queda para releer lo que haga falta.
  `_common_kwargs` de la T219 la lee con el harness por default, así que los runners que la
  importan no cambian.
