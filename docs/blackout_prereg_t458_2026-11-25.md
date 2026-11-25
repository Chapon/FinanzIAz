# Pre-registro — EARNINGS-BLACKOUT-SIN-MEDIR (tarea 458) · 2026-11-25

**Congelado antes de escribir el runner.** Nada de lo que sigue se cambia después de correr; si
algo tiene que cambiar, va como enmienda fechada y declarada antes de leer ningún Δ.

Origen: `docs/compras_ventas_efectividad_2026-11-23.md` §4. El Gate 6 (`earnings_blackout_days: 2`)
frena cada compra a ±2 días corridos de un balance, y nunca se midió: la 96 lo dio por no modelable
(*«no hay fechas de earnings point-in-time a 10 años»*), y Yahoo las tiene desde 2014.

## 0. Lo que ya se vio, declarado

- **El replay del 2026-06-25** (`docs/earnings_blackout_replay_2026-06-25.md`): 6 de 38 round-trips
  reales cayeron a ±2 días de un balance (15,8%) y perdieron en promedio 3,45%. Es una muestra de 38,
  sin contrafactual de cartera.
- **La literatura** apunta a que bloquear cuesta: las acciones rinden más en las semanas de su
  balance (*earnings announcement premium*: Frazzini y Lamont 2007; Barber y otros 2013).
- **Ningún número del harness con el Gate 6 existe**: es la primera vez que se modela.

## 1. La pregunta

¿Sacar el bloqueo le gana a la estrategia con el bloqueo, **fuera de muestra**? La carga de la prueba
es **a favor de lo que hay** (el gate está prendido): para recomendar sacarlo hacen falta **las cinco**
condiciones del §4, que son las de la T170.

## 2. Config

La de la T170 con el costo del vivo (`live_cost_model()`) y la tajada por día: 126 tickers
(`data/harness_universe_live_acct2.txt`, huella verificada), cohorte `2016-09-12..2026-09-09` (con
`--allow-stale-artifacts`), entradas `analyze BUY` PIT, 10 slots, `equal_weight`, `cap_days=250`,
`eval_mode=touch`, `fill_mode=decision`, gates de re-entrada modelados, hard stop apagado, trailing
2,0 ATR, TP 4,0 ATR, la salida de la T219, capital 50.000, caja al 0%. Sin régimen ni overlay en el
gate, como en la T170; los dos van en el descriptivo, que es el marco de la cuenta.

**El Gate 6 modelado** (`analysis/earnings_sim.py`): `entry_filter = filtro_de_balances(fechas, 2)`,
que vale 0 a ±2 días corridos de cualquier fecha de balance conocida del ticker (la regla de
`is_within_earnings_blackout`) y 1 fuera. Las fechas, del almacén `data/earnings_dates/fechas_balance.json`
(`scripts/bajar_fechas_balance_t458.py`, `get_earnings_dates(limit=48)`, capturado el 2026-11-25).

**Lo que el modelo no replica, y su dirección:**

- **La fecha se usa como si se conociera antes.** Las empresas la anuncian semanas antes y
  reprogramar es raro. Dirección: ninguna conocida.
- **El motor mira sólo la próxima fecha** del calendario de Yahoo, cacheada; acá, todas. Si el
  calendario se actualiza antes de que pasen los dos días posteriores, en vivo el bloqueo es más
  corto que acá: el modelo **sobreestima** cuánto bloquea.
- **El lugar del pick frenado:** en vivo se queda vacío en ese scan (tarea 471); en el simulador
  pasa al siguiente candidato. Dirección: el modelo **subestima** el costo del bloqueo.
- **Un ticker sin fechas no se bloquea nunca**, como en vivo.

## 3. Los brazos (fijos)

