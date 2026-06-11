# T-CAT-0 — Gate cero: harvesting point-in-time (diseño)

**Sprint 5 · Catalyst Intelligence Engine · 2026-06-05**

Status: PLANEADO. Este es el BLOCKER de todo el Sprint 5 (T-CAT-5/6/7 son imposibles de
validar sin esta data acumulada). Objetivo único: **empezar a acumular noticias y consenso
de analistas con timestamp de observación desde hoy**, para que dentro de semanas/meses se
pueda backtestear reacción a catalizadores sin lookahead.

T-CAT-0 NO tiene alpha que validar. Su definition-of-done es **integridad de datos +
acumulación arrancada**, nada más.

---

## 0. Por qué esto es el gate cero

El "secreto" de la propuesta (niveles 5-7) es el **surprise score = actual vs. consenso
*tal como estaba antes del evento***. Eso exige consenso *point-in-time*, y ahí está la
trampa que ya conocemos:

- yfinance `Ticker.recommendations` devuelve solo **4 snapshots mensuales móviles**, no
  histórico real (mismo problema documentado en analyst-features 2026-06-04).
- yfinance `earnings_estimate` / `eps_trend` / `eps_revisions` dan el consenso **actual**,
  un único snapshot, sin historia.
- No hay fuente gratis de **historia de consenso EPS/guidance**.

Conclusión: la única vía gratis para tener consenso point-in-time es **snapshotearlo
nosotros, diario, append-only, desde ya**. Si no arranca hoy, en 3 meses seguimos sin poder
calcular surprise sobre earnings pasados. Por eso T-CAT-0 es lo primero y corre en
background mientras se construyen los wins baratos (T-CAT-1..4).

**Disciplina central:** todo se guarda con `fetched_at` = fecha de observación, y NUNCA se
sobrescribe. Append-only. El valor de la tabla está en la serie temporal de observaciones,
no en el último estado.

---

## 1. Schema (dos tablas nuevas en `database/models.py`)

Siguen las convenciones existentes: `Base` declarative, `utcnow_naive` como default,
columna `fetched_at` indexada, `Index(...)` explícito en `__table_args__`. Se registran en
`init_db()` vía `Base.metadata.create_all` (ya corre sobre todos los modelos importados).
Como es SQLite, agregar tablas nuevas no requiere migración destructiva — `create_all` las
crea si no existen. (No tocar `_migrate()` salvo para columnas nuevas en tablas viejas.)

> **Nota 2026-06-11 (T7.3)**: el párrafo anterior quedó obsoleto — `_migrate()` ya no
> existe y los cambios de esquema van por revisión alembic. Ver `docs/schema_management.md`.

```python
class NewsEvent(Base):
    """
    Noticia cruda capturada point-in-time. Append-only: una fila por
    (noticia, fuente) observada. Los campos de clasificación (event_type,
    sentiment, classifier_confidence) quedan NULL hasta que T-CAT-2 los
    rellena — NO se re-fetchea ni se sobrescribe la noticia.
    """
    __tablename__ = "news_events"
    __table_args__ = (
        Index("ix_news_ticker_published", "ticker", "published_at"),
        Index("ix_news_content_hash", "content_hash", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), nullable=False, index=True)
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=True)          # summary o cuerpo si la fuente lo da
    source = Column(String(50), nullable=False)    # "yfinance", "sec_8k", "pr_rss", ...
    url = Column(Text, nullable=True)
    published_at = Column(DateTime, nullable=True)  # timestamp que declara la fuente
    fetched_at = Column(DateTime, default=utcnow_naive, index=True)  # cuándo LO VIMOS

    # content_hash = sha1(ticker | title-normalizado | published_at-redondeado)
    # → idempotencia: re-correr el harvester el mismo día no duplica.
    content_hash = Column(String(40), nullable=False)

    # Rellenados por T-CAT-2 (clasificador LLM). NULL = sin clasificar todavía.
    event_type = Column(String(40), nullable=True)
    sentiment = Column(String(12), nullable=True)          # positive/neutral/negative
    classifier_confidence = Column(Float, nullable=True)
    classified_at = Column(DateTime, nullable=True)


class AnalystEstimateSnapshot(Base):
    """
    Snapshot diario del consenso de analistas para un ticker+métrica.
    Append-only: una fila por (ticker, metric, period_label, snapshot_date).
    La serie de snapshots es lo que permite, post-earnings, leer el consenso
    'tal como estaba el día antes' → base del surprise score (T-CAT-5).
    """
    __tablename__ = "analyst_estimate_snapshots"
    __table_args__ = (
        Index("ix_est_ticker_metric_date", "ticker", "metric", "snapshot_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), nullable=False, index=True)
    metric = Column(String(24), nullable=False)        # "eps", "revenue", "rec_mean", "price_target"
    period_label = Column(String(16), nullable=True)   # "0q","+1q","0y","+1y" o "2026-09"
    consensus_value = Column(Float, nullable=True)
    num_analysts = Column(Integer, nullable=True)
    snapshot_date = Column(DateTime, default=utcnow_naive, index=True)  # día de observación
    fetched_at = Column(DateTime, default=utcnow_naive)
```

