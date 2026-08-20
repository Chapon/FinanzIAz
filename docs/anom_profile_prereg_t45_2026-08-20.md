# Pre-registro CONGELADO — ¿Qué queda del veredicto de la T11b? (Tarea 45, ANOM-PROFILE)

**Fecha:** 2026-08-20 · **Estado:** congelado ANTES de codear.
**Ref:** `docs/BACKLOG.md` tarea 45 · `docs/anomaly_signal_t11b_2026-07-23.md` (el veredicto que se
re-decide) · `docs/anomaly_signal_prereg_t11b_2026-07-23.md` (detector, brazos y criterios, que se
**reusan intactos** salvo lo del §4) · `docs/anom_regime_t38_2026-08-19.md` §2-§3 (por qué el motivo
publicado no replica) · `docs/regime_power_t46_2026-08-19.md` §4 (el criterio nuevo) ·
`docs/BACKLOG.md` tarea 48 (la ventana rodante, encontrada al armar el sanity de reproducción).

---

## 0. La parte incómoda, primero: esto **no es una corrida a ciegas**

**Los resultados de la T11b y de la 38 ya están publicados y yo los conozco al escribir esto.** Sé que
en la config viva el brazo `A_k2.0_m1.5` da **9.23%** de CAGR contra un p95 del azar time-matched de
**5.97%**, Sharpe **1.02**, maxDD **12.9%**, y sé su perfil de régimen entero (`bull_normal` +0.91,
`2018Q4` −1.12, `covid_2020` −1.75, `bear_2022` +0.46). Re-abrir un NO-SHIP cambiando **justo** el
criterio que lo produjo, sabiendo eso, es —sin recaudos— **la definición de elegir el resultado**.

Los cinco recaudos, declarados acá:

1. **El motivo para cambiar §6.5 es ajeno a esta tarea y anterior a ella.** La 46 midió la potencia de
   ese criterio sobre las **dos** poblaciones de la serie y encontró **5,0%** en las tres ventanas de
   stress de la población `anomaly` — o sea α. No se cambió el criterio porque frenara a la T11b; se
   cambió porque **no discrimina nada**, y la T11b es una de las cuatro que rechazó.
2. **El criterio nuevo no se elige: se computa.** La tolerancia sale de
   `detectable_mean_effect(σ, n)` sobre la muestra. Nadie puede ajustarla para que pase.
3. **Se AGREGAN criterios, no sólo se reemplaza uno.** Entran como gates duros la **sensibilidad a 5
   slots** (C7, precedente de la 47) y la **additividad sobre el engine** (C8) — la pregunta que el
   ship realmente plantea y que la T11b **nunca hizo**: su contrafactual era *entrar al azar*, y nadie
   opera contra eso; el engine ya tiene una fuente de candidatos. Las dos empujan a NO-SHIP y se
   declaran sabiéndolo.
4. **El brazo NO se re-selecciona.** El candidato queda **congelado en `A_k2.0_m1.5`**, que es el que
   la regla de la T11b eligió sobre la población **vieja**. Sobre la población viva la elección del
   brazo es, así, **fuera de muestra**. Lo que la regla de la T11b habría re-seleccionado hoy se
   reporta como descriptivo — y si es otro brazo, eso es un hallazgo de inestabilidad, no un cambio de
   candidato.
5. **El resultado esperado está escrito de antemano: es plausible que esto vuelva a cerrar NO-SHIP**, y
   eso sería un éxito de la tarea. Lo que se busca es **decidir con criterios que tengan potencia y
   contra el contrafactual correcto**, no llegar a un veredicto en particular.

**Lo que NO se toca del diseño de la T11b:** el detector y sus parámetros de forma (§2 de su
pre-registro), la grilla de 9 brazos `(k, m)`, el simulador, los costos, la triple barrera, el
contrafactual Monte Carlo time-matched, y los criterios **§6.1, §6.2, §6.3, §6.4 y §6.6** con sus
umbrales originales. Si se tocara algo más, esto no sería una re-decisión: sería una tarea nueva
disfrazada.

**Un cambio menor al contrafactual, y es adverso al candidato.** La T11b time-matcheaba el Monte Carlo
al brazo **primario** (`A_k2.0_m2.0`, 357-360 entradas) y comparaba contra él al brazo de **decisión**
(`A_k2.0_m1.5`, 466-467 entradas): el candidato entraba con **~30% más de entradas** que su control, o
sea con más exposición, y parte de su ventaja de CAGR es eso. Acá el MC se matchea al **candidato**,
que es lo que ya hizo la 38 (`run_anom_regime_t38.py:301`). Es **más estricto**, no menos, y queda
declarado como el único desvío de diseño respecto de la T11b fuera del §4.

