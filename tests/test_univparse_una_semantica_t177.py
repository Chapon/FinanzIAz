"""Tarea 177 — un solo parseo del formato de universo, y las huellas vivas no se movieron.

**El defecto.** `analysis/harness_config` tenía **dos** lectores del mismo formato:

* ``parse_universe_file`` (el de los runners, consolidado por la **161**) parte por
  **comas**, hace **uppercase** y **deduplica** preservando orden;
* ``_leer_universo`` (el que alimenta ``universe_fingerprint`` y ``artifact_population``)
  hacía **ninguna de las tres**.

**Y coincidían sólo por una propiedad de los datos de hoy.** Medido al cerrar la 161: los 5
archivos de universo del repo no tienen **ni una coma ni una minúscula** (``comas=0`` en los
cinco), así que las dos funciones devolvían exactamente lo mismo. La equivalencia era un
**accidente de la muestra**, no una garantía del código.

**Lo que arriesgaba, y de los cuatro ejes de diferencia sólo UNO llegaba a algo.** Esto lo
corregí **midiendo, después de escribir el enunciado**: ``tickers_fingerprint`` hace
``sorted({str(t).strip().upper() for t in tickers})``, o sea que **absorbe orden, caso y
duplicados**. Y el otro consumidor, ``retired_tickers``, hace ``{t.strip().upper() for t in
...}``. Así que las diferencias de uppercase, dedupe y orden eran **indiferentes** para los
dos, y el enunciado de la tarea las citaba como si contaran.

El eje que **sí** llegaba es el **split por comas**. El día que alguien escribiera dos
tickers en una línea —que el formato **admite**, y ``parse_universe_file`` lo documenta—
``_leer_universo`` habría devuelto el token entero (``'AAPL, MSFT'``) como **un** elemento:
la huella habría contado 1 donde el harness carga 2, y ``retired_tickers`` habría reportado a
los dos como retirados. Con eso una corrida podría declararse sobre otro universo del que
midió. Es la forma de la **52** (*«consciente de la ventana pero no de la población»*) un
nivel más abajo — un eje, no cuatro.

**Por qué se pudo unificar sin re-anclar, y por qué se midió antes.** La huella está
congelada dentro de las anclas de reproducción de los 17 runners, así que cambiar el parseo
es un cambio que **puede mover un veredicto**. Por eso el kill-criteria arrancaba con una
medición y no con el arreglo: las huellas de los 5 universos resultaron **byte-idénticas**
con el parseo unificado, y eso es lo que habilitó el cambio. Si hubieran diferido, la tarea
se cerraba **declarando el desvío** y sin tocar nada.
"""

from __future__ import annotations

import pathlib

import pytest

from analysis.harness_config import (
    _REPO_ROOT,
    _leer_universo,
    parse_universe_file,
    tickers_fingerprint,
    universe_fingerprint,
)

# Las huellas de los universos del repo, medidas con el parseo VIEJO (2026-09-11, antes de
# que `_leer_universo` delegara). Son la evidencia de que la unificación no movió la muestra,
# y por eso van pinneadas: derivarlas del código de hoy compararía el repo contra sí mismo,
# que es justo lo que la tarea 130 vino a cerrar.
_HUELLAS_ANTES: dict[str, str] = {
    "harness_universe_25.txt": "5cfcfee41380",
    "harness_universe_41_10y.txt": "dc8e4d0e59ec",
    "harness_universe_42.txt": "f2ef2539da8d",
    "harness_universe_live_acct2.txt": "06ab64fc6448",
    "sp500_universe.txt": "ef6a1134ce6a",
}


def test_los_universos_del_repo_siguen_siendo_los_de_la_medicion():
    """Contraprueba de población: si alguien agrega o saca un archivo de universo, las
    huellas pinneadas abajo dejan de cubrir el conjunto y hay que re-medir."""
    presentes = {p.name for p in (_REPO_ROOT / "data").glob("*universe*.txt")}
    assert presentes == set(_HUELLAS_ANTES), (
        f"el conjunto de universos cambió: {sorted(presentes ^ set(_HUELLAS_ANTES))} — "
        "re-medir las huellas antes de confiar en este guard"
    )


@pytest.mark.parametrize("nombre", sorted(_HUELLAS_ANTES))
def test_la_unificacion_NO_movio_ninguna_huella_viva(nombre):
    """**El kill-criteria de la tarea.** La huella con el parseo unificado tiene que ser la
    misma que con el viejo — si no, habría que re-anclar los 17 runners."""
    h = universe_fingerprint(f"data/{nombre}")
    assert h is not None, f"{nombre} no se pudo leer"
    assert h.startswith(_HUELLAS_ANTES[nombre]), (
        f"la huella de {nombre} se movió: {h[:12]} vs {_HUELLAS_ANTES[nombre]} (antes de la 177). "
        "Eso invalida las anclas de reproducción de los runners que la usan."
    )


@pytest.mark.parametrize("nombre", sorted(_HUELLAS_ANTES))
def test_las_dos_puertas_dan_LO_MISMO(nombre):
    """`_leer_universo` (por ruta relativa) y `parse_universe_file` (por `Path`) son ahora
    la misma lectura. Se comprueban las **dos puertas** porque los callers usan una o la
    otra y lo que la 177 cierra es que no puedan divergir."""
    rel = f"data/{nombre}"
    assert _leer_universo(rel) == parse_universe_file(_REPO_ROOT / rel)


# ── El caso que las separaba, que es el que prueba que la unificación hizo algo ──


