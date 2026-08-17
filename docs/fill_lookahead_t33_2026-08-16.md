# El fill de las barreras decididas al close era look-ahead — Tarea 33 (FILL-LOOKAHEAD)

_2026-08-16 · lo destapó la 26b (`docs/stop_price_t26b_2026-08-16.md` §2) · gate técnico ·
sin red, sin tocar `finanzias.db`_

---

## VEREDICTO: el default se invirtió, el quinto desvío queda declarado, y de los cuatro veredictos re-leídos **ninguno cambia de signo — pero dos de sus hallazgos sí**.

La 26b mostró que `replay_cycle` decidía la barrera contra el **close** y la llenaba **en el nivel**:
como al disparar vale `low ≤ close ≤ nivel`, el fill legacy devolvía siempre un precio mejor que el
close y tocado *antes* de que existiera la información que decidió. Esta tarea (a) lo declara, (b)
invierte el default a la variante honesta y (c) re-lee los cuatro veredictos que quedaban.

**Lo que importa del re-read:** T7, T23, T13 y T21 **siguen todos en NO-SHIP** — ningún cambio de
política se estaba perdiendo por el defecto. Pero el subsidio del look-ahead vale **~4–5 pp de CAGR
de cartera** en todos ellos, y en dos casos lo que se movió fue el *hallazgo*, no el veredicto:

| tarea | veredicto legacy | veredicto honesto | qué se movió |
|---|---|---|---|
| **T7** (scale-out) | NO-SHIP | **NO-SHIP** | la dosis-respuesta encoge 40% pero conserva el signo |
| **T23** (TP-cal) | NO-SHIP (sólo por PBO) | **NO-SHIP** | **el signo del ΔCAGR se da vuelta**: +1.25 → −1.50 pp |
| **T13** (ENT1) | NO-SHIP ×2 | **NO-SHIP ×2** | el anti-selector se **refuerza**; "sin población" intacto |
| **T21** (ranking) | NO-SHIP | **NO-SHIP** | nada: baja la escala, se conservan las seis afirmaciones |
| **R2 / T20** (fuera del enunciado) | NO-SHIP / **SHIP y activo** | igual | nada — ver §7, se re-corrieron por prudencia |

---

## 1. Qué se shipeó

**(a) El quinto desvío, declarado en `harness_config.deviations()`** — y **corregido el cuarto**, que
decía *"el fill sí está modelado; la decisión no"*. Esa frase era **falsa en modo `close`** y es la que
mantuvo el defecto invisible durante cinco harness: el fill no estaba modelado, estaba mal. Hay un test
de regresión (`test_the_false_fill_claim_never_comes_back`) que falla si alguien la reintroduce.

El desvío nuevo es **condicional al brazo**, porque el defecto también lo era:

| `eval_mode` | `fill_mode` | qué declara el banner |
|---|---|---|
| `close` | `resting` (legacy) | **LOOK-AHEAD ACTIVO**, con el número que vale (+5.01 pp al múltiplo vivo) |
| `close` | `decision` (default nuevo) | desvío **conservador**: el harness llena al close, el engine con orden en reposo |
| `touch` | cualquiera | nada — los dos fill coinciden entre sí **y con el engine** |

El banner además imprime siempre una línea nueva, `Regla de salida simulada: barrera decidida al … ·
fill …`, aunque no haya desvíos: las dos mitades de la regla de salida son justamente lo que la serie
T7→T26 arrastró sin nombrar, y la segunda mitad ni siquiera aparecía en el banner de la T32.

**(b) El default de `fill_mode` pasó de `"resting"` a `"decision"`** en `replay_cycle` y en
`simulate_portfolio`. Ese es el punto de la tarea: el defecto no era que existiera el modo legacy, era
que **fuera el default**, así que cualquier harness nuevo escrito en modo `close` —el default de
`eval_mode`— nacía con look-ahead. Hay un test que lee la firma de las dos funciones y falla si el
default vuelve atrás.

