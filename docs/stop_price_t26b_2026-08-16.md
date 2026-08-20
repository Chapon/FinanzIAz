# Veredicto — Contra qué precio se decide la barrera (Tarea 26b, STOP-PRICE)

_2026-08-16 · pre-registro congelado `docs/stop_price_prereg_t26b_2026-08-14.md` (2026-08-14) ·
runner `scripts/run_stop_price_replay_t26b.py` · tests `tests/test_stop_price_replay_t26b.py`_

Universo `data/harness_universe_live_acct2.txt` (127 tickers), **143.096 entradas `analyze BUY`**
point-in-time, `portfolio_sim` con capital finito, 10 slots (config de la cuenta viva 2),
`cap_days=250`, costos completos. Sin red, sin tocar `finanzias.db`.

---

## VEREDICTO: NO-SHIP por **C5 (robustez de régimen)**. El engine sigue decidiendo las barreras contra el precio corriente intradía.

**La corrida es VÁLIDA** — los tres sanity del §5 pasaron, incluido el que invalidó la T26. O sea que
esta vez sí hay veredicto, y el veredicto es que **la confirmación al close no se cabla**.

**Pero lo que la corrida destapó vale mucho más que su propio veredicto:** el harness tenía un
**look-ahead** en el fill de las barreras decididas al close, y **el resultado central de la T26
—"cuanto más ajustado el stop, mejor", +10.58 pp— era ese look-ahead, no una propiedad del stop.**
Con el fill corregido la curva **se da vuelta**: aflojar rinde mejor que ajustar, en los dos modos.

| | con el fill legacy (lo que corrió la T26) | con el fill honesto (esta corrida) |
|---|--:|--:|
| `close_1.0` | **23.38%** | **2.41%** |
| `close_2.0` (candidato) | 12.81% | 7.80% |
| `close_3.0` | 9.11% | 8.92% |
| veredicto de los 6 criterios | **SHIP** (pasan los 6) | **NO-SHIP** (falla C5) |

La fila de la izquierda **reproduce la T26 dígito por dígito**. La decisión de shipear colgaba entera
del defecto.

---

## 1. La corrida que decide (10 slots, `fill_mode=decision`)

| brazo | CAGR | Sharpe | maxDD | %stop | %trail | %tp | tomadas |
|---|--:|--:|--:|--:|--:|--:|--:|
| `touch_1.0` | −0.49% | 0.06 | 36.9% | 49.6% | 22.9% | 5% | 4200 |
| `touch_1.5` | 0.76% | 0.13 | 36.8% | 33.6% | 19.4% | 8% | 3241 |
| **`touch_2.0` (BASELINE — la regla viva)** | **4.41%** | **0.33** | **44.4%** | 19.9% | 12.2% | 10% | 2818 |
| `touch_2.5` | 6.19% | 0.42 | 40.2% | 11.6% | 7.1% | 11% | 2620 |
| `touch_3.0` | 9.92% | 0.60 | 36.5% | 7.2% | 3.2% | 12% | 2541 |
| `close_1.0` | 2.41% | 0.22 | 37.5% | 36.7% | 22.4% | 6% | 3410 |
| `close_1.5` | 5.15% | 0.36 | 41.5% | 22.6% | 16.4% | 8% | 2819 |
| **`close_2.0` (candidato)** | **7.80%** | **0.49** | **39.5%** | 13.4% | 9.0% | 9% | 2596 |
| `close_2.5` | 7.42% | 0.47 | 36.7% | 8.1% | 4.2% | 9% | 2495 |
| `close_3.0` | 8.92% | 0.54 | 34.2% | 4.8% | 2.2% | 9% | 2448 |
| _ORACULO_STOP (sanity)_ | 7.55% | 0.49 | 29.5% | 10.0% | 12.8% | 10% | 2688 |
| _AZAR_MISMA_TASA (sanity)_ | 3.83% | 0.29 | 44.7% | 13.5% | 12.4% | 11% | 2734 |

Los seis criterios congelados del §6, sobre `close_2.0` vs `touch_2.0`:

| # | criterio | umbral | medido | |
|---|---|---|---|---|
| C1 | ΔCAGR | ≥ +0.50 pp | **+3.39 pp** (7.80% vs 4.41%) | PASA |
| C2 | maxDD | ≤ base + 2.00 pp | **−4.88 pp** (mejora) | PASA |
| C3 | bootstrap pareado, IC95% inferior | > 0 | **[+0.03, +6.30] pp**, p=0.024 | PASA (al filo) |
| C4 | Sharpe | ≥ base − 0.05 | **+0.164** | PASA |
| C5 | régimen (Δ ret/trade en los 4) | ≥ −0.05 pts | +0.15 / **−0.15** / +0.03 / **−0.08** | **FALLA** |
| C6 | consistencia del signo a través del múltiplo | ≥ 3/5 | **4/5** | PASA |

