# Veredicto — ACTIVO-CONTRA-PASIVO-DE-IGUAL-RIESGO (tarea 456) · **NO DECIDIBLE · corrida VÁLIDA**

**Fecha:** 2026-11-23 · **Pre-registro congelado antes del runner:**
`docs/activo_pasivo_prereg_t456_2026-11-23.md` (`6d73516`) · **Runner:**
`scripts/run_activo_pasivo_t456.py` · **Comando:**
`python scripts/run_activo_pasivo_t456.py --allow-stale-artifacts --cache-dir .cache/t456`

Población: 126 tickers (huella verificada), 141.417 entradas `analyze BUY` PIT, ventana del cohorte
`2016-09-12..2026-09-09`, 10 slots. El vivo opera desde el **2017-09-08**, al terminar el
calentamiento, y los dos brazos se miden sobre esas mismas 2.262 fechas. Sin red, sin tocar
`finanzias.db`, **sin tocar ninguna perilla viva**.

---

## VEREDICTO: **NO DECIDIBLE** — fuera de muestra el pasivo rinde 6,4 puntos más por año, y el intervalo cruza el cero

| | condición | resultado | |
|---|---|---|---|
| **C1** | ΔCAGR OOS (pasivo − vivo) ≥ +1,00 pp | **+6,40 pp** (8,45% contra 2,06%) | **PASA** |
| **C2** | el pasivo gana ≥ 4 de 5 folds | **4/5** | **PASA** |
| **C3** | IC95% del bootstrap pareado > 0 | **[−1,61, +14,76] pp**, p = 0,056 | **FALLA** |
| **C4** | caída OOS del pasivo ≤ vivo + 1 pp | **16,4% contra 22,8%** | **PASA** |

**Era el riesgo escrito antes de correr** (§4 del pre-registro): *«C3 es la que puede fallar … Si
falla, el resultado es "NO DECIDIBLE" y así se publica, aunque el punto estimado sea grande»*. Así
se publica. **No se cambia nada.**

**Cómo leerlo, sin estirarlo:**

- **El punto estimado es grande y va en una sola dirección:** el pasivo rinde más en cuatro de
  cinco años, con menos caída. El bootstrap da un 94% de los resamples a favor del pasivo (p = 0,056
  unilateral). Es evidencia de que la estrategia viva no agrega valor sobre SPY con caja.
- **No alcanza el umbral congelado.** Cinco años de retornos diarios dejan un intervalo de 16 pp de
  ancho. Sin cerrar ese intervalo, *«el pasivo gana»* no se afirma, y tampoco lo contrario: la
  estrategia **no** le gana al pasivo en ningún criterio.
- **El año que salva a la estrategia es el último.** En el fold 5 (2025-08 → 2026-07) el vivo rinde
  22,2% contra 13,8%. En los otros cuatro pierde por entre 5 y 15 puntos.

## 1. La muestra completa, sobre el mismo calendario (descriptivo)

| brazo | CAGR | Sharpe | caída |
|---|--:|--:|--:|
| **`vivo`** (la cuenta 2: régimen ×0,25) | **7,32%** | **0,52** | **22,9%** |
| `vivo_sin_regimen` (`soff_t2.0` de la T170) | 8,78% | 0,55 | 28,4% |
| **`SPY_caja` (w = 0,65)** | **9,99%** | **0,85** | **22,5%** |
| `UNIV_caja` (w = 0,60) | 10,43% | 0,97 | 22,5% |
| SPY solo | 15,19% | 0,85 | 33,7% |

- **`w` salió de la regla, no de mirar:** la caída del vivo en la calibración (hasta el
  2021-07-31) es 22,9%, y la `w` más alta de SPY que no la supera es **0,65**. Para el universo,
  0,60.
- **Exposición media del vivo: 84,8%** de la equity invertida.

## 2. Fuera de muestra, fold por fold

