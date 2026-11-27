# El sanity del oráculo con cada orden de candidatos (Tarea 478) · **el sanity de un sorteo se descarta como gate**

**Fecha:** 2026-11-27 · **Script:** `scripts/medir_oraculo_t478.py` · **Comando:**
`python scripts/medir_oraculo_t478.py --allow-stale-artifacts --costo vivo` y `--costo harness`
(21 sorteos del control; los artefactos son los de la T170, que terminan el 2026-09-09).
**Origen:** la 477, que quedó INVÁLIDA por este sanity en el marco del vivo
(`docs/candidatas_rejilla_t477_2026-11-27.md`). Descriptivo: no decide nada, no cambia ningún
umbral y no re-corre la 477. Sin red, sin tocar `finanzias.db`.

Población: la de la T170 (126 tickers, 141.417 entradas, `2016-09-12..2026-09-09`, 10 slots,
`cap_days=250`, `touch`/`decision`, gates de re-entrada). Todo sobre `s2.0_t2.0`, que es donde la
T170 y la 477 montan el oráculo (con el stop apagado el filtro no tiene qué filtrar).

---

## Qué mide el sanity, y qué da por sentado

El §5.2 de la T170 —heredado por la 477— pide que el **oráculo del stop** (dispara el stop sólo si
el precio a 20 ruedas está más abajo) le gane a un **control igualado en tasa** (suprime stops al
azar) por ≥ +1,50 pp de CAGR **y** ≤ −5,00 pp de caída. La idea viene de la T26: separar *cuántos*
stops se suprimen de *cuáles*, para saber si el instrumento ve **calidad** de stop. Da por
sentadas dos cosas: que el control suprime **la misma proporción** que el oráculo, y que **un**
sorteo del control alcanza para comparar.

## 1. El control no está igualado

La T26 fijó la tasa del control como la proporción de salidas por stop del oráculo sobre las de la
base: 6,2% contra 13,4%, **0,463** (`RANDOM_KEEP_PROB`), en su marco de 5 slots y 41 tickers. Con
la población de la T170 ya no iguala:

| marco | salidas por stop de la base | oráculo (razón) | control, mediana de 21 (razón) |
|---|--:|--:|--:|
| alfabético, costo del harness | 19,8% | 10,2% (**0,513**) | 13,2% (**0,663**) |
| alfabético, costo del vivo | 19,0% | 10,1% (**0,529**) | 12,3% (**0,644**) |
| vivo, costo del harness | 20,3% | 9,2% (**0,454**) | 12,9% (**0,638**) |
| vivo, costo del vivo | 19,2% | 9,5% (**0,495**) | 12,5% (**0,653**) |

**En los cuatro marcos el control deja pasar más stops que el oráculo** (~0,65 contra ~0,50). La
razón es mecánica: el control sortea en cada consulta, y un stop suprimido se vuelve a consultar
en las ruedas siguientes, así que el 46,3% por consulta termina en ~65% de las salidas; el
oráculo, en cambio, suprime de forma persistente mientras el futuro le dé la razón. Por consulta,
el oráculo deja disparar el 28–31% y el control el 45–49%. O sea que la comparación de la T170
mezcla calidad con cantidad, que es justo lo que el control existía para separar.

## 2. Un solo sorteo es casi una moneda

El oráculo contra 21 sorteos del control (el de la T170, semilla 20260813, y 20 más):

| marco | ΔCAGR mediana [p10, p90] | ΔmaxDD mediana [p10, p90] | el sorteo de la T170 | el sanity pasaría |
|---|---|---|---|--:|
| alfabético, harness | +5,38 [+4,21, +7,82] | −9,77 [−14,75, −3,37] | +4,76 / −6,75 | **17 de 21** |
| alfabético, vivo | +3,12 [+1,52, +5,01] | −7,66 [−9,95, −2,84] | +3,12 / −8,53 | **14 de 21** |
| vivo, harness | +3,85 [+2,43, +4,60] | −6,41 [−8,23, −2,87] | +3,19 / −5,50 | **14 de 21** |
| **vivo, vivo** (el de la 477) | +2,49 [+1,79, +4,81] | **−5,06** [−7,84, −2,76] | **+2,37 / −3,61** | **10 de 21** |

- **La parte del CAGR del sanity se sostiene en todos los marcos:** el p10 del ΔCAGR supera el
  +1,50 en los cuatro. El instrumento ve calidad de stop también con el orden del vivo.
- **La parte de la caída es ruido de sorteo:** entre el p10 y el p90 hay de 5 a 11 pp. Con el
  orden del vivo, la mediana (−5,06) cae justo sobre el umbral, y la 477 sacó un sorteo del lado
  malo (−3,61). La T170, con el alfabético, uno del lado bueno (−6,75), en un marco donde el sanity
  pasa 17 de cada 21 veces.

## 3. Qué se concluye

- **El sanity §5.2 tal como está —un sorteo, con la tasa de la T26— se descarta como gate, en
  cualquier marco.** No iguala la tasa que dice igualar, y su parte de caída depende del sorteo:
  pasa entre el 48% y el 81% de las veces según el marco. La razón es ésa, y no que el marco del
  vivo sea inválido: el instrumento ve calidad de stop en los cuatro.
- **La 477 no se re-corre** con otro sanity: sería re-especificarla para salvarla. Su pregunta
  queda abierta, y si vale volver a hacerla, va con un pre-registro nuevo y el sanity nuevo.
- **El reemplazo es la 479:** un control igualado de verdad (la tasa de cada corrida calibrada para
  que su razón de salidas por stop sea la del oráculo) y varios sorteos, con la regla escrita
  antes de usarse; y releer qué veredictos publicados cambian de VÁLIDA a INVÁLIDA, o al revés,
  con él. Usan este sanity: T26, T26b, T34, T37 (y su re-corrida T167), T219, T170 y T477.
- **No se tocó nada:** ni un umbral, ni un runner, ni la política viva.
