# Re-lectura — ACTIVO-CONTRA-PASIVO-DE-IGUAL-RIESGO con la tajada por día (tarea 466) · **NO DECIDIBLE · corrida VÁLIDA · el veredicto no cambia**

**Fecha:** 2026-11-24 · **Pre-registro, sin tocar:** `docs/activo_pasivo_prereg_t456_2026-11-23.md`
(`6d73516`) · **Runner:** `scripts/run_activo_pasivo_t456.py` · **Comando:**
`python scripts/run_activo_pasivo_t456.py --allow-stale-artifacts --cache-dir .cache/t456 --tajada-del-dia`

**Por qué se relee:** la 456 corrió el brazo `vivo` con el sizing secuencial de `simulate_portfolio`,
en el que cada compra escalada del día agrandaba a la siguiente. La tarea 464 lo encontró y agregó
`tajada_del_dia`, que les da a todas las compras del día la misma tajada, como el motor vivo. Cambia
el instrumento y no la pregunta: los brazos, la regla de la `w`, los folds, el bootstrap y los cuatro
criterios son los del pre-registro. Es lo mismo que hicieron las re-lecturas de la T33 y la T36.

---

## VEREDICTO: **NO DECIDIBLE**, igual que la 456

| | condición | 456 (secuencial) | **466 (tajada por día)** | |
|---|---|--:|--:|---|
| **C1** | ΔCAGR OOS (pasivo − vivo) ≥ +1,00 pp | +6,40 pp | **+6,49 pp** (7,17% contra 0,68%) | PASA |
| **C2** | el pasivo gana ≥ 4 de 5 folds | 4/5 | **4/5** | PASA |
| **C3** | IC95% del bootstrap pareado > 0 | [−1,61, +14,76], p = 0,056 | **[−1,69, +14,89], p = 0,055** | **FALLA** |
| **C4** | caída OOS del pasivo ≤ vivo + 1 pp | 16,4% contra 22,8% | **14,0% contra 25,5%** | PASA |

**No se cambia nada.** El punto estimado casi no se mueve, porque los dos lados del gate bajan
juntos. El vivo pierde retorno con la tajada por día (fuera de muestra, de 2,06% a 0,68% por año). El
pasivo también baja: la regla fija su `w` con la caída del vivo en la calibración (ahora 20,6%), y
la `w` más alta que no la supera pasa de 0,65 a 0,55. El intervalo sigue cruzando el cero por poco.

## Sanity (los cinco en OK)

1. `vivo_sin_regimen` reproduce la T170: 8,78% / 0,55 / 2.531. No escala, así que es idéntico bit a
   bit al de la 456 (la 464 lo verificó).
2. Control del pasivo: con `w = 1` el error es 2,66e-15.
3. Contabilidad OK.
4. El escalado toca el 18,0% de las entradas.
5. `w = 0,55`.

## Muestra completa, mismo calendario (descriptivo)

| brazo | CAGR | Sharpe | caída |
|---|--:|--:|--:|
| `vivo` (tajada por día) | 6,41% | 0,47 | 25,5% |
| `vivo_sin_regimen` | 8,78% | 0,55 | 28,4% |
| `SPY_caja` (w = 0,55) | 8,47% | 0,86 | 19,2% |
| `UNIV_caja` (w = 0,50) | 8,70% | 0,98 | 18,9% |
| SPY | 15,19% | 0,85 | 33,7% |

Fuera de muestra, fold por fold (vivo contra pasivo): −10,70% contra −2,09%; 0,59% contra 7,50%;
3,48% contra 12,00%; −6,07% contra 9,71%; y en el último, 21,65% contra 11,58%. Como en la 456, el
único año que gana la estrategia es el último.

Descriptivo, no decide: `vivo` contra `UNIV_caja` da +6,92 pp, con IC [−1,04, +14,60]. En las
ventanas de régimen, el vivo cae más que el pasivo en 2018Q4 (−16,0% contra −7,5%) y en 2022
(−18,5% contra −9,8%), y menos en el COVID (−5,0% contra −6,8%).

## Lo que sale de acá

- **La conclusión de la 456 se sostiene con el instrumento corregido:** el pasivo rinde más fuera de
  muestra, en cuatro de cinco años y con menos caída, pero el intervalo no alcanza el umbral
  congelado. *«El pasivo gana»* no se afirma.
- **El escalado por régimen sale peor parado que en la 456:** con la tajada del vivo, sobre la muestra
  completa, cuesta 2,38 pp de CAGR por año por 2,9 pp de caída, y la caja constante compra esa caída
  más barata (la 464). Eso ya está en la acción manual del factor y en la tarea 465. Esta corrida no
  lo compara fuera de muestra: cada vivo tiene su propio pasivo, con su propia `w`.
- **Cuándo vuelve a ser decidible:** lo mismo que la 456. Hacen falta años nuevos fuera de muestra,
  o una muestra que no sea este cohorte.
