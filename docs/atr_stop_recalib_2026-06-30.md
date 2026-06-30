# Recalibración / continuidad de los stops ATR — backlog A1

_Fecha: 2026-06-30 · cuenta Sim Principal (id=1) · backup `finanzias_2026-06-29_09-57-54_daily.db`_

## Pregunta

¿Los stops ATR rinden con **fills honestos** (modelo gap/touch), y a qué múltiplo?
No asumir que solo falta subir el multiplicador: la primera pregunta es si los
stops, como están (`atr_stop_mult=2.0`), **agregan o destruyen valor** vs no
tenerlos.

## Baseline a batir (config viva confirmada 2026-06-25)

`atr_stops_enabled=true`, `atr_stop_mult=2.0`, `atr_tp_mult=4.0`,
`atr_period=14`, `atr_trail_enabled=true`.

## Kill-criteria (pre-registrado, ANTES de correr)

Se shipea la variante que mejore el **ΔP/L total ≥ +2 pts** (% sobre capital
inicial = $50.000) sobre el real, **sin** empeorar el max DD ajustado más de
**1.5×** el real. Si gana "sin stops", se apagan. Si ninguna pasa, se
documenta y los stops quedan como están.

## Contrafactual (decidido upfront — la skill exige dejarlo escrito)

Para cada ciclo que en la realidad salió por un exit ATR (`reason` empieza con
`atr_`), se re-simula bajo los parámetros ATR de la variante **desde el día del
exit real `D`**: si el nuevo stop/trail/tp dispara en `D` se sale en `D`, si no
la posición continúa hasta que dispare o se alcance el **cap de 20 días
hábiles** (vende al close). Los exits ATR usan el modelo de fill gap/touch
(`gates.model_exit_fill_price`); los exits por cap llenan al close.

- **Validez:** el contrafactual solo es honesto para variantes con stop **igual
  o más laxo** que el baseline (mult ≥ 2.0 o sin stops): con un stop más laxo,
  el disparo previo a `D` no cambia (a mult 2.0 no disparó antes de `D`, a mult
  mayor tampoco). Un stop **más estricto** (mult < 2.0) requeriría re-simular
  desde el entry y queda fuera de este harness.
- **Resto de los SELLs** (señal, trims) **no se tocan**: esta tarea aísla el
  efecto de los stops ATR.
- **DD ajustado:** equity real (snapshots) + MTM diario de mantener abierto el
  ciclo extendido (mismo método que el harness T6.1). Aproxima que el cash
  liberado por el exit real no se reinvirtió — acota el DD por arriba.

## Higiene de datos (decidido upfront)

Se **excluyen** ciclos con precio corrupto: fill que difiere del close del cache
en el día del exit por **> 50%** (split/precio basura de Yahoo no conciliado).
Se reportan aparte, no entran al P/L del veredicto.

- **KLAC (exit 2026-06-05)** ya identificado: ciclo entero en escala ~$1942–1987
  (BUY 1942.70 → SELL 1987.83) cuando el precio real de KLAC en junio 2026 era
  ~$190–210 (factor ~10×). Es un round-trip ejecutado con precio basura de
  Yahoo → se excluye de esta tarea y se levanta como bug de datos aparte.

## Variantes evaluadas

| variante      | parámetros                                  |
|---------------|---------------------------------------------|
| `baseline`    | mult 2.0 (sanity: ≈ real)                   |
| `no_stops`    | stops/trail/tp apagados → mantiene hasta cap |
| `mult_2.5`    | `atr_stop_mult=2.5`, resto igual            |
| `mult_3.0`    | `atr_stop_mult=3.0`, resto igual            |

- **(d) chequeo intradía:** NO evaluable con los datos disponibles — el cache es
  `1d`; yfinance intradía es acotado (~7d a 1m, ~730d a 1h) y requiere red
  (no determinista). Se documenta como no-evaluable en esta pasada.

## Resultados

`python scripts/run_atr_stop_recalib.py --db backups/finanzias_2026-06-29_09-57-54_daily.db`

7 exits ATR totales · **6 limpios, 1 excluido** (KLAC, fill/close−1 = +930%) ·
cap 20d · capital $50.000 · DD real 7.40%.

| variante      | mod | ΔP/L $   | ΔP/L pts | DD sim | ratio | PASS | sensib (sin el ciclo de ±mayor aporte) |
|---------------|-----|----------|----------|--------|-------|------|----------------------------------------|
| `baseline_2.0`| 6   | +57.55   | +0.12    | 7.42%  | 1.00  | —    | sin MO: +0.47 pts                       |
| `no_stops`    | 6   | +2688.93 | **+5.38**| 10.28% | 1.39  | ✅   | **sin LRCX: +1.99 pts** (cae bajo el umbral) |
| `mult_2.5`    | 6   | −628.55  | −1.26    | 8.56%  | 1.16  | —    | sin MO: −0.72 pts                       |
| `mult_3.0`    | 6   | +2228.75 | **+4.46**| 9.55%  | 1.29  | ✅   | **sin LRCX: +1.07 pts** (cae bajo el umbral) |

