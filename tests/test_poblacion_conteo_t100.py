"""NTICKERS-CIEGO (tarea 100) — la población compara los DOS ejes, no uno.

La tarea 87 le agregó a ``ArtifactPopulation`` la huella del **archivo** de
universo, y estuvo bien: sin ella, cambiar un ticker por otro dejaba ``127 == 127``
y la corrida seguía afirmando *"MISMA muestra"*. Pero la puso en un ``if`` que
**devolvía**, así que cuando las dos partes declaran huella el conteo **no se
mira** — y las dos siempre la declaran (``HarnessConfig.population()`` la setea
siempre; las anclas compartidas la traen hardcodeada). El
``return self.n_tickers == other.n_tickers`` quedó **inalcanzable en producción**.

**Y la justificación escrita quedó falsa en el mismo commit.** El docstring de
``universe_fingerprint`` defiende la semántica del archivo diciendo que *"el eje
«qué cargó» ya lo lleva ``n_tickers``, por separado"*. Desde la 87, no lo llevaba
nadie.

Medido antes del arreglo: una corrida sobre **98** tickers contra el ancla de
**127** daba ``same_universe_as → True`` y ``reproduction_check → REPRO_OK``. Antes
de la 87 daba ``REPRO_NA``. O sea que una corrida sobre otra muestra se certificaba
como reproducida — y el repo ya había rechazado por escrito el argumento de *"pero
el número coincidió"*: ver ``test_not_applicable_wins_over_a_number_that_happens_to_match``
en ``test_harness_config.py``.

**Ningún test cubría "mismo archivo, distinto n_tickers"**, y por eso la regresión
entró silenciosa en un commit que sumó 22 tests. Estos son esos tests.
"""

from __future__ import annotations

from analysis.harness_config import (
    LEGACY_UNIVERSE_FILE,
    LIVE_UNIVERSE_FILE,
    POPULATION_LEGACY_41,
    POPULATION_LIVE_ACCT2,
    REPRO_NA,
    REPRO_OK,
    ArtifactPopulation,
    ArtifactWindow,
    HarnessConfig,
    artifact_population,
    reproduction_check,
)

_VENTANA = ArtifactWindow("2016-08-08", "2026-09-01", 2514)


def _pop(n_tickers: int, n_entries: int | None = None) -> ArtifactPopulation:
    """La población de una corrida viva, por el mismo camino que usan los runners."""
    return HarnessConfig(10, LIVE_UNIVERSE_FILE, n_tickers).population(n_entries)


# ── El eje que la 87 dejó ciego ───────────────────────────────────────────────


def test_una_carga_encogida_NO_es_el_mismo_universo():
    """El caso exacto de la 100: mismo archivo, 98 de 127 cargados."""
    assert _pop(98).same_universe_as(POPULATION_LIVE_ACCT2) is False


def test_una_carga_encogida_sale_NO_APLICA_y_no_OK():
    """Y el número coincide a propósito.

    Es la trampa que la 87 destapó sin querer: ``reproduction_check`` chequea la
    población **antes** de comparar contra ``tol``, justamente para que una
    coincidencia no pueda convertirse en OK. Con ``tol=0.0005`` de CAGR, la merma de
    un puñado de tickers entra holgada — no hace falta un escenario exótico.
    """
    estado, motivo = reproduction_check(
        0.0347,
        0.0347,
        tol=0.0005,
        current=_VENTANA,
        measured_on=_VENTANA,
        population=_pop(98, 90_000),
        measured_over=POPULATION_LIVE_ACCT2,
    )
    assert estado == REPRO_NA
    assert "otro universo" in motivo or "no aplica" in motivo.lower()


# ── Lo que NO se puede romper: los veredictos publicados ──────────────────────


def test_la_corrida_SANA_sigue_reproduciendo():
    """El kill-criteria de la tarea: ningún veredicto vigente se mueve.

    El ancla viva declara 127 tickers y el archivo de universo tiene 127, así que
    una corrida sana compara igual que antes de la 100.
    """
    sana = _pop(POPULATION_LIVE_ACCT2.n_tickers, 142_670)
    assert sana.same_universe_as(POPULATION_LIVE_ACCT2) is True

    estado, _ = reproduction_check(
        0.0347,
        0.0347,
        tol=0.0005,
        current=_VENTANA,
        measured_on=_VENTANA,
        population=sana,
        measured_over=POPULATION_LIVE_ACCT2,
    )
    assert estado == REPRO_OK


def test_la_corrida_legacy_SANA_tampoco_se_mueve():
    """El otro universo, que tiene su propia ancla desde la tarea 68."""
    leg = artifact_population(LEGACY_UNIVERSE_FILE, n_tickers=POPULATION_LEGACY_41.n_tickers)
    assert leg.same_universe_as(POPULATION_LEGACY_41) is True


# ── Lo que la 87 ganó, y tiene que SEGUIR ganado ──────────────────────────────


def test_cambiar_un_ticker_por_otro_sigue_sin_ser_el_mismo_universo():
    """La mitad de la 87: mismo conteo, otra huella.

    Si el arreglo de la 100 se hubiera hecho al revés —volviendo a comparar sólo el
    conteo— este test caería. Los dos ejes tienen que estar vivos a la vez.
    """
    a = ArtifactPopulation(LIVE_UNIVERSE_FILE, 127, None, "aaaaaaaaaaaa")
    b = ArtifactPopulation(LIVE_UNIVERSE_FILE, 127, None, "bbbbbbbbbbbb")
    assert a.same_universe_as(b) is False


def test_otro_archivo_nunca_es_el_mismo_universo():
    """El eje más viejo (tarea 52) sigue primero y corta antes que los otros dos."""
    a = ArtifactPopulation(LIVE_UNIVERSE_FILE, 41, None, "dc8e4d0e59ec")
    assert a.same_universe_as(POPULATION_LEGACY_41) is False


# ── El fallback, que sigue existiendo para quien no declara huella ────────────


def test_sin_huella_de_un_lado_se_cae_al_conteo():
    """Poblaciones armadas a mano (tests, anclas viejas) no traen huella.

    Ahí el conteo es lo único que hay, y tiene que seguir alcanzando — el arreglo de
    la 100 **agrega** un chequeo, no cambia el camino débil por otro.
    """
    con_fp = ArtifactPopulation(LIVE_UNIVERSE_FILE, 127, None, "b88c89385ebc")
    sin_fp = ArtifactPopulation(LIVE_UNIVERSE_FILE, 127, None, None)
    assert sin_fp.same_universe_as(con_fp) is True
    assert ArtifactPopulation(LIVE_UNIVERSE_FILE, 98, None, None).same_universe_as(con_fp) is False


def test_el_conteo_se_compara_INCLUSO_con_las_dos_huellas_presentes():
    """La regresión de la 87, fijada en su forma más chica.

    Éste es *el* test que faltaba: con las dos huellas iguales —que es el caso de
    **todo** el camino vivo— el conteo tiene que seguir mirándose. Si alguien vuelve
    a poner el ``return`` de la huella antes del conteo, cae acá.
    """
    fp = "b88c89385ebc"
    a = ArtifactPopulation(LIVE_UNIVERSE_FILE, 127, None, fp)
    b = ArtifactPopulation(LIVE_UNIVERSE_FILE, 98, None, fp)
    assert a.tickers_fp == b.tickers_fp
    assert a.same_universe_as(b) is False
