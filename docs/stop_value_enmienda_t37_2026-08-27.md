# ENMIENDA al pre-registro de STOP-VALUE (Tarea 37) — C5 no tiene potencia, y hace falta un sanity de reproducción

**Fecha:** 2026-08-27 · **Estado:** escrita **ANTES de codear el enabler y el runner**, o sea antes de
medir absolutamente nada de la rejilla 2-D.
**Enmienda a:** `docs/stop_value_prereg_t37_2026-08-19.md` (`d6ba1b8`) — **§8 C5** y **§7 (sanity)**.
**Todo lo demás queda intacto:** población (§4), brazos (§5), walk-forward (§6), y **C1, C2, C3, C4,
C6, C7, C8 y C9 con sus umbrales sin tocar**.

**Mandato:** `docs/regime_power_t46_2026-08-19.md` §5 — *"La **37** tiene el criterio viejo congelado
en su pre-registro y todavía no corrió: necesita **enmienda antes de correr**, no re-lectura después."*

---

## 0. El conflicto de interés, declarado adelante

Esto hay que decirlo antes que nada, porque quien lea esta enmienda dentro de seis meses lo va a
pensar igual:

> **C5, tal como está congelado, es el criterio que rechaza al candidato favorito de esta tarea.**
> La T34 midió `touch_off` en **−1.18 pts por trade** en `stress_2018q4` y su propio veredicto escribió
> que *"veinte veces la tolerancia"* era la prueba de que el guardrail se paga en las ventanas malas.
> Cambiar ese criterio, en esta tarea, es **auto-favorable a primera vista** y por lo tanto necesita una
> vara más alta que una enmienda cualquiera.

Tres hechos sostienen la vara, y ninguno depende de que el resultado guste:

1. **La medición que invalida a C5 es anterior y ajena.** La **46** no se abrió para rescatar a la 37:
   la abrió la **38**, y su primer efecto fue re-abrir la **26b** (tarea 47), no ésta.
2. **El criterio de reemplazo ya tiene antecedente y no es un sello de goma.** La **47** hizo
   exactamente este cambio y cerró **NO-SHIP igual**: C5′ pasó y la frenaron **C3 y C7**, que son
   criterios con potencia. Cambiar C5 por C5′ no hizo pasar nada.
3. **El candidato de esta tarea todavía no existe.** Sale del walk-forward del §6 sobre una rejilla
   **5×3** cuyas celdas de *stop duro ancho + trailing propio* (`4.0×2.0`, `6.0×3.0`, …) **nunca se
   corrieron**. `off × off` es el favorito porque ganó 5/5 en la T34, pero no está elegido.

Y el número que más incomoda, calculado y publicado acá en vez de escondido: ponderando los Δ por
ventana que publicó la T34 (`+0.24 / −1.18 / +2.93 / +0.11`) con los `n` de la población `analyze` que
midió la 46 (79 / 77 / 251), el **agregado de stress de `touch_off` da ≈ +0.39 pts** — o sea que
**bajo C5′ el lead conocido probablemente pase este criterio**. Queda dicho **antes** de correr, que es
la única forma de que decirlo valga algo.

---

## 1. Por qué C5 no puede fallar por otra cosa que ruido — en **esta** población

C5 congelado: *"Δ(ret medio por trade) en cada uno de los 4 ≥ **−0.05 pts**"*.

La 46 midió la potencia sobre la población `analyze` — **que es exactamente la de esta tarea**: 127
tickers, 10 slots, entradas `analyze BUY` PIT.

| ventana | n trades | σ (pts) | **detectable al 80%** | potencia para ±0.05 | umbral vs detectable |
|---|--:|--:|--:|--:|--:|
| `bull_normal` | 2102 | 4.89 | ±0.30 | 7,6% | **6×** por debajo |
| `stress_2018q4` | **79** | 5.45 | **±1.72** | 5,1% | **34×** por debajo |
| `stress_covid_2020` | **77** | 10.44 | **±3.33** | 5,0% | **67×** por debajo |
| `stress_bear_2022` | **251** | 5.50 | **±0.97** | 5,2% | **19×** por debajo |
| **`stress_POOLED`** | **407** | 6.82 | **±0.95** | 5,3% | **19×** por debajo |

**α es 5%.** Un test con 5,0-5,3% de potencia no rechaza por evidencia: rechaza al nivel del azar. Y no
falla sólo en las ventanas chicas — **falla en las cuatro**, `bull_normal` incluida.

