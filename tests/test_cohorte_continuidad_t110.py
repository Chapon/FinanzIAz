"""Tarea 110 — el hueco INTERIOR que los dos guards del cohorte no podían ver.

``stale_artifacts`` y ``artifact_window`` miran **las puntas**: la primera barra y
la última. Una rueda faltante en el medio no mueve ninguna de las dos, así que pasa
entera. Medido el 2026-09-04: el **2026-08-28** —viernes hábil— está en **49 de 506**
artefactos ``10y`` (9,7%) contra 99,4-99,6% de sus fechas vecinas, y el banner de
frescura decía *«todos alineados»* porque los 506 terminan en la misma fecha.

**El instrumento tiene una trampa que estos tests fijan.** El primer intento derivaba
el calendario del propio cohorte (*"una fecha es rueda si la tiene la mayoría"*), y
eso **no puede ver** una fecha que falta en el 90%: por construcción la declara "no
rueda" y reporta cero huecos. La fuente tiene que ser independiente de lo que se
chequea — acá, **otro frame del mismo ticker**.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.harness_config import (
    MissingSession,
    StaleArtifactError,
    announce_artifacts,
    announce_continuity,
    announce_mixed_scale,
    artifact_window,
    cross_period_gaps,
    mixed_scale_frames,
    stale_artifacts,
)


def _bars(fechas: list[str]) -> list[tuple]:
    return [(f, 10.0, 10.0, 10.0, 10.0) for f in fechas]


def _frame(fechas: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1},
        index=pd.to_datetime(fechas),
    )


_SEMANA = ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"]
_CON_HUECO = ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-31"]


@pytest.fixture
def referencia(tmp_path, monkeypatch):
    """Escribe parquets **de verdad** en un directorio temporal.

    No se monkeypatchea ``labelled_1d``: el guard tiene un camino rápido que lista
    el directorio y saltea al ticker con un solo frame, así que parchear el lector
    dejaría ese camino **sin probar** — y es el que decide si el ticker se compara.
    Con archivos reales se ejercita entero, y de paso el fixture no puede mentir
    sobre lo que hay en disco.
    """
    from data import parquet_cache

    monkeypatch.setattr(parquet_cache, "_parquet_dir_override", tmp_path, raising=False)
    parquet_cache.set_parquet_dir(tmp_path)

    def _set(por_ticker: dict[str, list[str]]):
        for ticker, fechas in por_ticker.items():
            # DOS frames por ticker: el guard es bilateral y con uno solo no compara.
            parquet_cache.write(ticker, "2y", "1d", _frame(fechas))
            parquet_cache.write(ticker, "10y", "1d", _frame(fechas))

    yield _set
    parquet_cache.set_parquet_dir(None)


# ── Lo que los guards viejos NO pueden ver ──────────────────────────────────


def test_los_guards_de_PUNTAS_dan_todo_bien_con_el_hueco_adentro():
    """El corazón del hallazgo, en su forma más chica. Dos artefactos que arrancan y
    terminan igual, uno con una rueda menos en el medio: `stale_artifacts` no acusa
    nada y `artifact_window` publica la misma ventana."""
    sano = _bars(["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-31"])
    con_hueco = _bars(["2026-08-24", "2026-08-26", "2026-08-31"])  # le falta el 25
    cohorte = {"AAA": sano, "BBB": con_hueco}

    assert stale_artifacts(cohorte) == (), "las puntas coinciden: nada que declarar"
    w = artifact_window(cohorte)
    assert (w.start, w.end) == ("2026-08-24", "2026-08-31")


# ── El instrumento nuevo ────────────────────────────────────────────────────


def test_acusa_la_rueda_que_el_otro_periodo_SI_tiene(referencia):
    referencia({"AAA": _SEMANA})
    faltan = cross_period_gaps({"AAA": _bars(_CON_HUECO)})
    assert {(s.ticker, s.date) for s in faltan} == {("AAA", "2026-08-28")}
    assert all(isinstance(s, MissingSession) and s.reference in ("2y", "10y") for s in faltan)


def test_un_cohorte_sano_no_acusa_nada(referencia):
    """El control negativo: sin esto, un guard que acusa siempre pasaría el de arriba."""
    referencia({"AAA": _SEMANA})
    assert cross_period_gaps({"AAA": _bars(_SEMANA)}) == ()


def test_fuera_del_SOLAPE_una_ausencia_no_es_un_hueco(referencia):
    """Que el frame de referencia llegue más atrás no convierte en hueco todo lo que
    el otro no cubre — sería el error del que mide una IPO contra 10 años."""
    referencia({"AAA": ["2020-01-02", "2020-01-03", *_SEMANA]})
    faltan = cross_period_gaps({"AAA": _bars(_SEMANA)})
    assert faltan == (), "lo anterior al inicio del frame no es un hueco"


def test_sin_frame_de_referencia_el_ticker_NO_es_comparable(referencia):
    """La propiedad que hace innecesario cualquier umbral inventado: un ticker sin
    otro período simplemente no se compara, en vez de acusarse por defecto."""
    referencia({})
    assert cross_period_gaps({"ZZZ": _bars(_CON_HUECO)}) == ()


def test_el_calendario_NO_sale_del_cohorte_que_se_chequea(referencia):
    """**El defecto del primer instrumento, fijado como test.** Si el calendario se
    derivara por mayoría del propio cohorte, una rueda que le falta a TODOS dejaría
    de ser rueda y el guard reportaría cero. Acá los tres la pierden y los tres se
    acusan, porque la verdad viene de afuera."""
    referencia(dict.fromkeys(("AAA", "BBB", "CCC"), _SEMANA))
    cohorte = {t: _bars(_CON_HUECO) for t in ("AAA", "BBB", "CCC")}
    faltan = cross_period_gaps(cohorte)
    assert {s.ticker for s in faltan} == {"AAA", "BBB", "CCC"}
    assert {s.date for s in faltan} == {"2026-08-28"}


# ── El banner ───────────────────────────────────────────────────────────────


def test_el_banner_agrega_por_FECHA_y_no_por_ticker(referencia, capsys):
    """457 líneas de "a este le falta el 28" son ilegibles; la fecha es el eje real
    del defecto porque el hueco es un evento del refresh, no del ticker."""
    referencia(dict.fromkeys(("AAA", "BBB"), _SEMANA))
    announce_continuity({t: _bars(_CON_HUECO) for t in ("AAA", "BBB")})
    salida = capsys.readouterr().out
    assert "2026-08-28: falta en 2 ticker(s)" in salida
    assert "AAA" in salida and "BBB" in salida


def test_por_default_DECLARA_y_no_aborta(referencia):
    """Arreglar el dato re-baja la ventana y obliga a re-anclar las constantes de
    reproducción (lo que costó la 68). Abortar las 26 corridas por un impacto que
    todavía no se midió sería tomar esa decisión de paso."""
    referencia({"AAA": _SEMANA})
    assert announce_continuity({"AAA": _bars(_CON_HUECO)})  # devuelve, no levanta


def test_con_strict_SI_aborta(referencia):
    """El mecanismo existe y está probado: lo que falta para prenderlo es la
    decisión, no el código."""
    from analysis.harness_config import StaleArtifactError

    referencia({"AAA": _SEMANA})
    with pytest.raises(StaleArtifactError, match="rueda"):
        announce_continuity({"AAA": _bars(_CON_HUECO)}, strict=True)


# ── El cableado: los 26 lo reciben sin una llamada nueva ────────────────────


def test_announce_artifacts_ARRASTRA_la_continuidad(referencia, capsys):
    """Va adentro del guard que los 26 lectores ya llaman, en vez de ser una segunda
    llamada que hay que acordarse de cablear — la lección de la 97 y la 101 aplicada
    al diseño. Y el texto de las puntas lo dice, para que «todos alineados» no se
    vuelva a leer como «el cohorte está sano».

    **El `strict=False` lo agregó la 111**: desde que el cohorte quedó sin huecos, la
    continuidad **aborta** con el default. Acá sólo se mira el banner."""
    referencia({"AAA": _SEMANA})
    announce_artifacts({"AAA": _bars(_CON_HUECO)}, strict=False)
    salida = capsys.readouterr().out
    assert "en las PUNTAS" in salida
    assert "Continuidad del cohorte" in salida
    assert "2026-08-28" in salida


def test_la_continuidad_ABORTA_con_el_default(referencia):
    """**Tarea 111, paso 5.** Con el cohorte reparado (0 ruedas faltantes) el guard
    pasa de declarar a **frenar**: un hueco nuevo ya no deja correr el harness."""
    from analysis.harness_config import StaleArtifactError

    referencia({"AAA": _SEMANA})
    with pytest.raises(StaleArtifactError, match="rueda"):
        announce_artifacts({"AAA": _bars(_CON_HUECO)})


def test_la_bandera_que_ya_existia_cubre_las_DOS(referencia, capsys):
    """`strict_continuity` era un parámetro aparte que **ningún runner podía pasar**:
    prenderlo habría dejado a los 26 sin escape. Ahora cuelga de `strict`, o sea que
    `--allow-stale-artifacts` —la bandera de *«corro sobre un sustrato torcido y lo
    declaro»*— sirve para las puntas **y** para el medio."""
    referencia({"AAA": _SEMANA})
    fuera = announce_artifacts({"AAA": _bars(_CON_HUECO)}, strict=False)
    assert fuera == (), "las puntas están sanas: el que acusa es el de continuidad"
    assert "Continuidad del cohorte — 1 rueda" in capsys.readouterr().out


def test_se_puede_forzar_una_sin_la_otra(referencia, capsys):
    """El override explícito sigue existiendo, para el harness que a propósito corre
    sobre un cohorte con huecos pero exige frescura en las puntas."""
    referencia({"AAA": _SEMANA})
    announce_artifacts({"AAA": _bars(_CON_HUECO)}, strict=True, strict_continuity=False)
    assert "Continuidad del cohorte" in capsys.readouterr().out


def test_se_puede_apagar_para_el_que_no_lo_quiera(referencia, capsys):
    referencia({"AAA": _SEMANA})
    announce_artifacts({"AAA": _bars(_CON_HUECO)}, continuity=False)
    assert "Continuidad del cohorte" not in capsys.readouterr().out


# ── Escala MIXTA adentro de un frame — Tarea 113 ─────────────────────────────


def _serie(precios: list[float]) -> list[tuple]:
    return [(f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", p, p, p, p) for i, p in enumerate(precios)]


def _mnst_sintetico() -> list[tuple]:
    """La firma real de MNST: dos escalas (~47 y ~95) alternandose siete veces."""
    base = [95.0] * 20
    for _ in range(4):
        base += [47.0, 95.0]
    return _serie(base + [95.0] * 20)


def _crash_y_rebote() -> list[tuple]:
    """La firma de un evento REAL: cae fuerte y rebota UNA vez (COVID, un IPO, un
    panel de FDA). Los 506 frames tienen 110 tickers con saltos >30% y casi todos
    son esto."""
    return _serie([100.0] * 20 + [55.0, 88.0] + [90.0] * 20)


def test_acusa_a_la_escala_mixta():
    fuera = mixed_scale_frames({"MNST": _mnst_sintetico()})
    assert len(fuera) == 1
    assert fuera[0].ticker == "MNST"
    assert fuera[0].factor == pytest.approx(2.0, abs=0.05), "tiene que reconocer el split 2:1"


def test_NO_acusa_a_un_crash_y_rebote_real():
    """La contraprueba que define la tarea. El enunciado daba el umbral de magnitud
    por calibrar; medido sobre los 506, un umbral de magnitud solo acusa a **110**
    tickers y el round-trip solo a **9**, de los cuales **8 son reales** (COVID en
    NCLH/CVNA/DRI/MGM/OKE, PG&E 2018, el IPO de HOOD, el panel de BIIB).

    Lo que discrimina es la CONJUNCION: que la serie oscile varias veces **y** que
    todos los saltos sean el mismo factor. Un crash y su rebote cumplen lo primero
    una vez y no lo segundo.
    """
    assert mixed_scale_frames({"REAL": _crash_y_rebote()}) == ()


def test_UN_solo_round_trip_no_alcanza():
    """1 par = crash y rebote. 2 = semana volatil. Recien 3+ es "oscila". Sin este
    test, bajar `min_pairs` a 1 pasaria en verde y acusaria a los ocho reales."""
    dos_escalas_una_vez = _serie([95.0] * 20 + [47.0, 95.0] + [95.0] * 20)
    assert mixed_scale_frames(dos_escalas_una_vez and {"X": dos_escalas_una_vez}) == ()


def test_oscilar_con_MAGNITUDES_distintas_tampoco_alcanza():
    """El otro lado de la conjuncion: si oscila pero cada salto es de otro tamaño, es
    volatilidad, no una escala. Sin esto, sacar el chequeo de spread pasaria en verde.
    """
    caotico = _serie([100.0] * 20 + [50.0, 105.0, 62.0, 98.0, 40.0, 95.0] + [95.0] * 20)
    assert mixed_scale_frames({"CAOS": caotico}) == ()


def test_el_anuncio_aborta_con_strict_y_nombra_el_factor(capsys):
    with pytest.raises(StaleArtifactError):
        announce_mixed_scale({"MNST": _mnst_sintetico()}, strict=True)
    salida = capsys.readouterr().out
    assert "DOS escalas intercaladas" in salida
    assert "RE-BAJAR" in salida, "tiene que decir cual es la accion"


def test_el_caso_sano_lo_dice(capsys):
    """Un guard que solo habla cuando acusa deja al lector sin saber si corrio."""
    assert announce_mixed_scale({"REAL": _crash_y_rebote()}, strict=True) == ()
    assert "sin frames con escalas mezcladas" in capsys.readouterr().out
