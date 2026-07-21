# Tarea 8 — R2: filtro de régimen de mercado para BUYs · **PRE-REGISTRO**

_Escrito 2026-07-20, **antes** de codear el gate y de correr ningún brazo. La
definición exacta del régimen queda congelada acá — el backlog lo pide explícito:
"pre-registrar la definición exacta del régimen antes de codear (**sin sweep
post-hoc de umbrales**)". Resultados y veredicto se completan al final._

Backlog: tarea 8 (ref gap A1), severidad ALTA. Depende de **V1** (SPY en cache) y
**E4** (harness + ventanas de stress).

---

## 1. La pregunta

Verificado en código el 2026-07-06 y re-confirmado hoy: `analyze()` y
`detect_market_regime` / `detect_market_regime_hmm` (`analysis/ml_signals.py`)
reciben **solo el DataFrame del propio ticker**. Ninguna decisión de compra consulta
el índice, el breadth ni la volatilidad de mercado. El sistema compra long contra una
corrección general **sin enterarse de que hay una corrección**.

¿Suprimir (o reducir) las compras nuevas cuando el mercado está en riesgo mejora el
resultado, o al menos reduce el drawdown, sin costar demasiado en los mercados
normales?

## 2. Qué NO toca (invariante duro)

El gate actúa **solo sobre BUYs nuevos**. **Nunca** toca exits, stops, trailing ni
take-profits. Una posición abierta se comporta exactamente igual con el gate ON u
OFF. Esto es invariante de diseño y se testea explícitamente — es la misma regla que
protegió a R1 ("nunca frena una salida").

## 3. Definición del régimen (CONGELADA — sin sweep)

**Régimen risk-off ≡ `SPY.close < SMA200(SPY.close)` al cierre del día anterior a la
entrada.**

- **SMA simple de 200 ruedas** sobre el close de SPY. Es la definición canónica de la
  industria, elegida **por ser estándar, no por performance**. Cero parámetros
  ajustados a estos datos.
- **Point-in-time estricto:** se evalúa con el close de **D−1** respecto de la barra
  de entrada. Usar el close de D sería mirar el futuro (la decisión de comprar se
  toma con la información disponible antes de la barra).
- **SPY** como proxy del mercado (no un índice equal-weight ni breadth): es el que ya
  está cacheado y el que usaría el engine en vivo.
- Si SPY no tiene 200 barras previas o el dato falta → **fail-open**: se considera
  risk-on (no se bloquea nada). Un filtro de riesgo que rompe no puede frenar la
  operatoria.

**No se prueban umbrales alternativos** (SMA50, SMA100, pendiente de la SMA, bandas
de %). Cualquiera de esos sería un sweep post-hoc sobre la misma muestra y es
exactamente lo que el backlog prohíbe.

## 4. Brazos pre-registrados

| brazo | qué hace en risk-off | rol |
|---|---|---|
| **B0** | nada (el engine de hoy) | baseline |
| **R2a** | **no se abren BUYs nuevos** | **PRIMARIO** |
| R2b | los BUYs nuevos entran con **la mitad del tamaño** | pre-registrado |
| R2c | no se abren BUYs, pero exige **5 ruedas consecutivas** bajo la SMA200 para activarse (anti-whipsaw alrededor de la línea) | pre-registrado |

**3 brazos** contabilizados como intentos para el DSR. Las 5 ruedas de R2c son un
valor fijado de antemano, **no** un parámetro barrido.

## 5. Harness — simulador de cartera (cambio respecto de la Tarea 7)

**La Tarea 7 dejó una lección explícita:** su harness daba **capital ilimitado** a
cada entrada, y eso hacía que cualquier variante que retuviera más tiempo se viera
artificialmente bien (§8.3 de `docs/scaleout_trailing_t7_2026-07-20.md`: al
normalizar por ocupación de slot, los cinco brazos de scale-out pasaban a negativo).

