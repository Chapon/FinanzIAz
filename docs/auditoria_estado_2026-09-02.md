# Auditoría `estado` — 2026-09-02

**Área:** caches y artefactos **regenerables** de los que depende el sistema · **READ-ONLY**, no se
modificó nada · Segunda corrida de la skill `auditoria` · Fase adversarial: agente `verificador`

---

## 1. Kill-criteria — congelado ANTES de abrir un archivo

Por cada store, tres preguntas: **¿quién lo regenera?** · **¿cada cuánto o con qué disparador?** ·
**¿qué pasa si no?** Y una cuarta que salió de la tarea 30: **¿hay algo que compare su frescura
contra la de sus pares?**

**Corpus:** `data/parquet/` · `data/pit_signals/` · `data/pit_risk/` ·
`data/catalyst/surprise_profiles.json` · los archivos de universo · las tablas-cache de la DB
(`historical_data_cache`, `earnings_cache`, `price_cache`, `news_events`) · `dashboard_snapshot.json`
y el artifact del dashboard.

**Afuera:** los caches **en memoria** (indicadores, XGB, GARCH, stacking) — son por proceso, ya los
cubrieron la 24 y la 29 — y los artefactos de harness publicados, que son evidencia y no estado vivo.

**Barrido limpio ⇔** cada store tiene regenerador identificable, cadencia declarada en algún lado
que se lea, y o bien un guard de frescura o bien constancia de que atrasarse no importa.

**Resultado: NO fue limpio.** Cinco hallazgos, uno rechazado por mí y confirmado como bien
rechazado, y uno auto-refutado por el verificador.

## 2. Las predicciones, y cómo salieron

| | predicción | resultado |
|---|---|---|
| **P1** | `pit_risk` puede no tener quién lo corra | **reformulada por el verificador.** *"Nadie lo corre"* **no es un defecto** — es el diseño, y aplica **igual a `pit_signals`**, que también se llena a mano. El hallazgo real es otro (§3, E-1) |
| **P2** | `surprise_profiles.json` con 52 tickers, pendiente del rebuild | correcta pero **ya cubierta por la 70**; no se re-reporta |
| **P3** | universos 127 vs watchlist 128 | **correctamente NO es hallazgo**: está declarado como desvío #1 |

## 3. Los hallazgos

### [E-4] El índice está declarado en el código y **nunca se aplicó** — MEDIA · ALTA

`price_cache` tiene **398.576 filas / 142 tickers**, crece **~125k filas por mes** y **nadie la
poda**. La consulta de "último precio por ticker" hace `SCAN price_cache` + `USE TEMP B-TREE FOR
ORDER BY`. Medido: **38,5 ms** por lookup.

**Pero el hallazgo no es la tabla: es el drift de esquema.** `database/models.py:237-247` declara
tres índices para esa tabla —incluido el compuesto `ix_price_cache_ticker_fetched`— y **ninguno
existe en la DB**. Barrido completo `Base.metadata` vs `sqlite_master`:

> **18 índices declarados en `models.py` que no existen en la DB, en 7 tablas.**
> `alerts` (5) · `price_cache` (3) · `positions` (3) · `transactions` (3) · `dividend_cache` (2) ·
> `failed_tickers` (1) · `historical_data_cache` (1). De 35 declarados, en la DB hay 17.

**Causa raíz:** `alembic/versions/0001_baseline.py` es un no-op a propósito y el esquema lo crea
`Base.metadata.create_all` — que con `checkfirst=True` **saltea entera** una tabla que ya existe,
**índices incluidos**. El compuesto entró a `models.py` el 2026-05-06, después de que la tabla
existiera, y ninguna migración lo creó. Confirmación cruzada: las tablas **nuevas**
(`earnings_cache`, `news_events`, …) sí tienen todos sus índices.

**Lo filoso no es la lentitud: es que el código miente.** Cualquiera que lea `models.py` cree que
el índice existe, y un test que mire el ORM se lo confirma.