| fold | test | vivo | pasivo | Δ pp |
|---|---|--:|--:|--:|
| 1 | 2021-08-01..2022-07-31 | −7,73% | −2,57% | +5,16 |
| 2 | 2022-08-01..2023-07-31 | 0,88% | 8,82% | +7,94 |
| 3 | 2023-08-01..2024-07-31 | 3,72% | 14,26% | +10,54 |
| 4 | 2024-08-01..2025-07-31 | −3,79% | 11,53% | +15,31 |
| 5 | 2025-08-01..2026-07-31 | 22,23% | 13,76% | −8,47 |
| | **agregado** | **2,06%** | **8,45%** | **+6,40** |

El vivo se corrió una sola vez y se cortó (§3 del pre-registro), así que estos números no son los de
la T170, que reiniciaba la cartera en cada fold.

## 3. Sanity (los cinco en OK)

| | | |
|---|---|---|
| 1 | `vivo_sin_regimen` reproduce la T170 | **8,78% / 0,55 / 2.531** contra 8,78% / 0,55 / 2.531 |
| 2 | control del pasivo (sin costos: `w=1` = cociente de cierres, `w=0` plano) | error 2,7e-15 y 0 |
| 3 | contabilidad de los dos brazos del vivo | OK |
| 4 | el escalado muerde | **18,0%** de las entradas con `size_factor < 1` |
| 5 | `0 < w ≤ 1` | w = 0,65 |

## 4. Descriptivo (no decide)

- **`vivo_sin_regimen` contra `SPY_caja`** (con su propia `w`): ΔCAGR OOS +6,24 pp, 4/5 folds, IC
  [−1,81, +14,97]: el mismo resultado.
- **`vivo` contra `UNIV_caja`:** +7,07 pp, 4/5, IC [−0,47, +14,43]: más cerca, y también cruza el
  cero. Tiene sesgo de supervivencia (§3 del pre-registro).
- **Ventanas de régimen** (retorno compuesto de la cartera en esos días):

  | | `2018Q4` | `covid_2020` | `bear_2022` |
  |---|--:|--:|--:|
  | vivo | −15,0% | −6,1% | −16,0% |
  | `SPY_caja` | −8,9% | −8,2% | −11,6% |

  El vivo cae más que el pasivo en dos de las tres caídas, y menos en la del COVID.

## 5. Lo que sale de acá

- **Un número que no cierra → tarea 459.** El escalado por régimen a 0,25, bajo la política de
  salida viva, cuesta **1,46 pp de CAGR** (8,78% → 7,32%) y −0,03 de Sharpe por **5,5 pp** menos de
  caída. `docs/SETTINGS_REFERENCE.md` y el desvío `regime_scale` dicen que la preferencia de la 124
  pagaba **0,29 pp** por 4,2 pp, y el desvío cita **−0,34 pp**. La causa: la T121 midió con
  `AtrParams()` por defecto, que tiene el stop duro **prendido**, o sea la política de salida
  anterior a la del 2026-08-27. La preferencia se declaró con un precio que no es el de la config
  viva. Cómo seguir lo decide Chapa.
- **El pasivo como referencia en vivo ya existe:** Home pinta el universo de la cuenta en partes
  iguales (tarea 377), así que la comparación sigue a la vista sin cablear nada.
- **Cuándo vuelve a ser decidible:** con este ancho, el intervalo se cierra sobre +6 pp con unos
  **ocho años** fuera de muestra, contra los cinco de hoy. Refrescar la ventana `10y` no agrega
  muestra (T48). Hacen falta años nuevos, o una muestra que no sea este cohorte.

## 6. Límites

- Los del pre-registro: el overlay de volatilidad (457) y el Gate 6 (458) no están modelados, y su
  dirección neta sobre el Δ no se conoce. La caja cobra 0% en los dos brazos (con letras del Tesoro,
  el pasivo, que tiene más caja, ganaría más).
- Una sola década y alcista, con el universo de hoy. La comparación central es contra SPY, que no
  tiene sesgo de supervivencia.
