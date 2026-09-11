"""Tarea 163 — un ancla de ventana no puede tener una fecha en el nombre.

**El defecto.** Las dos constantes de ventana se llamaban
``WINDOW_REFRESH_2026_09_01_LIVE`` / ``_LEGACY``, y la tarea **157** les re-ancló el valor
a la ventana del **2026-09-09** —la LIVE pasó de ``2016-08-08..2026-09-01 (2514)`` a
``2016-09-12..2026-09-09 (2512)``, la LEGACY de ``(2513)`` a
``2016-09-01..2026-09-09 (2518)``— y **dejó los nombres**. El símbolo afirmaba una fecha y
su valor otra.

**Era latente, no activo,** y eso es lo que lo hacía fácil de dejar pasar: los runners
importan el **símbolo**, no la fecha, así que ninguna corrida estaba midiendo mal. Muerde
cuando alguien **lee el nombre** para decidir si su ancla es la del refresh que le toca —
que es exactamente lo que hay que hacer después de cada refresh.

**Y en este repo el nombre de un ancla no es decorativo.** El ancla anterior
(``WINDOW_REFRESH_2026_08_09``) no existe ni como alias, **a propósito**, con un test que
lo prohíbe en ``scripts/run_*.py`` porque *«dejarlo habría permitido elegir mal en
silencio»*. El mismo argumento aplica al revés.

**La salida elegida, entre las dos que la tarea planteaba:** sacarle la fecha al nombre
(``WINDOW_LIVE`` / ``WINDOW_LEGACY``) en vez de renombrar en cada re-anclaje. Elimina la
**clase entera** en lugar de depender de que alguien se acuerde: la fecha vive en el
``ArtifactWindow``, el único lugar donde no puede desincronizarse, y el eje que el nombre
sí distingue —el **universo**— se conserva. Lo único que se pierde es la señal de *«esto
se re-ancló»* al leer un diff, y no se pierde de verdad: el diff del **valor** la trae.

**Lo que este archivo NO cubre, dicho:** que el valor sea el correcto. De eso se ocupa el
re-anclaje (tareas 68 y 157) y el guard de frescura del cohorte. Acá sólo se sostiene que
el **nombre** no pueda volver a afirmar una fecha.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import analysis.harness_config as hc
from analysis.harness_config import ArtifactWindow

_REPO = Path(__file__).resolve().parent.parent

# Los nombres que ya se retiraron, cada uno con la tarea que lo hizo. Ninguno puede volver
# —ni como alias— por el mismo motivo que la 68 no dejó el primero: un alias deja pasar la
# elección equivocada en silencio.
_NOMBRES_RETIRADOS: dict[str, str] = {
    "WINDOW_REFRESH_2026_08_09": "tarea 68 — se partió en LIVE/LEGACY, sin alias a propósito",
    "WINDOW_REFRESH_2026_09_01_LIVE": "tarea 163 — la fecha del nombre mentía tras el re-anclaje de la 157",
    "WINDOW_REFRESH_2026_09_01_LEGACY": (
        "tarea 163 — mismo defecto que su par LIVE: la 157 le movió el valor de (2513) a "
        "2016-09-01..2026-09-09 (2518) y el nombre siguió diciendo 09_01"
    ),
}

# Una fecha embutida en un nombre de símbolo: `2026_09_01`, `20260901`, `2026-09-01`.
_FECHA_EN_NOMBRE = re.compile(r"(?:19|20)\d{2}[-_]?(?:0[1-9]|1[0-2])[-_]?(?:0[1-9]|[12]\d|3[01])")


def _anclas_de_ventana() -> dict[str, ArtifactWindow]:
    """Las anclas **descubiertas**, no enumeradas: todo `ArtifactWindow` del módulo.

    La población sale del tipo y no de una lista, así que un ancla nueva no puede nacer
    invisible a este guard — el defecto de la 133, la 141 y la 147.
    """
    return {n: v for n, v in vars(hc).items() if isinstance(v, ArtifactWindow)}


def test_hay_anclas_para_barrer():
    """Contraprueba de población: sin esto, un cambio de tipo o de módulo dejaría todos los
    tests de abajo pasando **por vacío** y "demostrando" que no hay fechas en los nombres."""
    anclas = _anclas_de_ventana()
    assert len(anclas) >= 2, f"el barrido encontró {len(anclas)} anclas: {sorted(anclas)}"
    assert {"WINDOW_LIVE", "WINDOW_LEGACY"} <= set(anclas)


def test_NINGUN_ancla_de_ventana_tiene_fecha_en_el_nombre():
    """**El invariante de la tarea.** La fecha va en el valor, no en el nombre."""
    con_fecha = {n: str(v) for n, v in _anclas_de_ventana().items() if _FECHA_EN_NOMBRE.search(n)}
    assert not con_fecha, (
        "estas anclas llevan una fecha en el nombre, y el nombre se desincroniza del valor "
        "en el próximo re-anclaje (tarea 163):\n  "
        + "\n  ".join(f"{n} = {v}" for n, v in sorted(con_fecha.items()))
    )


def test_el_valor_SI_lleva_la_fecha():
    """La otra mitad, y no es redundante: sacarle la fecha al nombre sólo sirve si el valor
    la tiene. Si alguien dejara la ventana sin fechas, el test de arriba pasaría igual y la
    información se habría **perdido** en vez de moverse."""
    for nombre, ancla in _anclas_de_ventana().items():
        assert _FECHA_EN_NOMBRE.search(str(ancla.start)), f"{nombre} no declara un start con fecha"
        assert _FECHA_EN_NOMBRE.search(str(ancla.end)), f"{nombre} no declara un end con fecha"


@pytest.mark.parametrize("viejo", sorted(_NOMBRES_RETIRADOS))
def test_los_nombres_retirados_NO_estan_definidos(viejo):
    """Ni como alias. Un alias que apunte al ancla nueva compila, corre y deja al runner
    diciendo que midió sobre un refresh que no es el suyo."""
    assert not hasattr(hc, viejo), f"{viejo} volvió a existir ({_NOMBRES_RETIRADOS[viejo]})"


@pytest.mark.parametrize("viejo", sorted(_NOMBRES_RETIRADOS))
def test_ningun_runner_importa_un_nombre_retirado(viejo):
    """Extiende a los dos nombres de la 163 el guard que la 68 escribió para el primero.
    Un runner que los nombre no arranca —`ImportError`— pero el mensaje no dice *por qué*,
    y este test sí."""
    culpables = [
        p.name for p in sorted((_REPO / "scripts").glob("run_*.py")) if viejo in p.read_text(encoding="utf-8")
    ]
    assert not culpables, f"{viejo} ({_NOMBRES_RETIRADOS[viejo]}) aparece en: {culpables}"


def test_cada_nombre_retirado_dice_POR_QUE_se_retiro():
    """Un nombre prohibido sin motivo escrito es una lista de conveniencia: el próximo que
    lea esto no puede saber si sigue teniendo sentido."""
    for viejo, motivo in _NOMBRES_RETIRADOS.items():
        assert "tarea" in motivo and len(motivo) > 30, f"{viejo} sin motivo trazado"
