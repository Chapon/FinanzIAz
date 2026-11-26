# ORDEN-DEL-DIA-SIN-DECLARAR (tarea 473) — el orden de los candidatos, y los veredictos releídos · 2026-11-25

**El harness ordena los candidatos de cada día alfabéticamente, y el vivo por `ml_probability`.** Con
el orden del vivo, la estrategia rinde **9,75% / Sharpe 0,63 / caída 38,3%**, y no los 13,72% / 0,79 /
29,5% que se citaban como *«la estrategia de la cuenta»* (costo del vivo, gates 5 y 5b, sin régimen).
Ahora el desvío se declara en el banner, con su precio.

**Releídos con el orden del vivo, ninguno de los cuatro veredictos de la semana cambia de acción:**
todos siguen en *no tocar nada*. Pero tres cambian de lectura, y uno queda a una condición de pasar
(el Gate 6). No se re-decide nada; va a Chapa.

Instrumento: `scripts/releer_orden_t473.py` (descriptivo). El orden del vivo:
`analysis/orden_del_dia.py`. Tests: `tests/test_orden_del_dia_t473.py`.

## 1. El defecto

`simulate_portfolio` sin `rank_score` procesa los candidatos de cada día en orden alfabético. Ningún
runner desde la T170 le pasa uno: ni `_common_kwargs` de la T219 (que importan la 456, la 457, la
465, la 468 y la 458) ni la T170. El vivo los ordena por `_default_strength("BUY", ml_probability)`
(`paper_trading/strategies.py`). Con ~56 candidatos por día para 10 lugares, el orden decide quién
entra.

La T39 ya había medido que el ranking vivo tiene alpha negativo y decidió no cambiarlo. Lo que no
estaba dicho es que **el harness mide con otro orden**, y `deviations()` no tenía clave para eso.
Lo destapó la 471, donde el signo de un Δ entre brazos se dio vuelta al cambiar el orden.

## 2. Lo que cuesta el orden

| orden | CAGR | Sharpe | caída | trades |
|---|--:|--:|--:|--:|
| alfabético (el harness) | 13,72% | 0,79 | 29,5% | 2.531 |
| **el del vivo** | **9,75%** | **0,63** | **38,3%** | 2.325 |

Costo del vivo, tajada por día, la salida de la T219, gates 5 y 5b, sin régimen, 10 slots, 126
tickers.

## 3. Los veredictos de la semana, releídos

`scripts/releer_orden_t473.py` corre los brazos de cada veredicto con los dos órdenes y los evalúa con
la función de su runner, con el pre-registro sin tocar. **Sanity:** con el orden alfabético reproduce
los cuatro veredictos publicados (y la base, 13,72% / 0,79); con el del vivo, la base da 9,75% / 0,63,
como la 471. **VÁLIDA.**

| veredicto | orden alfabético (publicado) | orden del vivo |
|---|---|---|
| **456** — la estrategia contra SPY + caja (marco de la 468) | NO DECIDIBLE: el pasivo +1,66 pp OOS, IC [−6,77, +10,25] | **NO DECIDIBLE**: el pasivo +0,84 pp, IC [−10,93, +12,63], 3/5 folds |
| **457** — el overlay de σ | NO SE DISTINGUE: ΔSharpe −0,063, IC [−0,220, +0,051] | **NO SE DISTINGUE**: ΔSharpe **+0,046**, IC [−0,074, +0,155] |
| **465** — el régimen contra su caja | DEPENDE: pierde en A (2021-26), gana en B (2017-21) | **DEPENDE, al revés**: gana en A (Sharpe 0,88 contra 0,81) y pierde en B (0,44 contra 0,59) |
| **458** — el Gate 6 | NO MOVER: sacarlo da +0,61 pp, 2/5 folds | **RESTA, PERO NO ALCANZA**: sacarlo da **+2,83 pp**, **4/5 folds**, D3 y D5 pasan; sólo el IC [−1,01, +6,90] cruza el cero |

**Qué dice:**

- **Ninguna acción cambia.** Las cuatro lecturas siguen siendo *no tocar nada*.
- **El signo del overlay se da vuelta** (de −0,06 a +0,05 de Sharpe), siempre dentro del ruido: no
  hay evidencia en ningún sentido.
- **La 465 se invierte**: con el orden del vivo, el escalado le gana a la caja en el tramo reciente
  y pierde en el de las caídas rápidas. *Depende del tramo* sigue siendo la lectura; lo que cambia es
  cuál.
- **El Gate 6 es lo único que se acerca a moverse**: con el orden del vivo cuesta 2,83 pp por año
  fuera de muestra, y pierde en 4 de 5 folds. Falta el bootstrap. Por el pre-registro, no se toca;
  pero es el número a mirar si Chapa quiere revisarlo.

## 4. Qué cambió en el repo

- **El desvío `orden_del_dia`** se declara en todo runner con cartera que no ordene como el vivo
  (`HarnessConfig.orden_del_vivo`, `announce(orden_del_vivo=...)`), con su precio y su marco.
- **`analysis/orden_del_dia.py`**: `orden_del_vivo(score_by)` (el `rank_score` del vivo sobre la
  `ml_probability` del store, con paridad contra `_default_strength`) y `rank_del_orden`.
- **Los textos** que citaban números de la cuenta con el orden alfabético (los desvíos `costos`,
  `regime_scale`, `vol_overlay` y `earnings_blackout`, y `SETTINGS_REFERENCE.md`) dicen con qué orden
  se midieron y qué da con el otro.

## 5. Lo que no se hizo

No se cambió el orden de ningún runner publicado: el alfabético sigue siendo el default, para que
todo reproduzca. Un runner nuevo que quiera medir como la cuenta tiene que pasar
`rank_score=orden_del_vivo(score_by)` y `announce(orden_del_vivo=True)`, además del costo, la tajada y
la regla del lugar (`lugar_del_bloqueado`).
