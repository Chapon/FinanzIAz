# Análisis profundo del estado — 2026-08-12

_Disparador: pedido de Chapa de buscar oportunidades de mejora (predicción / rentabilidad /
performance) sobre código + documentación + hallazgos de las últimas tareas, y de **confirmar
contra qué cuenta corrieron los NO-SHIP recientes**._

_Alcance: read-only. No se tocó `finanzias.db` (copia a `/tmp`, regla 5), no se tocó código,
no se corrió el engine. Todas las mediciones nuevas son offline sobre artefactos ya
commiteados (`data/pit_signals/`, `data/parquet/`) + la DB viva en lectura._

---

## 0. Resumen ejecutivo

Tres hallazgos, en orden de plata esperada:

1. **El criterio que elige qué comprar es anti-selectivo, y en la cuenta viva pesa más que
   en cualquier test que se le haya hecho.** Medido sobre 126 de los 128 tickers de la
   watchlist de la cuenta 2, 10 años, 141.794 eventos `analyze BUY` point-in-time: el corte real que hace
   el engine (top-10 del día por `buy_score`) rinde **−0.0975 pts cada 10 ruedas contra elegir
   10 al azar** (IC95% block-bootstrap [−0.222, +0.023], p(Δ<0)=0.943) → **−2.9 pts de retorno
   anual compuesto**. Es la tercera medición independiente que apunta al mismo lugar (T9:
   −2.17 pts en `portfolio_sim`; T9 §13.7: corr −0.0259 con n=26.988; LOG-HYGIENE: `val_acc`
   medio 0.5076 sobre el universo real). **La tarea 21 sigue abierta y es la decisión más
   cara del backlog.**

2. **El stop ATR es el mayor drenaje de P/L de la cuenta viva, y su único veredicto se
   dictó con n=6, en otra cuenta y sin el harness moderno.** En la cuenta 2 (53 días,
   36 round-trips): `atr_stop` = 9 salidas, **todas perdedoras, −$2.138**, y los nombres
   **recuperan +6.81% a 20 días** después de que los vendimos (n=5 con dato completo).
   El veredicto vigente (`docs/atr_stop_recalib_2026-06-30.md`) es NO-SHIP explícitamente
   *por falta de poder* — n=6, régimen de rebote, y **`portfolio_sim.py` todavía no existía**
   (nació 3 semanas después, con R2). Es la hermana de la T23 y reusa su harness casi tal cual.

3. **Los NO-SHIP recientes NO corrieron contra la cuenta 2 — no corrieron contra ninguna
   cuenta**, y la config sintética que usan es la de la cuenta **1** (pausada), no la de la 2.
   Detalle en §1. Tres mismatches: **5 slots vs 10**, **41–49 tickers vs 128**, y **ventana de
   `analyze()` expandida 250→2.514 barras vs 2y fija (504)**. No invalida los veredictos, pero
   define cuáles son transferibles y cuáles no.

Cierra el informe una cola priorizada (§6). El patrón que unifica casi todo está en §2.4:
**en cada punto donde el sistema elige, prefiere sistemáticamente al candidato más tranquilo
o más barato — y en una población de momentum ése es el lado perdedor.**

---

## 1. La pregunta directa: ¿los NO-SHIP corrieron contra la cuenta 2?

**No. Y la respuesta precisa es más útil que un sí/no.**

### 1.1 Ninguno corre contra una cuenta

Los ocho harness de la serie (T7 scale-out, T8/R2 régimen, T9 meta-labeling, T10 sizing,
T11b anomalía, T12 FORM4, T23 TP-CAL, T13 ENT1) **no leen `paper_accounts` ni `paper_orders`**.
Verificado por grep: la única aparición de "account" en esos scripts es `_accounting_ok()`,
que chequea la contabilidad interna del simulador. Corren sobre `analysis/portfolio_sim.py`
con una config sintética pasada por CLI.

