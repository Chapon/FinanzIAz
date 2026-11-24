# Pre-registro — ACTIVO-CONTRA-PASIVO-DE-IGUAL-RIESGO (tarea 456) · 2026-11-23

**Congelado antes de escribir el runner.** Nada de lo que sigue se cambia después de correr; si
algo tiene que cambiar, va como enmienda fechada y declarada antes de leer ningún Δ.

Origen: `docs/compras_ventas_efectividad_2026-11-23.md` §2, pedido de Chapa (*«buscar formas de
ser más efectivo con las compras y ventas»*).

## 0. Lo que ya se vio, declarado

El doc de origen ya comparó, **sobre la muestra completa**, la estrategia viva de la T170 (8,78% /
Sharpe 0,55 / caída 28,4%) contra SPY y contra mezclas de SPY con caja. Por eso:

- **El gate es fuera de muestra** (§4), y la proporción del pasivo se fija **con una regla
  mecánica sobre el tramo de calibración** (§3), no eligiendo la que mejor salió.
- **Los umbrales no se inventan acá:** son los de la T170 (D1, D2, D4 y D5), congelados el
  2026-09-10 para otra pregunta, antes de que existiera ésta.
- **Una corrección que ya se sabe:** el doc de origen midió SPY desde el 2016-09-12, y la
  estrategia recién opera después de las 250 ruedas de calentamiento (~2017-09). Este runner
  mide los dos brazos sobre **las mismas fechas**, y si la tabla del doc cambia, se corrige ahí al
  cerrar.

## 1. La pregunta

¿La estrategia viva le gana, **fuera de muestra**, a una mezcla pasiva de SPY y caja **con la misma
caída máxima**?

La carga de la prueba es **asimétrica, a favor de lo que hay**: para concluir que el pasivo gana
hacen falta **las cuatro** condiciones del §4.

## 2. Config (la de la T170, sin cambios)

126 tickers (`data/harness_universe_live_acct2.txt`, huella `POPULATION_LIVE_ACCT2.tickers_fp`,
verificada y no impresa), ventana del cohorte `2016-09-12..2026-09-09` (artefactos atrasados:
corre con `--allow-stale-artifacts`, igual que la T219 y la T385), entradas `analyze BUY` PIT,
10 slots, `equal_weight`, `cap_days=250`, `eval_mode=touch`, `fill_mode=decision`, gates de
re-entrada modelados, hard stop **apagado** (`NO_STOP`), trailing 2,0 ATR, TP 4,0 ATR, costos
`CostModel()` (0,10% de comisión + 0,05% de slippage por lado), capital 50.000, caja al 0%.

**Desvíos que quedan sin modelar, y su dirección:** el overlay de volatilidad (tarea 457) y el
Gate 6 (tarea 458). Los dos achican la exposición del vivo: le bajan la caída y el crecimiento, y
como la proporción del pasivo se calibra contra la caída del vivo, la dirección neta sobre el Δ
**no se conoce**. Se declara y no se estima.

## 3. Los brazos (fijos)

| brazo | qué es | rol |
|---|---|---|
| `vivo` | la config del §2 **más el escalado por régimen** a `LIVE_REGIME_SCALE_FACTOR` (0,25 en risk-off, SPY bajo su SMA200, `make_entry_filter(mode="scale")`) | **el del gate**: es lo que corre en la cuenta 2 |
| `vivo_sin_regimen` | el §2 sin escalado: el `soff_t2.0` de la T170 | sanity de reproducción (§5) y descriptivo |
| `SPY_caja` | SPY a proporción constante `w` y el resto en caja, rebalanceado el primer día hábil de cada mes, con los costos de `CostModel()` sobre lo operado | **el del gate** |
| `UNIV_caja` | igual, con el universo de 126 en partes iguales (rebalanceo mensual) en lugar de SPY | **descriptivo**: tiene sesgo de supervivencia |

- **Serie de SPY:** `SPY__max__1d` recortada a la ventana, para que la SMA200 del régimen exista
  desde el primer día (con la `10y`, que arranca el 2016-10-03, el régimen queda abierto hasta
  mediados de 2017). La misma serie es la del pasivo.
- **Calendario:** los dos brazos se miden sobre **las fechas de la curva de equity del `vivo`**,
  que empieza en su primera entrada. El pasivo arranca invertido a `w` ese mismo día, pagando la
  compra.
