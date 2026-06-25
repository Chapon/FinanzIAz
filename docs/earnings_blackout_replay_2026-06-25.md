# Replay — earnings blackout (impacto sobre BUYs)

Fecha: 2026-06-25. Round-trips cerrados analizados: 38 sobre 24 tickers. Contrafactual: plata bloqueada → siguiente pick (proxy = retorno medio de los BUYs no-near-earnings).

| ±N días | # near | P/L near | %medio near | win% near | %medio far | Δ blackout (cf−real) |
|---|---|---|---|---|---|---|
| 1 | 4 | -3569.89 | -5.32% | 0% | +1.14% | +4180.43 |
| 2 | 6 | -3399.41 | -3.45% | 17% | +1.19% | +4199.32 |
| 3 | 7 | -3237.76 | -2.69% | 29% | +1.17% | +4123.99 |
| 5 | 8 | -3053.14 | -2.21% | 38% | +1.17% | +4135.68 |

**Lectura:** Δ blackout > 0 ⇒ bloquear esos BUYs y redeployar habría mejorado el P/L → restaurar `earnings_blackout_days` a esa N. Δ ≤ 0 ⇒ dejarlo en 0.

_Cota inferior: las compras near-earnings aún abiertas no entran (sin P/L realizado). El contrafactual 'siguiente pick' es un proxy; la re-sim del ranking point-in-time es el refinamiento._
