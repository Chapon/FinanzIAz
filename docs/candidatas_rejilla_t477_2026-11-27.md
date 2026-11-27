# Veredicto — CANDIDATAS-DE-LA-REJILLA-T170 (Tarea 477) · **CORRIDA INVÁLIDA por el §5.2 — sin veredicto**

**Fecha:** 2026-11-27 · **Pre-registro congelado ANTES de codear:**
`docs/candidatas_rejilla_prereg_t477_2026-11-27.md` (`78d2d60`) ·
**Runner:** `scripts/run_candidatas_t477.py` (el gate de multiplicidad, `romano_wolf_stepdown`, en
`6cea68c`) ·
**Comando (marco primario):** `python scripts/run_candidatas_t477.py --allow-stale-artifacts`
(orden y costo del vivo, 2000 resamples); los secundarios con `--orden alfabetico --costo harness`
y `--orden alfabetico --costo vivo`.

Población: **126** tickers, **141.417** entradas `analyze BUY` PIT, ventana `2016-09-12..2026-09-09`
(los artefactos de la T170), 10 slots, `cap_days=250`, `eval_mode=touch`, `fill_mode=decision`,
gates de re-entrada modelados, sin régimen. Sin red, sin tocar `finanzias.db`. **No se tocó
ninguna perilla viva ni ningún umbral.**

---

## VEREDICTO: **CORRIDA INVÁLIDA — sin veredicto.** La salida viva (`soff_t2.0`) queda como está.

**Falla el sanity §5.2 en el marco primario**, el que decide: el oráculo del stop contra su
control igualado en tasa da **+2,37 pp** de CAGR (umbral ≥ +1,50: pasa) y **−3,61 pp** de caída
(umbral ≤ −5,00: **falla**). Por la regla del pre-registro, sin veredicto, y no se re-especifica
nada para salvarla (precedente T26, T38, T51, T54).

**Para la cuenta, nada cambia.** La carga de la prueba es del que propone mover la política viva,
y ninguna candidata llegó a tener evidencia.

**Lo que la corrida mostró igual, dicho como descriptivo y no como veredicto:** en los tres marcos
que corrieron, **ninguna celda pasa M1**. El p ajustado por Romano-Wolf más bajo es **0,186** en el
marco primario, **0,141** en el alfabético al costo del harness y **0,115** en el alfabético al
costo del vivo, contra un umbral de 0,05. O sea que con el sanity en verde el resultado habría sido
el esperado en el pre-registro, *«ninguna pasa»*. Y en los dos marcos alfabéticos, que sí pasan
todos los sanity, la conclusión es ésa: las cuatro candidatas de la 472 tienen p sin corregir de
0,009 a 0,021, y corregido por haber mirado las 14, de 0,115 a 0,208.

---

## 1. Sanity del instrumento (§5)

| | primario (vivo, vivo) | alfabético, harness | alfabético, vivo |
|---|---|---|---|
| 1. contabilidad | OK | OK | OK |
| **2. oráculo vs control** | **+2,37 / −3,61: FALLA** | +4,76 / −6,75: OK | +3,12 / −8,53: OK |
| 3. reproduce la 473 | **9,75% y 2.325 tomados: OK** | — | — |
| 4. reproduce la T170 y la 472 | — | 8,78% y las 14 celdas: OK | 13,72% y las 14 celdas: OK |
| 5. la barrera `off` no dispara | OK | OK | OK |
| 6. la ruina es determinista | OK | OK | OK |

El instrumento está bien armado: en los marcos alfabéticos reproduce al decimal la viva de la T170
y el ΔCAGR fuera de muestra de cada una de las 14 celdas de la 472, y en el primario la viva da
exactamente lo de la 473. Lo que falla es una propiedad del **marco**: con el orden de candidatos
del vivo, el oráculo del stop —montado sobre `s2.0_t2.0`, donde el stop actúa, como en la T170—
baja la caída la mitad que con el alfabético. Por qué, no se sabe todavía: queda como la **478**.

---

## 2. El marco primario, descriptivo (no es un veredicto)

Δ = celda − viva. C9 a = ruina a 2,60% / 50%, C9 b = a 0,47% / 70%, peor de tres semillas.