def test_un_universo_con_COMAS_ya_no_separa_a_las_dos(tmp_path, monkeypatch):
    """**El test que da sentido a la tarea.** Con el parseo viejo este archivo daba
    ``['aapl, msft', 'NVDA', 'AAPL']`` por un lado y ``['AAPL','MSFT','NVDA']`` por el otro:
    3 contra 3 por casualidad, pero **conjuntos distintos**, y la huella habría mentido."""
    import analysis.harness_config as hc

    (tmp_path / "data").mkdir()
    f = tmp_path / "data" / "universo.txt"
    f.write_text("aapl, msft  # dos en una\nNVDA\nAAPL\n", encoding="utf-8")
    monkeypatch.setattr(hc, "_REPO_ROOT", tmp_path)

    esperado = ["AAPL", "MSFT", "NVDA"]
    assert hc.parse_universe_file(f) == esperado
    assert hc._leer_universo("data/universo.txt") == esperado
    assert hc.universe_fingerprint("data/universo.txt") == tickers_fingerprint(esperado)


def test_el_dedupe_preserva_el_ORDEN_y_no_es_un_set(tmp_path):
    """El orden importa para el **cargador**, no para la huella.

    **Corregido al medir (ver el §del final del docstring del módulo):** la primera versión
    de este test decía que un `set` haría la huella no determinística. **Es falso** —
    `tickers_fingerprint` hace `sorted({... .upper()})`, o sea que absorbe orden, caso y
    duplicados. Lo que sí depende del orden es el universo que el harness **recorre**, y de
    ahí sale qué entradas se ofrecen primero, que la tarea 49 midió en +4.21 pp de CAGR.
    """
    f = tmp_path / "universo.txt"
    f.write_text("MSFT\nAAPL\nMSFT\nNVDA\nAAPL\n", encoding="utf-8")
    assert parse_universe_file(f) == ["MSFT", "AAPL", "NVDA"]


def test_la_huella_absorbe_orden_caso_y_duplicados():
    """El hecho que acota el alcance de esta tarea, fijado para que no se vuelva a
    sobreestimar: `tickers_fingerprint` normaliza los tres ejes, así que de las cuatro
    diferencias entre las dos semánticas viejas **sólo el split por comas** podía llegar a
    la huella. Las otras tres eran indiferentes ahí."""
    base = ["AAPL", "MSFT", "NVDA"]
    assert tickers_fingerprint(base) == tickers_fingerprint(["nvda", "aapl", "msft"])
    assert tickers_fingerprint(base) == tickers_fingerprint([*base, "AAPL", "aapl"])
    # y el eje que SÍ la mueve: un token con coma sin partir es otro elemento
    assert tickers_fingerprint(["AAPL, MSFT", "NVDA"]) != tickers_fingerprint(base)


def test_queda_UNA_sola_lectura_del_formato():
    """`_leer_universo` tiene que **delegar**, no re-implementar. Si alguien le vuelve a
    escribir el parseo adentro, las dos semánticas se separan otra vez y el guard de arriba
    no lo vería mientras los universos sigan sin comas."""
    import ast
    import inspect

    fuente = inspect.getsource(_leer_universo)
    arbol = ast.parse(fuente.lstrip())
    llamadas = {
        getattr(n.func, "attr", None) or getattr(n.func, "id", None)
        for n in ast.walk(arbol)
        if isinstance(n, ast.Call)
    }
    assert "parse_universe_file" in llamadas, "`_leer_universo` dejó de delegar: re-implementó el parseo"
    assert "read_text" not in llamadas, "`_leer_universo` volvió a leer el archivo por su cuenta"


def test_el_fail_open_de_OSError_se_conservo(tmp_path, monkeypatch):
    """`universe_fingerprint` documenta que cae a `None` si no puede leer, y varios callers
    dependen de eso. Delegar no podía cambiarlo: `parse_universe_file` levanta `OSError`
    igual que el parseo que reemplaza."""
    import analysis.harness_config as hc

    monkeypatch.setattr(hc, "_REPO_ROOT", tmp_path)
    assert hc.universe_fingerprint("data/no_existe.txt") is None
    with pytest.raises(OSError):
        hc._leer_universo("data/no_existe.txt")


def test_el_BOM_tambien_llega_a_la_huella(tmp_path, monkeypatch):
    """La mitad heredada de la 41 y la 161: ahora que la huella usa el mismo parseo, un
    universo escrito desde PowerShell tampoco le pierde el primer ticker **a ella**."""
    import analysis.harness_config as hc

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "u.txt").write_bytes("﻿ABBV\nAAPL\n".encode())
    monkeypatch.setattr(hc, "_REPO_ROOT", tmp_path)

    assert hc._leer_universo("data/u.txt") == ["ABBV", "AAPL"]
    assert hc.universe_fingerprint("data/u.txt") == tickers_fingerprint(["ABBV", "AAPL"])


def test_las_huellas_pinneadas_no_son_del_codigo_de_hoy():
    """Guard del guard: las huellas de `_HUELLAS_ANTES` son un **valor medido** y tienen que
    quedar escritas, no derivadas. Si alguien las regenerara con el código actual, el test
    de kill-criteria pasaría siempre y no probaría nada."""
    fuente = pathlib.Path(__file__).read_text(encoding="utf-8")
    for huella in _HUELLAS_ANTES.values():
        assert f'"{huella}"' in fuente, f"{huella} dejó de estar escrita como literal"
