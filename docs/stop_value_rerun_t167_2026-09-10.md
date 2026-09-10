# Tarea 167 — el T37 re-corrido sobre la muestra del 2026-09-09: **NO-SHIP · corrida VÁLIDA**

**Fecha:** 2026-09-10 · **Pre-registro:** el mismo de la T37, sin enmiendas ni umbrales
tocados (`docs/stop_value_prereg_t37_2026-08-19.md` + enmiendas 1 y 2) ·
**Comando:** `python scripts/run_stop_value_t37.py` (2000 resamples, el del veredicto
publicado) · **Origen:** el instrumento se arregló en la tarea **164**
(`docs/control_resorteado_t164_2026-09-10.md`), y recién con el sanity sano se le puede
creer a este número.

> **Esto NO re-escribe el veredicto de agosto.** Esa corrida midió **otra muestra** (127
> tickers, ventana `2016-07-11..2026-08-07`, 143.096 entradas) y sigue siendo lo que fue. Lo
> que este doc publica es **qué dice el mismo experimento sobre la muestra de hoy** (126
> tickers, `2016-09-12..2026-09-09`, 141.417 entradas).

## 1. El titular

**El veredicto no se reproduce: era SHIP por los nueve criterios y hoy es NO-SHIP por cuatro.**
La corrida es **VÁLIDA** —los nueve sanity en OK, y las **tres** constantes de reproducción
dan exactas (`0.0498` / `0.0878` / `0.1044`)—, así que no hay nada que descartar por
instrumento: lo que cambió es el resultado.

| criterio | publicado 2026-08-27 | **hoy 2026-09-10** |
|---|---|---|
| C1 ΔCAGR fuera de muestra ≥ +1.00 pp | PASA **+2.30 pp** | **FALLA −1.17 pp** |
| C2 maxDD in-sample y OOS ≤ base +1.00 pp | PASA **al filo** (+0.97) | PASA **−11.23 / −0.49** |
| C3 bootstrap pareado, IC95% inferior > 0 | PASA | **FALLA [−1.06, +12.75] p=0.053** |
| C4 ΔSharpe ≥ +0.05 | PASA | PASA +0.255 |
| C5′ régimen con potencia | PASA | PASA (Δ +0.42 pts vs tol 1.00) |
| C6 cola: Δ(peor) y Δ(p1) ≥ −2.00 pp | PASA | **FALLA −12.80 / −1.14** |
| C7 mismo brazo en ≥4/5 folds | PASA | **FALLA 3/5** |
| C8 signo a 5 slots y en modo `close` | PASA | PASA +7.33 / +3.57 |
| C9 ruina | PASA | PASA +5.40 · +5.22 · +3.49 |

**Veredicto:** NO-SHIP **por construcción** — el walk-forward elige `soff_toff` (trailing
**también** apagado), que el §5 del pre-registro declaró **no shipeable**.

## 2. Las dos reservas del doc de agosto eran justo éstas

El veredicto publicado traía **tres reservas adelante**, y las dos primeras describen con
precisión lo que pasó:

1. *«C2 pasa por 0,03 pp … un criterio que pasa por 0,03 pp no es evidencia, es un empate.»*
   **Hoy C2 pasa holgado (−0.49 pp OOS)** — la fragilidad no estaba donde se la esperaba.
2. *«El +2.30 pp fuera de muestra está dominado por un fold, y el procedimiento pierde en 2
   de 5.»* **Hoy el OOS es −1.17 pp y el procedimiento pierde en 3 de 5.** La reserva no era
   retórica: era el resultado, un mes antes.

Eso es lo que hace que esto no sea una sorpresa sino una **confirmación**: el margen fuera de
muestra del candidato dependía de un fold, y al moverse la muestra se fue.

## 3. La rejilla de hoy, que es lo que hay que mirar para decidir

CAGR por combinación, `#` = el baseline pre-registrado (lo vivo **al congelar**, 2026-08-19),
`*` = lo que elige el walk-forward hoy:

```
stop \ trail          2.0        3.0        off
2.0                4.98%#     4.02%      3.33%
3.0                7.10%      8.57%      7.72%
4.0                6.63%      8.67%      7.92%
6.0                6.77%      8.01%      9.46%
off                8.78%      9.31%     10.44%*
```

| brazo | CAGR | Sharpe | maxDD | Δ(peor) |
|---|--:|--:|--:|--:|
| `s2.0_t2.0` (baseline pre-registrado) | 4.98% | 0.36 | 44.2% | −30.1% |
| **`soff_t2.0` (lo que corre hoy en la cuenta 2)** | **8.78%** | **0.55** | **28.4%** | −28.0% |
| `soff_toff` (lo que elige el walk-forward) | 10.44% | 0.62 | 33.0% | **−42.9%** |

**In-sample el brazo vivo sigue ganando y por mucho** (+3.80 pp de CAGR, +0.19 de Sharpe,
**−15.8 pp de maxDD**) contra el baseline de agosto. Lo que **no** sobrevive es el fuera de
muestra, que es el eje con el que C1/C3/C7 deciden. Y el brazo que el walk-forward prefiere
—apagar también el trailing— tiene la **peor cola de la rejilla** (−42.9%), que es exactamente
la razón por la que el §5 lo declaró no shipeable de antemano.

## 4. Qué se concluye, y qué NO

- **Se concluye** que la evidencia con la que se adoptó la política de salida viva
  (`atr_hard_stop_enabled=False`, `atr_trail_mult=2.0`) **no se reproduce** sobre la muestra
  de hoy, con el instrumento sano y sin tocar un umbral.
- **No se concluye** que la política sea mala. El candidato sigue dominando al baseline
  in-sample en las tres métricas y C2/C4/C5′/C8/C9 pasan; lo que falla es la **generalización**
  fuera de muestra y la **estabilidad entre folds**.
- **No se toca nada en vivo acá.** Cambiar o no la política es decisión de Chapa, y ésta es la
  primera vez que una decisión viva queda sin la evidencia con la que se tomó.

## 5. Hallazgo de paso (tarea 169)

El banner del runner **se contradecía solo**: `deviations()` declara *«stop duro ENCENDIDO a
2.0×ATR en el harness vs APAGADO en la cuenta 2 (desde el 2026-08-27)»* y tres líneas después
imprimía `BASELINE = s2.0_t2.0 (la config viva)`, con la rejilla rotulando `# = BASELINE (lo
vivo)`. El desvío es el correcto; los **rótulos** quedaron viejos el día que la cuenta adoptó
el candidato. Corregidos: ahora dicen *«la config que estaba viva al CONGELAR el
pre-registro»*. Un lector de esta corrida habría concluido que *lo vivo rinde 4.98%* cuando lo
vivo rinde **8.78%**.
