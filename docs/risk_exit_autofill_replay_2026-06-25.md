# Replay — auto-fill de risk-exits en cuenta manual (tarea ① · N3/A2)

_2026-06-25 · cuenta 1 "Sim Principal" (manual) · backup `finanzias_2026-06-25_01-13-55_daily.db`_

## Pregunta

En una cuenta **manual**, ¿conviene ejecutar los risk-exits (`atr_*` / `vol_trim`)
al toque —como en auto— en vez de encolarlos como orden pendiente que requiere
aprobación y que `reconcile_account` marca `expired` a las 24h si no se aprueba?

Un stop que puede expirar por inacción **no es gestión de riesgo**: la posición
queda abierta y cayendo. El cambio bifurca `engine.run_scan`: en manual, los
risk-exits caen al path de fill (con el `fill_price_override` modelado gap/touch),
el resto sigue `pending`.

## Kill-criteria (pre-registrado — BACKLOG tarea ①)

Replay comparando **"stop pending que puede expirar"** vs **"auto-fill del
risk-exit"**. Se shipea si el auto-fill:

1. **No empeora** el P/L total, y
2. **Reduce** la exposición a la cola de pérdidas (max DD).

## Modelo de las dos políticas

Harness: `scripts/run_risk_exit_autofill_replay.py` (reusa `analysis/exit_replay.py`).
Read-only sobre el backup. Sobre cada uno de los **6 risk-exits reales** (FIFO):

- **AUTO-FILL (la feature):** el stop ejecuta en el scan que dispara. Es
  *exactamente* lo que pasó en la historia capturada — los 6 risk-exits reales se
  aprobaron a **0,00–0,14 h** del trigger (delay ≈ 0), así que el fill real ES el
  del auto-fill. `pnl_auto = pnl_real`.
- **PENDING-EXPIRA (el agujero que tapa la feature):** el stop queda pending, no se
  aprueba, expira a las 24h y la posición sigue **sin stop efectivo**. Peor caso
  acotado: rida hasta el cap (20 días hábiles) y salga al close. Se modela con
  `replay_event` y el ATR neutralizado (mult enormes, trail off) para que ningún
  stop dispare en la sim.

> El peor caso (ride al cap, nunca se aprueba) es la **cota superior** del daño.
> El caso realista (se re-aprueba en el próximo scan) ≈ auto-fill. La verdad vive
> entre ambos; reportamos la cota para acotar el riesgo de la cola.

## Resultados

```
ticker   reason       pnl_auto$  pnl_expire$  Δ(auto-exp)$  peor exc.$  delay h
WMT      atr_stop       -625.32      -943.50       +318.18     -594.22     0.01
MO       atr_trail      -188.03       -85.28       -102.75     -385.13     0.01
LRCX     atr_trail      -187.28     +1279.08      -1466.36     +197.52     0.02
KLAC     atr_trail       +85.51     -3402.20      +3487.70    -3554.05     0.14
MO       atr_stop       -404.07      -174.50       -229.58      -67.78     0.01
KO       atr_stop       -820.72      -788.01        -32.71     -183.57     0.00

TOTAL  pnl_auto=-2139.93  pnl_expire(worst)=-4114.41  Δ=+1974.48 (+3.95 pts)
DD auto=7.40%  DD expire(worst)=14.98%  ratio=2.02
Cola de pérdidas evitada (peor excursión total): -4587.23
```

- **No empeora P/L:** ✅ — Δ(auto − expira) = **+$1.974 (+3,95 pts)**. Frente al peor
  caso de expiry el auto-fill es **mejor**; en la historia realizada (delay ≈ 0) es
  **idéntico** (ΔP/L realizado = $0). En ningún caso empeora el P/L total.
- **Reduce la cola de DD:** ✅ — dejar expirar los stops ~**duplica** el max DD
  (7,40% → 14,98%, ratio 2,02). El auto-fill recorta esa cola.

### Lectura honesta (matices)

- **Per-evento es mixto:** WMT/KLAC/KO el stop salvó plata; MO×2/LRCX hubieran
  recuperado (whipsaw — el stop cortó una baja transitoria). Eso es una pregunta
  sobre el **múltiplo del stop** (tarea ③, recalibración), **no** sobre auto-fill.
  Esta validación mantiene la política de stop fija y solo compara *ejecutarla
  confiablemente* vs *que pueda no ejecutarse*.
- **El agregado positivo lo domina KLAC** (un atr_trail en un nombre que después
  cayó −$3.554 más). Es la asimetría típica de la cola: los stops cuestan poco la
  mayoría de las veces y ocasionalmente evitan un golpe grande. Concentrado por
  definición.
- **La muestra tuvo 0 expiries** (los 6 se aprobaron en minutos). El beneficio es
  **estructural**: elimina la dependencia de que el dueño esté al teclado. Los
  +3,95 pts / DD a la mitad son la **cola evitada**, no P/L realizado en esta corrida.

## Veredicto: **SHIP ✅**

El auto-fill no empeora el P/L (idéntico a lo realizado; mejor que el peor caso de
expiry) y reduce a la mitad la cola de max DD. Cumple el kill-criteria
pre-registrado. Se cablea en `engine.run_scan` (manual + `risk_exit` → fill directo
con override modelado).

**Reproducir:**
```
python scripts/run_risk_exit_autofill_replay.py \
    --db backups/finanzias_2026-06-25_01-13-55_daily.db --account 1
```

Tests: `tests/test_risk_exit_autofill_replay.py` (lógica del contrafactual),
`tests/test_atr_stops.py` (auto-fill en manual, señal sigue pending, vol_trim),
`tests/test_earnings_gate.py::test_atr_forced_sell_bypasses_earnings_gate`.
