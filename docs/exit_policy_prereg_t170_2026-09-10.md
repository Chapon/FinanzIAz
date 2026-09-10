# Pre-registro — EXIT-POLICY-REDECIDE (Tarea 170) · **CONGELADO 2026-09-10, antes de correr**

**Origen:** decisión de Chapa al cerrar la tarea **167** (*«no tocar nada y pre-registrar un
barrido nuevo»*), después de que el T37 re-corrido diera **NO-SHIP** sobre la muestra del
2026-09-09 (`docs/stop_value_rerun_t167_2026-09-10.md`).
**Instrumento:** sano desde la tarea **164** (el control igualado dejó de re-sortearse).
**Qué NO hace:** no toca el motor, no cambia ninguna perilla viva, no mueve ningún umbral
existente.

---

## 0. Qué se vio ANTES de congelar — la contaminación, declarada

**La rejilla 2-D entera de CAGR de la muestra de hoy ya está publicada** (`…rerun_t167…` §3),
con las 15 celdas, el Sharpe, el maxDD y la cola de los brazos clave. O sea que **no hay
ceguera posible** sobre esta muestra, y un diseño que eligiera celdas *después* de ver eso
repetiría exactamente el defecto que dejó al T37 sin margen fuera de muestra.

Consecuencias que este pre-registro acepta por adelantado:

1. **No se nombra ninguna celda candidata nueva.** Los dos brazos del gate se eligen por
   **procedencia**, no por su número: uno es la política que corre hoy y el otro es la que
   tenía evidencia antes del 2026-08-27.
2. **El gate no selecciona.** No hay ningún paso donde los datos elijan un brazo — y ahí está
   la diferencia con el T37, cuyo `C1`/`C3` miden **el procedimiento de selección** (lo que el
   walk-forward elige por fold), no un brazo fijo. Verificado leyendo el runner antes de
   congelar: `dcagr_oos = wf["proc"]["cagr"] − wf["base"]["cagr"]` y el bootstrap corre sobre
   `wf["star"]`, el brazo **elegido**.
3. **La rejilla queda como descriptivo con regla de lectura congelada** (§7), no como gate.

**Lo que NO se miró y no se va a mirar antes de correr:** el Δ fuera de muestra **fold por
fold** entre los dos brazos del gate, su bootstrap pareado y su cola — que es justamente la
medición nueva que esta tarea produce. Hoy no existe en ningún output: en agosto el brazo
seleccionado *coincidió* con el vivo y por eso el `C3` publicado sí lo medía; hoy el
seleccionado es otro (`soff_toff`).

---

## 1. La pregunta

**(A) — GATE.** ¿Hay evidencia, sobre la muestra de hoy, para **mover la política de salida
viva** de `soff_t2.0` (stop duro apagado, trailing 2.0×ATR) a `s2.0_t2.0` (stop duro a
2.0×ATR + trailing 2.0×ATR)?

**(B) — DESCRIPTIVO.** ¿La **elección de celda** en la rejilla stop×trail es decidible con
esta muestra, o estamos eligiendo ruido?

La (A) es la pregunta operativa. La (B) existe porque la serie 26 → 26b → 34 → 37 → 167 minó
la misma rejilla **cinco veces** y cada vez eligió distinto; si la (B) responde *«no es
decidible»*, eso **cierra** la discusión hasta que haya muestra nueva, y es una conclusión
publicable que ahorra el sexto barrido.

---

## 2. Población y config (CONGELADO)

Idénticas al T167, que es lo que hace comparables los números:

| eje | valor |
|---|---|
| universo | `data/harness_universe_live_acct2.txt` — **126** tickers (AVB salió, tarea 156) |
| ventana | `2016-09-12..2026-09-09` (**2512** barras) — **rodante**: estos números dejan de reproducir con el próximo refresh (T48) |
| entradas | `analyze BUY` PIT, **141.417** |
| slots | 10 · `equal_weight` · capital finito (`portfolio_sim`) |
| `cap_days` | 250 |
| eval / fill | `eval_mode=touch` · `fill_mode=decision` |
| gates de re-entrada | **modelados** |
| costos | completos (espejo de la cuenta viva) |

---

## 3. Brazos (CONGELADO)

| brazo | rol | por qué está |
|---|---|---|
| `soff_t2.0` | **referencia** | es **la política viva** de la cuenta 2 (`atr_hard_stop_enabled=False`, `atr_trail_mult=2.0`) |
| `s2.0_t2.0` | **desafiante** | es la política que tenía evidencia **antes** del 2026-08-27, y el baseline que el pre-registro del T37 congeló |
| `ORACULO_STOP` | sanity | el instrumento tiene que ver calidad, no cantidad |
| `AZAR_MISMA_TASA` | sanity | control igualado en tasa — **estable desde la T164** |
| las 15 celdas | descriptivo (§7) | **no son brazos del gate** |

**Ningún brazo se agrega, se saca ni se re-nombra después de congelar.** Si hiciera falta,
va como enmienda fechada y firmada, como la 1 y la 2 del T37.

---

## 4. Regla de decisión (CONGELADA)

Para **mover la política viva** hacen falta **las cinco**, sobre el Δ = `s2.0_t2.0` −
`soff_t2.0` (desafiante menos vivo):

