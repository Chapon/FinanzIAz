# Pre-registro CONGELADO — Insider cluster buys (Form 4) como fuente de leads (Tarea 12)

**Fecha:** 2026-07-24 · **Estado:** congelado ANTES de codear (regla 2 — kill-criteria upfront).
**Ref:** `docs/BACKLOG.md` tarea 12 · `docs/research_mejoras_2026-07-07.md` §A1 · benchmark gaps G7/G11.
**Hermano de:** tarea 11 (PEAD / anomalía) — misma familia "de dónde salen los candidatos", mismo harness.

Este documento fija la **hipótesis, el detector de cluster, la fuente de datos, el contrafactual, los brazos
y los kill-criteria ANTES de escribir una línea de collector, ingester o harness**. Nada acá se re-decide
después de ver resultados. Si el detector no supera el umbral, se documenta NO-SHIP y no se cablea (misma
disciplina que T7/T8/T9/T10/T11b).

---

## 1. Contexto y objetivo

FinanzIAs necesita **fuentes de candidatos de BUY independientes de `analyze()`**. La serie T7/T8/T9/T10
mostró que refinar decisiones *sobre los candidatos que `analyze()` produce* no rinde (cuándo salir, cuándo
cortar, cuáles rankear, cómo sizear: ninguno agregó alpha); el valor está en **de dónde salen los
candidatos**. La T11b (anomalía precio/volumen) fue la primera señal event-driven: tiene edge real pero
falla robustez de régimen (momentum de ruptura, colapsa en bear). Esta tarea prueba la **segunda fuente
event-driven**: **compras agrupadas de insiders (SEC Form 4)**.

**Por qué insider clusters:** es la evidencia pública más consistente entre las fuentes de leads gratis —
las **compras** de insiders (no las ventas) predicen ~4–8%/año de exceso, y la variante **cluster** (varios
insiders comprando a la vez) es la fuerte; el drift se concentra en los ~6 meses siguientes → compatible con
datos EOD + scan diario. A diferencia del momentum de ruptura (T11b), la señal de insider-buying tiende a ser
**contraria/de valor** (los insiders compran barato), así que la hipótesis interesante es que sea **más
robusta en régimen bajista** — justo la punta donde T11b se rompió.

**Ventaja de calidad decisiva vs T-CAT-5b / Brazo A de la T11:** el Form 4 es **point-in-time por diseño**.
Se publica dentro de los 2 días hábiles de la operación y su **fecha de filing es dato duro** — el sesgo de
revisión que bloquea el consenso point-in-time (T-CAT-5b) **acá no existe**. Por eso FORM4 se puede
backtestear **honestamente ahora**, sin esperar temporadas.

**Objetivo:** medir si una cartera cuyos BUYs nacen de **eventos de insider-cluster** —"≥ C insiders distintos
compran open-market el mismo issuer dentro de una ventana de W días; el ticker entra al día hábil siguiente,
con la misma triple barrera de salida"— **bate a entrar al azar** en el mismo universo con el mismo capital.

**Qué NO es:** no es 13F cloning (descartado 2026-07-07 — lag 45d, evidencia mixta); no es short (solo long
post-cluster de compras; los clusters de *ventas* quedan fuera de alcance); no toca el sizing ni los gates
salvo que pase (regla 3).

---

## 2. El detector de cluster (CONGELADO, sin sweep de forma)

Módulo puro nuevo `analysis/insider_cluster.py` (stdlib, sin red, sin DB — testeable offline con
transacciones sintéticas). Consume una lista de **transacciones de insider ya normalizadas**
`InsiderTx = (issuer_ticker, filing_date, owner_cik, trans_code, acq_disp, shares, price, is_officer,
is_director)` y produce **eventos de cluster** `(ticker, event_date)`.

**Filtro de transacción (CONGELADO):** solo cuentan las que son, todas a la vez:
- **no-derivativa** (tabla `NONDERIV_TRANS` del dataset; se ignoran ejercicios de opciones y derivados),
- **`trans_code == "P"`** (open-market **purchase**; se ignoran grants/awards `A`, ejercicios `M`, ventas
  `S`, disposiciones por impuestos `F`, etc.),
