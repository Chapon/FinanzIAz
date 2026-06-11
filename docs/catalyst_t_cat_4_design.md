# T-CAT-4 — Impact Score heurístico v1 (diseño)

**Sprint 5 · Catalyst Intelligence Engine · 2026-06-11**

Status: **DISEÑO** (no implementado). Aprobación de Chapa pendiente antes de codear.

Predecesores cerrados: T-CAT-0 (harvest point-in-time), T-CAT-1 (collectors SEC/RSS),
T-CAT-2 (classifier 17 categorías → `event_type/sentiment/confidence`, persistido con
`classified_by`), T-CAT-3 (`historical_reaction` = forward returns por tipo + `relevance`
= $/market_cap). T-CAT-4 **compone** esas piezas en un único número por evento y diseña su
primer consumidor concreto: el **exit-veto**.

---

## 0. Qué es y qué no es

El Impact Score es un **escalar determinístico** que responde "¿cuánto debería importarme
este catalizador para este ticker, y en qué dirección?". No es un modelo, no se entrena
(eso sería T-CAT-7), no toca el sizing del motor de precio (T-CAT-8, diferido). Es el
pegamento entre la clasificación cruda (T-CAT-2) y la reacción empírica (T-CAT-3).

Dos superficies de uso, deliberadamente separadas porque tienen horizontes opuestos:

1. **Score retrospectivo de un evento ya publicado** — "este 8-K de earnings de NVDA, dado
   cómo suele reaccionar NVDA a earnings y cuán grande es la cifra, tiene impacto +X". Sirve
   para rankear/medir y alimenta paneles y, eventualmente, el backtest de T-CAT-6.
2. **Señal prospectiva de catalizador inminente** — "¿hay un catalizador *conocido y futuro*
   (fecha de earnings en ≤K días hábiles) cuya reacción esperada es positiva?". Esta es la
   que consume el **exit-veto**. Es forward-looking y NO se construye a partir de noticias
   pasadas sino de la **fecha de earnings próxima** + la reacción histórica del ticker.

Mezclar las dos en un solo número fue tentador pero es un error: el caso MRVL (vendido por
señal técnica el día *antes* de earnings) se resuelve sabiendo que hay un evento **mañana**,
no puntuando un evento de ayer. Se mantienen como dos funciones distintas con un núcleo
compartido (la magnitud de reacción esperada).

---

## 1. Inputs disponibles (recap, todo ya en el repo)

| Pieza | De dónde | Forma |
|---|---|---|
| `event_type, sentiment, confidence` | `data.catalyst_classifier.classify(...)` (T-CAT-2) | labels sobre taxonomía de 17 |
| `historical_reaction` table | `analysis.catalyst_reaction.build_historical_reaction(...)` (T-CAT-3) | `by_event` / `by_ticker_event` → `ReactionStat(count, mean, std, hit_rate)` por horizonte 1/5/20 |
| `lookup_reaction(table, ticker, event_type, h)` | T-CAT-3 | stat con fallback ticker→global, `min_count=5` |
| `extract_dollar_amount(text)` / `relevance($, mcap)` | T-CAT-3 | magnitud económica 0..1+ |
| Próxima fecha de earnings | `EarningsCache` / yfinance (ya usado en Gate 6 blackout) | `date | None` |
| `market_cap` | yfinance / cache de fundamentals existente | float |
| OHLCV cache | `historical_data_cache` vía `price_loader` | DataFrame Close |

No se agrega ninguna fuente nueva. Si falta un input (mcap None, sin historia de reacción),
el componente correspondiente cae a neutro — **fail-soft, nunca raise** (mismo contrato que
los collectors y el classifier).

---

## 2. Fórmula del Impact Score retrospectivo (v1)

Para un evento `e = (ticker, event_type, sentiment, confidence, headline, published_at)`:

```
impact(e, h) = direction
             × magnitude
             × confidence_weight
             × relevance_weight
```

Cada factor en un rango acotado y con default neutro explícito:

**`direction` ∈ {-1, 0, +1}** — el signo del move esperado. Se toma del **signo de la
reacción histórica** (`sign(reaction.mean)` a horizonte h) cuando hay muestra suficiente;
si no hay historia, se cae al `sentiment` del classifier (`positive→+1`, `negative→-1`,
`neutral→0`). Priorizar la reacción medida sobre el sentiment del titular es deliberado: el
sentiment es una heurística de palabras; la reacción es lo que el mercado realmente hizo.

