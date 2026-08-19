# Veredicto — RANK-NEUTRAL (Tarea 39) · **NO-SHIP · corrida VÁLIDA**

**Fecha:** 2026-08-19 · **Pre-registro congelado:** `docs/rank_neutral_prereg_t39_2026-08-19.md` (`a9e1dfd`)
**Runner:** `scripts/run_rank_neutral_t39.py` · **Enablers nuevos:** `analysis/rank_policy.py` (la
política como función pura), `walkforward_power.regime_window_returns` (retorno de cartera por
ventana de régimen), `--eval-mode`/`--live-gates` en `scripts/run_ranking_t21.py`.
**Comando:** `python scripts/run_rank_neutral_t39.py` (determinista; `--json` para la salida completa).

**No se toca `engine.py` ni `strategies.py`.** El ranking por `buy_score` queda como está.

Población: **127 tickers** de la watchlist viva, **143.096 eventos `analyze BUY`** PIT, **62,8
candidatos por día** para 10 slots, `portfolio_sim` con `cap_days=250`, 10 años.
Config honesta: **`eval_mode="touch"` + `fill_mode="decision"` + `live_gates=True`** — los tres que la
T21 no tenía.

| brazo | CAGR | Sharpe | maxDD | tomad. | qué es |
|---|--:|--:|--:|--:|---|
| `B1_score` | **3.23%** | 0.28 | 41.6% | 2509 | **lo que corre hoy** |
| **`N_rot` ×20** | mediana **5.03%** [0.47%, 8.16%] | — | med. 41.9% | — | **CANDIDATO — la política** |
| `P_fix` ×20 | mediana **3.82%** [0.64%, 8.27%] | — | — | — | nulo pareado en persistencia |
| `I_inverted` | 5.00% | 0.35 | 47.1% | 3063 | diagnóstico (no promovible) |
| `ORACULO` | 612.80% | 9.32 | 15.4% | 2071 | sanity |
| `ANTI_ORACULO` | −89.63% | −10.22 | 100.0% | 3522 | sanity |

## 1. La regla congelada (§6) y su resultado

| # | Criterio | Resultado |
|---|---|---|
| C1 | ΔCAGR mediana ≥ +0.50 pp | **PASA** — +1.80 pp |
| **C2** | **las 20 semillas le ganan al baseline** | **FALLA** — ganan **15/20** |
| C3 | maxDD mediana ≤ base + 3.00 pp | **PASA** — +0.29 pp |
| **C4** | bootstrap pareado, IC95% inferior > 0 | **FALLA** — [−3.88, +7.61] pp, p=0.282 |
| C5 | retorno de cartera por régimen ≥ −0.50 pp en los cuatro | **PASA** — mejora en los cuatro |
| **C6** | el signo de C1 y el resultado de C2 aguantan a 5 slots | **FALLA** — +0.10 pp y 11/20 |

**Tres de los seis fallan ⇒ NO-SHIP.** No es un fallo al filo: C2 falla por cinco semillas, C4 tiene un
intervalo que cruza cero con holgura y C6 se cae del todo.

**Sanity del instrumento (§5): los cinco OK ⇒ la corrida es VÁLIDA y el veredicto vale.**

- **Contabilidad** OK en los 44 brazos.
- **Reproducción exacta de la línea publicada:** el mismo runner, en la config del re-read de la T33
  (`close` + `decision` + sin gates), da **1.97%** — el dígito publicado. La población y la cañería son
  las mismas; lo que cambia de acá en más es sólo la regla que se modela.
- **El oráculo despega** a 612.80% (+609.57 pp) y **el anti-oráculo se hunde** a −89.63%: el harness
  detecta calidad de ranking con enorme sensibilidad, así que un resultado nulo acá es real.
- **El ranking muerde:** 98,4% de los trades difieren entre el baseline y la política.
- **Las semillas mueven:** 98,3% de trades distintos entre semillas (mediana de los 190 pares).

## 2. EL HALLAZGO: con la regla del engine y sus gates, el ranking vivo **entra en la banda del azar**

Esa es la afirmación que la tarea existía para poner a prueba, y **no sobrevive en su forma fuerte**:

| corrida | config | `B1_score` | banda del azar | ¿debajo de la banda entera? |
|---|---|--:|---|---|
| T21 (publicada) | `close`, fill legacy, sin gates | 6.48% | [6.86%, 13.15%] (10 semillas) | **sí** |
| T33 (re-read) | `close`, fill honesto, sin gates | 1.97% | [2.46%, 8.55%] (10 semillas) | **sí** |
| **T39 (ésta)** | **`touch`, fill honesto, con gates** | **3.23%** | **[0.47%, 8.16%] (20 semillas)** | **NO — queda adentro** |

El baseline pasa de estar **debajo del mínimo** de las semillas a estar **adentro de la banda**, con
15 de 20 semillas por encima y 5 por debajo. El déficit contra la mediana se achica de −3.23 pp (T21)
a **−1.80 pp**, y deja de clarear su propio intervalo.

