# Tarea 164 (CONTROL-RESORTEADO) — el control igualado dejaba de ser el mismo control

**Fecha:** 2026-09-10 · **Tipo:** gate técnico sobre el **instrumento** (no toca el motor, no
mueve ningún umbral) · **Origen:** hallazgo al verificar el re-anclaje de la tarea 156.

## 1. El defecto, en una línea

`random_stop_filter` —el **control igualado en tasa** contra el que se mide el oráculo de
salidas— sorteaba con `blake2b("{semilla}|{fecha}|{índice de barra}")`. El índice es
posicional, así que **cualquier refresh que mueva el `start` del cohorte re-sortea el
control entero**. Y a la clave le faltaba el **ticker**, así que todos los tickers que
compartían índice recibían la **misma** decisión.

Medido antes de arreglarlo, sobre un frame de 200 ruedas:

| qué se mide | resultado |
|---|---|
| decisiones que cambian al recortar **24 barras de la cabeza**, para las **mismas fechas** | **90 de 176 (51%)** |
| decisiones idénticas entre **dos tickers distintos** con las mismas fechas | **176 de 176** |

Eso no es deriva: es **medio control nuevo** en cada refresh, y un control que elige *por
fecha* en vez de *por (ticker, fecha)*. Era la tarea **40**, declarada el 2026-08-19 —*«el
brazo aleatorio no es una función pura de (semilla, ticker, fecha)»*— y dejada sin migrar.

## 2. Lo que costaba

El sanity `oracle_quality_ok` (compartido por T26b/T37/T47) es una **conjunción**:
`ΔCAGR ≥ +1.50 pp` **y** `ΔmaxDD ≤ −5.00 pp`, los dos del oráculo contra ese control.

| | ΔCAGR | ΔmaxDD |
|---|--:|--:|
| T26b publicado (2026-08-16) | +3.72 pp | **−15.19 pp** |
| T37 publicado (2026-08-27) | — | **−17.59 pp** |
| 2026-09-10, control **viejo** | +5.03 pp | **−4.30 pp** ⇒ FALLA |
| 2026-09-10, control **estable** | +4.76 pp | **−6.75 pp** ⇒ OK |

El cruce del umbral dejó **INVÁLIDAS dos corridas con veredicto publicado VÁLIDO** (T37 y
T47). Y el T47 **imprimía el número de la pata que PASA** (`[FALLA] … +5.03pp de CAGR`), así
que el rechazo no se podía entender leyendo la salida — eso se arregló primero (`0522fa2`).

## 3. El arreglo

`StopFilter` pasa de `(bars, i)` a `(bars, i, ticker)`; `replay_cycle` acepta
`ticker=""` keyword-only y `portfolio_sim` le pasa el que ya tiene. El sorteo queda
`blake2b("{semilla}|{ticker}|{fecha}")` — **sin índice**. Los dos filtros oráculo aceptan el
tercer argumento y lo **ignoran**: deciden con el futuro del propio frame, que ya es por
ticker. Con el ticker vacío el sorteo **revienta** en vez de volver al defecto en silencio.

Invariantes en `tests/test_control_resorteado_t164.py` (11 tests): recortar la cabeza no
cambia **ninguna** decisión, agregar cola tampoco, dos tickers reciben sorteos distintos, la
tasa se sostiene **ticker por ticker**, y sigue siendo determinista entre procesos. Probado
por mutación: restaurar la clave vieja pone 4 en rojo.

## 4. La re-medición, y acá está lo que importa

Cuatro runners re-corridos (`--resamples 20`). **Ningún umbral se tocó.**

| runner | publicado | hoy, control viejo | hoy, control estable |
|---|---|---|---|
| **T47** | VÁLIDA · NO-SHIP por C3 y C7 | INVÁLIDA | **VÁLIDA · NO-SHIP por C3 y C7** — reproduce **exacto** |
| **T37** | VÁLIDA · **SHIP por los nueve** | INVÁLIDA | **VÁLIDA · NO-SHIP** (C1, C6, C7) |
| **T34** | VÁLIDA · NO-SHIP por C6 y C5 | no medido | VÁLIDA · NO-SHIP por C6 |
| **T26b** | VÁLIDA · NO-SHIP por C5 | no medido | **sanity FALLA** (ΔCAGR 1.26 · ΔmaxDD −3.85) ⇒ INVÁLIDA |

Las 17 constantes de reproducción siguen **exactas** en los cuatro (T37 3/3, T47 2/2).
El brazo **oráculo no se movió** (10.94% / 27.1% antes y después): lo único que cambió es el
control, que es el arm que se arregló — la atribución es limpia.

### 4.1 El T37 vuelve a ser válido y su veredicto **ya no es el mismo**

Con el instrumento sano, sobre la muestra refrescada:

```
C1  FALLA  ΔCAGR fuera de muestra ≥ +1.00 pp     -1.17 pp
C6  FALLA  cola: Δ(peor) y Δ(p1) ≥ -2.00 pp      -12.80 / -1.14 pp
C7  FALLA  mismo brazo en >=4/5 folds            3/5
```

**C1, C6 y C7 son deterministas** —no dependen del número de resamples—, así que el NO-SHIP
no es un artefacto del smoke. In-sample el candidato sigue ganando (`soff_t2.0` 8.78% vs
`s2.0_t2.0` 4.98%); lo que no sobrevive es **fuera de muestra**, y el walk-forward elige en
3 de 5 folds un brazo con el **trailing apagado** que el propio §5 declaró no shipeable.

**Y eso toca la política viva.** El candidato `soff_t2.0` —stop duro apagado, trailing 2.0—
es **exactamente** lo que corre hoy en la cuenta 2 (`atr_hard_stop_enabled=False`,
`atr_trail_mult=2.0`, verificado contra el `settings.json` vivo). O sea que la evidencia que
sostiene la política de salida viva **no se reproduce sobre la muestra de hoy**. Eso **no se
decide acá**: abre la tarea **167**, con re-corrida completa a 2000 resamples.

### 4.2 El T26b no se recupera, y la atribución queda incompleta

Su sanity falla por las **dos** patas (ΔCAGR 1.26 contra 1.50; ΔmaxDD −3.85 contra −5.00).
No es el mismo experimento que el T47 aunque comparta código: su oráculo rinde 6.89% contra
el 10.94% del T47. **No lo medí con el control viejo**, así que no puedo atribuir cuánto de
esto es el refresh y cuánto el arreglo; lo que sí sé es que en T37/T47 el control estable
**mejoró** el ΔmaxDD (−4.30 → −6.75), así que es implausible que el arreglo lo empeore. Queda
como tarea **168**.

## 5. Lo que este arreglo NO hace

- **No mueve ningún umbral.** Mover el umbral para que una corrida pase sería arreglar el
  termómetro cambiándole las marcas.
- **No re-escribe ningún veredicto publicado.** Lo que cambia es qué dice el runner **hoy**;
  el veredicto de agosto se midió sobre otra muestra y sigue siendo lo que fue.
- **No toca el motor ni la política viva.** El T37 es un harness; que su veredicto no se
  reproduzca es evidencia para una decisión, no la decisión.
- **No cubre los demás sanity no anclados.** Este arreglo explica **uno** (el del oráculo vs
  control). El inventario de umbrales de sanity comparados contra literales —y cuáles de
  ellos el refresh mueve— sigue siendo la pata (a) de la 164, sin cerrar.
