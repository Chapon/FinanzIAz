"""Tarea 228 — el CLI del dashboard resuelve la cuenta viva en vez de devolver un error.

El defecto
----------
``scripts/dashboard_data.py`` declaraba ``DEFAULT_ACCOUNT_ID = None  # None ⇒ la cuenta
viva`` y **no lo referenciaba en ninguna línea**. ``main()`` pasaba ``args.account`` —con
su propio ``default=None``— directo a ``build_payload``, y ``_account_row(con, None)`` no
encuentra nada, así que sin ``--account`` el script imprimía::

    {"error": "account None not found in ..."}

**Tres afirmaciones distintas sobre lo mismo, y ninguna era la que corría:** el ``--help``
decía *«default: 1»*, la constante decía *«la cuenta viva»* y el comportamiento era un
error. Vivió desde el 2026-09-01 —el commit que cableó la tarea 70— porque el guard que
debía cazarlo mira que la constante esté **declarada** con el valor correcto y nunca que
esté **usada** (eso es la tarea 229).

Era latente, no roto en producción: el artefacto se alimenta de
``scripts/refresh_dashboard.py``, que sí tiene la resolución de la 70. Pero el docstring
del módulo documenta el CLI como el camino del artefacto, así que dirigía mal.

Por qué la regla se duplica en vez de llamar a ``live_account_id``
------------------------------------------------------------------
``paper_trading.account.live_account_id`` resuelve por el **ORM**, contra el engine
global — o sea contra la base del repo. ``dashboard_data.py`` es read-only sobre la base
que le pasen por ``--db``, que puede ser un backup o una copia en ``/tmp`` (regla 5).
Llamarlo haría que ``--db backup.db`` trajera el id de la base **viva** y lo aplicara a
la otra: un desvío cruzado, silencioso, de la misma familia que los que la 220 y la 223
destaparon en el VS SPY.

Así que la regla se duplica **a propósito**, y lo que evita que derive es el test de
abajo, que corre las **dos** implementaciones sobre los mismos datos y exige el mismo
resultado. Es la forma de la 71, y la misma con la que se ató ``dia_local`` a
``fmt_local`` en la 227.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from paper_trading.account import live_account_id
from paper_trading.models import PaperAccount
from scripts.dashboard_data import DEFAULT_ACCOUNT_ID, _live_account_id, build_payload

_REPO = Path(__file__).resolve().parent.parent

# Configuraciones de cuentas con las que se alimentan LAS DOS implementaciones.
# Una sola fuente para los dos lados: así «los mismos datos» es por construcción y no
# por dos listas escritas a mano que pueden separarse.
_CASOS = [
    pytest.param([(1, True)], 1, id="una-activa"),
    pytest.param([(1, False), (2, True)], 2, id="la-pausada-no-gana"),
    pytest.param([(2, True), (5, True)], 2, id="varias-activas-gana-la-de-menor-id"),
    pytest.param([(3, True), (1, True), (2, True)], 1, id="menor-id-aunque-se-creen-desordenadas"),
    pytest.param([(1, False), (2, False)], None, id="ninguna-activa-no-se-elige-cualquiera"),
    pytest.param([], None, id="sin-cuentas"),
]


def _db_cruda(tmp_path: Path, cuentas) -> Path:
    """DB de **archivo** con el esquema real y las cuentas pedidas.

    El esquema sale de ``Base.metadata``, no escrito a mano: si se escribiera a mano,
    el test podría quedar verde sobre una tabla que ya no se parece a la de producción.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import paper_trading.models  # noqa: F401  (registra las tablas de paper en Base)
    from database import models as db_models

    ruta = tmp_path / "cruda.db"
    engine = create_engine(f"sqlite:///{ruta}")
    db_models.Base.metadata.create_all(engine)
    Sesion = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Sesion() as s:
        for cid, activa in cuentas:
            s.add(PaperAccount(id=cid, name=f"Cuenta {cid}", is_active=activa))
        s.commit()
    engine.dispose()
    return ruta


# ── El invariante: las dos implementaciones dicen lo mismo ───────────────────


