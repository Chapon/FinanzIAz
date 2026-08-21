# HARNESS-WINDOW (Tarea 48) — el `10y` de los artefactos es una **ventana rodante**

**Fecha:** 2026-08-20 · **Módulo:** `analysis/harness_config.py` · **Tests:** `tests/test_harness_config.py`

**No es una tarea de trading:** no toca el motor, no decide ningún flag y no necesita pre-registro
congelado (mismo caso que la 46). Es un **gate técnico**: declara el séptimo desvío del harness y
arregla un diseño de sanity que convierte el paso del tiempo en corridas inválidas.

---

## 1. El problema en una línea

> **Los artefactos del harness guardan una ventana de 10 años anclada al día del refresh, no a una
> fecha fija. Cuando se refrescan, la ventana rueda — y ningún veredicto publicado vuelve a
> reproducir.**

Medido, re-corriendo la **T11b** con su comando publicado (`--max-positions 5 --universe
data/harness_universe_41_10y.txt --fill-mode resting`) el 2026-08-20, contra lo que publicó el
2026-07-23:

| | publicado T11b | hoy | Δ |
|---|--:|--:|--:|
| `A_k2.0_m1.5` CAGR | 12.89% | **12.77%** | −0.12 pp |
| `A_k2.0_m1.5` Sharpe | 1.24 | **1.22** | −0.02 |
| tomadas / ofrecidas | 420 / 467 | **419 / 466** | −1 / −1 |
| `bull_normal` pts/trade (n) | +1.57 (380) | **+1.55 (379)** | −0.02 |
| obs diarias (DSR) | 2257 | **2256** | −1 |

**Los nueve brazos perdieron entre 1 y 3 entradas.** No cambió el detector ni el simulador: cambió la
muestra. Los parquet se refrescaron el **2026-08-09** y la ventana efectiva pasó a
`2016-07-11..2026-08-07` (2.514 barras).

---

## 2. Lo caro no es el 0.12 pp: es que el diseño de sanity de la serie se rompe solo con el calendario

Desde la 26b, cada tarea congela un **sanity de reproducción** con tolerancia de ±0.05 pp (26b §5,
47 §5.4, 45 §5.3, 49 §5.2), y la regla congelada dice que **un sanity fallado ⇒ corrida INVÁLIDA, sin
veredicto y sin re-especificar nada**.

Con la ventana rodante, ese chequeo **no distingue dos cosas completamente distintas**:

1. **cambió la cañería** — que es lo que el sanity existe para detectar, y ahí invalidar es correcto;
2. **se refrescaron los artefactos** — que no le importa al sanity, y ahí invalidar es un error de
   diagnóstico.

La deriva ya medida (0.12 pp en un mes) es **2,4× la tolerancia**. O sea: un sanity escrito hoy
**falla mañana por el calendario**, y el runner lo reporta como *"cambió algo en la cañería y nada de
lo que siga es comparable"* — que es falso. **Es una máquina de invalidar corridas buenas.**

*(Y contamina las lecturas cruzadas: el backlog cita permanentemente números medidos en fechas
distintas como si fueran conmensurables.)*

---

## 3. La decisión: **(b) aceptar la ventana rodante y hacerla visible**, no anclarla

Las dos opciones eran:

**(a) Anclar la ventana** — un `--end-date` fijo o un snapshot congelado de los artefactos. Da
reproducibilidad bit a bit. **Se descarta** porque el costo es que el harness deje de ver los datos
que la cuenta viva sigue acumulando, que es justamente lo que destraba las tareas bloqueadas por datos
(el Brazo A de la 11 espera la temporada Q3). Además obligaría a re-keyear el cache Parquet, que está
indexado por `período`, no por fechas.

**(b) Aceptar la deriva, declararla y hacer que los sanity la conozcan** — elegida. La
reproducibilidad se recupera por el otro lado: **cada corrida declara sobre qué muestra corrió**, y el
chequeo de reproducción **sabe sobre qué muestra se midió su referencia**.

*(Si alguna vez hiciera falta reproducibilidad bit a bit —una auditoría externa, por ejemplo—, (a)
sigue disponible y esta tarea no la bloquea: lo que agrega es la huella de la ventana, que es
justamente lo que haría falta para anclarla.)*

---

## 4. Qué se shipeó

### 4.1 El séptimo desvío, declarado y en el banner

