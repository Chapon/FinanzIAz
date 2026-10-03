# Entrada intradía vs close — tarea 293 — 2026-10-03

Origen: `docs/auditoria_tanda_2026-10-03.md` [C-2]. El harness decide y entra al **close** de la barra con señal BUY; el scan vivo corre **en sesión**, decide con la barra del día todavía abierta y llena al precio de ese momento. `deviations_keyed()` no lo declaraba y la magnitud nunca se había medido.

**Veredicto: el desvío existe y es chico. No se cumple ninguna de las dos condiciones del kill-criteria**, tampoco en el extremo del intervalo de confianza. Queda declarado como `entrada_intradia` y no abre la re-evaluación de veredictos.

## Kill-criteria (pre-registrado antes de medir)

Escrito en la tarea 293 y commiteado en `edb8c9a`, antes de que existiera el instrumento: si la fracción de BUY en sesión cuya señal **no** sobrevive al close supera el **10%**, o el |desvío medio de precio| supera el **0,5%**, entra una tarea de re-evaluar los veredictos vigentes que dependen de la entrada.

## Instrumento

`scripts/measure_entrada_intradia_t293.py`. Lee `finanzias.db` en sólo lectura y los frames `2y` del cache (el período que usa el motor; última barra 2026-10-02 en los 58 tickers), y pide a Yahoo los closes crudos.

- **Población:** los 86 BUY `analyze BUY` llenados por la cuenta 2 (2026-06-20 → 2026-10-02). *En sesión* es un día hábil con barra, entre 13:30 y 20:00 UTC; toda la muestra cae en horario de verano de EE.UU. y el script lo verifica.
- **Señal:** el mismo `analyze()` del motor, con `HARNESS_MODEL_TOGGLES`, sobre las últimas `LIVE_HISTORY_BARS` (504) barras hasta el **close del día** del fill.
- **Precio:** `fill sin slippage / close crudo − 1`. El fill sale de `fill_price − slippage_cost / fill_shares`; el close, de `auto_adjust=False`. Comparar un fill crudo contra el frame del cache, que está ajustado por dividendos, sesga el número: es el instrumento que el `verificador` refutó en [C-1] de la misma auditoría.
- **IC:** Wilson para las fracciones. Para la media del precio, bootstrap que remuestrea **días**, porque los BUY de un mismo scan no son independientes.

### Validación del instrumento, antes de creerle

Los BUY llenados **fuera** de sesión son el control: ahí el motor vio barras completas, así que el mismo `analyze()` sobre el mismo frame tiene que reproducir el BUY. **Lo reproduce en 22 de 22.** Con eso, lo que cambie en sesión se puede atribuir a la barra parcial y no al instrumento (ventana, frame ajustado, toggles).

## Resultado

| | n | no son BUY | IC95 |
|---|---|---|---|
| control, fuera de sesión | 22 | 0 (0,0%) | 0,0–14,9% |
| **en sesión, con la barra completa del día** | 64 | **1 (1,6%)** | **0,3–8,3%** |
| en sesión, sólo hasta la barra del día anterior | 64 | 9 (14,1%) | 7,6–24,6% |

**Precio, en sesión (n=64):** media **−0,002%**, IC95 por día **−0,26% a +0,32%**; mediana +0,017%; |desvío| medio 0,64%. Extremos: −3,21% (AMD, 2026-08-14) y **+7,79%** (HON, 2026-06-29).

### Cómo se lee

- **La señal sobrevive.** El único BUY que no sigue siendo BUY con la barra completa es PM, el 2026-09-11, y tampoco era BUY con la barra anterior. La tercera fila dice algo más: en 9 de 64 casos el BUY **lo creó** la barra parcial del día, y en 8 de esos 9 la barra completa lo confirma. El harness ve esos BUY el mismo día, al close.
- **El precio es ruido simétrico.** El fill queda en promedio sobre el close y el IC no se acerca al 0,5%. El |desvío| medio de 0,64% es la dispersión de cada trade, no un sesgo de la cuenta: suma varianza al resultado del vivo respecto del harness, pero no lo corre hacia un lado.
- **El +7,79% de HON es real, no un artefacto.** Es el ex-date del spin-off de Honeywell. El fill (10:15 ET, 244,69 crudo) coincide con la barra horaria de las 9:30, y la acción cerró en 227,80. Al día siguiente la posición salió por `atr_stop`.

## Hallazgos de paso

- **JNJ se llenó el 2026-09-07 a las 14:05 UTC, que era Labor Day**, con el mercado cerrado. Es un caso de la **292** (`paper_enforce_market_hours=False`): un feriado, que el conteo por reloj de la auditoría no distingue. Se anota en la 292.
- **Yahoo publica el spin-off de HON como `Stock Splits = 0,9535`.** La 262 lo rechaza como split, y hace bien, porque no es una fracción simple. Pero nada más lo trata: una posición **mantenida** a través de un spin-off registraría la caída del ex-date como pérdida, sin acreditar las acciones de la escindida. **Hoy es latente:** es el único evento de ese tipo desde marzo en los 70 tickers que operaron las dos cuentas, ninguna lo tuvo en cartera ese día, y no está en la cartera real. → tarea **297**.

## Lo que NO se midió

- **La barra parcial exacta que vio el motor.** No hay registro de la barra intradía del momento del scan; se mide contra la barra completa del mismo día, que es lo que ve el harness. Por eso la pregunta es *«¿sobrevive al close?»* y no *«¿qué vio el motor?»*.
- **El efecto sobre el CAGR de un runner.** La señal sobrevive en 63 de 64 casos y el precio no tiene sesgo, así que no hay una diferencia sistemática que propagar. Correr un brazo de harness con la entrada intradía no se justifica con estos números.