@pytest.mark.parametrize(("cuentas", "esperado"), _CASOS)
def test_las_dos_implementaciones_resuelven_LA_MISMA_cuenta(tmp_path, monkeypatch, cuentas, esperado):
    """``_live_account_id`` (SQL crudo) y ``live_account_id`` (ORM) no pueden divergir.

    Las dos corren sobre **la misma base de archivo** —el ORM apuntado ahí con
    monkeypatch—, no sobre dos bases "equivalentes" construidas por separado: dos bases
    que alguien tiene que mantener iguales son otra duplicación, y podrían separarse sin
    que nadie lo note. Si mañana se cambiara la regla de desempate en un lado —por
    ejemplo a «la más reciente»— este test lo caza, y es lo único que sostiene una
    duplicación deliberada.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database import models as db_models

    ruta = _db_cruda(tmp_path, cuentas)
    engine = create_engine(f"sqlite:///{ruta}")
    monkeypatch.setattr(db_models, "ENGINE", engine)
    monkeypatch.setattr(
        db_models, "SessionLocal", sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    )

    con = sqlite3.connect(ruta)
    try:
        por_sql = _live_account_id(con)
    finally:
        con.close()
    por_orm = live_account_id()
    engine.dispose()

    assert por_sql == esperado
    assert por_sql == por_orm, "el CLI y el ORM resuelven cuentas distintas"


# ── El caso del kill-criteria ────────────────────────────────────────────────


def test_sin_account_devuelve_la_cuenta_VIVA_y_no_un_error(tmp_path):
    """Lo que el defecto rompía: ``build_payload`` sin id explícito.

    Antes devolvía ``{"error": "account None not found"}`` porque ``None`` viajaba entero
    hasta el ``SELECT``.
    """
    ruta = _db_cruda(tmp_path, [(1, False), (2, True)])
    payload = build_payload(ruta)

    assert "error" not in payload, payload.get("error")
    assert payload["account"]["id"] == 2
    assert payload["account"]["is_active"] == 1


def test_el_default_del_modulo_MANEJA_de_verdad_el_default_del_CLI(tmp_path, monkeypatch, capsys):
    """La constante tiene que estar **cableada**, y eso sólo se ve si cambia de valor.

    **Apareció probando por mutación.** El primer intento afirmaba *«llamar sin argumento
    da lo mismo que llamar con ``DEFAULT_ACCOUNT_ID``»*, y eso es cierto **también** con
    el bug puesto: como la constante vale ``None`` y la resolución vive en
    ``build_payload``, escribir ``default=None`` a mano es behaviouralmente idéntico. El
    test no podía distinguir lo que decía fijar — el mismo falso negativo que la fila
    centinela de la 221 y el caso plano de la 230, ahora en su cuarta forma.

    Lo que sí lo distingue es **mover la constante**: si ``main()`` la usa de verdad, el
    CLI tiene que seguirla a un id concreto en vez de resolver la cuenta viva. Ésa es la
    propiedad que el guard de la 70 nunca miró y que la **229** va a cubrir para toda la
    familia.
    """
    import scripts.dashboard_data as dd

    assert DEFAULT_ACCOUNT_ID is None, "el default declarado del módulo es «la cuenta viva»"
    ruta = _db_cruda(tmp_path, [(1, False), (2, True)])

    monkeypatch.setattr(dd, "DEFAULT_ACCOUNT_ID", 1)  # la PAUSADA, que jamás se resolvería sola
    assert dd.main(["--db", str(ruta)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["account"]["id"] == 1, "el CLI no sigue a DEFAULT_ACCOUNT_ID: la constante está muerta"


# ── Las otras direcciones ────────────────────────────────────────────────────


def test_con_account_explicito_se_respeta_AUNQUE_este_pausada(tmp_path):
    """La decisión es del operador, igual que en la 70. Pedirla explícitamente la trae."""
    ruta = _db_cruda(tmp_path, [(1, False), (2, True)])
    payload = build_payload(ruta, 1)

    assert payload["account"]["id"] == 1
    assert payload["account"]["is_active"] == 0


def test_sin_ninguna_cuenta_activa_NO_se_elige_cualquiera(tmp_path):
    """Un dashboard que no sabe qué cuenta mostrar no debe mostrar una al azar.

    Es la misma política que `refresh_dashboard`: se devuelve el motivo, no un payload
    sobre una cuenta elegida por descarte.
    """
    ruta = _db_cruda(tmp_path, [(1, False), (2, False)])
    payload = build_payload(ruta)

    assert "error" in payload
    assert "activa" in payload["error"]


def test_una_base_SIN_la_tabla_no_revienta(tmp_path):
    """DB sintética o de otra cosa: devuelve el motivo, no un traceback."""
    ruta = tmp_path / "vacia.db"
    sqlite3.connect(ruta).close()

    con = sqlite3.connect(ruta)
    try:
        assert _live_account_id(con) is None
    finally:
        con.close()
    assert "error" in build_payload(ruta)


# ── El entry point de verdad, que es como se descubrió ───────────────────────


def test_el_CLI_corrido_como_PROCESO_resuelve_sin_account(tmp_path):
    """Se ejecuta el script de verdad, desde **fuera** del repo y como subproceso.

    El defecto apareció así y no leyendo: corriendo el script desde otro directorio, que
    es la regla del repo tras tocar imports en ``scripts/``. Un test que sólo llamara a
    ``build_payload`` no habría visto nunca el ``main()``, que era donde estaba el bug.
    """
    ruta = _db_cruda(tmp_path, [(1, False), (7, True)])
    r = subprocess.run(
        [sys.executable, str(_REPO / "scripts" / "dashboard_data.py"), "--db", str(ruta)],
        cwd=tmp_path,  # FUERA del repo
        capture_output=True,
        text=True,
    )

    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert "error" not in payload, payload.get("error")
    assert payload["account"]["id"] == 7


def test_el_help_ya_no_promete_la_cuenta_1(tmp_path):
    """El `--help` decía *«default: 1»* mientras la constante decía otra cosa.

    Las tres afirmaciones —help, constante y comportamiento— tienen que decir lo mismo,
    y el help es la única que el usuario lee.
    """
    r = subprocess.run(
        [sys.executable, str(_REPO / "scripts" / "dashboard_data.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert r.returncode == 0, r.stderr
    assert "default: 1" not in r.stdout
    assert "VIVA" in r.stdout or "viva" in r.stdout
