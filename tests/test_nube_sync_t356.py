"""Tarea 356 (NUBE-SYNC-EN-LA-APP) — la app baja lo que juntó la Lambda, sin AWS y sin red.

La tabla simulada se llena con ``item_consenso`` e ``item_noticia`` **de la Lambda**
(``scripts/recolector_nube.py``): si el formato de lo que escribe la nube cambia, estos
tests lo ven, en vez de probar el importador contra un formato inventado acá.

El kill-criteria, uno por test: (a) dos días que la DB no tiene entran con el
``snapshot_date`` de la nube y no con el de hoy; (b) re-sincronizar no agrega filas;
(c) un corte a mitad del segundo día deja el cursor en el primero y la siguiente completa
sin duplicar; (d) sin perfil no hay excepción y hay **un** aviso; (e) con la
sincronización prendida el harvest in-app no pide el consenso.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import pytest

from data import news_sources as ns
from data import nube_sync
from data.news_sources import EstimateSnapshot, NewsItem, SourceOutcome
from scripts import recolector_nube as rn

D1 = datetime(2026, 10, 14, 21, 30, 5, tzinfo=timezone.utc)
D2 = datetime(2026, 10, 15, 21, 34, 7, tzinfo=timezone.utc)
HOY = date(2026, 10, 16)


class TablaNube:
    """Lo que la app usa de la tabla de ``boto3``: ``query`` por ``pk``, paginado.

    Pagina de a ``pagina`` ítems para que el camino de ``LastEvaluatedKey`` corra siempre.
    """

    def __init__(self, pagina: int = 2):
        self.items: dict[tuple[str, str], dict] = {}
        self.pagina = pagina
        self.consultas: list[str] = []

    def poner(self, item: dict) -> None:
        self.items[(item["pk"], item["sk"])] = item

    def query(self, KeyConditionExpression, ExpressionAttributeValues, ExclusiveStartKey=None):
        assert KeyConditionExpression == "pk = :pk"
        pk = ExpressionAttributeValues[":pk"]
        self.consultas.append(pk)
        todos = sorted((v for (p, _), v in self.items.items() if p == pk), key=lambda v: v["sk"])
        desde = 0
        if ExclusiveStartKey is not None:
            desde = next(i for i, v in enumerate(todos) if v["sk"] == ExclusiveStartKey["sk"]) + 1
        pag = todos[desde : desde + self.pagina]
        r = {"Items": pag}
        if desde + self.pagina < len(todos):
            r["LastEvaluatedKey"] = {"pk": pk, "sk": pag[-1]["sk"]}
        return r


def _snaps(ticker: str, eps: float):
    return [
        EstimateSnapshot(ticker, "eps", "0q", eps, 20),
        EstimateSnapshot(ticker, "price_target", None, eps * 100, 30),
    ]


def _nota(ticker: str, titulo: str, publicada: datetime | None, url: str | None = None) -> NewsItem:
    return NewsItem(ticker, titulo, "finnhub:Reuters", f"cuerpo {titulo}", url, publicada)


def _tabla_de_dos_dias() -> TablaNube:
    t = TablaNube()
    for tk, eps in (("AAPL", 1.5), ("MSFT", 3.25), ("NVDA", 0.75)):
        t.poner(rn.item_consenso(tk, _snaps(tk, eps), D1))
        t.poner(rn.item_consenso(tk, _snaps(tk, eps + 0.01), D2))
    for i in range(3):
        t.poner(rn.item_noticia(_nota("AAPL", f"nota uno {i}", datetime(2026, 10, 14, 15, i)), D1))
        t.poner(rn.item_noticia(_nota("MSFT", f"nota dos {i}", datetime(2026, 10, 15, 16, i)), D2))
    return t


def _consenso():
    from database.models import AnalystEstimateSnapshot, session_scope

    with session_scope() as s:
        return [
            (r.ticker, r.metric, r.period_label, r.consensus_value, r.snapshot_date, r.fetched_at)
            for r in s.query(AnalystEstimateSnapshot).order_by(AnalystEstimateSnapshot.id)
        ]


def _noticias():
    from database.models import NewsEvent, session_scope

    with session_scope() as s:
        return [
            (r.ticker, r.title, r.content_hash, r.fetched_at)
            for r in s.query(NewsEvent).order_by(NewsEvent.id)
        ]


# ── (a) la marca de la nube, no la de hoy ────────────────────────────────────


def test_a_dos_dias_entran_con_el_snapshot_date_de_la_NUBE(test_db):
    res = nube_sync.sincronizar(tabla=_tabla_de_dos_dias(), hoy=HOY)

    assert res.corrio and not res.errores
    filas = _consenso()
    assert len(filas) == 12  # 3 tickers × 2 métricas × 2 días
    dias = sorted({f[4] for f in filas})
    assert dias == [datetime(2026, 10, 14), datetime(2026, 10, 15)]  # no 2026-10-16
    # fetched_at es el capturado_at de la Lambda, no la hora de importar
    assert {f[5] for f in filas} == {datetime(2026, 10, 14, 21, 30, 5), datetime(2026, 10, 15, 21, 34, 7)}
    aapl_d2 = [f for f in filas if f[0] == "AAPL" and f[1] == "eps" and f[4].day == 15]
    assert aapl_d2[0][3] == pytest.approx(1.51)

    notas = _noticias()
    assert len(notas) == 6
    assert {n[3] for n in notas} == {datetime(2026, 10, 14, 21, 30, 5), datetime(2026, 10, 15, 21, 34, 7)}


def test_a_el_cursor_queda_en_hoy_y_lo_que_se_consulto_es_por_dia(test_db):
    tabla = _tabla_de_dos_dias()
    nube_sync.sincronizar(tabla=tabla, hoy=HOY)

    assert nube_sync.leer_cursor("consenso") == HOY
    assert nube_sync.leer_cursor("noticia") == HOY
    # Sin cursor baja lo que el TTL conserva: 90 días atrás hasta hoy, un Query por día y tipo
    # (con las páginas de a dos, los días con datos se consultan más de una vez).
    assert {c for c in tabla.consultas if c.startswith("consenso#")} == {
        f"consenso#{d.isoformat()}" for d in nube_sync.dias_a_bajar(None, HOY)
    }
    assert len(nube_sync.dias_a_bajar(None, HOY)) == nube_sync.RETENCION_DIAS + 1


# ── (b) idempotente ──────────────────────────────────────────────────────────


def test_b_re_sincronizar_no_agrega_filas(test_db):
    tabla = _tabla_de_dos_dias()
    nube_sync.sincronizar(tabla=tabla, hoy=HOY)
    antes = (_consenso(), _noticias())

    res = nube_sync.sincronizar(tabla=tabla, hoy=HOY)

    assert res.nuevas == 0
    assert (_consenso(), _noticias()) == antes


def test_b_lo_que_ya_trajo_el_harvest_in_app_GANA_y_no_se_duplica(test_db):
    """El primero del día gana, como en la Lambda y en el harvest."""
    from database.models import AnalystEstimateSnapshot, NewsEvent, session_scope

    nota = _nota("AAPL", "nota uno 0", datetime(2026, 10, 14, 15, 0))
    with session_scope() as s:
        s.add(
            AnalystEstimateSnapshot(
                ticker="AAPL",
                metric="eps",
                period_label="0q",
                consensus_value=9.99,
                snapshot_date=datetime(2026, 10, 14),
                fetched_at=datetime(2026, 10, 14, 13, 0),
            )
        )
        s.add(NewsEvent(ticker="AAPL", title=nota.title, source="yfinance", content_hash=nota.content_hash()))

    nube_sync.sincronizar(tabla=_tabla_de_dos_dias(), hoy=HOY)

    aapl = [f for f in _consenso() if f[0] == "AAPL" and f[1] == "eps" and f[4].day == 14]
    assert [f[3] for f in aapl] == [9.99]
    assert len([n for n in _noticias() if n[1] == "nota uno 0"]) == 1


def test_b_una_nota_SIN_FECHA_conserva_el_hash_de_la_nube(test_db):
    """``content_hash`` de una nota sin fecha usa el día en que se lo llama: re-calcularlo
    al importar daría otro hash, y la nota se duplicaría al re-importarla otro día."""
    tabla = TablaNube()
    item = rn.item_noticia(_nota("AAPL", "sin fecha", None), D1)
    tabla.poner(item)

    nube_sync.sincronizar(tabla=tabla, hoy=HOY)

    assert [n[2] for n in _noticias()] == [item["sk"]]


# ── (c) el corte a mitad de un día ──────────────────────────────────────────


def test_c_un_corte_a_mitad_del_SEGUNDO_dia_deja_el_cursor_en_el_primero(test_db, monkeypatch):
    from scripts import harvest_catalysts as hc

    original = hc._insert_estimate_if_new_today
    vistos: list[datetime] = []

    def _se_corta(session, snap, today, **kw):
        vistos.append(today)
        if today == datetime(2026, 10, 15) and vistos.count(today) == 3:
            raise OSError("se cortó")
        return original(session, snap, today, **kw)

    monkeypatch.setattr(hc, "_insert_estimate_if_new_today", _se_corta)
    tabla = _tabla_de_dos_dias()

    res = nube_sync.sincronizar(tabla=tabla, hoy=HOY)

    assert [t.tipo for t in res.tipos if t.error] == ["consenso"]
    assert nube_sync.leer_cursor("consenso") == date(2026, 10, 14)
    # el segundo día no quedó a medias: ninguna de sus filas sobrevivió al rollback
    assert sorted({f[4] for f in _consenso()}) == [datetime(2026, 10, 14)]
    assert len(_consenso()) == 6

    monkeypatch.setattr(hc, "_insert_estimate_if_new_today", original)
    res2 = nube_sync.sincronizar(tabla=tabla, hoy=HOY)

    assert not res2.errores
    assert len(_consenso()) == 12  # completó sin duplicar el primero
    assert res2.tipos[0].dias[0] == date(2026, 10, 14)  # re-leyó el último día completo
    assert nube_sync.leer_cursor("consenso") == HOY


def test_c_se_RE_LEE_el_ultimo_dia_porque_la_Lambda_lo_sigue_escribiendo(test_db):
    tabla = TablaNube()
    tabla.poner(rn.item_consenso("AAPL", _snaps("AAPL", 1.5), D2))
    nube_sync.sincronizar(tabla=tabla, hoy=D2.date())  # la app abrió entre dos lotes
    assert len(_consenso()) == 2

    tabla.poner(rn.item_consenso("MSFT", _snaps("MSFT", 3.0), D2))  # el lote siguiente
    nube_sync.sincronizar(tabla=tabla, hoy=D2.date())

    assert sorted({f[0] for f in _consenso()}) == ["AAPL", "MSFT"]


def test_c_el_cursor_viejo_no_baja_mas_alla_de_lo_que_conserva_el_TTL():
    dias = nube_sync.dias_a_bajar(date(2026, 1, 1), HOY)
    assert dias[0] == date(2026, 7, 18) and dias[-1] == HOY
    assert nube_sync.dias_a_bajar(HOY, HOY) == [HOY]


# ── (d) sin credenciales ─────────────────────────────────────────────────────


def test_d_sin_perfil_no_hay_excepcion_y_hay_UN_aviso(test_db, monkeypatch, caplog):
    monkeypatch.setattr(nube_sync, "_avisado", False)
    caplog.set_level(logging.WARNING, logger=nube_sync.log.name)

    r1 = nube_sync.sincronizar(hoy=HOY)
    r2 = nube_sync.sincronizar(hoy=HOY)

    assert not r1.corrio and not r2.corrio
    assert "finanzias-lector" in r1.motivo
    assert (r1.aviso_nuevo, r2.aviso_nuevo) == (True, False)
    avisos = [r for r in caplog.records if "FUENTE NO DISPONIBLE" in r.getMessage()]
    assert len(avisos) == 1


def _escribir_perfil(tmp_path, monkeypatch, *, perfil="finanzias-lector"):
    ruta = tmp_path / "credentials"
    ruta.write_text(
        f"[{perfil}]\naws_access_key_id = AKIAFALSA\naws_secret_access_key = falsa\n", encoding="utf-8"
    )
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(ruta))


def test_d_el_perfil_se_detecta_sin_boto3_y_SOLO_el_nuestro(tmp_path, monkeypatch):
    assert not nube_sync.perfil_disponible()  # el conftest aísla el ~/.aws de la máquina
    _escribir_perfil(tmp_path, monkeypatch, perfil="otra-cuenta")
    assert not nube_sync.perfil_disponible()
    _escribir_perfil(tmp_path, monkeypatch)
    assert nube_sync.perfil_disponible()


# ── (e) un solo recolector del consenso ──────────────────────────────────────


def test_e_con_la_nube_andando_el_harvest_in_app_NO_pide_el_consenso(tmp_path, monkeypatch):
    from analysis.news_digest import fuentes_del_harvest

    pedidos: list[str] = []
    monkeypatch.setattr(
        ns, "_yf_news", lambda t: (pedidos.append("news") or [], SourceOutcome("yfinance_news", "ok", 0))
    )
    monkeypatch.setattr(
        ns,
        "_yf_estimates",
        lambda t: (pedidos.append("est") or [], SourceOutcome("yfinance_estimates", "ok", 0)),
    )
    monkeypatch.setattr(nube_sync, "boto3_instalado", lambda: True)

    assert fuentes_del_harvest() == "yfinance,sec,finnhub"  # sin perfil: como siempre
    _escribir_perfil(tmp_path, monkeypatch)
    fuentes = fuentes_del_harvest()
    assert fuentes == "yfinance_news,sec,finnhub"

    ns.collect_all("AAPL", {s for s in fuentes.split(",") if s not in ("sec", "finnhub")})
    assert pedidos == ["news"]


def test_e_con_la_sincronizacion_APAGADA_el_harvest_pide_todo(tmp_path, monkeypatch):
    from analysis.news_digest import fuentes_del_harvest
    from config.settings_manager import settings

    monkeypatch.setattr(nube_sync, "boto3_instalado", lambda: True)
    _escribir_perfil(tmp_path, monkeypatch)
    settings.set("nube_sync_enabled", False)

    assert fuentes_del_harvest() == "yfinance,sec,finnhub"
    assert nube_sync.sincronizar(tabla=TablaNube()).motivo.startswith("apagada")


def test_e_yfinance_a_secas_sigue_pidiendo_las_dos_cosas(monkeypatch):
    pedidos: list[str] = []
    monkeypatch.setattr(
        ns, "_yf_news", lambda t: (pedidos.append("news") or [], SourceOutcome("yfinance_news", "ok", 0))
    )
    monkeypatch.setattr(
        ns,
        "_yf_estimates",
        lambda t: (pedidos.append("est") or [], SourceOutcome("yfinance_estimates", "ok", 0)),
    )
    ns.collect_all("AAPL", {"yfinance"})
    assert pedidos == ["news", "est"]


# ── El scheduler ─────────────────────────────────────────────────────────────


@pytest.fixture
def qapp():
    """`pytest-qt` no está en el entorno de Chapa: la app de Qt se crea a mano."""
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _WorkerVivo:
    def __init__(self, vivo=True):
        self.vivo = vivo

    def isRunning(self):
        return self.vivo


def test_el_refresh_de_catalysts_ESPERA_a_la_nube_sin_perder_el_dia(qapp, monkeypatch):
    from analysis import news_digest
    from paper_trading import scheduler

    s = scheduler.PaperScheduler()
    lanzados: list[int] = []
    monkeypatch.setattr(s, "_launch_catalyst_refresh", lambda: lanzados.append(1))
    monkeypatch.setattr(news_digest, "refresh_due", lambda: True)

    s._nube_worker = _WorkerVivo(True)
    s._maybe_refresh_catalysts()
    assert lanzados == [] and s._last_catalyst_refresh is None  # no estampó el día

    s._nube_worker.vivo = False
    s._maybe_refresh_catalysts()
    assert lanzados == [1]


def test_sin_perfil_el_scheduler_no_lanza_worker_y_avisa_UNA_vez(qapp, monkeypatch):
    from paper_trading import scheduler

    monkeypatch.setattr(nube_sync, "_avisado", False)
    s = scheduler.PaperScheduler()
    recibidos = []
    s.nube_sync_completed.connect(recibidos.append)

    s._maybe_sync_nube()
    s._last_nube_sync = None  # otro día
    s._maybe_sync_nube()

    assert s._nube_worker is None
    assert len(recibidos) == 1 and recibidos[0].aviso_nuevo and not recibidos[0].corrio


def test_nube_sync_due():
    d = date(2026, 10, 16)
    assert scheduler_due(enabled=True, today=d, last=None, worker_running=False)
    assert not scheduler_due(enabled=True, today=d, last=d, worker_running=False)
    assert scheduler_due(enabled=True, today=d, last=date(2026, 10, 15), worker_running=False)
    assert not scheduler_due(enabled=False, today=d, last=None, worker_running=False)
    assert not scheduler_due(enabled=True, today=d, last=None, worker_running=True)


def scheduler_due(**kw):
    from paper_trading.scheduler import nube_sync_due

    return nube_sync_due(**kw)
