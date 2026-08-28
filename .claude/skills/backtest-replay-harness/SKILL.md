---
name: backtest-replay-harness
description: Cómo correr y crear backtests/replays de exits y estrategia en FinanzIAs, con kill-criteria upfront. Usar al validar una feature de trading antes de shipear, reproducir el comportamiento histórico del motor sobre ciclos reales, o medir el impacto de una variante de salida/entrada.
---

# Backtest / Replay harness

Acá se valida si una feature **mejora las decisiones** antes de cablearla. Regla: **kill-criteria definidos ANTES de correr** (ver skill `finanzias-conventions`). Si no supera el umbral, se documenta en `docs/` y no se shipea.

## Harnesses existentes (`scripts/`)

- `run_exit_replay_t61.py` — replay de exits sobre los ciclos reales. Base del T6.1. Infra en `analysis/exit_replay.py`.
- `run_catalyst_exit_veto_backtest.py` — backtest del exit-veto por catalyst (T-CAT-6); reusa `analysis/exit_replay.py`.
- `harness.py`, `harness_walkforward.py` — backtest de estrategia (walk-forward).
- `run_switcher_validation.py`, `run_cross_sectional_validation.py` — validación de variantes de régimen / cross-sectional.
- `prefetch_harness_cache.py` — precarga el cache histórico (flag `-b` usa `get_historical_data_batch`) para no pegarle a Yahoo durante el backtest.

## Datos

- Correr **read-only sobre un backup limpio** de `finanzias.db` (carpeta `backups/`), NO sobre la DB viva. No escribir la DB desde Linux (ver `finanzias-conventions`).
- Precargar cache con `prefetch_harness_cache.py` antes de correr, para evitar 401 de Yahoo y resultados no-deterministas.
- Los harness deben ser **deterministas**. Ojo: el stacking XGBoost NO es determinístico entre runs (descubierto en T05) — está en modo kill_only justamente por eso.

## Config: contra qué cuenta corre (T27)

Los harness **no leen `paper_accounts`** (y está bien: un backtest de 10 años no puede correr sobre una cuenta viva de semanas). Pero entonces *"¿contra qué cuenta?"* = *"¿con qué config?"*, y hasta la T27 la respuesta era **la cuenta 1, pausada desde el 2026-07-01**.

- La config viva vive en **`analysis/harness_config.py`** (`LIVE_MAX_POSITIONS=10`, cuenta 2). Los runners toman de ahí el default de `--max-positions` — **no clavar literales**.
- Todo runner llama a **`announce(args.max_positions, args.universe, len(bars_by))`** antes de simular: imprime la config y **nombra los desvíos**. El objetivo no es que todo coincida a la fuerza, sino que **coincida o que el desvío esté escrito** en el pre-registro.
- Universo de la cuenta viva: **`data/harness_universe_live_acct2.txt`** (127 tickers), regenerable con `scripts/refresh_live_universe.py`. El de 41 (`harness_universe_41_10y.txt`) es el histórico de T7→T13.
- **Desvío que sigue vivo y hay que declarar:** `data/pit_signals/` se generó con ventana **expandida** (250 → ~2.514 barras) mientras el engine le pasa a `analyze()` **504 barras fijas** (`paper_history_period="2y"`). Cambian train set del XGBoost, fit de GARCH, régimen y warm-up de SMA200. Regenerar cuesta horas; cuál ventana da mejor señal es **otra pregunta, con pre-registro propio**.
- **Segundo desvío estructural (T32, lo destapó la T26):** `replay_cycle` decide **toda** salida ATR contra el **close diario** (`eval_mode="close"`, el default); el engine vivo la decide contra el **precio corriente intradía** (`get_bulk_prices`, scan ~15 min). O sea que una barra cuyo *mínimo* perforó el nivel pero cuyo *close* se recuperó **no dispara en el harness y sí en producción**. Aplica a los cinco harness de salida (T7/T23/T13/T21/T26). **El sesgo es asimétrico y crece cuanto más ajustado el múltiplo**: el harness sub-dispara, así que mide una barrera *confirmada al close*, más benigna que la viva. La 26b lo **cuantificó**: al múltiplo vivo y 10 slots, el modo `close` mide **+3.39 pp de CAGR de más** que la regla que el engine ejecuta. `eval_mode="touch"` es la cota superior; el engine queda **entre** las dos y más cerca de `touch`.
- **Tercer desvío estructural (T33, lo destapó la 26b): el fill de esa barrera.** `fill_mode="decision"` (default desde la T33) la llena al precio que la decidió; `"resting"` (legacy) siempre en el nivel. En modo `close` el legacy es **look-ahead** — ver abajo. Con el default honesto queda un desvío **conservador**: el engine llena con `gates.model_exit_fill_price` (orden en reposo) y el harness al close. Bajo `touch` los dos `fill_mode` coinciden entre sí **y con el engine**.
- **Reproducir un veredicto publicado de T7→T13 requiere `--max-positions 5`** (el banner lo avisa solo) **y `--fill-mode resting`** (T7/R2/T9/T10-T20/T11b/T12/T23/T13/T21/T26 corrieron con el fill legacy).

