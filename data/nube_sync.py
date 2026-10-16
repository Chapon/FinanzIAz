"""La app baja lo que juntó la nube (tarea 356): DynamoDB → ``finanzias.db``.

La Lambda de la 355 (``scripts/recolector_nube.py``) escribe el consenso y las noticias
en la tabla ``finanzias_harvest``, particionados por **día de captura UTC**
(``pk = consenso#2026-10-16``, ``noticia#2026-10-16``). Esto los baja y los inserta. El
diseño es el §11 de ``docs/harvest_nube_t196_2026-09-14.md``; lo que importa:

* **La nube nunca escribe ``finanzias.db``** (regla 5): escribe la app, en Windows.
* **Se respeta la marca de la nube** (§6.1): ``snapshot_date`` es la medianoche del día
  de captura y ``fetched_at`` es ``capturado_at``. Si se estampara la fecha de la
  importación, dos semanas de consenso entrarían todas con el día en que se abrió la app,
  y el dato no serviría para T-CAT-5b.
* **Las mismas reglas que el harvest:** se inserta con ``_insert_estimate_if_new_today`` y
  ``_insert_news_if_new`` de ``scripts/harvest_catalysts.py``, así que el dedup (UNIQUE
  del consenso por día, ``content_hash``, URL y la nota repetida a < 24 h) es el mismo, y
  lo que ya trajo el harvest in-app no se duplica. **El primero del día gana.**
* **Primero baja, después escribe** (§11.6, la lección de la 237): el ``Query`` de un día
  se hace sin ninguna transacción abierta, y la escritura va en una transacción corta
  **por día**.
* **El cursor** (``cloud_import_cursor``, §11.5) avanza en **la misma transacción** que las
  filas de su día —y se escribe primero: ver ``sincronizar``—: un corte a
  mitad de un día no lo mueve y no deja ese día a medias. La
  sincronización siguiente **re-lee el último día importado**, porque la Lambda puede
  seguir escribiéndolo; re-leer es seguro porque escribir es idempotente.
* **Sin credenciales no corre y lo dice una vez** (§11.1): el perfil ``[finanzias-lector]``
  de ``~/.aws/credentials``, nunca en el repo (que es público).

Lo que **no** se importa: ``corrida#{día}`` (el registro de cada lote de la Lambda, que
mira la 245) y ``universo`` (lo que la Lambda lee).
"""

from __future__ import annotations

import configparser
import importlib.util
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from config.logging_config import get_logger

log = get_logger(__name__)

PERFIL = "finanzias-lector"
REGION = "us-east-1"
TABLA = "finanzias_harvest"
#: Lo que se baja, en este orden. El consenso primero: es lo que lee el scan.
TIPOS = ("consenso", "noticia")
#: El TTL de la tabla (``RETENCION_DIAS`` de la Lambda): más atrás no hay nada que bajar.
RETENCION_DIAS = 90

_avisado = False


# ── ¿Se puede? ───────────────────────────────────────────────────────────────


def ruta_credenciales() -> Path:
    """La de ``boto3``: ``AWS_SHARED_CREDENTIALS_FILE`` si está, si no ``~/.aws/credentials``."""
    env = os.environ.get("AWS_SHARED_CREDENTIALS_FILE")
    return Path(env).expanduser() if env else Path.home() / ".aws" / "credentials"


def perfil_disponible(ruta: Path | None = None) -> bool:
    """¿Está el perfil con una key? Lee el archivo sin ``boto3``, así que es barato."""
    ruta = ruta or ruta_credenciales()
    cp = configparser.ConfigParser()
    try:
        if not cp.read(ruta, encoding="utf-8"):
            return False
    except (configparser.Error, OSError, UnicodeDecodeError):
        return False
    return cp.has_option(PERFIL, "aws_access_key_id") and cp.has_option(PERFIL, "aws_secret_access_key")


def boto3_instalado() -> bool:
    return importlib.util.find_spec("boto3") is not None


def motivo_no_disponible() -> str | None:
    """Por qué no se puede sincronizar, o ``None`` si se puede."""
    if not boto3_instalado():
        return "falta boto3 (pip install -r requirements.txt)"
    if not perfil_disponible():
        return f"sin el perfil [{PERFIL}] en {ruta_credenciales()} (ver Acciones manuales, tarea 356)"
    return None


def habilitada() -> bool:
    from config.settings_manager import settings

    return bool(settings.get("nube_sync_enabled", True))