Notas de diseño:
- **`content_hash` UNIQUE** es lo que da idempotencia barata. El harvester hace
  `INSERT ... ON CONFLICT DO NOTHING` (o `try/except IntegrityError` por fila). Correr 1 o 5
  veces el mismo día deja exactamente las mismas filas.
- **Clasificación in-place, no tabla aparte.** T-CAT-2 hará `UPDATE news_events SET
  event_type=... WHERE id=...`. Esto es la única excepción al append-only y es segura: añade
  metadata, no altera la observación cruda (`title/content/published_at/fetched_at`).
- `published_at` puede ser NULL (algunas RSS son flojas); el hash usa published_at redondeado
  a hora o, si falta, `fetched_at` del día — evita colisiones espurias.

---

## 2. Fuentes — matriz de viabilidad (gratis primero)

| Fuente | Qué da | Costo | Point-in-time confiable | Fase |
|---|---|---|---|---|
| yfinance `Ticker.news` | titulares + link + publisher + ts | gratis | sí (ts del publisher) | **MVP** |
| SEC EDGAR 8-K (full-text search / RSS) | filings materiales oficiales | gratis | **sí, el más confiable** (fecha oficial) | **MVP** |
| PR Newswire / Business Wire / GlobeNewswire RSS | press releases corporativos | gratis | sí | **MVP** |
| yfinance `earnings_estimate` / `eps_trend` | consenso EPS **actual** (snapshot) | gratis | solo si lo snapshoteamos diario | **MVP** (→ estimates table) |
| yfinance `recommendations` / `analyst_price_targets` | rec_mean + price target actual | gratis | solo si lo snapshoteamos diario | **MVP** (→ estimates table) |
| Reuters / Benzinga / Bloomberg / MarketWatch | cobertura premium | **pago / scraping hostil** | sí | opt-in futuro, NO bloquea MVP |
| Historia de consenso EPS (FactSet/Zacks/Refinitiv) | surprise sin esperar | **pago** | sí | opcional, evita el warm-up de meses |

Decisión MVP: arrancar con **yfinance news + SEC 8-K + PR/BW/GNW RSS** para `news_events`, y
**snapshot diario de yfinance estimates + recommendations + price_targets** para
`analyst_estimate_snapshots`. Todo gratis. Las pagas se documentan como aceleradores
opcionales, no como dependencia.

Caveat honesto a dejar escrito: con solo fuentes gratis, el surprise score (T-CAT-5) tiene
**warm-up de meses** hasta acumular suficientes ciclos de earnings con consenso pre-evento.
Comprar historia de consenso es la única forma de saltarse esa espera — decisión de Chapa.

---

## 3. Harvester — `scripts/harvest_catalysts.py`

Script standalone, idempotente, pensado para correr una vez por día. **Corre en Windows**
(no en el sandbox Linux — recordar la incoherencia virtiofs de `finanzias.db`: nunca escribir
la DB desde Linux).

Pseudo-estructura:

```python
def harvest(universe: list[str] | None = None, sources: set[str] | None = None) -> HarvestReport:
    tickers = universe or _watchlist_union_positions(account_id=1)  # Sim Principal
    with session_scope() as s:
        for t in tickers:
            for item in collect_news(t, sources):          # yfinance + sec + rss
                _insert_news_if_new(s, item)                # dedup por content_hash
            for snap in collect_estimates(t):               # eps/rev/rec/pt actuales
                _insert_estimate_snapshot(s, t, snap)       # 1 fila/métrica/día
    return report  # nuevos, duplicados-saltados, tickers-fallidos
```

Decisiones:
- **Universo por defecto = watchlist de Sim Principal ∪ posiciones** (consistente con
  `engine.py:392`). Flag `--universe sp500` para escanear SP500 cuando se quiera ampliar
  cobertura (más caro en requests).