## Patrón para una variante nueva

1. **Definir kill-criteria upfront** en un doc `docs/<nombre>_<fecha>.md`: métrica (p.ej. ΔP/L total en puntos), umbral, y restricción de riesgo (p.ej. max DD no sube > 1.5×). **Declarar la config** (slots/universo/ventana) y sus desvíos.
2. Elegir el **contrafactual** explícito (p.ej. "la posición vetada sale al próximo scan con ATR activo"). El veredicto suele ser sensible a esto — dejarlo escrito.
3. Reusar `analysis/exit_replay.py` para no reimplementar el motor.
4. Correr sobre el backup + cache precargado.
5. Escribir resultados en el doc, incluyendo el veredicto (ship / no-ship) y por qué.
6. Tests offline del harness (ver `tests/` por convención de naming).

## Lecciones registradas

- Cross-sectional ranking (T05): **KILLED**, +0.124 ΔSharpe < umbral +0.15 → ruido. Quedó como dead-code.
- Exit-veto catalyst (T-CAT-6): flag OFF por razón **medida** (ΔP/L −0.25 < +1.5), no por ceguera.
- min_holding 3d (T6.1): única variante pre-registrada que PASÓ (+3.18 pts, DD 0.92) → shipeada en T6.4.

### Cómo NO construir un brazo oráculo (T26 — costó una corrida entera)

El oráculo existe para probar que **el instrumento ve lo que se le pide medir**. La T26 lo especificó mal y la corrida quedó inválida con los 6 criterios pasados. Dos reglas que salen de ahí:

1. **Un oráculo tiene que poder moverse en las DOS direcciones del eje.** El de la T26 sólo podía *suprimir* stops (saltearlos cuando el precio iba a rebotar), nunca *agregarlos*. Como en ese harness suprimir cuesta plata por sí solo, el brazo era **estructuralmente incapaz** de superar su umbral, por bien que eligiera. Si el oráculo sólo puede empujar hacia el lado que el eje penaliza, no está midiendo sensibilidad: está midiendo el costo de ese lado.
2. **El umbral del oráculo va contra un control IGUALADO, no contra el baseline.** Medido en T26: suprimir al azar a la misma tasa costó **−4.20 pp**, y elegir bien valió **+2.33 pp de CAGR / −11.1 pp de maxDD**. Contra el baseline el oráculo "fallaba" (−1.87 pp); contra el control igualado se veía clarísimo que el harness **sí** distingue calidad. Un oráculo que cambia el *número* de eventos además de *cuáles* necesita su control con el mismo número.

**Y la lección de lectura:** con ratio de selección alto (T26 midió **~55:1** — 143.096 candidatos BUY para 10 slots), una salida no compite contra la recuperación del propio nombre sino contra **el próximo candidato de la fila**. Toda métrica de "salimos antes de tiempo" (rebote post-salida, MFE no capturado) es engañosa si no se la pone contra el costo de oportunidad del slot.

## Brazos condicionados a régimen (decisión de Chapa, 2026-08-19)

Un candidato **puede ser una política condicional** —opera en un régimen y se apaga o se
achica en otro— y eso cuenta como candidato de primera clase, no como truco. Lo que **no** se
hace nunca es sacar los períodos malos de la muestra de evaluación.

**Por qué la distinción importa:** el criterio de robustez de régimen (C5 en la serie
26b/34/37) exige signo estable en los cuatro regímenes con **una sola** regla incondicional.
Eso mata por definición a toda estrategia buena en un régimen y mala en otro — y ahí murieron
las tres tareas más prometedoras de la serie: **T26b** (−0.15 pts en 2018Q4), **T34** (−1.18
pts), y sobre todo **T11b**, el **único brazo con alpha medido** (CAGR 12.89% vs 3.9% del azar,
Sharpe 1.24) que pierde sólo en `bear_2022` y `2018Q4`. La respuesta correcta no es aflojar el
umbral: es dejar que el candidato **sea** condicional.

