"""Tarea 87 — la población compara el CONJUNTO, y sin poder compararlo no acusa.

`ArtifactPopulation` existe para terminar con los chequeos ciegos a la muestra
(tarea 52) y **era ella misma uno**: `same_universe_as` prometía en su nombre
*"el mismo conjunto de tickers"* y comparaba **un string de path y un entero**.
Con eso, cambiar un ticker por otro dejaba `127 == 127` y la corrida seguía
afirmando *"MISMA muestra ⇒ cambió la cañería"*.

Y no era hipotético: `scripts/refresh_live_universe.py` regenera el archivo **en
el lugar**, con el mismo nombre.

La otra mitad: `matches()` devuelve `True` cuando alguna de las dos puntas no
declara `n_entries` —*"no se puede acusar por un dato que nadie publicó"*— pero
ese `True` entraba en `reproduction_check` **como si fuera evidencia**. No
declarar volvía al chequeo **más** confiado, exactamente al revés de su objetivo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from analysis.harness_config import (
    LEGACY_UNIVERSE_FILE,
    LIVE_UNIVERSE_FILE,
    POPULATION_LEGACY_41,
    POPULATION_LIVE_ACCT2,
    REPRO_INDETERMINATE,
    REPRO_NA,
    ArtifactPopulation,
    ArtifactWindow,
    artifact_population,
    reproduction_check,
    tickers_fingerprint,
    universe_fingerprint,
)

_REPO = Path(__file__).resolve().parent.parent
_W = ArtifactWindow("2016-08-08", "2026-09-01", 2514)


# ── La huella ────────────────────────────────────────────────────────────────


def test_la_huella_no_depende_del_orden():
    """Sale de un `set` recorrido por el loader: si dependiera del orden, dos
    corridas sobre el mismo universo darían huellas distintas."""
    assert tickers_fingerprint(["AAPL", "MSFT", "KO"]) == tickers_fingerprint(["KO", "AAPL", "MSFT"])


def test_la_huella_no_depende_de_como_este_escrito_el_ticker():
    assert tickers_fingerprint(["aapl", " MSFT "]) == tickers_fingerprint(["AAPL", "MSFT"])


def test_conjuntos_distintos_dan_huellas_distintas():
    assert tickers_fingerprint(["AAPL", "MSFT"]) != tickers_fingerprint(["AAPL", "KO"])


def test_el_mismo_TAMANO_con_otro_conjunto_da_otra_huella():
    """El caso que motiva todo: mismo conteo, otro conjunto."""
    a, b = ["AAPL", "MSFT", "KO"], ["AAPL", "MSFT", "PEP"]
    assert len(a) == len(b)
    assert tickers_fingerprint(a) != tickers_fingerprint(b)


# ── same_universe_as ─────────────────────────────────────────────────────────


def test_un_ticker_cambiado_por_otro_ya_NO_pasa_por_el_mismo_universo():
    """**El defecto, en un test.** Antes esto devolvía `True` porque comparaba
    `("u.txt", 3) == ("u.txt", 3)`."""
    p1 = ArtifactPopulation("u.txt", 3, None, tickers_fingerprint(["AAPL", "MSFT", "KO"]))
    p2 = ArtifactPopulation("u.txt", 3, None, tickers_fingerprint(["AAPL", "MSFT", "PEP"]))
    assert p1.n_tickers == p2.n_tickers
    assert not p1.same_universe_as(p2)


def test_el_mismo_conjunto_sigue_siendo_el_mismo_universo():
    fp = tickers_fingerprint(["AAPL", "MSFT", "KO"])
    assert ArtifactPopulation("u.txt", 3, None, fp).same_universe_as(ArtifactPopulation("u.txt", 3, 999, fp))


def test_sin_huella_en_alguna_punta_cae_al_conteo():
    """Compatibilidad declarada: el modo viejo sigue funcionando, **más débil**.
    Por eso las anclas compartidas sí la declaran."""
    con = ArtifactPopulation("u.txt", 3, None, tickers_fingerprint(["A", "B", "C"]))
    sin = ArtifactPopulation("u.txt", 3)
    assert con.same_universe_as(sin) and sin.same_universe_as(con)


def test_otro_archivo_nunca_es_el_mismo_universo():
    fp = tickers_fingerprint(["A"])
    assert not ArtifactPopulation("a.txt", 1, None, fp).same_universe_as(
        ArtifactPopulation("b.txt", 1, None, fp)
    )


# ── Las anclas ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ancla,archivo",
    [(POPULATION_LIVE_ACCT2, LIVE_UNIVERSE_FILE), (POPULATION_LEGACY_41, LEGACY_UNIVERSE_FILE)],
    ids=["live", "legacy"],
)
def test_las_anclas_declaran_la_huella_de_su_universo_real(ancla, archivo):
    """La huella baked-in tiene que ser la del archivo que hay en el repo. Si el
    universo cambia y nadie re-ancla, esto se pone rojo — que es el punto: un
    cambio de universo **debe** obligar a re-anclar, no pasar desapercibido."""
    from scripts.precompute_pit_signals import parse_universe_file

    tickers = parse_universe_file(_REPO / archivo)
    assert ancla.tickers_fp == tickers_fingerprint(tickers)
    assert ancla.n_tickers == len(tickers)


# ── artifact_population ──────────────────────────────────────────────────────


def test_la_poblacion_saca_la_huella_del_ARCHIVO_no_de_los_que_cargaron():
    """**Una sola semántica.** La huella es del universo *declarado* (el archivo);
    el eje "qué cargó" lo lleva `n_tickers`, por separado.

    Se eligió así porque el conjunto **cargado** cambiaría con una falla
    transitoria de carga —y eso es un hipo, no un cambio de universo— y porque
    tener las dos huellas sería dos fuentes de verdad para la misma pregunta, que
    es el defecto que esta tarea cierra."""
    pop = artifact_population(LIVE_UNIVERSE_FILE, {"AAPL": [1], "MSFT": [1]})
    assert pop.n_tickers == 2, "n_tickers sigue siendo lo que cargó"
    assert pop.tickers_fp == universe_fingerprint(LIVE_UNIVERSE_FILE)


def test_un_archivo_ilegible_no_inventa_huella():
    """Fail-open: sin huella el chequeo cae al conteo, que es el comportamiento
    previo. Un guard que revienta por no poder leer un universo sería peor que el
    defecto."""
    assert artifact_population("data/no_existe.txt", n_tickers=5).tickers_fp is None


def test_la_huella_llega_a_la_poblacion_que_arman_los_RUNNERS():
    """Sin esto el arreglo quedaba **inerte en producción**: cuatro de los ocho
    call sites del sanity construyen su población con `cfg.population(...)`."""
    from analysis.harness_config import HarnessConfig

    cfg = HarnessConfig(10, LIVE_UNIVERSE_FILE, 127)
    assert cfg.population(142_670).tickers_fp == universe_fingerprint(LIVE_UNIVERSE_FILE)


# ── reproduction_check ───────────────────────────────────────────────────────


def test_un_universo_con_un_ticker_cambiado_sale_NO_APLICA():
    """El escenario del `refresh_live_universe`: mismo archivo, mismo conteo, otro
    conjunto. Antes salía **FALLA acusando a la cañería**; ahora el ancla
    directamente no aplica."""
    ancla = ArtifactPopulation("u.txt", 3, None, tickers_fingerprint(["AAPL", "MSFT", "KO"]))
    corrida = ArtifactPopulation("u.txt", 3, 900, tickers_fingerprint(["AAPL", "MSFT", "PEP"]))
    st, why = reproduction_check(
        0.02, 0.0347, tol=0.0005, current=_W, measured_on=_W, population=corrida, measured_over=ancla
    )
    assert st == REPRO_NA
    assert "otro universo" in why or "no aplica" in why.lower()


def test_sin_entradas_declaradas_no_acusa_a_la_caneria():
    """Misma ventana, mismo conjunto, pero el ancla no declara entradas ⇒ no se
    puede confirmar que la muestra sea la misma."""
    fp = tickers_fingerprint(["AAPL", "MSFT", "KO"])
    ancla = ArtifactPopulation("u.txt", 3, None, fp)
    corrida = ArtifactPopulation("u.txt", 3, 900, fp)
    st, why = reproduction_check(
        0.02, 0.0347, tol=0.0005, current=_W, measured_on=_W, population=corrida, measured_over=ancla
    )
    assert st == REPRO_INDETERMINATE
    assert "no se puede confirmar" in why


def test_con_entradas_en_las_dos_puntas_SI_puede_acusar():
    """La capacidad de acusar no se pierde: se condiciona a tener con qué."""
    from analysis.harness_config import REPRO_FAIL

    fp = tickers_fingerprint(["AAPL", "MSFT", "KO"])
    ancla = ArtifactPopulation("u.txt", 3, 1000, fp)
    corrida = ArtifactPopulation("u.txt", 3, 1000, fp)
    st, why = reproduction_check(
        0.02, 0.0347, tol=0.0005, current=_W, measured_on=_W, population=corrida, measured_over=ancla
    )
    assert st == REPRO_FAIL and "cañería" in why
