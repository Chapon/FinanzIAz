"""Tarea 148 (SLACK-EN-TESTS) — la suite no le manda mensajes al Slack de Chapa.

**Lo reportó él, no la suite.** El 2026-09-09 aparecieron en el canal avisos de
precio de **MARA a $13.00 · objetivo BELOW $14.00 · rebote** —un precio de
laboratorio, y semanas de desfase contra el mercado— más una tanda de *«Yahoo sin
responder»*. Son **9 mensajes por corrida**, contados interceptando el POST:

* **3** de alerta de precio. ``tests/test_alerts_worker_t80.py`` crea una alerta de
  MARA y llama a ``AlertCheckWorker.do_work()``; el worker construye su
  ``AlertManager`` **sin notifier inyectado** (``ui/alerts_tab.py:75``), así que
  ``_notify_slack`` cae en ``default_notifier``.
* **6** de outage de datos (4 de caída + 2 de recuperación), por el mismo camino
  vía ``data.yahoo_finance._maybe_notify_outage``. Los dos tests que *sí* inyectan
  ``_outage_notifier`` no son los que mandan — es el resto.
* ``default_notifier`` → ``post_to_slack`` → ``requests.post`` de verdad, porque
  ``SLACK_BOT_TOKEN`` y ``SLACK_CHANNEL`` están en el entorno de Chapa.

Todos **pasaban en verde**: mandar un mensaje no es un fallo para nadie. Es la misma
forma del log de producción (tarea 78) —la suite escribiendo en un recurso vivo sin
que nada lo note— y por eso el arreglo tiene la misma forma: una variable de entorno
puesta en ``conftest.py`` antes de cualquier import, leída en el **límite de red** y
no en cada productor.

**Y la mitad del defecto se diagnosticó mal antes de medirlo.** La primera lectura
fue *«los de Yahoo son de la app corriendo de verdad»*, porque
``test_data_outage_alert.py`` inyecta el notifier en los dos tests que se leen
primero. Los 9 salieron de contar, no de leer — [[validar-el-instrumento-antes-del-numero]].

Que el corte vaya en el límite y no en los productores es lo que lo hace un
predicado: hoy mandan tres (``alert_manager``, ``yahoo_finance``, el motor) y el
cuarto no va a estar en ninguna lista. Ver [[guard-no-puede-usar-de-verdad-lo-que-chequea]].
"""

from __future__ import annotations

import os

import pytest

import integrations.slack as slack
from alerts.alert_manager import AlertManager
from integrations.slack import SLACK_DISABLED_ENV, AlertNotice, post_to_slack, slack_deshabilitado


class _RespuestaOK:
    """Lo mínimo que ``post_to_slack`` le pide a la respuesta de `requests`."""

    @staticmethod
    def json() -> dict:
        return {"ok": True}


@pytest.fixture
def red(monkeypatch):
    """Registra todo POST que salga, en vez de dejarlo salir."""
    posts: list[tuple] = []

    def _post(url, **kw):
        posts.append((url, kw))
        return _RespuestaOK()

    import requests

    monkeypatch.setattr(requests, "post", _post)
    return posts


# ── El invariante ────────────────────────────────────────────────────────────


def test_la_suite_corre_con_el_bloqueo_puesto():
    """Si alguien saca la línea del ``conftest``, esto es lo que se entera.

    El test que importa no es el de la función: es éste. La función puede estar
    perfecta y el bloqueo no estar puesto, que es exactamente el estado en el que
    estuvo el proyecto hasta hoy.
    """
    assert os.environ.get(SLACK_DISABLED_ENV), (
        f"{SLACK_DISABLED_ENV} no está en el entorno de la suite: sacaron el "
        "os.environ.setdefault del conftest y los tests vuelven a mandar Slack real"
    )
    assert slack_deshabilitado()


def test_el_camino_EXACTO_del_defecto_no_manda_nada(red, monkeypatch):
    """La regresión del bug real: un ``AlertManager`` **sin notifier**, que es como
    lo construye el worker de la pestaña de alertas."""
    monkeypatch.setattr(slack, "_resolve_channel", lambda c: c or "C-DE-PRUEBA")
    monkeypatch.setattr(slack, "_resolve_token", lambda t: t or "xoxb-de-prueba")

    AlertManager()._notify_slack([AlertNotice("MARA", "BELOW", 14.0, 13.0, "rebote")])

    assert red == [], "un test volvió a mandarle un mensaje al Slack de producción"


def test_post_to_slack_corta_ANTES_de_resolver_token_y_canal(red):
    """No sale, y devuelve ``False`` como cualquier otra rama fail-open."""
    assert post_to_slack("hola") is False
    assert red == []


def test_el_bloqueo_no_depende_de_que_diga_exactamente_1(monkeypatch):
    """El modo seguro se activa con la variable **presente**, no con un valor exacto.

    Si sólo bloqueara con ``"1"``, un ``FINANZIAS_DISABLE_SLACK=true`` escrito de
    memoria dejaría la suite mandando mensajes y con toda la pinta de estar cortada.
    """
    for valor in ("1", "true", "si", "0.0"):
        monkeypatch.setenv(SLACK_DISABLED_ENV, valor)
        assert slack_deshabilitado(), f"{valor!r} tendría que bloquear"

    for valor in ("", "0"):
        monkeypatch.setenv(SLACK_DISABLED_ENV, valor)
        assert not slack_deshabilitado(), f"{valor!r} NO tendría que bloquear"


# ── La salida para un test que sí sea de mensajería ──────────────────────────


def test_un_test_de_mensajeria_puede_levantar_el_bloqueo(red, monkeypatch):
    """La excepción que pidió Chapa, y la mutación en el otro sentido.

    Sin esto el guard podría estar cortando por cualquier otro motivo —un token
    ausente, un canal vacío— y los tests de arriba pasarían igual. Acá se prueba que
    lo único que separa *no manda* de *manda* es la variable.

    Un test específico de mensajería igual **stubbea `requests`**: levantar el
    bloqueo habilita el camino, no el envío real.
    """
    monkeypatch.delenv(SLACK_DISABLED_ENV, raising=False)

    assert post_to_slack("hola", channel="C-DE-PRUEBA", token="xoxb-de-prueba") is True
    assert len(red) == 1
    url, kw = red[0]
    assert url == slack.SLACK_POST_MESSAGE_URL
    assert kw["json"] == {"channel": "C-DE-PRUEBA", "text": "hola"}
