# PRE-REGISTRO — PEAD honesto, Brazo A (Tarea 11)

**Escrito el 2026-09-07, ANTES de codear el detector y de correr ningún brazo.**
Criterios congelados acá. Origen: tarea 11 (`research §4 + gap G6`), desbloqueada por
T-CAT-5b. El **Brazo B** (anomalía precio/volumen) cerró NO-SHIP el 2026-07-23
(`docs/anomaly_signal_t11b_2026-07-23.md`); esto es el **Brazo A**.

---

## 0. Qué se miró ANTES de congelar, y qué NO

**Se midió, y es lo que abre y a la vez limita la tarea:**

- **La ventana point-in-time existe:** `analyst_estimate_snapshots` tiene **35.242
  filas, 2026-06-06 → 2026-09-07, 131 tickers**, con las métricas correctas —
  `eps` y `revenue` en `0q`/`+1q`, no sólo `rec_mean`/`price_target`. La dependencia
  que la tarea declaraba (*«≥1 temporada capturada, ~40 pares»*) **está cumplida**.
- **La población de eventos:** muestra de 15 tickers ⇒ **13 prints** dentro de la
  ventana ⇒ extrapolado a los 127 del universo vivo, **~110 eventos**.
- **La pista forward por evento** (§1, y es lo que decide el diseño).

**NO se miró, a propósito:** ningún retorno post-evento, ninguna relación entre
sorpresa y reacción. La primera vez que se van a ver es después de congelar esto.

**Se declara un tropiezo de instrumento del paso previo**, porque explica por qué el
primer conteo dio cero: `collect_yfinance_earnings_history` devuelve `list[tuple]` (no
dicts) **y** el `.venv` no tiene `lxml`, que `get_earnings_dates` necesita — el
hallazgo de la tarea 18. Bajo el `.venv` la función devuelve **lista vacía sin error**.
Todo lo de acá se midió con el python de **Anaconda**, y el harness tiene que correr
ahí (§7).

---

## 1. LA LIMITACIÓN QUE MANDA SOBRE TODO LO DEMÁS: el horizonte donde vive el efecto es donde NO hay muestra

El PEAD de la literatura es un **drift de 30 a 60 días**. Medida la pista forward de
cada evento contra el fin del cohorte (2026-09-04):

| horizonte | eventos con pista completa |
|---|---|
| 5 ruedas | **100%** |
| 10 ruedas | **100%** |
| **20 ruedas** | **92%** (~101 de 110) |
| 40 ruedas | **15%** (~17) |
| 60 ruedas | **8%** (~9) |

**Consecuencia, congelada:** esta corrida sólo puede medir el drift a **20 ruedas**, que
es la **cola corta** del fenómeno. A 40-60 la muestra no existe — 9 a 17 eventos no son
una población, son una anécdota.

**Y por lo tanto, congelado antes de ver nada:** un resultado negativo a 20 ruedas
**NO refuta el PEAD**. Refuta que *este sistema, con esta muestra, pueda explotar la
cola corta del drift*. Escribir *«el PEAD no funciona»* a partir de esto sería el error
exacto que la regla 3 de `CLAUDE.md` documenta sobre el `buy_score`: **no detectar no
es lo mismo que no existe**, y la muestra que sólo descarta efectos grandes no dice
nada sobre los chicos.

## 2. El poder, calculado antes y no después

Con `n ≈ 101` eventos y una desviación por trade `σ` (a medir en la corrida, no
asumida), el **efecto mínimo detectable** al 80% de poder y α=0.05 en una comparación
pareada contra el control es aproximadamente `MDE ≈ 2.8 · σ / √n`.

**Regla congelada:** el harness **calcula e imprime el MDE con la σ medida** antes de
mostrar ningún veredicto. Si el MDE resulta **mayor que el efecto que la literatura
reporta** para la variante EAR (~7,55%/año ⇒ del orden de **0,6 pts por trade** a 20
ruedas), entonces **la corrida NO PUEDE responder la pregunta** y se declara
**SIN PODER**, sin veredicto — igual que una corrida inválida por sanity.

Esto se congela ahora porque después de ver un resultado nulo es demasiado tarde para
preguntarse si se podía detectar algo.

## 3. Población y config (CONGELADO)

- **Universo:** `data/harness_universe_live_acct2.txt` (127 tickers).
- **Eventos:** todo print de earnings con fecha dentro de `[2026-06-06, 2026-09-07]`
  que tenga (a) un snapshot de consenso **estrictamente anterior** a la fecha del
  print, y (b) ≥20 ruedas de pista forward en el cohorte. Se declara el `n` final.