**`magnitude` ∈ [0, 1]** — cuán grande es el move típico, normalizado. Se usa
`|reaction.mean|` aplastado por una saturación suave para que un outlier no domine:

```
magnitude = tanh(|reaction.mean(h)| / SCALE)      # SCALE ≈ 0.05 (5% move ≈ 0.76)
```

Si no hay reacción histórica (count 0 incluso en el global), `magnitude` cae a un **prior
por event_type** (tabla fija abajo) — earnings/M&A/FDA pesan más que stock_movement/other.

**`confidence_weight` ∈ [0.4, 1]** — escala por la confianza del classifier y, crucialmente,
por el **tamaño de muestra** de la reacción histórica (un `mean` con n=2 es ruido):

```
confidence_weight = clamp(0.4 + 0.6 × classifier_confidence × sample_factor, 0.4, 1.0)
sample_factor     = min(1.0, reaction.count / MIN_SAMPLE)     # MIN_SAMPLE = 8
```

El piso 0.4 evita anular eventos materiales solo por poca historia; el techo respeta que
ni el clasificador ni la muestra son perfectos.

**`relevance_weight` ∈ [1, 1+R]** — empuja eventos económicamente grandes:

```
relevance_weight = 1 + R × tanh(relevance / REL_SCALE)        # R = 0.5, REL_SCALE = 0.10
```

`relevance` = `$amount / market_cap` (T-CAT-3). Un contrato de $1B sobre una empresa de $10B
(relevance 0.10) pesa ~1.4×; sin cifra extraíble, `relevance_weight = 1` (no penaliza).

Resultado: `impact(e, h) ∈ [-1.5, +1.5]` aprox., centrado en 0, interpretable
(signo = dirección, magnitud = convicción). El horizonte default operativo es **h=5**
(consistente con que el modelo de precio predice a 5 días — la auditoría mostró que ese es
el horizonte donde el alpha vive).

### Prior por event_type (cuando no hay reacción histórica)

Magnitud base ∈ [0,1], sin signo (el signo lo da sentiment en ese caso):

| event_type | prior | event_type | prior |
|---|---|---|---|
| earnings_results | 0.90 | capital_return | 0.45 |
| clinical_fda | 0.90 | partnership_contract | 0.45 |
| mna | 0.85 | executive_change | 0.40 |
| guidance_raise/cut | 0.80 | financing_offering | 0.40 |
| legal_regulatory | 0.65 | insider_activity | 0.30 |
| analyst_rating | 0.55 | macro_sector | 0.30 |
| product_launch | 0.50 | stock_movement | 0.15 |
| restructuring | 0.60 | other | 0.10 |

Estos priors son **hipótesis explícitas, no verdad**: existen solo para el arranque en frío
y se vuelven irrelevantes a medida que la reacción histórica acumula muestra (T-CAT-0 sigue
harvesteando). Documentados acá para que el día que el backtest los contradiga, se ajusten
con evidencia, no a ojo.

### M2 del code review — entry next-day open para el componente tradeable

T-CAT-3 calcula forward returns con entry = primer día hábil on/after el evento, usando
**Close**. Para *medir reacción histórica* eso está bien. Pero el componente que el motor
podría tradear (el exit-veto) no puede asumir que entró al close del día del anuncio: una
noticia after-hours ya tiene el gap incorporado en ese close. **M2**: para cualquier uso
*accionable* del score, el forward return debe medirse con **entry = next-day open**
(`Open` de la barra siguiente al evento), reservando el entry actual (Close mismo día) solo
para la tabla descriptiva "cómo reaccionó". Concretamente:

- `catalyst_reaction.forward_return(...)` gana un parámetro `entry="close"|"next_open"`
  (default `"close"` para no romper T-CAT-3); el Impact Score accionable pide `"next_open"`.
- Requiere que `price_loader` devuelva la columna `Open` (ya está en el cache OHLCV).

Esto cierra explícitamente M2 (`docs/code_review_2026-06-09.md`).

---

## 3. Señal prospectiva: catalizador inminente (lo que consume el exit-veto)

Función separada, forward-looking:

```
imminent_catalyst(ticker, asof_date, *, horizon_bdays=K) -> CatalystSignal | None
```

Devuelve `None` si no hay catalizador conocido y futuro dentro de la ventana. Hoy la única
fuente confiable de un evento *futuro datado* es la **próxima fecha de earnings**
(`EarningsCache`, el mismo input que el Gate 6 blackout ya consume). v1:

```
CatalystSignal:
    kind: "earnings"
    days_until: int                 # días hábiles hasta el evento
    expected_direction: -1|0|+1     # sign(reaction_histórica earnings_results para el ticker)
    expected_magnitude: float       # magnitude de §2 sobre event_type="earnings_results"
    score: float                    # direction × magnitude × confidence_weight (sin relevance)
```

- `days_until ≤ K` (K = `paper_catalyst_imminent_bdays`, default **3**) → "inminente".
- `expected_direction`/`magnitude` salen de `lookup_reaction(table, ticker,
  "earnings_results", h=5)`. Si el ticker no tiene historia propia, cae al global de
  `earnings_results`; si tampoco hay, `expected_direction = 0` → **no veta** (sin evidencia
  de upside, no se interfiere con el exit).

Honestidad de diseño: en v1 "catalizador inminente" = **solo earnings**. Es el caso de la
auditoría (MRVL) y el único evento futuro con fecha confiable y gratis. FDA/M&A datados
quedan para v2 cuando haya fuente de calendario. No se inventa "inminencia" a partir de
noticias pasadas.

---

## 4. El consumidor: exit-veto (Gate 2c)

Simétrico del earnings-blackout de BUYs (Gate 6), pero para SELLs. Se enchufa en
`paper_trading/engine.py` **inmediatamente después de Gate 2b** (la hysteresis de T6.4,
líneas ~625-643), reusando exactamente la misma población elegible para no contaminar nada:

**Elegibilidad (todas deben cumplirse):**
- `trade.side == "SELL"` y **no** es risk_exit (`atr_*`/`vol_trim` nunca se vetan — un stop
  de riesgo manda sobre cualquier catalyst).
- Es un SELL **de señal con score en zona gris** — el mismo rango que gobierna T6.4
  (score en `[bypass_score, gray_high]`, p.ej. `[0.25, 0.50]`). SELLs de altísima convicción
  (score alto) **se ejecutan igual**: si el modelo está muy seguro de salir, un earnings no
  lo frena.
- `imminent_catalyst(ticker, scan_at, horizon_bdays=K)` devuelve señal con
  `expected_direction == +1` y `score ≥ veto_min_score`.

**Acción:** bloquear el SELL este ciclo (igual que Gate 2b: `skipped += 1` + warning
explicativo), dejándolo para reevaluación post-evento. NO es un buy, NO cambia sizing — solo
pospone una venta de baja convicción frente a un upside conocido inminente.

**Flag y defaults (DEFAULT OFF):**
```
paper_catalyst_exit_veto_enabled = False   # ← OFF hasta que T-CAT-6 lo valide
paper_catalyst_imminent_bdays     = 3
paper_catalyst_veto_min_score     = 0.30
paper_catalyst_veto_gray_high     = 0.50   # techo de score elegible (reusa zona gris T6.4)
```

Queda **detrás de flag, default OFF**, por la misma disciplina que todo lo no validado: se
shipea el código + tests con el flag, pero NO se activa en producción hasta que el backtest
de **T-CAT-6** muestre que mejora el P/L sin empeorar el max DD (kill criteria abajo). Esto
respeta la regla del roadmap: *no tocar la lógica de exits por corazonada; el experimento
manda*.

---

## 5. Forma del módulo — `analysis/impact_score.py`

Funciones puras, sin estado, `price_loader`/`earnings_loader` inyectables → testeable offline
(mismo patrón que `catalyst_reaction.py`).

```python
@dataclass(frozen=True)
class ImpactScore:
    value: float            # [-1.5, 1.5] aprox
    direction: int          # -1|0|+1
    magnitude: float        # [0,1]
    confidence_weight: float
    relevance_weight: float
    horizon: int
    basis: str              # "reaction" | "prior" — de dónde salió la magnitud (trazabilidad)

def score_event(
    ticker, event_type, sentiment, classifier_confidence,
    *, reaction_table, headline=None, market_cap=None, horizon=5,
) -> ImpactScore: ...

@dataclass(frozen=True)
class CatalystSignal:
    kind: str               # "earnings" (v1)
    days_until: int
    expected_direction: int
    expected_magnitude: float
    score: float

def imminent_catalyst(
    ticker, asof_date, *, reaction_table, earnings_loader, horizon_bdays=3, score_horizon=5,
) -> "CatalystSignal | None": ...

# Constantes calibrables arriba del módulo (SCALE, MIN_SAMPLE, R, REL_SCALE, EVENT_PRIORS)
```

