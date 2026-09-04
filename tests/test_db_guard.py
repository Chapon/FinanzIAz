"""Valida la red de seguridad autouse que aísla la ``finanzias.db`` real (B4).

El 2026-06-25 ``test_historical_batch`` escribió frames sintéticos en la DB de
producción (no usaba ``test_db``) y rompió AAPL/MSFT 1y en la pestaña Análisis.
El fixture autouse ``_guard_real_db`` (en ``conftest.py``) previene toda la
clase de bug rebindeando ``ENGINE`` a una SQLite in-memory. Estos tests fallan
si ese guard se rompe o se elimina.

**La segunda mitad, agregada en la 108.** El rebind aísla **este proceso**, y eso
dejaba afuera a los tests que abren un **subproceso**: el hijo importa
``database.models`` sin pasar por el conftest, se queda con la ruta de producción y
toca la DB real. No es hipotético — el escenario de la 82 lo hacía, y en un checkout
limpio dejaba una ``finanzias.db`` vacía en la raíz del repo que tuvo el job
``pytest`` del CI **rojo 12 corridas** (tarea 107). Esa mitad la cubre
``FINANZIAS_DB_PATH``, y los tres tests de abajo son los que la fijan.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from data import yahoo_finance as yf_mod
from database.models import session_scope

_REPO = Path(__file__).resolve().parent.parent
_DB_REAL = _REPO / "finanzias.db"


def _en_subproceso(codigo: str, env: dict[str, str] | None = None) -> str:
    """Corre ``codigo`` en un intérprete limpio y devuelve su stdout pelado.

    Un subproceso de verdad y no un ``monkeypatch``: lo que se está probando es
    justamente lo que **no** viaja al hijo.
    """
    src = f"import sys; sys.path.insert(0, {str(_REPO)!r})\n" + codigo
    out = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, timeout=120, env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def _huella(p: Path) -> tuple[int, int] | None:
    """Tamaño y mtime, o ``None`` si no existe. Sirve para las dos máquinas: en CI
    el archivo no está y no tiene que aparecer; acá está y no se puede mover."""
    if not p.exists():
        return None
    st = p.stat()
    return (st.st_size, st.st_mtime_ns)


def test_engine_is_isolated_in_memory():
    """Sin ``test_db`` ni ``@real_db``, ``ENGINE`` apunta a una in-memory."""
    from database import models as db_models

    assert db_models.ENGINE.url.database == ":memory:", (
        f"ENGINE no aislado por el guard: {db_models.ENGINE.url}"
    )


def test_cache_write_lands_in_isolated_db():
    """Un write por la ruta real de cache cae en la in-memory del test, no en
    producción — exactamente lo que faltaba el 2026-06-25."""
    df = pd.DataFrame(
        {"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [1_000_000]},
        index=pd.to_datetime(["2026-01-01"]),
    )
    yf_mod._write_historical_cache("ZZZZGUARD", "1y", "1d", df)

    with session_scope() as s:
        n = s.execute(
            text("SELECT COUNT(*) FROM historical_data_cache WHERE ticker = :t"),
            {"t": "ZZZZGUARD"},
        ).scalar()
    assert n == 1  # quedó en la DB aislada; la suite no toca finanzias.db


# ── El aislamiento que el rebind no alcanza: los subprocesos (tarea 108) ─────


def test_DB_PATH_respeta_el_override_del_entorno(tmp_path):
    """La pieza de abajo: ``database.models`` lee ``FINANZIAS_DB_PATH`` al importarse."""
    destino = tmp_path / "otra.db"
    salida = _en_subproceso(
        "from database.models import DB_PATH; print(DB_PATH)",
        env={**os.environ, "FINANZIAS_DB_PATH": str(destino)},
    )
    assert Path(salida) == destino


def test_una_ruta_VACIA_cae_al_default_y_no_a_la_cadena_vacia():
    """El borde exacto que se arregló en la 82 con `FINANZIAS_DISABLE_TICKER_FETCH=0`:
    leer la variable sin cuidado convierte un valor vacío en un valor. Una ruta vacía
    no significa nada útil —siempre hace falta una DB— así que cae al default."""
    salida = _en_subproceso(
        "from database.models import DB_PATH; print(DB_PATH)",
        env={**os.environ, "FINANZIAS_DB_PATH": ""},
    )
    assert Path(salida) == _DB_REAL


def test_un_subproceso_de_la_suite_NO_toca_la_db_real(tmp_path):
    """**EL GUARD.** Un hijo que *conecta de verdad* —el camino de la 82— cae en la DB
    de la sesión y deja la de producción intacta.

    Mira los dos lados a propósito. Sólo con *«la real no se movió»* el test pasaría
    también si el subproceso no hubiera hecho nada, que es como se pierde un guard sin
    que nadie se entere; el ``assert`` sobre la aislada es el control positivo.
    """
    destino = tmp_path / "aislada.db"
    antes = _huella(_DB_REAL)
    _en_subproceso(
        # Un ``with`` vacío NO alcanza: la sesión es perezosa y sin query no abre
        # conexión, así que el archivo no aparece y el test "pasaría" por no probar
        # nada. Hace falta una query real, que es lo que hace ``_ensure_db_loaded``
        # del tooltip — el camino exacto de la 82.
        "from sqlalchemy import text\n"
        "from database.models import session_scope\n"
        "with session_scope() as s: s.execute(text('SELECT 1'))\n"
        "print('ok')",
        env={**os.environ, "FINANZIAS_DB_PATH": str(destino)},
    )
    assert destino.exists(), "el subproceso no conectó a la DB aislada"
    assert _huella(_DB_REAL) == antes, "el subproceso tocó la finanzias.db de producción"
