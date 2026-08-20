# Pre-registro CONGELADO — Re-decidir contra qué precio se decide la barrera (Tarea 47, STOP-PRICE-REDECIDE)

**Fecha:** 2026-08-19 · **Estado:** congelado ANTES de codear.
**Ref:** `docs/BACKLOG.md` tarea 47 · `docs/stop_price_t26b_2026-08-16.md` (el veredicto que se
re-decide) · `docs/stop_price_prereg_t26b_2026-08-14.md` (población y brazos, que se **reusan
intactos**) · `docs/regime_power_t46_2026-08-19.md` (por qué se re-decide) ·
`docs/stop_loosen_t34_2026-08-18.md` (el enabler `live_gates`).

---

## 0. La parte incómoda, primero: esto **no es una corrida a ciegas**

**Los resultados de la 26b ya están publicados y yo los conozco al escribir esto.** `close_2.0` le
ganó a `touch_2.0` por **+3.39 pp** de CAGR con **−4.88 pp** de maxDD y bootstrap **[+0.03, +6.30]
p=0.024**, pasó **C1-C4 y C6**, y cerró NO-SHIP por **C5 solo**. Re-abrirla cambiando justo el
criterio que la frenó es, si no se toma ningún recaudo, **la definición de elegir el resultado**.

Los cuatro recaudos, declarados acá:

1. **El motivo para cambiar C5 es ajeno a esta tarea y anterior a ella.** La 46 midió la potencia del
   criterio sobre **otra** pregunta (disparada por la 38, que ni siquiera es de salidas) y encontró
   **5,1%** para la tolerancia de ±0.05 pts — o sea α. No se cambió el criterio porque frenara a la
   26b; se cambió porque **no discrimina nada**, y la 26b es una de las cuatro que rechazó.
2. **El criterio nuevo no se elige: se computa.** La tolerancia sale de
   `detectable_mean_effect(σ, n)` sobre la muestra, no de un número puesto a dedo. Nadie puede
   ajustarlo para que pase.
3. **Se AGREGAN criterios, no sólo se reemplaza uno.** Entra como gate duro la sensibilidad a 5 slots
   —**que la 26b ya midió y donde FALLA** (C3 con IC [−0.40, +8.88])— y se modelan los **gates de
   re-entrada** del engine, que la 26b no tenía. Las dos cosas hacen la prueba **más** exigente, no
   menos, y las dos están declaradas sabiendo que empujan hacia NO-SHIP.
4. **El resultado esperado está escrito de antemano: es plausible que esto vuelva a cerrar NO-SHIP**,
   y eso sería un éxito de la tarea, no un fracaso. Lo que se busca es **decidir con un criterio que
   tenga potencia**, no llegar a un veredicto en particular.

**Lo que NO se toca del diseño de la 26b:** población, brazos, múltiplos, sanity, C1, C2, C3, C4 y C6
quedan **idénticos**. Si se tocara algo más, esto no sería una re-decisión: sería una tarea nueva
disfrazada.

## 1. La pregunta (sin cambios respecto de la 26b)

El engine decide **toda** salida ATR contra el **precio corriente intradía** (`get_bulk_prices`, scan
~15 min). El harness puede decidirla al **close diario** (`close`) o al **toque del extremo de la
barra** (`touch`). Son **dos reglas distintas**, no dos calibraciones.

> **¿Conviene que el engine confirme la barrera al cierre en vez de dispararla al toque?**

Con el fill honesto (T33) la 26b midió que sí, por +3.39 pp de CAGR, y no lo cableó por un criterio
que la 46 mostró sin potencia. **Esta tarea lo vuelve a decidir con un criterio que discrimina.**

## 2. Brazos (CONGELADO — los mismos de la 26b)

Rejilla **2 modos × 5 múltiplos**: `touch_{1.0, 1.5, 2.0, 2.5, 3.0}` y `close_{…}` idem.

| brazo | qué es |
|---|---|
| **`touch_2.0`** | **BASELINE — la regla que el engine ejecuta hoy**, al múltiplo vivo |
| **`close_2.0`** | **CANDIDATO** — misma calibración, la otra regla de decisión |
| los otros 8 | alimentan C6 (consistencia del signo a través del múltiplo) |
| `ORACULO_STOP` | sanity: elige qué stops saltear mirando el futuro |
| `AZAR_MISMA_TASA` | sanity: control **igualado en tasa** de stops (lección T26) |

## 3. Población y config (CONGELADO)