def consenso_desde_nube() -> bool:
    """¿El consenso lo trae la nube? Entonces el harvest in-app no lo pide (§7.6).

    Hace falta que la sincronización esté prendida **y** que pueda correr: sin el perfil
    nadie bajaría el consenso de la nube, y dejar de pedirlo perdería el día.
    """
    return habilitada() and motivo_no_disponible() is None


def avisar_no_disponible(motivo: str) -> bool:
    """El aviso, **una vez por proceso**. ``True`` si lo dio ahora (para la pantalla)."""
    global _avisado
    if _avisado:
        return False
    _avisado = True
    log.warning(
        "Nube — FUENTE NO DISPONIBLE: %s. La app no baja lo que juntó la Lambda, y el harvest "
        "in-app sigue pidiendo el consenso (tarea 356).",
        motivo,
    )
    return True


# ── Bajar ────────────────────────────────────────────────────────────────────


def abrir_tabla():  # pragma: no cover — pega a AWS
    import boto3
    from botocore.config import Config

    # Las 10 RCU de la tabla se agotan bajando un día de noticias (~2,8 MB): los reintentos
    # adaptativos esperan en vez de fallar con ProvisionedThroughputExceeded.
    cfg = Config(retries={"mode": "adaptive", "max_attempts": 10}, connect_timeout=10, read_timeout=30)
    return (
        boto3.Session(profile_name=PERFIL, region_name=REGION).resource("dynamodb", config=cfg).Table(TABLA)
    )


def bajar_dia(tabla, tipo: str, dia: date) -> list[dict]:
    """Todos los ítems de ``{tipo}#{día}``, paginando. Sin ninguna transacción abierta."""
    kw = {
        "KeyConditionExpression": "pk = :pk",
        "ExpressionAttributeValues": {":pk": f"{tipo}#{dia.isoformat()}"},
    }
    items: list[dict] = []
    while True:
        r = tabla.query(**kw)
        items.extend(r.get("Items", []))
        siguiente = r.get("LastEvaluatedKey")
        if not siguiente:
            return items
        kw["ExclusiveStartKey"] = siguiente


def dias_a_bajar(cursor: date | None, hoy: date) -> list[date]:
    """Del último día importado (que se re-lee) a hoy. Sin cursor, lo que el TTL conserva."""
    piso = hoy - timedelta(days=RETENCION_DIAS)
    desde = piso if cursor is None else max(cursor, piso)
    return [desde + timedelta(days=i) for i in range((hoy - desde).days + 1)]


# ── Escribir ─────────────────────────────────────────────────────────────────


def _fecha(s) -> datetime | None:
    """Los timestamps de la Lambda: ISO, naive y en UTC (``recolector_nube._iso``)."""
    if not s:
        return None
    dt = datetime.fromisoformat(str(s))
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _num(v) -> float | None:
    """``boto3`` devuelve los números como ``Decimal``."""
    return None if v is None else float(v)


def escribir_dia(session, tipo: str, items: list[dict]) -> tuple[int, int]:
    """Inserta los ítems de un día con las reglas del harvest. ``(nuevas, repetidas)``."""
    from data.news_sources import EstimateSnapshot, NewsItem
    from scripts.harvest_catalysts import _insert_estimate_if_new_today, _insert_news_if_new

    nuevas = dup = 0
    if tipo == "consenso":
        for it in items:
            capturado = _fecha(it["capturado_at"])
            dia = capturado.replace(hour=0, minute=0, second=0, microsecond=0)
            for f in it.get("filas") or []:
                snap = EstimateSnapshot(
                    ticker=str(it["sk"]).upper(),
                    metric=f["metric"],
                    period_label=f.get("period_label"),
                    consensus_value=_num(f.get("consensus_value")),
                    num_analysts=None if f.get("num_analysts") is None else int(f["num_analysts"]),
                )
                if _insert_estimate_if_new_today(session, snap, dia, fetched_at=capturado):
                    nuevas += 1
                else:
                    dup += 1
    elif tipo == "noticia":
        vistos: set[str] = set()
        urls: set[str] = set()
        for it in items:
            item = NewsItem(
                ticker=str(it["ticker"]).upper(),
                title=it["title"],
                source=it["source"],
                content=it.get("content"),
                url=it.get("url"),
                published_at=_fecha(it.get("published_at")),
            )
            ok = _insert_news_if_new(
                session, item, vistos, urls, h=it["sk"], fetched_at=_fecha(it["capturado_at"])
            )
            if ok:
                nuevas += 1
            else:
                dup += 1
    else:
        raise ValueError(f"tipo desconocido: {tipo}")
    return nuevas, dup


