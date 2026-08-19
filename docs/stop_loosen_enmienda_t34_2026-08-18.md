# ENMIENDA al pre-registro de la Tarea 34 (STOP-LOOSEN) — el sanity §7.5 estaba mal especificado

**Fecha:** 2026-08-18 · **Estado:** enmienda **declarada antes del veredicto**, sobre el
pre-registro congelado `docs/stop_loosen_prereg_t34_2026-08-18.md` (commit `1e73b2b`).

**Qué pasó:** la primera corrida **falló el sanity §7.5** y, por la regla congelada
(*"si falla alguno, la corrida es INVÁLIDA y no hay veredicto"*), **queda invalidada**. No
se re-especifica nada para salvarla: se corrige la especificación, se declara acá, y se
vuelve a correr. Es el mismo procedimiento que la T26 aplicó cuando su oráculo estaba mal
construido.

---

## 1. Qué decía el sanity y qué medía en realidad

**§7.5 congelado:** *"la fracción de candidatos elegibles bloqueada por Gate 5 en el
BASELINE cae en **[15%, 45%]** (la sonda sin modelar midió 28,2%). 0% o ~100% significa
enabler mal cableado, no hallazgo."*

**Medido en la corrida: 2,44%.** El sanity falla.

**Pero el enabler no está roto** — el umbral estaba mal puesto, y estaba mal puesto porque
el pre-registro **conflacionó dos cantidades distintas**:

| | qué mide | medido |
|---|---|--:|
| **Sonda pre-freeze (§3)** | de los trades que el harness **efectivamente toma sin gates**, qué fracción habría bloqueado el engine | **28,21%** |
| **Runner (§7.5)** | de los **candidatos elegibles** en el path **ya gateado**, qué fracción bloquea Gate 5 | **2,44%** |

No son la misma pregunta y no tienen por qué dar parecido. Dos razones, las dos
verificadas:

1. **El denominador del runner es enorme y casi todo es ruido.** `n_offered` = 143.096;
   descontando las que caen por ticker ya abierto quedan **128.486 "elegibles"**, pero de
   ésas sólo **2.815** llegan a tomar un slot. Medir bloqueos contra los elegibles es
   medirlos contra una fila de candidatos que en su enorme mayoría nunca iba a entrar.
2. **El gate es auto-extintivo por realimentación.** Bloquear una re-entrada evita el ciclo
   que habría generado el próximo bloqueo. El path gateado tiene menos ciclos cerrados
   perdedores que el path sin gates, así que dispara menos que lo que la sonda contó sobre
   el path sin gates. La sonda midió un **contrafáctico sobre el path viejo**; el runner
   mide el **régimen estacionario del path nuevo**.

## 2. El número que sí muestra que el enabler muerde

| baseline `touch_2.0` | tomadas | ya abierto | Gate 5 bloqueó | Gate 5b bloqueó |
|---|--:|--:|--:|--:|
| gates **OFF** | 2818 | 14.500 | 0 | 0 |
| gates **ON** | **2815** | 14.610 | **3.141** | 0 |

Gate 5 bloquea **3.141** candidatos —**más que los 2.815 trades que la cartera termina
tomando**— y sin embargo `n_taken` baja apenas 3 (2818 → 2815). Eso **no** es que el gate
no muerda: es el **costo de oportunidad del slot** con ratio de selección ~55:1, la lección
que la T26 dejó escrita en la skill `backtest-replay-harness`. Un candidato bloqueado no
deja el slot vacío — se lo lleva el siguiente de la fila el mismo día. **El gate cambia la
composición de la cartera, no su exposición.**

Y la composición cambia lo suficiente como para mover el resultado: el CAGR del baseline
pasa de 4.41% (sin gates) a 2.01% (con gates), −2,39 pp.

## 3. La corrección (y por qué este umbral sí está bien puesto)

**§7.5 se reemplaza por dos checks**, los dos sobre cantidades que el runner mide
directamente y sin denominadores ambiguos:

1. **Cableado:** `n_gate5_blocked > 0` con `live_gates=True` **y** `== 0` con
   `live_gates=False`, en el BASELINE. Es la verificación literal de que el flag hace algo
   y de que apagarlo lo apaga del todo.
2. **La regla muerde:** ≥ **10%** de los trades difieren (par `ticker`+`entry_date`) entre
   el baseline con gates y sin gates.

El segundo check **no es nuevo ni fue calibrado para esta corrida**: es exactamente el
sanity §5.3 de la 26b (*"la regla muerde: ≥10% de los trades difieren"*), con el mismo
umbral de 10% y el mismo helper (`trade_overlap`). Se lo importa tal cual. Reusar un
umbral ya publicado, decidido para otra pregunta, es lo que evita que este parche sea un
umbral elegido para que pase.

**Lo que NO se toca:** ni un carácter de §4 (población y config), §5 (brazos), §6
(walk-forward) ni §8 (los ocho criterios). La enmienda es sobre el **sanity del
instrumento**, no sobre la regla de decisión ni sobre nada que pueda mover el veredicto.

## 4. Disclosure — qué había visto al escribir esta enmienda

Necesario para que se pueda juzgar si la enmienda es honesta o conveniente. Cuando la
escribí **ya había visto la corrida invalidada completa**, incluyendo:

- La rejilla `touch` con gates: −2.52 / −1.84 / **2.01** / 6.12 / 8.71 / 8.31 / **9.52**.
- Que **el máximo cae en `touch_off`**, o sea que **C6 (máximo interior) va a fallar** y el
  resultado va camino a NO-SHIP con la lectura *"el stop ATR no aporta"*, que el §8 manda
  a tarea propia.
- La rejilla `close` y la rejilla sin gates.
- Que los otros cinco sanity (contabilidad, oráculo vs azar en CAGR y en maxDD, brazo `off`
  sin disparos, monotonía de la tasa) **pasaron**.

**Por qué la enmienda no se beneficia de eso:** el sanity corregido no toca ningún
criterio, y su efecto es **habilitar la publicación de un NO-SHIP** que el umbral viejo
habría dejado sin veredicto. No abre la puerta a cablear nada: para shipear hay que pasar
los ocho criterios del §8, que siguen intactos, y C6 ya se ve que no pasa. Si la enmienda
sesga algo, sesga en contra de la conclusión cómoda, no a favor.

**Lo que igualmente hay que asumir:** la corrida vieja queda **descartada** y el veredicto
se dicta sobre la corrida **nueva**, con el sanity corregido y el walk-forward completo
(que la invalidada ni siquiera había corrido, porque se la lanzó con `--no-walk-forward`).

## 5. Consecuencia para el §3 del pre-registro

El **número del sexto desvío sigue siendo válido**, pero hay que leerlo con la etiqueta
correcta: **21,15%-36,36% es la fracción de los trades del harness sin gates que el engine
vivo habría bloqueado** — o sea *el tamaño del desvío*, que es para lo que se lo midió y
lo que justifica modelarlo. **No** es la tasa de bloqueo en régimen del path gateado
(2,44% de los elegibles). Las dos son ciertas; describen cosas distintas.

Corregido en `analysis/harness_config.REENTRY_GATES_COST_DESC` para que el banner no
prometa lo que no es.