**Para R2 esa lección no es opcional, es central.** El valor entero de un filtro de
régimen es *cuándo estás en el mercado y cuándo no*, o sea una pregunta de cartera.
Medirlo con capital ilimitado sería medir otra cosa. Por eso R2 se corre sobre un
**simulador de cartera de verdad**:

- **`max_positions = 5`** (el de la cuenta viva). Una entrada que llega sin slot
  libre **se pierde** (no se encola) — igual que el engine.
- **Capital finito**, arrancando en el `initial_capital` de la cuenta; cada entrada
  toma un slice del cash disponible.
- Entradas procesadas en **orden cronológico** sobre los 41 tickers.
- **Salidas** con la maquinaria ya validada (`analysis/scaleout_replay.replay_cycle`
  con `sell_fraction=1.0` = comportamiento actual: stop/trail/TP + SELL de señal +
  Gate 2b).
- **Costos** 0.1% comisión + 0.05% slippage, las dos puntas.
- El cash liberado **sí se reinvierte** (a diferencia de T7): en un simulador de
  cartera eso es justamente el mecanismo que se está midiendo.

Salida: **una curva de equity por brazo** → P/L total, max DD, y el desglose por
ventana de stress.

> Este simulador es el enabler que la Tarea 7 pidió por escrito. Queda reusable para
> las tareas 9/11/12/13, que tienen el mismo problema de competencia por capital.

## 6. Población

Las mismas **4025 entradas BUY point-in-time** de la Tarea 7 (41 tickers × 10y, señal
`analyze()` completa precomputada en `data/pit_signals/`), filtradas por el simulador
según haya slot y cash. Ventanas de régimen de E4: `bull_normal` + `stress_2018q4` +
`stress_covid_2020` + `stress_bear_2022`.

## 7. Kill-criteria (congelados — del backlog, sin aflojar)

> Se shipea si **mejora el P/L ≥ +1.5 pts** **o** **reduce el max DD ≥ 20% relativo**
> en las ventanas de stress, **sin recortar el P/L de las ventanas normales más de
> 1.0 pt**.

Nótese que es un **OR** en el beneficio y un **AND** en la restricción: alcanza con
ganar por P/L *o* por DD, pero el costo en mercados normales está acotado en los dos
casos. Más:

- **PBO ≤ 0.5** (CSCV) y **DSR > 0** contabilizando los 3 brazos como intentos.
- **Invariante de exits verificado por test:** con el gate ON, ninguna posición
  abierta cambia su fecha ni su precio de salida respecto del baseline. Si esto no se
  cumple, es un bug, no un resultado.

**Reglas de decisión:**

- Ningún brazo pasa → **NO-SHIP**, se documenta y no se cablea nada.
- Pasa un brazo secundario pero no el primario → **no se shipea**; queda como
  hipótesis para un pre-registro propio.
- Lo que se shipee entra **detrás de `paper_market_regime_gate_enabled`, default
  OFF**.

## 8. La advertencia de R1 (declarada antes de correr)

**R1 (circuit breaker de drawdown) cerró NO-SHIP** por una razón estructural que
aplica parcialmente acá: *un mecanismo que solo suprime entradas nuevas no puede
reducir un drawdown que viene del book que ya tenés* — que por diseño nunca se
des-apalanca. En las 3 ventanas de stress R1 redujo el max DD apenas 2.2% relativo
medio (requería ≥20%) y costó −27% de equity terminal a 10 años por perderse los
rebotes.

**En qué se diferencia R2 y por qué vale medirlo igual:**

- R1 se activaba por el **drawdown de la propia cuenta** (una variable que reacciona
  *después* del daño); R2 se activa por el **estado del mercado**, que es información
  externa y anticipatoria.
- R1 apuntaba **solo** a reducir DD; R2 tiene también la pata de P/L (evitar entradas
  malas), y por eso su kill-criteria es un OR.