- **Reusa la plomería existente**: `_run_with_timeout`, rate-limit token bucket y
  `session_scope` ya están en el repo. Negative caching como en `EarningsCache` (si una
  fuente no cubre un ticker, no re-hammerear).
- **Idempotente**: `content_hash` UNIQUE + "1 snapshot de estimate por día" (chequear
  `snapshot_date == today` antes de insertar) → re-correr no duplica.
- **Tolerante a fallos por fuente**: cada fuente en su `try/except`; una RSS caída no tumba
  el run (mismo patrón que `get_analyst_data`).
- **Reporte al final**: filas nuevas, duplicados saltados, tickers fallidos → loguear y, si
  Slack está configurado (`integrations/slack.py`), mandar un resumen de 1 línea.

---

## 4. Scheduling — dónde corre el cron diario

El harvesting **debe correr todos los días** independientemente de si la app está abierta, e
idealmente **después del cierre** (~16:30 ET) para capturar el día completo de noticias +
el consenso de cierre. Tres opciones:

1. **Windows Task Scheduler** (recomendado) — una tarea que ejecuta
   `python scripts/harvest_catalysts.py` a las 16:30 ET. Corre aunque la app esté cerrada,
   desacoplado del trading. Es el equivalente nativo del cron y evita el problema de
   escribir la DB desde el sandbox Linux.
2. **Wire al cron diario existente de la app** (`paper_trading/scheduler.py`, trigger
   "Daily cron") — barato de implementar (ya existe la maquinaria `paper_daily_scan`), pero
   solo corre si la app está abierta a esa hora. Aceptable si la usás a diario.
3. **Cowork scheduled task** — NO recomendado para esto: correría en el contexto del agente
   (sandbox Linux) y escribiría `finanzias.db` desde Linux, justo lo que la nota de
   incoherencia virtiofs prohíbe. Sirve para reportes/lecturas, no para este write diario.

Recomendación: **Opción 1** (Task Scheduler) como fuente de verdad del harvesting; opcional
**Opción 2** como respaldo "si la app está abierta, asegurate de haber corrido hoy".

---

## 5. Plan de tests (`tests/test_harvest_catalysts.py`)

Sin red en los tests — fixtures con payloads grabados de cada fuente.

- **Dedup / idempotencia**: insertar la misma noticia 2x → 1 fila. Correr `harvest()` 2x
  sobre el mismo fixture → cero filas nuevas en la 2da pasada.
- **Append-only de estimates**: 2 snapshots en días distintos → 2 filas; 2 en el mismo día →
  1 fila.
- **content_hash estable**: misma noticia con whitespace/caso distinto en el título → mismo
  hash (normalización).
- **Tolerancia a fallos**: una fuente que tira excepción no impide insertar las otras.
- **Parsers por fuente**: yfinance news, SEC 8-K, RSS → mapear correctamente a `NewsEvent`.
- **Universo**: default = watchlist de account 1; `--universe sp500` expande.
- **Negative caching**: ticker sin cobertura no se re-fetchea dentro de la TTL.

Correr la suite en Windows antes de declarar done (regla de workflow). Verificar 0 null-bytes
en los archivos editados si algún Edit achicó contenido (bug conocido del Edit tool).

---

## 6. Definition of Done (T-CAT-0)

1. `NewsEvent` + `AnalystEstimateSnapshot` creadas vía `init_db()` en la DB real.
2. `scripts/harvest_catalysts.py` corre idempotente sobre la watchlist de Sim Principal sin
   duplicar al re-ejecutar.
3. Tests verdes en Windows.
4. Scheduling activo (Task Scheduler u opción elegida) → **la acumulación arrancó**.
5. Verificado: tras 1 corrida hay filas en ambas tablas con `fetched_at`/`snapshot_date` de
   hoy, y una 2da corrida no agrega duplicados.

No se mide alpha acá. El éxito es: **mañana hay un día más de data point-in-time que ayer.**

---

## 7. Qué NO hacer en T-CAT-0 (alcance cerrado)

- No clasificar noticias todavía (eso es T-CAT-2).
- No calcular impact/surprise/score (T-CAT-4/5).
- No entrenar nada (T-CAT-7).
- No integrar al sizing del motor de precio (T-CAT-8, decisión diferida).
- No agregar fuentes pagas hasta que el MVP gratis esté acumulando y se justifique el gasto.
```
