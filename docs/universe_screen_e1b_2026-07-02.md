# E1b — Screen de universo por liquidez/calidad (anti-MLTX estructural)

**Fecha:** 2026-07-02 · **Veredicto:** **SHIP** (kill-criteria PASS) · master flag OFF-by-default, enable manual pendiente de Chapa.

## Contexto

El análisis de efectividad 2026-06-30 mostró que **un solo nombre frágil define el resultado**: MLTX (MoonLake, biotech clínico pre-revenue, −89.9%, −$2.554 realizados). P/L total +$278 con MLTX vs **+$2.920 sin MLTX**. El cap de tamaño (E1a) quedó **NO-SHIP** — MU/AAPL estaban tan sobre-concentrados como MLTX, así que un cap ciego recorta ganadores igual que perdedores. **La defensa correcta es de universo, no de tamaño:** evitar que nombres tipo MLTX entren.

## Diseño

Screen aplicado a **candidatos de BUY únicamente** (nunca a posiciones tenidas → las SELL/stops de lo tenido siguen corriendo). Dos patas, ambas *fail-open* (excluir solo ante evidencia positiva):

1. **Liquidez (ADV$):** excluye candidatos con ADV$ (media Close×Volume, ventana `paper_adv_lookback_days`) por debajo de `paper_universe_min_adv_dollars`. Reusa `recent_adv_dollars` (gates.py). **Default 0 = apagada** (no validada por watchlist; complementa el ADV cap de tamaño ya activo).
2. **Calidad fundamental (EDGAR XBRL):** excluye nombres con **net income anual sostenidamente < 0** (`paper_universe_min_negative_years`, default 2) **y** revenue anual más reciente **ausente o < `paper_universe_revenue_floor_dollars`** (default $10M). Es la firma del biotech clínico pre-revenue.

### Módulos
- `data/edgar_fundamentals.py` — fetch `companyfacts` (reusa la infra SEC de `news_sources`: mapa ticker→CIK cacheado, User-Agent SEC) + `parse_fundamental_facts` (puro: extrae net income y revenue **anuales**, dedup por fin de año fiscal prefiriendo el valor framed `CYxxxx`). Cache por proceso.
- `paper_trading/universe.py` — decisión pura `screen_candidate(ticker, adv$, facts, thresholds) → UniverseVerdict`. `UniverseThresholds.from_settings()`.
- `paper_trading/strategies.py` — cableado en el loop de candidatos de `generate_trades_analyze_single`: liquidez primero (sin round-trip a EDGAR si ya se descarta), fundamentals después. **OFF → `_universe_thresholds()` devuelve None → path legacy exacto, sin red.**
- `scripts/run_universe_screen_validation.py` — harness read-only del kill-criteria (red viva).

### Decisión de diseño clave (hallada en validación)
Un biotech clínico pre-revenue **no reporta ningún concepto de revenue en EDGAR** → `revenue_latest = None`. La versión inicial hacía *fail-open* ante revenue ausente y **dejaba pasar a MLTX** (la primera corrida de validación lo mostró: NI −227M/−118M, revenue —, INCLUIDO). Corrección: con **pérdidas sostenidas ya presentes** (la evidencia positiva), la **ausencia** de revenue se lee como pre-revenue (≈$0), no como gap. Es la única forma de agarrar a MLTX. El riesgo de falso positivo (un nombre bueno con 2+ años de pérdidas y revenue que no parseamos) se descartó empíricamente contra la watchlist real (ver abajo).

## Kill-criteria

> El screen de ADV$/calidad **excluye los nombres tipo MLTX sin sacar nombres buenos** (validar contra la watchlist actual). Suite Windows verde.

## Validación (datos vivos, 2026-07-02)

`python scripts/run_universe_screen_validation.py` sobre la **watchlist real de Sim Principal (52 nombres)**, thresholds default (min_adv=0, fundamentals ON, min_neg_years=2, revenue_floor=$10M):

- **kill_pass = True.** Único excluido: **MLTX** (`fragile_fundamentals`; NI −227M/−118M; sin revenue). `fragile_missed: []`, `other_exclusions: []`.
- **Casos de borde, todos CONSERVADOS correctamente:**
  - **INTC** — 2 años de pérdidas (−267M, −18.7B) pero revenue **$52.8B** ≫ piso → no pre-revenue → conservado.
  - **TEAM** (Atlassian) — 3 años de pérdidas GAAP pero revenue **$5.2B** → conservado (caso "growth no rentable con revenue real").
  - **GIS** — pérdida puntual 1 año (el 2º positivo) → no sostenida → conservado.
  - **ASML, TSM** — foreign filers sin facts EDGAR resolubles → fail-open → conservados.
- Control adicional (`--tickers MLTX,AAPL,MU,TSLA,LMT,JPM`): MLTX excluido, los 5 large-caps conservados.

**Observación:** el ADV$ de MLTX era **$26.4M** — un piso de liquidez agresivo ($50M) también lo agarraría, pero recortaría mid-caps legítimos. La pata fundamental es el corte quirúrgico; la de liquidez queda apagada por default (sin validar por watchlist).

## Qué se shipea / qué queda

- **Código:** SHIP con `paper_universe_screen_enabled=False` en el SCHEMA (sin cambio de comportamiento en instalaciones/tests; la habilitación viva es decisión de Chapa, igual que el ADV cap y el earnings blackout).
- **Acción manual (Chapa, Windows):** setear `paper_universe_screen_enabled=true` en `~/.finanzias/settings.json` para activarlo vivo. Opcional: `paper_universe_min_adv_dollars` si quiere sumar la pata de liquidez (sweep antes con el script de validación).
- **Tests:** 33 offline (parse EDGAR, screen puro, wiring con mocks). Suite Windows **1016 passed, 1 skipped**.

## Limitaciones / follow-ups
- **Costo de red en hot-path:** con el screen ON, cada candidato de BUY dispara un fetch de `companyfacts` (cache por proceso → ~1 vez por nombre por sesión). El payload de `companyfacts` es de varios MB por ticker. **Optimización futura:** usar el endpoint por concepto `/api/xbrl/companyconcept/CIK.../us-gaap/NetIncomeLoss.json` (mucho más liviano); el parser ya opera sobre la sub-estructura `{units:{USD:[...]}}` compatible, así que el cambio queda localizado en la capa de fetch.
- **Cache no persistente:** hoy es por proceso; un refresh diario a una tabla `fundamentals_cache` (patrón `earnings_cache`) sacaría la red del hot-path del todo. No necesario para v1.
- **Foreign filers (ASML/TSM):** sin facts EDGAR → fail-open. Correcto (no dropear buenos), pero no protegidos por la pata fundamental. Aceptable: no son perfil MLTX.
- **`auto_adjust`/survivorship** (restricción transversal del BACKLOG) no aplican acá: EDGAR son hechos contables filed, point-in-time.