**En qué se parecen — y es el riesgo real:** los dos suprimen entradas y ninguno
des-apalanca. Así que **espero de antemano que la pata de DD rinda poco**, por el
mismo motivo que R1. Si R2 pasa, lo más probable es que sea por P/L. Y si falla por
las dos patas, la conclusión no es "el filtro de régimen no sirve" sino **"suprimir
entradas no alcanza; lo que haría falta es de-grossear"** — que es la idea R1-v2 ya
anotada en el backlog y que necesita su propio pre-registro.

Dejar esto escrito de antemano evita dos trampas: cantar victoria si el DD baja un
poco por ruido, y concluir de más si falla.

## 9. Limitaciones documentadas

- **`auto_adjust=True`** (lookahead conocido en backtests largos) y **survivorship**
  (los 41 tickers están vivos hoy): afectan a todos los brazos por igual → mueven el
  nivel, no el ranking.
- **SPY como único proxy de mercado:** no se prueba breadth ni VIX. Es una decisión de
  alcance, no un hallazgo; si R2a falla, no queda descartado que otro proxy funcione
  (pero eso sería otro pre-registro, no un sweep sobre este).
- **El simulador no modela** el ranking por `buy_score` entre candidatos simultáneos
  (usa orden cronológico y, ante empate de fecha, orden alfabético estable). Dado que
  el `buy_score` no tiene alpha medido (ref A3), rankear por él sería agregar ruido,
  no realismo. Se declara como supuesto.

## 10. Resultados

Corrido el 2026-07-20. SPY: 2512 barras (2016-07-21 → 2026-07-20), **401 días
risk-off (16.0%)**. 41 tickers, 4025 entradas candidatas, `max_positions=5`,
capital inicial $50.000, ~9 años de operatoria simulada.

**Integridad del simulador verificada antes de leer nada:** la curva de equity y la
contabilidad de cash cierran con **0.000% de desvío** en los cuatro brazos, y la suma
de P/L por trade coincide exactamente con `equity − capital`.

| brazo | equity final | P/L total | **CAGR** | max DD (cartera) | DD en stress | alivio DD stress | tomadas | filtradas |
|---|---|---|---|---|---|---|---|---|
| B0 baseline | $238.848 | 377.7% | **18.98%** | **21.6%** | 21.6% | — | 1270 | 0 |
| **R2a (primario)** | $146.620 | 193.2% | **12.70%** | **24.8%** | 15.5% | +28.1% | 1061 | 699 |
| R2b (medio tamaño) | $249.450 | 398.9% | **19.55%** | **19.1%** | 18.9% | +12.3% | 1270 | 0 |
| R2c (confirm 5d) | $141.380 | 182.8% | **12.24%** | 26.1% | 18.8% | +13.0% | 1093 | 593 |

Retorno medio por trade, por ventana:

| brazo | bull_normal | stress_2018q4 | stress_covid_2020 | stress_bear_2022 |
|---|---|---|---|---|
| B0 | +0.92 (n=1068) | −1.49 (n=47) | −0.14 (n=30) | −0.41 (n=125) |
| R2a | +0.71 (n=999) | **−1.72** (n=23) | **−3.53** (n=8) | **−2.19** (n=31) |
| R2b | +0.92 (n=1068) | −1.49 (n=47) | −0.14 (n=30) | −0.41 (n=125) |
| R2c | +0.74 (n=1011) | −1.20 (n=30) | **−5.64** (n=13) | **−2.24** (n=39) |

**Invariante de exits: OK en los tres brazos** (987 / 1270 / 1040 posiciones
compartidas con el baseline, todas con fecha y retorno de salida idénticos). El gate
no tocó ninguna salida, como exige §2.

### 10.1 El filtro identifica bien los regímenes — y aun así pierde plata

