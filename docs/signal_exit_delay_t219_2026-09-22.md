# Tarea 219 — Demorar la salida por señal (Gate 2b) · **NO-SHIP** · 2026-09-22

Pre-registro: `docs/signal_exit_delay_prereg_t219_2026-09-22.md` (congelado antes del
código de brazos, con una enmienda declarada antes de leer ningún Δ).
Runner: `scripts/run_signal_exit_delay_t219.py`.

> **Veredicto: NINGÚN BRAZO PASA.** El efecto es **real, grande y monótono** en la muestra
> completa —hasta +5,94 pp de CAGR— pero se compra con **tiempo de tenencia**, **sube el
> drawdown** en los dos brazos que más ganan, y **se da vuelta en las ventanas de stress**.
> Es la misma forma que mató a `C_A4` en la tarea 7, replicada sobre otra perilla, otra
> población y con 3× más brazos.

---

## 0. La corrida es válida — y el sanity que lo dice cazó un bug mío primero

| sanity | resultado |
|---|---|
| **el baseline reproduce el número PUBLICADO de la T170** | CAGR **8,78% vs 8,78%** (+0,00pp) · Sharpe **0,55 vs 0,55** · tomados **2531 vs 2531** (+0,0%) → **OK** |
| oráculo − azar igualado en tasa | **+24,30 pp** de CAGR (hace falta ≥ 2,0) → **OK** |
| contabilidad de cartera | **OK** |
| monotonía esperada (sanity blando) | **sí**: +0,00 → +3,43 → +5,21 → +5,94 → +8,19 |

**El primer intento de esta corrida fue INVÁLIDO y el sanity de reproducción no existía
todavía.** Puse `stop_mult=0.0` creyendo que era *«stop apagado»* — el centinela es
`NO_STOP = 1e9`, y `0.0` pone el stop **en el precio de entrada**, así que dispara ante
cualquier baja. Salió así:

| | primer intento (inválido) | corrida válida |
|---|---:|---:|
| trades tomados | **8.838** | 2.531 |
| tenencia media | **1,6 d** | 7,9 d |
| CAGR del baseline | **−17,89%** | +8,78% |
| Sharpe del baseline | **−1,76** | +0,55 |

**Y lo peligroso no es que saliera mal: es que salía *decidible*.** Los Δ entre brazos
seguían pareciendo razonables, la curva seguía siendo monótona y los sanity de oráculo y
contabilidad **pasaban**. El veredicto habría salido sin que nada lo marcara. Lo cazó
comparar el baseline contra un número **ya publicado** — la T170 corrió el mismo brazo
(`soff_t2.0`) sobre la misma población y su fila dice 8,78% / 0,55 / 2531.

Por eso la referencia quedó **cableada como sanity duro y con los números clavados del
doc**: una referencia derivada de esta misma corrida habría sido **ciega al defecto**,
porque afectaba a los siete brazos por igual. Es el defecto que las tareas 101 y 110
dejaron documentado, y acá se habría repetido.

---

## 1. Población y config

126 tickers (`data/harness_universe_live_acct2.txt`, huella `06ab64fc6448` **verificada**,
no impresa), **141.417** entradas `analyze BUY` PIT, 10y, 10 slots, `equal_weight`, hard
stop **OFF**, trailing 2,0 ATR, TP 4,0 ATR, fill honesto (T33). Artefactos 8 sesiones
atrasados, declarado en la enmienda 1 del pre-registro.

---

## 2. Los brazos

| brazo | CAGR | Sharpe | maxDD | tenencia | % salidas por señal | tomados |
|---|--:|--:|--:|--:|--:|--:|
| `age3` **(vivo)** | **8,78%** | **0,55** | **28,4%** | **7,9 d** | 76% | 2531 |
| `age5` | 12,21% | 0,71 | 28,1% | 9,3 d | 71% | 2193 |
| `age10` | 13,99% | 0,75 | 34,4% | 13,0 d | 57% | 1613 |
| `age20` | 14,72% | 0,77 | 33,8% | 17,8 d | 35% | 1205 |
| `C_A4_repl` *(referencia, no desafiante)* | 16,97% | 0,86 | 31,9% | 40,4 d | 0% | 546 |
| `ORACULO_SALIDA` *(sanity)* | 35,18% | 1,62 | 32,1% | 13,4 d | 54% | 1573 |
| `AZAR_MISMA_TASA` *(sanity)* | 10,87% | 0,64 | 28,7% | 9,0 d | 71% | 2264 |

**La curva dosis-respuesta de la T7 se replica limpia:** cuanto menos se le obedece a la
señal, mejor rinde la cartera — monótonamente, y hasta el extremo de no obedecerle nunca.

---

## 3. El veredicto, brazo por brazo