`analysis/harness_config.py` gana el bloque que declara la ventana rodante, junto a los otros seis, y
`announce()` acepta `window=`. Los **16 runners** que simulan cartera lo pasan. El banner ahora dice:

```
  · ventana de los artefactos 10y = 2016-07-11..2026-08-07 (2514 barras) — es RODANTE
    (anclada al refresh, no a una fecha fija): estos números dejan de reproducir cuando
    se refresquen los parquet (tarea 48)
```

Y si un runner **no** la declara, el banner dice **eso** —*"el runner NO declara la ventana efectiva
… no se sabe contra qué muestra se midió"*— en vez de callarse. La diferencia entre *"no aplica"* y
*"no se sabe"* es la que la serie viene pagando cara.

- `ArtifactWindow(start, end, n_bars)` — la huella de la muestra.
- `artifact_window(bars_by)` — la computa de las barras ya cargadas. **Pura**: sin I/O, sin pandas.

### 4.2 El chequeo de reproducción pasa a tener **tres** estados

`reproduction_check(measured, expected, *, tol, current, measured_on)` devuelve:

| estado | cuándo | qué hacer |
|---|---|---|
| **`OK`** | reproduce dentro de `tol` | seguir |
| **`FALLA`** | no reproduce **y la ventana es la misma** | **cambió la cañería** ⇒ corrida INVÁLIDA |
| **`INDETERMINADO`** | no reproduce **y la ventana se movió** (o la referencia no dice sobre cuál se midió) | **re-anclar la constante**: re-correr y re-publicar el número con la ventana nueva. No es un bug de cañería |

**`INDETERMINADO` sigue bloqueando el veredicto** —no se decide sobre una cañería sin verificar— pero
con el diagnóstico correcto y con la acción concreta al lado. Eso es todo lo que cambia: antes
bloqueaba **acusando a la cañería**.

Y el default es **conservador**: si la referencia no declara su ventana, el resultado es
`INDETERMINADO`, nunca `FALLA`. **No se acusa a la cañería sin evidencia.**

### 4.3 Las constantes quedan ancladas

`WINDOW_REFRESH_2026_08_09 = ArtifactWindow("2016-07-11", "2026-08-07", 2514)` — la ventana con la que
se midieron **todas** las constantes de reproducción que hoy viven en los runners (T39 §5.2, 47 §5.4,
45 §5.3, 49 §5.2). Los cuatro runners pasan a usar `reproduction_check` con ese ancla.

**Ningún veredicto publicado cambia:** la ventana de hoy **es** el ancla, así que los cuatro chequeos
siguen dando `OK` exactamente como cuando se publicaron. Lo que cambia es qué van a decir **después
del próximo refresh**.

---

## 5. Y una afirmación publicada que había que corregir

`docs/anom_regime_t38_2026-08-19.md` §2 decía que su config A *"reproduce el veredicto publicado
**dígito por dígito**"*. **No lo hace:** su propia tabla da **12.77%** y `bull_normal` **+1.55
(n=379)** contra los **12.89%** y **+1.57 (n=380)** de la T11b. Lo que sí reproduce exacto es el
**perfil de stress** (−0.30 / +1.71 / −2.01), que es presumiblemente lo único que se comparó. Nota de
corrección agregada.

No mueve ninguna conclusión de la 38 —su hallazgo es que **la población** da vuelta el perfil, y eso
se sostiene con margen— pero la frase era falsa y otros docs la citan.

---

## 6. Qué deja

- **El séptimo desvío declarado**, en el mismo lugar que los otros seis, con la ventana efectiva
  impresa en cada corrida.
- **`reproduction_check` con tres estados** — reusable por cualquier sanity de reproducción futuro.
- **`artifact_window` / `ArtifactWindow`** — la huella de la muestra, pura y barata.
- **10 tests nuevos** en `tests/test_harness_config.py`, incluido el que fija el caso que motivó la
  tarea (*"una ventana movida es INDETERMINADO, no FALLA"*).
- **La regla operativa para el próximo pre-registro:** si un sanity se va a leer contra un número
  publicado, hay que declarar **sobre qué ventana se midió**. Va a la skill
  `backtest-replay-harness`, junto a la lección hermana de la 49 (*"un eje de config no declarado
  puede sostener un hallazgo entero"*).
