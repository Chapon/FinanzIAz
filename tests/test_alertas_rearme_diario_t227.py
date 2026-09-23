"""Tarea 227 — las alertas se reevalúan todos los días y el estado se resetea.

El defecto, que se vio en la pantalla antes que en el código
-------------------------------------------------------------
El panel de Alertas mostraba, para el **mismo ticker**, *«Por encima»* y *«Por
debajo»* las dos en **Disparada**. Eso no puede ser cierto al mismo tiempo — y no lo
era: eran dos disparos de **fechas distintas** pintados como si fueran el presente.
En CRM, el de compra del 09/07 y el de venta del 27/08; en MARA, uno del 10/08.

La causa es que ``is_active=False`` era un **latch sin salida**. Significa
*«disparada»*, y lo único que lo devolvía a ``True`` era **editar** la alerta a mano
(``update_alert``). Ningún camino automático lo reseteaba, así que una alerta que
disparó una vez quedaba disparada para siempre y dejaba de avisar de nada.

Y había un segundo defecto, que el primero tapaba
--------------------------------------------------
Tres de las cinco alertas tenían los umbrales **invertidos** — el target de *por
encima* por **debajo** del de *por debajo* —, o sea una banda donde las **dos**
condiciones son verdaderas a la vez. Medido con los precios del 2026-09-23:

======  =========  =========  =========  =================================
ticker  precio     ▲ encima   ▼ debajo   dispara
======  =========  =========  =========  =================================
LOW     191,63     160,00     218,00     **las dos** (invertida)
AMT     170,77     160,0001   173,00     **las dos** (invertida)
PFE      28,05      19,80      22,00     sólo ▲, pero invertida
======  =========  =========  =========  =================================

O sea que el latch estaba **escondiendo** el otro defecto: con el re-arme puesto y
los umbrales sin tocar, LOW y AMT habrían disparado las dos alertas **todos los
días**, y el estado imposible habría pasado a ser genuinamente cierto. Por eso las
dos cosas van juntas y no en tareas separadas. Los umbrales los decidió Chapa
(swap en las tres), y se corrigieron por ``update_alert``, que es el camino de la app.

Qué fija este archivo
---------------------
El re-arme es **por día del reloj local**, no por UTC, y ésa es la parte que se
puede romper sin que se note: con ART = UTC−3 un disparo de las 22:30 cae al día
siguiente en UTC, así que cortar por UTC re-armaría a las 21:00 del mismo día.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from alerts.alert_manager import AlertManager, alert_status, corresponde_rearmar, dia_local
from database.models import Alert, Portfolio, session_scope, utcnow_naive


def _prices(mapping):
    def _fn(ticker):
        return {"price": mapping[ticker]} if ticker in mapping else None

    return _fn


class _MudoNotifier:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, text: str) -> bool:
        self.calls.append(text)
        return True


@pytest.fixture
def portfolio_id(test_db):
    with session_scope() as s:
        p = Portfolio(name="Test PF")
        s.add(p)
        s.flush()
        return p.id


def _stub(*, is_active: bool, triggered_at):
    return SimpleNamespace(is_active=is_active, triggered_at=triggered_at, is_paused=False)


# ── El caso de la pantalla: dos alertas del mismo ticker, las dos "Disparada" ──


def test_dos_disparos_de_DIAS_DISTINTOS_no_pueden_quedar_los_dos_en_disparada(portfolio_id, monkeypatch):
    """El bug tal como se veía: CRM ▲ y ▼ las dos en rojo, con 49 días de diferencia.

    Se reconstruye el estado exacto de la DB viva —dos alertas del mismo ticker, las
    dos con ``is_active=False`` y ``triggered_at`` de julio y agosto— y se chequea.
    Con el precio de hoy sólo una de las dos puede estar disparada.
    """
    AlertManager.create_alert(portfolio_id, "CRM", "ABOVE", 230.0, "CRM en rango de venta")
    AlertManager.create_alert(portfolio_id, "CRM", "BELOW", 180.0, "CRM en rango de compra")
    with session_scope() as s:
        for a in s.query(Alert).all():
            a.is_active = False
            a.triggered_at = (
                datetime(2026, 7, 9, 20, 0) if a.alert_type == "BELOW" else datetime(2026, 8, 27, 14, 49)
            )

    monkeypatch.setattr("alerts.alert_manager.get_current_price", _prices({"CRM": 238.86}))
    AlertManager(notifier=_MudoNotifier()).check_alerts(portfolio_id)

    with session_scope() as s:
        por_tipo = {a.alert_type: a for a in s.query(Alert).all()}
        # 238,86 ≥ 230 → la de venta SÍ está disparada, hoy.
        assert alert_status(por_tipo["ABOVE"]) == "disparada"
        assert dia_local(por_tipo["ABOVE"].triggered_at) == dia_local(utcnow_naive())
        # 238,86 > 180 → la de compra NO. Se re-armó y su fecha vieja queda como historia.
        assert alert_status(por_tipo["BELOW"]) == "activa"
        assert por_tipo["BELOW"].triggered_at == datetime(2026, 7, 9, 20, 0)


# ── La frontera del día, que es la parte rompible ────────────────────────────


def test_el_re_arme_corta_por_el_dia_LOCAL_y_no_por_UTC():
    """Un disparo de las 22:30 ART es «hoy» para el usuario aunque en UTC sea mañana.

    Si el corte fuera por UTC, una alerta que disparó a las 22:30 ART se re-armaría
    a las 21:00 del **mismo** día local y podría avisar dos veces el mismo día.
    """
    ahora_utc = utcnow_naive()
    hoy_local = dia_local(ahora_utc)

    # Un timestamp del mismo día local, a otra hora: NO se re-arma.
    mismo_dia = datetime.combine(hoy_local, datetime.min.time()).astimezone().astimezone(
        timezone.utc
    ).replace(tzinfo=None) + timedelta(hours=1)
    assert dia_local(mismo_dia) == hoy_local
    assert corresponde_rearmar(_stub(is_active=False, triggered_at=mismo_dia), ahora_utc) is False

    # Uno de ayer: SÍ.
    ayer = ahora_utc - timedelta(days=1)
    assert corresponde_rearmar(_stub(is_active=False, triggered_at=ayer), ahora_utc) is True


def test_dia_local_coincide_con_lo_que_MUESTRA_la_UI():
    """``alerts/`` duplica la convención de ``ui.time_utils`` en vez de importarla.

    Se duplica a propósito —el dominio no debe depender de la capa de UI— pero un
    literal o una convención duplicados **derivan solos** (lección de la 71), así que
    lo que evita la deriva es este test. Si derivaran, el re-arme cortaría el día en
    un instante distinto del que el usuario ve en la columna «Última vez».
    """
    from ui.time_utils import fmt_local

    for dt in (
        datetime(2026, 9, 23, 2, 30),  # madrugada UTC = día anterior en ART
        datetime(2026, 9, 23, 23, 45),
        datetime(2026, 1, 1, 0, 0),
    ):
        assert dia_local(dt).isoformat() == fmt_local(dt, "%Y-%m-%d")


# ── Las dos direcciones del kill-criteria ────────────────────────────────────


def test_una_alerta_que_disparo_HOY_no_se_re_arma_y_no_avisa_dos_veces(portfolio_id, monkeypatch):
    """La otra dirección: el re-arme es DIARIO, no en cada chequeo.

    El chequeo corre cada 120 s. Si el re-arme no mirara la fecha, la misma alerta
    avisaría por Slack y por popup cada dos minutos mientras la condición se cumpla.
    """
    AlertManager.create_alert(portfolio_id, "MARA", "BELOW", 14.0)
    monkeypatch.setattr("alerts.alert_manager.get_current_price", _prices({"MARA": 13.0}))
    notifier = _MudoNotifier()

    mgr = AlertManager(notifier=notifier)
    assert [a.ticker for a in mgr.check_alerts(portfolio_id)] == ["MARA"]
    # Segunda pasada el mismo día, con la condición todavía verdadera.
    assert mgr.check_alerts(portfolio_id) == []
    assert len(notifier.calls) == 1, "avisó dos veces el mismo día"


def test_el_re_arme_NO_borra_triggered_at(portfolio_id, monkeypatch):
    """La fecha del último disparo es la memoria del panel, y se conserva.

    Borrarla dejaría la tabla sin historia; dejar ``is_active=False`` es lo que la
    tenía congelada. La columna «Última vez» existe por esta decisión.
    """
    AlertManager.create_alert(portfolio_id, "MARA", "ABOVE", 100.0)
    viejo = datetime(2026, 8, 10, 15, 49)
    with session_scope() as s:
        a = s.query(Alert).one()
        a.is_active = False
        a.triggered_at = viejo

    monkeypatch.setattr("alerts.alert_manager.get_current_price", _prices({"MARA": 13.0}))
    AlertManager(notifier=_MudoNotifier()).check_alerts(portfolio_id)

    with session_scope() as s:
        a = s.query(Alert).one()
        assert a.is_active is True, "se re-armó"
        assert a.triggered_at == viejo, "y conservó cuándo fue la última vez"


def test_el_re_arme_corre_ANTES_de_evaluar_y_no_una_pasada_tarde(portfolio_id, monkeypatch):
    """Una alerta de ayer tiene que poder disparar en el MISMO chequeo que la re-arma.

    Si el re-arme fuera después de evaluar, el reset recién se vería 120 s más tarde
    y la pantalla mostraría el estado de la pasada anterior. La mutación que esto
    caza es mover ``_rearmar_dia_nuevo`` abajo del loop.
    """
    AlertManager.create_alert(portfolio_id, "MARA", "BELOW", 14.0)
    with session_scope() as s:
        a = s.query(Alert).one()
        a.is_active = False
        a.triggered_at = utcnow_naive() - timedelta(days=1)

    monkeypatch.setattr("alerts.alert_manager.get_current_price", _prices({"MARA": 13.0}))
    disparadas = AlertManager(notifier=_MudoNotifier()).check_alerts(portfolio_id)

    assert [a.ticker for a in disparadas] == ["MARA"], "no disparó en la misma pasada del re-arme"


def test_una_PAUSADA_se_re_arma_pero_sigue_sin_evaluarse(portfolio_id, monkeypatch):
    """Pausar y disparar son ejes distintos, y el re-arme no los mezcla.

    Una pausada que había disparado pasa a mostrarse como **Pausada** —que es lo que
    de verdad es— sin volver a consultar precio ni avisar. Antes quedaba como
    *Disparada* para siempre, que era doblemente falso.
    """
    AlertManager.create_alert(portfolio_id, "MARA", "BELOW", 14.0)
    with session_scope() as s:
        a = s.query(Alert).one()
        a.is_active = False
        a.is_paused = True
        a.triggered_at = utcnow_naive() - timedelta(days=3)

    notifier = _MudoNotifier()
    monkeypatch.setattr("alerts.alert_manager.get_current_price", _prices({"MARA": 13.0}))
    assert AlertManager(notifier=notifier).check_alerts(portfolio_id) == []
    assert notifier.calls == []

    with session_scope() as s:
        a = s.query(Alert).one()
        assert alert_status(a) == "pausada"


def test_el_re_arme_respeta_el_filtro_de_portafolio(portfolio_id, monkeypatch):
    """Chequear un portafolio no puede tocar el estado de otro."""
    with session_scope() as s:
        otro = Portfolio(name="Otro PF")
        s.add(otro)
        s.flush()
        otro_id = otro.id

    AlertManager.create_alert(portfolio_id, "MARA", "BELOW", 14.0)
    AlertManager.create_alert(otro_id, "AAPL", "BELOW", 14.0)
    ayer = utcnow_naive() - timedelta(days=1)
    with session_scope() as s:
        for a in s.query(Alert).all():
            a.is_active = False
            a.triggered_at = ayer

    monkeypatch.setattr("alerts.alert_manager.get_current_price", _prices({"MARA": 13.0}))
    AlertManager(notifier=_MudoNotifier()).check_alerts(portfolio_id)

    with session_scope() as s:
        por_ticker = {a.ticker: a for a in s.query(Alert).all()}
        assert por_ticker["MARA"].is_active is False  # disparó hoy
        assert por_ticker["AAPL"].is_active is False  # intacta: es de otro portafolio


def test_una_disparada_SIN_fecha_no_queda_trabada():
    """Estado que no se puede justificar: se re-arma en vez de quedar congelado."""
    assert corresponde_rearmar(_stub(is_active=False, triggered_at=None), utcnow_naive()) is True


def test_una_ACTIVA_nunca_entra_al_re_arme():
    """La guarda barata: sin esto el re-arme tocaría filas que no le corresponden."""
    assert corresponde_rearmar(_stub(is_active=True, triggered_at=None), utcnow_naive()) is False


# ── Los umbrales invertidos, que el latch tapaba ─────────────────────────────


def test_umbrales_INVERTIDOS_hacen_verdaderas_las_dos_condiciones_a_la_vez(portfolio_id, monkeypatch):
    """Por qué los umbrales se arreglaron en la MISMA pasada que el re-arme.

    Con ▲160 / ▼173 y el precio en 170,77, las dos condiciones son ciertas. Sin el
    re-arme eso quedaba congelado y parecía un estado viejo; **con** el re-arme, LOW
    y AMT habrían disparado las dos alertas todos los días. El latch escondía el
    defecto, y sacarlo sin corregir los umbrales lo habría vuelto ruido diario.
    """
    AlertManager.create_alert(portfolio_id, "AMT", "ABOVE", 160.0001)
    AlertManager.create_alert(portfolio_id, "AMT", "BELOW", 173.0)
    monkeypatch.setattr("alerts.alert_manager.get_current_price", _prices({"AMT": 170.77}))

    disparadas = AlertManager(notifier=_MudoNotifier()).check_alerts(portfolio_id)
    assert sorted(a.alert_type for a in disparadas) == ["ABOVE", "BELOW"]


def test_con_los_umbrales_EN_ORDEN_el_precio_del_medio_no_dispara_ninguna(portfolio_id, monkeypatch):
    """Y la dirección que valida el arreglo: ▲173 / ▼160 con AMT en 170,77 → nada.

    Es el valor que eligió Chapa. La banda del medio es justamente lo que una pareja
    de alertas compra/venta tiene que dejar en silencio.
    """
    AlertManager.create_alert(portfolio_id, "AMT", "ABOVE", 173.0)
    AlertManager.create_alert(portfolio_id, "AMT", "BELOW", 160.0)
    monkeypatch.setattr("alerts.alert_manager.get_current_price", _prices({"AMT": 170.77}))

    assert AlertManager(notifier=_MudoNotifier()).check_alerts(portfolio_id) == []