**C5 falla en dos de los cuatro regímenes** — `stress_2018q4` (−0.15 pts por trade) y
`stress_bear_2022` (−0.08 pts), las dos afuera de la tolerancia de −0.05. La regla congelada es un
**AND de los seis**, así que el resultado es NO-SHIP y **no se re-decide**.

> **NOTA DE CORRECCIÓN 2026-08-19 (Tarea 47, `docs/stop_price_redecide_t47_2026-08-19.md`).** Este
> rechazo **no se sostiene**, por dos motivos independientes. (1) **Potencia:** la tarea 46 midió que
> en esta población el efecto detectable al 80% es **±1.72 pts** en `2018Q4` y **±0.97** en
> `bear_2022`, así que −0.15 y −0.08 están **11 y 12 veces por debajo** de lo que la muestra resuelve,
> y la potencia para detectar la propia tolerancia de ±0.05 es **5,1%** — o sea α. (2) **Signo:** al
> modelar los gates de re-entrada del engine (T34), que acá **no** son un nivel común porque los dos
> brazos disparan stop a tasas muy distintas (19,9% vs 13,4%), el Δ por régimen **se da vuelta**:
> **+0.05** en `2018Q4` y **+0.12** en `bear_2022`. **El mecanismo que el párrafo de abajo propone
> —que confirmar al close se paga en los tramos malos— queda sin respaldo.** El veredicto NO-SHIP se
> mantiene, pero por **otros criterios**: con los gates puestos, C3 pasa de [+0.03, +6.30] a
> **[−0.23, +8.51]** y a 5 slots el efecto se da vuelta (**−0.50 pp**). Ver la tarea 47.

**Y el mecanismo de la falla es coherente con lo que la regla hace:** confirmar al close **retrasa**
la salida, y el precio de ese retraso se paga justo donde las barras malas encadenan — en los
regímenes de stress. En `bull_normal` (+0.15) el retraso se cobra, en 2018Q4 y 2022 se paga. Es
exactamente el caso partido que el pre-registro previó al declarar C2 y C5 al frente: comprar retorno
agregado con más riesgo en los tramos malos **no** es mejorar la regla.

**La regla muerde fuerte:** **50,1%** de los trades difieren entre `touch_2.0` y `close_2.0` (par
`ticker`+`entry_date`). No es una diferencia de matiz: es media cartera.

---

## 2. El defecto que la corrida destapó — el fill legacy es look-ahead

`replay_cycle` decidía la barrera contra el **close** y la **llenaba en el nivel**
(`_exit_fill_price`, el modelo de *orden en reposo* que espeja `gates.model_exit_fill_price`). Las dos
mitades son incompatibles:

- una orden en reposo en el nivel se habría ejecutado **intradía**, cuando el `low` lo tocó — eso es
  la regla `touch`, no la `close`;
- cuando dispara al close vale `low ≤ close ≤ nivel`, así que el fill legacy devuelve **siempre** el
  nivel: un precio **mejor que el close** y tocado **antes** de que existiera la información que tomó
  la decisión.

O sea: el brazo cobraba el precio de la regla benigna con la frecuencia de disparo de la regla
benigna. Es look-ahead, no una convención discutible. Está cubierto por
`test_el_fill_al_nivel_es_siempre_mejor_que_el_close_cuando_dispara_al_close`, que fija la **dirección**
del sesgo y no sólo su existencia.

**El fill honesto (`fill_mode="decision"`) llena al close**, que además es la convención que el harness
**ya usaba** para todas las otras salidas decididas al close: flip de señal, time stop y cap
(`scaleout_replay.py`, pasos 2, 2b y 3 — los tres venden a `close_i`). La barrera ATR era la única
incoherente.

**Cuánto valía, por múltiplo** (10 slots, brazos `close`; `resting` − `decision`):

| múltiplo | legacy | honesto | regalo del look-ahead |
|---|--:|--:|--:|
| 1.0 | 23.38% | 2.41% | **+20.97 pp** |
| 1.5 | 15.62% | 5.15% | **+10.47 pp** |
| 2.0 | 12.81% | 7.80% | **+5.01 pp** |
| 2.5 | 9.19% | 7.42% | +1.77 pp |
| 3.0 | 9.11% | 8.92% | +0.19 pp |

**El regalo es monótono decreciente en el múltiplo, y esa ES la curva de la T26.** Cuanto más ajustado
el stop, más veces dispara, y cada disparo cobraba de más. La "monotonía de punta a punta" que la T26
leyó como dosis-respuesta era la dosis-respuesta **del defecto**.

