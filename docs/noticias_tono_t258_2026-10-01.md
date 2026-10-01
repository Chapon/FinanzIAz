# Tarea 258 — ¿El tono −3…+3 ordena el retorno a 5 días? (pre-registro)

**Fecha del pre-registro:** 2026-10-01, **antes** de mirar ningún retorno con niveles. Lo único
que se miró son conteos (abajo). Lo que sigue no se mueve después de ver el número.

## Por qué

Desde la parte 1 de la tarea 258, la pestaña Noticias muestra el **tono** de cada noticia:
`round(3 × sentiment_score)`, de −3 a +3. La columna se llama «Tono» y no «impacto», porque la
tarea 255 midió que el **signo** del clasificador no predice el retorno a 5 días
(`docs/noticias_impacto_t255_2026-10-01.md`). La intensidad es información que la 255 no usó.
La pregunta es si el nivel **ordena** el retorno siguiente. Si lo hace, la columna se gana el
nombre de impacto y puede mostrar el retorno medido por nivel.

## Lo que se miró antes (conteos, sin retornos)

Polaridad disponible: 78 filas en junio, 10.938 en julio, todas desde agosto. Niveles de las
53.788 filas con polaridad desde junio:

| −3 | −2 | −1 | 0 | +1 | +2 | +3 |
|---|---|---|---|---|---|---|
| 99 | 8.030 | 112 | 33.364 | 17 | 6.610 | 5.556 |

**La escala es casi categórica:** qwen devuelve polaridades agrupadas y los niveles ±1 y −3
casi no aparecen. En la práctica la medición compara −2, 0, +2 y +3. Eso se reporta como
hallazgo aparte; acá no se corrige.

## Datos y definiciones

Igual que la 255 (mismo instrumento: entrada en la primera apertura posterior a la publicación en
hora NY, salida al cierre de la quinta rueda, exceso contra SPY, IC por bootstrap de ruedas con
5.000 réplicas y semilla 258), con estas diferencias:

- **Filas:** `news_events` con `sentiment_score` no nulo y publicadas desde el **2026-07-01**.
  **Incluye las neutrales** (nivel 0), que son el grupo de control natural de una escala.
- **Frames:** `2y`, los que la app mantiene al día (la lección de la 255).
- **Unidad:** `(ticker, rueda de entrada)`; su tono es la **media de los niveles** de las
  noticias de esa unidad.

## Métrica y veredicto

**Primaria:** la correlación de Spearman `ρ` entre el tono de la unidad y su exceso a 5 días,
con IC 95% por bootstrap de ruedas.

**Extremos:** `Δ_ext = media(exceso | tono ≥ +1,5) − media(exceso | tono ≤ −1,5)`.

**PASA** —el nivel ordena el retorno y la columna puede llamarse impacto— si se cumplen las
**cuatro**:

1. `ρ > 0`;
2. el límite inferior del IC 95% de `ρ` es mayor que 0;
3. `Δ_ext ≥ 0,5 pp` (el mismo piso de costo que la 255);
4. el signo de `ρ` es el mismo antes y después del **2026-08-16** (las dos mitades de la ventana).

**NO PASA** si falla cualquiera. En ese caso la columna sigue llamándose «Tono», sin cambios.

**Se reporta y no cambia el veredicto:** el exceso medio por nivel redondeado de la unidad (−3…+3,
con su `n`), y `+3` contra `+2`, que es la única comparación de **intensidad** que los datos
permiten (las dos del mismo signo con muestra).

## Lo que esto NO es

Display. No se cablea nada a sizing ni a gates (regla 3), pase lo que pase.

## Resultado (2026-10-01) — **NO PASA**

Corrida: `python scripts/measure_news_tone_fwd5_t258.py`. El pre-registro de arriba no se tocó.
53.710 noticias con polaridad desde el 2026-07-01, 131 tickers con frame `2y` (4 atrasados:
AAPL, AVB, MLTX, TEAM). **4.082 unidades en 59 ruedas.**

| | valor | condición |
|---|---|---|
| `ρ` (Spearman) | **−0,018** | > 0 → **falla** |
| IC 95% de `ρ` | [−0,055, +0,016] | límite inferior > 0 → **falla** |
| MDE de `ρ` | ≈ 0,050 | |
| `ρ` por mitad | −0,058 \| +0,003 | mismo signo → **falla** |
| `Δ_ext` (≥ +1,5: n=362 · ≤ −1,5: n=78) | +0,66 pp | ≥ 0,5 pp → cumple |

Exceso medio a 5 días por nivel redondeado de la unidad:

| −2 | −1 | 0 | +1 | +2 | +3 |
|---|---|---|---|---|---|
| −1,02 pp (n=78) | −0,44 pp (n=400) | −0,46 pp (n=2.143) | −0,80 pp (n=1.099) | −0,21 pp (n=267) | −0,77 pp (n=95) |

**+3 contra +2: −0,55 pp** (n=95 / 267). La intensidad tampoco ordena dentro de las positivas.

**Qué dice y qué no:**

- **El nivel no ordena el retorno.** `ρ` es prácticamente cero, con el IC centrado en el cero y
  sin signo estable entre mitades. Esta muestra descarta `|ρ|` mayores que ~0,05.
- **El `Δ_ext` que pasa el piso no alcanza solo:** el grupo negativo tiene 78 unidades y la
  serie por nivel no es monótona (el +1 rinde peor que el 0, y el +3 peor que el +2). Un extremo
  que pasa sin un orden que lo sostenga es ruido, y por eso el pre-registro pidió las cuatro.
- **Junto con la 255:** ni el signo (3 niveles) ni la intensidad (7) de lo que el clasificador
  lee en el titular anticipan el retorno desde la apertura siguiente.

**Límites:** 59 ruedas (julio–septiembre 2026, un único régimen); la escala es casi categórica
(ver arriba), así que en la práctica se compararon −2, 0, +2 y +3, y la media por unidad genera
los niveles intermedios.

**Consecuencia, según lo pre-registrado:** la columna sigue llamándose **«Tono»**, sin cambios.