**Y hay un consumidor peor que el dashboard**, que el verificador encontró: `get_current_price`
(`data/yahoo_finance.py:1113-1117`) hace un SCAN completo **por ticker** (**48,9 ms**), y
`ui/alerts_tab.py:37-40` lo dispara con un `QTimer` cada **120 s** **en el hilo de la GUI, sin
worker**. Con 10 alertas son ~0,5 s de UI congelada cada dos minutos, hoy.

**Corrección a mi propia medición:** yo medí 128 lookups (4,93 s) como si fuera el dashboard. El
dashboard hace **12** —uno por posición abierta—, así que mi número era una **cota superior
sintética**. El costo real del dashboard es ~0,6 s cada 15 min y en un `QThread`. El de las alertas
es el que duele.

### [E-1] `run_ranking_t21` mide cobertura por TICKER y reporta 100% con 17 fechas faltando — BAJA-MEDIA · ALTA

*(Reformulado por el verificador; mi versión original —"nadie corre `pit_risk`"— fue refutada.)*

`data/pit_risk/` tiene 127 archivos con última fecha **2026-08-07**; `data/pit_signals/` va al
**2026-09-01**. Son **17 ruedas**. Eso, solo, no es un defecto: **ninguno de los dos stores tiene
quién los corra** —los dos son on-demand y resumibles, y `pit_signals` se llenó a mano en la 69—.

El defecto es que su único consumidor no puede notarlo. `scripts/run_ranking_t21.py:157`:

```python
coverage = (len(out) / len(tickers)) if tickers else 0.0
```

Con 127/127 archivos y `complete=True`, `MIN_RISK_COVERAGE` pasa y el banner imprime **"risk_score
PIT: 100% de cobertura"**. Después `b2()` hace `if r is None: return float(s)` — o sea que para cada
**fecha** sin `risk_score` el brazo diagnóstico **es el baseline, en silencio**. Es exactamente el
modo de falla que el comentario de `MIN_RISK_COVERAGE` dice que existe para evitar, pero en el eje
de **fechas** en vez del de tickers. **Es, otra vez, un chequeo por cantidad ciego a la ventana** —
la familia de la 48, la 52, la 62 y la 69.

Medido: **934 de 144.511** entradas caen en el hueco ⇒ **0,65%** del brazo contaminado. El daño no
es ese 0,65%: es **el reporte de cobertura que miente**. Y no es estado muerto — la tarea **42
(VOLPEN)**, abierta, prescribe como primer paso correr justamente ese runner.

### [N-1] El guard de la tarea 30 está cableado en **1 de 32** runners — MEDIA · ALTA

*(Hallazgo del verificador, sobre trabajo mío de ayer.)*

`announce_artifacts` dice en su propio docstring *"se llama **al arrancar**: si la muestra está
torcida, la corrida entera no vale"*, y aparece en **un solo** archivo (`run_trail_arm_t54.py`) de
**32**; el test que fija el cableado lo exige **sólo para ése**.

**Y mi razonamiento al cerrar la 30 fue el equivocado.** Argumenté *"cablear sólo el runner con la
pregunta viva, siguiendo el precedente de la 58"*. Pero **el precedente no transfiere**: el
`announce_grid` de la 58 es sobre **la grilla de ese runner**, mientras que el `announce_artifacts`
de la 30 es sobre **el sustrato compartido** — los 32 runners leen el mismo cohorte. Concreto: el
primer paso prescrito de la tarea 42 corre hoy **sin chequear el cohorte**.

### [E-2] 22,7 MB de cache muerto, y dos lectores sin TTL — BAJA · ALTA

*(Mi mecanismo fue **refutado**; sobrevive por otro, más angosto.)*