- **`acq_disp == "A"`** (adquisición — redundante con `P` pero se exige por robustez ante datos sucios),
- `shares > 0` y `price > 0`.

**Definición de cluster (PRIMARIA, CONGELADA):** para un issuer, un **evento de cluster** dispara en la
**fecha de filing `f`** de una transacción que cumple el filtro, si el número de **CIK de insider distintos**
(`owner_cik`) con al menos una compra que cumple el filtro cuya `filing_date ∈ [f − W + 1, f]` es **≥ C**,
con:

- **`C = 3`** insiders distintos (la variante cluster fuerte de la evidencia).
- **`W = 15` días calendario** (ventana móvil hacia atrás, inclusiva).

El **event_date** es la `filing_date` del filing que hace que el conteo distinto llegue por primera vez a `C`
dentro de la ventana — o sea el día en que el cluster se vuelve **observable point-in-time**. Distintos por
`owner_cik` (no por nombre: evita variantes de tipeo y doble conteo). Dedup por `accession_number` (un filing
cuenta una vez aunque reporte varias líneas).

- **Entrada:** al **close del día hábil siguiente** al `event_date`, `entry_idx = i(event_date) + 1`.
  Point-in-time estricto: el cluster queda determinado por filings públicos hasta el EOD de `event_date`
  (el scan EOD lo vería), y la orden se llena en la rueda siguiente — exactamente como actuaría el engine
  vivo (scan post-close → fill al próximo close). **Se usa `filing_date`, NO `transaction_date`**: el cluster
  solo es conocible cuando los filings son públicos; usar la fecha de la operación sería look-ahead.
- **Período refractario:** tras un cluster aceptado en un ticker, se saltean los siguientes en ese ticker por
  `cap_days` (20) ruedas — evita re-disparo degenerado mientras corre el drift y espeja el `no reabrir
  mientras está en cartera` del engine.
- **Fail-safe:** requiere que exista la barra de entrada `i+1` y ≥ `warmup` barras previas para los exits;
  si no, no dispara (nunca mira el futuro, nunca rompe por falta de datos).

**Parámetros de forma CONGELADOS (no se barren en el brazo primario):** filtro `P/A` no-derivativo, entrada
`D+1`, refractario `= cap_days = 20`, dirección long-only. Lo único que barre la grilla (§4) es `(C, W)` y una
variante de seniority — y ese barrido se contabiliza como intentos en el DSR (§6).

---

## 3. Fuente de datos y universo (CONGELADO)

Esta es la diferencia sustantiva con T11b (que ya tenía precio/volumen en el cache Parquet). FORM4 necesita
**dos** insumos:

### 3.1 Transacciones de insiders — **SEC Form 345 quarterly datasets** (bulk, estructurado, point-in-time)

Fuente primaria del backtest: los **Insider Transactions Data Sets** de la SEC
(`https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets`), un zip **por trimestre**
(`YYYYqN_form345.zip`) con TSV normalizados: `SUBMISSION` (accession, `FILING_DATE`, `ISSUERCIK`,
`ISSUERTRADINGSYMBOL`), `REPORTINGOWNER` (`RPTOWNERCIK`, flags director/officer), `NONDERIV_TRANS`
(`TRANS_CODE`, `TRANS_ACQUIRED_DISP_CD`, `TRANS_SHARES`, `TRANS_PRICEPERSHARE`).

**Por qué esta fuente y no otra** (decisión de calidad, orden de Chapa 2026-06-25):
- **vs full-text search (`efts.sec.gov`):** el bulk es una descarga por trimestre (~40 para 10y) contra miles
  de requests rate-limited; y ya viene parseado y estructurado por la SEC.
- **vs parsear el XML de cada Form 4 uno por uno** (patrón del collector 8-K): serían **decenas de miles** de
  fetches para 10y × S&P 500. El bulk evita el N×fetch por completo.
- **Point-in-time:** la columna `FILING_DATE` es la fecha oficial de disclosure — dato duro, sin sesgo de
  revisión. Es la razón por la que esta tarea no está bloqueada como el Brazo A.