| celda | ΔCAGR OOS | p | p RW | folds | Δpeor | Δp1 | ΔDD muestra | ΔDD OOS | C9 a | C9 b | fallaría |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| `s6.0_toff` | +3,85 | 0,028 | 0,186 | 4/5 | +1,66 | −1,78 | −3,15 | −6,18 | +1,62 | +2,40 | M1 |
| `soff_toff` | +3,83 | 0,029 | 0,188 | 4/5 | +0,00 | −1,66 | −1,90 | −5,87 | −1,03 | +1,94 | M1, C9 |
| `s3.0_toff` | +3,09 | 0,105 | 0,337 | 3/5 | −0,81 | −0,05 | −3,88 | −7,34 | −2,16 | −0,21 | M1, D2, C9 |
| `s4.0_toff` | +3,02 | 0,088 | 0,337 | 4/5 | +21,05 | −0,49 | −4,39 | −5,61 | +1,07 | +0,94 | M1 |
| `soff_t3.0` | +2,76 | 0,097 | 0,380 | 4/5 | −0,00 | −0,03 | −0,79 | −5,50 | +0,06 | +1,42 | M1 |
| `s6.0_t3.0` | +2,24 | 0,152 | 0,493 | 4/5 | +1,66 | −0,19 | −4,80 | −5,53 | +2,39 | +2,43 | M1 |
| `s4.0_t3.0` | +1,83 | 0,215 | 0,548 | 3/5 | +21,05 | +0,57 | −7,52 | −5,81 | +1,17 | −0,03 | M1, D2, C9 |
| `s3.0_t2.0` | +1,66 | 0,147 | 0,548 | 3/5 | +17,83 | −0,05 | −4,16 | −2,53 | −2,77 | −2,57 | M1, D2, C9 |
| `s3.0_t3.0` | +0,98 | 0,331 | 0,662 | 2/5 | +17,83 | −0,19 | −2,39 | −7,58 | −1,02 | −1,26 | M1, D1, D2, C9 |
| `s2.0_toff` | +0,44 | 0,409 | 0,743 | 3/5 | +18,64 | +1,19 | −2,83 | −7,02 | −0,19 | −2,63 | M1, D1, D2, C9 |
| `s4.0_t2.0` | +0,22 | 0,419 | 0,789 | 3/5 | +21,05 | −0,03 | −5,23 | −0,99 | −1,91 | −1,70 | M1, D1, D2, C9 |
| `s2.0_t2.0` | +0,14 | 0,493 | 0,789 | 3/5 | +18,64 | +1,42 | +1,15 | −3,43 | −2,53 | −3,30 | M1, D1, D2, D5, C9 |
| `s6.0_t2.0` | +0,07 | 0,397 | 0,789 | 3/5 | +1,66 | −0,03 | −3,05 | −1,78 | −0,20 | +0,49 | M1, D1, D2, C9 |
| `s2.0_t3.0` | −0,67 | 0,590 | 0,789 | 3/5 | +18,64 | +1,52 | −0,47 | −6,95 | −1,23 | −2,50 | M1, D1, D2, C9 |

Tres cosas, todas descriptivas:

- **El orden del vivo reordena la tabla.** Con el alfabético, la primera era `soff_toff` (+3,75
  pp, 5/5); con el del vivo, `s6.0_toff` (+3,85 pp, 4/5), y `s4.0_t3.0` —una de las cuatro de la
  472— baja a +1,83 pp y 3/5. Lo que anticipó la 471: un Δ entre brazos depende del orden.
- **En el marco del vivo la salida viva cae más que casi cualquier celda** (38,3% de caída, la 473):
  13 de las 14 tienen menos caída en la muestra completa (todas menos `s2.0_t2.0`) y las 14 fuera
  de muestra. Con el alfabético era al revés: al costo del harness, las 14 caían más que la viva en
  la muestra completa.
- **`s6.0_toff` es la única que pasaría todo menos M1**: Romano-Wolf la deja en 0,186.

---

## 3. Los marcos secundarios

Los dos reproducen la tabla de la 472 celda por celda (tolerancia 0,0005) y pasan todos los sanity.
En los dos, **ninguna celda pasa M1**:

| | `soff_toff` | `s4.0_toff` | `s6.0_toff` | `s4.0_t3.0` | p RW más bajo |
|---|---|---|---|---|--:|
| alfabético, harness: p → p RW | 0,010 → 0,141 | 0,013 → 0,141 | 0,013 → 0,151 | 0,021 → 0,208 | 0,141 |
| alfabético, vivo: p → p RW | 0,009 → 0,115 | 0,011 → 0,117 | 0,011 → 0,128 | 0,015 → 0,163 | 0,115 |

Y además de M1, las cuatro fallan otros criterios. Al costo del harness, las sin trailing tienen
el peor trade 7,7 a 15,4 pp peor y 4,6 a 6,8 pp más de caída en la muestra completa (D3, D5), y
tres de las cuatro pierden contra la viva con ruina inyectada (C9). Al costo del vivo, las cuatro
fallan D5 y C9.

**Lo que el pre-registro anticipó sobre Romano-Wolf no se cumplió:** esperaba que la correlación
entre celdas dejara el umbral bastante más cerca del p sin corregir que el de Bonferroni. Para la
primera de la tabla no fue así: `soff_toff` queda en 0,141, lo mismo que Bonferroni (0,010 × 14 =
0,14); para las siguientes corrige algo menos (`s4.0_t3.0`, 0,208 contra 0,021 × 14 = 0,29). Lo que
la 472 vio era real como Δ, pero no se distingue de haber elegido lo mejor entre 14.

---

## 4. Qué se concluye, y qué NO

- **Se concluye** que no hay evidencia para mover la salida viva. La corrida que decidía es
  inválida, y los dos marcos válidos dicen que ninguna celda sobrevive a la corrección por
  multiplicidad.
- **No se concluye** que el trailing sobre: la corrida no tiene veredicto. Tampoco que el trailing
  de 2,0 sea el mejor: la diferencia entre las celdas **no se distingue** de haber elegido entre 14.
- **La rejilla:** la T170 la había dado por cerrada con un intervalo equivocado (la 472). Esta
  tarea no la reabre ni la cierra con veredicto. Lo que queda escrito es lo de arriba, y que
  cualquier test de salida nuevo en el marco de la cuenta necesita primero la **478**.
- **No se tocó nada:** ni la política, ni un umbral, ni `engine.py`, ni `gates.py`.

---

## 5. Lo que deja

- **La 478 (SANITY-DEL-ORACULO-EN-EL-MARCO-DEL-VIVO, MEDIA):** con el orden del vivo, el oráculo
  del stop baja la caída 3,61 pp contra su control, y el sanity pide 5,00. Hasta medir por qué,
  ningún test de salida en el marco de la cuenta puede tener veredicto.
- **El gate de multiplicidad queda en el repo** (`romano_wolf_stepdown`): cualquier lectura que
  elija entre varias celdas por su intervalo puede usarlo.
