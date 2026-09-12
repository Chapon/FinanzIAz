"""Tarea 189 — que se pueda contestar *«¿sobre qué muestra se validó este veredicto?»*.

**El defecto.** El 2026-09-10 se re-corrieron nueve runners sobre el cohorte refrescado y la
evidencia quedó repartida así: **dos** en un doc propio, **cinco en una sola línea** de la
entrada 164 de `docs/BACKLOG.md`, y **uno en una fila de tabla** de un doc que se llama por
otra tarea. El resultado de una re-corrida post-refresh es exactamente el dato que la próxima
auditoría —o el próximo pre-registro— necesita para saber si puede apoyarse en un veredicto, y
**no era buscable**.

**El costo está demostrado y el caso fue una auditoría de este repo.** La corrida de `muestra`
del 2026-09-11 midió la cobertura con `ls docs/*2026-09-09* docs/*2026-09-10*` —o sea **por
nombre de archivo**— y publicó tres veredictos como *«nadie los re-chequeó»* cuando **dos de
los tres sí lo habían sido**. Es la forma de las tareas 173/150/176/177/179/181: **la
referencia del chequeo no podía ver el objeto que buscaba**, esta vez cometida por el proceso
que existe para cazarla.

**La población se descubre por DOS mecanismos, no por una lista.** Un refresh puede invalidar
un veredicto por dos vías distintas, y cada una tiene su marca en el código:

1. **el ancla de reproducción** — el runner llama a `reproduction_check(..., measured_on=WINDOW_*)`,
   o sea que su número está pinneado a una ventana;
2. **el umbral de sanity de clase `magnitud`** — se compara contra **pp de CAGR/maxDD**, así que
   pierde resolución cuando la muestra tiene menos alpha (tarea 164).

La unión de las dos es la población. Un runner nuevo con cualquiera de las dos marcas **no
puede nacer sin fila** en `docs/VALIDEZ_VEREDICTOS.md`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.test_sanity_no_anclado_t164 import INVENTARIO, MAGNITUD

_REPO = Path(__file__).resolve().parent.parent
_TABLA = _REPO / "docs" / "VALIDEZ_VEREDICTOS.md"


def runners_con_veredicto_anclado() -> dict[str, set[str]]:
    """``{runner: {mecanismos}}`` — la población, descubierta por las dos marcas."""
    out: dict[str, set[str]] = {}
    for p in sorted((_REPO / "scripts").glob("run_*.py")):
        src = p.read_text(encoding="utf-8")
        if re.search(r"measured_on=WINDOW_\w+", src):
            out.setdefault(p.name, set()).add("ancla_de_reproduccion")
    for clave, clase in INVENTARIO.items():
        if clase == MAGNITUD:
            runner = clave.split(":", 1)[0]
            out.setdefault(runner, set()).add("sanity_magnitud")
    return out


def filas_de_la_tabla() -> dict[str, str]:
    """``{runner: fila completa}`` de `docs/VALIDEZ_VEREDICTOS.md`."""
    texto = _TABLA.read_text(encoding="utf-8")
    return {m.group(1): m.group(0) for m in re.finditer(r"^\| `(run_\w+\.py)` \|.*$", texto, re.M)}


# ── La población, y su contraprueba ─────────────────────────────────────────


def test_la_poblacion_se_descubre_por_LOS_DOS_mecanismos():
    """Contraprueba: si uno de los dos barridos se rompiera, el test de abajo pasaría con la
    mitad de la población y "demostraría" que la tabla está completa."""
    pob = runners_con_veredicto_anclado()
    por_ancla = {r for r, m in pob.items() if "ancla_de_reproduccion" in m}
    por_sanity = {r for r, m in pob.items() if "sanity_magnitud" in m}
    assert len(por_ancla) >= 8, f"el barrido de anclas vio {len(por_ancla)} runners"
    assert len(por_sanity) >= 8, f"el barrido de sanity vio {len(por_sanity)} runners"
    # y que los dos aporten runners que el otro no tiene, o sea que la unión sirve de algo
    assert por_ancla - por_sanity, "el barrido de anclas no aporta nada sobre el de sanity"
    assert por_sanity - por_ancla, "el barrido de sanity no aporta nada sobre el de anclas"


# ── El invariante de la tarea ───────────────────────────────────────────────


def test_TODO_veredicto_anclado_tiene_su_FILA():
    """**El invariante.** Dado un veredicto publicado, la pregunta *«¿sobre qué muestra se
    validó?»* tiene que tener respuesta en un solo lugar."""
    faltan = sorted(set(runners_con_veredicto_anclado()) - set(filas_de_la_tabla()))
    assert not faltan, (
        "estos runners tienen su veredicto anclado a una muestra y no tienen fila en "
        "`docs/VALIDEZ_VEREDICTOS.md` (tarea 189):\n  " + "\n  ".join(faltan)
    )


def test_no_hay_filas_FANTASMA():
    """Una fila para un runner que ya no existe envejece peor que no tenerla: da la impresión
    de que la tabla está cuidada. Mismo criterio que el guard de la 152."""
    fantasmas = sorted(r for r in filas_de_la_tabla() if not (_REPO / "scripts" / r).exists())
    assert not fantasmas, f"filas para runners que no existen: {fantasmas}"


@pytest.mark.parametrize("runner", sorted(filas_de_la_tabla()))
def test_cada_fila_dice_SOBRE_QUE_MUESTRA_y_donde_esta_la_evidencia(runner):
    """Las dos columnas que hacen útil a la tabla. Una fila sin muestra o sin evidencia es la
    apariencia de trazabilidad sin la trazabilidad."""
    celdas = [c.strip() for c in filas_de_la_tabla()[runner].strip("|").split("|")]
    assert len(celdas) == 6, f"{runner}: la fila no tiene las 6 columnas — {celdas}"
    _, _, _, ultima, muestra, evidencia = celdas
    assert ultima, f"{runner}: sin «última validación»"
    assert muestra, f"{runner}: sin «sobre qué muestra»"
    assert evidencia, f"{runner}: sin evidencia"


@pytest.mark.parametrize("runner", sorted(filas_de_la_tabla()))
def test_la_evidencia_de_cada_fila_EXISTE(runner):
    """**La condición que separa esta tabla de una lista de buenas intenciones.** Una referencia
    a un doc que no existe es peor que ninguna: manda a buscar y no está. Se acepta `BACKLOG.md`
    como evidencia —ahí vive la mitad de la evidencia operativa de este repo— y también la
    referencia a una tarea, que el guard del backlog ya verifica que exista."""
    evidencia = filas_de_la_tabla()[runner].strip("|").split("|")[-1].strip()
    rutas = re.findall(r"`(docs/[\w./-]+\.md)`", evidencia)
    if not rutas:
        assert re.search(r"tarea \*\*\d+\*\*", evidencia), (
            f"{runner}: la evidencia no nombra ni un doc ni una tarea — {evidencia!r}"
        )
        return
    for ruta in rutas:
        assert (_REPO / ruta).exists(), f"{runner}: la evidencia apunta a {ruta}, que no existe"


# ── El caso que motivó la tarea, fijado ─────────────────────────────────────


def test_los_re_corridos_del_2026_09_10_estan_TODOS():
    """El conjunto concreto cuya dispersión costó el error de la auditoría. Si alguno se cae de
    la tabla, el próximo barrido por nombre de archivo vuelve a no verlo."""
    filas = filas_de_la_tabla()
    for runner in (
        "run_stop_value_t37.py",
        "run_stop_price_redecide_t47.py",
        "run_stop_loosen_t34.py",
        "run_stop_price_replay_t26b.py",
        "run_rank_neutral_t39.py",
        "run_anom_profile_t45.py",
        "run_prio_event_t49.py",
    ):
        assert runner in filas, f"{runner} salió de la tabla"
        assert "2026-09-10" in filas[runner], f"{runner}: su fila no fecha la re-corrida"


def test_el_unico_sin_re_correr_esta_DECLARADO_como_tal():
    """El T21 es el único que el refresh dejó sin re-validar, y la tabla no puede disimularlo:
    su fila tiene que decirlo y apuntar a la tarea que lo sostiene (183)."""
    fila = filas_de_la_tabla()["run_ranking_t21.py"]
    assert "NO RE-CORRIDO" in fila, "la fila del T21 dejó de declarar que no se re-corrió"
    assert "183" in fila, "la fila del T21 no apunta a la tarea que lo declara"