Desglose por ciclo de `no_stops` (mantener hasta cap vs salir por ATR):

| ciclo | exit real | mantener 20d | ΔP/L $ |
|-------|-----------|--------------|--------|
| WMT  2026-05-21 | 121.93 | 117.18 (siguió cayendo) | −318 |
| MO   2026-05-29 | 70.77  | 73.79 | +372 |
| **LRCX 2026-06-05** | 313.98 | **379.09 (+21%)** | **+1693** |
| MO   2026-06-16 | 69.56  | 73.79 | +474 |
| KO   2026-06-16 | 80.24  | 82.63 | +516 |
| TJX  2026-06-25 | 156.24 | 155.43 | −48 |

- **`baseline_2.0` (sanity):** re-disparar a mult 2.0 reproduce el real (ΔP/L
  ≈ 0, DD ratio 1.00) → el motor `replay_atr_recalib` está bien calibrado.

## Hallazgos

1. **El veredicto cuelga de un solo ciclo.** `no_stops` y `mult_3.0` superan el
   umbral numérico (+5.38 / +4.46 pts), pero **LRCX aporta el 63%** del efecto
   de `no_stops`. Sacando LRCX (leave-one-out) ambas caen **por debajo de +2.0
   pts** (+1.99 / +1.07). No hay robustez: 1 de 6 ciclos decide.
2. **Régimen de muestra benigno.** El período abr–jun 2026 fue de rebote (mismo
   sesgo que los SELLs de señal: mediana fwd5 +3.92%); MO/KO/LRCX rebotaron.
   En este régimen *cualquier* stop parece malo porque todo revierte. Los stops
   existen para el drawdown sostenido que esta muestra **no contiene**
   (watchlist 52/52 vivos → survivorship). Aun así, apagar stops sube el DD
   ajustado (1.39× / 1.29×) incluso acá; en un bear real el DD sería peor y la
   restricción de 1.5× no lo captura con n=6.
3. **El único ciclo donde el stop salvó (WMT, siguió cayendo −3.9%) es
   minoría** en esta muestra — exactamente porque la muestra no tiene caídas
   sostenidas. No es evidencia de que los stops no sirvan; es evidencia de que
   no se los puede evaluar honestamente sin un período de stress.
4. **El fill de un stop "honesto" es el close del scan, no el touch intradía.**
   En WMT el modelo gap/touch (`model_exit_fill_price`) dio 124.41 (≈ nivel)
   mientras el real ejecutó a 121.93 (close EOD, ~2% abajo). El stop es un
   *market-on-next-scan* a precio EOD: el modelo de fill intradía es **optimista
   para los stops**. Sub-orden, no cambia el veredicto (la variante `no_stops`
   sale por cap = close, comparable al real), pero confirma que la frecuencia de
   scan —no el slippage— es la raíz del gap (ver tarea "subir frecuencia de scan").

## Veredicto: **NO-SHIP** — los stops quedan en mult 2.0

Aunque `no_stops` y `mult_3.0` pasan el kill-criteria *numérico*, el resultado
**no es robusto**: depende enteramente de LRCX (leave-one-out lo tumba bajo el
umbral) sobre una muestra de **n=6** en un **régimen de rebote sin drawdown**.
Apagar o aflojar un guardrail de riesgo con esa evidencia sería justo la feature
especulativa que las reglas del proyecto prohíben (CLAUDE.md #2/#3: kill-criteria
con poder, display antes que sizing). Se mantiene `atr_stop_mult=2.0` /
`atr_trail_enabled=true`.

**Re-evaluar cuando:** (a) haya ≥1 período con drawdown real en la historia de
la cuenta, y/o (b) n de exits ATR ≥ ~20. El harness (`scripts/run_atr_stop_recalib.py`)
queda listo para re-correr. La variante intradía (d) requiere datos 1m/1h
(red, acotados) y se evalúa junto con "subir frecuencia de scan".

**Hallazgo derivado (bug separado):** KLAC ejecutó un round-trip entero con
precio de Yahoo ~10× corrupto (BUY $1942 / SELL $1987 cuando KLAC valía ~$200).
Distorsiona notional/sizing del portfolio real. Se levanta como tarea de
robustez de datos en el backlog (no es parte de esta tarea de stops).
