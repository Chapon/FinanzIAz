# Tarea 220 — Reconciliación cuenta viva ↔ harness · 2026-09-21

**La pregunta.** El harness publica un baseline de **~19,6% de CAGR** y la cuenta 2 lleva
**+3,12% en 3 meses (~13% anualizado)** con alpha 0. ¿Es ruido de muestra chica o hay un
desvío harness↔engine? La **tarea 33** ya mostró que **un solo** desvío de fill valía
**4-5 pp de CAGR** y dio vuelta el veredicto de la T23, así que la pregunta no es académica.

**El veredicto, en una línea.** La comparación de **equity final** que pedía el enunciado
**no es decidible** con esta ventana, y el motivo no es el poder estadístico sino algo que
había que ver antes de correr nada (§1 y §2). Pero por otra vía apareció un **desvío real y
medido**: el harness cobra dividendos y el motor vivo no, y eso vale **2,54%/año** (§4).

---

## 1. Bloqueo metodológico: la ventana atraviesa TRES configuraciones

Correr el harness con la config de hoy sobre toda la ventana habría producido una diferencia
que **no es un desvío sino un cambio de configuración** — y habría mandado a perseguir un
fantasma. Los cambios están fechados en *Acciones manuales resueltas* y se confirman contra
los datos:

| tramo | hard stop | factor régimen | screen universo | round-trips |
|---|---|---|---|---:|
| 2026-06-20 → 2026-08-26 | **ON** | 0,50 | OFF | **43** |
| 2026-08-27 → 2026-09-06 | OFF | 0,50 | OFF | 13 |
| 2026-09-07 → 2026-09-21 | OFF | **0,25** | **ON** | 13 |

**Confirmado contra la conducta, no sólo contra el doc:** las **9** salidas por `atr_stop` de
la cuenta son **todas** anteriores al 2026-08-27 (la última, PLD, el 2026-08-10). O sea que
`LIVE_HARD_STOP_ENABLED = False` describe bien el presente — y describe mal los primeros dos
meses de la cuenta, que es justo la ventana que había que reconciliar.

**Consecuencia:** el régimen más largo tiene **43** round-trips. Con σ por trade de **$303**,
la σ de la suma de 43 trades es **$1.988** ≈ 3,8% de la equity. Una reconciliación de equity
sobre ese tramo sólo detectaría desvíos **mayores a ~7,6%** (2σ). El de la tarea 33 valía
4-5 pp de CAGR anual, o sea ~1,2 pp en un trimestre: **quedaría por debajo del umbral**. El
instrumento que pedía el enunciado no tiene poder para encontrar lo que busca.

---

## 2. Las barras de hoy NO son las barras que el motor vio

Antes de comparar trade por trade hay que preguntarse si las series son las mismas. **No lo
son.** Contrastando el `fill_price` registrado por el motor contra la barra de esa misma fecha
en el cache actual:

| ticker | fecha | fill del motor | close de hoy | dif |
|---|---|---:|---:|---:|
| MU | 2026-06-18 | 1134,56 | 1133,82 | +0,07% |
| ROST | 2026-06-18 | 232,92 | 232,35 | +0,24% |
| JNJ | 2026-06-18 | 228,50 | 227,27 | +0,54% |
| WMB | 2026-06-18 | 73,16 | 72,59 | +0,78% |
| O | 2026-06-18 | 60,27 | 59,47 | **+1,35%** |
| SBUX | 2026-06-22 | 101,28 | 99,58 | **+1,71%** |

El sesgo es **sistemáticamente positivo** y **ordena por dividend yield**: MU, que no paga
dividendos, es el más chico (+0,07%); O (Realty Income, mensual) y SBUX, los más grandes. Tres
de doce caen **fuera del rango high/low** del día. No es slippage —serían ~5 bps—, es el
**ajuste retroactivo por dividendos**.

**Esto invalida cualquier reconciliación por trade contra el cache actual**, y es lo que hay
que saber antes de escribir el comparador: las diferencias que aparecerían escalan con el
rendimiento por dividendos del ticker, no con un defecto del motor.

---

## 3. Lo que SÍ coincide: las dos implementaciones de ATR

Hay **dos** implementaciones de ATR en el repo —`analysis/atr.py:compute_atr_series` (Wilder
con pandas) y `analysis/exit_replay.py:atr_series` (Wilder a mano sobre `list[Bar]`)— y la
segunda **afirma en su docstring** tener la misma semántica que la primera.