Eso es correcto por diseño (un backtest de 10 años no puede correr sobre una cuenta viva de
7 semanas), pero significa que **la pregunta "¿contra qué cuenta?" se traduce en "¿con qué
config?"** — y ahí sí hay un problema.

### 1.2 La config sintética es la de la cuenta 1, que está pausada

| dimensión | harness (los 8) | cuenta 1 (`Sim Principal`) | **cuenta 2 (`Sim Segundo`, VIVA)** |
|---|---|---|---|
| `max_positions` | **5** (default de argparse en los 8 scripts) | 5 | **10** |
| universo | 41–49 tickers | 52 watchlist | **128 watchlist** |
| capital | 50.000 | 50.000 | 50.000 |
| allocation | equal slice | `signal_weighted` (cae a equal) | `equal_weight` |
| modo | — | `manual` | **`auto`** |
| `is_active` | — | **0 (pausada desde 2026-07-01)** | 1 |
| ventana de `analyze()` | expandida, 250 → 2.514 barras | `paper_history_period="2y"` (504) | **504** |

Fuentes: `grep -A3 '"--max-positions"' scripts/run_*.py` (default 5 en los 8);
`SELECT * FROM paper_accounts`; `scripts/precompute_pit_signals.py:192`
(`analyze(ticker, df.iloc[: i + 1])` = ventana expandida);
`config/settings_manager.py:580` (`paper_history_period` default `"2y"`).

### 1.3 Qué se mueve y qué no

**Se mueve (conclusiones sensibles a la escasez de slots):**