**La versión legítima ya está shipeada y activa:** **T20** escala exposición según régimen con
un detector point-in-time (`analysis/market_regime.py`, SPY vs SMA200, `is_risk_off` busca la
última fecha **estrictamente menor** ⇒ sin look-ahead) y mejora Sharpe, CAGR y maxDD **a la
vez**. Es la única decisión de la serie cableada en la cuenta viva.

**Reglas para pre-registrar un brazo condicional:**

1. **El detector es parte del sistema, no del análisis.** Tiene que correr point-in-time con
   datos que existían ese día, y evaluarse **adentro** del brazo. Un gate calibrado mirando el
   resultado no es una política, es una etiqueta puesta después.
2. **C5 se mide a nivel CARTERA por ventana de régimen, no por trade.** Un gate que deja de
   operar en el bear tiene ~cero trades ahí, así que el Δ *por trade* es vacío y **pasaría el
   criterio sin hacer nada**. Lo que decide es el **retorno de la cartera durante los días de
   ese régimen**, con el cash contando como 0. Así "no operar" se premia si evita la caída y
   se castiga si se pierde la recuperación.
3. **Se reporta `n_trades` por régimen** junto al retorno, para que se vea si el brazo pasó
   porque le fue bien o porque no jugó.
4. **Preferir el mecanismo ya validado.** Si existe un overlay shipeado (hoy: el factor 0.50 de
   T20), el candidato primario es el que lo reusa — no pide flag nuevo ni mecanismo nuevo, y su
   validación no se paga dos veces. Las variantes nuevas (hard gate, `confirm_days`) van como
   secundarias.
5. **El gate paga su costo de selección.** Agregar un eje condicional agranda el espacio de
   búsqueda: el brazo se pre-registra, no se retrofitea sobre un veredicto ya publicado.

**Lo que NO es aceptable:** excluir 2008 / COVID / 2018Q4 / bear-2022 de la población para que
los números salgan mejor. No mejora la capacidad predictiva — borra la evidencia de cuándo
falla el sistema, y la cuenta llega al próximo stress sin haberlo medido. Si un brazo sólo
funciona sacando los bears, el hallazgo **es** que tiene crash-risk.

## Brazos que son una POLÍTICA ALEATORIA (T39 — RANK-NEUTRAL)

Cuando el candidato no es una regla determinista sino **una política con azar adentro**
(orden aleatorio rotado, desempate no persistente, muestreo), tres reglas que salieron de
la T39:

1. **La política es una distribución; se cablea una realización.** Se corren K semillas y
   el criterio de retorno se lee sobre la **mediana**, pero hace falta además un criterio
   sobre la **cola**: si sólo gana con algunas semillas, no hay política validada — hay una
   apuesta, porque la semilla que va a producción se elige **a ciegas**. La T39 pidió que
   ganaran **las K** y falló 15/20.
2. **La semilla que se shipearía se declara en el pre-registro, antes de correr.** Elegir
   después la que mejor rindió es seleccionar el ganador post-hoc con otro nombre.
3. **El brazo tiene que ser una función pura de sus argumentos**, no del orden de las
   llamadas (`analysis/rank_policy.py`: `blake2b` de `(semilla, fecha, ticker)`, con golden
   value testeado). Si depende del orden de llamada, el objeto medido **no es
   implementable en el engine** —que ve otro conjunto de candidatos cada scan— y no
   sobrevive a un cambio de población. La T21 lo tenía así (tarea 40) y su medición se
   sostuvo por casualidad: `portfolio_sim` pide la clave una vez por candidato del día.

### El nulo tiene que estar pareado en PERSISTENCIA

"Sin información" no es una sola cosa. Un orden **fijo** (alfabético, permutación fija) y
uno **rotado** son igual de ignorantes y **no rinden igual**: la T39 midió que persistir el
orden cuesta **1.21 pp de CAGR por sí solo**, porque concentra el book en el mismo
subconjunto elección tras elección. Por eso el alfabético de la T21 no era un baseline
neutro y su +3.10 pp era suerte de una realización de una familia ancha (7,6 pp).