---

## 1. La pregunta

La T11b cerró **NO-SHIP por un solo criterio**: su §6.5 de robustez de régimen, que exigía retorno
medio por trade **positivo o neutro en cada una de las 4 ventanas** y le rechazaba el brazo por
`bear_2022` (−2.01 pts/trade, **n=20**). Después:

- la **38** midió que ese perfil **no es una propiedad de la señal sino del universo de 41 tickers**:
  en la población viva `bear_2022` pasa a **+0.46** y `covid_2020` de +1.71 a **−0.92**. Dos de las
  tres ventanas de stress cambian de signo, y no por modelar la regla del engine (eso deja el perfil
  intacto) sino por la **población** — cada ventana tenía 10-20 trades y ahora tiene 19-63;
- la **46** midió que con esos `n` el criterio **rechaza al nivel del azar**: en la población `anomaly`
  el efecto detectable al 80% de potencia es **±3.43** (`2018Q4`), **±4.73** (`covid_2020`), **±2.35**
  (`bear_2022`) y **±1.85** en el agregado — contra un umbral de 0.00 pts.

> **¿Vuelve la señal de ruptura como candidato de entrada —sin gate de régimen— cuando se la decide
> con criterios que tienen potencia y contra el contrafactual que el ship realmente plantea?**

**Sin gate** porque la variante gateada ya se midió: la 38 encontró que el overlay de T20 sobre esta
señal **destruye valor** (ΔCAGR −1.19 pp, bootstrap p=0.999, dosis-respuesta monótona: cuanto más
agresivo el gate, peor) — el gate apuntaba al régimen equivocado. Esa corrida fue INVÁLIDA por sanity y
no produjo veredicto, pero **no hay ninguna hipótesis viva que diga que condicionar esta señal a
régimen ayude**, así que el candidato de esta tarea es el brazo **ungated**.

---

## 2. Brazos (CONGELADO)

**Población A — el marco de la T11b (*"¿hay señal?"*).** La grilla de 9 brazos `(k, m)` intacta:

| brazo | k | m | rol |
|---|--:|--:|---|
| `A_k1.5_m1.5`, `A_k1.5_m2.0`, `A_k1.5_m3.0` | 1.5 | 1.5 / 2.0 / 3.0 | alimentan DSR/PBO (C4) |
| **`A_k2.0_m1.5`** | **2.0** | **1.5** | **CANDIDATO — congelado (§0.4)** |
| `A_k2.0_m2.0` | 2.0 | 2.0 | primario histórico de la T11b (descriptivo) |
| `A_k2.0_m3.0`, `A_k2.5_m1.5`, `A_k2.5_m2.0`, `A_k2.5_m3.0` | | | alimentan DSR/PBO (C4) |
| `AZAR_TIME_MATCHED` | — | — | **BASELINE** — K=500 carteras, matcheadas al **candidato** |
| `V_oracle_entry` | — | — | sanity: mejores entradas operables por retorno realizado |

**Población B — el marco vivo (*"¿le aporta al engine?"*), NUEVA.** Sobre las **mismas** barras,
señales PIT, universo, slots y config:

| brazo | qué es |
|---|---|
| **`E_analyze`** | **BASELINE de C8 — los `analyze BUY` solos: la fuente de candidatos que el engine usa hoy** |
| **`E_analyze+anom`** | **CANDIDATO de C8** — la unión de `analyze BUY` **+** las entradas de `A_k2.0_m1.5`, por el **mismo pipeline** (empate del día resuelto alfabéticamente, como hoy) |
| `E_analyze+anom_PRIO` | **descriptivo obligatorio** — idem pero el candidato de anomalía **gana el slot** en su día |

El descriptivo priorizado existe por una razón declarada: si `E_analyze+anom` no se mueve, hay que
poder distinguir **"la señal no aporta"** de **"la señal nunca consigue un slot"** (con ~143k
candidatos `analyze` para 10 slots, la cola está saturada y el desempate alfabético decide — T21/T39).
**No es un gate** y no puede reemplazar al primario después de ver los números.

---

## 3. Población y config (CONGELADO)

- **Universo:** `data/harness_universe_live_acct2.txt` (**127 tickers** con artefacto PIT), período
  `10y`, `warmup=250`.