| brazo | ΔSharpe | ΔCAGR | ΔmaxDD | tenencia | magnitud | maxDD | stress | **PASA** |
|---|--:|--:|--:|--:|:-:|:-:|:-:|:-:|
| `age5` | +0,160 | **+3,43pp** | −0,27pp | +1,4 d | OK | OK | **NO** | **no** |
| `age10` | +0,203 | **+5,21pp** | **+6,05pp** | +5,1 d | OK | **no** | **NO** | **no** |
| `age20` | +0,223 | **+5,94pp** | **+5,45pp** | +9,8 d | OK | **no** | **NO** | **no** |

### El criterio que los mata es el heredado de la T7

Δ medio por trade dentro de cada ventana de stress:

| brazo | 2018-Q4 | bear-2022 | covid-2020 |
|---|--:|--:|--:|
| `age5` | −0,149 (n=57) | **−0,429** (n=224) | −0,008 (n=43) |
| `age10` | +0,833 (n=41) | **−0,944** (n=154) | **−1,254** (n=32) |
| `age20` | −0,800 (n=29) | +0,693 (n=113) | **−3,473** (n=21) |

**Los tres se dan vuelta en al menos una ventana**, y `age5` es negativo en las **tres**.
La T7 midió −0,231 en bear-2022 para `C_A4` y eso bastó para rechazarlo; acá el mismo eje,
movido por otra perilla, da **−0,429 / −0,944 / +0,693**. No es un caso límite.

**Y para `age10` y `age20` hay un segundo motivo independiente:** el maxDD **sube** 6,05 y
5,45 pp. Eso no estaba en el veredicto de la T7 —allá el DD ratio de `C_A4` era 1,12— y
acá es un rechazo por sí solo.

---

## 4. Lo que el resultado SÍ deja, y vale más que el veredicto

### 4.1 El 61% del beneficio aparente es «salir menos», no «salir mejor»

`AZAR_MISMA_TASA` difiere la **misma cantidad** de salidas que el oráculo, elegidas al
azar, y rinde **10,87%** contra 8,78% del baseline: **+2,09 pp sin elegir nada**. Contra el
+3,43 pp de `age5`, eso es el **61%** del efecto.

O sea que la mayor parte de lo que se gana demorando la señal **no viene de que la señal
esté mal cronometrada** — viene de operar menos. Es la medida más directa que hay de
cuánto vale el *timing* de la señal: poco.

### 4.2 Y el 39% que queda sí es calidad, porque el oráculo lo ve

El oráculo llega a **35,18%** (+26,40 pp sobre el vivo) eligiendo **cuáles** salidas
suprimir. Así que **hay** información explotable en distinguir una salida por señal buena
de una mala — mucha. Lo que no hay es una regla implementable que la capture: la edad
mínima es demasiado gruesa, y la T9 ya mostró con n=26.988 que el score tampoco ordena.

### 4.3 La tenencia explica el veredicto, como en la T7

`age10` retiene **13,0 días** — exactamente los 13,0 de `C_A4` en la T7. Compró el mismo
costo de ocupación de slot que hundió a aquel brazo, y por eso su Δ tampoco sobrevive.
`age5`, que sólo suma 1,4 días, es el único que no empeora el drawdown — y es el que sale
negativo en las tres ventanas de stress.

**No hay punto intermedio:** demorar poco no alcanza para mejorar el riesgo, y demorar lo
suficiente para mover el retorno compra la ocupación que lo anula. Ésa es la respuesta a la
pregunta del pre-registro, y es negativa.

---

## 5. Qué se cablea

**Nada.** `paper_signal_sell_min_age_bdays` queda en **3**. Tampoco se toca
`sell_fraction` (tiene veredicto en la T7), ni las barreras ATR (la T170 dijo NO MOVER), ni
el escalado por régimen (T20, cableado), ni `bypass_score`.

**El resultado negativo cierra el último eje sin medir de la familia de salidas.** Con esto
la familia queda completa: T7 (fracción vendida), T26/26b/34/37/47/167 (stops), T23 (TP),
T170 (política de salida, re-decidida), T51 (time stop) y ésta (edad mínima). **Ninguna
movió el retorno de forma que sobreviva a las ventanas de stress.**

---

## 6. Caveats, los del pre-registro

- **Los dividendos los cobra el harness y no el motor vivo** (desvío `dividendos`, 2,54%/año
  medido en la tarea 220). Es común a los brazos y se cancela en el Δ **salvo por el tiempo
  en mercado** — y acá los brazos **cambian** el tiempo en mercado (7,9 → 40,4 días). Así
  que una parte del Δ crudo de los brazos que retienen más es dividendo, no alpha. **No
  cambia el veredicto** —los tres ya fallan por stress y por maxDD— pero sí significa que
  los +3,43/+5,21/+5,94 pp están **sobrestimados** como medida de habilidad.
- No se modelan: blackout de earnings, gates de re-entrada, cap por ADV, overlay de
  volatilidad, screen de universo E1b. Los cinco los emite `deviations_keyed()` y salieron
  en el banner de la corrida.
- Los artefactos estaban **8 sesiones atrasados** (enmienda 1). La ventana es de 10 años, y
  las 8 ruedas que faltan son las **más recientes**: este veredicto vale para la década
  medida, no para el mercado de esta semana.