- **El `vivo` se corre una sola vez, de punta a punta, y se corta.** No hay nada que entrenar, así
  que no se reinicia en cada fold como en la T170. Por eso sus números por fold **no** van a
  coincidir con los de la T170, que reiniciaba la cartera.

**La regla de `w`, congelada.** Tramo de calibración: desde la primera fecha del `vivo` hasta el
**2021-07-31**, que es el fin del train del primer fold de la T170. `w` es la **más alta** de
`0,05, 0,10, …, 1,00` cuya caída máxima en ese tramo **no supera** la del `vivo` en ese mismo
tramo. La misma regla, por separado, da `w` para `UNIV_caja`.

## 4. El gate (fuera de muestra: los cinco folds de test de la T170, 2021-08-01 → 2026-07-31)

| | condición | de dónde sale |
|---|---|---|
| **C1** | ΔCAGR OOS (pasivo − vivo) **≥ +1,00 pp**, sobre el tramo de test completo | D1 de la T170 |
| **C2** | el pasivo gana en **≥ 4 de 5** folds (CAGR de cada fold) | D2 de la T170 |
| **C3** | bootstrap pareado por bloques (bloque 20, 2.000 resamples, semilla 12345) sobre los retornos diarios OOS: **IC95% inferior > 0** | D4 de la T170 |
| **C4** | caída máxima OOS del pasivo **≤ la del vivo + 1,00 pp** | D5 de la T170 |

**Lectura, congelada:**

- **«EL PASIVO GANA»**: C1, C2, C3 y C4 juntas. **No se cablea nada.** Se le presentan a Chapa las
  opciones de la tarea 456: (a) una cuenta paper pasiva nueva al lado de la 2, (b) convertir la 2,
  (c) seguir igual sabiendo el costo, dejado por escrito como en la 124.
- **«LA ESTRATEGIA LE GANA AL PASIVO»**: el espejo: ΔCAGR OOS ≤ −1,00 pp, el vivo gana en ≥ 4 de 5
  folds, IC95% superior < 0 y caída OOS del vivo ≤ la del pasivo + 1,00 pp.
- **Cualquier otra combinación: «NO DECIDIBLE»**, documentado, sin cambios.

**Lo que se espera, escrito antes de correr.** Por el descriptivo del doc de origen, que se vio:
C1 y C2 pasan. **C3 es la que puede fallar**: cinco años de retornos diarios pueden no alcanzar para
separar unos puntos de CAGR, y la T170 vio un IC de 13 pp de ancho. Si falla, el resultado es
«NO DECIDIBLE» y así se publica, aunque el punto estimado sea grande.

## 5. Sanity (si uno falla, la corrida es INVÁLIDA y no hay veredicto)

1. **Reproducción:** `vivo_sin_regimen` da **8,78% / 0,55 / 2.531** (la T170), con las
   tolerancias de la T219 (0,5 pp, 0,05 y 2%). Es una referencia **externa** a esta corrida.
2. **Control del pasivo:** sin costos y con `w = 1`, el retorno total de `SPY_caja` sobre el
   calendario es el cociente de cierres de SPY, con tolerancia 1e-9. Con `w = 0`, la curva queda
   plana.
3. **Contabilidad:** `accounting_ok` en los dos brazos del vivo.
4. **El escalado muerde:** la fracción de entradas del `vivo` con `size_factor < 1` es mayor que el
   1% y menor que el 50%. Por la lección de la T38, para un brazo que escala el chequeo va sobre las
   entradas tocadas, no sobre el agregado.
5. **`w` queda adentro:** la regla da `0 < w ≤ 1`. Si ninguna `w` cumple, la corrida no compara
   nada.

## 6. Descriptivo obligatorio (no decide)

La muestra completa sobre el mismo calendario (crecimiento, Sharpe, caída) para los cuatro brazos;
los cinco folds, uno por uno; `vivo_sin_regimen` contra `SPY_caja`; `UNIV_caja`; el retorno de
cartera en las ventanas de régimen (`2018Q4`, `covid_2020`, `bear_2022`); y la exposición media del
vivo, o sea la fracción de la equity invertida.

## 7. Lo que no hace

No toca la cuenta viva ni ningún setting. No re-decide la T7, la 170 ni la 219. No elige entre
mezclas después de ver el test.
