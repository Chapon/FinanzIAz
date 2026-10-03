---
name: catalyst-pipeline
description: Operar el Catalyst Engine (T-CAT) de FinanzIAs — harvesting de noticias, clasificación con LLM, perfiles de sorpresas y el scheduler diario. Usar al recolectar noticias/8-K, clasificar eventos, regenerar surprise_profiles, o diagnosticar el harvest diario.
---

# Catalyst Engine (T-CAT)

Pipeline append-only point-in-time: recolecta noticias → clasifica → alimenta señales de catalyst. Modelos `NewsEvent` y `AnalystEstimateSnapshot` (append-only) en `database/models.py`.

## Harvesting de noticias

`scripts/harvest_catalysts.py` — idempotente (UPDATE in-place, re-correr es no-op). Fuentes: yfinance, SEC 8-K (EDGAR), Finnhub (la rama `rss` se borro en la tarea 212). Dedup por URL canónica.

```
python scripts/harvest_catalysts.py                 # la cuenta VIVA (T70), no un literal
python scripts/harvest_catalysts.py --universe sp500
python scripts/harvest_catalysts.py --tickers NVDA,PLTR,RKLB
python scripts/harvest_catalysts.py --sources yfinance,sec,finnhub
python scripts/harvest_catalysts.py --dry-run    # recolecta y reporta, sin escribir
python scripts/harvest_catalysts.py --budget-seconds 780   # techo de 13 min (0 = sin techo)
```

**El harvest tiene techo de wall-clock y está ON (tarea 204).** `catalyst_harvest_budget_seconds`, default **1200 s (20 min)**; `--budget-seconds` lo pisa por corrida y **`0` = sin techo**, no «cortar ya». El motivo es que el camino lento del harvest es el de la **falla**, no el del éxito: con las tres fuentes timeouteando, cada ticker agota su presupuesto de timeout + reintentos y eso se multiplica por 3 fuentes × N tickers. El chequeo va **antes de cada ticker**, así que una corrida cortada se lleva el **sufijo** del universo y **lo ya recolectado se persiste igual**. Al diagnosticar un harvest, leer el `Harvest: X/Y tickers en Ns …` del log: `X<Y` más `CORTADO por presupuesto` es un corte, no una falla.

**El reporte dice si las fuentes se cayeron, y el nivel del log también (tarea 207).** `failed N` cuenta sólo los tickers cuyo *collector* levanta, y `collect_all` no levanta nunca — por eso las dos corridas catastróficas del 2026-08-14 decían `failed 0`. Lo que hay que mirar es `fuentes X/Y limpias` y, si aparece, `FUENTES CAIDAS: <fuente> N/M`: una corrida con alguna fuente fallando en ≥20% de los tickers sale a **`WARNING`** en vez de `INFO`. `sin datos N` es **contexto, no alarma** — con dedup, cero filas nuevas es lo normal.

**Y una fuente puede estar caída de RAÍZ sin fallar nunca (tarea 217): eso sale como `FUENTE NO DISPONIBLE: <fuente> (<motivo>)`.** Si falta la dependencia o la key, la fuente no corre para **ningún** ticker, así que no tiene tasa de falla y `FUENTES CAIDAS` no la menciona nunca. Hasta la 217 lo único que se movía era el **denominador** de `fuentes X/Y limpias` — de `4/4` a `3/3` —, que no se puede leer sin saber de memoria cuántas fuentes se pidieron. Ahora se dice, **una vez por fuente** (no una por ticker), y el resumen sube a `WARNING`. Importa porque sin `FINNHUB_API_KEY` se va el **56,6%** del volumen de `news_events`. **No entra al gate del 20%**, que está calibrado sobre fuentes que sí corrieron.

**Con la red caída hay UN traceback por fuente y tipo de falla, no uno por ticker (tarea 289).** La primera falla de red (`OSError`, donde caen las de `requests` y `curl_cffi`, DNS incluido) de cada `(fuente, tipo)` escribe su traceback con *«las siguientes de <tipo> van sin traceback»*; las demás van en una línea `WARNING` con el error resumido, y al final la corrida escribe `harvest: fallas de red sin traceback en esta corrida — <fuente>: N`. Para contar cuántos tickers fallaron, sumá esa línea y no los tracebacks. Una falla que **no** es de red (un bug de parseo) sigue con traceback cada vez. La salud por fuente de la 207 no cambia: cada falla cuenta.

**Sin `--account-id` el harvest resuelve la cuenta viva contra `is_active` (tarea 70).** Este bloque decía `--account-id 1` y esa cuenta está pausada desde el 2026-07-01: el harvest —y el que corre el scheduler cada hora, que llama sin flag— recolectaba para los **52** tickers de la cuenta 1 en vez de los **128** de la viva. Pasarle un id explícito sigue funcionando, y ahora avisa fuerte si apunta a una cuenta pausada.