- Correr **las dos familias** (fija y rotada) acota al candidato sin depender del supuesto.
- Y para saber **cuál punta aplica**, medir la autocorrelación de rango de la clave **al
  horizonte de tenencia**, no a un día: el `buy_score` da ρ=0.59 a 1 rueda pero **0.16 a 8**
  (su tenencia media), o sea que está mucho más cerca de la punta rotada. Extrapolar el
  lag-1 como AR(1) habría dado 0.015 — el decaimiento real es más lento, así que **se mide,
  no se asume** (`rank_autocorr(key, pool, lag=k)`).

### Modelar los gates de re-entrada puede mover un HALLAZGO, no sólo la escala

La T33 dejó el criterio *"¿los brazos disparan barreras a tasas distintas?"* — si no, el
desvío es un nivel común y se cancela en la comparación. **Ese criterio no cubre los gates
de re-entrada (`live_gates`, T34).** Los gates no cambian el nivel: cambian **quién entra**,
y en un harness cuyo eje es *quién entra* eso es el eje mismo.

Medido en la T39: con `touch` + `live_gates` el ranking vivo pasa de estar **por debajo de
la banda entera** del azar (T21/T33) a caer **adentro** de la banda, y el déficit se achica
de −3.23 a −1.80 pp. Mismo runner, misma población (el sanity de reproducción devuelve el
1.97% publicado al dígito). **Antes de re-leer un veredicto de ranking o selección,
`live_gates` no es opcional.**

## "El brazo muerde": cómo especificarlo cuando el brazo ESCALA (T38 — costó una corrida)

El sanity de *"el candidato cambia algo"* se venía escribiendo como **≥10% de trades
distintos** (26b, T34, T37, T39) y funcionó siempre — porque esos brazos **bloqueaban o
cambiaban qué se toma**. La T38 lo copió para un brazo que **escala el tamaño** y la
corrida salió **inválida** con el gate funcionando perfectamente:

- El candidato `G_half` **nunca bloquea** (factor 0.5, no 0), así que toma **exactamente
  los mismos tickets** que el baseline ⇒ `trade_diff ≡ 0` **por aritmética**, no por
  resultado.
- La segunda pata —*"o ≥10% del capital desplegado"*— tampoco lo ve, porque
  `portfolio_sim` **redespliega el cash liberado** en la próxima entrada: achicar una
  posición no baja el capital invertido a 10 años, lo **reasigna**. Medido: el gate
  achicó el **11,4%** de las entradas y el agregado sólo se movió **7,9%**.

**La regla:** para un brazo que escala, el sanity va sobre **la fracción de entradas (o
de capital) que el brazo efectivamente tocó** — `size_factor < 1.0` en los trades del
candidato—, no sobre el agregado ni sobre el solapamiento de tickets. Y en general:
antes de congelar, preguntarse **si el brazo puede mover esa métrica por construcción**.
Si la respuesta es no, el criterio no mide nada.

**Y la parte incómoda:** en la T38 esto se anticipó **antes** de correr (quedó en el
docstring del helper y en un test) y **la corrida se declaró inválida igual**, porque el
criterio congelado manda. Anticiparlo sirve para escribir el descriptivo que explica el
fallo, no para saltearlo.

## El perfil de régimen puede ser una propiedad de la POBLACIÓN, no de la señal (T38)

T11b cerró NO-SHIP porque su brazo *"fallaba sólo por régimen"* (`bear_2022` −2.01
pts/trade). La T38 lo descompuso en cuatro configs y el resultado cambia cómo hay que
leer todo criterio de régimen:

- Cambiar **la regla de salida** (`eval_mode` + `fill_mode` + `live_gates`, los tres de
  golpe) **no mueve el perfil**: baja el nivel, mantiene el signo de cada ventana.
- Cambiar **la población** (41 → 127 tickers, 5 → 10 slots) **lo da vuelta**:
  `bear_2022` pasa de −2.01 a **+0.46** y `covid_2020` de +1.71 a **−0.92**.
- El porqué está en los `n`: con 41 tickers cada ventana de stress tenía **10-20
  trades**. Triplicar la muestra da vuelta el signo en **dos de tres**.

**Antes de leer un criterio de régimen, mirar `n` por ventana.** Con 10-60 trades no se
distingue crash-risk de ruido de muestra, y una política condicional construida sobre
ese perfil puede quedar apuntada **al régimen equivocado** — que es exactamente lo que
le pasó al gate de la T38: en la config viva `bear_2022` es donde la señal **gana**.

## El criterio de régimen: la tolerancia se COMPUTA, no se elige (T46)

El criterio de robustez de régimen de la serie —C5 en 26b/34/37, §6.5 en T11b— usaba una
tolerancia de **−0.05 pts por trade** por ventana. La T46 midió su potencia:

- **La potencia para detectar ±0.05 pts es 5,0-5,3%** en las tres ventanas de stress de
  las **dos** poblaciones. α es 5% ⇒ **potencia nula: rechaza al nivel del azar.**
- El efecto detectable al 80% es **±0.95 a ±4.73 pts** según ventana y población
  (`n` de 20 a 407). La tolerancia estaba **19-95× por debajo** de eso.
- **Los cuatro rechazos que produjo** (26b −0.15 y −0.08; 34 −1.18; T11b −2.01) caen
  todos **por debajo** de lo detectable en su propia muestra.
- **El criterio no es inservible; el umbral sí.** Con efectos de −2,5 a −3 pts la
  estabilidad de signo es 95-100%. Con décimas, 53-66% — una moneda apenas cargada.
- **La versión de cartera tampoco rescata:** el Δ pareado por ventana da P(signo) 58-92%,
  nunca cerca del 95%. Y ojo: el **nivel** de la ventana sí es estable, pero *"la cartera
  perdió en el bear"* habla del **mercado**, no de la política.

**Cómo se escribe un criterio de régimen a partir de ahora:**

1. Calcular `detectable_mean_effect(σ, n)` de cada ventana **antes** de congelar, y
   declarar la tolerancia **por encima** de ese número. Es una línea.
2. El **gate** va sobre el **agregado de las tres ventanas de stress** (ahí hay `n`), y
   falla sólo si el **IC95%** del Δ está **enteramente** del lado malo. Rechazar por el
   punto estimado con el IC cruzando cero es lo que la serie venía haciendo.
3. Las ventanas individuales son **descriptivo obligatorio** (con `n`, IC y P(signo) al
   lado), nunca motivo de rechazo por sí solas.
4. El peso de la decisión va a los criterios **con** potencia: bootstrap pareado sobre la
   serie diaria completa (T≈2.280), maxDD, walk-forward.

**Y la advertencia de fondo:** un criterio con potencia 5% **no es conservador**. Acepta y
rechaza arbitrariamente. Un test que no puede detectar el efecto que dice vetar no está
protegiendo nada — está generando rechazos al azar y disfrazándolos de hallazgo.

Herramientas: `detectable_mean_effect`, `sign_stability`, `block_sign_stability`,
`block_delta_sign_stability` (pareada) en `analysis/walkforward_power.py`;
`scripts/run_regime_power_t46.py` corre las cuatro lecturas sobre las dos poblaciones.

## Un smoke sobre universo chico NO predice el sanity del oráculo (T49)

Un smoke con 25 tickers es la forma correcta de probar la **cañería** de un runner nuevo, y
es **engañoso para cualquier umbral**. Medido en la 49, mismo brazo y mismo código:

| universo | `ORACULO_PRIO` − baseline |
|---|--:|
| 25 tickers | **+2.50 pp** |
| 127 tickers | **+51.35 pp** |

**El mecanismo:** el poder de un oráculo escala con **la cantidad de candidatos por día**.
"El mejor del día" es muchísimo mejor cuando el día trae 50 candidatos que cuando trae 8.
Cualquier sanity de la forma *"el oráculo despega ≥ X pp"* mide, en un universo chico, algo
que no tiene nada que ver con lo que va a medir en el grande.

**Qué hacer:** usar el smoke para verificar que el runner corre, que la contabilidad cierra y
que los brazos se distinguen — **nunca** para anticipar si un umbral pasa. Y si un sanity se
va a leer contra un número, que el número **salga de la muestra** (un percentil de la banda del
control) en vez de ser un `pp` elegido a mano: así el umbral escala solo con la población.

*(En la 49 esto costó una enmienda al pre-registro que, medida sobre la población real,
resultó innecesaria: el sanity original habría pasado. La enmienda mejoró el criterio pero no
rescató nada, y el veredicto lo dice así.)*

## El control IGUALADO EN TASA es lo que convierte un descriptivo en veredicto (T26 → T49)

Cuando un brazo **elige un subconjunto** —qué stops saltear (T26), a qué candidatos darles el
turno (T49)— la comparación contra el baseline mezcla dos cosas: **intervenir** y **elegir bien
a quién**. El baseline no interviene nunca, así que no separa.

El control correcto interviene **igual de seguido, en los mismos días, en la misma cantidad**, y
elige **al azar**:

- `analysis/rank_policy.rate_matched_priority(candidates_by_date, n_by_date, seed)` — el molde
  reusable (clave **pura**: `neutral_rank(seed, fecha, ticker)`).