**(c) `--fill-mode` en los once runners** que corren sobre `replay_cycle` (los 9 de cartera de la T27 +
T7 + 26b), todos con default honesto y `--fill-mode resting` disponible para reproducir el veredicto
publicado. Test de regresión parametrizado sobre la lista. `precompute_oracle_returns`
(`analysis/risk_sizing.py`) también lo toma: con el legacy, el oráculo de T10/T11b/T12 rankeaba por un
retorno que **ningún brazo podía cobrar**.

---

## 2. Por qué el default honesto **sigue** siendo un desvío, y por qué el sesgo va para los dos lados

El engine vivo decide contra el precio corriente intradía y llena con
`gates.model_exit_fill_price` (`engine.py:427`), o sea el modelo de **orden en reposo** en el nivel.
Eso es coherente *con su propia regla de decisión*: al decidir al toque, el precio que decide **es** el
nivel. Por eso bajo `eval_mode="touch"` los dos `fill_mode` del harness dan idéntico y coinciden con
producción.

Lo que no se puede tener es la orden en reposo **más** la confirmación al close: son reglas mutuamente
excluyentes. Con el fill honesto el harness queda del lado **conservador** (cobra el close, que en el
stop es peor que el nivel), y eso también se declara: el objetivo nunca fue que coincida, es que esté
escrito.

**La asimetría que hay que tener presente al leer cualquier resultado viejo:**

| barrera | al disparar vale | fill legacy vs close | el legacy… |
|---|---|---|---|
| stop / trailing (abajo) | `low ≤ close ≤ nivel` | nivel **≥** close | **regala** plata a cada disparo |
| take-profit (arriba) | `nivel ≤ close ≤ high` | nivel **≤** close | **cobra de menos** cada disparo |

O sea: en el stop el defecto **premiaba** a los brazos que disparan más (de ahí la falsa monotonía
"más ajustado gana" de la T26), y en el TP **castigaba** a los que disparan más — lo que infla
artificialmente el atractivo de **aflojar o apagar** el take-profit. Es exactamente el aviso del
enunciado de esta tarea, y el §4 muestra que la advertencia era correcta y el efecto grande.

---

## 3. T7 (scale-out + trailing) — el veredicto y la dosis-respuesta se sostienen, encogidos

41 tickers, 4028 entradas PIT, `cap_days=20`, capital ilimitado. El brazo primario y el mejor brazo
reproducen el veredicto publicado con `--fill-mode resting` (+0.07 y +0.52 contra +0.07 y +0.54 del
doc; la diferencia es que hoy hay 4028 entradas y en julio 4025).

| brazo | Δ pts legacy | Δ pts honesto |
|---|--:|--:|
| `A50_scaleout_50` (primario) | +0.07 | +0.04 |
| `A33_scaleout_33` | +0.09 | +0.05 |
| `A67_scaleout_67` | +0.04 | +0.02 |
| `B_trail_2.5` | +0.03 | +0.04 |
| `B_trail_3.0` | +0.01 | +0.05 |
| `C_A4_levels_rule` (mejor) | **+0.52** | **+0.31** |

Umbral pre-registrado: **+1.5 pts**. Ningún brazo se acerca en ninguna de las dos corridas ⇒
**NO-SHIP intacto**, y ni siquiera de cerca.

**El hallazgo de la T7 sobrevive con el signo pero pierde el 40% del tamaño.** La dosis-respuesta
("cuanto menos caso se le hace al SELL de señal, mejor") vive en `C_A4`, que es el brazo donde los
niveles mandan sobre la señal: pasa de +0.52 a +0.31 pts. Se entiende: `C_A4` es el brazo que **más**
sale por barrera ATR (1280 stops + 996 trails + 782 TP contra 503/360/330 del baseline), así que es el
que más subsidio cobraba. La conclusión que la T7 exportó a las tareas 9/21 —*el `SELL` de `analyze()`
es peor que dejar actuar a los niveles*— **se mantiene**, más chica.