- **T23 / TP-CAL.** El NO-SHIP es por `PBO 0.889`, y el mecanismo que el propio veredicto
  identifica es la **cascada de path por slots finitos** (§77 del doc: "con slots finitos el
  cambio de TP induce cascada de path… 98.9% de trades con salida distinta"). Sacar el TP
  hace que las posiciones duren más; **con 10 slots el costo de oportunidad de ocupar uno es
  exactamente la mitad**. El brazo pasó 5 de 6 criterios a 5 slots.
- **T13(b) / time stop.** El NO-SHIP es "SIN POBLACIÓN" (0,5% de trades alcanzados, umbral
  ≥5%) porque la tenencia mediana del baseline es **6 días**. En la cuenta 2 la tenencia
  mediana real es **10 días** (media 12, máx 40). Población distinta.
- **T9 / ranking.** Con 5 slots y la watchlist de la cuenta 1 (49 con artefacto PIT) hay
  **~24 candidatos BUY/día mediana → ratio 4,8:1**. En la cuenta 2: **64 candidatos/día
  mediana sobre 127 tickers → 6,4:1**. El ranking decide más, no menos. (Ver §2 — lo medí
  directamente.)
- **T20 / R2b, SHIPEADO Y ACTIVO.** Validado a 5 slots. Hoy corre a 10 slots y con la cuenta
  al **99,96% invertida** (cash $18,79). Un escalado de tamaño a la mitad sobre una cuenta sin
  cash libre no hace lo mismo que sobre una con 20% de caja. **Es el único de la lista que ya
  está tomando decisiones vivas con validación de otra config.**

**No se mueve:**

- **T9 (el nulo del `buy_score`), T11b, T12.** Son afirmaciones sobre la *señal*, no sobre la
  cartera: AUC 0.498, robustez de régimen del detector de anomalía, insider cluster contrario
  en stress. La escasez de slots no cambia si una señal predice.
- **T10 / sizing por riesgo.** El costo de ~4pp de CAGR de `inverse_vol`/`vol_target` es un
  efecto de sizing por nombre, ortogonal al conteo de slots.

### 1.4 El tercer mismatch, el más silencioso

`data/pit_signals/` —el artefacto que alimenta **toda** la serie T7→T13— se generó con
`analyze()` sobre una **ventana expandida** (de 250 barras al principio a 2.514 al final).
El engine vivo le pasa a `analyze()` **exactamente 504 barras** (`paper_history_period="2y"`).
No es el mismo generador de señal: cambian el set de entrenamiento del XGBoost, el fit de
GARCH, el detector de régimen y los warm-ups de SMA200.

**Mitigante medido:** la distribución de scores es comparable. Score medio del top-10/día en
el artefacto PIT (2025+) = **0.725** [p10 0.698, p90 0.750]; score de las BUYs realmente
filleadas en la cuenta 2 = **0.784** [0.720, 0.850]. Suficientemente parecidas para que las
mediciones de §2 transfieran, pero **la ventana debería igualarse explícitamente** (o
declararse como caveat en cada pre-registro). Hoy no está declarada en ninguno.

---

## 2. Predicción — el criterio de selección vivo, medido sobre el universo real

### 2.1 El experimento

Reproducción del hallazgo de la T9 §13.7, pero **sobre la watchlist de la cuenta 2** y **en
el corte exacto que hace el engine**.

- Universo: **126 de los 128** tickers de `paper_watchlist` (account_id=2) — 127 tienen
  artefacto PIT y 126 tienen además barras `10y` en Parquet.
- Eventos: **141.794** `analyze BUY` point-in-time, 2017-07 → 2026-08.
- Entrada: close de D+1 (mismo convenio del engine). Salida: +5 / +10 / +20 ruedas.
- Score: `ml_probability` — **el mismo objeto** que `_default_strength()` usa para rankear
  (`strategies.py:271-276`), verificado contra `precompute_pit_signals.py:201`.

### 2.2 Resultado: el score rankea al revés, y peor cuanto más largo el horizonte

| horizonte | corr(score, fwd) | decil TOP | decil BOTTOM | spread |
|---|---|---|---|---|
| 5 d | −0.0184 | +0.212% | +0.582% | **−0.370 pts** |
| 10 d | −0.0261 | +0.492% | +1.083% | **−0.591 pts** |
| 20 d | −0.0364 | +0.988% | +2.091% | **−1.104 pts** |

Monotonía por decil a 10 días (del más bajo al más alto):
`+1.08 +0.91 +0.87 +0.70 +0.72 +0.73 +0.72 +0.45 +0.59 +0.49`.
Recorte 2024+ (n=38.302): corr −0.0249, mismo patrón → **no es un artefacto de un régimen viejo.**

### 2.3 El corte real: top-10 del día vs 10 al azar

Esto es lo que el engine hace todos los días con 10 slots libres.

```
top-10 por buy_score : +0.6430%  por período de 10 ruedas
10 al azar           : +0.7405%  (media de 300 carteras aleatorias, pareadas por día)
Δ pareado            : −0.0975 pts   (mediana −0.0870)
IC95% block-bootstrap (bloques de 20d, 2.000 resamples): [−0.2219, +0.0227]
p(Δ<0) = 0.943 · días en que la selección pierde: 52.4%
compuesto anual: 17.53% vs 20.43%  →  Δ −2.90 pts/año
```

**Honestidad sobre el resultado:** el IC95% **cruza cero**, y el desglose por año da
**6 de 10 años negativos** (2018 −0.14, 2019 −0.14, 2020 −0.13, 2023 −0.20, 2025 −0.20,
2026 −0.66; positivos 2017 +0.23, 2021 +0.02, 2022 +0.15, 2024 +0.12). Por sí sola esta
medición **no clarea un kill-criteria al 95%**. Lo que la hace accionable es la convergencia:

| medición | método | resultado |
|---|---|---|
| T9 brazo B1 | `portfolio_sim`, 41 tickers, 5 slots | −2.17 pts de CAGR vs alfabético |
| T9 §13.7 | corr score↔fwd, n=26.988 | −0.0259, top-20% < bottom-20% |
| T9 modelo | AUC OOS del meta-modelo pooled | 0.4980 |
| LOG-HYGIENE (T25) | `val_acc` media, 134 tickers vivos | 0.5076 |
| **este informe** | corte real top-10/día, n=141.794, universo de la cuenta 2 | **−2.90 pts/año**, p(Δ<0)=0.943 |

Cinco mediciones, cuatro métodos, dos universos distintos, todas del mismo lado.

### 2.4 El mecanismo, trazado a una línea

`analysis/ml_signals.py:1147`:

```python
vol_penalty = market_context.risk_score * 0.08
return float(np.clip(raw_prob - vol_penalty, 0.05, 0.95))
```

El score **le resta una penalidad de volatilidad al ranking**. Medido sobre los mismos
141.794 eventos:

- `corr(score, vol20) = −0.1165` → efectivamente prefiere nombres calmos.
- `corr(vol20, fwd10) = +0.1189` → en esta población, más vol ⇒ más retorno a 10 días.
- `corr(score, fwd10) = −0.0261`, y **controlando por vol20 queda −0.0124**.

O sea: **la penalidad de vol explica aproximadamente la mitad de la anti-selección**. La otra
mitad la aporta el consenso de indicadores en sí — el spread top-vs-bottom sigue siendo
negativo **dentro de cada quintil de volatilidad** (−0.17 / −0.64 / −0.29 / −0.75 / −0.33).
Perfil del top-10 vs el resto: momentum 20d **+1.91% vs +2.30%**, vol20 **26.1% vs 28.5%**.

**Dos consecuencias:**

1. **Sacar la `vol_penalty` no alcanza.** Arregla la mitad. El score completo no sirve para
   rankear. Eso refuerza la opción (b) de la tarea 21 (ranking no-predictivo) por sobre un
   parche quirúrgico.
2. **La penalidad de vol está en el lugar equivocado, y encima duplicada.** Penalizar
   volatilidad es una decisión de **sizing**, y el sistema ya la toma dos veces por otro lado:
   el `vol_overlay` (σ de cartera) y el R2b (régimen). Meterla además en el criterio de
   *selección* mezcla riesgo con retorno esperado y sesga el ranking hacia el lado que rinde
   menos.

### 2.5 Es el mismo patrón que T13, T7 y T9 — vale la pena nombrarlo

- **T13(a):** la entrada por pullback "es un anti-selector" — las esperas que **expiran**
  (el precio nunca retrocedió) rinden +2.55 pts / 65% ganadoras contra +0.26 / 43% de las que
  fillan. Exigir un descuento descarta a las mejores.
- **T7:** curva dosis-respuesta monótona — cuanto menos se le hace caso al SELL de señal, mejor.
- **T9 + este informe:** el ranking prefiere el nombre más calmo y con menos momentum, y ése
  rinde menos.

**En los tres casos el sistema elige al candidato más tranquilo / más barato / más "prudente",
y en una población de momentum ése es el lado perdedor.** No son tres bugs: es una preferencia
sistemática repetida en tres capas distintas (entrada, salida, ranking). Cualquier tarea
futura debería declarar de qué lado de este eje está antes de correr.

### 2.6 Exploratorio (NO promovible — sin pre-registro, costo DSR pagado)

Mismo corte top-10/día, fwd 10d, cambiando solo el criterio de orden:

| criterio de ranking | fwd10 medio |
|---|---|
| vol 20d DESC | +1.286% |
| momentum 20d DESC | +0.940% |
| `buy_score` ASC (inverso) | +0.842% |
| momentum 20d ASC | +0.766% |
| **aleatorio** | **+0.757%** |
| **`buy_score` DESC (el vivo)** | **+0.643%** |
| vol 20d ASC | +0.457% |

Se anota tal cual y **no se recomienda ninguno**: "vol DESC" es un factor de riesgo sin
ajustar (más vol, más retorno, más DD), y "score inverso" es exactamente el tipo de resultado
post-hoc que la T9 mostró que hay que validar con brazo oráculo y `portfolio_sim` antes de
creerle. Sirven solo para dimensionar cuánto hay sobre la mesa.

---

## 3. Plata — dónde se va en la cuenta viva

Datos: cuenta 2, 2026-06-20 → 2026-08-12 (53 días corridos), 82 fills, 36 round-trips FIFO,
equity 50.000 → **51.307,06 (+2,61%)**, max DD −2,88%, Sharpe diario anualizado ≈1,52 (n=31 días
con snapshot — indicativo, no concluyente).

### 3.1 Por familia de salida

| familia | n | P/L neto | ret medio | días p50 | ret del ticker **después** de vender |
|---|---|---|---|---|---|
| `atr_tp` | 8 | **+2.978,52** | +9,39% | 15,5 | +0,49% @10d · **+2,15% @20d** (n=7/…) |
| `analyze SELL` | 17 | +226,91 | −0,19% | 9,0 | **−1,51% @10d · −5,63% @20d** (n=15) |
| `atr_trail` | 2 | −15,59 | −0,08% | 8,0 | +0,47% @10d |
| `atr_stop` | 9 | **−2.138,30** | −5,22% | 12,0 | −0,89% @10d · **+6,81% @20d** (n=5) |
| **total** | 36 | **+1.051,53** | | 10,0 | |

Win rate 38,9% · payoff 2,10 · profit factor 1,34 · fricción $231,54.

**Cuidado con la lectura fácil:** que `atr_tp` sea 100% ganadora y `atr_stop` 0% es
tautológico (un TP solo dispara en ganancia, un stop solo en pérdida). Lo informativo es la
última columna — **qué hizo el precio después de que salimos**:

- **El `analyze SELL` está vendiendo bien.** −1,51% a 10 días y −5,63% a 20 después de la
  venta (n=15). Eso **contradice** el sesgo pesimista histórico (auditoría 2026-06-09, T6.3:
  gap SELL 0.20-0.45 = +23 pts) y la dosis-respuesta de T7. Muestra chica y un solo régimen,
  pero es una señal de que ese diagnóstico puede haber caducado — vale re-medirlo con la
  pestaña Métricas antes de seguir citándolo.
- **El `atr_stop` está cortando nombres que rebotan.** +6,81% a 20 días post-salida (n=5).
  Junto con los −$2.138 que aportó, es el candidato más claro de la cuenta.
- **El `atr_tp` trunca poco.** +2,15% a 20 días (n=7) — consistente con el sweep de la T23
  (+0,165 pts por trade de 4.0→6.0). Real, pero chico.

### 3.2 El stop ATR es la tarea de plata más fundamentada

El veredicto vigente (`docs/atr_stop_recalib_2026-06-30.md`) dice NO-SHIP, pero **se auto-declara
sin poder**:

- **n=6 ciclos**, de los cuales **LRCX aporta el 63%** del efecto (leave-one-out tumba las dos
  variantes ganadoras bajo el umbral).
- Régimen de rebote abr–jun 2026: *"los stops existen para el drawdown sostenido que esta
  muestra no contiene"*.
- Cuenta 1, con el contrafactual limitado a variantes **más laxas** (mult ≥ 2.0) porque
  re-simular desde el entry no era posible con ese harness.
- **`analysis/portfolio_sim.py` no existía**: nació el 2026-07-20 con R2, tres semanas después.

Hoy están las tres cosas que faltaban: `portfolio_sim` con capital y slots finitos, los
47.282 eventos PIT (o los 141.794 del universo de 127), y el `paired_block_bootstrap` que la
T13 dejó como enabler y que ya demostró separar mejor que el PBO. **Es la hermana simétrica
de la T23** (aquélla movió la barrera de arriba, ésta mueve la de abajo) y reusa
`scripts/run_tp_cal_replay_t23.py` casi tal cual.

Kill-criteria sugerido (a congelar antes de codear, regla 2 — esto es un enunciado, no el
pre-registro): umbrales en **CAGR y Sharpe sobre la curva de equity** (lección de la lápida
de la T8), **maxDD declarado al frente como métrica de riesgo** (el defecto que dejó abierta
la tarea 21), brazos `mult ∈ {2.0 baseline, 2.5, 3.0, 3.5, sin stop}` **más el brazo oráculo
obligatorio** (validó el harness en T9/T10/T11b/T12), robustez por régimen como prueba central
(2018Q4 / COVID / bear-2022 — es un guardrail de riesgo, no puede shipear si solo funciona
en bull) y `max_positions=10` **más** una corrida de sensibilidad a 5.

### 3.3 Fricción y rotación

```
82 fills · notional total $361.922 · comisión $50,59 · slippage $180,95 · total $231,54
fricción / notional = 0,064%
fricción / equity   = 0,46% en 53 días  →  ≈ 3,19%/año
rotación            = 7,24× el equity en 53 días  →  ≈ 50×/año
```

La fricción se comió el **18% de la ganancia bruta cerrada** ($231,54 sobre $1.283). No es un
bug: la comisión sale del modelo IBKR tiered (`ibkr_commission_plan="tiered"`, ~$0,62/fill,
realista) y el slippage es exactamente los 5 bps del spec. **Es estructural a la tenencia de
10 días con 10 slots**, y define el piso: la estrategia arranca cada año **3,2 puntos abajo**.
Sumado al arrastre del ranking (§2.3, −2,9 pts) son **~6 puntos anuales de viento en contra**
antes de que la señal diga nada. Vale la pena tenerlo escrito al lado de cualquier estimación
de alpha futura.

### 3.4 Benchmark

En el mismo período la cuenta hizo **+2,61%**. No pude cerrar el `vs SPY` acá porque
`data/parquet/SPY__10y__1d.parquet` está congelado en **2026-07-20** mientras los otros 503
archivos `10y` llegan al 2026-08-07 (el `SPY__2y__1d.parquet` **sí** está fresco al 08-12, así
que **R2b y el panel vivo no están afectados**). Es la misma clase de bug que cerró la T22,
pero en la capa Parquet y golpeando solo a los harness. Ver §5.

---

## 4. Performance de código

**Titular honesto: después de la T24 el cómputo ya no es el cuello.** Medí lo que quedaba y
son ~1,4 s por scan. Lo reporto igual porque los dos ítems son **el mismo defecto que la T24
acaba de arreglar**, uno de ellos esconde una trampa de corrección, y cerrarlos cuesta poco.

### 4.1 `_INDICATOR_CACHE` — cap 50 contra 128 tickers (mismo defecto (b) de la T24)

`analysis/technical.py:166` → `_INDICATOR_CACHE_MAX = 50`.
La cuenta 2 recorre **128 tickers distintos por scan**. Con LRU de 50 y un barrido secuencial
de 128, **ninguna entrada sobrevive a una pasada: el hit rate es 0%**. RSI + MACD + Bollinger
+ SMA20/50/200 se recalculan enteros en cada scan y otra vez si se abre la pestaña Análisis.

Costo medido (128 tickers × ~2.448 barras, sandbox): **0,27 s por scan**. Chico.

**Pero hay una trampa: subir el cap solo, empeora.** La huella es
`_df_fingerprint(df) = (len(df), str(df.index[-1]))` — **no mira el close**. Durante la rueda,
la barra parcial de hoy cambia de valor pero **no** de largo ni de fecha ⇒ misma clave. Hoy
eso está enmascarado porque el cache nunca acierta; con el cap arreglado, los indicadores del
día quedarían **congelados en la primera lectura de la mañana** mientras el precio se mueve.
Es literalmente el defecto (a) de la T24 (huella keyada por un dato que se mueve / no se mueve
cuando debería) en el otro sentido. **El fix son las dos patas juntas**: cap ≥ 192 (mismo
criterio que `_XGB_CACHE_MAX`) **y** huella que incluya el último close (digest, como
`_xgb_cache_key`).

### 4.2 GARCH refitea en cada scan intradía

`analysis/garch_signals.py:136-157` → la huella incluye `close[-5:]`. Durante la rueda el
último close se mueve ⇒ clave nueva ⇒ **miss garantizado en cada scan**. El cap (256) está
bien; el problema es la clave, igual que en 4.1.

Costo medido: **8,3 ms por fit** (GARCH(1,1) sobre 501 retornos) → **~1,1 s por scan** para
128 tickers. Con `paper_scan_interval_minutes=15` son ~26 refits/hora/ticker que devuelven
prácticamente lo mismo.

**Matiz que hay que decidir, no asumir:** a diferencia del XGBoost (que descarta las últimas
5 filas sin label, así que la barra parcial es demostrablemente irrelevante), el fit de GARCH
**sí** usa el último retorno. La pregunta abierta es si mover el último de 501 retornos cambia
el `GarchForecast` lo suficiente como para justificar el refit. Se mide antes de tocar nada
(distribución del Δforecast entre el primer y el último scan del día); si es despreciable,
misma solución que la T24 — keyear a granularidad diaria.

### 4.3 `_STACK_CACHE_MAX = 64` — latente

`ml_signals.py:1203`. Hoy no molesta porque `stacking_enabled=False` (kill_only). Si alguna
vez se prende, thrashea igual que 4.1 con 128 tickers. Subirlo cuando se toque el archivo.

### 4.4 Dónde sí está el costo

La telemetría de runtime (log 2026-07-15) daba scan de 124,81 s con **fetch de 81,95 s**.
Después de la T24 el `analyze` bajó de 48,9 s a 1,7 s, así que **el fetch es ahora ~el 90% del
scan**. Y escala con el universo: la watchlist de la cuenta 2 tiene **128 nombres para llenar
10 slots** — con 64 candidatos BUY por día de mediana, **~118 de los 128 análisis se tiran a
la basura en cada scan**. Si en algún momento la latencia molesta, la palanca no es el CPU:
es (a) prefiltrar barato antes de bajar/analizar, o (b) revisar si la watchlist necesita 128
nombres. Las dos tocan qué candidatos se consideran ⇒ **son decisiones de trading, con
pre-registro**, no optimizaciones libres.

---

## 5. Riesgo operativo y deuda de contexto

1. **App cerrada = no se acumula nada.** El hueco 2026-07-25 → 08-08 (16 días) costó el pico
   de la temporada Q2 y corrió T-CAT-5b (y con él el Brazo A de la T11) a **oct-nov 2026**.
   Ya está en el backlog como decisión pendiente; lo repito acá porque es lo único que
   **bloquea la única tarea de trading de la cola** y el costo se paga en meses, no en horas.
2. **La cuenta 1 sigue pausada con 5 posiciones abiertas** (SBUX, LRCX, MO, KO, CL) de hace
   30–41 ruedas que nadie evalúa. Reactivarla dispararía varias salidas juntas en el primer
   scan.
3. **`CLAUDE.md` está desactualizado** (dice "cuenta activa: Sim Principal (id=1)" y
   "`signal_weighted`"); el backlog ya lo corrigió en *Acciones manuales pendientes* pero el
   archivo que Claude lee primero cada sesión sigue diciendo lo viejo. Es barato y evita que
   la próxima tarea vuelva a leer mal la evidencia viva — que es exactamente lo que le pasó
   al brazo (b) de la T13.
4. **`SPY__10y__1d.parquet` congelado en 2026-07-20** vs 503 archivos `10y` al 2026-08-07.
   No afecta la app (el `2y` está fresco), sí afecta a cualquier harness que use el régimen de
   mercado sobre 10y — o sea al brazo de robustez por régimen de **toda** la serie. Chequeo de
   frescura antes de correr, o refresh del artefacto.
5. **`_INDICATOR_CACHE` + GARCH**: ver §4, misma familia que la T24.
6. **28 órdenes con `signal_score` NULL** (ya en el backlog) — ensucian cualquier análisis
   score↔outcome, incluido el de §2 si alguna vez se hace sobre datos vivos.

---

## 6. Cola priorizada propuesta

Ninguna de estas es una tarea abierta: son enunciados. Cada una necesita **pre-registro
congelado antes de codear** (regla 2). El orden sale de plata esperada × solidez de la
evidencia × costo.

| # | tarea | tipo | por qué ahora | costo |
|---|---|---|---|---|
| **1** | **Cerrar la tarea 21** — decidir el ranking, con pre-registro propio y la métrica de riesgo declarada al frente | decisión + código | 5 mediciones convergentes (§2.3); **−2,9 pts/año** de arrastre estimado; el ratio de selección vivo (6,4:1) es peor que el testeado; es una **resta**, no una feature | 1 sesión de harness sobre `portfolio_sim` a 10 slots + brazo oráculo |
| **2** | **STOP-CAL** — recalibrar `atr_stop_mult` con el harness moderno | trading | mayor drenaje vivo (−$2.138 / 9 salidas) + rebote +6,81% @20d; el NO-SHIP vigente se auto-declara sin poder (n=6, sin `portfolio_sim`) | reusa `run_tp_cal_replay_t23.py`; 1 sesión |
| **3** | **Igualar la config del harness a la cuenta viva** — `max_positions=10` y ventana `2y`, o declarar el caveat en cada pre-registro | metodología | §1.2/§1.4; hoy **R2b decide en vivo con validación de otra config** | chico: defaults + una corrida de sensibilidad |
| **4** | **Re-abrir T23 (TP-CAL) a 10 slots** | trading | pasó 5/6 criterios a 5 slots y el criterio que falló (PBO) mide justo la cascada de path que la escasez de slots amplifica | re-corrida del harness existente |
| **5** | **CACHE-IND + GARCH-KEY** — cap ≥192 **y** huella sensible al close, en los dos | técnico | mismo defecto que la T24; ~1,4 s/scan + **trampa de indicadores stale** si se sube el cap solo | 1 sesión chica, gate técnico |
| **6** | **Actualizar `CLAUDE.md`** (cuenta 2, `equal_weight`, 10 slots) + frescura del artefacto SPY 10y | higiene | la T13 ya leyó mal la evidencia viva por esto | minutos |
| **7** | **Re-medir el sesgo del `analyze SELL`** con la pestaña Métricas sobre la cuenta 2 | medición | §3.1 sugiere que el diagnóstico de pesimismo (2026-06-09 / T6.3) puede haber caducado; se sigue citando en tareas nuevas | display-only |

**Lo que sigue bloqueado y no cambia:** el Brazo A de la T11 (PEAD honesto) hasta la temporada
Q3, y con él la única fuente de candidatos nueva de la cola. Las ideas derivadas de T11b
(`anomalía × gate de régimen`) y T12 (`C≥4 × risk-off`) siguen vivas y siguen necesitando
pre-registro propio.

---

## 7. Nota de método

Todo lo cuantitativo de §2 y §3 es reproducible offline con los artefactos ya commiteados
(`data/pit_signals/`, `data/parquet/`) más la DB en lectura. Las mediciones nuevas son
diagnósticos exploratorios, **no** veredictos: ninguna tiene kill-criteria pre-registrado y
por lo tanto **ninguna habilita a shipear nada por sí sola** — habilitan a *abrir* tareas con
su pre-registro. Los IC y los desgloses por año se reportan aunque debiliten el titular
(§2.3): el punto de la serie T7→T13 es que la evidencia decide, no el enunciado.
