# Pre-registro — REGIMEN-CONTRA-SU-CAJA (tarea 465) · 2026-11-25

**Congelado antes de escribir el runner.** Nada de lo que sigue se cambia después de correr; si
algo tiene que cambiar, va como enmienda fechada y declarada antes de leer ningún Δ.

Origen: la 464 (`docs/tajada_t464_2026-11-24.md` §3), corregida por el costo de la 468
(`docs/costos_t468_2026-11-25.md` §3). La decisión del factor es de Chapa, y está en *Acciones
manuales*.

## 0. Lo que ya se vio, declarado

- **Sobre la muestra completa, con el costo del vivo** (468 §3): el escalado a ×0,25 da **11,35% /
  Sharpe 0,77 / caída 21,4%**, y la estrategia sin régimen con 30% de caja constante (`w` = 0,70,
  elegida mirando la caída de la muestra entera) da **9,75% / 0,80 / 21,1%**. O sea, el régimen
  **gana en CAGR** (crecimiento anual compuesto) por 1,60 pp y **pierde en Sharpe** por 0,03.
- **El criterio de la tarea se escribió antes de eso** (el 2026-11-24, al costo del harness, cuando
  el régimen perdía en las dos): Sharpe y caída. **No se cambia por CAGR**, que es la métrica que hoy
  favorece al régimen: sería elegir el criterio mirando el resultado. El CAGR va en el descriptivo.
- **La 124 midió** que el 99,2% del beneficio del escalado está antes de 2022, en las dos caídas
  rápidas de la muestra (`2018Q4` y `covid_2020`), y que un hold-out temporal en un solo sentido
  deja el tramo de test sin ningún evento de ese tipo: un *«no se detecta»* ahí es ausencia de
  población, no evidencia en contra. **Por eso el diseño es en los dos sentidos** (§3).
- **Los parámetros del régimen** (SMA200 de SPY, factor 0,25) se eligieron en la T115 y la T121
  mirando la muestra entera, 2018 y 2020 incluidos. Lo que este diseño saca de muestra es **la
  `w` de la caja**, no el régimen. Si el régimen gana en el tramo con las caídas, eso no prueba que
  generalice a la próxima caída: prueba que, con esas caídas, compra la caída mejor que una caja
  calibrada en otro lado.

## 1. La pregunta

Con la `w` de la caja constante fijada **en un tramo** para que caiga lo mismo que el escalado, ¿el
escalado tiene, **en el otro tramo**, un Sharpe al menos igual y una caída no peor?

## 2. Config

La de la T170 con el costo del vivo (`live_cost_model()`) y la tajada por día: 126 tickers
(`data/harness_universe_live_acct2.txt`, huella verificada), cohorte `2016-09-12..2026-09-09` (con
`--allow-stale-artifacts`), entradas `analyze BUY` PIT, 10 slots, `equal_weight`, `cap_days=250`,
`eval_mode=touch`, `fill_mode=decision`, gates de re-entrada modelados, hard stop apagado
(`NO_STOP`), trailing 2,0 ATR, TP 4,0 ATR, la salida de la T219, capital 50.000, caja al 0%.

**El overlay de σ va apagado en el gate**, como en todas las mediciones del precio del régimen
(456, 464, 468), y prendido en el descriptivo, que es como corre la cuenta (la 457 no lo distinguió
del ruido, y la decisión de apagarlo es de Chapa).

## 3. Los brazos y los dos tramos (fijos)

| brazo | qué es |
|---|---|
| `regimen` | la config del §2 más el escalado a ×0,25 en risk-off (`make_entry_filter(mode="scale")` sobre `SPY__max__1d`) |
| `sin_regimen` | la config del §2 |
| `caja_A`, `caja_B` | `sin_regimen` con caja al 0% a proporción constante `w`, rebalanceada el primer día hábil de cada mes (`mezcla_constante` de la 456, con el costo del vivo sobre lo operado) |

Cada brazo se corre **una sola vez**, de punta a punta, y se corta. Los dos tramos:

| | calibración de `w` | test |
|---|---|---|
| **A** | desde la primera fecha → **2021-07-31** | **2021-08-01 → 2026-07-31** (el OOS de la T170) |
| **B** | **2021-08-01 → 2026-07-31** | desde la primera fecha → **2021-07-31** (tiene `2018Q4` y `covid_2020`) |

**La regla de `w`, congelada:** en el tramo de calibración, la **más alta** de `0,01, 0,02, …, 1,00`
cuya mezcla (armada sobre las fechas de ese tramo, arrancando en su primera fecha) tiene una caída
máxima que **no supera** la de `regimen` cortado al mismo tramo.

## 4. El gate

Para cada tramo `f` ∈ {A, B}, sobre las fechas de test (la mezcla arranca en la primera fecha de
test; `regimen` se corta a las mismas fechas):

- **S_f**: Sharpe de `regimen` **≥** Sharpe de `caja_f` (`sharpe_annual`).
- **D_f**: caída máxima de `regimen` **≤** la de `caja_f` **+ 1,00 pp**.
- El tramo **pasa** si S_f y D_f.

**Lectura, congelada:**

- **«EL ESCALADO SE SOSTIENE»**: pasan A y B.
- **«EL ESCALADO NO SE SOSTIENE»**: no pasa ninguno. NO-SHIP documentado; apagarlo
  (`paper_regime_scale_enabled=false`, con la app cerrada) lo decide Chapa.
- **«DEPENDE DEL TRAMO»**: pasa uno solo. Se documenta cuál, y el escalado sigue siendo lo que la 124
  dijo que era: una **preferencia de riesgo**. No se toca nada.

En los tres casos se publica, por tramo, el bootstrap pareado del ΔSharpe y del ΔCAGR (`regimen` −
`caja_f`; bloque 20, 2.000 resamples, semilla 12345), **descriptivo**: el gate es de punto, como
lo propuso la tarea, y el IC dice cuánto pesa.

**Lo que se espera, escrito antes de correr.** Con lo de la 124: en B (el test con las caídas
rápidas), el escalado debería caer menos que una caja calibrada en el tramo tranquilo; en A, la caja
calibrada contra las caídas de B va a tener poca `w` y el Sharpe de las dos debería quedar parecido.
Lo más probable es **«DEPENDE DEL TRAMO»** o **«SE SOSTIENE»** con márgenes chicos en A.

## 5. Sanity (si uno falla, la corrida es INVÁLIDA y no hay veredicto)

1. **Reproducción externa, al costo del harness:** `sin_regimen` da **8,78% / 0,55 / 2.531** (la
   T170, tolerancias de la T219) y `regimen` da **6,41%** de CAGR (la 464).
2. **Reproducción al costo del vivo** (la 468, muestra completa): `sin_regimen` **13,72% / 0,79 /
   29,5%** y `regimen` **11,35% / 0,77 / 21,4%**, a dos decimales.
3. **El escalado muerde:** la fracción de entradas de `regimen` con `size_factor < 1` está entre el
   1% y el 50% (la regla de la 456).
4. **`w` existe** en los dos tramos: alguna `w` de la grilla cumple la regla.
5. **Calendario:** las fechas comunes de `regimen` y `sin_regimen` cubren al menos el 99% de cada
   curva; todo se compara sobre esas fechas.

## 6. Descriptivo obligatorio (no decide)

Por tramo: CAGR, Sharpe y caída de los tres brazos, `w`, los dos bootstraps; el retorno de cartera
de `regimen` y `caja_f` en las ventanas de estrés (`regime_window_returns`: `2018Q4`, `covid_2020`,
`bear_2022`); la misma lectura con el overlay prendido en `regimen` y `sin_regimen` (el marco de la
cuenta); y, como referencia, la comparación de la 468 sobre la muestra completa.

## 7. Lo que no hace

No toca la cuenta ni ningún setting. No re-elige el factor (0,25) ni la SMA: un barrido sería otra
tarea. No decide nada por Chapa: con cualquier lectura, el factor sigue siendo su decisión.
