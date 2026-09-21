"""
T-CAT-0 harvester — daily point-in-time ingest of news + analyst consensus.

Sprint 5 · Catalyst Intelligence Engine · gate cero.

Runs once per day (recommended: ~16:30 ET via Windows Task Scheduler, decoupled
from the trading scans). Idempotent: re-running the same day adds no duplicates.
It only writes the two append-only tables ``news_events`` and
``analyst_estimate_snapshots`` — no alpha, no classification, no scoring. The
whole point is that *tomorrow there is one more day of point-in-time data than
today*.

IMPORTANT: run this on Windows (where ``finanzias.db`` lives). Never run the
write path from the Linux sandbox — see the virtiofs-incoherence note.

Usage
-----
    python scripts/harvest_catalysts.py                 # Sim Principal watchlist
    python scripts/harvest_catalysts.py --account-id 1
    python scripts/harvest_catalysts.py --universe sp500
    python scripts/harvest_catalysts.py --tickers NVDA,PLTR,RKLB
    python scripts/harvest_catalysts.py --sources yfinance,sec,finnhub
    python scripts/harvest_catalysts.py --dry-run       # collect + report, no writes
    python scripts/harvest_catalysts.py --budget-seconds 780   # techo de 13 min (0 = sin techo)

Finnhub: set a free key once (Windows: ``setx FINNHUB_API_KEY "your-key"``) so
the scheduled harvest sees it. Without the key the finnhub source is skipped.
News rows are deduped both by content_hash and by canonical URL, so enabling
overlapping sources (e.g. finnhub + yfinance) won't double-count a shared story.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Allow ``python scripts/harvest_catalysts.py`` from the repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.exc import IntegrityError

from config.logging_config import get_logger
from data.news_sources import _CollectResult, collect_all
from database.models import (
    AnalystEstimateSnapshot,
    NewsEvent,
    session_scope,
    utcnow_naive,
)

log = get_logger(__name__)

# T70: era `1` ("Sim Principal"), pausada desde el 2026-07-01 — el harvest
# recolectaba para 52 tickers en vez de los 128 del universo vivo, y esa cobertura
# NO se recupera (la fuente consulta `days_back=7`). Ahora se resuelve contra
# `is_active` en tiempo de ejecución, no en el import: un default de argparse que
# pega a la DB al importar el módulo rompe el `--help` y los tests.
DEFAULT_ACCOUNT_ID = None  # se resuelve con `resolve_account_id()`


def resolve_account_id(account_id: int | None = None) -> int | None:
    """El id explícito, o la cuenta viva. ``None`` ⇒ no hay sobre qué correr (T70)."""
    if account_id is not None:
        return int(account_id)
    from paper_trading.account import live_account_id

    return live_account_id()


# Tasa de fallas de UNA fuente, sobre los tickers en que se la consultó, a partir de la
# cual la corrida se loguea como WARNING (tarea 207).
#
# **Calibrado contra la población real, no elegido a ojo.** Contando las líneas de fallo
# de cada collector entre cada *«harvest starting»* y su *«done»* sobre los cinco logs
# (77 corridas con reporte, 2026-07-12 a 2026-09-15):
#
#   * **Normales (n=72, excluyendo el 2026-08-14):** la tasa máxima de **todas** las
#     fuentes es **0,019** — una sola falla de Finnhub en una sola corrida. Las otras
#     tres nunca fallaron: 0 de 72.
#   * **2026-08-14 (el desastre):** las dos corridas largas dan **1,00 / 0,98 / 1,00**
#     — cada fuente falló para prácticamente todos los tickers.
#
# O sea que las dos poblaciones están separadas por ~50×, y cualquier umbral entre 0,02
# y 0,98 las separa. 0,20 está ~10× arriba del peor caso normal y 5× abajo del desastre;
# además es una tasa que ya vale la pena mirar (una fuente cayéndose para un quinto del
# universo). **Verificado en las dos direcciones** —ninguna corrida normal lo cruza, las
# dos catastróficas sí—, que es lo que hace que esto no repita el defecto de sacar la
# referencia de la misma población que se chequea: el día malo se excluyó de la
# calibración *antes* de medir, no después de ver el resultado.
#
# **`cero_resultados` NO es la alarma, y es a propósito.** El dedup hace que la mayoría
# de los tickers devuelva cero filas nuevas en una corrida perfectamente sana (los
# reportes reales dicen `news +1 (dup 33)`), y la tasa normal de eso **no se puede medir
# con los logs de hoy**, que no son por ticker. Se reporta, no se usa de gate.
SOURCE_FAILURE_ALARM_RATE = 0.20


@dataclass
class HarvestReport:
    """Qué hizo la corrida. ``tickers`` es sobre cuántos corrió **de verdad** (T204).

    Antes valía ``len(universe)``, o sea *cuántos se pidieron*: las dos corridas
    catastróficas del 2026-08-14 reportaron ``52 tickers`` igual que una sana. Con el
    presupuesto de wall-clock la distinción deja de ser cosmética — una corrida cortada
    recolecta sobre un prefijo del universo y el resto queda en ``skipped``.

    Y esas dos corridas reportaban además ``failed 0`` (T207): ``failed`` sólo cuenta
    los tickers cuyo **collector** levanta, y ``collect_all`` guarda cada fuente en su
    propio ``try``, así que no levanta nunca. La salud de las fuentes vive ahora en
    ``src_fail``/``src_run``, que se llenan de los ``SourceOutcome``.
    """

    tickers: int = 0  # sobre cuántos se invocó el collector
    requested: int = 0  # cuántos tenía el universo
    news_new: int = 0
    news_dup: int = 0
    est_new: int = 0
    est_dup: int = 0
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # no se llegó: presupuesto agotado
    elapsed_s: float = 0.0
    # Por fuente: en cuántos tickers se la consultó y en cuántos falló (T207).
    src_run: Counter = field(default_factory=Counter)
    src_fail: Counter = field(default_factory=Counter)
    # Por fuente: en cuantos tickers contesto pero con parte de sus sub-fetches caidos
    # (tarea 210). Va SEPARADO de `src_fail` a proposito: `SOURCE_FAILURE_ALARM_RATE` se
    # calibro contra una poblacion donde esto era invisible, asi que no dice nada sobre
    # cuantos `degraded` tiene un dia sano. Contexto, no gate — la misma decision que la
    # 207 tomo con `cero_resultados`, y por la misma razon.
    src_degraded: Counter = field(default_factory=Counter)
    # Tickers que se consultaron y no trajeron NADA (ni news ni estimates). Se reporta
    # como contexto; no dispara la alarma — ver `SOURCE_FAILURE_ALARM_RATE`.
    cero_resultados: list[str] = field(default_factory=list)

    @property
    def stopped_early(self) -> bool:
        return bool(self.skipped)

    def source_failure_rates(self) -> dict[str, float]:
        """Fracción de tickers en que cada fuente falló, sobre los que se la consultó."""
        return {s: self.src_fail.get(s, 0) / n for s, n in self.src_run.items() if n}

    def sources_alarming(self) -> list[str]:
        """Las fuentes cuya tasa de falla cruza el umbral calibrado, peor primero."""
        malas = [(s, r) for s, r in self.source_failure_rates().items() if r >= SOURCE_FAILURE_ALARM_RATE]
        return [s for s, _ in sorted(malas, key=lambda x: -x[1])]

    @property
    def degraded(self) -> bool:
        return bool(self.sources_alarming())

    def summary(self) -> str:
        techo = f" | CORTADO por presupuesto: {len(self.skipped)} sin correr" if self.skipped else ""
        tasas = self.source_failure_rates()
        alarma = (
            " | FUENTES CAIDAS: "
            + ", ".join(f"{s} {self.src_fail[s]}/{self.src_run[s]}" for s in self.sources_alarming())
            if self.degraded
            else ""
        )
        # Sin alarma igual se dice cuántas fuentes tuvieron ALGUNA falla: es la
        # diferencia entre "no falló nada" y "falló poco", que antes no existía.
        #
        # **Y "limpia" incluye no estar degradada (tarea 210).** Con la cuenta vieja una
        # fuente con sub-fetches caidos tenia tasa de falla 0, asi que el resumen decia
        # `fuentes 1/1 limpias | degradadas: yfinance_estimates 1` — las dos cosas a la
        # vez. Quien lee se queda con la primera. El GATE no cambia (sigue mirando solo
        # `source_failure_rates`); lo que cambia es que la etiqueta para humanos no
        # afirme que esta limpio algo que el mismo renglon declara degradado.
        sucias = {s for s, r in tasas.items() if r > 0} | set(self.src_degraded)
        salud = f" | fuentes {len(tasas) - len(sucias)}/{len(tasas)} limpias" if tasas else ""
        # Contexto, no alarma (tarea 210): una fuente que contesto con parte de sus
        # sub-fetches caidos. Sin esta linea, `degraded` seria un estado que el codigo
        # distingue y el reporte no — o sea el defecto de la 207 con otro nombre.
        degradadas = (
            " | degradadas: " + ", ".join(f"{s} {n}" for s, n in sorted(self.src_degraded.items()))
            if self.src_degraded
            else ""
        )
        return (
            f"Harvest: {self.tickers}/{self.requested} tickers en {self.elapsed_s:.0f}s | "
            f"news +{self.news_new} (dup {self.news_dup}) | estimates +{self.est_new} "
            f"(dup {self.est_dup}) | failed {len(self.failed)} | "
            f"sin datos {len(self.cero_resultados)}{salud}{degradadas}{techo}{alarma}"
        )


def _midnight(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


# Tracking query params that don't identify the article — dropped so the same
# story arriving via two sources/feeds with different campaign tags collapses.
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ncid", "cmp", "_ga", "guccounter"}


def canonical_url(url: str | None) -> str | None:
    """
    Normalize a URL into a stable dedup key.

    Forces https, lowercases + de-``www``s the host, strips tracking query
    params, drops the fragment and any trailing slash. Returns None for a falsy
    or scheme-less/host-less string. Best-effort: on any parse error it falls
    back to the lowercased raw string so a weird URL still dedups against itself.
    """
    if not url or not str(url).strip():
        return None
    raw = str(url).strip()
    try:
        s = urlsplit(raw)
        if not s.netloc:
            return None
        host = s.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        q = [
            (k, v)
            for k, v in parse_qsl(s.query, keep_blank_values=False)
            if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_KEYS
        ]
        q.sort()
        path = s.path.rstrip("/")
        return urlunsplit(("https", host, path, urlencode(q), ""))
    except Exception:
        return raw.lower()


def resolve_universe(account_id: int | None = None) -> list[str]:
    """Watchlist ∪ open positions for the account (mirrors engine.py).

    ``account_id=None`` ⇒ la **cuenta viva** (T70), no la 1 hardcodeada.
    """
    from paper_trading.models import PaperPosition, PaperWatchlistItem

    account_id = resolve_account_id(account_id)
    if account_id is None:
        return []

    with session_scope() as s:
        watch: set[str] = {
            w.ticker
            for w in s.query(PaperWatchlistItem).filter(PaperWatchlistItem.account_id == account_id).all()
        }
        pos: set[str] = {
            p.ticker
            for p in s.query(PaperPosition)
            .filter(PaperPosition.account_id == account_id)
            .filter(PaperPosition.shares > 0)
            .all()
        }
    return sorted(watch | pos)


def ordenar_por_rezago(universe: list[str], ultimos: dict[str, object]) -> list[str]:
    """El universo ordenado **por quién hace más que no se recolecta** (tarea 208).

    Puro y separado del query a propósito: el criterio es lo que hay que poder
    interrogar en un test, y mezclarlo con la lectura de la DB obligaría a montar filas
    para probar una comparación.

    **El defecto que arregla.** ``resolve_universe()`` devuelve ``sorted(...)`` y
    ``_collect_fase1`` recorre esa lista en orden, así que el corte por presupuesto
    (tarea 204) se lleva siempre el **sufijo**: los mismos tickers del final del
    alfabeto, en cada corrida degradada. No es aleatorio, es sistemático — y el snapshot
    de consenso **no tiene catch-up posible** (la 196 lo midió: las noticias se
    auto-recuperan hasta 7 días, el consenso no), así que la pérdida se concentra
    siempre en los mismos nombres y es para siempre.

    **Por qué este criterio y no rotar el arranque.** Rotar pide recordar por dónde se
    quedó la corrida anterior, o sea **estado nuevo que hay que persistir**. El rezago
    sale de ``analyst_estimate_snapshots``, que ya existe, y además es
    **auto-corrector**: un ticker que se saltó ayer tiene la fecha más vieja hoy y pasa
    al frente solo. No hace falta que nadie lleve la cuenta.

    Quien **nunca** se recolectó va primero (``None`` ordena antes que cualquier fecha):
    es el caso de un ticker recién agregado a la watchlist, que es justo el que más
    urge. Los empates se rompen **alfabéticamente**, así que el orden sigue siendo
    determinístico — importa, porque en una corrida sana todos comparten la fecha de hoy
    y sin el desempate el orden sería arbitrario entre corridas.
    """
    return sorted(universe, key=lambda t: (ultimos.get(t) is not None, ultimos.get(t), t))


def _ultimo_consenso_por_ticker() -> dict[str, object]:
    """``{ticker: fecha del último snapshot de consenso}``, para ``ordenar_por_rezago``.

    Un solo agregado sobre la tabla (47.890 filas / 131 tickers al 2026-09-21), indexado
    por ``ix_est_ticker_metric_date``. Fail-open: si el query falla se devuelve ``{}`` y
    el orden cae al alfabético de siempre — ordenar mejor es una optimización de reparto,
    no algo por lo que valga la pena no recolectar.
    """
    from sqlalchemy import func

    from database.models import AnalystEstimateSnapshot

    try:
        with session_scope() as s:
            filas = (
                s.query(
                    AnalystEstimateSnapshot.ticker,
                    func.max(AnalystEstimateSnapshot.snapshot_date),
                )
                .group_by(AnalystEstimateSnapshot.ticker)
                .all()
            )
        return {t: d for t, d in filas}
    except Exception:
        log.exception("no se pudo leer el rezago de consenso — se recorre alfabético")
        return {}


def _insert_news_if_new(session, item, seen: set[str], seen_urls: set[str]) -> bool:
    """
    Insert a NewsItem unless it's a duplicate. Returns True if new.

    Two dedup layers:
      1. URL: the same article URL (canonicalized) from any source collapses —
         catches a story carried by both Finnhub and Yahoo/RSS in the same run,
         where the titles differ so ``content_hash`` would not catch it.
      2. content_hash: (ticker, normalized title, hour) — the original guard for
         items without a URL or with differing URLs but the same headline.
    Both are checked in-run (the sets) and against already-stored rows.
    """
    cu = canonical_url(item.url)
    if cu is not None and cu in seen_urls:
        return False
    h = item.content_hash()
    if h in seen:
        return False
    seen.add(h)
    if cu is not None:
        seen_urls.add(cu)
    exists = session.query(NewsEvent.id).filter(NewsEvent.content_hash == h).first()
    if exists is not None:
        return False
    if item.url is not None:
        url_dup = session.query(NewsEvent.id).filter(NewsEvent.url == item.url).first()
        if url_dup is not None:
            return False
    session.add(
        NewsEvent(
            ticker=item.ticker,
            title=item.title,
            content=item.content,
            source=item.source,
            url=item.url,
            published_at=item.published_at,
            content_hash=h,
        )
    )
    session.flush()  # surface IntegrityError early; keeps the dedup honest
    return True


def _insert_estimate_if_new_today(session, snap, today: datetime) -> bool:
    """Insert one EstimateSnapshot per (ticker, metric, period_label, day). Returns True if new.

    **Dos capas, y la de abajo es la que manda (tarea 203).** La consulta previa es
    el camino rápido: evita el INSERT cuando la fila del día ya está, que es el caso
    normal de re-correr el harvest. Pero compara el datetime **exacto**, así que por
    sí sola no ve una fila del mismo día estampada con otra hora — y no es atómica.
    Lo que garantiza el invariante es el índice único por expresión
    ``ux_est_ticker_metric_period_dia``, sobre ``date(snapshot_date)``.

    Por eso el INSERT va en un **savepoint**: si otro escritor metió la fila en el
    medio, la colisión revierte sólo esta fila y se cuenta como duplicado, en vez de
    abortar la transacción del ticker y llevarse puestas también sus noticias (la
    fase 2 persiste news + estimates del mismo ticker en una sola sesión).
    """
    exists = (
        session.query(AnalystEstimateSnapshot.id)
        .filter(AnalystEstimateSnapshot.ticker == snap.ticker)
        .filter(AnalystEstimateSnapshot.metric == snap.metric)
        .filter(AnalystEstimateSnapshot.period_label == snap.period_label)
        .filter(AnalystEstimateSnapshot.snapshot_date == today)
        .first()
    )
    if exists is not None:
        return False
    try:
        with session.begin_nested():
            session.add(
                AnalystEstimateSnapshot(
                    ticker=snap.ticker,
                    metric=snap.metric,
                    period_label=snap.period_label,
                    consensus_value=snap.consensus_value,
                    num_analysts=snap.num_analysts,
                    snapshot_date=today,
                    fetched_at=utcnow_naive(),
                )
            )
            session.flush()
    except IntegrityError:
        # El índice la frenó: la fila del día ya existe con otro sello de hora.
        # Es exactamente el caso que el chequeo de arriba no puede ver.
        log.debug(
            "snapshot duplicado frenado por el indice: %s/%s/%s @ %s",
            snap.ticker,
            snap.metric,
            snap.period_label,
            today.date(),
        )
        return False
    return True


def resolve_budget_seconds(budget_seconds: float | None = None) -> float | None:
    """El presupuesto de wall-clock explícito, o el de settings. ``None`` ⇒ sin techo.

    ``0`` (y cualquier valor ≤ 0) significa **sin techo**, no «cortar ya»: es la única
    forma de apagar el mecanismo sin un segundo flag, y la semántica queda fijada por un
    test — no sólo por esta línea.
    """
    if budget_seconds is None:
        from config.settings_manager import settings

        budget_seconds = settings.get("catalyst_harvest_budget_seconds", 1200)
    try:
        b = float(budget_seconds)
    except (TypeError, ValueError):
        return None
    return b if b > 0 else None


def _loguear(report: HarvestReport, prefijo: str = "") -> None:
    """El resumen, a ``WARNING`` cuando alguna fuente cruzó el umbral (T207).

    El nivel es la mitad que importa: el 2026-08-14 el resumen salió a ``INFO`` como
    cualquier otro día, así que el desastre quedó indistinguible del ruido normal para
    cualquiera que filtre por nivel — que es cómo se lee un log de tres meses.
    """
    (log.warning if report.degraded else log.info)("%s%s", prefijo, report.summary())


def _anotar_salud(report: HarvestReport, ticker: str, res) -> None:
    """Vuelca los ``SourceOutcome`` del ticker a los contadores del reporte (T207).

    ``skipped`` **no** cuenta como consultada: una fuente sin key (Finnhub) o sin CIK
    (un ADR en EDGAR) no dice nada sobre su salud, y meterla en el denominador diluiría
    la tasa justo cuando hay que verla. Tolera un ``_CollectResult`` sin ``outcomes``
    —un collector inyectado por un test viejo— sin inventar nada.
    """
    for o in getattr(res, "outcomes", None) or []:
        if o.status == "skipped":
            continue
        report.src_run[o.source] += 1
        if o.status == "failed":
            report.src_fail[o.source] += 1
        elif o.status == "degraded":
            # Cuenta en `src_run` (la fuente SI corrio) y NO en `src_fail` (no esta
            # caida). Ver el comentario del campo: meterlo al gate seria inventar un
            # umbral en vez de calibrarlo.
            report.src_degraded[o.source] += 1
    if not (getattr(res, "news", None) or getattr(res, "estimates", None)):
        report.cero_resultados.append(ticker)


def _collect_fase1(
    universe: list[str],
    sources: set[str] | None,
    collector,
    report: HarvestReport,
    deadline: float | None,
) -> list[tuple[str, _CollectResult]]:
    """Fase 1 — recolectar (RED) FUERA de toda sesión, con techo de wall-clock (T204).

    Tener la conexión tomada durante los fetch de red (yfinance/SEC/RSS, ~90s para 52
    tickers) era un lock-holder enorme que chocaba con el scan/bulk-fetch paralelo →
    "database is locked" + agotamiento del QueuePool. Mismo patrón que classify_events.

    **El corte va por TICKER, no por lote.** Un chequeo de reloj por ticker cuesta
    nanosegundos contra un fetch de ~2,7 s, así que agrupar sólo empeoraría la
    granularidad sin ahorrar nada. Se chequea **antes** de arrancar cada ticker: cortar
    adentro de uno pediría meter el deadline en ``collect_all``, que es el contrato de
    otro módulo y del ``collector`` inyectable. El precio de esa decisión es que el
    sobrepaso es **lo que tarde el último ticker** — ~110 s en el peor caso medido
    (95 min / 52 tickers el 2026-08-14, con las tres fuentes timeouteando).

    `_CollectResult` y no `object`: es lo que devuelve `collect_all`, y con `object` los
    accesos a `.news` y `.estimates` de más abajo quedaban sin tipo.
    """
    collected: list[tuple[str, _CollectResult]] = []
    for i, t in enumerate(universe):
        if deadline is not None and time.monotonic() >= deadline:
            report.skipped = list(universe[i:])
            log.warning(
                "harvest CORTADO por presupuesto de wall-clock: %d de %d tickers "
                "recolectados, %d sin correr (el primero sin correr es %s)",
                i,
                len(universe),
                len(report.skipped),
                t,
            )
            break
        try:
            res = collector(t, sources)
        except Exception:
            log.exception("collect failed for %s", t)
            report.failed.append(t)
            continue
        _anotar_salud(report, t, res)
        collected.append((t, res))
    report.tickers = len(universe) - len(report.skipped)
    return collected


def harvest(
    tickers: list[str] | None = None,
    *,
    account_id: int | None = None,
    sources: set[str] | None = None,
    collector=collect_all,
    now: datetime | None = None,
    dry_run: bool = False,
    budget_seconds: float | None = None,
) -> HarvestReport:
    """
    Collect news + estimate snapshots for ``tickers`` (default = the account's
    watchlist ∪ positions) and persist new rows idempotently.

    ``collector(ticker, sources)`` is injectable so tests can run fully offline.

    ``budget_seconds`` es el techo de wall-clock de la **recolección** (tarea 204);
    ``None`` lo resuelve contra ``catalyst_harvest_budget_seconds``. Lo que ya se
    recolectó **siempre se persiste**: el modo de falla que esto evita es justamente el
    de morir después de haber hecho trabajo parcial. O sea que el total es
    ``presupuesto + último ticker + persistir lo recolectado``; la fase 2 es local y
    corta (transacciones por ticker sobre SQLite), pero **no** está acotada por este
    presupuesto y va dicho.
    """
    t0 = time.monotonic()
    universe = tickers if tickers is not None else resolve_universe(account_id)
    # Tarea 208 — el orden decide QUIÉN se pierde cuando el presupuesto corta, así que
    # va acá y no adentro de `resolve_universe`: esa función la usan también
    # `build_surprise_profiles` y `news_feed`, que no tienen techo y a los que cambiarles
    # el orden no aporta nada. El reparto es un problema del harvest, y se arregla donde
    # está el corte.
    universe = ordenar_por_rezago(universe, _ultimo_consenso_por_ticker())
    now = now or utcnow_naive()
    today = _midnight(now)
    report = HarvestReport(tickers=len(universe), requested=len(universe))
    seen_hashes: set[str] = set()
    seen_urls: set[str] = set()

    budget = resolve_budget_seconds(budget_seconds)
    deadline = None if budget is None else t0 + budget

    if dry_run:
        for _t, res in _collect_fase1(universe, sources, collector, report, deadline):
            report.news_new += len(res.news)
            report.est_new += len(res.estimates)
        report.elapsed_s = time.monotonic() - t0
        _loguear(report, prefijo="[dry-run] ")
        return report

    collected = _collect_fase1(universe, sources, collector, report, deadline)

    # Fase 2 — persistir en transacciones CORTAS, una por ticker. Los contadores
    # se vuelcan al report SOLO tras commit exitoso (antes un rollback por un
    # item fallido descartaba en silencio todo lo pendiente del run pero dejaba
    # los contadores inflados). El dedup in-run (seen_hashes) se mantiene global.
    for t, res in collected:
        n_new = n_dup = e_new = e_dup = 0
        try:
            with session_scope() as session:
                for item in res.news:
                    if _insert_news_if_new(session, item, seen_hashes, seen_urls):
                        n_new += 1
                    else:
                        n_dup += 1
                for snap in res.estimates:
                    if _insert_estimate_if_new_today(session, snap, today):
                        e_new += 1
                    else:
                        e_dup += 1
        except Exception:
            log.exception("persist failed for %s", t)
            report.failed.append(t)
            continue
        report.news_new += n_new
        report.news_dup += n_dup
        report.est_new += e_new
        report.est_dup += e_dup

    report.elapsed_s = time.monotonic() - t0
    _loguear(report)
    return report


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="T-CAT-0 catalyst harvester (point-in-time ingest).")
    p.add_argument("--account-id", type=int, default=None, help="Paper account whose watchlist to harvest.")
    p.add_argument(
        "--universe",
        choices=["sim", "sp500"],
        default="sim",
        help="sim = account watchlist; sp500 = full index.",
    )
    p.add_argument("--tickers", type=str, default=None, help="Comma-separated override, e.g. NVDA,PLTR,RKLB.")
    p.add_argument(
        "--sources",
        type=str,
        default="yfinance",
        help="Comma-separated: yfinance,sec,finnhub (finnhub needs FINNHUB_API_KEY).",
    )
    p.add_argument("--dry-run", action="store_true", help="Collect and report without writing to the DB.")
    p.add_argument(
        "--budget-seconds",
        type=float,
        default=None,
        help=(
            "Techo de wall-clock de la recolección (tarea 204). 0 = sin techo. "
            "Sin el flag sale de `catalyst_harvest_budget_seconds` (default 1200)."
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    sources = {s.strip() for s in args.sources.split(",") if s.strip()}

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    elif args.universe == "sp500":
        from data.ticker_universe import get_sp500_tickers

        tickers = get_sp500_tickers()
    else:
        tickers = None  # resolve from account watchlist

    report = harvest(
        tickers,
        account_id=args.account_id,
        sources=sources,
        dry_run=args.dry_run,
        budget_seconds=args.budget_seconds,
    )
    print(report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