**Refutado:** yo afirmé que si el backend volviera a `sqlite` la app leería frames de dos meses. **No
puede**: `HISTORICAL_CACHE_TTL_HOURS = 1` y el `_read_historical_cache` filtra por `fetched_at >=
cutoff`. Y `dual` **escribe a los dos** backends, así que las filas viejas se van pisando.

**Sobrevive por dos lecturas que el propio docstring marca "Sin TTL"** —
`_read_latest_1d_frame:513` y `_read_all_1d_frames:551`, que alimentan el **guard de sanity E5** y
el **detector de split de la T63**. En backend `sqlite` usarían el close del 2026-07-11 como
referencia hasta el primer fetch. Y el default del spec **sigue siendo `sqlite`**: el `parquet` vivo
existe sólo porque está en `~/.finanzias/settings.json`, que **no está versionado**.

Costo hoy: **22,7 MB** de `data_json` muerto sobre 90,2 MB de DB — **25% del archivo**.

**La tensión honesta para el fix:** el spec vende *"rollback = volver a `sqlite`"*, y esas filas
**son** el rollback. Lo que hay que decir no es *"la tabla sobra"* sino **"ese rollback ya caducó"**.

### [N-2] La suite escribe en el log de producción — BAJA · ALTA

*(Hallazgo del verificador.)* El log vivo tiene **153** `Earnings cache write failed for TSLA:
database is locked` y **170** `earnings gate: provider failed for NVDA`, que parecen un defecto de
producción y **no lo son**: el traceback apunta a `tests/test_earnings_gate.py:205`. Es la suite
escribiendo en `~/.finanzias/finanzias.log`. **Es una fábrica de falsos positivos para cualquier
auditoría que use logs como evidencia** — y estuvo a punto de producir uno acá.

## 4. Lo rechazado

**[E-3] `earnings_cache` 41 de 127 tickers — RECHAZADO por mí, confirmado por el verificador.** Es
un cache **lazy con TTL** y está **fresco**: su tamaño refleja **demanda**, no atraso. Tiene un solo
consumidor (Gate 6) que lo pide **por candidato**, no por universo; pedirlo para los 127 serían 127
llamadas de red por scan para un gate que sólo dispara sobre candidatos. **La cobertura no es su
trabajo.**

**[AVB] `data/parquet/AVB__10y__1d.parquet` congelado — auto-refutado por el verificador**, y bien:
es la excepción **declarada** de `ARTIFACT_REFRESH_EXCEPTIONS` (tarea 63), con su motivo y con el
banner diciéndolo en cada corrida.

## 5. Dónde el verificador se equivocó, y por qué se publica mi número

Reportó *"faltan **24** índices en **11** tablas"* e incluyó `paper_orders` (3),
`paper_positions` (1), `paper_watchlist` (1) y `paper_equity_snapshots` (1). **Esas tablas no
declaran ningún índice**: el conteo correcto es **18 en 7 tablas**, verificado
independientemente recorriendo `Base.metadata.sorted_tables` contra `sqlite_master`.

Se deja escrito porque es el punto de la fase adversarial: **corre en las dos direcciones**. El
verificador me refutó dos framings y me encontró dos hallazgos; yo le corregí un número. Ninguno de
los dos lados se toma al otro por buena fe.

## 6. Alcance NO mirado

- **`news_events`** (39.332 filas, desde 2023): se vio el tamaño y la frescura, no la política de
  retención ni sus índices. Misma familia que E-4.
- **`data/parquet/` como store**: la frescura del cohorte ya la cubre el guard de la 30 (y su
  cableado es N-1); no se miró el crecimiento en disco (60 MB, 752 archivos) ni si algo lo poda.
- **`dashboard_snapshot.json`** y el artifact: los tocó la 70; no se re-auditaron.
- **Los índices que faltan en las otras 6 tablas** no se midieron en costo — sólo los de
  `price_cache`, que es la que tiene el consumidor caliente.
- Las otras tres áreas de la skill: `muestra`, `desvios`, `guards`.