Finnhub requiere `FINNHUB_API_KEY` en el entorno (source tag `finnhub:<Outlet>`).

## Clasificación

`scripts/classify_catalysts.py` — taxonomía de 17 categorías; heurístico (item-codes SEC + keywords) con backend LLM enchufable (qwen). Idempotente; `--reclassify` fuerza redo.

```
python scripts/classify_catalysts.py --limit 200
python scripts/classify_catalysts.py --source sec_8k
python scripts/classify_catalysts.py --reclassify
```

**El tono tiene dos escalas según la fecha (tarea 259).** Desde el 2026-10-03, qwen califica en **7 niveles** (`sentiment_level` de −3 a +3, con rúbrica) y el score se guarda como `nivel / 3`; esas filas llevan el sufijo **`-7n`** en `classified_by` (`ollama-7n`, `llm-7n`, ver `SUFIJO_ESCALA_7`). Lo anterior quedó con la escala **agrupada** de 4 valores y **no se reclasificó** (decisión de Chapa); una respuesta del LLM sin nivel válido también toma el camino viejo, sin sufijo. Al contar distribuciones de tono, separá por sufijo: mezclarlas compara dos escalas. Al diagnosticar el classify, un `classified_by` con `-7n` es LLM, no una caída a heurística. Si los extremos ±3 son raros es la pregunta de la tarea 290.

## Perfiles de sorpresas (T-CAT-5a)

`scripts/build_surprise_profiles.py` → `data/catalyst/surprise_profiles.json`. Agrega el historial EPS estimate vs reported (yfinance) en un prior direccional por ticker. Usado por `imminent_catalyst` (reemplaza el mean neutral de reacción).

**La cadencia sale del artefacto (tarea 160).** El scheduler regenera cada `surprise_build_interval_days` (default 7) contando desde el `_meta.built_at` del propio JSON — `analysis.surprise_score.last_build_iso`. Antes la marca vivía en `settings['surprise_last_build']`, así que **correr el script a mano no reseteaba el reloj**; ahora sí. Y si el artefacto no está, corresponde rebuild (antes el scheduler esperaba la semana igual). La ruta la declara `analysis.surprise_score.PROFILES_PATH`: el que escribe y el que lee tienen que hablar del mismo archivo.

**Caveat**: yfinance da el estimate *actual* por trimestre, no el consenso del día previo al print → sesgo de revisión/look-ahead. Es bootstrap. La forma final (T-CAT-5b, consenso point-in-time desde `analyst_estimate_snapshots`) está **BLOQUEADA** por falta de datos acumulados (necesita ≥1 temporada capturada, ~40 pares). La fecha vive en *Bloqueado* del backlog —acá decía *«hasta ~fines jul 2026»*, y el hueco del 25/07 al 08/08 la corrió a la temporada Q3—; no se copia acá para que no vuelva a caducar.

## Reacción histórica

`scripts/build_historical_reaction.py` — forward returns por `event_type` (point-in-time, entry primer día hábil). Módulo `analysis/catalyst_reaction.py`.

## Scheduler: corre ADENTRO de la app

**Desde el 2026-07-12 no hay ninguna tarea del Task Scheduler de Windows** (verificado con `Get-ScheduledTask` el 2026-09-30, tarea 240). Acá decía que `daily_catalyst_harvest.bat` corría vía Task Scheduler y mandaba a *«confirmar periódicamente que corre»*: no había nada que confirmar. Todo corre en `paper_trading/scheduler.py`, **sólo con la app abierta**:

- **Refresh diario** — la primera apertura del día corre harvest + classify.
- **Harvest horario** — durante RTH, harvest-only cada `catalyst_hourly_harvest_minutes` (default 60).
- **Rebuild de surprise** — cada `surprise_build_interval_days`, con backoff tras un fallo (tarea 197).

Para diagnosticar, mirar en `~/.finanzias/finanzias.log` las líneas `Harvest: X/Y tickers …` (ver arriba) y `hourly catalyst harvest done`. **App cerrada = no se captura nada**, y eso es lo que frena el reloj de T-CAT-5b: la solución de fondo es la recolección en la Pi (tarea 196, y la 245 para sincronizar lo que falte). `scripts/daily_catalyst_harvest.bat` sigue en el repo y se puede correr a mano; **si se vuelve a programar, tiene que tener CRLF** o `cmd.exe` lo mata en silencio (ver `finanzias-conventions`).

## Estado de los gates

El consumidor en el motor es **Gate 2c (exit-veto, T-CAT-4)**, hoy **DEFAULT OFF** por kill-criteria no superado (ver skill `backtest-replay-harness`).
