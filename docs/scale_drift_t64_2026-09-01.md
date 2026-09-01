# SCALEDRIFT (tarea 64) — calibración del umbral de drift de escala

**Fecha:** 2026-09-01 · **Instrumento:** `scripts/measure_scale_drift_t64.py` (offline, reproducible)
· **Origen:** hallazgo al cerrar la tarea 63 · **Severidad:** BAJA-MEDIA (latente, path vivo)

---

## 1. El agujero

Todo el aparato de escala —E5, y la **63** encima— se dispara **sólo cuando el precio vivo se sale
de la banda** (`price_sanity_band_pct`, 50%). Un ajuste espurio **menor** —un split fantasma de 1.3,
un re-ajuste mal conciliado— deja el histórico fuera de escala con el precio vivo **adentro** de la
banda: no hay WARNING, no se evalúa disputa, no corre nada.

**Y duele igual, porque la cotización no es lo único que se usa.** El **ATR y las barreras** salen
del histórico (`paper_history_period`, default `2y`), así que un histórico 1,3× chico da un stop
**1,3× más ajustado** que el que la política dice, sin que nada lo declare. Es el mismo mecanismo que
la 63 midió en AVB a 2,793× — pero por debajo del radar.

## 2. Por qué hizo falta un umbral, y no se pudo reusar el truco de la 63

La 63 define la disputa por el **veredicto**, no por un porcentaje: si un frame dice *"en banda"* y
otro dice *"fuera de banda"* sobre el mismo precio, el cache no puede arbitrar. Esa definición es lo
que la hace robusta — el drift legítimo nunca la dispara — pero **necesita un rechazo previo**.

Acá no hay rechazo, así que no hay veredicto que comparar: hay que mirar la **magnitud** de la
diferencia entre frames, y eso es un umbral. El enunciado de la tarea decía que ése era el problema:

> *"por debajo de ~10% el drift **legítimo** del re-ajuste por dividendos entre dos fetches separados
> se vuelve indistinguible de una corrupción, así que ese umbral hay que **calibrarlo sobre los
> frames reales**, no elegirlo de memoria."*

## 3. Criterio de aceptación, fijado ANTES de medir

El umbral se acepta si cae en un hueco que cumple las dos condiciones:

1. **Arriba** del máximo drift legítimo observado en el cache real, con margen — si no, bloquearía
   entradas sanas.
2. **Abajo** del split más chico que existe en la práctica (3:2 ⇒ **33%** de desvío) — si no, dejaría
   pasar el caso que la tarea vino a atrapar.

Si no hubiera hueco, la conclusión correcta era **no cablear nada** y declarar el drift sin política.

## 4. Cómo se mide

Sobre las fechas que **solapan** entre los dos frames, nunca sobre el último close de cada uno: los
frames se bajan en momentos distintos, así que sus puntas difieren por el **movimiento real** del
precio. Sobre las mismas fechas, lo único que puede quedar es la escala. Mínimo **5** fechas
solapadas (el único caso real, AVB, solapa 16).

## 5. El resultado

Barrido del cache OHLCV vivo: **514** tickers con parquet `1d`, **140** con dos o más frames ⇒
**365** pares comparables.

| medida | \|ratio mediano − 1\| |
|---|--:|
| p50 | **0,000%** |
| p90 | 0,741% |
| p95 | 0,831% |
| p99 | 1,702% |
| **máx** | **64,196%** |

Y el detalle de la cola, que es donde está la respuesta:

| \|dev\| | ticker | frames | fechas | ratio | spread |
|--:|---|---|--:|--:|--:|
| **64,196%** | **AVB** | 2y/10y | 16 | 0,358038 | 1,000000 |
| 1,719% | PFE | 2y/5y | 437 | 0,982807 | 1,000000 |
| 1,702% | GIS | 2y/1y | 251 | 0,982985 | 1,000000 |
| 1,569% | UPS | 2y/10y | 484 | 0,984306 | 1,000000 |
| 1,468% | NEE | 2y/5y | 437 | 0,985319 | 1,000001 |
| 1,188% | ACN | 10y/1y | 251 | 0,988119 | 1,000000 |
| 1,071% | F | 2y/10y | 484 | 0,989286 | 1,000001 |