- **Sorpresa, point-in-time y sin excepción:** `actual` contra el consenso del
  **último snapshot estrictamente anterior al print**. **Nunca** contra el consenso
  actual de yfinance — ése es el sesgo de revisión que mantuvo bloqueada a T-CAT-5b, y
  usarlo invalidaría la corrida entera.
- **Salida:** `replay_cycle` con la misma triple barrera de todo el proyecto,
  `cap_days=20`, `eval_mode="touch"`, `fill_mode="decision"`, política de salida viva.
- **Cartera:** `simulate_portfolio`, 10 slots, capital 50.000, `live_gates=True` — la
  regla que el engine ejecuta. Los desvíos los declara el banner.

## 4. Brazos (CONGELADO)

| brazo | qué entra |
|---|---|
| `B0_random` | **control**: mismas fechas y mismo `n`, tickers al azar del universo. **Familia de 20 semillas**, no una realización — la lección de la T39 |
| `A1_beat` | sorpresa de EPS positiva contra el consenso PIT |
| `A2_beat_and_raise` | **primario** — beat de EPS **y** de revenue (la señal máxima según el research) |
| `A3_beat_ear` | beat de EPS **y** reacción de precio positiva el día del print (variante EAR) |
| `V_oraculo` | **sanity**: entra sólo en los eventos cuyo retorno a 20 ruedas fue positivo. Mira el futuro; jamás shipeable |

## 5. Sanity del instrumento (si falla alguno ⇒ corrida INVÁLIDA, sin veredicto)

1. **El oráculo se despega:** `CAGR(V_oraculo) ≥ CAGR(B0_random_mediana) + 5.00 pp`.
   Sin esto el harness no ve calidad de entrada y un nulo no significa nada.
2. **La señal muerde:** `A2` selecciona ≥10% de eventos distintos de `A1`.
3. **Contabilidad** equity-vs-cash ≤ `1e-4` en todos los brazos.
4. **Point-in-time verificado:** para **cada** evento usado, la fecha del snapshot de
   consenso es **estrictamente menor** que la fecha del print. Un solo caso que falle
   invalida la corrida — es la propiedad que separa esto de un backtest sesgado.
5. **Poder declarado** (§2): el MDE se imprime antes del veredicto.

## 6. Regla de decisión (CONGELADA)

Sobre `A2_beat_and_raise` (primario) contra la **mediana** de las 20 semillas de
`B0_random`:

| # | criterio | umbral |
|---|---|---|
| C1 | retorno medio por trade | `≥ B0_mediana + 0.60 pts` (el orden del efecto de la literatura) |
| C2 | supera la banda | por encima del **percentil 95** de las 20 semillas |
| C3 | riesgo | `maxDD ≤ 1.5 ×` el maxDD mediano del control |
| C4 | no cuelga de un evento | sacando el mejor evento, C1 se sigue cumpliendo |

**SHIP requiere los cuatro.** Falla uno ⇒ NO-SHIP, se documenta y **no se cablea nada**.

**Y aunque pasara los cuatro, no se cabla en esta tarea.** Con una sola temporada el
resultado es, como máximo, **un candidato a validar sobre la próxima**. Cablear una
fuente de entradas nueva sobre 3 meses de datos sería exactamente lo que la regla 2
prohíbe. Lo que un SHIP habilita es **una segunda tarea de confirmación**, no un flag.

## 7. Qué se toca de código

Módulo nuevo `analysis/pead.py` (puro: evento + sorpresa PIT, sin red) y
`scripts/run_pead_t11a.py` (harness). **Nada del engine, ningún flag de la cuenta
viva.** El harness corre con **Anaconda**, no con el `.venv` (§0).

## 8. Caveats declarados antes de correr

- **Una sola temporada.** No hay walk-forward posible ni CPCV con sentido: no hay
  folds temporales que valgan sobre 3 meses. Por eso el control es una **familia de
  semillas** y no un descuento por selección múltiple.
- **El consenso PIT arranca el 2026-06-06**, así que un print del 06-08 tiene dos días
  de historia de snapshots. Se usa el último anterior, sea cual sea su antigüedad, y
  **se declara la antigüedad mediana** del snapshot usado.
- **Los desvíos harness↔engine de siempre** los declara el banner, incluido que **no
  se modela el blackout de earnings (Gate 6)** — que en esta tarea es especialmente
  incómodo: el engine **bloquea** BUY cerca de earnings, o sea que **una entrada PEAD
  sería hoy imposible en producción sin tocar ese gate**. Eso no invalida la medición
  —mide si la señal tiene edge— pero sí significa que un SHIP obligaría a abrir esa
  discusión aparte, y queda dicho antes de correr.