- **`max_positions=10`** para el veredicto; **5** para C7. `initial_capital=50.000`, `cap_days=20`,
  `AtrParams()` default, `ScaleOutParams()`, `CostModel()`, `allow_reentry_while_open=False`.
- **`eval_mode="touch"`** (la regla que ejecuta el engine, 26b) + **`fill_mode="decision"`** (el fill
  honesto, T33) + **`live_gates=True`** (los gates de re-entrada del engine, T34). **La T11b no tenía
  ninguno de los tres**; la 38 los midió juntos y **no mueven el perfil de régimen** (A→B y C→D
  mantienen el signo de las cuatro ventanas), sólo el nivel.
- **`live_gates=True` también en C8, y ahí hace falta de verdad:** las dos fuentes producen ciclos con
  tasas de cierre distintas, así que Gate 5 / 5b **no son un nivel común** y no pueden darse por
  cancelados (criterio de la T33).
- **K = 500** carteras Monte Carlo, `seed=12345`, a 10 y a 5 slots.
- **Desvíos declarados que siguen vivos:** survivorship (127 sobrevivientes de **hoy** — no eran la
  watchlist en 2016); ventana de `analyze()` expandida (250 → ~2.514 barras) vs 504 fijas del engine;
  sin overlay T20 (atribución limpia, igual que la T11b); volumen de yfinance sin ajustar por splits
  (mitigado por diseño: la condición de precio del detector no dispara con un split); y **la ventana
  rodante de los artefactos (tarea 48)**, que es la que obliga al §5.3 a ser como es.

---

## 4. El criterio de régimen nuevo (CONGELADO) — lo único que se reemplaza

**C5′ reemplaza al §6.5 de la T11b** (*"ret medio por trade ≥ 0 en cada uno de los 4 regímenes"*), que
la 46 midió con **5,0% de potencia** en esta población.

**Tres partes, y las tres se computan de la muestra:**

1. **La tolerancia se calcula, no se elige:**
   `tol = max(TOL_MATERIAL, detectable_mean_effect(σ, n))` sobre los trades del **candidato** en la
   ventana, con **`TOL_MATERIAL = 1.00 pts`** — **el mismo valor que congeló la 47**, no re-elegido
   para esta población. Con lo que midió la 46 (`stress_POOLED`: n=106, σ=6.80) la tolerancia efectiva
   va a salir **±1.85**, o sea que manda lo detectable, no el material.
2. **El gate va sobre el AGREGADO de las tres ventanas de stress** (`stress_POOLED`), que es donde hay
   `n`, y **contra el control time-matched**, no contra cero. Δ = (media pts/trade del candidato en
   stress) − (media pts/trade del **azar time-matched** en stress, agrupando los trades de las K
   carteras). **Falla sólo si el IC95% del Δ está enteramente por debajo de −tol** (2000 resamples,
   `seed=12345`, `_delta_samples` — remuestreo independiente de cada lado, que es lo correcto acá
   porque los brazos no comparten trades).
   - **Por qué contra el control y no contra cero:** un nivel negativo en una ventana de stress habla
     del **mercado**, no de la señal (lección explícita de la 46 §3). El control time-matched es
     justamente el que cancela el mercado. Rechazar por el nivel sería medir 2018.
   - **Nota sobre la incertidumbre:** el control tiene ~500× más trades que el candidato, así que su
     media está estimada con precisión y la incertidumbre del Δ viene, correctamente, del candidato.
3. **Las cuatro ventanas individuales son descriptivo OBLIGATORIO**, con `n`, σ, detectable, IC95% y
   `P(signo)` al lado. Se reportan siempre y **no pueden por sí solas producir un rechazo**.

Se reporta además la versión de **cartera** por ventana (`regime_window_returns`) como segundo
descriptivo, porque es la que usan la 38 y la 39 — pero **no es el gate**: la 46 midió que su P(signo)
por ventana es 58-92%, tampoco suficiente.

---

## 5. Sanity del instrumento (si falla alguno, la corrida es INVÁLIDA y no hay veredicto)

1. **Contabilidad:** `|equity_curve[-1] − final_equity| / final_equity ≤ 1e-6` en **todos** los brazos
   de las dos poblaciones.
2. **El oráculo despega:** `V_oracle_entry` supera al candidato por ≥ **+20.00 pp** de CAGR (la 38
   midió +93,57 pp). Si el harness no ve calidad de entrada, ningún veredicto vale.