**Consecuencia concreta para el −1.18 pts que la T34 publicó como su argumento:** en esa ventana lo
detectable es **±1.72**. El número está **por debajo del piso de resolución de su propia muestra**
(0,69×). No es un efecto chico medido bien; es un efecto que esa muestra no puede distinguir de cero.
El veredicto de la T34 **se sostiene igual** —lo frenó **C6**, el máximo en el borde, que no depende de
esto— pero el argumento que publicó al lado no tiene respaldo.

---

## 2. Lo que esta enmienda **no** hace

**No afloja el peso del régimen en esta tarea.** El backlog pidió explícitamente lo contrario
(*"el criterio de régimen tiene que pesar más que el agregado, porque es la única evidencia sobre para
qué existe el guardrail"*), y sigue en pie. Lo que cambia es **por dónde pesa**.

Querer más al régimen no crea potencia. Con `n` de 77 a 251 por ventana, **ningún** test de régimen
sobre estos datos resuelve efectos de décimas: la 46 también midió la versión de **cartera** —P(signo)
**58-92%**, nunca cerca del 95%— así que mudar el gate al nivel de cartera tampoco lo arregla.

Así que el peso se muda a los dos criterios que **sí** fueron diseñados para la pregunta *"¿para qué
existe el stop?"*, que **ya estaban congelados** y que **no se tocan**:

- **C9 (ruina inyectada)** — el pre-registro ya lo declara *"el criterio central de la tarea"*. Sus
  umbrales **no son inventados**: son las tasas medidas dentro del propio universo (2,60%/año a −50%,
  0,47%/año a −70%) y son **cotas inferiores**, porque la muestra es de sobrevivientes. Es el único
  criterio de la tarea cuya potencia **se construye** en vez de padecerse: la ruina se inyecta a una
  tasa elegida y el candidato la aguanta o no.
- **C6 (cola)** — Δ(peor trade) y Δ(p1) ≥ −2.00 pp cada uno. Mide la protección **donde un stop la
  tiene que dar**, sobre la distribución entera y no sobre 77 trades.

**Y el §8 ya tenía escrito el desenlace que corresponde si el régimen se cae por este lado:** *"Todo
pasa menos C9 → NO-SHIP, y es el resultado más informativo posible: significa que la ventaja del
candidato **es** el survivorship."* Esa frase no cambia.

---

## 3. C5′ — el criterio que reemplaza a C5 (CONGELADO)

Idéntico en forma al que implementó la **47** (`scripts/run_stop_price_redecide_t47.py`,
`regime_criterion`). **No se inventa una variante a medida de esta tarea** — usar el molde ya corrido
es justamente lo que impide calibrar un criterio contra un lead conocido.

1. **La tolerancia se computa, no se elige:**
   `tol = max(TOL_MATERIAL = 1.00 pts, detectable_mean_effect(σ_pooled, n_pooled))`.
2. **El gate va sobre `stress_POOLED`** — el agregado de las tres ventanas de stress, que es donde hay
   `n` (407 en esta población).
3. **Falla sólo si el IC95% del Δ del agregado está ENTERAMENTE por debajo de `−tol`.** Rechazar por el
   punto estimado con el IC cruzando cero es exactamente lo que la serie venía haciendo mal.
4. **Las cuatro ventanas individuales pasan a descriptivo OBLIGATORIO**, con `n`, σ, detectable, Δ, IC95%
   y P(signo) al lado. **Nunca solas como motivo de rechazo.**
5. **Descriptivo #2 obligatorio:** la versión de **cartera**, pareada por bloques
   (`block_delta_sign_stability`), por ventana y agregada. Tampoco es gate.

### 3-bis. C5′-bis — la escalada que le devuelve dientes al régimen (CONGELADO, **es un endurecimiento**)

Sin esto, C5′ solo no podría bloquear nunca por régimen en esta tarea, y eso sería vaciar la pregunta
que la tarea existe para contestar. Entonces:

> **Si alguna ventana de stress muestra un Δ negativo cuya magnitud ALCANZA su propio piso de
> resolución** —o sea `Δ_w < 0` **y** `|Δ_w| ≥ detectable_mean_effect(σ_w, n_w)`, un efecto que esa
> muestra **sí** puede distinguir de cero— **entonces C9 tiene que cumplirse además en el escalón
> siguiente de la rejilla ya congelada: `r = 5.00%/año` a `d = 50%`**, en la peor de las tres semillas.
> Si ninguna ventana resuelve un efecto negativo, **C9 queda exactamente como está congelado**.

Tres propiedades que lo hacen legítimo:

- **No inventa un número.** `r=5%` ya está en la rejilla de tasas del §3 del pre-registro.
- **Sólo puede endurecer.** Nunca relaja C9; en el mejor caso lo deja igual.
- **No se sabe si dispara.** Con los Δ de la T34 **no dispararía** (−1.18 contra ±1.72 no resuelve),
  pero el candidato de esta tarea no está elegido y las celdas nuevas de la rejilla no se midieron. Un
  Δ de −2.5 pts en `bear_2022` (detectable ±0.97) lo dispararía.

**Regla del régimen, en una línea:** el régimen ya no bloquea por ruido, pero un efecto de régimen
**que la muestra puede ver** sube la vara de la ruina.

---

## 4. Sanity nuevo §7.7 — reproducción tri-estado + ventana declarada (CONGELADO)

El pre-registro es del **2026-08-19** y la **tarea 48** cerró el **2026-08-20**: el §7 no tiene ningún
chequeo de reproducción y ningún runner de la serie puede ya correr sin declarar su ventana. Se agrega,
y es **una forma más de que la corrida salga INVÁLIDA**, no menos.

**Tres anclas gratis**, porque son celdas de la propia rejilla 5×3 que la T34 ya publicó con **la misma
config** (127 tickers, 10 slots, `cap_days=250`, `touch`, `fill_mode=decision`, `live_gates=True`):

| celda de la rejilla | brazo en la T34 | CAGR publicado |
|---|---|--:|
| stop **2.0** / trail **2.0** (= BASELINE, lo vivo) | `touch_2.0` | **2.01%** |
| stop **off** / trail **2.0** | `D1` (§4 de la T34) | **9.17%** |
| stop **off** / trail **off** | `touch_off` | **9.52%** |

- Tolerancia **±0.05 pp** (`tol=0.0005`), la misma que usó la 47.
- Se evalúa con `harness_config.reproduction_check(...)`, `measured_on=WINDOW_REFRESH_2026_08_09`
  (la T34 corrió el 2026-08-18, después del refresh del 09) y `current=artifact_window(bars_by)`.
- **`FALLA`** (misma ventana, no reproduce) ⇒ **corrida INVÁLIDA**. **`INDETERMINADO`** (la ventana se
  movió) ⇒ **también bloquea el veredicto**, con la acción al lado: re-anclar la constante sobre la
  ventana nueva, no buscar un bug.
- El banner de `announce()` declara la ventana efectiva, como en los 16 runners de cartera.

**Bonus de control que sale de la misma ancla:** que `stop 2.0 / trail 2.0` explícito reproduzca el
`touch_2.0` de la T34 —que corrió con `trail_mult=None`— **demuestra el desacople**: prueba que el
`trail_mult` nuevo llega hasta `replay_cycle` sin pisarse con `stop_mult`. Es el §11.2 del plan de
ejecución convertido en sanity.

---

## 5. Qué NO cambia (para que quede escrito)

- **Población, entradas, cartera y config del §4** — idénticas.
- **Los 15 brazos del §5** y las dos reglas sobre `off` (el `off` del stop es candidato legítimo; el
  `off` del trailing **no es shipeable**).
- **El walk-forward del §6** — mismos 5 folds, mismo embargo, misma selección por CAGR de train.
- **Los seis sanity del §7** (contabilidad, oráculo vs control igualado, control mecánico, el desacople
  muerde ≥10%, la ruina hace daño y es monótona, la ruina es idéntica para todos los brazos).
- **C1, C2, C3, C4, C6, C7, C8 y C9 con sus umbrales exactos.** En particular **C9 no se toca**: las
  tasas siguen siendo 2,60%/50% y 0,47%/70%, sobre la peor de las tres semillas.
- **Los cinco casos partidos del §8** y el §9 (qué se cabla) y el §10 (qué no se modela).

---

## 6. Qué pasa si el candidato igual falla

Lo mismo que decía el pre-registro, sin excepciones: **NO-SHIP, se documenta, y la política de salida
viva queda como está.** Si falla un sanity del §7 (incluido el §7.7 nuevo), **corrida INVÁLIDA sin
veredicto** y no se re-especifica nada para salvarla — precedente T26, T34 y 38.

Y la **tasa de ruina de breakeven** va al frente del informe pase lo que pase, como pide el §11.6: es
el número que resume la tarea aunque el veredicto sea NO-SHIP.

**Congelada. Cualquier cambio posterior a ver un resultado del §8 invalida el pre-registro y esta
enmienda.**
