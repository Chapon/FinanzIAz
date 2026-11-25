"""Tarea 466 — la re-lectura de la 456 con la tajada por día no puede leer el cache viejo.

La 456 se publicó con el sizing secuencial de ``simulate_portfolio`` (cada compra escalada del día
agrandaba a la siguiente; tarea 464). La re-lectura corre el mismo runner con
``--tajada-del-dia``. El riesgo concreto es el cache: ``SimCache`` guarda cada brazo por su tag, y
si el tag no cambiara con el modo, la re-lectura leería los brazos secuenciales y los publicaría
como corregidos, con todos los números «reproducidos» y sin que nada lo acuse.
"""

from __future__ import annotations

import pytest

from analysis.harness_config import LIVE_REGIME_SCALE_FACTOR
from scripts import run_activo_pasivo_t456 as r

_RUN_TAG = "2016-09-12..2026-09-09|n126|e141417|mp10|cap250|$50000.00"


def test_sin_la_opcion_los_tags_son_los_publicados():
    """Así la 456 sigue reproduciendo desde su cache, como se publicó."""
    assert r.tags_de_corrida(_RUN_TAG, False) == (
        f"t456|{r.VIVO_SIN_REGIMEN}|{_RUN_TAG}",
        f"t456|{r.VIVO}|f{LIVE_REGIME_SCALE_FACTOR}|{_RUN_TAG}",
    )


def test_con_la_opcion_los_dos_tags_cambian():
    viejos = r.tags_de_corrida(_RUN_TAG, False)
    nuevos = r.tags_de_corrida(_RUN_TAG, True)
    assert all(n != v for n, v in zip(nuevos, viejos, strict=True)), (viejos, nuevos)
    assert len(set(nuevos) | set(viejos)) == 4


def test_la_opcion_existe(capsys):
    with pytest.raises(SystemExit):
        r.main(["--help"])
    assert "--tajada-del-dia" in capsys.readouterr().out
