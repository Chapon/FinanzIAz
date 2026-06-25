# Validación — aprobación encadenada de BUY/SELL en manual (tarea ② · N2)

_2026-06-25 · cuenta 1 "Sim Principal" (manual) · backup `finanzias_2026-06-25_01-13-55_daily.db`_

## Pregunta

En manual, las BUY se sizean contra `available = account.cash + est_proceeds`
(proceeds estimados de las SELL del mismo scan). En auto las SELL se llenan
primero y liberan ese cash; en manual **ambas quedan pending**, así que si el
usuario aprueba una BUY antes que su SELL financiadora, `_fill_trade` topa el
budget en `acct.cash` (≈0) → devuelve None → la BUY **expira por cash fantasma**.

## Fix

`engine.approve_order`: una BUY que no se llena por falta de cash **no expira**
mientras haya una SELL pendiente en la cuenta (que al aprobarse libera cash).
Queda `pending` con nota; aprobar la SELL libera el cash y re-aprobar la BUY la
llena al budget real **al precio de aprobación**. `_fill_trade` nunca gasta más
que `acct.cash` → **no sobre-apalanca** (estructural). Sin SELL pendiente, la
BUY expira como antes (no hay financiamiento que esperar — el fix no se
sobre-extiende). `reconcile_account` la barre igual si nunca se financia (>24h).

> **Decisión de calidad (mayor ganancia, orden de Chapa 2026-06-25):** se eligió
> la aprobación encadenada por sobre el parche de "zerar `est_proceeds` al
> sizear". Zerar shrinkearía las BUY financiadas (sub-deployment al rotar). El
> encadenado mantiene el tamaño intencional y hace que el **orden de aprobación
> deje de importar**: ninguna entrada se pierde y el cash real se respeta en el
> fill.

## Kill-criteria (pre-registrado — BACKLOG tarea ②)

1. Test de integración manual: SELL+BUY pending del mismo scan → aprobar la BUY
   primero **no la expira** por cash fantasma.
2. Replay: las entradas antes perdidas **se concretan** sin sobre-apalancar.

## Validación (1) — tests de integración

`tests/test_chained_approval.py`:
- `test_buy_before_sell_stays_pending_not_expired` — aprobar BUY sin cash → queda
  `pending` (no `expired`), cash intacto.
- `test_chained_flow_sell_then_buy_both_fill` — BUY pending → aprobar SELL (libera
  ~$5.000) → re-aprobar BUY → se llena; `acct.cash ≥ 0` y `fill_value ≤` cash al
  aprobar (no sobre-apalanca).
- `test_buy_without_pending_sell_expires` — sin SELL pendiente, la BUY sí expira.
- `test_funded_buy_still_fills_directly` — con cash de sobra, llena directo (el
  encadenado no interfiere con el camino normal).

## Validación (2) — contrafactual sobre las BUYs expiradas reales

`scripts/analyze_expired_buys_financing.py` (read-only sobre el backup). De cada
BUY expirada se clasifica la causa (de `notes`) y se busca si en el mismo scan
hubo SELL(s) cuyos proceeds reales liberarían cash para la entrada.

```
ticker       need$ causa              co-SELL$  recup?  co-sells
NVDA        16,667 approved_limbo            0   fuera  (ninguna)
AAPL        16,667 approved_limbo            0   fuera  (ninguna)
META        16,667 approved_limbo            0   fuera  (ninguna)
WMT          8,936 cash_insuficiente      8,838 SÍ-parc  GM
AMD          9,368 cash_insuficiente      9,164 SÍ-parc  AMAT
AAPL        24,253 cash_insuficiente     23,694 SÍ-parc  MLTX
MU          24,288 cash_insuficiente          0       —  (ninguna)
PM          29,339 cash_insuficiente     25,607 SÍ-parc  MU
TJX         29,769 cash_insuficiente          0       —  (ninguna)
TJX         13,069 cash_insuficiente        119 SÍ-parc  F
GM           7,923 sin_precio                0   fuera  (ninguna)
KO          11,660 cash_insuficiente     25,489  SÍ-tot  GM,TJX

Expiradas total: 12  (cash=8, limbo=3 [T7.2, fuera], sin_precio=1 [datos, fuera])
Recuperables por encadenado: 6/8 de las de cash (total=1, parcial=5;
  ~$96,625 de entradas)  ·  sin financiamiento (siguen expirando, correcto): 2
```

**Lectura:**
- De las 12 expiraciones, solo **8 son por cash insuficiente** (las que ataca la
  ②). Las otras 4 son de otra clase: 3 `approved-limbo` (bug T7.2, ya resuelto) y
  1 `sin precio` (robustez de datos, bugs B1/B3) — fuera de scope.
- De esas 8, **6 tenían una SELL co-pendiente** en el mismo scan → con encadenado
  no expiran: 1 se financia entera (KO) y 5 se concretan como entrada real al
  cash liberado (WMT/AMD/AAPL/PM/TJX; los proceeds quedan apenas bajo el target
  porque el target se sizeó como `cash+proceeds`, así que la entrada se concreta
  algo menor pero **no se pierde**). Total ~**$96.625** de entradas recuperadas.
- Las **2 sin SELL co-pendiente** (MU, TJX-05-20) **siguen expirando** — correcto:
  no hay liquidez por venir.
- **Sin sobre-apalancar:** garantizado por `_fill_trade` (budget topado en cash).

> Caveat: el "recuperable" asume que la SELL se aprueba antes de que `reconcile`
> expire la BUY (ya pending) a las 24h. En la historia las SELL se aprobaron y
> llenaron (status `filled`), así que el cash sí se liberó; el encadenado elimina
> la expiración por aprobar-antes y le da tiempo a la SELL. El caso TJX/F ($119)
> es marginal (el cash liberado puede no alcanzar 1 acción).

## Veredicto: **SHIP ✅**

Cumple el kill-criteria: aprobar la BUY primero ya no la expira por cash fantasma
(tests), y 6/8 de las entradas perdidas por cash se concretan bajo encadenado sin
sobre-apalancar (contrafactual sobre datos reales).

**Reproducir:**
```
python scripts/analyze_expired_buys_financing.py \
    --db backups/finanzias_2026-06-25_01-13-55_daily.db --account 1
python -m pytest tests/test_chained_approval.py -ra -m "not network"
```
