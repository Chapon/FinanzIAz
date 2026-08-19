# Veredicto — El múltiplo del stop ATR bajo la regla que el engine ejecuta (Tarea 34, STOP-LOOSEN)

_2026-08-18 · pre-registro congelado `docs/stop_loosen_prereg_t34_2026-08-18.md` (`1e73b2b`) ·
enmienda del sanity §7.5 `docs/stop_loosen_enmienda_t34_2026-08-18.md` ·
runner `scripts/run_stop_loosen_t34.py` · tests `tests/test_stop_loosen_t34.py`_

Universo `data/harness_universe_live_acct2.txt` (127 tickers), **143.096 entradas `analyze BUY`**
point-in-time, `portfolio_sim` con capital finito, 10 slots, `cap_days=250`, costos completos,
`eval_mode=touch`, `fill_mode=decision` y **los gates de re-entrada del engine modelados**.
Sin red, sin tocar `finanzias.db`.

---

## VEREDICTO: NO-SHIP por **C6 (máximo en el borde)** y **C5 (régimen)**. `atr_stop_mult` queda en **2.0**.

**Seis de los ocho criterios pasan, y con margen.** El walk-forward elige el mismo brazo en
**5 de 5 folds**, el efecto fuera de muestra es **+4.12 pp de CAGR**, el drawdown **mejora**
en las dos ventanas y el Sharpe sube **+0.380**. Nada de eso alcanza, porque el brazo que
elige es **`touch_off`**: *apagar el stop*.

**Y ése es exactamente el caso que C6 estaba puesto para atrapar.** Lo que la corrida dice no
es *"aflojá el stop a M\*"* — es *"el stop ATR no aporta"*, que es una afirmación mucho más
grande, mucho más dependiente del régimen, y que **no se cabla desde acá**. Abre la
**tarea 37**, con pre-registro propio.

**C5 muestra por qué la cautela no es ceremonia:** en `stress_2018q4` apagar el stop cuesta
**−1.18 pts por trade**, veinte veces la tolerancia. El guardrail no se paga en el agregado
de diez años dominados por un bull: se paga en las ventanas malas, que es para lo que existe.

---

## 1. La corrida que decide (10 slots, `touch`, gates vivos modelados)

| brazo | CAGR | Sharpe | maxDD | %stop | %trail | %tp | tomadas | G5 bloqueó |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| `touch_1.0` | −2.52% | −0.07 | 39.0% | 50.6% | 22.3% | 5% | 4176 | 6036 |
| `touch_1.5` | −1.84% | −0.02 | 40.8% | 33.6% | 19.0% | 8% | 3218 | 4060 |
| **`touch_2.0` (BASELINE — el múltiplo vivo)** | **2.01%** | **0.20** | **46.7%** | 20.1% | 12.4% | 10% | 2815 | 3141 |
| `touch_2.5` | 6.12% | 0.43 | 31.5% | 11.8% | 7.5% | 11% | 2587 | 2664 |
| `touch_3.0` | 8.71% | 0.55 | 35.6% | 7.1% | 3.2% | 11% | 2512 | 2462 |
| `touch_3.5` | 8.31% | 0.52 | 38.2% | 4.5% | 1.7% | 11% | 2460 | 2322 |
| **`touch_off`** | **9.52%** | **0.58** | **30.1%** | 0.0% | 0.0% | 12% | 2374 | 2094 |

**El múltiplo vivo tiene el peor maxDD de la rejilla (46.7%)** y el tercer peor CAGR. La
curva es monótona creciente hasta el borde suelto: no hay óptimo interior.

Los ocho criterios congelados del §8:

| # | criterio | umbral | medido | |
|---|---|---|---|---|
| C1 | ΔCAGR **fuera de muestra** (cadena OOS) | ≥ +1.00 pp | **+4.12 pp** (5.53% vs 1.41%) | PASA |
| C2 | maxDD in-sample **y** OOS | ≤ base + 1.00 pp | **−16.53 pp** y **−2.74 pp** (mejora las dos) | PASA |
| C3 | bootstrap pareado, IC95% inferior | > 0 | **[+0.0098, +0.1502]**, p=0.010 | PASA |
| C4 | ΔSharpe | ≥ +0.05 | **+0.380** | PASA |
| C5 | régimen (Δ ret/trade en los 4) | ≥ −0.05 pts | +0.24 / **−1.18** / +2.93 / +0.11 | **FALLA** |
| C6 | máximo de la curva **interior** | ∉ {3.5, off} | **`touch_off`** | **FALLA** |
| C7 | mismo múltiplo en ≥4/5 folds | ≥ 4/5 | **5/5** | PASA |
| C8 | signo a 5 slots **y** en modo `close` | las dos ≥ 0 | **+3.02 pp** y **+4.26 pp** | PASA |

La regla es un **AND de los ocho**, así que el resultado es NO-SHIP y **no se re-decide**.

## 2. El walk-forward — unánime, y aun así no alcanza