**Y aparece un matiz que el legacy tapaba:** con el fill honesto `C_A4` pasa a perder en dos de los
cuatro regímenes (2018Q4 +0.07 → **−0.37**, bear-2022 −0.23 → **−0.54**), así que el criterio "el signo
no puede depender de un solo régimen" ahora lo falla de forma clara. El PBO del conjunto sube de 0.000
a 0.071 (sigue muy por debajo de 0.5).

---

## 4. T23 (TP-CAL) — el veredicto se sostiene y **el hallazgo se da vuelta**

Es el caso caro, y es el que el enunciado marcó: en el take-profit el defecto sesga **al revés**.

### 4.1 En la config publicada (5 slots, 41 tickers)

`--fill-mode resting` reproduce el veredicto **dígito por dígito** (ΔCAGR +1.25 pp, PBO 0.889,
DSR 0.997).

| brazo | legacy | honesto |
|---|--:|--:|
| `TP_4.0` (BASE, el vivo) | 18.60% | 14.95% |
| `TP_6.0` | 19.57% | 13.45% |
| `TP_off` | 19.85% | 13.23% |
| `TP_2.0` (sanity) | 7.03% | 10.34% |
| candidato (mejor Sharpe) | `TP_off` | `TP_6.0` |
| **ΔCAGR** | **+1.25 pp** | **−1.50 pp** |
| criterios fallados | sólo DSR/PBO (0.889) | ΔCAGR, Sharpe y régimen — **PBO pasa (0.460)** |

**Aflojar el TP dejó de ser gratis: ahora cuesta.** El veredicto publicado decía *"pasa 5 de 6 y muere
por PBO"*; con el fill honesto pasa lo contrario — el PBO deja de ser el problema y lo que falla es el
retorno. El NO-SHIP se sostiene, pero **la razón por la que la T23 murió era la equivocada**, y la
"idea derivada" que dejó (reabrir con block-bootstrap pareado porque el PBO era un estimador grueso)
**se queda sin objeto**: no hay edge que rescatar.

### 4.2 En la config viva (10 slots, 127 tickers) — la medición que había disparado la tarea 28

| brazo | legacy | honesto |
|---|--:|--:|
| `TP_4.0` (BASE) | 11.94% | **7.01%** |
| `TP_6.0` | 14.11% | 7.87% |
| `TP_off` | 15.00% | 8.19% |
| `TP_2.0` (sanity) | 7.08% | **9.15%** |
| ΔCAGR | +3.06 pp | +1.17 pp |
| PBO | **0.317** | **0.873** |
| sanity `TP_2.0 < TP_4.0` | OK | **FALLA** |

Acá el fill honesto **destruye la premisa de la tarea 28**. Esa tarea existía porque la T27 midió que
el `PBO 0.889` que mató a la T23 caía a **0.317** con la config viva, o sea que el criterio que la mató
pasaba con los slots correctos. Con el fill honesto el PBO vuelve a **0.873**: el estimador nunca dijo
que hubiera edge estable, y lo que lo había movido 57 puntos era el subsidio, no los slots.

**Y falla el sanity propio de la T23:** con el fill honesto `TP_2.0` (9.15%) **le gana** al baseline
`TP_4.0` (7.01%), cuando el sanity asumía que un TP más ajustado tiene que rendir claramente peor. La
curva queda en **U** —9.15 / 7.01 / 7.87 / 8.19 para 2.0 / 4.0 / 6.0 / off— con el múltiplo vivo en el
piso. Es el espejo exacto del §3 de la 26b (donde el stop vivo quedaba en el peor tramo), pero acá la
no-monotonía es tan fuerte que el resultado se lee como **path/ruido, no como dirección**: los dos
extremos ganan. Se reporta como descriptivo y **no se decide nada** con eso.

### 4.3 El cross-check que cierra la atribución

El baseline de esta corrida (`TP_4.0`, stop 2.0, 10 slots, 127 tickers) cae **−4.93 pp** al sacar el
look-ahead — y la 26b, con otro runner y otros brazos, había medido **+5.01 pp** para `close_2.0` en
esa misma config. Dos harness distintos miden el mismo subsidio. Además, las salidas **tomadas** son
idénticas entre los dos fills en todos los brazos (2638 / 2566 / 2543 / 3072): el fill no cambia
*cuándo* se sale, sólo *a qué precio* — igual que el control interno de la 26b.