R2a bloquea con puntería: **7.9%** de las entradas en `bull_normal` contra **60.0%**
en 2018Q4, **76.1%** en bear-2022 y **81.9%** en COVID. O sea que la SMA200 **sí**
distingue los regímenes malos. El problema no es la detección.

Aun así R2a termina con **$146.620 vs $238.848** del baseline: se comió **6.3 puntos
de CAGR** (12.70% vs 18.98%). Bloquear entradas durante el risk-off también te deja
afuera de los rebotes, que es donde el sistema recupera. Es **exactamente** el
mecanismo que ya había matado a R1 (−27% de equity terminal por perderse los
rebotes), ahora medido con más resolución.

### 10.2 Los trades que R2a **sí** toma en stress son PEORES que los del baseline

El hallazgo contraintuitivo. En las tres ventanas de stress, el retorno medio por
trade de R2a es peor que el del baseline: −1.72 vs −1.49 (2018Q4), **−3.53 vs −0.14**
(COVID), **−2.19 vs −0.41** (bear-2022).

**Causa:** la SMA200 es un indicador lento. Mientras todavía marca risk-on, el
mercado ya está girando — así que las entradas que el filtro **deja pasar** son
justamente las del arranque de la caída, antes de que la media móvil reaccione. El
filtro no solo llega tarde: al bloquear las entradas posteriores (que son las que
compran barato y se benefician del rebote), **deja una muestra sesgada hacia lo
peor**. Filtrar por régimen lento empeora la calidad de lo que queda.

### 10.3 R2a empeora el drawdown de la cartera

R2a "alivia" el DD **dentro de las ventanas de stress** (15.5% vs 21.6%, −28.1%
relativo) pero el **max DD de la cartera empeora: 24.8% vs 21.6%**. Con menos trades
la cartera queda más concentrada, y su peor drawdown se muda **fuera** de las
ventanas que el criterio miraba.

Esto importa para el veredicto: el objetivo de un guardrail de drawdown es el
drawdown **de la cartera**. Medido donde corresponde, R2a no lo reduce: lo empeora.

### 10.4 Defecto de especificación en los kill-criteria (detectado post-hoc)

Se declara porque afecta cómo hay que leer la tabla, y para no repetirlo:

**(a) El umbral "+1.5 pts" de P/L está mal escalado para esta métrica.** Venía del
backlog pensado para un Δ *por trade* (como en la Tarea 7). Acá se aplicó al
**retorno total compuesto a 9 años**, donde el baseline hace 377.7%. En esa escala
+1.5 pts es ruido: cualquier cosa lo supera. Por eso R2b lo "pasa" con +21.20 pts
sin que eso signifique gran cosa (+5.6% relativo, ~0.57 pts de CAGR).

**(b) La restricción "no recortar el P/L de las ventanas normales más de 1.0 pt" no
captura el costo real.** Se midió como retorno medio **por trade** en `bull_normal`,
y R2a la cumple holgadamente (+0.21 pts). Pero el costo de R2a no está en el retorno
por trade: está en **no hacer 699 trades**. La restricción tiene un agujero por el
que pasa un brazo que destruye un tercio de la riqueza terminal.

**Lección para los próximos pre-registros:** cuando el harness es de cartera, los
umbrales tienen que expresarse en **CAGR o Sharpe**, no en puntos de retorno
acumulado, y el costo de oportunidad tiene que medirse sobre la **equity terminal**,
no sobre el retorno medio por trade. El defecto no cambia el veredicto (ver §11),
pero lo habría cambiado si R2a hubiera sido menos catastrófico.

## 11. Veredicto

### **NO-SHIP — no se cablea ningún gate de régimen. `engine.py` queda intacto.**

**R2a (el brazo primario) falla en sustancia**, aunque satisfaga la letra de la pata
de DD del criterio:

1. **Empeora el drawdown de la cartera** — 24.8% vs 21.6% (§10.3). El alivio del
   28.1% que muestra la tabla es solo *dentro* de las ventanas de stress; el peor
   drawdown se corre afuera. Un guardrail de drawdown que aumenta el drawdown de la
   cartera no cumple su propósito, por más que pase el número que se le midió.
