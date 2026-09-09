"""Tarea 138 (CLAIMS-QUE-ENVEJECEN) — una edad se escribe como fecha, no como conteo.

*Acciones manuales pendientes* decía que la cuenta 1 tiene *«sus 5 slots ocupados por
posiciones abiertas entre el 16/06 y el 01/07 (SBUX, LRCX, MO, KO, CL; **30–41
ruedas**)»*. Contra la DB al 2026-09-08 eran **49–60**. Los tickers y las fechas
estaban bien; **sólo la edad caducó**, y caducaba de nuevo al día siguiente.

**Es una clase distinta de claim, y por eso vale un guard propio.** No se rompió porque
alguien cambiara algo: **se rompe sola con el paso del tiempo**. Ningún barrido
disparado por *«se movió una constante»* la va a agarrar nunca, porque no se movió
ninguna constante. Los guards de las tareas 130, 135 y 137 son todos de esa familia y
**ninguno** la habría visto.

**El arreglo no era actualizar el número.** La nota **ya traía las fechas**, que no
caducan, así que el conteo de ruedas era redundante **y** decadente: actualizarlo es
plantar el mismo defecto con otro número. Se borró y quedaron las fechas.

**Dónde está es lo que le da peso.** *Acciones manuales pendientes* es la sección que
el paso 4 de `/ship` marca como la más peligrosa, porque *«afirman en presente y encima
son las que Chapa ejecuta a mano»*. Una edad equivocada ahí no es un error de
documentación: es una premisa falsa en algo que se va a ejecutar.

**Por qué el guard es de esa sección y no del archivo entero.** El barrido sobre todo
el corpus da decenas de *«N ruedas»* y casi todos son legítimos: parámetros (*«una
entrada cada 20 ruedas»*), mediciones fijas (*«tenencia máxima 37»*) o **edades
fechadas dentro de un registro histórico** (*«46 ruedas atrás del cohorte
(2026-09-03)»*). Ésas no envejecen porque están ancladas. Lo que envejece es una edad
**en una sección que afirma el presente**, y ahí el guard puede ser estricto sin
acusar a nadie que esté bien.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_BACKLOG = Path(__file__).resolve().parent.parent / "docs" / "BACKLOG.md"

# Formas en que se escribe una edad: un conteo que se mide *hasta ahora*.
#
# ``_SEP`` en vez de ``\s+`` **porque la contraprueba lo pidió**: el corpus escribe
# ``**46 ruedas** atrás``, y con un separador de sólo espacios el patrón se parte contra
# el énfasis de markdown y **no matchea nada**. Un guard de texto sobre markdown que
# ignore el markdown está midiendo otro idioma.
_SEP = r"[\s*_]+"
_EDADES = {
    "rango de ruedas": rf"\b\d+\s*[–-]\s*\d+{_SEP}ruedas\b",
    "N ruedas atrás": rf"\b\d+{_SEP}ruedas{_SEP}atr[áa]s\b",
    "hace N días": rf"\bhace{_SEP}~?\d+{_SEP}d[ií]as?\b",
    "hace N semanas": rf"\bhace{_SEP}~?\d+{_SEP}semanas?\b",
    "lleva N días": rf"\blleva{_SEP}~?\d+{_SEP}(?:d[ií]as?|ruedas|semanas?)\b",
    "N días sin": rf"\b\d+{_SEP}d[ií]as{_SEP}sin\b",
}


def _seccion_acciones_manuales() -> str:
    """El texto de *Acciones manuales pendientes*, la sección que afirma el presente.

    **El ancla es el encabezado, no la frase, y lo aprendí fallando.** La primera
    versión buscaba ``txt.index("## Acciones manuales pendientes")`` y agarraba la
    primera **mención** —que está adentro de un WIP de *En curso*— así que la "sección"
    salía de **79.374 caracteres**: medio backlog, con todo *Hecho reciente* adentro.
    El guard habría acusado cada edad fechada de cada registro histórico.

    Lo cazó la contraprueba, no el guard: ``len(seccion) > 500`` pasaba **de sobra**
    justamente porque el error hacía la sección más grande, no más chica. Es la lección
    de [[validar-el-instrumento-antes-del-numero]] en su forma más barata.
    """
    txt = _BACKLOG.read_text(encoding="utf-8")
    m = re.search(r"^## Acciones manuales pendientes.*$", txt, re.M)
    assert m, "la sección *Acciones manuales pendientes* desapareció del backlog"
    fin = txt.find("\n## ", m.end())
    return txt[m.start() : fin if fin != -1 else len(txt)]


def test_la_seccion_esta_bien_ACOTADA():
    """Contraprueba con **cota superior**, que es la que faltaba.

    Un piso (*«tiene más de 500 caracteres»*) sólo caza que la sección se vacíe. El
    error real fue el opuesto: la sección salía **enorme** porque el ancla estaba mal, y
    con eso el guard habría corrido sobre medio backlog. Las dos cotas, entonces.
    """
    seccion = _seccion_acciones_manuales()
    assert seccion.startswith("## Acciones manuales pendientes")
    assert 500 < len(seccion) < 20_000, f"la sección mide {len(seccion)} — el ancla se movió"
    assert "## Próximo" not in seccion and "## Hecho reciente" not in seccion


@pytest.mark.parametrize("nombre,patron", list(_EDADES.items()), ids=list(_EDADES))
def test_las_acciones_manuales_no_expresan_una_EDAD_como_conteo(nombre, patron):
    """**El guard de la clase.** Una edad escrita como número se rompe sola.

    Si esto se pone rojo, el arreglo casi nunca es actualizar el número: es
    **reemplazarlo por la fecha**, que dice lo mismo y no caduca.
    """
    hits = [m.group(0) for m in re.finditer(patron, _seccion_acciones_manuales(), re.IGNORECASE)]
    assert not hits, (
        f"*Acciones manuales pendientes* expresa una edad como conteo ({nombre}): {hits}. "
        "Escribila como **fecha** — la edad se recalcula sola y el número no (tarea 138)."
    )


def test_los_patrones_reconocen_una_edad_de_verdad():
    """Contraprueba del instrumento: sin esto, los de arriba podrían pasar por no
    matchear nada nunca."""
    ejemplos = {
        "rango de ruedas": "las posiciones tienen 30–41 ruedas",
        "N ruedas atrás": "el cohorte está 71 ruedas atrás",
        "hace N días": "AVB está invisible hace 4 días",
        "hace N semanas": "el scan no corre hace 6 semanas",
        "lleva N días": "lleva 21 días sin refrescar",
        "N días sin": "van 16 días sin acumular datos",
    }
    for nombre, patron in _EDADES.items():
        assert re.search(patron, ejemplos[nombre], re.IGNORECASE), f"{nombre} no reconoce su ejemplo"


def test_una_edad_FECHADA_en_un_registro_historico_no_se_acusa():
    """El falso positivo que hay que evitar, y la razón de acotar la sección.

    *«46 ruedas atrás del cohorte (2026-09-03)»* es una medición **anclada a una
    fecha**: no envejece, porque no afirma nada sobre hoy. El backlog está lleno de
    ésas en *Hecho reciente* y en los WIP, y todas están bien.
    """
    historico = "el `2y` quedó congelado el 2026-07-12 — **46 ruedas** atrás del cohorte (2026-09-03)."
    assert re.search(_EDADES["N ruedas atrás"], historico, re.IGNORECASE), (
        "el patrón sí matchea el texto histórico, y por eso el guard NO puede correr "
        "sobre el archivo entero: correría sobre registros que están bien"
    )
    # Y la prueba de que el recorte es real: ese texto está en el backlog y **no** en la
    # sección que se audita.
    assert "46 ruedas" in _BACKLOG.read_text(encoding="utf-8")
    assert "46 ruedas" not in _seccion_acciones_manuales()