El engine importa solo `imminent_catalyst` + un helper de elegibilidad por score. El score
retrospectivo (`score_event`) lo consumen paneles/backtest, no el hot-path de trading.

---

## 6. Plan de tests (`tests/test_impact_score.py`)

Determinístico, offline, sin red (frames sintéticos):

- **Direction**: reacción histórica media positiva → `direction = +1` aunque el sentiment
  diga negative (la reacción manda); sin historia → cae a sentiment.
- **Magnitude saturación**: reacción de 50% no produce magnitude >1; 0% → ~0; usa prior
  cuando count=0.
- **Sample factor**: misma `mean` con count=2 vs count=20 → confidence_weight menor en el de
  poca muestra.
- **Relevance**: `$5B / $10B mcap` empuja el score ~1.4×; headline sin cifra → weight 1.0.
- **Fail-soft**: mcap None, reaction_table vacía, event_type fuera de taxonomía → no raise,
  score neutro/0.
- **M2 next_open**: `forward_return(entry="next_open")` usa Open de la barra siguiente, no el
  Close del día del evento; verifica divergencia en un fixture con gap overnight.
- **imminent_catalyst**: earnings en 2 días hábiles con reacción histórica + → señal con
  direction +1; earnings en 10 días → None (fuera de ventana); sin historia → direction 0.
- **Gate 2c (integración engine)**: SELL gris + catalyst inminente + flag ON → bloqueado;
  flag OFF → pasa; risk_exit (atr_/vol_trim) → nunca vetado; SELL score alto (>gray_high) →
  no vetado; BUY → intacto (no se toca la lógica de compras).

Suite completa en **Windows** antes de declarar done (regla de workflow). Verificar 0
null-bytes tras edits que achiquen archivos (bug conocido del Edit tool).

---

## 7. Kill criteria upfront (la activación la decide T-CAT-6)

El **código** de T-CAT-4 (módulo + Gate 2c tras flag + tests) se considera DONE cuando la
suite pasa en Windows. Pero la **activación del exit-veto en producción** está atada a un
criterio medible, fijado ahora para no racionalizar después:

> El exit-veto se activa (`paper_catalyst_exit_veto_enabled = True`) sólo si el replay de
> T-CAT-6 sobre los ciclos reales muestra que vetar los SELLs grises con catalyst inminente
> positivo mejora el P/L total **≥ +1.5 puntos** sin aumentar el max DD **más de 1.3×**, y
> sin reducir el opportunity-capture del panel T6.2. Si no pasa, queda como dead-code
> documentado (mismo destino que cross-sectional en T05) y se documenta por qué.

Este umbral es más estricto que el de T6.1 (+2 pts) en P/L porque el universo de eventos es
chico (pocos earnings caen junto a un SELL gris), así que se exige también no degradar las
otras métricas, no solo el P/L agregado.

---

## 8. Fuera de alcance de T-CAT-4 (cerrado)

- No entrenar nada (T-CAT-7).
- No tocar el sizing del motor de precio (T-CAT-8, diferido).
- No tocar la lógica de **BUYs** — la auditoría mostró que las entradas funcionan; T-CAT-4
  sólo agrega un gate de exit *opt-in*. (Regla explícita del roadmap v3.)
- No inventar "inminencia" para eventos sin fecha confiable (FDA/M&A datados → v2).
- No activar el veto sin el backtest de T-CAT-6 (§7).

---

## 9. Definition of Done (T-CAT-4)

1. `analysis/impact_score.py` con `score_event` + `imminent_catalyst` + `ImpactScore`/
   `CatalystSignal`, puro e inyectable.
2. M2 cerrado: `catalyst_reaction.forward_return(entry=...)` con `next_open` y T-CAT-3 sin
   regresión (default `close`).
3. Gate 2c en `engine.py` tras Gate 2b, detrás de flag **default OFF**, sólo SELLs grises,
   risk_exits exentos, BUYs intactos.
4. `tests/test_impact_score.py` + tests de integración del Gate 2c, **verdes en Windows**.
5. Settings nuevos registrados con defaults seguros (veto OFF).
6. Kill criteria de activación (§7) escritos y vinculados a T-CAT-6.

El alpha NO se mide acá. T-CAT-4 entrega el **mecanismo** y su criterio de prueba; la
decisión de encenderlo es de T-CAT-6 con evidencia.