2. **Cuesta 6.3 puntos de CAGR** (12.70% vs 18.98%), un tercio de la riqueza terminal
   ($146.620 vs $238.848).
3. **Degrada la calidad de los trades que deja pasar** en las tres ventanas de stress
   (§10.2).

**R2c falla directo:** alivio de DD 13.0% (< 20%), −195 pts de P/L, −6.7 pts de CAGR,
y el peor max DD de cartera de los cuatro (26.1%).

**R2b es el único hallazgo positivo, y aun así NO se shipea ahora:**

- Mejora las dos cosas a la vez: **CAGR 19.55% vs 18.98%** (+0.57) y **max DD de
  cartera 19.1% vs 21.6%** (−11.6% relativo), con **costo cero** en ventanas normales
  (toma exactamente los mismos 1270 trades).
- Pero: (i) es un brazo **secundario**, y la regla pre-registrada §7 dice que un
  secundario que pasa sin el primario **no se shipea**; (ii) el umbral de P/L que
  "pasa" está mal escalado (§10.4a), así que ese PASS no es evidencia; (iii) no se
  pre-registró robustez (CPCV/DSR) para él, y +0.57 de CAGR sobre un solo camino
  histórico no alcanza para descartar suerte.

### El hallazgo que vale: **el problema no es la información de régimen, es el on/off**

Los tres brazos usan **exactamente la misma señal** (SPY < SMA200) y la señal
**detecta bien** (§10.1). Lo que los separa es qué hacen con ella:

| qué hace en risk-off | CAGR | max DD cartera |
|---|---|---|
| nada (B0) | 18.98% | 21.6% |
| **entrar a medio tamaño** (R2b) | **19.55%** | **19.1%** |
| no entrar (R2a) | 12.70% | 24.8% |
| no entrar, confirmado (R2c) | 12.24% | 26.1% |

**Apagar las entradas destruye el compounding; escalarlas lo preserva.** El binario
te saca del mercado justo antes de los rebotes y encima te deja una muestra sesgada
hacia las peores entradas; el proporcional te mantiene adentro con menos riesgo.

Esto **refina** la lección de R1. R1 concluyó *"suprimir entradas no reduce el DD del
book ya tenido"*. Con R2 se puede decir algo más fuerte y más útil: **la supresión
binaria es activamente dañina, mientras que el escalado proporcional del tamaño sí
ayuda en las dos puntas.** El eje que vale explorar no es *cuándo cortar* sino
*cuánto exponerse* — que es la familia de vol-targeting / risk-parity de la
**tarea 10**, no la de los circuit breakers.

### Recomendación (no se ejecuta acá — necesita su propio pre-registro)

**R2b merece una tarea propia**, pre-registrada con: umbrales en **CAGR/Sharpe** (no
en puntos acumulados), costo de oportunidad medido sobre **equity terminal**,
robustez **CPCV/DSR**, y un sweep pre-declarado del factor de escala (0.25/0.5/0.75)
en vez del único 0.5 probado acá. Sinergia directa con la **tarea 10** (`inverse_vol`
/ `vol_target`), que ataca el mismo eje de "cuánto exponerse" desde la volatilidad en
vez del régimen — conviene pre-registrarlas juntas para no pagar dos veces el costo
de DSR.

### Enablers shipeados (nada cableado a decisiones)

- **`analysis/portfolio_sim.py`** — simulador de cartera con slots y capital finitos,
  el que la Tarea 7 pidió por escrito. Reusable por las tareas 9/10/11/12/13.
- `analysis/market_regime.py` — detector puro SPY/SMA200 con semántica PIT estricta.
- `scripts/run_market_regime_r2.py` — runner de los brazos.
- SPY 10y traído al cache Parquet (antes solo había 2y).
