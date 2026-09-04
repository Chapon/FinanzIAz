"""NUM-STALE (tarea 43) — una magnitud supersedida no se puede citar pelada.

El caso real
------------
El **~8 pp de CAGR** de la T9 (*"un AUC de 0.498 no se comporta como el azar"*) se
midió a **5 slots, 41 tickers, fill legacy, sin gates** y contra el orden
**alfabético** — que la T21 después mostró que **no era un baseline neutro**: ganó
por suerte, +3.10 pp sobre la mediana de las semillas. La T39 re-midió el mismo eje
con la config honesta: **+1.80 pp, IC95% [−3.88, +7.61], p=0.282**, y +0.10 pp a 5
slots. Entre cuatro y ochenta veces menos, y no significativo.

Y el número seguía citado **cuatro veces** en el backlog como el argumento por el que
la selección era prioritaria — o sea que **movía el orden de la fila**.

Por qué es un guard y no un barrido
-----------------------------------
Un barrido arregla las cuatro citas de hoy. El defecto es que **la quinta se escribe
igual**: quien reordene el backlog el mes que viene va a leer el número grande, que
es más contundente, y no la nota de corrección que vive en otro archivo. El guard
obliga a que la cifra viaje **con su contexto**, que es lo único que impide que una
magnitud caducada siga decidiendo.

Es el mismo patrón con el que la 72 convirtió un checklist en test.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BACKLOG = _REPO / "docs" / "BACKLOG.md"
_DOC_T9 = _REPO / "docs" / "meta_labeling_t9_2026-07-21.md"

_MARCA = "MAGNITUD CADUCADA"

# {patrón de la cifra supersedida: por qué caducó}. Agregar una es una línea, y el
# motivo va escrito porque una entrada sin motivo no se puede auditar después.
_CIFRAS_SUPERSEDIDAS = {
    r"~?8 (?:pp|puntos) de CAGR": (
        "el ~8 pp de la T9 §13.6: medido a 5 slots/41 tickers/fill legacy/sin gates y "
        "contra un alfabético que no era neutro. La T39 lo re-midió en +1.80 pp "
        "no significativo (tarea 43)."
    ),
}


def _lineas_del_enunciado_de_la_43() -> set[int]:
    """La tarea 43 **describe** la cifra caducada; no la cita como argumento.

    Sin esta excepción el guard se acusaría a sí mismo — y taparla con la marca
    dentro del propio enunciado haría el texto ilegible."""
    texto = _BACKLOG.read_text(encoding="utf-8")
    i = texto.index("### 43. ")
    j = texto.index("\n### ", i + 10)
    desde = texto[:i].count("\n")
    hasta = texto[:j].count("\n")
    return set(range(desde, hasta + 1))


def test_ninguna_cita_de_la_cifra_caducada_viaja_sin_su_contexto():
    """**EL GUARD.** Cada línea del backlog que nombre la magnitud supersedida tiene
    que llevar la marca al lado. No se prohíbe citarla —el mecanismo que explica
    sigue siendo la mejor explicación disponible— se prohíbe citarla **sola**."""
    lineas = _BACKLOG.read_text(encoding="utf-8").split("\n")
    exentas = _lineas_del_enunciado_de_la_43()

    peladas = []
    for n, linea in enumerate(lineas):
        if n in exentas or _MARCA in linea:
            continue
        for patron in _CIFRAS_SUPERSEDIDAS:
            if re.search(patron, linea):
                peladas.append(f"L{n + 1}: {linea[:120]}")
    assert peladas == [], (
        "cifras supersedidas citadas sin contexto:\n"
        + "\n".join(peladas)
        + f"\n\nAgregar «{_MARCA}» con el número vigente, o sacar la cita."
    )


def test_el_guard_tiene_algo_que_vigilar():
    """Sanity: si el patrón dejara de matchear —porque alguien reescribió las citas—
    el test de arriba pasaría vacío y nadie se enteraría."""
    texto = _BACKLOG.read_text(encoding="utf-8")
    for patron in _CIFRAS_SUPERSEDIDAS:
        assert re.search(patron, texto), f"el patrón ya no matchea nada: {patron}"
    assert texto.count(_MARCA) >= 4, "las cuatro citas del barrido de la 43 tienen que seguir marcadas"


def test_cada_cifra_vigilada_declara_por_que_caduco():
    """Una entrada sin motivo es una prohibición sin auditoría: dentro de un mes nadie
    sabe si sigue valiendo."""
    for patron, motivo in _CIFRAS_SUPERSEDIDAS.items():
        assert len(motivo) > 60, f"motivo demasiado corto para {patron}"
        assert "tarea" in motivo.lower(), f"el motivo de {patron} no dice de qué tarea sale"


def test_el_doc_de_origen_lleva_la_nota_de_correccion():
    """El backlog manda a §13.6 a buscar el número vigente. Si la nota no está ahí, la
    marca del backlog apunta a un lugar donde el número sigue siendo el viejo."""
    texto = _DOC_T9.read_text(encoding="utf-8")
    i = texto.index("### 13.6")
    j = texto.index("### 13.7")
    seccion = texto[i:j]
    assert "NOTA DE CORRECCIÓN" in seccion
    assert "+1.80 pp" in seccion, "la nota tiene que traer el número vigente, no sólo el aviso"
    assert "rank_neutral_t39" in seccion, "y de dónde sale"


def test_la_nota_conserva_lo_que_NO_caduco():
    """Media corrección es peor que ninguna: si la nota se leyera como *«todo esto era
    falso»*, se perdería el mecanismo —repartir vs concentrar—, que es el resultado
    transferible de la T9 y que la T39 midió de forma directa (1.21 pp)."""
    texto = _DOC_T9.read_text(encoding="utf-8")
    i = texto.index("### 13.6")
    seccion = texto[i : texto.index("### 13.7")]
    assert "mecanismo" in seccion and "1.21 pp" in seccion
    assert "no tiene alpha" in seccion, "la distinción con «alpha negativo» también se sostiene"