- Se corre con **~20 semillas** y el gate va contra el **p95** de la banda, no contra un punto.
- **Los oráculos también van igualados en tasa**, si no el sanity es trivial.

Lo que esto compró en la 49: el descriptivo de la 45 decía **+4.21 pp** para *"priorizar el
evento"*. Con el control puesto, el candidato quedó **adentro** de la banda del azar **y** por
debajo del baseline — y encima se vio que a la tenencia del engine **intervenir a esa tasa
cuesta ~2 pp elijas lo que elijas**. Sin el control, ese +4.21 pp se cableaba.

## Un eje de config no declarado puede sostener un hallazgo entero (T45/T49/T50)

`cap_days` valía **20** en la familia T11b/T38/T45 y **250** en la T21/T23/T26/T39, y **ningún
pre-registro lo nombraba**. No era una diferencia de nivel: el **+4.21 pp** que la 45 publicó
como su hallazgo principal **se da vuelta a −1.42 pp** con la tenencia del engine.

Antes de congelar un pre-registro, listar **todos** los ejes de config del harness —slots,
universo, `cap_days`, `eval_mode`, `fill_mode`, `live_gates`, overlay— y decir cuál se usa y
por qué. Si un número se va a comparar contra el de otra tarea, los ejes tienen que coincidir o
la diferencia tiene que estar escrita. Ver también la tarea 48 (la ventana `10y` es **rodante**,
así que un número publicado tampoco dice contra qué **muestra** se midió).

## Un número publicado no dice contra qué MUESTRA se midió (T48 + T52)

**«Muestra» son DOS ejes: *cuándo* (la ventana) y *sobre qué* (la población).** La T48 cubrió
el primero, la T52 el segundo. Para acusar a la cañería hay que declarar **los dos**.


Los artefactos (`data/parquet/*__10y__1d.parquet`, `data/pit_signals/`) guardan una ventana
de 10 años **anclada al día del refresh**, no a una fecha fija: cuando se refrescan, **rueda**.
Medido — la T11b re-corrida con su comando publicado, un mes después:

| | publicado | hoy |
|---|--:|--:|
| CAGR | 12.89% | **12.77%** |
| Sharpe | 1.24 | **1.22** |
| tomadas | 420 | **419** |

**Los nueve brazos perdieron 1-3 entradas.** No cambió el código: cambió la muestra.

**Por qué importa para un pre-registro:** los sanity de reproducción de la serie usan
tolerancias de ±0.05 pp, y la deriva de un mes es **2,4× eso**. Con dos estados
(OK / FALLA) el paso del tiempo se reporta como *"cambió la cañería"* ⇒ **corrida
INVÁLIDA**. Es una máquina de invalidar corridas buenas.

**Qué hacer:**

- `announce(..., window=artifact_window(bars_by))` — el banner declara la ventana efectiva.
  Es el **séptimo desvío** y ya está cableado en los 16 runners de cartera.
- Un sanity de reproducción se escribe con `harness_config.reproduction_check(...)`, que
  devuelve **cuatro** estados: `OK`, `NO APLICA` (el ancla se midió sobre **otro universo**
  ⇒ no hay nada que reproducir; **no cuenta como OK**), `FALLA` (misma ventana **y** misma
  población ⇒ cañería ⇒ corrida INVÁLIDA) e `INDETERMINADO` (la muestra se movió, o no se
  sabe cuál era ⇒ **re-anclar la constante**, no buscar un bug). `INDETERMINADO` sigue
  bloqueando el veredicto, pero con el diagnóstico correcto.
- Toda constante de reproducción **declara sobre qué ventana y sobre qué población se midió**
  (`measured_on=WINDOW_REFRESH_2026_08_09`, `measured_over=POPULATION_LIVE_ACCT2`). Sin las
  dos, un desajuste es `INDETERMINADO`: **no se acusa a la cañería sin evidencia**. La
  población de la corrida sale de `cfg.population(len(entries))` — `announce()` devuelve el
  `cfg`, así que es una línea.
- **El caso que motivó la T52:** el smoke de la 37 corrió sobre el universo legacy (41
  tickers) contra anclas medidas sobre el vivo (127) **con la misma ventana**, y los tres
  chequeos salieron `FALLA — MISMA ventana ⇒ cambió la cañería`. No había cambiado una línea.
  Antes de escribir un sanity nuevo: preguntarse si el ancla se midió sobre **esta** muestra.