Reproducible y **offline tras la descarga**: los zips se bajan una vez a `data/form345/` (gitignored, como
`data/pit_signals/`) y el ingester los normaliza a un artefacto local. El collector **vivo** (producción,
fuera de este backtest) usará en cambio la API `submissions` + parse del XML del Form 4 (mismo patrón que
`collect_sec_8k`), pero eso es concern de producción, no del veredicto.

### 3.2 Universo y precios — **S&P 500, 10y, vía el cache existente**

El **valor declarado de FORM4 es lead-sourcing** (candidatos **fuera** de la watchlist de 41). Por eso el test
corre sobre el **universo S&P 500** (~500 nombres, la lista del fallback de UNIV1 / screen E1b), no sobre los
41 tickers cacheados: restringir a 41 large-caps mediría una pregunta menos interesante y probablemente
quedaría *event-starved* (los clusters open-market son más raros en mega-caps). Se acota a los issuers del
universo que tengan al menos un evento de cluster; para ésos y para el pool del baseline se baja el histórico
EOD 10y con la infra de cache existente (`get_historical_data_batch` → Parquet), una vez, cacheado.

**Caveat de survivorship (declarado):** usar la membresía **actual** del S&P 500 introduce sesgo de
supervivencia (nombres que quebraron/salieron no están). Mitigación estructural: el **baseline random se
sortea del MISMO universo** (§4), así el sesgo afecta a los dos brazos por igual y **se cancela en la
comparación** ΔCAGR; el nivel absoluto de CAGR queda sobreestimado en ambos y no se lee como pronóstico.

---

## 4. Contrafactual / baseline y brazos (CONGELADO)

### 4.1 Baseline

La pregunta del kill-criteria del backlog: *"la cartera de eventos cluster-buy bate al baseline (entradas
aleatorias del universo screeneado, mismo capital)"*. Un solo sorteo es ruidoso → el baseline es una
**distribución Monte Carlo**:

- **B_random (benchmark primario):** `K = 500` carteras de entradas aleatorias. Cada sorteo toma `N_clu` pares
  `(ticker, entry_idx)` al azar del universo (restringido a nombres con precio ese día), donde `N_clu` = nº de
  entradas del brazo **PRIMARIO** (§4.2).
  - **Control de confusión temporal (clave):** cada sorteo respeta la **distribución por mes calendario** de
    las entradas del cluster (mismo nº de entradas por mes). Los clusters se concentran en ciertos períodos
    (p.ej. tras caídas de mercado, cuando los insiders compran barato); sin time-matching el benchmark mediría
    *timing de régimen*, no *selección*. Con él, la comparación aísla el valor de la señal.
  - Semillas fijas y ordenadas (reproducible). Mismo `simulate_portfolio`, mismo capital, mismos exits.
  - Se reporta la **distribución** (p5 / mediana / p95) de CAGR, Sharpe y maxDD de las 500 carteras.
- **B_datematched (robustez secundaria, NO gatea):** mismas fechas de disparo, ticker aleatorio del universo
  en cada fecha → separa selección cross-sectional de timing. Diagnóstico; el ship no depende de él.

### 4.2 Brazos pre-registrados

Grilla `(C, W)` + una variante de seniority. Todo lo demás fijo (§2). Idéntico pipeline entre brazos.

| brazo                       | C (insiders) | W (días) | extra |
|-----------------------------|:------------:|:--------:|-------|
| **CLU_C3_W15 (PRIMARIO)**   | **3**        | **15**   | —     |
| CLU_C2_W15                  | 2            | 15       | —     |
| CLU_C4_W15                  | 4            | 15       | —     |
| CLU_C3_W10                  | 3            | 10       | —     |
| CLU_C3_W30                  | 3            | 30       | —     |
| CLU_C3_W15_senior           | 3            | 15       | el cluster debe incluir ≥1 officer (CEO/CFO/insider con flag officer) |

- **Brazo PRIMARIO (titular):** `CLU_C3_W15` — la definición central del backlog (≥3 insiders / ~15 días),
  elegida por la evidencia, **no** por performance. Fija `N_clu` para el baseline y se reporta como referencia.
- **Brazo de decisión:** el de mejor Sharpe anualizado **entre los que pasan el filtro local** (§6),
  convención T10/T11b; sobre él se aplican DSR/PBO. Los **6 brazos** cuentan como intentos para el DSR.