| fold (test OOS) | n_train | n_test | elige | OOS proc | OOS baseline |
|---|--:|--:|---|--:|--:|
| 2021-08 → 2022-07 | 51.854 | 16.487 | `touch_off` | **−2.51%** | −10.86% |
| 2022-08 → 2023-07 | 68.218 | 13.210 | `touch_off` | 2.77% | **3.75%** |
| 2023-08 → 2024-07 | 84.705 | 15.134 | `touch_off` | 3.22% | **4.42%** |
| 2024-08 → 2025-07 | 97.915 | 14.718 | `touch_off` | **0.64%** | 0.17% |
| 2025-08 → 2026-07 | 113.049 | 15.111 | `touch_off` | **26.71%** | 11.18% |

Cadena encadenada: **5.53%** de CAGR con **22.9%** de maxDD contra **1.41%** y **25.6%** del
baseline fijo.

**Dos lecturas que el agregado tapa y hay que decir:**

1. **El procedimiento pierde en 2 de los 5 folds** (2022-23 y 2023-24). El +4.12 pp agregado
   está **dominado por el último fold** (+26.71% vs +11.18%), o sea por los últimos doce
   meses. Un efecto que necesita un fold para existir no es el mismo objeto que uno estable.
2. **El fold que contiene el bear de 2022 es el que más lo favorece** (−2.51% vs −10.86%).
   Ahí apagar el stop protegió, porque el stop realizaba pérdidas en barras que se daban
   vuelta. Pero **C5 mide el efecto en `stress_2018q4` con signo opuesto** (−1.18 pts por
   trade). Las dos ventanas de stress no dicen lo mismo, y esa contradicción es justamente
   lo que impide leer "apagar el stop es más seguro".

## 3. Por qué C6 no es un tecnicismo

Con la rejilla de la 26b (que llegaba hasta 3.0) el máximo **parecía** estar en 3.0 y la
lectura natural era *"aflojá a 3.0"*. Extendida a 3.5 y `off`, el máximo se corre al borde y
la lectura cambia de objeto:

| | 1.0 | 1.5 | 2.0 | 2.5 | 3.0 | 3.5 | off |
|---|--:|--:|--:|--:|--:|--:|--:|
| **con gates** | −2.52% | −1.84% | 2.01% | 6.12% | 8.71% | 8.31% | **9.52%** |
| **sin gates** | −0.49% | 0.76% | 4.41% | 6.19% | 9.92% | **10.52%** | 10.50% |

**La conclusión del borde es robusta a los gates** (en las dos filas el máximo está en el
extremo suelto), pero **dónde cae exactamente el máximo no lo es**: sin gates es `3.5`, con
gates es `off`. Que la ubicación del óptimo dependa de si modelás o no un gate de
re-entrada es, por sí solo, motivo suficiente para no cablear un múltiplo desde esta corrida.

Y el survivorship pesa acá más que en ningún otro brazo de la serie: **un universo de 127
sobrevivientes es el ambiente más benévolo posible para no tener stop**. Estaba declarado
en el §10 del pre-registro antes de correr, y ahora es la advertencia central.

## 4. La descomposición stop-duro vs trailing (descriptivo, NO decide)

El diagnóstico del §5, con el stop duro apagado y el trailing en 2.0×ATR:

| brazo | CAGR |
|---|--:|
| `touch_2.0` — stop 2.0 **y** trail 2.0 (lo vivo) | 2.01% |
| `D1` — stop **off**, trail 2.0 | **9.17%** |
| `touch_off` — stop off **y** trail off | 9.52% |

**Casi todo el daño está en el stop duro desde el precio de entrada, no en el trailing desde
el máximo.** Apagar sólo el stop duro recupera 7.16 de los 7.51 pp. Es descriptivo —el knob
vivo es uno solo y el desacople quedó NO-SHIP en la T7— pero es **la pista más concreta que
deja la tarea** y va derecho al enunciado de la 37.

## 5. El sexto desvío, cuantificado

Modelar los gates de re-entrada del engine **baja el CAGR en los siete brazos**, entre
−0.07 pp y −2.60 pp, y **no de forma pareja**:

- `touch_1.5` pierde **−2.60 pp**; `touch_2.5` pierde **−0.07 pp**. No es un nivel común.
- El gate bloqueó **3.141** candidatos en el baseline —**más que los 2.815 trades que la
  cartera toma**— y aun así `n_taken` cayó apenas 3 (2818 → 2815). Con ratio de selección
  ~55:1 **el slot bloqueado se lo lleva el siguiente candidato el mismo día**: el gate cambia
  la **composición**, no la exposición. **70,4%** de los trades difieren.
- Efecto sobre la forma: mueve el máximo de `3.5` a `off`.

Confirma el criterio de la T33 aplicado en el pre-registro: los brazos disparaban a tasas
muy distintas, así que el desvío **no se cancelaba**. Modelarlo era necesario.

## 6. El sanity — el instrumento quedó validado (a la segunda)

