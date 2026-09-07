# PRE-REGISTRO — ¿El brazo que decide en vivo sigue cumpliendo el kill-criteria de la T20? (Tarea 115, T20-KILLGATE)

**Escrito el 2026-09-07, ANTES de tocar el runner y ANTES de mirar ningún resultado de `R2b_f050`.**
Criterios congelados acá. Runner: `scripts/run_sizing_exposure_t10_t20.py`.
Origen: `docs/reentry_decl_t36_2026-09-07.md` §4.1 (tarea 36).

**Por qué hay pre-registro y no una corrida a secas:** `R2b_f050` es la **única decisión de la serie
T7→T26b que está cableada y ACTIVA** en la cuenta viva (`paper_regime_scale_enabled = True`,
`paper_regime_scale_factor = 0.50`), y hoy recorta **todas** las BUY nuevas cuando SPY está bajo su
SMA200. Re-medirla toca una decisión de trading ⇒ regla 2.

---

## 0. Qué se miró ANTES de congelar, y qué se evitó a propósito

**Se miró** (todo publicado, nada nuevo):

- El kill-criteria congelado de la T20 (`docs/sizing_exposure_prereg_t10_t20_2026-07-22.md` §5) — son
  **cuatro** criterios y hay que cumplir **todos**, no el primero solo.
- La tabla publicada de la T20 (2026-07-22) y la re-corrida de la T33 (2026-08-16) §7.
- El código del runner: arms, `common`, oráculo, invariantes.

**Se vio de más, y se declara:** verificando la tarea 117 corrí el runner en su config publicada y la
salida imprimió el banner y **las dos primeras filas** — `B0_equal_weight` (CAGR 14.05%, Sharpe 0.81)
y `S1_inverse_vol`. **No se miró `R2b_f050` ni ningún brazo de régimen**, que son los que están bajo
test. El baseline no es un grado de libertad acá: los umbrales son **diferencias contra él** y ya
estaban congelados desde julio, así que conocerlo no permite elegir nada.

**Se evitó a propósito:** correr con `--live-gates` (todavía no existe el flag), y mirar la salida
completa de la corrida de verificación.

**Lo que esta tarea NO puede ser:** una re-decisión del criterio. Los cuatro criterios vienen de julio
y **no se tocan**. Si alguno resulta incómodo, el resultado es que no se cumple — no que el umbral
estaba mal puesto.

---

## 1. La pregunta

> ¿`R2b_f050` —el factor cableado y activo— sigue cumpliendo los **cuatro** kill-criteria congelados de
> la T20, sobre la muestra de hoy, **y** bajo la regla que el engine ejecuta (con sus gates de
> re-entrada)?

Motivo, con los números que la abren:

| corrida | ΔSharpe | ΔCAGR | criterio 1 (`≥0.10` **o** `≥1.0pp`) |
|---|--:|--:|---|
| T20 publicada (2026-07-22) | **+0.11** | +0.59 pp | **pasa**, por **0.01**, en una sola pata |
| T33 legacy (2026-08-16) | +0.09 | +0.44 pp | **falla las dos** |
| T33 honesta (2026-08-16) | +0.08 | +0.52 pp | **falla las dos** |

La T33 re-corrió T10/T20 **fuera de su enunciado** y concluyó *"veredicto SHIP en las dos corridas,
mismo brazo seleccionado, y el factor 0.50 que Chapa eligió cablear sigue mejorando las tres métricas
a la vez"*. **Las tres afirmaciones son ciertas y ninguna es el criterio 1.** El brazo que el harness
**selecciona** por Sharpe es `R2b_f025` (+0.15 Sh honesto, pasa cómodo); el que **decide en vivo** es
`f050`. Nadie los había separado por escrito.

**Y falta un eje entero:** ninguna de las tres corridas modela los gates de re-entrada. Mecanismo
declarado en el doc de la 36 y **no medido**: Gate 5 bloquea el re-BUY tras un cierre **en pérdida**
reciente, las pérdidas se agrupan en **risk-off**, y `R2b` recorta el tamaño **en risk-off** ⇒ el
engine ya haría **parte** de lo que el harness le acredita entero al brazo. Contra-argumento honesto,
también declarado: el slot bloqueado se lo lleva el siguiente candidato, así que la exposición se
redistribuye en vez de caer — salvo cuando la pila entera está bloqueada.

---