**Dos controles internos que cierran la atribución:**

1. Los cinco brazos `touch` dan **idénticos** en las dos corridas (−0.49 / 0.76 / 4.41 / 6.19 / 9.92)
   — como debe ser: bajo `touch` la orden en reposo sí es coherente y `decision` es un no-op
   (`test_al_toque_los_dos_fill_modes_coinciden`). Todo el efecto vive en el modo `close`.
2. Los brazos `close` conservan **el mismo conjunto de trades y la misma mezcla de salidas** entre las
   dos corridas (`%stop`, `%trail`, tomadas: 36.7/22.4/3410, 13.4/9.0/2596, …). El fill no cambia
   *cuándo* se sale sino *a qué precio* — lo único que se mueve es el precio de cada salida decidida
   al close. Los +5.01 pp son puro efecto de precio.

**A quién afecta:** a **los cinco harness de salida de la serie** (T7, T23, T13, T21, T26), porque todos
corren sobre `replay_cycle` en modo `close`. El default se dejó en `resting` a propósito para no mover
en silencio nada ya publicado — pero eso significa que **el próximo harness que se escriba lo hereda**.
Fijarlo (y re-leer los cuatro veredictos restantes con el fill honesto) es la **tarea 33**, abierta con
este cierre.

---

## 3. La segunda pregunta (§7): la monotonía de la T26 **no sobrevive — se invierte**

El pre-registro declaró las tres lecturas posibles antes de correr. Salió la segunda, y en su versión
fuerte:

| múltiplo | `touch` (regla viva) | `close` (fill honesto) |
|---|--:|--:|
| 1.0 | −0.49% | 2.41% |
| 1.5 | 0.76% | 5.15% |
| 2.0 | 4.41% | 7.80% |
| 2.5 | 6.19% | 7.42% |
| 3.0 | **9.92%** | **8.92%** |

En **las dos** reglas, aflojar el stop rinde mejor. Contra la T26 (`S_1.0` +10.58 pp sobre `S_2.0`),
acá `close_1.0` rinde **−5.39 pp** contra `close_2.0` — mismo modo de evaluación, signo dado vuelta.
A 5 slots pasa lo mismo (−4.27 pp donde la T26 medía +11.98 pp).

**Y esto corrige la atribución que el propio pre-registro había supuesto:** el confound principal **no
era** `close` vs `touch`, era el **fill**. Con el fill honesto, `close` le sigue ganando a `touch`
(+3.39 pp), o sea que el eje de la 26b existe y es real — pero la monotonía de la T26 se cae **dentro
del mismo modo `close`**, apenas se le saca el look-ahead. La tarea 26 queda **cerrada del todo**:
su hallazgo central era artefacto.

**Lo que queda picando (y NO se decide acá):** bajo la regla que el engine **realmente ejecuta**,
`touch_3.0` da 9.92% contra 4.41% de `touch_2.0` — el múltiplo vivo está en el peor tramo de la curva.
Es la **dirección opuesta** a la que la T26 quiso cablear. Pero a 5 slots la curva es ruidosa y no
monótona (3.45 / 0.48 / 3.04 / 7.10 / 6.11), así que esto es un **lead, no un resultado**: pide su
propio pre-registro (tarea 34). El pre-registro de la 26b es explícito: *"no se cabla ningún múltiplo
desde esta tarea"*.

---

## 4. Sensibilidad a 5 slots — el NO-SHIP se refuerza

| | 10 slots | 5 slots |
|---|--:|--:|
| ΔCAGR (`close_2.0` − `touch_2.0`) | +3.39 pp | +4.29 pp |
| ΔmaxDD | −4.88 pp | −4.41 pp |
| ΔSharpe | +0.164 | +0.200 |
| C3 bootstrap IC95% | [+0.03, +6.30] p=0.024 → PASA | **[−0.40, +8.88] p=0.037 → FALLA** |
| C5 régimen | **FALLA** (−0.15 / −0.08) | **FALLA más fuerte** (−0.66 / −0.24) |
| C6 consistencia | 4/5 | 3/5 (justo en el umbral) |

El efecto agregado es **más grande** a 5 slots y aun así **falla dos criterios** en vez de uno: el
punto estimado sube pero el intervalo cruza cero y el daño por régimen se triplica. Es la firma de un
efecto **ruidoso**, no robusto — y es la razón por la que C3 y C5 estaban congelados de antemano.

---

## 5. El sanity — esta vez el instrumento quedó validado