- **Variante de ranking (declarada, no es brazo de detección):** cuando varios clusters compiten por el mismo
  slot el mismo día, el brazo primario desempata por **monto total comprado en dólares** (`Σ shares·price`)
  descendente, luego alfabético (determinista). Es un uso del `rank_score` inyectable de `portfolio_sim`, no
  cambia qué eventos existen. El "ponderado por rol" queda como exploratorio y NO se corre en este pre-registro.
- **Oráculo de validación:** un brazo que rankea las entradas por el retorno realizado (look-ahead deliberado)
  — como en T9/T10/T11b, confirma que el harness **tiene** sensibilidad (si el oráculo no despega, el harness
  está roto y el NO-SHIP no vale). No es candidato.

---

## 5. Métricas

Sobre `analysis/portfolio_sim.py` (`max_positions = 5`, `initial_capital = 50.000`,
`allow_reentry_while_open = False` engine-faithful, `cap_days = 20`, `AtrParams()` default = stop 2×ATR /
TP 4×ATR / trailing, `CostModel()` = comisión 0.1% + slippage 0.05% en las dos puntas):

- **CAGR**, **Sharpe anualizado** y **maxDD de cartera** sobre la curva de equity (`risk_sizing.cagr` /
  `sharpe_annual`) — **NO** puntos acumulados (corrige el defecto de especificación de la lápida de T8).
- Descriptivos (no deciden): win rate, payoff, retorno medio por trade, exposición, mezcla de salidas,
  desglose por régimen, nº de entradas, distribución del tamaño del cluster (cuántos insiders / cuánto $).

**Invariantes que se chequean ANTES de leer el veredicto** (si fallan, el run se descarta): integridad
contable (la curva de equity termina en la equity final calculada), invariante de exits, y el oráculo despega
claramente sobre el baseline.

---

## 6. Kill-criteria (CONGELADOS)

El brazo de **decisión** shipea **si y solo si se cumplen TODOS**:

1. **Significancia estadística:** su **CAGR y su Sharpe** superan el **percentil 95** de la distribución
   B_random (§4.1) → p empírico unilateral < 0.05 en las dos métricas.
2. **Significancia económica:** `ΔCAGR ≥ +2.0 pp` sobre la **mediana** de B_random. Un edge estadísticamente
   real pero trivial no justifica una fuente de señal nueva con su costo operativo (mismo umbral que T11b).
3. **Riesgo:** `maxDD ≤ 1.5 ×` la **mediana** del maxDD de B_random (el "sin DD > 1.5×" del backlog).
4. **Anti-overfitting (selección múltiple sobre 6 brazos):** `DSR > 0.5` **y** `PBO < 0.5`
   (`walkforward_power.deflated_sharpe_ratio` / `pbo_cscv`, matriz de retornos diarios de equity alineados a
   calendario común, patrón T10/T11b).
5. **Robustez de régimen:** el retorno medio por trade es **positivo o neutro en cada régimen**
   (`bull_normal` + los 3 de stress: 2018Q4, COVID-2020, bear-2022). Esta es **la prueba clave que distingue a
   FORM4 de T11b**: la hipótesis es que el insider-buying (contrario/de valor) aguante el bear donde el
   momentum de ruptura se rompió. Si el signo cuelga de un solo régimen bull → NO-SHIP, igual que T11b.
6. **Robustez por nombre (leave-one-ticker-out):** sacar el ticker que más aporta al edge **no invierte el
   signo** del ΔCAGR — la señal no puede ser un solo nombre disfrazado.

Si el brazo de decisión falla **cualquiera** → **NO-SHIP**, se documenta el hallazgo y el detector +
`insider_transactions` quedan como enabler (el dato acumulado sirve como **feature del meta-modelo** futuro,
mismo criterio que T9/T11b). El collector vivo se puede shipear igual como acumulador point-in-time aunque el
brazo no cablee (decisión aparte).

**Si PASA:** se cablea detrás de un flag propio **default OFF** (regla 3: opción nueva no prendida por
default), inyectando los candidatos en `generate_trades_analyze_single` por el mismo pipeline de gates/screen
que cualquier BUY; hereda en producción el escalado por régimen T20 (ya activo) y el earnings-blackout
(Gate 6). El valor validado de `(C, W)` queda como default del flag. Los candidatos fuera de la watchlist
pasan por el universe screen E1b antes de entrar.