---

## 5. T13 (ENT1) — veredicto intacto y el hallazgo **se refuerza**

5 slots, 41 tickers, 47.282 entradas, `cap_days=250`. `--fill-mode resting` reproduce el veredicto
publicado (BASE 18.73%, `A_pullback` 14.79%, población del time stop 0.5%).

| brazo | legacy | honesto |
|---|--:|--:|
| `BASE` | 18.73% | 14.72% |
| `A_pullback` (primario a) | 14.79% (−3.94 pp) | 10.40% (**−4.32 pp**) |
| `B_timestop` (primario b) | 18.51% (−0.22 pp) | 14.49% (−0.23 pp) |
| `A_negday` (exploratorio) | 17.26% | 14.17% |
| `B_N10` (exploratorio) | 19.18% | 15.17% |

**(a) El pullback sigue siendo un anti-selector, y peor.** El diagnóstico central de la T13 —las esperas
que **expiran** (el precio nunca retrocedió) rinden mucho más que las que **fillan**— se separa todavía
más con el fill honesto:

| | legacy | honesto |
|---|--:|--:|
| esperas que fillan (n=7588) | +0.26 pts · 43% ganadoras | **+0.07 pts · 41%** |
| esperas que expiran (n=3518) | +2.55 pts · 65% ganadoras | **+2.53 pts · 63%** |
| brecha | 2.29 pts | **2.46 pts** |

**(b) El "sin población" es exactamente el mismo** (0,5% contra el mínimo de 5%), y tenía que serlo: el
fill no cambia *cuándo* se sale, así que el perfil de tenencia es idéntico (p50 6 días, 3,8% de los
trades llegan a 20 ruedas). El NO-SHIP del brazo (b) por falta de población **no depende en nada** del
defecto.

---

## 6. T21 (ranking) — el re-read más limpio: **todo se mueve y nada cambia**

10 slots, 127 tickers, 143.096 entradas. `--fill-mode resting` reproduce el veredicto publicado
exacto (6.48% / 12.81% / mediana 9.71% [6.86, 13.15] / oráculo 475.58% / p=0.071).

| brazo | legacy | honesto |
|---|--:|--:|
| `B1_score` (**lo que corre hoy**) | 6.48% | **1.97%** |
| `B0_neutral` (alfabético, candidato) | 12.81% | 7.80% |
| `B2_no_volpen` (diagnóstico) | 8.09% | 3.54% |
| `B0r_random` ×10 — mediana [banda] | 9.71% [6.86, 13.15] | **4.96% [2.46, 8.55]** |
| `ORACULO` / `ANTI_ORACULO` (sanity) | 475.58% / −87.29% | 519.13% / −89.42% |
| ΔCAGR candidato vs base | +6.33 pp | +5.83 pp |
| C3 bootstrap IC95% | [−1.82, +13.56] p=0.071 → FALLA | [−2.71, +13.10] p=0.090 → **FALLA** |
| PBO (descriptivo) | 0.437 | 0.444 |

Toda la tabla baja ~4,5 pp y **ninguna afirmación de la T21 se mueve**:

- **El ranking vivo sigue por debajo de la banda ENTERA del azar:** 1.97% contra un mínimo de 2.46%
  entre las 10 semillas (antes: 6.48% contra 6.86%). El déficit contra la mediana pasa de −3.23 a
  **−2.99 pp/año** — la sexta medición convergente sigue en su lugar.
- **`B2` sigue recuperando exactamente la mitad del déficit** (53% con el fill honesto, 50% con el
  legacy) y sigue debajo del azar: sacar la `vol_penalty` no alcanza, igual que decía el veredicto.
- **El NO-SHIP sigue saliendo por el mismo criterio** (C3, el bootstrap pareado del alfabético) y con
  el mismo p-valor al filo.