3. **Reproducción, en dos patas** — y acá hay que ser explícito sobre por qué **no** se usan los
   números publicados por la T11b:
   - **(a) config viva:** `A_k2.0_m1.5` da **9.23%** de CAGR (±0.05 pp), que es el `U_ungated` que la
     **38** midió el 2026-08-19 sobre **los mismos artefactos** que hay hoy (refrescados el
     2026-08-09, verificado por mtime). Ésta es la pata que importa: es exactamente el path que la
     tarea decide.
   - **(b) config legacy:** con `--max-positions 5 --universe data/harness_universe_41_10y.txt
     --fill-mode resting`, `A_k2.0_m1.5` da **12.77%** y Sharpe **1.22** (±0.05 pp / ±0.02).
     **Ojo: la T11b publicó 12.89% y 1.24.** No es un error de este pre-registro ni una cañería rota:
     es la **ventana rodante** de la tarea 48 — los artefactos se refrescaron el 2026-08-09, la
     ventana pasó a `2016-08-08..2026-08-07` y **los nueve brazos perdieron 1-3 entradas**. El
     12.77% se **midió el 2026-08-20 antes de congelar este documento**, precisamente para no congelar
     un sanity que no puede pasar. Queda declarado como tal.
   - Si cualquiera de las dos no reproduce, cambió algo en la cañería y nada de lo que siga es
     comparable.

**Lo que NO es un sanity, y es a propósito:** *"la anomalía consigue slots en `E_analyze+anom`"*. Que
la fuente nueva gane o no gane slots **es un resultado**, no una propiedad del instrumento — es la
mitad de la respuesta a C8. La 38 pagó una corrida entera por confundir las dos cosas (su §5.4 pedía
que *"el gate mordiera"* midiéndolo con una métrica que por construcción daba 0). Acá el desempate se
reporta como número y se interpreta con el descriptivo priorizado del §2.

---

## 6. Regla de decisión (CONGELADA)

**Candidato** = `A_k2.0_m1.5` (congelado, §0.4). 10 slots, config viva. Se cablea **sólo si pasa las
ocho**:

| # | Criterio | Umbral | origen |
|---|---|---|---|
| C1 | CAGR **y** Sharpe del candidato > **p95** del azar time-matched | los dos | §6.1 T11b, intacto |
| C2 | ΔCAGR vs la **mediana** del azar | ≥ **+2.00 pp** | §6.2 T11b, intacto |
| C3 | maxDD ≤ **1.5 ×** la mediana del maxDD del azar | | §6.3 T11b, intacto |
| C4 | **DSR > 0.5** y **PBO < 0.5** sobre los 9 brazos | los dos | §6.4 T11b, intacto |
| **C5′** | **régimen con potencia** (§4): IC95% del Δ del candidato vs el azar en `stress_POOLED` | **no enteramente < −tol** | **reemplaza §6.5** |
| C6 | **LOTO**: sacar el ticker de mayor aporte no baja el CAGR por debajo de la mediana del azar | | §6.6 T11b, intacto |
| **C7** | **sensibilidad a 5 slots: C1 y C2 se mantienen** | **los dos** | **nuevo** (precedente 47) |
| **C8** | **additividad sobre el engine**: `E_analyze+anom` vs `E_analyze` — ΔCAGR ≥ **+0.50 pp** **y** bootstrap pareado sobre Δ(retorno diario), bloques 20 d, 2000 resamples, **IC95% inferior > 0** | **los dos** | **nuevo** |

**Casos partidos, resueltos ex ante:**

- **Pasa todo menos C8** → **NO-SHIP**, y el doc tiene que decir **cuál de las dos cosas pasó**: si el
  descriptivo priorizado muestra que con slot la señal **sí** aporta, el hallazgo es *"la señal vale
  pero no hay mecanismo que le dé prioridad"* y **abre una tarea** sobre ese mecanismo (que es de la
  familia de la 21/39 y no se resuelve acá). Si aporta poco **incluso priorizada**, el hallazgo es que
  el alpha de la T11b **no sobrevive a competir con la fuente que ya existe**, y eso cierra la
  pregunta.
- **Pasa todo menos C7** → **NO-SHIP.** Está declarado ex ante que un efecto que sólo existe con 10
  slots es **frágil**. Se reportan los dos slots.
- **Pasa todo menos C5′** → **NO-SHIP**, y esta vez el rechazo **sí significa algo**: querría decir que
  el IC entero del Δ contra el control en el agregado de stress está del lado malo de una tolerancia
  detectable.