- **Universo:** `data/harness_universe_live_acct2.txt` (127 tickers), **143.096 entradas
  `analyze BUY`** PIT. `cap_days=250`, `CostModel()`, `allow_reentry_while_open=False`.
- **`fill_mode="decision"`** (el honesto, T33) — igual que la 26b.
- **`max_positions=10`** para el veredicto; **5** para C7.
- **`live_gates=True` — ESTO ES NUEVO y hay que justificarlo.** La 26b corrió sin los gates de
  re-entrada del engine. El criterio que dejó la T33 dice que un desvío se cancela como nivel común
  **sólo si los brazos no difieren en la tasa que lo alimenta**, y acá **difieren mucho**: `touch_2.0`
  dispara stop en el **19,9%** de los ciclos y `close_2.0` en el **13,4%**. Distinta tasa de cierre ⇒
  distinta exposición a Gate 5 (que bloquea el re-BUY tras un ciclo perdedor reciente). **No es un
  nivel común y no puede darse por cancelado.** Es el mismo razonamiento por el que la T34 lo modeló
  adentro.
- **Desvíos que siguen vivos y quedan declarados:** ventana de `analyze()` expandida (250 →
  ~2.514 barras) vs 504 fijas del engine; survivorship de 127 sobrevivientes; y el **bracket**: el
  engine samplea c/15 min, así que está **entre** los dos modos y **más cerca de `touch`** — ninguno
  de los dos ES producción, lo acotan.

## 4. El criterio de régimen nuevo (CONGELADO) — lo único que cambia

Reemplaza al C5 de la 26b (*"Δ ret/trade ≥ −0.05 pts en cada uno de los 4 regímenes"*), que la 46
midió con **5,1% de potencia**.

**C5′ tiene tres partes, y las tres se computan de la muestra:**

1. **La tolerancia se calcula, no se elige:**
   `tol = max(TOL_MATERIAL, detectable_mean_effect(σ, n))` por ventana, con
   **`TOL_MATERIAL = 1.00 pts`** por trade — declarado acá, y elegido por ser del orden de lo
   detectable en la ventana con más datos (`bear_2022`: ±0.97 con n=251), **no** por lo que le
   convenga al candidato.
2. **El gate va sobre el AGREGADO de las tres ventanas de stress** (`stress_POOLED`, n=407 en esta
   población, detectable ±0.95): falla si el **IC95%** del Δ (bootstrap de 2000 resamples,
   `seed=12345`) está **enteramente por debajo de −tol**. O sea: se rechaza **con evidencia**, no con
   un punto estimado que cae del lado feo de cero.
3. **Las cuatro ventanas individuales son descriptivo OBLIGATORIO**, con `n`, IC95% y `P(signo)` al
   lado. Se reportan siempre y **no pueden por sí solas producir un rechazo**.

**Se reporta también la versión de cartera** (`regime_window_returns` + `block_delta_sign_stability`,
pareada) como segundo descriptivo, porque es la que usan la T38 y la T39 — pero **no es el gate**: la
46 midió que su P(signo) por ventana es 58-92%, tampoco suficiente.

## 5. Sanity del instrumento (si falla alguno, la corrida es INVÁLIDA y no hay veredicto)

Los tres de la 26b, **sin cambios** (los tres pasaron allá):

1. **Contabilidad:** `|equity_curve[-1] − final_equity| / final_equity ≤ 1e-6` en todos los brazos.
2. **El instrumento ve calidad de stop:** `ORACULO_STOP` supera al **control igualado en tasa**
   (`AZAR_MISMA_TASA`) por ≥ **2.00 pp** de CAGR. *(Lección T26: el umbral va contra el control
   igualado, no contra el baseline.)*
3. **La regla muerde:** ≥ **10%** de los trades difieren entre `touch_2.0` y `close_2.0`
   (la 26b midió **50,1%** — media cartera).

Y uno nuevo, por el cambio de config:

4. **Reproducción:** con `--live-gates` apagado, `close_2.0` da **7.80%** y `touch_2.0` **4.41%**
   (±0.05 pp), los números publicados por la 26b. Si no reproduce, cambió algo en la cañería y nada
   de lo que siga es comparable.

## 6. Regla de decisión (CONGELADA)

**Candidato** = `close_2.0`. **Baseline** = `touch_2.0`. 10 slots. Se cablea **sólo si pasa las
siete**:

| # | Criterio | Umbral | *(medido por la 26b sin gates)* |
|---|---|---|---|
| C1 | ΔCAGR | ≥ **+0.50 pp** | +3.39 pp |
| C2 | maxDD | ≤ base + **2.00 pp** | −4.88 pp |
| C3 | bootstrap pareado sobre Δ(retorno diario), bloques 20 d, 2000 resamples | **IC95% inferior > 0** | [+0.03, +6.30] |
| C4 | Sharpe | ≥ base − **0.05** | +0.164 |
| **C5′** | **régimen con potencia** (§4): IC95% del Δ en `stress_POOLED` | **no enteramente < −tol** | *criterio nuevo* |
| C6 | consistencia del signo a través de los 5 múltiplos | ≥ **3/5** | 4/5 |
| **C7** | **sensibilidad a 5 slots: C1 y C3 se mantienen** | **los dos** | **C3 FALLA allá** |

**Casos partidos, resueltos ex ante:**

- **Pasa todo menos C7** → **NO-SHIP.** Es el desenlace más probable dado lo que la 26b ya midió, y
  está declarado así a propósito: si el efecto sólo existe con 10 slots, es **frágil**, y cablear una
  regla de salida frágil en la cuenta viva no se hace. Se reporta el número de los dos slots.
- **Pasa todo menos C5′** → **NO-SHIP**, y esta vez el rechazo **sí significa algo**: querría decir
  que el IC entero del agregado de stress está del lado malo de una tolerancia detectable.
- **C5′ pasa pero alguna ventana individual se ve fea** → **no bloquea** (§4.3). Se reporta con su `n`
  y su IC, y se dice explícitamente que no tiene potencia para decidir.
- **Falla cualquier sanity del §5** → **corrida INVÁLIDA**, sin veredicto, y no se re-especifica nada
  (precedente T26; la T34 y la 38 ya pagaron una cada una).
- **El resultado cambia de signo respecto de la 26b sólo por `live_gates`** → se reporta como el
  hallazgo principal y **el veredicto es el de la config con gates**, que es la fiel al engine.

## 7. Qué se cablea si pasa / qué NO se toca

- **Si pasa las siete:** flag `paper_atr_confirm_at_close` (default **OFF**, o sea sin cambio de
  comportamiento) cableado en el evaluador de barreras del engine. **Toca decisiones vivas de
  salida**, así que se avisa explícitamente y **la decisión de prenderlo es de Chapa**, no del
  veredicto. El rollback es una línea.
- **Qué NO se toca aunque pase:** el múltiplo (`atr_stop_mult` queda en 2.0 — es la pregunta de la 34
  y la 37, no ésta); el trailing; el take-profit; el sizing; el ranking.
- **Si no pasa:** NO-SHIP documentado, el engine intacto, y queda escrito **cuál** criterio lo frenó y
  con cuánta potencia — que es justamente lo que faltaba la primera vez.

## 8. Qué NO se modela (caveats antes de correr)

- **El bracket:** el engine samplea c/15 min. `touch` **sobre-dispara** y `close` **sub-dispara**
  respecto de producción; la respuesta real está en el medio y más cerca de `touch`. **Ninguno de los
  dos brazos es el engine** — por eso el candidato, si pasa, entra detrás de un flag y apagado.
- **Survivorship:** 127 sobrevivientes. Común a todos los brazos.
- **Ventana de `analyze()`** expandida: común a todos los brazos, afecta el nivel.
- **Sin overlay T20** (sizing por régimen), igual que la 26b, por atribución limpia.

## 9. Plan de ejecución

1. **Enabler:** `--live-gates` en `scripts/run_stop_price_replay_t26b.py` (default OFF, preserva el
   veredicto publicado), mismo patrón que el que la 38 y la 39 agregaron a sus runners.
2. **Runner** `scripts/run_stop_price_redecide_t47.py`: reusa los brazos y la carga de la 26b, agrega
   C5′ (`detectable_mean_effect` + `sign_stability` sobre el agregado de stress), C7 (corrida a 5
   slots), el sanity de reproducción y el AND de los siete.
3. **Tests offline:** el AND de los siete y **cada** caso partido del §6; que la tolerancia de C5′ se
   **computa** (no es constante) y que crece cuando la muestra se achica; que una ventana individual
   fea **no** bloquea.
4. **Correr** a 10 slots + sensibilidad a 5 + la corrida de reproducción, sin red, sin tocar
   `finanzias.db`.
5. **Veredicto** en `docs/stop_price_redecide_t47_<fecha>.md`, con **el Δ del agregado de stress y su
   IC al frente**, y la comparación explícita contra lo que la 26b decidió.

**Congelado. Cualquier cambio a §2–§7 después de ver un resultado invalida el pre-registro.**
