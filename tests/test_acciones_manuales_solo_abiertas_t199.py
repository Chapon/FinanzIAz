"""Tarea 199 — *Acciones manuales pendientes* guarda sólo lo que está abierto.

Al cerrar una acción manual se la tachaba **en el lugar**. El 2026-09-13 la sección tenía
**17 cerradas de 20** —lo que Chapa tenía que hacer, enterrado entre lo hecho— y puso en rojo
la cota de tamaño de la 138 **sin que el ancla se hubiera movido**. Subir la cota era el
arreglo equivocado: existe para cazar un ancla corrida. Lo que se hizo fue mover las cerradas
a *Acciones manuales resueltas*, con su texto completo, y dejar la regla escrita arriba de la
sección.

**Qué chequea este archivo:** que ningún ítem de *pendientes* tenga la marca de cerrado. La
marca no es una lista inventada: es **la que usan los 18 ítems que se movieron**, y la
contraprueba lo verifica sobre esa población en las dos direcciones —las 18 resueltas se
reconocen como cerradas y las abiertas no—. Si alguien cierra una acción con una marca
nueva, la contraprueba no se entera; eso va dicho.
"""

from __future__ import annotations

import re
from pathlib import Path

_BACKLOG = Path(__file__).resolve().parent.parent / "docs" / "BACKLOG.md"

# Las formas en que el archivo marca una acción como cerrada: el título tachado, o un estado
# en negrita / con tilde verde al principio del ítem.
_TACHADO = re.compile(r"^- (?:\*\*)?~~")
_ESTADO = re.compile(r"\*\*(?:HECHO|HECHA|DECIDIDO|RETIRADA)\b|✅ (?:RESUELTO|ACTIVADO)|— RETIRADA\b")


def _seccion(titulo: str) -> str:
    txt = _BACKLOG.read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(titulo)}.*$", txt, re.M)
    assert m, f"falta la sección '## {titulo}'"
    fin = txt.find("\n## ", m.end())
    return txt[m.end() : fin if fin != -1 else len(txt)]


def _items(seccion: str) -> list[str]:
    return [ln for ln in seccion.split("\n") if ln.startswith("- ")]


def esta_cerrada(item: str) -> bool:
    return bool(_TACHADO.match(item) or _ESTADO.search(item[:300]))


def test_pendientes_no_tiene_ninguna_accion_CERRADA():
    cerradas = [it[:120] for it in _items(_seccion("Acciones manuales pendientes")) if esta_cerrada(it)]
    assert not cerradas, (
        "hay acciones cerradas en *Acciones manuales pendientes*: al cerrar una se MUEVE a "
        "*Acciones manuales resueltas*, no se tacha en el lugar (tarea 199):\n  " + "\n  ".join(cerradas)
    )


def test_pendientes_no_quedo_vacia_de_items():
    """Si esto falla porque de verdad no queda nada que hacer, está bien: la sección lo tiene
    que decir con un ítem, porque el guard de la 66 no acepta una sección vacía."""
    assert _items(_seccion("Acciones manuales pendientes"))


def test_la_marca_reconoce_a_TODAS_las_resueltas():
    """Contraprueba sobre la población real: si una resuelta no se reconociera como cerrada,
    el test de arriba dejaría pasar su gemela en *pendientes*."""
    resueltas = _items(_seccion("Acciones manuales resueltas"))
    assert len(resueltas) >= 18
    no_reconocidas = [it[:120] for it in resueltas if not esta_cerrada(it)]
    assert not no_reconocidas, no_reconocidas


def test_cada_marca_alcanza_SOLA():
    """En la población real todas las cerradas llevan tachado Y estado, así que la
    contraprueba de arriba no distingue si alguna de las dos marcas dejó de funcionar."""
    assert esta_cerrada("- ~~**Algo que se hizo.**~~ Y el detalle.")
    assert esta_cerrada("- **~~Algo retirado~~ — ya no hace falta.**")
    assert esta_cerrada("- **Algo.** **HECHO 2026-09-13.** Detalle.")
    assert esta_cerrada("- **Algo (2026-07-12): ✅ RESUELTO + VERIFICADO.**")


def test_la_marca_no_acusa_a_las_ABIERTAS():
    """La otra dirección: un ítem abierto que mencione un paso cumplido adentro de su texto
    (el caso de OPS1, con sus ✅ por paso) no es una acción cerrada."""
    abiertas = _items(_seccion("Acciones manuales pendientes"))
    assert not [it for it in abiertas if esta_cerrada(it)]
    assert not esta_cerrada("- **Algo abierto.** El paso (1) quedó ✅ hecho, falta el (2).")


def test_la_regla_esta_escrita_arriba_de_la_seccion():
    assert "se **mueve** a *Acciones manuales resueltas*" in _seccion("Acciones manuales pendientes")