- **El instrumento sigue validado**, y el oráculo incluso mejora (519% contra 475%) porque
  `precompute_realized` ahora puntúa con la misma mecánica de fill que los brazos que valida.

Es el caso que mejor muestra la forma general del defecto: **un subsidio de nivel, común a todos los
brazos**. Cuando los brazos disparan barreras a la misma tasa (acá cambian el *orden*, no la regla de
salida), el subsidio se cancela en la comparación y sólo mueve la escala. Cuando la cambian —el TP de
la T23— no se cancela y puede dar vuelta el signo.

---

## 7. Fuera del alcance del enunciado: **R2 y T10/T20 también se re-corrieron**

El enunciado pedía re-leer T7/T23/T13/T21. Se agregaron R2 y T10/T20 por dos razones concretas:

1. **Los brazos de R2 SÍ cambian la frecuencia de disparo.** Un hard gate en risk-off suprime entradas
   justo en las ventanas donde más dispara el stop, así que el subsidio **no** se cancela entre brazos
   — es el mismo mecanismo que dio vuelta a la T23, y el déficit publicado del gate (−6,3 pp de CAGR)
   es del mismo orden de magnitud que el subsidio.
2. **T20 (R2b) es la única decisión de esta serie que está cableada y ACTIVA en la cuenta viva.** Si su
   conclusión colgaba del defecto, eso no es un tema de backlog.

**Las dos conclusiones aguantan.** R2 en su config publicada (41 tickers, 4028 entradas, 5 slots):

| brazo | Δ P/L legacy | Δ P/L honesto | alivio DD stress |
|---|--:|--:|---|
| `R2a_hard_gate` | −150.84 pts | **−112.28 pts** | +28.1% → +24.4% |
| `R2b_half_size` (**el shipeado**) | +15.86 pts | **+15.04 pts** | +12.3% → +9.3% |
| `R2c_confirm_5d` | −163.53 pts | −124.67 pts | +13.0% → +11.4% |

El hallazgo de R2 —*apagar entradas destruye el compounding; escalarlas a medio tamaño lo mejora*—
queda igual, y el brazo shipeado es el que **menos** se mueve (−0.8 pts sobre +15.86), como
corresponde: no filtra entradas, así que dispara exactamente las mismas barreras que el baseline. El
propio runner lo verifica con su invariante (`exits: OK — 1274 posiciones compartidas, todas con
salida idéntica`). El hard gate, que sí cambia la tasa de disparo, es el que más se corrige — su
déficit encoge un 26% y **sigue siendo catastrófico**, que era el punto del veredicto.

T10/T20, también en su config publicada (5 slots): veredicto **SHIP** en las dos corridas, mismo brazo
seleccionado, y el factor 0.50 que Chapa eligió cablear sigue mejorando las tres métricas a la vez:

| | legacy | honesto |
|---|--:|--:|
| `B0_equal_weight` (base) | 17.39% · Sharpe 0.99 · DD 21.6% | 14.51% · 0.83 · 25.0% |
| `R2b_f050` (**lo cableado**) | 17.83% · **+0.09 Sh** · DD 19.1% | 15.03% · **+0.08 Sh** · DD 22.8% |
| `R2b_f025` (mejor brazo) | +0.17 Sh · +0.44 pp | +0.15 Sh · +0.73 pp |
| `S1_inverse_vol` / `S2_vol_target` | −3.28 / −4.06 pp, sin Sharpe | −3.41 / −4.03 pp, sin Sharpe |
| PBO / DSR | 0.218 / 0.999 | 0.127 / 0.995 |

**El escalado por régimen que está decidiendo en vivo no depende del defecto**, y el NO-SHIP del sizing
por volatilidad (T10) tampoco.

### Los que siguen sin re-correrse (T9, T11b, T12)

Tienen `--fill-mode` para reproducir su veredicto publicado, y la razón de no re-correrlos está escrita
para que no se lea como olvido:

- **Sus brazos no cambian la tasa de disparo de las barreras** (T9 y T11b rankean o filtran entradas;
  T12 cambia la **fuente** de los leads), así que el subsidio entra como nivel común — que es
  exactamente lo que la T21 midió acá de punta a punta, con el mismo tipo de brazos.
