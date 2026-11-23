"""Tarea 437 [H-1] — un aviso de Slack que sale bien deja una línea INFO con su encabezado, sin el cuerpo.

Hasta acá sólo dejaban línea los fallos, y el bot no puede leer el canal (``missing_scope``): la
auditoría 404 escribió *«ningún envío a Slack, ni fallido ni bueno»* con 10 fills en su ventana.
"""

from __future__ import annotations

import logging
from datetime import datetime

import pytest

import integrations.slack as slack
from integrations.slack import (
    SLACK_DISABLED_ENV,
    OrderNotice,
    encabezado_del_aviso,
    format_outage_message,
    format_scan_summary,
    post_to_slack,
)


class _Respuesta:
    def __init__(self, ok: bool):
        self._ok = ok

    def json(self) -> dict:
        return {"ok": True} if self._ok else {"ok": False, "error": "channel_not_found"}


@pytest.fixture
def slack_abierto(monkeypatch):
    """Levanta el bloqueo de la suite y cambia la red por un POST registrado."""
    import requests

    posts: list = []
    estado = {"ok": True}

    def _post(url, **kw):
        posts.append(kw)
        return _Respuesta(estado["ok"])

    monkeypatch.delenv(SLACK_DISABLED_ENV, raising=False)
    monkeypatch.setattr(requests, "post", _post)
    monkeypatch.setattr(slack, "_resolve_channel", lambda c: c or "C-DE-PRUEBA")
    monkeypatch.setattr(slack, "_resolve_token", lambda t: t or "xoxb-de-prueba")
    return posts, estado


def _ordenes() -> str:
    avisos = [
        OrderNotice(
            account_name="Sim Segundo",
            ticker=t,
            side="BUY",
            status="filled",
            shares=10,
            price=100.0,
            reason="señal secreta",
        )
        for t in ("AAPL", "MSFT")
    ]
    return format_scan_summary("Sim Segundo", avisos, scan_at=datetime(2026, 11, 23, 14, 5))


def _lineas_de_envio(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "Slack notify: enviado" in r.getMessage()]


def test_un_envio_bueno_deja_su_linea_con_el_encabezado_y_sin_el_cuerpo(slack_abierto, caplog):
    texto = _ordenes()
    with caplog.at_level(logging.INFO, logger="integrations.slack"):
        assert post_to_slack(texto) is True
    lineas = _lineas_de_envio(caplog)
    assert len(lineas) == 1
    assert "Sim Segundo" in lineas[0] and "2 nuevas" in lineas[0] and "(+2 líneas)" in lineas[0]
    assert "AAPL" not in lineas[0] and "señal secreta" not in lineas[0]  # el cuerpo no va


def test_bloqueado_o_fallido_no_deja_la_linea_de_enviado(slack_abierto, caplog, monkeypatch):
    posts, estado = slack_abierto
    estado["ok"] = False
    with caplog.at_level(logging.INFO, logger="integrations.slack"):
        assert post_to_slack(_ordenes()) is False  # Slack contestó not-ok
        monkeypatch.setenv(SLACK_DISABLED_ENV, "1")
        assert post_to_slack(_ordenes()) is False  # bloqueado: no sale nada
    assert len(posts) == 1
    assert _lineas_de_envio(caplog) == []


def test_el_encabezado_de_cada_formato():
    caida = format_outage_message("open", minutes=12, level=1)
    assert encabezado_del_aviso(caida).startswith("⚠️ *FinanzIAs · Yahoo sin responder*")
    assert encabezado_del_aviso("una\ndos") == "una (+1 línea)"
    largo = encabezado_del_aviso("x" * 300)
    assert len(largo) == 100 and largo.endswith("…")
    assert encabezado_del_aviso("") == ""