**Verificado, no asumido:** sobre las 500 barras de SPY del cache, **486 comparables**,
diferencia **máxima 0,0000%** y media 0,0000%. La afirmación es cierta.

Es un resultado negativo y vale anotarlo: era el lugar más probable de un desvío silencioso
—dos implementaciones del mismo cálculo, una de ellas afirmando paridad— y no lo hay.

---

## 4. El desvío que sí existe: el harness cobra dividendos, el motor no

**Las dos patas, verificadas por separado:**

- `data/yahoo_finance.py` baja **todo** con `auto_adjust=True` (líneas 1805 y 1867). Cada
  barra cacheada es una serie **total-return**: los dividendos ya están reinvertidos en el
  precio ajustado. Todo lo que el harness simula los cobra implícitamente.
- `paper_trading/` **no menciona dividendos en ninguna línea**. Cero órdenes de la cuenta 2
  tienen rastro de dividendo. Cuando una posición pasa por su fecha ex-dividendo, el precio
  cae y la cuenta **no recibe el efectivo**: lo pierde.

**Medido sobre las tenencias reales**, bajando el calendario de dividendos de cada ticker y
contando sólo los ex-dates dentro de cada período de tenencia (79 tenencias, 54 tickers):

| ticker | no cobrado |
|---|---:|
| MO | $148,74 |
| KMI | $39,04 |
| JNJ | $37,52 |
| GS | $25,00 |
| WMB | $24,15 |
| UNP | $19,88 |
| O | $17,62 |
| DE | $9,72 |
| TSM | $1,11 |
| **TOTAL** | **$322,77** |

> **$322,77 = 0,65% del capital en 3,05 meses ≈ 2,54% anual.**

**Y hay que leer ese número contra el resultado, no solo:** el P&L neto realizado de la cuenta
en la misma ventana fue **$521,38**. Los dividendos no cobrados son el **62% de toda la
ganancia realizada**.

*(Los dos tickers sin historial de dividendos —AMD y WBD— no pagan, así que el total no está
subestimado.)*

### Qué le hace esto al VS SPY

El sesgo estaba documentado **de un solo lado**. `analysis/metrics_panel.py:102` dice que SPY
es *«total-return implícito del cache yfinance (auto_adjust=True) — sesgo documentado»*.
Correcto. Lo que no estaba dicho es que **la cuenta se mide sin sus propios dividendos**, así
que la comparación resta peras de manzanas:

| | valor |
|---|---:|
| cuenta, como la mide el sistema (sólo precio) | +3,12% |
| cuenta, retorno total (precio + dividendos) | **+3,77%** |
| SPY, total-return | +4,17% |
| **brecha que reporta el panel** | **−1,05pp** |
| **brecha comparando total contra total** | **−0,40pp** |

**El 62% de la brecha contra SPY es un artefacto de medición, no rendimiento.** Una cuenta que
tuviera SPY y nada más aparecería perdiendo contra SPY por su propio dividend yield.

---

## 5. Qué se decide y qué no

**No se decide acá**, porque es una decisión de trading y no de auditoría: si el motor debe
**acreditar** dividendos (que el vivo se parezca al harness) o si el harness debe correr sobre
series **sin ajustar** (que el harness se parezca al vivo). Las dos cierran el desvío y no son
equivalentes — la primera cambia el P&L de la cuenta, la segunda cambia todos los veredictos
publicados. Va como tarea **221**.

**Lo que sí queda establecido:**

1. La reconciliación de **equity final** no es decidible en esta ventana, por las tres
   configuraciones (§1), y aunque lo fuera no tendría poder para un desvío del tamaño del de
   la tarea 33.
2. Una reconciliación **por trade** contra el cache actual sería **inválida** mientras no se
   controle el ajuste retroactivo (§2).
3. Las dos implementaciones de ATR **coinciden exactamente** (§3).
4. Hay **un desvío real de 2,54%/año** entre lo que el harness cobra y lo que el motor puede
   cobrar (§4), y explica el **62%** de la brecha contra SPY.

**Y lo que esto NO dice:** que el sistema tenga alpha. Con los dividendos acreditados la
cuenta pasa de −1,05pp a −0,40pp contra SPY, que sigue siendo ≤ 0 y sigue estando muy dentro
del ruido (`docs/diagnostico_pnl_cuenta2_2026-09-21.md`, t=0,21 sobre 69 trades). Lo que
cambia es que **una parte concreta de la diferencia dejó de ser un misterio**.