- **C5′ pasa pero alguna ventana individual se ve fea** → **no bloquea** (§4.3). Se reporta con su `n`,
  su detectable y su IC, y se dice explícitamente que no tiene potencia para decidir.
- **La regla de la T11b re-seleccionaría otro brazo sobre la población viva** → **no cambia el
  candidato** (§0.4). Se reporta como hallazgo de inestabilidad del criterio de selección.
- **Falla cualquier sanity del §5** → **corrida INVÁLIDA**, sin veredicto, y **no se re-especifica nada
  para salvarla** (precedente T26; la T34 y la 38 ya pagaron una cada una).

---

## 7. Qué se cablea si pasa / qué NO se toca

- **Si pasa las ocho:** flag `paper_anomaly_entries_enabled` (default **OFF**, o sea sin cambio de
  comportamiento) + `paper_anomaly_k` / `paper_anomaly_m` con los valores validados (2.0 / 1.5),
  inyectando los candidatos en el pipeline de BUY por los mismos gates y screen que cualquier otro
  (que es lo que declaró la T11b §6). **Toca decisiones vivas de ENTRADA**, así que se avisa
  explícitamente y **prenderlo es decisión de Chapa**, no del veredicto. El rollback es una línea.
- **Qué NO se toca aunque pase:** el gate de régimen sobre esta señal (la 38 midió que destruye valor);
  el ranking / desempate del día (es la 21/39); el sizing; las salidas (stop, TP, trailing); el
  overlay T20, que sigue activo y que el candidato heredaría en producción.
- **Si no pasa:** NO-SHIP documentado, el engine intacto, el detector sigue como enabler y feature del
  meta-modelo futuro, y queda escrito **cuál** criterio lo frenó y **con cuánta potencia** — que es
  justamente lo que faltaba la primera vez.

---

## 8. Qué NO se modela (caveats antes de correr)

- **El bracket de `eval_mode`:** el engine samplea c/15 min, así que está **entre** `close` y `touch` y
  más cerca de `touch`. Se corre en `touch`, que es la cota fiel; ninguno de los dos ES producción.
- **Survivorship:** 127 tickers que sobreviven **hoy**, y que además son la watchlist de hoy, no la de
  2016. Común a todas las poblaciones y brazos, y sesga el **nivel** hacia arriba en los dos lados de
  C8.
- **Ventana de `analyze()`** expandida: común a todos los brazos, afecta el nivel.
- **Ventana rodante de los artefactos (tarea 48):** los números de esta corrida son reproducibles
  mientras no se refresquen los parquet. Queda anotado con la ventana efectiva.
- **Sin overlay T20** (sizing por régimen), igual que la T11b, por atribución limpia. En producción el
  candidato lo heredaría.
- **Sin screen de universo E1b:** el sourcing de nombres fuera de watchlist es concern de producción.
- **Márgenes, apalancamiento, dividendos, intradía:** fuera de alcance de `portfolio_sim`.

---

## 9. Plan de ejecución

1. **Enabler:** `random_baseline` de `run_anomaly_replay_t11b.py` pasa a devolver también los
   **retornos por trade por régimen** de las K carteras (hoy sólo devuelve CAGR/Sharpe/maxDD), que es
   lo que C5′ necesita como control. Sin cambio de default para nadie.
2. **Runner** `scripts/run_anom_profile_t45.py`: reusa la carga, la grilla, el MC, el oráculo y el
   LOTO de la T11b; agrega C5′ (§4), C7 (corrida a 5 slots), C8 (población B con sus tres brazos), los
   dos sanity de reproducción y el AND de los ocho.
3. **Tests offline:** el AND de los ocho y **cada** caso partido del §6; que la tolerancia de C5′ se
   **computa** (no es constante) y crece cuando la muestra se achica; que una ventana individual fea
   **no** bloquea; que el merge de la población B **deduplica** `(ticker, idx)` y respeta el orden
   cronológico; que el brazo priorizado no cambia el conjunto de candidatos, sólo el orden del día.
4. **Correr** a 10 slots + la sensibilidad a 5 + las dos reproducciones, sin red y sin tocar
   `finanzias.db`.
5. **Veredicto** en `docs/anom_profile_t45_<fecha>.md`, con **el Δ contra el control en el agregado de
   stress y su IC al frente**, el resultado de C8 al lado, y la comparación explícita contra lo que la
   T11b decidió y por qué.

**Congelado. Cualquier cambio a §2–§7 después de ver un resultado invalida el pre-registro.**