| sanity | umbral | medido | |
|---|---|---|---|
| contabilidad | ≤ 1e-6 | ok en los 16 brazos | OK |
| oráculo vs azar — ΔCAGR | ≥ +1.50 pp | **+6.14 pp** | OK |
| oráculo vs azar — ΔmaxDD | ≤ −5.00 pp | **−17.59 pp** | OK |
| brazo `off` no dispara stops | == 0.0 | 0.0% | OK |
| monotonía de la tasa de disparo | no creciente | 50.6 → 0.0 | OK |
| gates cableados (ON dispara, OFF no) | — | 3141 / 0 | OK |
| los gates muerden (composición) | ≥ 10% | **70,4%** | OK |

**La primera corrida quedó INVÁLIDA** porque el sanity §7.5 original —una banda sobre la
"fracción de elegibles bloqueada"— estaba mal especificado: conflacionaba el **tamaño del
desvío** medido sobre el path sin gates (28,2%) con la **tasa de bloqueo en régimen** del
path ya gateado (2,44%), que es chica porque el gate es auto-extintivo. Se declaró la
enmienda con disclosure completo de lo ya visto, se reemplazó por el check de la 26b (mismo
umbral, mismo helper) y se volvió a correr. Detalle en
`docs/stop_loosen_enmienda_t34_2026-08-18.md`.

**Dos aproximaciones del instrumento que no estaban declaradas y quedan escritas** (ninguna
mueve el signo de nada, pero heredarlas en silencio es exactamente el defecto que esta serie
viene arreglando):

- **El `ret` que alimenta Gate 5 es neto de costos** (`proceeds/entry_cost − 1`, ~0,3% de
  round-trip) mientras el engine compara el `fill_price` del SELL contra el avg de compra
  **sin** costos (`engine.py:265`). Con el umbral vivo en `0.0` —cualquier pérdida bloquea—
  el harness bloquea una franja fina de ciclos que en vivo pasarían. Efecto de segundo
  orden y del lado conservador.
- **La cadena OOS concatena bloques que se solapan en el tiempo:** con `cap_days=250` los
  trades del test del fold *k* pueden cerrar dentro del bloque *k+1*. No hay doble conteo de
  plata (la equity encadena), pero `cagr()` anualiza por largo de curva, así que sesga
  **contra** el brazo de ciclos más largos — o sea contra el candidato. El +4.12 pp de C1 es,
  por ese lado, conservador.

## 7. Qué NO se cabla y qué queda declarado

- **`atr_stop_mult` sigue en 2.0.** No cambia nada de la política de salida viva.
- **El lead de la 26b §3 queda resuelto, pero no como esperaba:** el múltiplo vivo **sí**
  está en un tramo malo de la curva (peor maxDD de la rejilla, tercer peor CAGR), sólo que
  la curva **no tiene óptimo interior**, así que no hay múltiplo que cablear — hay una
  pregunta más grande abierta.
- **El sexto desvío queda declarado y modelable:** `live_gates` en `portfolio_sim` (default
  OFF ⇒ cero cambio para lo publicado) + declarado en `harness_config.deviations()`.
- **Se abre la tarea 37 (STOP-VALUE):** *¿el stop ATR aporta?*, con pre-registro propio.
- **La tarea 36 (REENTRY-DECL)** queda desbloqueada: el enabler ya existe.

## 8. Lo que deja la tarea

1. **C6 hizo exactamente lo que un criterio pre-registrado tiene que hacer:** frenó un
   cambio que pasaba seis criterios con margen y un walk-forward unánime. Sin C6, la lectura
   habría sido *"el walk-forward eligió, 5/5, con +4.12 pp OOS y mejor drawdown"* — y se
   habría cableado apagar el stop desde un backtest sobre 127 sobrevivientes.
2. **Extender la rejilla más allá del borde cambió el objeto de la pregunta.** Con la
   rejilla de la 26b el resultado habría sido "aflojá a 3.0". Un máximo en el borde es una
   dirección, no un óptimo — y verificarlo costó dos brazos más.
3. **La lección de método (la segunda de esta serie sobre el mismo tema):** el sanity que
   falló no era del eje sino del **instrumento**, y falló por un umbral que yo especifiqué
   mal conflacionando dos denominadores. La 26b avisó *"congelar los brazos no exime de
   auditar el instrumento"*; ahora se agrega que **auditar el instrumento tampoco exime de
   verificar que la métrica del sanity mida lo que la frase dice que mide**.
4. **El costo de oportunidad del slot volvió a aparecer donde la skill avisó:** 3.141
   bloqueos movieron 3 trades de exposición y 70% de composición.

## 9. Reproducir

```bat
python scripts/run_stop_loosen_t34.py                       :: veredicto (10 slots)
python scripts/run_stop_loosen_t34.py --max-positions 5     :: sensibilidad (C8a)
python scripts/run_stop_loosen_t34.py --no-walk-forward     :: rejilla sola, SIN veredicto
```

Suite Windows con el enabler adentro: **1676 passed, 3 skipped**.
