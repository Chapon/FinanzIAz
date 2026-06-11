# T-CAT-6 — Backtest del exit-veto (Gate 2c). Decisión de activación

Fecha: 2026-06-11. Decide la activación del exit-veto de T-CAT-4
(`paper_catalyst_exit_veto_enabled`) contra los kill-criteria pre-registrados en
`docs/catalyst_t_cat_4_design.md` §7. Ejecutado en sandbox sobre el backup limpio
`backups/finanzias_2026-06-11_10-06-50_daily.db` (la DB viva da malformed vía el
mount Linux mientras el engine de Windows escribe — incoherencia virtiofs conocida).
Read-only; nada se escribió a la DB ni al engine. Script: `/tmp/tcat6.py` + `tcat6b.py`
(reproducible; importa los módulos reales `analysis/impact_score.py` y
`analysis/catalyst_reaction.py` en HEAD `0cdb2c2`).

## Resultado en una línea

**El exit-veto NO pasa los kill-criteria y queda OFF (dead-code documentado).** No
se dispara en ninguno de los 32 ciclos cerrados reales — ni siquiera en MRVL, el caso
que motivó su diseño. La causa es estructural, no de escasez de datos.

## Universo del backtest

De los 32 SELLs filled de la cuenta Sim Principal (2026-04-30 → 2026-06-08): 4 son
risk-exits (`atr_stop`/`atr_trail`, exentos del veto por diseño) y 28 son SELLs de
señal. La zona gris del veto es score ∈ [0.25, 0.50]; 27 caen ahí (solo PEP @0.22 la
esquiva por bypass).

El filtro vinculante es la **inminencia de un catalyst**: que exista un earnings dentro
de ≤3 días hábiles después del SELL. Reconstruí el calendario point-in-time desde los
418 eventos `earnings_results` de `news_events` (el próximo earnings con `published_at`
≥ fecha del SELL). Solo **3 SELLs grises** tienen earnings inminente:

| Ticker | Fecha SELL | score venta | Earnings | días háb. |
|--------|-----------|-------------|----------|-----------|
| WMT    | 2026-05-20 | 0.337 | 2026-05-21 | 1 |
| MRVL   | 2026-05-27 | 0.434 | 2026-05-27 | 0 |
| TSM    | 2026-06-08 | 0.315 | 2026-06-09 | 1 |

MRVL es exactamente el caso del diseño (vendido por señal técnica justo antes de un
earnings que lo voló).

## Decisión del veto: no dispara en ninguno

Reconstruí la decisión con `imminent_catalyst` + `exit_veto_block` usando una reaction
table **point-in-time** (solo earnings con fecha anterior al SELL, sin lookahead). El
veto requiere `expected_direction == +1` **y** `catalyst_score ≥ veto_min_score (0.30)`.

| Ticker | dirección esperada | catalyst_score | ¿dispara? |
|--------|--------------------|----------------|-----------|
| WMT    | +1 | 0.061 | No |
| MRVL   | +1 | 0.049 | No |
| TSM    | +1 | 0.085 | No |

Los tres dan dirección positiva pero un score un orden de magnitud por debajo del
umbral. **Vetoes que disparan: 0 de 3.** En consecuencia, el P/L del motor es idéntico
con el flag ON u OFF: el veto no cambia ninguna decisión real.

## Por qué es estructural (no se arregla con más harvest)

`imminent_catalyst` usa `sentiment="neutral"` a propósito: ex-ante no se conoce el
resultado del earnings. Con sentiment neutral, el score sale enteramente del **mean
histórico de reacción a earnings**, que sobre 354–366 eventos es ~+0.3% a 5 días con
hit-rate ~46%. Es decir: en promedio un earnings es una moneda al aire simétrica.
Entonces `magnitude = tanh(0.003 / 0.05) ≈ 0.06`, y aun con `confidence_weight = 1.0`
y dirección +1 el score tope ronda 0.06–0.09. **El umbral 0.30 es esencialmente
inalcanzable para una señal de earnings-inminente con sentiment neutral.** Las stats
per-ticker no ayudan (muestras finas; las 3 earnings previas de MRVL promediaban −2%).

## La lección de fondo: el veto es direccionalmente ciego

Aunque se bajara el umbral para forzar el disparo, el mecanismo no sabría distinguir
una sorpresa positiva de una negativa. Los dos casos con forward data lo muestran de
manera limpia y opuesta (precios verificados, sin artefactos de split):

- **MRVL**: SELL @198.70 → +51.8% a 5 días (cerró 301.65). Holdear habría capturado un
  rally enorme. El veto **habría ayudado**.
- **WMT**: SELL @130.85 → −9.1% a 5 días (cerró 118.90). El earnings hundió la acción.
  Holdear habría **perdido**. El veto correctamente **no debía** disparar.
- **TSM**: sin forward data (el cache corta a 2026-06-04; earnings 06-09). No evaluable.

Un veto de "earnings inminente" que dispara por inminencia y no por dirección habría
agarrado tanto el +52% de MRVL como el −9% de WMT — neto, una moneda al aire, justo lo
que predice el mean global ~0. Incluso el caso optimista (bajar el umbral y vetar los
tres) falla los kill-criteria: la única ganancia es un outlier de un nombre (MRVL),
WMT (posición más grande, $8.853 vs $5.536) pierde y **empeora el max DD** al sostener
una caída de 9%, y queda n=2 evaluable. El §7 exige no degradar DD ni opportunity-
capture con universo chico — no se cumple.

## Decisión (kill-criteria §7)

> Activar solo si vetar SELLs grises con catalyst positivo inminente mejora el P/L
> total ≥ +1.5 pts sin subir el max DD más de 1.3× ni reducir el opportunity-capture.

**No pasa.** Con 0 disparos el lift es exactamente 0 pts; con el umbral relajado la
evidencia es un único outlier que empeora DD. `paper_catalyst_exit_veto_enabled`
queda **False** (dead-code documentado, mismo destino que cross-sectional en T05). El
código de T-CAT-4 (módulo + Gate 2c + tests) sigue siendo válido como mecanismo; lo que
no se valida es **encenderlo**.

## Qué lo desbloquearía

El veto solo tiene sentido si puede predecir una **sorpresa de earnings positiva**, no
la mera inminencia. Eso es T-CAT-5 (surprise score vs estimaciones), hoy bloqueado por
falta de datos point-in-time de estimaciones con fuentes gratis (caveat ya escrito en
`docs/catalyst_t_cat_0_design.md`). Re-evaluar T-CAT-6 solo cuando exista una señal
direccional que reemplace el sentiment neutral; recién ahí el umbral 0.30 sería
alcanzable de forma informativa. Alternativa de rediseño (no activación): keyear el
veto en un evento positivo reciente datado (guidance_raise / pre-announcement) en vez
de en el mean simétrico de earnings.

## Reproducibilidad / notas

- DB: backup limpio del 2026-06-11 10:06 (no la viva). cell_size_check=OFF.
- Calendario de earnings = `news_events.event_type='earnings_results'` (418 eventos,
  rango 2023-06 → 2026-06). Reaction table point-in-time por SELL.
- Precios = `historical_data_cache` (data_json split-orient → DataFrame). MRVL solo
  tiene 1y/2y; suficiente.
- Pendiente Windows: ninguno de código. Esto es una decisión, no un cambio. Si se quiere
  dejar rastro en settings, el default ya es OFF — no hay nada que setear.