---

## 7. Qué NO se modela (caveats declarados antes de correr)

- **Overlay de régimen T20 (activo en prod):** el harness mide la señal **sin** el escalado risk-off ×0.5 para
  atribución limpia. En producción el candidato lo hereda (orthogonal, ya shipeado). Anotado.
- **Modo "prior sobre la watchlist":** el backlog define dos modos (prior direccional sobre los 52 vivos +
  lead-sourcing real). Se testea **solo el lead-sourcing** (S&P 500) — es el más difícil y el que justifica la
  feature; el modo prior es un subconjunto (restringir el mismo detector a la watchlist) y no necesita su
  propio veredicto.
- **Screen de universo E1b:** el test corre sobre el S&P 500 sin la pata de liquidez del screen; el sourcing
  filtrado por liquidez es concern de producción.
- **Salida:** es la triple barrera completa del engine (ATR stop/TP/trail + flip `analyze SELL`), idéntica a la
  de todos los BUYs. Fiel e intencional ("misma triple barrera de salida", ref backlog).
- **Survivorship** (§3.2): membresía S&P 500 actual → nivel absoluto de CAGR sobreestimado en ambos brazos; se
  cancela en el ΔCAGR contra el baseline del mismo universo.
- **Form 4/A (enmiendas):** se usa la `filing_date` original; las enmiendas se deduplican por accession. Un
  filing tardío (fuera del plazo de 2 días) sigue siendo point-in-time por su `filing_date` real.
- **Márgenes, apalancamiento, dividendos, intradía:** fuera de alcance (limitaciones de `portfolio_sim`).
- **`auto_adjust=True`** introduce el lookahead conocido de backtests largos (sesgo transversal, igual que
  siempre). Tenerlo presente al leer niveles.

---

## 8. Plan de ejecución

1. **Ingester** `scripts/ingest_form345.py` — baja/lee los zips `YYYYqN_form345.zip` a `data/form345/`,
   joinea SUBMISSION×REPORTINGOWNER×NONDERIV_TRANS, aplica el filtro `P/A` no-derivativo, y escribe un
   artefacto normalizado `list[InsiderTx]` por ticker (JSON/parquet local, gitignored). Sin tocar `finanzias.db`.
2. **Detector** `analysis/insider_cluster.py` — puro (§2): `build_cluster_events(txs, C, W, cap_days) →
   list[(ticker, event_date)]` + helpers de tamaño de cluster ($ y nº insiders) para el ranking.
3. **Harness** `scripts/run_insider_cluster_replay_t12.py` — carga barras del Parquet + los eventos de los 6
   brazos, arma B_random (Monte Carlo time-matched) + oráculo, corre `simulate_portfolio`, computa
   CAGR/Sharpe/maxDD, DSR/PBO sobre los 6 brazos, aplica §6. Sin red en la corrida (datos precargados), sin
   tocar `finanzias.db`.
4. **Tabla `insider_transactions`** (alembic, append-only) — solo si se decide shipear el **collector vivo**
   (independiente del veredicto del brazo); el backtest usa el artefacto local, no la DB.
5. **Tests offline** (`tests/test_insider_cluster.py`): cluster dispara / no dispara al borde de C y W, PIT
   (usa filing_date no transaction_date; no mira el futuro), refractario, dedup por accession, filtro de
   código (una venta `S` o un grant `A` no cuentan; un ejercicio `M` no cuenta), distinct por CIK (dos líneas
   del mismo owner = 1), fail-safe sin barra `i+1`, determinismo del baseline.
6. **Correr** vía agente `backtest-runner` sobre el backup limpio + Parquet precargado + artefacto Form 345.
7. **Veredicto** en `docs/insider_cluster_t12_2026-07-24.md` (ship/no-ship + por qué).
8. Si SHIP: cablear detrás de flag default OFF + tests de engine + suite Windows verde. Si NO-SHIP: documentar
   y dejar el detector + el ingester como enablers.

**Congelado. Cualquier cambio a §2–§6 después de ver un resultado invalida el pre-registro.**