| brazo | qué es | rol |
|---|---|---|
| `vivo` | el §2 con el Gate 6 a ±2 días | **el del gate** (lo que hay) |
| `sin_bloqueo` | el §2 sin el Gate 6 | **el del gate** (el desafiante) |
| `vivo_cuenta`, `sin_bloqueo_cuenta` | los dos con el escalado por régimen a ×0,25 y el overlay de σ: el marco de la cuenta | descriptivo |
| `sin_bloqueo_harness` | `sin_bloqueo` con `CostModel()` | sanity de reproducción |

Cada brazo se corre una sola vez, de punta a punta, y se corta: no hay nada que entrenar.

## 4. El gate (los cinco umbrales de la T170)

Fuera de muestra = los cinco folds de test de la T170, 2021-08-01 → 2026-07-31. Dentro de muestra =
de la primera fecha a 2021-07-31.

| | condición |
|---|---|
| **D1** | ΔCAGR OOS (`sin_bloqueo` − `vivo`) **≥ +1,00 pp** |
| **D2** | `sin_bloqueo` gana en **≥ 4 de 5** folds (CAGR de cada fold) |
| **D3** | cola por trade, muestra completa: Δ(peor trade) y Δ(percentil 1) **≥ −2,00 pp** (`tail_stats` de la T37) |
| **D4** | bootstrap pareado sobre los retornos diarios **OOS** (bloque 20, 2.000 resamples, semilla 12345): **IC95% inferior > 0** |
| **D5** | caída máxima de `sin_bloqueo` **≤** la de `vivo` **+ 1,00 pp**, dentro de muestra **y** fuera |

**Lectura, congelada:**

- **«SACAR EL BLOQUEO»**: las cinco. Se recomienda a Chapa `earnings_blackout_days: 0` (con la app
  cerrada); el cambio lo decide Chapa.
- **«EL BLOQUEO RESTA, PERO NO ALCANZA»**: D1 pasa y alguna otra no. No se toca nada.
- **«NO MOVER»**: D1 no pasa. No se toca nada.

El D4 se mide sobre la misma muestra que el D1 (los retornos OOS), a diferencia de la T170 (tarea
472).

**Lo que se espera, escrito antes de correr.** Con ±2 días corridos alrededor de ~4 balances por año,
el gate tapa ~5 días de cada ~91: algo más del 5% de las entradas si las señales no se concentran
cerca de los balances. Con el premium de la literatura, `sin_bloqueo` debería ganar algo; con cinco
años de OOS, lo más probable es que D1 o D4 no alcancen: **«NO MOVER»** o **«RESTA, PERO NO
ALCANZA»**.

## 5. Sanity (si uno falla, la corrida es INVÁLIDA y no hay veredicto)

1. **Reproducción:** `sin_bloqueo_harness` da **8,78% / 0,55 / 2.531** (la T170) y `sin_bloqueo` da
   **13,72% / 0,79** (la 468).
2. **Cobertura del almacén:** al menos el 90% de los 126 tickers tiene fechas, y de esos, al menos el
   90% tiene una fecha anterior al arranque del cohorte (2016-09-12).
3. **El gate muerde y no de más:** la fracción de entradas ofrecidas que el filtro suprime en `vivo`
   está entre el **2%** y el **25%**. (El 15,8% de junio es otra medida —round-trips cerrados, n = 38—
   y va al lado, sin compararse como número.)
4. **Paridad con el motor:** `filtro_de_balances` da 0 exactamente cuando
   `is_within_earnings_blackout` da `True`, en un test con fechas a −3, −2, 0, +2 y +3 días.

## 6. Descriptivo obligatorio (no decide)

Muestra completa de los cuatro brazos de la config (CAGR, Sharpe, caída, trades, suprimidas); los
cinco folds; el retorno medio por trade de las entradas que el gate suprime, medido en `sin_bloqueo`
(lo que el bloqueo se pierde), contra el de las demás; el marco de la cuenta; y la cobertura del
almacén por ticker.

## 7. Lo que no hace

No toca la cuenta ni ningún setting. No elige otro N de días después de ver el resultado: un barrido
sería otra tarea.
