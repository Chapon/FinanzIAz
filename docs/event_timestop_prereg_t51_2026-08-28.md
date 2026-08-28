# Pre-registro CONGELADO — El tope de tenencia, y si es del EVENTO (Tarea 51, EVENT-TIMESTOP)

**Fecha:** 2026-08-28 · **Estado:** congelado ANTES de codear.
**Ref:** `docs/BACKLOG.md` tarea 51 · `docs/prio_event_t49_2026-08-20.md` §2 (de dónde sale el lead) ·
`docs/ent1_t13_2026-08-12.md` §2 y `docs/ent1_prereg_t13_2026-08-12.md` §6.3 (el brazo del time stop
y su sanity de población, que se **reusa tal cual**) · `docs/anom_profile_t45_2026-08-20.md` §3 (el
descriptivo de +4.21 pp y el detector) · `docs/prio_event_prereg_t49_2026-08-20.md` (el molde del
control **igualado en tasa**, que se reusa) · `docs/regime_power_t46_2026-08-19.md` §4 (el criterio de
régimen con potencia) · `docs/stop_value_t37_2026-08-27.md` §6 (el walk-forward de la selección) ·
`docs/repro_pop_t52_2026-08-28.md` (los sanity de reproducción declaran ventana **y** población).

---

## 0. La parte incómoda, primero: **dos premisas del enunciado son falsas**

**Conozco el número que motiva la tarea al escribir esto.** El descriptivo de la 45 da **+4.21 pp**
(3.71% → 7.92%) con `cap_days=20`, y la 49 midió que a la tenencia del engine (`cap_days=250`) el
mismo candidato de turno da **0.51%** contra **3.23%** — el efecto se da vuelta entero. De ahí la
hipótesis: no era *cuándo entra* sino **cuánto se lo sostiene**.

Antes de diseñar nada hay que decir esto, porque cambia la tarea:

**(1) `cap_days` y `time_stop_days` NO son la misma regla.** Son dos ramas distintas de
`replay_cycle`:

| | qué hace | cuándo | a quién cierra | motivo del leg |
|---|---|---|---|---|
| **`cap_days`** (`scaleout_replay.py:385-388`) | cierra el remanente al close | al llegar a la barra `entry_idx + N` | **a todos** — ganadores incluidos | `cap_reached` |
| **`time_stop_days`** (`scaleout_replay.py:371-383`) | cierra el remanente al close | chequeo de **una sola vez** en la barra N | **sólo si está en pérdida** (`net_if_closed <= entry_cost`) | `time_stop` |

El **+4.21 pp vive en `cap_days=20`**, o sea en un tope **duro e incondicional** que corta también a
los que van ganando. La T13 midió la **otra** regla.

**(2) La T13 no refutó nada: cerró «sin población».** Su brazo (b) falló el sanity §6.3 —de los
trades del baseline, sólo el **0,5%** era alcanzado por el time stop, contra un umbral pre-registrado
de **≥5%**— y el propio veredicto lo reporta como *"el brazo está **sin poder**, no refutado"*
(`docs/ent1_t13_2026-08-12.md` §2). Sus deltas (ΔCAGR −0.22 pp, IC95% [−0.78, +0.31], p=0.787) son
*"consistentes con «no pasa nada», que es lo que se espera de una regla que casi nunca se ejecuta"*.
Y corrió sobre la config vieja: **5 slots, 41 tickers**.

