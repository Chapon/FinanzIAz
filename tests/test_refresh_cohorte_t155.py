"""Tarea 155 (REFRESH-SIN-GUARD) — refrescar no puede pisar una excepción declarada.

**El incidente que la abre, y lo causé yo.** El 2026-09-09, ejecutando el refresh que
Chapa pidió (tareas 139/140), bajé el `10y` de los 127 tickers del universo vivo **sin
excluir** los de ``ARTIFACT_REFRESH_EXCEPTIONS``. **AVB está ahí desde la tarea 63
precisamente porque refrescarlo es destructivo**, y se perdió su histórico de ~2.500
barras de forma **irreversible**: Yahoo devuelve **27 filas** para *cualquier* período,
así que no se recupera bajándolo de nuevo, y el cache Parquet no tiene backup.

**Por qué pasó, y no es un descuido aislado:** el refresh del cohorte **existía como
operación pero no como script**. La T30 y la T68 lo hicieron a mano, y a mano no hay
nada que consulte el dict de excepciones. Una operación destructiva estaba a un
``get_historical_data_batch(tickers)`` de distancia de la operación normal, sin nada en
el medio.

**Lo que el diagnóstico sí aclaró (tarea 156):** AVB **no cambió de ticker**. Yahoo
sigue diciendo *AvalonBay Communities, Inc.*, NYSE, EQUITY — pero le reseteó el
``firstTradeDate`` al **2026-07-17** y le aplicó un split de **2,793 el 2026-08-17**.
Es una corrupción del proveedor sobre una empresa que sigue listada.

El invariante queda acá: **un ticker exento no se refresca**, y forzarlo requiere
pedirlo por nombre. Ver [[guard-no-puede-usar-de-verdad-lo-que-chequea]] — el dict
existía, lo que faltaba era que alguien lo consultara en el camino de la acción.
"""

from __future__ import annotations

import pytest

import analysis.harness_config as hc
from scripts.refresh_cohort import particionar, universo_vivo


@pytest.fixture(autouse=True)
def excepcion(monkeypatch):
    monkeypatch.setattr(hc, "ARTIFACT_REFRESH_EXCEPTIONS", {"AVB": "tarea 63: refrescarlo lo rompe"})
    import scripts.refresh_cohort as rc

    monkeypatch.setattr(rc, "ARTIFACT_REFRESH_EXCEPTIONS", hc.ARTIFACT_REFRESH_EXCEPTIONS)


def test_un_ticker_EXENTO_no_entra_a_la_lista_de_refresh():
    """**El invariante.** Es el test que habría evitado el incidente entero."""
    a_refrescar, exentos = particionar(["AAPL", "AVB", "MSFT"], forzados=set())

    assert exentos == ["AVB"]
    assert "AVB" not in a_refrescar
    assert a_refrescar == ["AAPL", "MSFT"]


def test_la_particion_pasa_ANTES_de_tocar_la_red():
    """No alcanza con saltearlo adentro del loop de descarga.

    ``particionar`` es una función **pura**: se le puede preguntar qué haría sin bajar
    un byte, y eso es lo que hace posible el ``--dry-run``. Un guard que sólo existe
    adentro de la operación destructiva no se puede ensayar.
    """
    assert particionar(["AVB"], forzados=set()) == ([], ["AVB"])


def test_forzar_requiere_nombrarlo_explicitamente():
    """La salida de emergencia existe, pero cuesta: hay que escribir el ticker.

    Un flag global tipo ``--refresh-all`` sería el mismo defecto con otro nombre —
    quien no sabe de la excepción lo usaría sin enterarse.
    """
    a_refrescar, exentos = particionar(["AVB", "AAPL"], forzados={"AVB"})
    assert a_refrescar == ["AVB", "AAPL"] and exentos == []


def test_forzar_OTRO_ticker_no_destapa_al_exento():
    """El `--force` es por nombre, no un interruptor."""
    a_refrescar, exentos = particionar(["AVB", "AAPL"], forzados={"AAPL"})
    assert exentos == ["AVB"] and a_refrescar == ["AAPL"]


def test_la_comparacion_no_depende_de_las_mayusculas():
    a_refrescar, exentos = particionar(["avb"], forzados=set())
    assert exentos == ["avb"] and a_refrescar == []


def test_el_universo_ignora_comentarios_y_vacios(tmp_path):
    """El archivo de universo trae un header de cuatro líneas de comentario."""
    f = tmp_path / "u.txt"
    f.write_text("# header\n\nAAPL\n  MSFT  \n# otro\n", encoding="utf-8")
    assert universo_vivo(f) == ["AAPL", "MSFT"]


def test_el_script_declara_los_TRES_pasos_que_siguen():
    """Un refresh a medias es peor que ninguno, y eso ya pasó dos veces.

    Después de refrescar: el store PIT queda atrás (T111/T117 — tres días sin poder
    correr ningún harness), las constantes quedan INDETERMINADAS (T48/T68 — 17 para
    re-anclar) y si la última barra es de hoy sin asentar (T112) anclar sobre ella
    mueve los números. El script lo imprime en vez de confiar en que alguien se acuerde.
    """
    from pathlib import Path

    txt = (Path(__file__).resolve().parent.parent / "scripts" / "refresh_cohort.py").read_text(
        encoding="utf-8"
    )
    assert "precompute_pit_signals" in txt
    assert "re-anclarlas TODAS en el" in txt
    assert "T112" in txt and "cierre firme" in txt