La corrección que la T26 pagó cara: el oráculo se compara contra el **control igualado en tasa**, no
contra el baseline.

| sanity | umbral | medido | |
|---|---|---|---|
| contabilidad (`equity_curve[-1]` vs `final_equity`) | ≤ 1e-6 | ok en los 12 brazos | OK |
| oráculo vs azar — ΔCAGR | ≥ +1.50 pp | **+3.72 pp** (7.55% vs 3.83%) | OK |
| oráculo vs azar — ΔmaxDD | ≤ −5.00 pp | **−15.19 pp** (29.5% vs 44.7%) | OK |
| la regla muerde (trades distintos) | ≥ 10% | **50,1%** | OK |
| dominancia de disparo (`close` ⇒ `touch`) | invariante | unit tests sobre ciclos sintéticos | OK |

**El harness ve calidad de salida**: elegir *cuáles* stops respetar vale +3.72 pp de CAGR y −15.19 pp
de maxDD contra suprimir la misma cantidad al azar. El defecto de la T26 estaba en el brazo (oráculo
de-sólo-supresión medido contra el baseline), no en el instrumento — y con el umbral puesto donde
corresponde, pasa con margen.

---

## 6. Qué NO se cabla y qué queda declarado

- **NO se cabla `paper_atr_confirm_at_close`.** El engine sigue evaluando las barreras contra el
  precio corriente intradía (`get_bulk_prices`, `engine.py:627`). Nada de la política de salida viva
  cambia con este cierre.
- **`atr_stop_mult` sigue en 2.0**, como declaró el §8 del pre-registro pase lo que pase.
- **El desvío #4 de la T32 queda cuantificado:** el harness en modo `close` mide **+3.39 pp de CAGR
  por encima** de la regla que el engine ejecuta, al múltiplo vivo y a 10 slots. Los cinco harness de
  la serie miden una regla **más benigna** que la de producción.
- **El bracket se respeta:** `touch` es la cota **superior** de frecuencia de disparo (ve el mínimo
  exacto) y `close` la **inferior**; el engine samplea c/15 min, así que está entre las dos y más
  cerca de `touch`. **Ningún brazo de acá ES producción** — la acotan. Nada en este veredicto afirma
  reproducir el engine.
- **Se abre la tarea 33 (FILL-LOOKAHEAD):** declarar el quinto desvío en `harness_config.deviations()`,
  decidir el flip del default de `fill_mode` y **re-leer los cuatro veredictos restantes** (T7, T23,
  T13, T21) con el fill honesto. Es un gate técnico, igual que la 32 — y ahora se sabe que puede dar
  vuelta un veredicto entero, así que la severidad es **ALTA**.
- **Se abre la tarea 34 (STOP-LOOSEN):** el lead del §3, con pre-registro propio.

---

## 7. Lo que deja la tarea

1. **La T26 queda cerrada del todo.** Su hallazgo central (+10.58 pp por ajustar el stop) era el
   look-ahead del fill. El sanity que la invalidó **la salvó**: si hubiera pasado, se habría cableado
   `atr_stop_mult=1.0` — el peor extremo de la curva real (2.41% contra 7.80% del valor vivo, en el
   mismo modo de evaluación). **La regla de "si falla un sanity no hay veredicto" evitó un cambio de
   política de salida que iba justo para el lado equivocado.**
2. **Ningún harness de salida de esta serie se puede leer sin corregir el fill**, y no sólo el precio
   de evaluación. Dos defectos distintos, los dos en la misma llamada, los dos invisibles porque
   `_exit_fill_price` "modelaba el fill" — el banner de la T32 lo decía con esas palabras y la frase
   era falsa en modo `close`.
3. **La lección de método**, para el próximo pre-registro: la 26b se congeló declarando **un** eje
   (`eval_mode`) y el defecto grande apareció en la **mecánica de al lado** (el fill), que el
   pre-registro daba por buena. Congelar los brazos no exime de auditar el instrumento: lo que salvó
   la corrida fue mirar de dónde salía el precio de cada salida **antes** de escribir el veredicto.
4. **El desvío del fill se declaró en el runner, no se tapó:** `--fill-mode resting` sigue disponible
   y reproduce la corrida invalidada, que es lo que permitió atribuir el efecto con evidencia en vez
   de con un argumento.

---

## 8. Reproducir

```bat
python scripts/run_stop_price_replay_t26b.py                      :: veredicto (10 slots)
python scripts/run_stop_price_replay_t26b.py --max-positions 5    :: sensibilidad
python scripts/run_stop_price_replay_t26b.py --fill-mode resting  :: la corrida con look-ahead
```

Suite Windows con el enabler adentro: **1635 passed, 3 skipped**.