**Qué le pasa entonces a la advertencia del enunciado** (*"si el pre-registro no puede explicar por
qué el condicionamiento cambia algo que incondicional ya falló, la tarea no vale la pena"*): **se
apoya en una premisa falsa por partida doble.** El incondicional **no falló** — no se midió con
poder, y además la regla que se midió no es la que produjo el número. La respuesta honesta a la
advertencia no es *"el condicionamiento rescata al incondicional"*: es que **el incondicional es la
pregunta que falta, y es la primera**.

Anotado como hallazgo → **tarea 57** en el backlog, con la corrección al enunciado de la 51 y a la
hipótesis derivada del §2 de la 49.

**(3) Y una consecuencia de diseño, declarada acá para que no sea un rescate post-hoc:** si el efecto
resulta ser del **tope** y no del **evento**, el candidato que shipearía es el tope incondicional —
que es un brazo distinto del que el enunciado imaginaba. Por eso este pre-registro declara **dos
candidatos con jerarquía** (§6), no uno: el condicional tiene que ganarle al incondicional, no sólo
al baseline. Declararlo antes de correr es lo que impide elegir el ganador después de verlo
(regla 2).

---

## 1. La pregunta

Tres preguntas anidadas, en este orden:

- **Q1 — ¿El tope de tenencia hace algo?** ¿Un cap duro de N ruedas mejora la cartera **viva** (127
  tickers, 10 slots, `touch`/`decision`/`live_gates`) contra el engine de hoy, que efectivamente no
  tiene tope (`cap_days=250`, y la T13 midió `cap_reached` en 0,38%)?
- **Q2 — ¿Es del EVENTO o de cualquier posición?** Si Q1 da que sí, ¿el efecto sobrevive cuando el
  mismo tope se aplica a un subconjunto **aleatorio igualado en tasa**? Es la lección de la T26 y el
  molde exacto que hizo concluyente a la 49.
- **Q3 — ¿Hay dosis-respuesta, o es un pico en 20?** Si el efecto es real tiene que haber **gradiente
  en N**. Un pico aislado en el mismo 20 que motivó la tarea es la firma del sobreajuste, no del
  mecanismo.

**El mecanismo que se postula:** un edge de ruptura de momentum está **al frente** y se drena si se
lo sostiene; con slots finitos, sostener una posición drenada cuesta además el **costo de oportunidad
del slot** (ratio de selección ~55:1 en esta población). El tope corto cosecha el primero por la
fuerza y libera el segundo. Si el mecanismo es ése, **no tiene por qué ser exclusivo del evento** —
y por eso Q2 es un gate y no un descriptivo.

---

## 2. Brazos (CONGELADO)

**Grilla del tope:** `N ∈ {10, 15, 20, 30, 40, 60}` ruedas, más `N = 250` (el engine, sin tope
efectivo) como **BASELINE**.

**Tres familias**, que cruzan el tope con *a quién se le aplica*:

| familia | brazos | qué capa |
|---|---|---|
| **`B_base`** | 1 | nada — `cap_days=250`, el engine de hoy. **BASELINE.** |
| **`U_N`** (incondicional) | 6 | el cap N a **todas** las posiciones. **CANDIDATO B.** |
| **`E_N`** (condicional al evento) | 6 | el cap N **sólo** a las posiciones cuya entrada `(ticker, fecha)` también es entrada del detector de anomalía. **CANDIDATO A.** |
| **`C_N*_k`** (control igualado en tasa) | 20 semillas | el cap N* a un subconjunto **aleatorio** de entradas candidatas: mismos días, **misma cantidad por día** que `E_N*`. Sólo en el `N*` elegido por walk-forward (costo de cómputo declarado). |

**El evento** es el detector congelado `A_k2.0_m1.5` (`analysis/anomaly_signal.py`, el brazo que la
45 dejó como enabler), **restringido al pool del engine** con `restrict_to_pool` (T49 §2): el
candidato **no agrega candidatos nuevos**, sólo cambia cuánto se sostiene lo que el engine ya iba a
abrir. Agregar pool es lo que la 45 rechazó por C8 y acá queda explícitamente afuera.

**El control se construye con `rank_policy.rate_matched_priority(cands_by_date, n_by_date, seed)`** —
el enabler de la 49, sin tocar: le da el conjunto de claves `(ticker, fecha)` elegidas al azar en la
misma cantidad por día que el evento. Es puro (depende sólo de `(semilla, fecha, ticker)`).

**Brazos de sanity (§5), igualados en tasa:**

- **`ORACULO_cap`** — capa al `N*` las posiciones que **peor** terminan, en la misma cantidad por día
  que `E_N*`. Tiene que despegar.
- **`ANTI_ORACULO_cap`** — capa las que **mejor** terminan, misma tasa. Tiene que hundirse.

(Lección de la T26/T44 registrada en la skill: un oráculo tiene que poder moverse **en las dos
direcciones** del eje, y su umbral va contra un **control igualado**, no contra el baseline.)

**Descriptivo obligatorio, NO gate — la descomposición que a la 49 le faltó:** el 2×2
`{fondo alfabético, fondo buy_score} × {cap 20, cap 250}` sobre el pool del engine. La 49 no puede
separar cuánto del vuelco del +4.21 pp es el `cap_days` y cuánto el cambio de fondo; lo único aislado
limpio es que **sólo `cap_days`** le cuesta **−1.70 pp** al brazo alfabético. Estos cuatro brazos
cierran la atribución. **No pueden promoverse a candidato** (regla 2).

---

## 3. Población y config (CONGELADO)

- **Universo:** `data/harness_universe_live_acct2.txt` (**127 tickers**). Correr sobre otro ⇒ smoke,
  sin veredicto.
- **Slots:** `max_positions=10` (la cuenta 2). Capital inicial 50.000. `allow_reentry_while_open=False`.
- **Regla de salida:** `eval_mode="touch"` (26b) · `fill_mode="decision"` (T33) · `live_gates=True`
  (T34). Los mismos tres que congelaron la 39, la 45, la 47 y la 49.
- **Entradas:** `analyze BUY` PIT (`buy_entries`), fondo de orden `buy_score` (`B1_score`) — el
  desempate que la 39 y la 49 dejaron vivo.
- **Costos:** `CostModel()` (comisión 0.1% + slippage 0.05% en las dos puntas).
- **`time_stop_days` queda en `None` en todos los brazos.** La regla bajo prueba es el **cap duro**;
  mezclar las dos volvería a confundirlas, que es justo el hallazgo del §0.
- **Ventana y población declaradas** en el banner y en los sanity de reproducción
  (`artifact_window` + `cfg.population(len(entries))`, tareas 48 y 52).

---

## 4. Dosis-respuesta (CONGELADO) — el criterio que el enunciado pide

Sobre la grilla `N ∈ {10, 15, 20, 30, 40, 60}`, la curva de **ΔCAGR vs el baseline** tiene que
cumplir **las dos** condiciones:

1. **Unimodal** — una sola subida y una sola bajada al recorrer N (empates dentro de **±0.20 pp** no
   cuentan como cambio de dirección). Un óptimo interior es esperable —el tope corta ganadores si es
   demasiado corto—, pero una curva que sube y baja varias veces es ruido.
2. **Sin pico aislado** — los **vecinos** de `N*` en la grilla conservan **≥50%** del ΔCAGR de `N*`.
   Si `N*` está en el borde de la grilla, alcanza con su único vecino.

**Si el efecto sólo existe en N=20** —el valor que motivó la tarea— **C6 falla y no shipea nada**,
por bueno que sea el número.

---

## 5. Sanity del instrumento (si falla alguno, la corrida es INVÁLIDA y no hay veredicto)

1. **Contabilidad** OK en todos los brazos (`accounting_ok`).
2. **Población del gate ≥ 5%** — el umbral de la T13, reusado tal cual. La fracción de trades del
   **baseline** que el cap del brazo alcanzaría (tenencia ≥ N) tiene que ser **≥5%**. Se mide por
   separado para `U_N*` y `E_N*`. Si no llega, ese brazo se reporta **«sin población»** —
   *sin poder, no refutado*—, exactamente como la T13, y **no** como un NO-SHIP.
3. **Reproducción** (tri-estado consciente de ventana y población, tareas 48 y 52), tolerancia
   ±0.05 pp:
   - `B_base` (fondo `buy_score`, cap 250) = **3.23%** — publicado por la 49 §0 y por la 39.
   - el descriptivo alfabético a cap 20 (`E_analyze` de la 45) = **3.71%** — publicado por la 49 §5.2.
4. **El instrumento ve topes BUENOS y MALOS:** `ORACULO_cap` > **p95** del control igualado y
   `ANTI_ORACULO_cap` < **mediana** del control.
5. **El tope muerde:** ≥**10%** de trades distintos entre `B_base` y el brazo candidato.
6. **Las semillas del control son efectivas:** ≥**10%** de trades distintos entre semillas (mediana
   de los pares), igual que la 39 y la 49.

---

## 6. Regla de decisión (CONGELADA)

**`N*` se elige por walk-forward**, no in-sample: cinco folds `(train, val, test)` de la T37
(2020-08→2026-07). El `N*` que dicta el veredicto es el que gana en **validación**; si difiere del
mejor in-sample, **manda el walk-forward**. La concordancia entre folds se reporta.

**Jerarquía declarada — primero B, después A contra B.**

### CANDIDATO B (`U_N*`, tope incondicional)

| # | Criterio | Umbral |
|---|---|---|
| **C1** | ΔCAGR vs `B_base` | ≥ **+0.50 pp** |
| **C3** | maxDD | ≤ base **+3.00 pp** |
| **C4** | block-bootstrap pareado vs `B_base` (bloque 20, 2000 resamples, semilla 12345) | IC95% inferior > **0** |
| **C6** | dosis-respuesta (§4) | las dos condiciones |
| **C7** | sensibilidad a **5 slots** | C1 y C4 se sostienen |
| **C8** | régimen con potencia (§4 de la 46): Δ vs base en `stress_POOLED` | IC95% **no entero** por debajo de **−1.00 pt** |

*(C2 y C5 no aplican a B: su "tasa" es el 100% y un control igualado en tasa sería el brazo mismo.)*

### CANDIDATO A (`E_N*`, tope condicionado al evento)

Todos los de B, **más**:

| # | Criterio | Umbral |
|---|---|---|
| **C2** | CAGR > **p95** de los 20 controles igualados en tasa | el criterio que mató a la 49 |
| **C5** | block-bootstrap pareado vs la serie **promedio** del control | IC95% inferior > **0** |
| **C9** | **A le gana a B**: ΔCAGR(A − B) ≥ **+0.50 pp** *y* bootstrap pareado IC95% inferior > **0** | si no, el efecto no es del evento |

**Qué shipea:**

- **A pasa todo** ⇒ el candidato es el tope **condicionado al evento**.
- **A falla C2, C5 o C9 pero B pasa lo suyo** ⇒ el candidato es el tope **incondicional**, y el
  hallazgo publicado es *"no era el evento, era la tenencia"*.
- **B falla C1 o C4** ⇒ **NO-SHIP los dos**, y la hipótesis del §1 queda refutada **con poder** (lo
  que la T13 no pudo hacer).
- **La población del §5.2 no llega al 5%** ⇒ **«sin población»**, sin veredicto para ese brazo.

**Descriptivos que NO son gate** (se publican con su costo de multiplicidad): DSR y PBO sobre la
grilla, el 2×2 de atribución del §2, la mezcla de motivos de salida por brazo y la tenencia por
percentil.

---

## 7. Qué se cabla si pasa / qué NO se toca

- **No se cabla nada en esta tarea.** Como la 37→53, el ship de un veredicto de salida es **el
  mecanismo, y apagado**: un `paper_max_holding_days` (default `None` = sin tope, el comportamiento
  de hoy) más sus tests, en una tarea propia. Prenderlo es decisión de Chapa.
- **Y para el candidato A hay un costo de cañería que se declara ahora:** el detector de anomalía
  **no corre en el engine vivo** — la 45 lo dejó como enabler sin cablear. O sea que **A no es
  cableable** sin construir antes esa cañería (harvest/serving del evento PIT en el scan diario).
  Eso no cambia el veredicto, pero sí la lectura: **A tiene que ganar por bastante más que B para
  justificar su costo**, y si empatan, gana B por barato.
- No se toca `engine.py`, `strategies.py`, `gates.py` ni la DB viva.

---

## 8. Qué NO se modela (caveats antes de correr)

- Los **desvíos declarados** del harness (`analysis/harness_config.py`): ventana de `analyze()`
  (504 barras vivas vs expandida en los artefactos PIT), precio de decisión de las barreras, fill,
  gates de re-entrada y la ventana **rodante** de los artefactos.
- El **cap se cuenta en ruedas** (barras), no en días calendario.
- **No se modela la re-entrada inmediata** al ticker capado más allá de lo que ya hacen
  `allow_reentry_while_open=False` y los gates 5/5b: si el tope libera un slot y el mismo ticker
  vuelve a ser candidato, el engine vivo puede bloquearlo por whipsaw. Está dentro de `live_gates`,
  pero el **tope aumenta la tasa de eventos que los disparan** y eso no está calibrado.
- El evento se computa **PIT** sobre los artefactos, con la ventana expandida — no con las 504 barras
  que vería el engine.

---

## 9. Plan de ejecución

1. **Enabler** — `simulate_portfolio(..., cap_days_of=Callable[[str, str], int] | None)`: resuelve el
   cap **por posición** a partir de `(ticker, fecha_entrada)` y se lo pasa a `replay_cycle`, que ya
   recibe `cap_days` posición por posición. `None` ⇒ el `cap_days` global de siempre, así que ningún
   harness previo cambia de comportamiento. **Tests del enabler**, no sólo del runner.
2. **Runner** `scripts/run_event_timestop_t51.py` — determinista, `--json`, con `announce(...)`,
   ventana y población declaradas, y cache reanudable como el de la 37.
3. **Smoke** sobre universo chico para validar la cañería. **No se leen umbrales del smoke:** la
   lección de la 49 es que el poder del oráculo **escala con candidatos por día**, así que un smoke
   chico es útil para la cañería y **engañoso para cualquier umbral**.
4. **Corrida completa** sobre los 127 tickers, y veredicto contra el §6 sin re-especificar nada.