| id | criterio | umbral |
|---|---|---|
| **D1** | ΔCAGR **fuera de muestra** (walk-forward, los 5 folds agregados) | ≥ **+1.00 pp** |
| **D2** | consistencia: folds en que el desafiante gana | ≥ **4 de 5** |
| **D3** | cola por trade: Δ(peor) **y** Δ(p1) | ≥ **−2.00 pp** |
| **D4** | bootstrap pareado por bloques (20 ruedas, 2000 resamples) sobre el retorno diario | **IC95% inferior > 0** |
| **D5** | maxDD de cartera, in-sample **y** OOS | ≤ vivo **+1.00 pp** |

**Los umbrales son los del T37, sin tocar uno.** D1/D3/D5 son sus C1/C6/C2; D2 es su C7
reencuadrado sobre un brazo fijo en vez de sobre la selección; D4 es su C3.

**La asimetría es deliberada y va declarada:** para **mover una política viva** se pide
evidencia en **todos** los ejes; para **dejarla** no se pide nada. No es neutralidad — es que
el costo de equivocarse no es simétrico, y el que propone el cambio carga la prueba. Si se
quisiera la regla al revés (*«se vuelve al stop duro salvo evidencia de lo contrario»*) eso
sería otro pre-registro, con esta misma tabla y los roles dados vuelta.

**Resultado esperado, escrito ANTES de correr: NO MOVER.** In-sample el desafiante pierde por
**−3.80 pp** de CAGR y tiene **+15.8 pp** de maxDD, así que para pasar D5 tendría que dar eso
vuelta. **El valor del ejercicio es que *«no mover»* sea una respuesta medida y no inercia**, y
que el único eje donde el desafiante puede ganar —la generalización fuera de muestra— quede
medido con su intervalo, no inferido de un número de un experimento que medía otra cosa.

**Si alguna de las cinco no se puede medir, la corrida es INVÁLIDA y no hay veredicto.** No se
re-especifica nada para salvarla (precedente T26, T34, T38, T51, T54).

---

## 5. Sanity del instrumento (si falla alguno ⇒ INVÁLIDA, sin veredicto)

Los del T37 §7, que ya corren y hoy pasan todos, más uno nuevo:

1. contabilidad ≤ 1e-6 en todos los brazos;
2. oráculo vs control igualado: ΔCAGR ≥ +1.50 pp **y** ΔmaxDD ≤ −5.00 pp;
3. control mecánico: el brazo `off` no dispara su barrera;
4. el desacople muerde ≥ 10% de los trades;
5. reproducción multi-estado contra la T34: `s2.0_t2.0 0.0498`, `soff_t2.0 0.0878`,
   `soff_toff 0.1044` (tol 0.0005);
6. **NUEVO — el control no depende del índice de barra** (invariante de la T164). No se
   verifica en la corrida sino en la suite (`tests/test_control_resorteado_t164.py`): recortar
   la cabeza del frame no cambia **ninguna** decisión del sorteo. Se declara acá porque es la
   condición que hace creíble al sanity 2, y hasta el 2026-09-10 **no se cumplía**.

---

## 6. Qué NO se modela (caveats antes de correr)

Los ocho desvíos que `deviations()` declara solo en el banner, sin cambios: ventana de
`analyze()` expandida, barreras decididas al toque (cota superior), ventana rodante de los
artefactos, **stop duro encendido en el harness vs apagado en vivo** (el desvío que esta tarea
mide), overlay de volatilidad de cartera, escalado por régimen, screen de universo E1b y
blackout de earnings. Y el supuesto más fuerte, heredado del T37 §10: la **ruina correlaciona**
en una crisis real y el modelo de inyección la trata independiente entre nombres, lo que
favorece al brazo sin stop.

---

## 7. La pregunta (B) y su regla de LECTURA (congelada)

Para las **15 celdas**, y sólo como descriptivo: ΔCAGR fuera de muestra contra `soff_t2.0`,
folds ganados, y el **IC95%** del bootstrap pareado.

**Regla congelada:** si el IC95% del ΔCAGR OOS de **ninguna** celda excluye el cero, la
conclusión publicable es **«con esta muestra la elección de celda no es decidible»**, y la
rejilla queda **cerrada** —no se vuelve a barrer— hasta que haya muestra nueva que no sea la
misma ventana rodante. Si **alguna** celda lo excluye, eso **no la cabla**: abre su propio
pre-registro, porque una celda elegida entre 15 por su intervalo necesita un gate
anti-multiplicidad que esta tarea no define.

---

## 8. Qué se cablea si pasa / qué NO se toca

- Si D1-D5 pasan: **nada se cambia automáticamente.** Se publica el veredicto y prender o no
  es decisión de Chapa, igual que el §9 del T37. El mecanismo ya está cableado (tarea 53):
  mover la política es editar `atr_hard_stop_enabled` en el settings vivo, con la app cerrada.
- Si no pasan: la política viva **queda como está**, y el doc lo dice con el número.
- En ningún caso se toca `engine.py`, `gates.py` ni un umbral existente.

---

## 9. Plan de ejecución

1. Runner nuevo y chico (`scripts/run_exit_policy_t170.py`) que reusa `build_arms`,
   `portfolio_sim` y el walk-forward del T37 **sin el paso de selección**: dos brazos fijos,
   cinco folds, bootstrap pareado, cola y maxDD. Tests offline del runner antes de correr.
2. Corrida completa (2000 resamples) y veredicto en `docs/exit_policy_t170_<fecha>.md`.
3. El descriptivo de la (B) en el mismo doc, con su regla de lectura aplicada tal cual.
4. Las constantes de reproducción que se publiquen entran al registro de anclas con **su
   ventana y su población** (T48/T52), para que el próximo refresh las deje `INDETERMINADO` en
   vez de `FALLA`.
