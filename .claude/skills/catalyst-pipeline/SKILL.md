---
name: catalyst-pipeline
description: Operar el Catalyst Engine (T-CAT) de FinanzIAs — harvesting de noticias, clasificación con LLM, perfiles de sorpresas y el scheduler diario. Usar al recolectar noticias/8-K, clasificar eventos, regenerar surprise_profiles, o diagnosticar el harvest diario.
---

# Catalyst Engine (T-CAT)

Pipeline append-only point-in-time: recolecta noticias → clasifica → alimenta señales de catalyst. Modelos `NewsEvent` y `AnalystEstimateSnapshot` (append-only) en `database/models.py`.

## Harvesting de noticias

`scripts/harvest_catalysts.py` — idempotente (UPDATE in-place, re-correr es no-op). Fuentes: yfinance, SEC 8-K (EDGAR), RSS por-ticker, Finnhub. Dedup por URL canónica.

```
python scripts/harvest_catalysts.py                 # la cuenta VIVA (T70), no un literal
python scripts/harvest_catalysts.py --universe sp500
python scripts/harvest_catalysts.py --tickers NVDA,PLTR,RKLB
python scripts/harvest_catalysts.py --sources yfinance,sec,finnhub
python scripts/harvest_catalysts.py --dry-run    # recolecta y reporta, sin escribir
```

**Sin `--account-id` el harvest resuelve la cuenta viva contra `is_active` (tarea 70).** Este bloque decía `--account-id 1` y esa cuenta está pausada desde el 2026-07-01: el harvest —y el que corre el scheduler cada hora, que llama sin flag— recolectaba para los **52** tickers de la cuenta 1 en vez de los **128** de la viva. Pasarle un id explícito sigue funcionando, y ahora avisa fuerte si apunta a una cuenta pausada.

Finnhub requiere `FINNHUB_API_KEY` en el entorno (source tag `finnhub:<Outlet>`).

## Clasificación

`scripts/classify_catalysts.py` — taxonomía de 17 categorías; heurístico (item-codes SEC + keywords) con backend LLM enchufable (qwen). Idempotente; `--reclassify` fuerza redo.

```
python scripts/classify_catalysts.py --limit 200
python scripts/classify_catalysts.py --source sec_8k
python scripts/classify_catalysts.py --reclassify
```

## Perfiles de sorpresas (T-CAT-5a)

`scripts/build_surprise_profiles.py` → `data/catalyst/surprise_profiles.json`. Agrega el historial EPS estimate vs reported (yfinance) en un prior direccional por ticker. Usado por `imminent_catalyst` (reemplaza el mean neutral de reacción).

**Caveat**: yfinance da el estimate *actual* por trimestre, no el consenso del día previo al print → sesgo de revisión/look-ahead. Es bootstrap. La forma final (T-CAT-5b, consenso point-in-time desde `analyst_estimate_snapshots`) está **BLOQUEADA hasta ~fines jul 2026** por falta de datos acumulados (necesita ≥1 temporada capturada, ~40 pares).

## Reacción histórica

`scripts/build_historical_reaction.py` — forward returns por `event_type` (point-in-time, entry primer día hábil). Módulo `analysis/catalyst_reaction.py`.

## Scheduler diario

`scripts/daily_catalyst_harvest.bat` corre vía Task Scheduler de Windows. **El .bat DEBE tener CRLF** o muere en silencio (ver `finanzias-conventions`). Es lo que hace avanzar el reloj de T-CAT-5b — confirmar periódicamente que corre (verificado funcionando 2026-06-09).

## Estado de los gates

El consumidor en el motor es **Gate 2c (exit-veto, T-CAT-4)**, hoy **DEFAULT OFF** por kill-criteria no superado (ver skill `backtest-replay-harness`).