def leer_cursor(tipo: str) -> date | None:
    from database.models import CloudImportCursor, session_scope

    with session_scope() as s:
        fila = s.get(CloudImportCursor, tipo)
        return None if fila is None else date.fromisoformat(fila.ultimo_dia_importado)


def _mover_cursor(session, tipo: str, dia: date) -> None:
    from database.models import CloudImportCursor, utcnow_naive

    fila = session.get(CloudImportCursor, tipo)
    if fila is None:
        session.add(
            CloudImportCursor(tipo=tipo, ultimo_dia_importado=dia.isoformat(), importado_at=utcnow_naive())
        )
    else:
        fila.ultimo_dia_importado = dia.isoformat()
        fila.importado_at = utcnow_naive()


# ── La sincronización ────────────────────────────────────────────────────────


@dataclass
class ResumenTipo:
    tipo: str
    dias: list[date] = field(default_factory=list)  # los importados enteros
    nuevas: int = 0
    dup: int = 0
    error: str | None = None


@dataclass
class ResumenSync:
    corrio: bool
    motivo: str | None = None  # por qué no corrió
    aviso_nuevo: bool = False  # el «no disponible» se dio en esta llamada
    tipos: list[ResumenTipo] = field(default_factory=list)

    @property
    def nuevas(self) -> int:
        return sum(t.nuevas for t in self.tipos)

    @property
    def errores(self) -> list[str]:
        return [f"{t.tipo}: {t.error}" for t in self.tipos if t.error]

    def texto(self) -> str:
        if not self.corrio:
            return f"Nube: no sincroniza — {self.motivo}"
        partes = [f"{t.tipo} +{t.nuevas}" for t in self.tipos]
        err = f" | ERROR {'; '.join(self.errores)}" if self.errores else ""
        return "Nube: " + ", ".join(partes) + err


def sincronizar(*, tabla=None, hoy: date | None = None) -> ResumenSync:
    """Baja lo pendiente de cada tipo y lo inserta. Nunca lanza.

    ``tabla`` se inyecta en los tests (una tabla simulada); sin ella se abre la de AWS con
    el perfil, y si no se puede, no corre y lo avisa una vez.
    """
    if not habilitada():
        return ResumenSync(corrio=False, motivo="apagada (nube_sync_enabled)")
    if tabla is None:
        motivo = motivo_no_disponible()
        if motivo is not None:
            return ResumenSync(corrio=False, motivo=motivo, aviso_nuevo=avisar_no_disponible(motivo))
        try:
            tabla = abrir_tabla()
        except Exception as e:  # pragma: no cover — depende de AWS
            log.exception("Nube: no se pudo abrir la tabla")
            return ResumenSync(corrio=False, motivo=f"{type(e).__name__}: {e}")

    from database.models import session_scope, utcnow_naive

    hoy = hoy or utcnow_naive().date()
    resumen = ResumenSync(corrio=True)
    for tipo in TIPOS:
        rt = ResumenTipo(tipo)
        resumen.tipos.append(rt)
        try:
            for dia in dias_a_bajar(leer_cursor(tipo), hoy):
                items = bajar_dia(tabla, tipo, dia)  # sin transacción abierta (§11.6)
                with session_scope() as s:
                    # El cursor va PRIMERO y con flush, en la misma transacción que sus
                    # filas. Lo pidió un defecto que ya no está: el `begin_nested()` de
                    # `_insert_estimate_if_new_today` commiteaba fila por fila cuando era
                    # el primer write (pysqlite no emite BEGIN antes de un SAVEPOINT), y un
                    # corte dejaba el día a medias. La 363 lo cambió por ON CONFLICT DO
                    # NOTHING; el orden queda porque no cuesta nada y no depende de eso.
                    _mover_cursor(s, tipo, dia)
                    s.flush()
                    n, d = escribir_dia(s, tipo, items)
                rt.dias.append(dia)
                rt.nuevas += n
                rt.dup += d
        except Exception as e:
            log.exception(
                "Nube: la sincronización de %s se cortó; el cursor quedó en el último día completo", tipo
            )
            rt.error = f"{type(e).__name__}: {str(e)[:120]}"
        if rt.dias:
            log.info(
                "Nube: %s %s..%s (%d días) +%d nuevas (dup %d)%s",
                tipo,
                rt.dias[0],
                rt.dias[-1],
                len(rt.dias),
                rt.nuevas,
                rt.dup,
                f" | CORTADA: {rt.error}" if rt.error else "",
            )
    return resumen