**Qué cambió y qué no.** No cambió la población: el sanity de reproducción da el 1.97% publicado al
dígito. Lo que cambió es que se modelan **la regla que el engine ejecuta** (`touch`) y **sus gates de
re-entrada** (T34, que bloquean entre 21% y 36% de las entradas que el harness tomaría). Con los dos
puestos el baseline sube 1.26 pp y la banda se ensancha. **Mecanismo probable, no medido acá:** los
gates y el `touch` acortan y espacian los ciclos, y con eso le sacan a cualquier clave de orden parte
de su capacidad de concentrar el book — que es justamente el canal por el que la T9 explicaba el
costo. Queda como hipótesis; medirla es otra pregunta.

**Consecuencia documental:** la afirmación central de la T21 —*"el ranking vivo rinde por debajo de la
banda entera del azar"*— queda como **config-dependiente**. Es cierta en la config en que se midió (y
esta corrida la reproduce), y **no se sostiene** cuando se modela la regla viva con sus gates. Se
agrega nota de corrección en `docs/ranking_t21_2026-08-12.md`. Las otras cinco mediciones convergentes
(corr −0.0259, AUC 0.4980, top/bottom quintil, `val_acc` 0.5076, análisis profundo) **no dependen de
esta config** y siguen en pie: dicen que el score no tiene alpha, que es distinto de decir que tiene
alpha negativo.

## 3. El bracket de persistencia: qué explica y, sobre todo, qué **no** explica

Ésta era la pieza de método nueva del pre-registro (§4.2), y da dos números que no existían:

**(a) Persistir el orden cuesta 1.21 pp de CAGR por sí solo.** Las dos familias son igual de
ignorantes —ninguna mira nada— y difieren sólo en si el orden rota: mediana rotada **5.03%** contra
mediana fija **3.82%**. O sea que **parte de lo que se le cobra a cualquier ranking persistente es
estructural, no informativo**. Es la primera vez que se mide, y aplica a cualquier clave de orden
futura, incluida la integración de fuentes que deja pendiente la T38.

**(b) Pero el `buy_score` casi no es persistente a la escala que importa.** La autocorrelación de
rango del score entre los candidatos del día:

| lag (ruedas) | 1 | 2 | 5 | **8** | 20 | 60 | 250 |
|---|--:|--:|--:|--:|--:|--:|--:|
| ρ del score | 0.591 | 0.465 | 0.249 | **0.161** | 0.061 | 0.055 | 0.017 |

(las puntas del bracket, con el mismo estadístico: rotado **0.003**, fijo **1.000**. Calculado con
`rank_autocorr(clave, pool, lag=k)`, el mismo helper que el runner imprime; la corrida canónica
publicó los lags 1/5/20/60 y el juego completo se agregó después, sin tocar ningún brazo.)

La tenencia media del baseline es de **8,0 ruedas**, y ahí el score conserva **ρ = 0.16**: mucho más
cerca de la punta **rotada** que de la fija. El decaimiento es más lento que un AR(1) (0.591⁸ = 0.015
contra 0.161 medido), o sea que **hay** una componente lenta, pero es chica.

**(c) Contra cada nulo, cuántas semillas le ganan al score:**

| familia | mediana | banda | semillas que le ganan a `B1_score` |
|---|--:|---|---|
| `N_rot` (rotada) | 5.03% | [0.47%, 8.16%] | **15 / 20** |
| `P_fix` (fija) | 3.82% | [0.64%, 8.27%] | **12 / 20** |

Contra el nulo **pareado en persistencia** el score queda en **12/20** — o sea, prácticamente en el
medio de esa familia. Contra el nulo **rotado** queda 15/20: del lado malo, pero adentro.

**Las tres cosas juntas:** el bracket **no rescata** al score —no se le puede atribuir su déficit a la
persistencia, porque persiste poco a la escala de la tenencia— **y tampoco lo condena**, porque el
déficit que queda no clarea su intervalo. Y de paso cierra la pregunta de la T21 §2b desde el otro
lado: el alfabético ganó por suerte, y ahora se ve **la banda entera de su familia** —[0.64%, 8.27%],
7,6 pp de ancho—, así que cualquier orden fijo podía caer en cualquier lado.

## 4. El brazo invertido: **no hay señal inversa que explotar** (lectura pre-declarada)

`I_inverted` da **5.00%** y la mediana rotada da **5.03%**: son el mismo número.

El §4.3 del pre-registro declaró los dos desenlaces posibles **antes** de correr. Se cumplió el
primero: *"si `I_inverted` ≈ la mediana de `N_rot` ⇒ el score no tiene signo explotable: el déficit
viene de concentrar, no de una señal inversa"*. Si el score tuviera alpha negativo aprovechable,
invertirlo tendría que **superar** al azar; le empata exactamente.

**La opción (b) del backlog —invertir el score— queda cerrada por medición, no por opinión.** Lo que
mejora contra el baseline no es dar vuelta el signo: es **dejar de usar el score**, y eso lo hace igual
de bien cualquier orden que no lo use.

## 5. C6: el efecto **se encoge** a 5 slots, y eso contradice el mecanismo

