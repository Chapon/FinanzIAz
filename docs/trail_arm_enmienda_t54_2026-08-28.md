# Enmienda 1 al pre-registro de TRAIL-ARM (Tarea 54) — el control igualado en tasa es **degenerado** acá

**Fecha:** 2026-08-28 · **Pre-registro:** `docs/trail_arm_prereg_t54_2026-08-28.md` (`9040c0f`)
**Escrita ANTES de correr un solo brazo del candidato.** No se vio ningún número de la grilla: el
defecto salió al escribir el runner, no al mirar un resultado. (Precedente: las dos enmiendas de la
37, `106892b` y `03efd5a`, y la de la 49, `5ee9d9d`.)

---

## 1. El defecto

El §2 del pre-registro define el control así:

> **`CONTROL_k_j`** — 20 semillas: baja el umbral en un subconjunto **aleatorio** de entradas, con la
> **misma cantidad por día** que el candidato.

**El candidato de esta tarea es incondicional.** `trail_min_excess_atrs` es un parámetro global del
gate: el brazo `k` se lo aplica a **todas** las posiciones. O sea que *"la misma cantidad por día que
el candidato"* es **el 100% de las entradas**, y el control igualado en tasa **es el brazo mismo**.
C2 (*CAGR > p95 del control*) y C5 (*bootstrap contra el control promedio*) quedan sin contenido.

**Este error ya estaba resuelto en la serie, y lo copié mal.** El §6 de la 51 lo declara textual para
su candidato B, que también era incondicional:

> *(C2 y C5 no aplican a B: su "tasa" es el 100% y un control igualado en tasa sería el brazo mismo.)*

En la 51 había **dos** familias —una condicionada a un evento, otra no— y el control existía para la
primera. Acá no hay evento: no hay señal que haya seleccionado a quién intervenir, sino una propiedad
**mecánica** del propio trade (su excedente sobre la entrada). La pregunta *"¿es la señal o es la
tasa?"* no tiene referente.

---

## 2. Qué cambia

**Se retiran C2 y C5** de la regla de decisión del §6, por degenerados. **No se los reemplaza por
nada más blando:** el peso pasa a los criterios que sí discriminan un efecto real de un
reordenamiento, y que ya estaban congelados —C4 (bootstrap pareado contra el baseline), C6
(dosis-respuesta sobre cinco brazos), C7 (5 slots), C8 (régimen) y C9 (el resultado, no la etiqueta)—.

| # | antes | ahora |
|---|---|---|
| C2 | CAGR > p95 de 20 controles igualados en tasa | **retirado** (degenerado: el control es el brazo) |
| C5 | bootstrap pareado vs el control promedio | **retirado** (ídem) |
| C1, C3, C4, C6, C7, C8, C9 | — | **sin cambios**, mismos umbrales |

**Los 20 brazos de control no se corren**, y eso además saca 20 simulaciones del costo de cómputo.

---

## 3. Qué NO cambia: el oráculo y el anti-oráculo se quedan, y acá **sí** tienen tasa

Los dos brazos de sanity del §5.4 **siguen siendo gate**, con una precisión que el pre-registro no
había fijado: **la tasa contra la que se igualan es la población diferencial del `k*`** —los trades
que el candidato efectivamente cambia—, no el 100%.

- **`ORACULO_arm`** — baja el umbral a `k*` **sólo** en los trades que **peor** terminan, en la misma
  cantidad por día que la población diferencial del candidato. Tiene que despegar.
- **`ANTI_ORACULO_arm`** — lo mismo en los que **mejor** terminan. Tiene que hundirse.

Los dos usan información futura **a propósito**: son el instrumento, no un candidato. Y acá el
contraste tiene poder, que es justo lo que a la 51 le faltó: la población diferencial va de **36,5%**
(`k=0.00`) a **10,4%** (`k=0.75`), contra el **0,48%** con el que el oráculo de la 51 no pudo
despegar. Si aun con esa tasa el oráculo no se separa del anti-oráculo, la corrida es **INVÁLIDA** y
no hay veredicto — la misma regla, mejor sostenida.

El umbral del §5.4 se reformula sin control: **`ORACULO_arm` > `ANTI_ORACULO_arm` por al menos
**+1.00 pp** de CAGR**, y el candidato tiene que quedar **dentro** del intervalo que ellos dos
definen. Un candidato *fuera* de ese rango sería un resultado imposible para el mecanismo que se
dice estar midiendo, y lo correcto ahí es sospechar de la cañería, no publicar el número.

---

## 4. Lo que esta enmienda no toca

- La grilla, su población medida y el baseline (§2 y §3) — **congelados**.
- Los sanity §5.1 (contabilidad), §5.2 (reproducción, ya verificada: 9.17% / 28.2%), §5.3
  (población diferencial ≥5%) y §5.5 (el umbral muerde ≥10% de trades distintos).
- **§5.6 (semillas del control efectivas) se retira junto con los controles.**
- La regla de selección de `k*` por walk-forward sobre la grilla con población (§6).
- El §7: no se cabla nada en esta tarea.
