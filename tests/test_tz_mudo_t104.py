"""Tarea 104 — la zona horaria caía a UTC en silencio, y por la rama equivocada.

Dos defectos en la misma cadena:

1. **La rama de `pytz` era inalcanzable en el escenario para el que existe.** El
   `except` atrapaba ``ImportError``, pero el fallo realista en Windows no es que
   falte el módulo: es que ``ZoneInfo("America/New_York")`` no encuentre la base
   IANA, y eso levanta ``ZoneInfoNotFoundError`` — subclase de **``KeyError``**.
2. **El fallback a UTC no se anunciaba.** Y no es cosmético: de `_now_et` sale el
   disparo del scan diario (default 16:05 ET = después del cierre). Con UTC esas
   16:05 caen **12:05 ET**, el scan se dispara en pleno mercado y, como
   ``_last_daily_run`` marca el día como hecho, **el de las 16:05 ET ya no corre**.

Hoy está **latente**: los dos intérpretes del proyecto resuelven bien. Estos tests
simulan el fallo para que el día que pase se vea.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfoNotFoundError

import pytest

from data import yahoo_finance as yf


@pytest.fixture(autouse=True)
def _reset_aviso(monkeypatch):
    """El aviso sale una vez por proceso; cada test arranca con el flag limpio."""
    monkeypatch.setattr(yf, "_TZ_FALLO_AVISADO", False, raising=False)


def _romper_zoneinfo(monkeypatch, exc: Exception) -> None:
    """Hace que ``ZoneInfo("America/New_York")`` levante ``exc``."""
    import zoneinfo

    def _boom(_nombre):
        raise exc

    monkeypatch.setattr(zoneinfo, "ZoneInfo", _boom)


# ── El error de cableado ────────────────────────────────────────────────────


def test_ZoneInfoNotFoundError_NO_es_ImportError():
    """La premisa del defecto, fijada como test: el `except ImportError` no podía
    atrapar el fallo para el que se escribió."""
    assert issubclass(ZoneInfoNotFoundError, KeyError)
    assert not issubclass(ZoneInfoNotFoundError, ImportError)


def test_sin_tzdata_AHORA_si_cae_a_pytz(monkeypatch):
    """**El arreglo.** Con `ZoneInfoNotFoundError` la rama de `pytz` tiene que
    alcanzarse: antes se saltaba entera y se iba a UTC."""
    pytz = pytest.importorskip("pytz")
    _romper_zoneinfo(monkeypatch, ZoneInfoNotFoundError("no tzdata"))

    tz = yf.market_timezone()
    assert tz is not None
    assert "New_York" in str(tz)
    assert isinstance(tz, type(pytz.timezone("America/New_York")))


def test_sin_zoneinfo_NI_pytz_devuelve_None_y_AVISA(monkeypatch, caplog):
    """El caso terminal: no hay con qué resolver la zona. Antes devolvía UTC sin
    una sola línea; ahora avisa **antes** de que nadie use la hora equivocada."""
    _romper_zoneinfo(monkeypatch, ZoneInfoNotFoundError("no tzdata"))
    monkeypatch.setitem(__import__("sys").modules, "pytz", None)

    with caplog.at_level(logging.WARNING):
        tz = yf.market_timezone()

    assert tz is None
    assert any("zona horaria" in r.getMessage() for r in caplog.records), [
        r.getMessage() for r in caplog.records
    ]


def test_el_aviso_dice_la_CONSECUENCIA_no_solo_el_sintoma(monkeypatch, caplog):
    """*«No se pudo resolver la zona»* no le dice nada a nadie a las 3 de la mañana.
    El mensaje tiene que nombrar qué se rompe y cómo se arregla."""
    _romper_zoneinfo(monkeypatch, ZoneInfoNotFoundError("no tzdata"))
    monkeypatch.setitem(__import__("sys").modules, "pytz", None)

    with caplog.at_level(logging.WARNING):
        yf.market_timezone()

    msg = next(r.getMessage() for r in caplog.records if "zona horaria" in r.getMessage())
    assert "scan diario" in msg
    assert "tzdata" in msg and "pytz" in msg


def test_el_aviso_sale_UNA_sola_vez(monkeypatch, caplog):
    """Lo llaman el scheduler en cada tick y la UI en cada refresh: un WARNING por
    llamada es spam, y un guard que hace ruido se termina apagando."""
    _romper_zoneinfo(monkeypatch, ZoneInfoNotFoundError("no tzdata"))
    monkeypatch.setitem(__import__("sys").modules, "pytz", None)

    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            yf.market_timezone()

    assert sum("zona horaria" in r.getMessage() for r in caplog.records) == 1


def test_el_camino_sano_no_avisa_nada(caplog):
    """El control: con la zona resuelta —que es el estado de hoy— no hay ruido."""
    with caplog.at_level(logging.WARNING):
        tz = yf.market_timezone()
    assert tz is not None
    assert not any("zona horaria" in r.getMessage() for r in caplog.records)


# ── Los dos consumidores ────────────────────────────────────────────────────


def test_now_et_cae_a_UTC_pero_ya_no_en_silencio(monkeypatch, caplog):
    from paper_trading import scheduler

    _romper_zoneinfo(monkeypatch, ZoneInfoNotFoundError("no tzdata"))
    monkeypatch.setitem(__import__("sys").modules, "pytz", None)

    with caplog.at_level(logging.WARNING):
        ahora = scheduler._now_et()

    assert isinstance(ahora, datetime)
    assert any("zona horaria" in r.getMessage() for r in caplog.records)


def test_is_market_open_falla_CERRADO_que_es_la_direccion_segura(monkeypatch, caplog):
    """Sin hora confiable no se puede afirmar que el mercado está abierto. Devolver
    `False` es lo que ya hacía; lo que faltaba era que se supiera por qué."""
    _romper_zoneinfo(monkeypatch, ZoneInfoNotFoundError("no tzdata"))
    monkeypatch.setitem(__import__("sys").modules, "pytz", None)

    with caplog.at_level(logging.WARNING):
        abierto, etiqueta = yf.is_market_open()

    assert abierto is False
    assert etiqueta == "—"
    assert any("zona horaria" in r.getMessage() for r in caplog.records)


def test_los_dos_consumidores_usan_LA_MISMA_resolucion():
    """El comentario del scheduler decía *«reuse the same logic as is_market_open»*
    mientras la duplicaba — y por eso el defecto vivía en los dos lados. Ahora es
    una sola función, y este test lo fija contra la próxima copia."""
    from pathlib import Path

    fuente = (Path(__file__).resolve().parent.parent / "paper_trading" / "scheduler.py").read_text(
        encoding="utf-8"
    )
    assert "market_timezone" in fuente
    assert 'ZoneInfo("America/New_York")' not in fuente, "volvió a duplicar la resolución"
