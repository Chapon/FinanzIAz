# Auditoría de decisiones de trading — 2026-06-09

Pregunta: ¿las órdenes ejecutadas fueron decisiones correctas, y mejoró la calidad de decisión a medida que el código evolucionó? Base: 69 órdenes filled de "Sim Principal" (2026-04-24 → 2026-06-08), 32 ciclos cerrados, 445 snapshots de equity, forward returns calculados contra `historical_data_cache`.

## Las tres eras del código

Los cortes salen de los milestones reales del repo. **E1 "inicial"** (24-abr → 17-may): HMM + stacking activos, comisiones legacy (%), sin signal_score persistido, sin ATR stops. **E2 "gates+score"** (18-may → 1-jun): modelo de comisiones tiered, signal_score en órdenes, ATR stops activos — pero HMM + stacking todavía ON. **E3 "kill_only"** (2-jun → hoy): XGB + vol_overlay solamente, min_trade $250 desde el 5-jun.

| Era | Ciclos | Win rate | P/L | P/L% medio | Hold medio | Equity | Mercado* | Costos |
|---|---|---|---|---|---|---|---|---|
| E1 | 12 | 75% | +$3,470 | +2.52% | 6.7d | **+5.75%** | +0.88% | 15.0 bps |
| E2 | 17 | 41% | −$2,061 | −0.32% | 3.6d | **−3.96%** | +1.66% | 6.1 bps |
| E3 | 3 | 67% | +$138 | +1.36% | 4.7d | **+2.90%** | +0.41% | 5.9 bps |

\* Mediana del retorno de ~73 tickers cacheados en la misma ventana (proxy de watchlist; hereda survivorship).

La lectura ingenua sería "el código nuevo de E2 empeoró las cosas". La lectura correcta es otra: en E2 el motor **compró bien y vendió mal**. Los BUYs de E2 tuvieron forward return a 5 días de **+6.97% promedio** (los mejores de las tres eras) — la selección de entradas mejoró con el score. Pero el equity cayó −3.96% en un mercado +1.66% porque los exits cortaron esas posiciones a los 1-3 días. E3 es la única era con alpha y buen win rate simultáneos, aunque con n=3 es dirección, no veredicto.

## Hallazgo central: el eslabón débil son los SELLs por señal

En las tres eras, después de vender, el precio siguió **subiendo** (mediana del forward a 5 días post-SELL: +0.84% en E1, +3.75% en E2; a 20 días en E1: +5.8%, con 0 de 3 ventas "correctas"). Solo 11 de 27 ventas con datos evitaron una caída. Los SELLs salen con ml_probability entre 0.22 y 0.47 — el modelo dice "55-78% de probabilidad de que NO suba" y el mercado lo contradice sistemáticamente: las señales SELL están descalibradas hacia el pesimismo.

Casos ilustrativos: **MU** comprado el 18-may, vendido a +7.3% al día siguiente — subió +26% más en los 5 días posteriores. **ON** vendido a −3.9% tras 1 día — rebotó +12.3% en 5 días. **MRVL** es el caso extremo: vendido el 27-may a −2.8% el mismo día de la compra; el 2-jun reportó y voló de $219 a $316 (+52% desde nuestra venta a 5 días). El motor lo recompró el 8-jun a $298 — pagando $100 más por share que donde lo soltó.

El **churn** agrava: el hold medio cayó de 6.7 días (E1) a 3.6 (E2), con 8 ciclos de 0-2 días. KO se operó 3 veces entre el 21 y el 28 de mayo (neto ≈ −$265 más costos); el anti-whipsaw no lo frenó porque el gate solo mira si el ciclo anterior fue perdedor, y el primero fue ganador.

## Lo que sí funcionó

**El signal_score discrimina.** Ciclos con score de entrada alto (≥0.71): 62% win rate, +1.02% medio. Score bajo: 38% y +0.22%. Con n=16 es sugestivo, no concluyente, pero apunta en la dirección correcta y justifica usar el score más agresivamente.

**Los ATR stops dieron saldo positivo.** 4 disparos: WMT (stop duro, −7%) siguió cayendo −4.6% después — salida correcta; KLAC (trail) protegió +2.3% de ganancia; LRCX (trail) salida neutra; MO (trail, −2%) fue whipsaw (+3.8% después). 2 claramente buenos, 1 neutro, 1 malo — y el rol del stop es asimétrico: el WMT evitado vale más que el MO perdido.

**Los costos bajaron 15.0 → 5.9 bps** con el modelo tiered (18-may). Sobre ~$300k de notional por era, son ~$280 por era ahorrados.

**La peor pérdida individual fue de sizing, no de señal.** MLTX 12-may: $26,239 en un solo biotech ilíquido (≈50% del equity del momento) → −$2,582 (−9.8%). Hoy ese ticket no pasaría: el ADV cap (T10) lo habría recortado y min_trade/max_weight acotan el resto — pero `paper_adv_cap_pct` sigue en 0.0 (OFF).

## Recomendaciones, en orden de impacto esperado

**1. Atacar la calibración de exits (es T07 del roadmap, hoy PENDING — este análisis es su caso de negocio).** Opciones concretas, de menor a mayor invasividad: exigir confirmación de SELL en 2 scans consecutivos antes de ejecutar; bajar el umbral de SELL (vender solo con prob < 0.25 en vez de < ~0.45); subir `paper_min_holding_minutes` para forzar holds más cercanos a E1 (6-7 días) que a E2 (3.6). Cualquiera de las tres se puede validar en el harness contra los 32 ciclos históricos antes de tocar producción.

**2. Activar el ADV cap y auditar max_position_weight.** El código ya está shipped y testeado; es un setting. Previene el próximo MLTX.

**3. Usar el signal_score en el exit, no solo en la entrada.** Hoy un SELL con score 0.45 ejecuta igual que uno con 0.20. Una histéresis simple (no vender si el score de exit está en zona gris 0.35-0.50 y la posición tiene menos de N días) capturaría buena parte del opportunity cost medido. Conecta con el follow-up abierto de signal_score bypass.

**4. Medir esto de forma continua.** Agregar al dashboard un panel de "opportunity cost post-SELL" (forward return 5/20d después de cada venta). Es la métrica que este informe calculó a mano y la que dirá si T07 funciona. Barato: la infraestructura de `dashboard_data.py` ya existe.

**5. El Catalyst Engine ataca exactamente el caso MRVL.** Vendimos por señal técnica el día antes de un catalyst de earnings masivo. T-CAT-4 (impact score) podría vetar SELLs de baja convicción cuando hay catalyst positivo inminente — un "earnings blackout para exits débiles", simétrico al que ya existe para BUYs. Anotarlo como candidato de diseño para T-CAT-4.

**6. Housekeeping:** hay 3 órdenes clavadas en status `approved` (limbo pre-fix de `approve_order`) — correr `reconcile_account` o marcarlas a mano.

## Caveats

Muestras chicas (12/17/3 ciclos por era) — los contrastes E1/E2 son fuertes pero un solo trade mueve los promedios; los forward returns usan la cache con `auto_adjust=True` (sesgo conocido del data audit, menor en ventanas de 5-20 días); el proxy de mercado es la mediana de la watchlist (survivorship); y las eras confunden código + régimen de mercado — el harness con settings de cada era sobre el mismo período sería el experimento limpio si se quiere confirmar causalidad.