- **La T12 cuesta 10,76 h de corrida**, y su veredicto no se apoya en un ΔCAGR chico sino en que el
  brazo primario queda **debajo de la mediana del baseline aleatorio** —una comparación entre brazos
  con idéntica mecánica de salida— más el efecto de régimen.

**El criterio para el próximo que se reabra:** *"¿los brazos disparan barreras a tasas distintas?"*. Si
sí, hay que re-correrlo con el fill honesto antes de citarlo. Y si se reabre T10/T11b/T12, el brazo
**oráculo** se puntuaba con `precompute_oracle_returns`, que con el legacy rankeaba por un retorno que
ningún brazo podía cobrar; ya toma `fill_mode`, así que es correr, no programar.

---

## 8. Consecuencias

1. **La tarea 28 (re-abrir la T23 por sensibilidad de slots) se queda sin premisa** y se cierra como
   NO-VA: el `PBO 0.317` que la motivaba era subsidio, no config. Si alguien quiere volver al TP, el
   punto de partida honesto es la curva en U del §4.2 — que pide explicar por qué ganan **los dos**
   extremos antes de proponer un múltiplo.
2. **La idea derivada de la T23** (block-bootstrap pareado sobre Δ(retorno diario) para reemplazar al
   PBO) pierde su objeto en esa tarea: con el fill honesto el candidato no tiene edge que medir. La
   técnica sigue siendo la correcta para el eje "refinar un parámetro" (T26b la usó).
3. **La 34 (STOP-LOOSEN) queda desbloqueada:** su condicional era *"correrla con el fill legacy sería
   repetir el defecto que caducó la T26"*, y el default ya es el honesto. Su lead (`touch_3.0` 9.92%
   contra `touch_2.0` 4.41%) se midió en la 26b **ya con el fill honesto**, así que sigue en pie.
4. **Idea derivada nueva, del lado del engine (tarea 35 propuesta):** el engine vivo decide la salida
   con el precio del scan (`px ≤ nivel`) y **la contabiliza al nivel**, que es ≥ `px`. Bajo la lectura
   "hay una orden en reposo en el nivel" es el modelo realista que eligió T01 — pero el paper-trading
   **no coloca esa orden**: emite un SELL de mercado en el scan. O sea que la cuenta viva **también**
   se acredita un precio mejor que aquel con el que se enteró, acotado por la ventana de 15 min en vez
   de por un día entero. Es chico y es de **contabilidad**, no de decisión; queda como tarea propia,
   sin tocar nada acá.

---

## 9. Reproducir

```bat
:: la re-lectura (fill honesto, ya es el default)
python scripts/run_scaleout_replay_t7.py
python scripts/run_tp_cal_replay_t23.py --max-positions 5
python scripts/run_tp_cal_replay_t23.py --universe data/harness_universe_live_acct2.txt
python scripts/run_ent1_replay_t13.py --max-positions 5
python scripts/run_ranking_t21.py
python scripts/run_market_regime_r2.py --max-positions 5
python scripts/run_sizing_exposure_t10_t20.py --max-positions 5

:: el veredicto publicado de cada una (fill legacy = look-ahead)
python scripts/run_scaleout_replay_t7.py       --fill-mode resting
python scripts/run_tp_cal_replay_t23.py        --max-positions 5 --fill-mode resting
python scripts/run_ent1_replay_t13.py          --max-positions 5 --fill-mode resting
python scripts/run_ranking_t21.py              --fill-mode resting
python scripts/run_market_regime_r2.py         --max-positions 5 --fill-mode resting
python scripts/run_sizing_exposure_t10_t20.py  --max-positions 5 --fill-mode resting
```

Tiempos reales de esta corrida (Windows): T7 30 s · T23 9 s · T13 ~40 s · T21 174 s por fill.

Suite Windows con el cambio adentro: **1651 passed, 3 skipped** (16 tests nuevos: 5 sobre el desvío y
el banner + 11 de la regresión parametrizada sobre los runners).