## 2. Lo que esta tarea NO va a poder hacer, dicho antes

**No hay ancla de reproducción, y no se va a fabricar una.** Este runner no llama a
`reproduction_check` (sólo lo hacen 7 runners, todos posteriores), y la muestra se movió dos veces
desde julio: la ventana de los artefactos es **RODANTE** (T48) y la 111 reparó el cohorte insertando
el 2026-08-28 (T117). El T7 declaraba **4028** entradas el 2026-08-16 y hoy el mismo loader da
**4015**.

**Consecuencia de diseño, y es la decisión central del pre-registro:** el veredicto **no** se dicta
comparando contra los números de julio. Se dicta sobre una comparación **pareada dentro de una misma
corrida**: `B0` vs `f050`, con los gates **OFF** y con los gates **ON**, sobre la misma muestra, el
mismo día, el mismo cohorte. Los números de julio y de agosto se reportan **al lado**, con su
población declarada, como contexto — no como gate. Un ΔSharpe medido hoy contra un B0 medido hoy
responde *"¿el criterio se cumple?"* sin depender de reproducir nada.

---

## 3. Población y config (CONGELADO)

**Corrida A — la del veredicto (reproduce el marco de la T20):**

- Universo `data/harness_universe_41_10y.txt` (41 tickers), `--period 10y`, `--warmup 250`,
  `--spacing 20`, `--cap-days 20`, `--capital 50000`, `--max-positions 5`.
- `--fill-mode decision` (el honesto, default desde la T33). El `resting` **no** se corre: reproducir
  el look-ahead no es la pregunta.
- Muestra declarada al momento de escribir esto: **4015 entradas**, ventana
  `2016-09-01..2026-09-01` (2513 barras), store de señales **sin fechas pendientes** (T117 cerrada).
- Los **siete** brazos candidatos corren, aunque el que está bajo test sea uno: el criterio 3
  (PBO/DSR) los cuenta a los siete **como intentos**, y sacar brazos cambiaría el descuento.

**Corrida B — la lectura para la cuenta viva (NO dicta el veredicto):** idéntica pero
`--max-positions 10` y universo `data/harness_universe_live_acct2.txt` (127 tickers, 12404 entradas).
Se reporta aparte y **se declara explícitamente que no es el marco del criterio congelado**, que se
midió a 5 slots sobre 41 tickers. Cambiar la población convierte esto en otro experimento; se corre
porque la cuenta viva tiene 10 slots y esa brecha merece un número, no porque mande.

**Cada corrida, dos veces:** `live_gates=False` y `live_gates=True`. Es el único eje nuevo.

---

## 4. Los brazos (CONGELADO — sin cambios respecto de la T20)

Los siete de `CANDIDATE_ARMS`, tal como están: `B0_equal_weight` (baseline), `S1_inverse_vol`,
`S2_vol_target`, `R2b_f025`, `R2b_f050`, `R2b_f075`, `C_S2xf050`. Más `V_oracle_size` (validación,
no candidato).

**El brazo bajo test es `R2b_f050`**, y esto es lo que cambia respecto de la lectura de la T33: el
veredicto se dicta sobre **el brazo cableado**, no sobre el que el harness selecciona por Sharpe.
`R2b_f025` se reporta al lado porque es la alternativa natural si `f050` falla, pero **no es el
sujeto**.

---

## 5. Sanity del instrumento (si falla alguno, la corrida es INVÁLIDA y no hay veredicto)

1. **Contabilidad:** desvío equity-vs-cash ≤ `1e-4` en los siete brazos + el oráculo.
2. **Invariante de exits:** ninguna variante cambia la salida de una posición **compartida** con el
   baseline (`check_exit_invariant`).
3. **El oráculo se despega:** `V_oracle_size` tiene que superar claramente a `B0` en CAGR. Es el
   sanity que la propia T10 usó y que **atrapó un bug real** (el rechazo por cash); sin él, el
   NO-SHIP del sizing habría sido un artefacto. Umbral: `CAGR(oráculo) ≥ CAGR(B0) + 5.00 pp`, el
   mismo orden que usan la T26/T26b para su oráculo.
4. **Los gates muerden:** con `live_gates=True`, `n_gate5_blocked > 0`. Un gate que no bloquea nada no
   está midiendo el eje.