**Entre 1,719% y 64,196% no hay NADA.** El hueco es de **37×**, y el único par que lo cruza es el
split fantasma de 2,793 que destapó la 63.

## 6. El umbral: **10%**

Cae en el medio del hueco: **5,8×** el máximo legítimo observado, y **3,3×** por debajo del split más
chico de la práctica. Los dos criterios del §3, con margen.

- **Falsos positivos medidos sobre el cache real: 0 de 364** pares legítimos.
- **Detecciones: 1** — AVB, el caso conocido.

Vive como `scale_drift_tolerance_pct` (default `0.10`); `0` lo apaga, misma convención que
`price_sanity_band_pct`.

## 7. Dos cosas que la medición corrigió, y valen más que el número

**(a) La premisa del enunciado no se sostiene.** El backlog daba por sentado que el drift legítimo
llegaba hasta cerca del 10% y que por eso el umbral iba a quedar al filo. **No**: el drift legítimo se
termina en **1,72%**. El 10% no está al filo de nada — está a casi 6× de distancia. La parte cara de
la tarea (calibrar contra una frontera difusa) resultó no existir, y eso **sólo se supo midiendo**.

**(b) La dispersión NO discrimina, y era el otro candidato obvio.** Antes de mirar la magnitud, la
hipótesis natural es *"una corrupción es un re-escalado constante; el drift legítimo, ruido"*. Se
midió el **spread** (máx/mín del ratio por fecha) en los 365 pares: máximo **1,0140**, o sea el ratio
es **constante por fecha en todos**, legítimos incluidos. Un re-ajuste por dividendos también es un
re-escalado limpio. La única diferencia con una corrupción es el **tamaño** — que es exactamente por
lo que el guard tuvo que quedar apoyado en un umbral de magnitud y no en una forma.

## 8. Qué se hace con un ticker en disputa

**Se declara siempre, y se bloquea la ENTRADA — no la salida.** Es la misma asimetría que shipeó la
63 un nivel más arriba: el ATR y las barreras salen del histórico en duda, así que entrar sería
abrir con un stop calculado en otra escala; **entrar es opcional, salir no**, y quedar trapeado es
peor que salir con un histórico dudoso.

Lo que **no** se hace, y es deliberado:

- **No se excluye al ticker del universo.** Eso lo volvería invisible — el modo de falla exacto que
  la 63 vino a arreglar.
- **No se prefiere el frame que coincide con la cotización.** Darle a la cotización el rol de árbitro
  es lo que hizo E5, y la 63 mostró que ese lado también se pudre. Con los dos frames en desacuerdo
  el cache **no puede arbitrar**, y la conducta correcta es no apostar plata nueva sobre él.

**Efecto vivo hoy: ninguno.** El único ticker que supera el umbral es AVB, cuyas entradas ya están
bloqueadas por la 63 (y por encima de la banda). El guard nuevo entra en un universo donde **0 de
140** tickers cruzables lo disparan: es defensa para el próximo caso, no un cambio de conducta.

## 9. Dónde corre

- **Declaración incondicional** en `run_scan`, después del warm-up de la cache (o sea sobre el cache
  más fresco que va a haber ese scan) — `_declare_scale_drift`. Offline y barato: **130 tickers en
  0,6 s**. Best-effort: nunca corta un scan.
- **Política** en `_price_out_of_band`, que es el punto donde hay un lado (BUY/SELL) que mirar.
- **No** se toca el guard del *fetch*: el drift está en el **histórico**, no en la cotización, así
  que rechazar el precio vivo por esto sería acusar al dato sano.