El pre-registro §3 dejó escrita la dirección esperada, antes de ver nada: *"el ranking decide **más**
cuanto peor es el ratio de selección, así que a 5 slots el efecto debería **crecer**, no encogerse"*.

| | baseline | mediana rotada | Δ | semillas que ganan |
|---|--:|--:|--:|---|
| 10 slots | 3.23% | 5.03% | **+1.80 pp** | 15/20 |
| 5 slots | 4.52% | 4.62% | **+0.10 pp** | 11/20 |

**La predicción direccional pre-registrada falló.** Con la mitad de los slots el ratio de selección
empeora, el orden decide más, y sin embargo la ventaja de la política prácticamente desaparece y las
semillas se reparten casi 50/50. Eso es información sobre el mecanismo, no sobre la tarea: si el efecto
viniera de la concentración que describe la T9, tendría que **amplificarse**. Lo que se ve es
compatible con que el +1.80 pp de 10 slots sea ruido de una trayectoria — que es también lo que dicen
C4 (IC [−3.88, +7.61]) y el PBO descriptivo (0.937).

## 6. Qué significa para la cuenta viva

**El engine queda como está** y el `buy_score` sigue documentado como **no-validado para ranking**,
pero la afirmación se corrige a la baja y conviene que quede escrita con precisión:

> No es *"el ranking vivo tiene alpha negativo y cuesta plata"*. Es *"el ranking vivo no tiene alpha
> medible, y el déficit que la T21 le atribuyó no sobrevive a modelar la regla del engine con sus
> gates"*.

El costo de oportunidad de no tocar nada también baja. La T9 estimaba ~8 pp de CAGR; acá el punto
estimado de cambiar es **+1.80 pp** con IC95% **[−3.88, +7.61]** — un cambio de comportamiento vivo,
todos los días, sostenido por un intervalo que cruza cero.

## 7. Qué queda (cada uno con pre-registro propio)

1. **`vol_penalty` fuera de la selección** (idea derivada 2 de la T21, ~1.6 pp/año). Sigue abierta,
   **pero ese número hay que re-medirlo**: salió en la config de la T21, y esta corrida acaba de
   mostrar que esa config **exagera los efectos de ranking** (la banda entera se movió al modelar la
   regla viva). No es un lead muerto; es un lead con el número desactualizado.
2. **Rotar la clave en vez de reemplazarla.** Persistir cuesta 1.21 pp medidos, así que un desempate
   rotado *encima* del score sería un cambio mucho más chico que apagar el ranking. **Ojo con este
   lead:** el número se midió sobre claves **sin información** y el score persiste poco a la escala de
   la tenencia (§3b), así que la ganancia esperada es una fracción de esos 1.21 pp. Necesita su propio
   kill-criteria antes de que valga la pena.
3. **La banda del azar es enorme** — [0.47%, 8.16%] a 10 slots y [−3.45%, 12.52%] a 5. Cualquier tarea
   futura que compare órdenes de candidatos tiene que reportar **la banda entera de una familia de
   semillas**, nunca una realización. Es la lección que la T21 abrió con 10 semillas y ésta cierra con
   20 y **dos** familias.

## 8. Descriptivos (NO fueron gate)

**DSR 0.837 · PBO 0.937** (T=2283 obs). El pre-registro §6 los declaró descriptivos por adelantado y
la corrida muestra por qué: con 20 semillas de la **misma** política los brazos son intercambiables
por construcción, así que el PBO —que responde *"¿el mejor de muchos candidatos generaliza?"*— mide
otra cosa. Un PBO de 0.937 acá es consistente con todo lo demás (elegir entre estos brazos no
generaliza), no un criterio.

**Retorno de cartera por ventana de régimen (C5), en pp:**

| régimen | baseline | política | Δ |
|---|--:|--:|--:|
| `bull_normal` | +146.57% | +150.66% | +4.09 |
| `stress_2018q4` | −12.75% | −11.93% | +0.82 |
| `stress_covid_2020` | −29.66% | −24.27% | +5.39 |
| `stress_bear_2022` | −11.89% | −7.33% | +4.55 |

C5 pasa con la política mejor en los cuatro, pero **hay que leerlo con el ancho de la banda al lado**:
toda la comparación vive adentro del ruido que muestran C4 y C6.

## 9. Qué deja de enabler

- **`analysis/rank_policy.py`** — la política de orden como **función pura** de `(semilla, fecha,
  ticker)` (`blake2b`), que es el objeto que se cablearía en el engine, con golden value testeado para
  que no cambie en silencio. **Cierra la tarea 40**.
- **`walkforward_power.regime_window_returns`** — retorno de **cartera** por ventana de régimen con el
  cash contando 0. Es el helper que la **T38** necesita para su C2, escrito una sola vez.
- **`--eval-mode` / `--live-gates` en `scripts/run_ranking_t21.py`**, con defaults que preservan el
  veredicto publicado.
- **Tarea 41 (UNIV-BOM)**, encontrada y arreglada durante el smoke: un universo con BOM perdía el
  primer ticker en silencio.
