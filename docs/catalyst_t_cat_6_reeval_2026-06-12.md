# T-CAT-6 — Re-evaluación del exit-veto con dirección de sorpresas (T-CAT-5a)

Fecha: 2026-06-12. Read-only sobre `backups\finanzias_2026-06-11_10-06-50_daily.db`. Contrafactual: re-evaluar al próximo scan (salida post-earnings, ATR activo).

## Resultado en una línea

**NO pasa** el kill-criteria → el flag queda OFF (dead-code documentado). ΔP/L = -0.25 pts (umbral ≥ +1.5), DD ratio = 0.97 (umbral ≤ 1.3). Vetó 2/4 SELLs con earnings inminente.

## Configuración

- Universo: 32 SELLs filled (28 por señal), cuenta 1.
- Zona gris: [0.25, 0.5], veto_min_score = 0.3, imminencia ≤ 3 días hábiles.
- Capital inicial: 50,000. Cap de holding: 20d.

## Candidatos (SELLs con earnings inminente)

| Ticker | SELL | score venta | gris | earnings | díasháb | basis | dir | cat_score | vetado |
|--------|------|-------------|------|----------|---------|-------|-----|-----------|--------|
| WMT | 2026-05-20 | 0.337 | sí | 2026-05-21 | 1 | surprise | +1 | 0.276 | no |
| WMT | 2026-05-21 | 1.000 | no | 2026-05-21 | 0 | surprise | +1 | 0.276 | no |
| MRVL | 2026-05-27 | 0.434 | sí | 2026-05-27 | 0 | surprise | +1 | 0.397 | **SÍ** |
| TSM | 2026-06-08 | 0.315 | sí | 2026-06-09 | 1 | surprise | +1 | 0.644 | **SÍ** |

## Métricas agregadas

- SELLs modificados (vetados c/datos): 2
- ΔP/L total: -123.85 USD (-0.25 pts)
- Max DD real: 7.40% · sim: 7.17% · ratio: 0.97
- Mediana extra-return (modificados): -0.87%
- Mediana capture del rally 20d: +5.99%
- Salidas por razón: {'deferred_signal_sell': 2}

## Decisión

El veto no alcanza el umbral de mejora exigido (o degrada el DD). `paper_catalyst_exit_veto_enabled` queda False (dead-code documentado, mismo destino que cross-sectional en T05). Revisitar cuando T-CAT-5b (consenso point-in-time) reemplace el prior v0.