5. **Predicción falsable de la tarea 36, y cuenta como sanity:** con los gates ON, los **siete brazos
   tienen que bloquear exactamente el mismo conjunto de candidatos** (`n_gate5_blocked` y
   `n_gate5b_blocked` **idénticos** en los siete). El §3 del doc de la 36 lo deriva del código —`ret`
   invariante al notional, cash que nunca rechaza, `scale` que nunca llega a 0—. **Si no da idéntico,
   ese razonamiento está mal** y hay que anotarlo como hallazgo antes de leer nada más: sería un
   desvío entre lo que el doc afirma y lo que el simulador hace.

---

## 6. Regla de decisión (CONGELADA)

Se evalúan los **cuatro** criterios de la T20 §5 sobre **`R2b_f050` vs `B0_equal_weight`**, en la
corrida A, **con los gates ON** (es la regla que el engine ejecuta) — y se reporta el mismo cuadro con
los gates OFF al lado.

1. **C1 beneficio:** `ΔSharpe ≥ +0.10` **o** `ΔCAGR ≥ +1.0 pp`.
2. **C2 riesgo (brazo de régimen):** el **maxDD de cartera NO sube** respecto de `B0`.
3. **C3 robustez OOS:** `DSR > 0` **y** `PBO < 0.5`, con los siete brazos como intentos.
4. **C4 régimen:** el signo del beneficio no viene enteramente de una sola ventana
   (`bull_normal` / `2018Q4` / `covid_2020` / `bear_2022`).

**Cumple = los cuatro.** Falla uno ⇒ el criterio congelado **ya no se cumple**.

### Qué se hace con cada desenlace — y qué NO se hace

| desenlace | lectura | acción |
|---|---|---|
| pasa los 4 con gates **ON y OFF** | el criterio se sostiene y no dependía del desvío | se anota la re-verificación con la muestra de hoy. **Nada que tocar.** |
| pasa **OFF**, falla **ON** | el criterio se apoyaba en un desvío que la cuenta viva **no tiene** | se documenta y **se eleva a Chapa** |
| falla en **las dos** | el criterio no se cumple con la muestra de hoy, y los gates no son la causa | se documenta y **se eleva a Chapa** |
| falla ON y pasa OFF **por C2/C3/C4** (no C1) | el motivo es otro que el margen de julio | idem, y se nombra cuál |

**En ningún desenlace se cambia nada en la cuenta viva desde esta tarea.** Las opciones —mover el
factor a `f025`, apagar `paper_regime_scale_enabled`, o dejarlo activo declarando que el criterio ya
no se cumple— son **decisión de Chapa**, igual que lo fue activarlo en julio (patrón E1b). Este
pre-registro se compromete a **medir y presentar las tres**, no a elegir.

**Y no se re-decide después de ver resultados:** si los cuatro criterios dan incómodo, el resultado es
que no se cumplen. No se afloja un umbral de julio en septiembre.

---

## 7. Qué se toca de código (y qué no)

**Sólo el enabler, que ya existe:** `--live-gates` en `run_sizing_exposure_t10_t20.py`, pasado a
`common` como `live_gates=args.live_gates`. Default **OFF**, así que la corrida publicada no cambia —
mismo patrón que `eval_mode` (26b), `fill_mode` (33) y `live_gates` en los otros tres runners que ya
lo tienen (T11b, T21, T26b).

**No se toca:** `portfolio_sim`, los brazos, el criterio, los umbrales, ni ningún flag de la cuenta
viva.

---

## 8. Caveats declarados antes de correr

- **Los otros desvíos siguen sin modelarse** y el banner los declara: overlay de volatilidad de
  cartera (muerde todos los días), blackout de earnings (no modelable hoy), barreras al close vs
  intradía, stop duro encendido en el harness y apagado en la cuenta. **El overlay de volatilidad es
  el que más preocupa acá**, porque —igual que los gates y que `R2b`— **recorta tamaño**, así que
  también podría estar haciendo parte del trabajo que el harness le acredita al brazo. No se modela
  en esta tarea y queda dicho: si `f050` falla, el overlay es el siguiente sospechoso, con tarea
  propia.
- **La corrida B no es el marco del criterio.** Se reporta y no dicta.
- **`0 de 62 BUY vivas dispararon el escalado`** (tarea 95): en la cuenta viva el flag todavía no
  cambió ninguna orden. O sea que la decisión es real pero su efecto medido en vivo es **cero hasta
  hoy** — lo que baja la urgencia operativa y no cambia nada del criterio.
