# LUGAR-DEL-BLOQUEADO (tarea 471) — medición · 2026-11-25

**Descriptivo, no decide nada.** En vivo, una compra que frena un gate se queda con su lugar en ese
scan; el simulador se lo daba al siguiente candidato. Ahora el simulador tiene la regla del vivo
(`simulate_portfolio(lugar_del_bloqueado=True)`), y el desvío se declara con su precio.

**El resultado que importa:** cuánto vale la diferencia **depende de cómo se ordenan los candidatos
del día**, y el harness no los ordena como el vivo. Con el orden del vivo, la regla que el vivo ya
tiene es la **mejor** de las dos: cambiar el motor para pasarle el lugar al siguiente costaría 1,3
a 1,4 pp por año. **No hay nada que cambiar en el motor.** Y el orden en sí es un desvío más grande,
que nadie declaraba: la tarea **473**.

Instrumento: `scripts/medir_lugar_t471.py`. Tests: `tests/test_lugar_del_bloqueado_t471.py`.

## 1. Qué pasa en vivo

`generate_trades_analyze_single` (`paper_trading/strategies.py`) toma como picks los primeros
candidatos no tenidos hasta llenar los lugares libres (`ranked[:free_slots]`), y **después** el
motor corre los gates de compra (`engine.py`: tamaño mínimo, Gate 5, Gate 5b, Gate 6). Si un pick
cae en un gate, su lugar queda vacío en ese scan.

En la cuenta 2 (`paper_scan_candidates`, copia de la DB del 2026-11-25): **36 de 381 scans** desde el
2026-10-02 tuvieron un pick frenado y candidatos esperando, en 6 días. Todos por el Gate 6 (TGT, 20
scans el 2026-11-20, con 87 candidatos detrás; KMB, UNP, RTX) o por el tamaño mínimo. **Ninguno por
el Gate 5 ni el 5b**: de 27 ventas en pérdida desde el 2026-09-25, en 20 casos el ticker volvió a ser
candidato dentro de 7 días, y nunca quedó entre los picks.

## 2. La medición

Costo del vivo, tajada por día, la salida de la T219, gates de re-entrada modelados. Tres marcos: los
gates 5 y 5b solos; más el Gate 6 de la 458; y el de la cuenta (régimen ×0,25 y Gate 6; el overlay no
se combina con esta regla). Con el orden del harness, la regla de hoy reproduce la 468 (13,72% / 0,79)
y la 458 (13,14% / 0,77).

**Con el orden alfabético del harness** (lo que corrieron todos los runners desde la T170):

| marco | regla | CAGR | Sharpe | caída | CAGR OOS | lugares perdidos |
|---|---|--:|--:|--:|--:|--:|
| gates 5 y 5b | pasa (hoy) | 13,72% | 0,79 | 29,5% | 9,18% | — |
| | pierde (vivo) | 12,44% | 0,78 | 20,1% | 8,45% | 1.215 |
| + Gate 6 | pasa | 13,14% | 0,77 | 29,7% | 8,58% | — |
| | pierde | 12,59% | 0,79 | 19,8% | 8,10% | 1.501 |
| cuenta | pasa | 11,05% | 0,76 | 20,7% | 6,04% | — |
| | pierde | 10,10% | 0,74 | 16,5% | 5,80% | 1.501 |

**Con el orden del vivo** (`ml_probability` del store, como `_default_strength`):

| marco | regla | CAGR | Sharpe | caída | CAGR OOS | lugares perdidos |
|---|---|--:|--:|--:|--:|--:|
| gates 5 y 5b | pasa | 9,75% | 0,63 | 38,3% | 11,58% | — |
| | pierde | 8,88% | 0,59 | 39,1% | 12,07% | 142 |
| + Gate 6 | pasa | 7,25% | 0,49 | 38,2% | 8,75% | — |
| | pierde | **8,69%** | **0,59** | 37,2% | **10,80%** | 373 |
| cuenta | pasa | 6,34% | 0,49 | 30,8% | 8,56% | — |
| | pierde | **7,64%** | **0,59** | 33,2% | **11,18%** | 373 |

## 3. Qué dice

- **Con el orden alfabético, el Gate 5 frena muchos picks** (1.215 lugares perdidos en 10 años): un
  ticker recién vendido en pérdida vuelve a quedar arriba, porque su lugar en el abecedario no
  cambia. **Con el orden del vivo, 142**, y eso cierra con lo que se vio en la cuenta (ninguno en
  siete semanas).
- **Con el orden del vivo y el Gate 6, perder el lugar es mejor** que pasarlo: +1,44 pp de CAGR,
  +2,05 pp fuera de muestra, Sharpe 0,59 contra 0,49. En el marco de la cuenta, +1,30 pp y +2,62 pp
  fuera de muestra, con 2,4 pp más de caída. Es consistente con lo que midió la T39 (el ranking vivo
  tiene alpha negativo, así que el siguiente candidato no es mejor que la caja), aunque eso no se
  midió aparte acá.
- **Para el motor:** la regla que tiene es la mejor de las dos con el orden que usa. No se propone
  ningún cambio.
- **Para el harness:** el desvío `lugar_del_bloqueado` se declara en el banner de todo runner que
  modela un gate de compra, con estos números.

## 4. El hallazgo mayor: el orden de los candidatos (tarea 473)

Con la regla de hoy y los gates 5 y 5b, la estrategia da **13,72% / 0,79 / 29,5%** con el orden
alfabético y **9,75% / 0,63 / 38,3%** con el orden del vivo: ~4 pp por año y 8,8 pp de caída. Todos
los runners desde la T170 corren sin `rank_score` (alfabético), así que los números que se citan
como *«la estrategia de la cuenta»* —el 8,78% de la T170, el 13,72% de la 468— son de una estrategia
con otro orden que el de la cuenta. Y como muestra la 471, **un Δ entre brazos también puede cambiar
de signo** con el orden. El orden no aparece entre los desvíos del banner.

## 5. Las correcciones de texto

- `simulate_portfolio`: el docstring decía *«el slot se le ofrece al siguiente, igual que en vivo»*;
  ahora dice que en vivo no, y cómo se modela.
- `docs/stop_loosen_prereg_t34_2026-08-18.md` §11: una nota fechada que corrige la misma afirmación,
  sin tocar el pre-registro.
