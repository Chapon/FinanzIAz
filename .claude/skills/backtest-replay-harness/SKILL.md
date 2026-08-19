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
