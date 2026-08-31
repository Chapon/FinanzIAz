"""
Tests de ``analysis/harness_config`` y del universo vivo — Tarea 27 (HARNESS-CFG).

Todo offline: sin DB, sin red. Los tests del refresh usan una DB SQLite temporal.

Cubre:
  deviations / config_banner — los cinco desvíos: slots, tamaño de universo y
                               ventana de analyze() (T27) + el precio contra el que
                               se deciden las barreras ATR (T32, lo destapó la T26)
                               + el fill de esa barrera (T33, lo destapó la 26b)
  verdict_max_positions      — el aviso de reproducibilidad cuando el default nuevo
                               no reproduce el veredicto publicado
  announce                   — imprime y devuelve la config
  reproduction_check         — los cuatro estados: la ventana rodante de los
                               artefactos (T48) y la población sobre la que se midió
                               el ancla (T52), que son los dos ejes de "misma muestra"
  defaults de los runners    — regresión: ningún harness vuelve a heredar en
                               silencio los 5 slots de la cuenta pausada ni el fill
                               look-ahead de la barrera decidida al close, y ningún
                               ancla de reproducción vuelve a ser ciega a la muestra
  refresh_live_universe      — filtra la watchlist por artefacto PIT disponible
  grid_population            — la población de cada valor de la grilla (T58): brazos
                               INERTES (el baseline con otro nombre) vs brazos «sin
                               población» (<5%, el umbral de la T13), que no son lo
                               mismo y no piden lo mismo
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from analysis.harness_config import (
    GRID_MIN_POPULATION,
    HARNESS_FILL_MODE,
    LEGACY_FILL_MODE,
    LEGACY_MAX_POSITIONS,
    LIVE_ACCOUNT_ID,
    LIVE_MAX_POSITIONS,
    LIVE_WATCHLIST_SIZE,
    POPULATION_LEGACY_41,
    POPULATION_LIVE_ACCT2,
    REPRO_FAIL,
    REPRO_INDETERMINATE,
    REPRO_NA,
    REPRO_OK,
    WINDOW_REFRESH_2026_08_09,
    ArtifactPopulation,
    ArtifactWindow,
    HarnessConfig,
    announce,
    announce_grid,
    artifact_population,
    artifact_window,
    config_banner,
    deviations,
    exit_rule_line,
    grid_population,
    reproduction_check,
)

_REPO = Path(__file__).resolve().parent.parent

# Los runners de la serie que simulan cartera (T7 no: corre con capital ilimitado,
# es anterior a portfolio_sim).
PORTFOLIO_RUNNERS = [
    "run_market_regime_r2.py",
    "run_meta_label_t9.py",
    "run_sizing_exposure_t10_t20.py",
    "run_anomaly_replay_t11b.py",
    "run_insider_cluster_replay_t12.py",
    "run_tp_cal_replay_t23.py",
    "run_ent1_replay_t13.py",
    "run_ranking_t21.py",
    "run_stop_cal_replay_t26.py",
    "run_stop_loosen_t34.py",
]

# Todos los que corren sobre ``replay_cycle``, o sea los que heredaban el fill
# look-ahead de la barrera decidida al close (T33). Suma el T7 —que no simula
# cartera pero replaya ciclos— y el 26b, que es el que lo destapó.
REPLAY_RUNNERS = [*PORTFOLIO_RUNNERS, "run_scaleout_replay_t7.py", "run_stop_price_replay_t26b.py"]

# Los runners que anclan un sanity de reproducción contra un número publicado, o
# sea los que la tarea 52 barrió para que declaren también su POBLACIÓN.
REPRO_ANCHOR_RUNNERS = [
    "run_stop_value_t37.py",
    "run_rank_neutral_t39.py",
    "run_anom_profile_t45.py",
    "run_stop_price_redecide_t47.py",
    "run_prio_event_t49.py",
]


# ── deviations / banner ──────────────────────────────────────────────────────


def test_legacy_config_declares_slots_and_universe():
    cfg = HarnessConfig(LEGACY_MAX_POSITIONS, "data/harness_universe_41_10y.txt", 41)
    devs = deviations(cfg)
    assert any("slots 5 vs 10" in d for d in devs)
    assert any("41 tickers" in d for d in devs)


def test_live_config_only_declares_the_structural_deviations():
    """Con la config viva quedan **cinco** desvíos estructurales: la ventana de
    ``analyze()`` (T27), el precio de evaluación de las barreras (T32), el precio al
    que se llena esa barrera (T33), los gates de re-entrada (T34) y la ventana
    RODANTE de los artefactos (T48). Son los que se declaran en vez de corregirse."""
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE)
    devs = deviations(cfg)
    assert len(devs) == 5
    assert any("ventana de analyze()" in d for d in devs)
    assert any("barreras ATR" in d for d in devs)
    assert any("fill de la barrera" in d for d in devs)
    assert any("gates de re-entrada" in d for d in devs)
    assert any("artefactos" in d for d in devs)


def test_reentry_gates_deviation_is_declared_unless_modelled():
    """T34 — el sexto desvío. ``portfolio_sim`` nunca modeló los gates de re-entrada
    del engine, así que mientras no se los modele hay que decirlo, **con el número que
    vale**: el defecto no es que existan, es que el harness los ignore en silencio."""
    off = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE)
    dev = next(d for d in deviations(off) if "gates de re-entrada" in d)
    assert "Gate 5" in dev and "Gate 5b" in dev
    assert "21,15%-36,36%" in dev  # el costo medido, no una vaguedad
    assert "gates de re-entrada" in config_banner(off)


def test_modelling_the_reentry_gates_removes_the_deviation():
    """Con ``live_gates=True`` el harness deja de desviarse en ese eje, así que el
    desvío **no** se anuncia — mismo patrón que ``fill_mode`` bajo ``touch``."""
    on = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE, live_gates=True)
    devs = deviations(on)
    assert not any("gates de re-entrada" in d for d in devs)
    assert len(devs) == 4


def test_signal_window_deviation_is_always_declared():
    """No es condicional: mientras los artefactos PIT sean los actuales, la ventana
    difiere siempre y tiene que decirlo aunque todo lo demás coincida."""
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE + 50)
    assert any("ventana de analyze()" in d for d in deviations(cfg))


def test_exit_eval_price_deviation_is_always_declared():
    """T32 — el cuarto desvío: el harness decide las barreras ATR al **close** y el
    engine vivo al **precio intradía**. Es estructural de ``replay_cycle``, así que
    no depende de cómo se invoque al harness: se declara siempre."""
    for cfg in (
        HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE),
        HarnessConfig(LEGACY_MAX_POSITIONS, "y.txt", 41),
    ):
        devs = deviations(cfg)
        assert any("barreras ATR" in d and "close diario" in d for d in devs)


def test_the_false_fill_claim_never_comes_back():
    """T33 — la T32 declaraba *"el fill sí está modelado; la decisión no"*, y esa
    media verdad tapó el look-ahead durante cinco harness: en modo ``close`` el fill
    **no** estaba modelado, estaba mal. Si alguien reintroduce la frase, esto falla."""
    for fm in (HARNESS_FILL_MODE, LEGACY_FILL_MODE):
        cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE, fill_mode=fm)
        assert "el fill sí está modelado" not in config_banner(cfg)


def test_honest_fill_is_declared_as_a_conservative_deviation():
    """Con el default honesto el harness **sigue** sin coincidir con el engine —que
    llena con el modelo de orden en reposo— pero ahora por el lado conservador. Eso
    también se declara: el objetivo no es que coincida, es que esté escrito."""
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE)
    dev = next(d for d in deviations(cfg) if "fill de la barrera" in d)
    assert "orden en reposo" in dev and "conservador" in dev
    assert "LOOK-AHEAD" not in dev


def test_legacy_fill_in_close_mode_is_announced_as_look_ahead():
    """El caso que dio vuelta el hallazgo central de la T26 no es un desvío: es un
    defecto, y el banner tiene que gritarlo (con el número que vale)."""
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE, fill_mode=LEGACY_FILL_MODE)
    dev = next(d for d in deviations(cfg) if "LOOK-AHEAD" in d)
    assert "NIVEL" in dev and "+5.01 pp" in dev
    assert "LOOK-AHEAD" in config_banner(cfg)


def test_at_touch_there_is_no_fill_deviation_at_all():
    """Bajo ``touch`` el precio que decide **es** el nivel, así que los dos fill_mode
    coinciden entre sí y con ``gates.model_exit_fill_price`` del engine: no hay nada
    que declarar, ni siquiera con el legacy."""
    for fm in (HARNESS_FILL_MODE, LEGACY_FILL_MODE):
        cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE, eval_mode="touch", fill_mode=fm)
        devs = deviations(cfg)
        assert not any("fill de la barrera" in d or "LOOK-AHEAD" in d for d in devs)
        assert any("cota SUPERIOR" in d for d in devs)


def test_exit_rule_line_names_both_halves():
    """Las dos mitades que la serie T7→T26 arrastró sin nombrar: contra qué precio se
    decide la barrera y a qué precio se llena."""
    honest = exit_rule_line("close", HARNESS_FILL_MODE)
    legacy = exit_rule_line("close", LEGACY_FILL_MODE)
    assert "close diario" in honest and "decisión" in honest
    assert "orden en reposo" in legacy and "LEGACY" in legacy
    assert "toque intradía" in exit_rule_line("touch", HARNESS_FILL_MODE)


def test_banner_lists_the_exit_eval_deviation():
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE)
    banner = config_banner(cfg)
    assert "barreras ATR" in banner
    assert "Regla de salida simulada" in banner


def test_banner_names_the_live_account():
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE)
    txt = config_banner(cfg)
    assert f"id={LIVE_ACCOUNT_ID}" in txt
    assert "Sim Segundo" in txt


def test_banner_warns_when_default_does_not_reproduce_the_verdict():
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", 41, verdict_max_positions=LEGACY_MAX_POSITIONS)
    txt = config_banner(cfg)
    assert "--max-positions 5" in txt


def test_banner_is_quiet_when_verdict_config_matches():
    cfg = HarnessConfig(LEGACY_MAX_POSITIONS, "x.txt", 41, verdict_max_positions=LEGACY_MAX_POSITIONS)
    assert "OJO" not in config_banner(cfg)


def test_announce_prints_and_returns(capsys):
    cfg = announce(7, "u.txt", 12, verdict_max_positions=LEGACY_MAX_POSITIONS)
    out = capsys.readouterr().out
    assert cfg.max_positions == 7 and cfg.n_tickers == 12
    assert "slots 7 vs 10" in out


# ── Regresión sobre los runners ──────────────────────────────────────────────


@pytest.mark.parametrize("script", PORTFOLIO_RUNNERS)
def test_runner_defaults_to_the_live_slot_count(script):
    """El defecto que esta tarea arregla: siete harness con ``default=5`` heredado
    de una cuenta pausada. Si alguien vuelve a clavar un literal, esto falla."""
    txt = (_REPO / "scripts" / script).read_text(encoding="utf-8")
    assert '"--max-positions", type=int, default=LIVE_MAX_POSITIONS' in txt
    assert '"--max-positions", type=int, default=5' not in txt


@pytest.mark.parametrize("script", PORTFOLIO_RUNNERS)
def test_runner_announces_its_config(script):
    # La aserción va por regex y no por substring literal a propósito: lo que se
    # exige es que el runner **declare su config**, no cómo quedó envuelta la
    # llamada. Con el substring, `ruff format` partiendo `announce(` en varias
    # líneas rompía diez runners sin que ninguno dejara de declarar nada (tarea 65).
    txt = (_REPO / "scripts" / script).read_text(encoding="utf-8")
    assert re.search(r"announce\(\s*args\.max_positions", txt), (
        f"{script} dejó de declarar su config con announce(args.max_positions, …)"
    )


@pytest.mark.parametrize("script", REPLAY_RUNNERS)
def test_runner_exposes_fill_mode_and_defaults_to_the_honest_one(script):
    """T33 — el defecto que esta tarea arregla: el fill legacy era el default y un
    harness nuevo lo heredaba en silencio. Cada runner que corre sobre
    ``replay_cycle`` tiene que poder elegirlo **y** arrancar en el honesto, para que
    el veredicto publicado siga siendo reproducible sin volver a ser el default."""
    txt = (_REPO / "scripts" / script).read_text(encoding="utf-8")
    assert '"--fill-mode"' in txt
    assert f"default={LEGACY_FILL_MODE!r}" not in txt
    assert 'default="resting"' not in txt


def test_replay_library_defaults_to_the_honest_fill():
    """El default vive en la librería, no en los runners: si vuelve a ``resting``,
    todo harness nuevo escrito en modo ``close`` nace con look-ahead."""
    import inspect

    from analysis.portfolio_sim import simulate_portfolio
    from analysis.scaleout_replay import replay_cycle

    for fn in (replay_cycle, simulate_portfolio):
        assert inspect.signature(fn).parameters["fill_mode"].default == HARNESS_FILL_MODE


def test_live_universe_file_exists_and_is_parseable():
    from analysis.harness_config import LIVE_UNIVERSE_FILE
    from scripts.precompute_pit_signals import parse_universe_file

    path = _REPO / LIVE_UNIVERSE_FILE
    assert path.exists(), "correr scripts/refresh_live_universe.py"
    tickers = parse_universe_file(path)
    assert len(tickers) > 100
    assert len(tickers) == len(set(tickers))


def test_universe_file_with_bom_does_not_lose_the_first_ticker(tmp_path):
    """Tarea 41. PowerShell 5.1 escribe UTF-8 **con BOM** por default, y con
    ``encoding="utf-8"`` el BOM se pegaba al primer ticker (``\\ufeffABBV``), que
    después no encontraba su artefacto PIT y **se caía del universo con un simple
    AVISO** — un ticker menos en el harness, en silencio."""
    from scripts.precompute_pit_signals import parse_universe_file

    path = tmp_path / "uni.txt"
    path.write_text("# comentario\nAAA\nBBB\n", encoding="utf-8-sig")
    assert parse_universe_file(path) == ["AAA", "BBB"]


# ── refresh_live_universe ────────────────────────────────────────────────────


def _make_db(path: Path, tickers: list[str], account_id: int = 2) -> None:
    con = sqlite3.connect(path)
    con.execute("create table paper_watchlist (account_id int, ticker text)")
    con.executemany("insert into paper_watchlist values (?, ?)", [(account_id, t) for t in tickers])
    con.commit()
    con.close()


def test_refresh_filters_watchlist_by_pit_availability(tmp_path):
    """Un ticker sin señal precomputada no puede entrar a ningún harness de la
    serie, así que el universo generado lo tiene que dejar afuera."""
    from scripts.refresh_live_universe import pit_tickers, watchlist_tickers

    db = tmp_path / "t.db"
    _make_db(db, ["AAA", "BBB", "CCC"])
    pit_dir = tmp_path / "pit"
    pit_dir.mkdir()
    for t in ("AAA", "CCC"):
        (pit_dir / f"{t}__10y__w250.json").write_text("{}", encoding="utf-8")

    wl = watchlist_tickers(db, 2)
    pit = pit_tickers(pit_dir)
    assert wl == ["AAA", "BBB", "CCC"]
    assert [t for t in wl if t in pit] == ["AAA", "CCC"]


def test_refresh_reads_only_the_requested_account(tmp_path):
    from scripts.refresh_live_universe import watchlist_tickers

    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute("create table paper_watchlist (account_id int, ticker text)")
    con.executemany("insert into paper_watchlist values (?, ?)", [(1, "OLD"), (2, "NEW"), (2, "NEW")])
    con.commit()
    con.close()
    assert watchlist_tickers(db, 2) == ["NEW"]  # distinct
    assert watchlist_tickers(db, 1) == ["OLD"]


def test_pit_tickers_on_missing_dir_is_empty(tmp_path):
    from scripts.refresh_live_universe import pit_tickers

    assert pit_tickers(tmp_path / "nope") == set()


# ── Tarea 48 — la ventana RODANTE de los artefactos (el séptimo desvío) ──────


def test_the_artifact_window_deviation_is_declared_even_when_the_runner_omits_it():
    """El desvío existe igual: si el runner no declara la ventana, el banner tiene que
    decir **eso**, no callarse. Es la diferencia entre "no aplica" y "no se sabe"."""
    sin = deviations(HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE))
    dev = next(d for d in sin if "artefactos" in d)
    assert "NO declara" in dev and "RODANTE" in dev

    con = deviations(
        HarnessConfig(
            LIVE_MAX_POSITIONS,
            "x.txt",
            LIVE_WATCHLIST_SIZE,
            window=ArtifactWindow("2016-07-11", "2026-08-07", 2514),
        )
    )
    dev2 = next(d for d in con if "artefactos" in d)
    assert "2016-07-11..2026-08-07" in dev2 and "RODANTE" in dev2


def test_artifact_window_is_computed_from_the_bars_without_io():
    bars = {"A": [("2020-01-02", 1, 1, 1, 1), ("2020-01-03", 1, 1, 1, 1)], "B": [("2019-12-31", 1, 1, 1, 1)]}
    w = artifact_window(bars)
    assert (w.start, w.end, w.n_bars) == ("2019-12-31", "2020-01-03", 2)
    assert artifact_window({}) is None
    assert artifact_window({"A": []}) is None


_W_HOY = ArtifactWindow("2016-07-11", "2026-08-07", 2514)
_W_VIEJA = ArtifactWindow("2016-06-20", "2026-07-19", 2514)
_LIVE_U = "data/harness_universe_live_acct2.txt"
_P_VIVO = ArtifactPopulation(_LIVE_U, 127)
_P_LEGACY = ArtifactPopulation("data/harness_universe_41_10y.txt", 41)


def test_reproduction_ok_when_the_number_reproduces():
    st, _ = reproduction_check(0.1277, 0.1277, tol=0.0005, current=_W_HOY, measured_on=_W_HOY)
    assert st == REPRO_OK


def test_reproduction_fails_only_when_the_whole_sample_is_the_same():
    """MISMA muestra + número distinto ⇒ cambió la cañería, que es lo que el sanity
    existe para detectar. Ahí sí corresponde invalidar la corrida. Desde la tarea 52
    "misma muestra" son **los dos ejes**: misma ventana y misma población."""
    st, why = reproduction_check(
        0.1277,
        0.1289,
        tol=0.0005,
        current=_W_HOY,
        measured_on=_W_HOY,
        population=_P_VIVO,
        measured_over=_P_VIVO,
    )
    assert st == REPRO_FAIL
    assert "cañería" in why


def test_a_moved_window_is_indeterminate_not_a_failure():
    """EL punto de la tarea 48: la T11b dejó de reproducir (12.89% → 12.77%) porque los
    artefactos se refrescaron, no porque se rompiera nada. Con dos estados eso se
    reportaba como FALLA ⇒ corrida INVÁLIDA: una máquina de invalidar corridas buenas
    con el paso del calendario."""
    st, why = reproduction_check(0.1277, 0.1289, tol=0.0005, current=_W_HOY, measured_on=_W_VIEJA)
    assert st == REPRO_INDETERMINATE
    assert "la ventana se movió" in why and "tarea 48" in why


def test_an_undeclared_reference_window_never_accuses_the_pipeline():
    """Default conservador: sin saber sobre qué muestra se midió la referencia, no se
    puede afirmar que cambió la cañería."""
    st, why = reproduction_check(0.1277, 0.1289, tol=0.0005, current=_W_HOY)
    assert st == REPRO_INDETERMINATE
    assert "no declara sobre qué ventana" in why


def test_a_missing_measurement_is_a_failure_not_an_indeterminate():
    """Si el brazo de reproducción ni siquiera corrió, no hay nada que interpretar."""
    st, _ = reproduction_check(None, 0.1289, tol=0.0005, current=_W_HOY, measured_on=_W_HOY)
    assert st == REPRO_FAIL


def test_the_anchor_constant_matches_the_measured_window():
    """Las constantes de reproducción de los runners están ancladas a esta ventana."""
    assert str(WINDOW_REFRESH_2026_08_09) == "2016-07-11..2026-08-07 (2514 barras)"


# ── Población (Tarea 52 — REPRO-POP) ─────────────────────────────────────────


def test_artifact_population_counts_the_tickers_that_loaded():
    """La población sale de las barras que **cargaron**, no de lo que el archivo de
    universo pretendía — que es lo mismo que el banner ya declara."""
    pop = artifact_population("u.txt", {"A": [1], "B": [2]}, n_entries=7)
    assert (pop.universe_file, pop.n_tickers, pop.n_entries) == ("u.txt", 2, 7)
    assert str(pop) == "u.txt (2 tickers, 7 entradas)"
    assert str(artifact_population("u.txt", n_tickers=41)) == "u.txt (41 tickers)"


def test_entries_are_compared_only_when_both_sides_declare_them():
    """Las anclas compartidas no declaran ``n_entries`` (dependen de la config del
    runner), así que compararlas contra las de la corrida acusaría por un desvío de
    config y no de muestra."""
    ancla = ArtifactPopulation("u.txt", 127)
    assert ancla.matches(ArtifactPopulation("u.txt", 127, 3210))
    assert ArtifactPopulation("u.txt", 127, 3210).matches(ancla)
    assert not ArtifactPopulation("u.txt", 127, 3210).matches(ArtifactPopulation("u.txt", 127, 2999))


def test_another_universe_is_not_applicable_not_a_failure():
    """EL punto de la tarea 52: el smoke de la 37 corrió sobre el universo legacy
    (41 tickers) contra anclas medidas sobre el vivo (127) **con la misma ventana**,
    y los tres chequeos salieron `FALLA — MISMA ventana ⇒ cambió la cañería`. No
    había cambiado ninguna línea de la cañería: cambió la muestra. Un `FALLA`
    invalida la corrida entera, así que el defecto puede matar una corrida buena."""
    st, why = reproduction_check(
        0.0693,
        0.0201,
        tol=0.0005,
        current=_W_HOY,
        measured_on=_W_HOY,
        population=_P_LEGACY,
        measured_over=_P_VIVO,
    )
    assert st == REPRO_NA
    assert "cañería" not in why and "tarea 52" in why


def test_not_applicable_wins_over_a_number_that_happens_to_match():
    """Sobre otra población el ancla no aplica, y que el número coincida es
    coincidencia: sigue sin haber reproducción que reportar."""
    st, _ = reproduction_check(
        0.0201,
        0.0201,
        tol=0.0005,
        current=_W_HOY,
        measured_on=_W_HOY,
        population=_P_LEGACY,
        measured_over=_P_VIVO,
    )
    assert st == REPRO_NA


def test_not_applicable_does_not_count_as_ok():
    """El estado nuevo no es un pase libre: los runners leen ``== REPRO_OK``, así que
    una corrida cuyo sanity no aplica no reprodujo nada y no puede dictar veredicto
    por ese lado (es lo que el parche local de la 37 hacía a mano)."""
    assert REPRO_NA != REPRO_OK


def test_a_sample_change_inside_the_same_universe_is_indeterminate():
    """Mismo universo pero otras entradas: no es otra población —el ancla sigue
    aplicando— pero tampoco es la misma muestra, así que no alcanza para acusar."""
    st, why = reproduction_check(
        0.1277,
        0.1289,
        tol=0.0005,
        current=_W_HOY,
        measured_on=_W_HOY,
        population=ArtifactPopulation(_LIVE_U, 127, 3210),
        measured_over=ArtifactPopulation(_LIVE_U, 127, 2999),
    )
    assert st == REPRO_INDETERMINATE
    assert "cambió la muestra dentro del universo" in why


def test_an_undeclared_population_never_accuses_the_pipeline():
    """Mismo default conservador que la ventana: para acusar hacen falta los dos
    ejes declarados. Antes de la 52 esto salía `FALLA`."""
    st, why = reproduction_check(0.1277, 0.1289, tol=0.0005, current=_W_HOY, measured_on=_W_HOY)
    assert st == REPRO_INDETERMINATE
    assert "no declara sobre qué población" in why


def test_a_moved_window_is_reported_as_the_window_even_with_populations():
    """Cuando se mueven los dos ejes manda la ventana: es la explicación más barata
    (un refresh de artefactos) y la que trae la instrucción de re-anclar."""
    st, why = reproduction_check(
        0.1277,
        0.1289,
        tol=0.0005,
        current=_W_HOY,
        measured_on=_W_VIEJA,
        population=_P_VIVO,
        measured_over=_P_VIVO,
    )
    assert st == REPRO_INDETERMINATE
    assert "la ventana se movió" in why


def test_the_anchor_populations_match_the_universe_files_on_disk():
    """Las anclas de los runners se midieron sobre estos universos. Si alguien
    refresca uno, esto falla: la acción correcta es **re-anclar las constantes**
    (re-correr y re-publicar el número), no cambiar el conteo a mano."""
    from scripts.precompute_pit_signals import parse_universe_file

    for pop in (POPULATION_LIVE_ACCT2, POPULATION_LEGACY_41):
        tickers = parse_universe_file(_REPO / pop.universe_file)
        assert len(tickers) == pop.n_tickers, pop.universe_file
        assert pop.n_entries is None


@pytest.mark.parametrize("script", REPRO_ANCHOR_RUNNERS)
def test_a_runner_with_live_anchors_declares_its_population(script):
    """Regresión del barrido de la 52: un runner que ancla contra un número
    publicado tiene que declarar **sobre qué población** se midió ese número. Sin
    ``measured_over`` el chequeo vuelve a ser ciego a la muestra."""
    txt = (_REPO / "scripts" / script).read_text(encoding="utf-8")
    assert txt.count("reproduction_check(") == txt.count("measured_over="), script
    assert txt.count("reproduction_check(") == txt.count("population="), script


# ── Tarea 58 (GRIDPOP) — la población de la grilla ───────────────────────────
#
# La 51 congeló seis valores de tope sin mirar la distribución de tenencia y dos
# de ellos no tocaban ningún trade. Estos tests fijan la distinción que la tarea
# existe para hacer visible: **inerte** (sacarlo de la grilla) no es lo mismo que
# **sin población** (medible, pero su resultado no refuta nada).


def _tenencias(**cuantos: int) -> list[int]:
    """``_tenencias(**{"3": 900})`` ⇒ 900 trades que duraron 3 ruedas."""
    out: list[int] = []
    for ruedas, n in cuantos.items():
        out.extend([int(ruedas.lstrip("d"))] * n)
    return out


def test_an_arm_touches_the_trades_that_reach_it():
    """La regla de *tocar* es ``medida >= valor``: es lo que hace un cap duro."""
    pop = grid_population([1, 5, 5, 10, 20], [5, 10])
    a5, a10 = pop.arms
    assert (a5.value, a5.n_hit) == (5, 4)
    assert (a10.value, a10.n_hit) == (10, 2)
    assert a5.share == 4 / 5


def test_an_arm_nobody_reaches_is_inert_not_insignificant():
    """El hallazgo de la 51: `N=40` sobre una cartera cuya tenencia máxima es 37
    da `Δ = 0.0000` porque **es el baseline con otro nombre**. Tiene que salir
    marcado como INERTE, no como "no significativo"."""
    pop = grid_population(_tenencias(d3=900, d17=220, d37=3), [10, 40])
    diez, cuarenta = pop.arms
    assert not diez.inert and cuarenta.inert
    assert cuarenta.n_hit == 0
    assert pop.viable == (10,)
    assert any("INERTE" in w for w in pop.warnings())


def test_underpowered_is_not_inert_and_asks_for_something_different():
    """Un brazo por debajo del 5% de la T13 **se puede medir** — lo que no se
    puede es leer su resultado como refutación (*sin poder, NO refutado*)."""
    pop = grid_population(_tenencias(d3=990, d30=10), [30])
    arm = pop.arms[0]
    assert arm.n_hit == 10 and arm.share == 0.01
    assert arm.underpowered and not arm.inert and not arm.viable
    assert any("SIN POBLACIÓN" in w and "NO refutado" in w for w in pop.warnings())


def test_the_threshold_is_the_one_the_T13_and_the_51_used():
    """Pin de consistencia: si alguien mueve el umbral en un runner y no acá (o al
    revés), dos partes del mismo sanity dirían cosas distintas."""
    from scripts.run_event_timestop_t51 import SANITY_MIN_POPULATION

    assert GRID_MIN_POPULATION == SANITY_MIN_POPULATION == 0.05


def test_percentiles_are_nearest_rank_over_real_trades():
    """Sin interpolar: un percentil tiene que ser una tenencia que **algún trade
    tuvo**, porque de ahí sale qué valores de grilla tienen población."""
    pop = grid_population(list(range(1, 11)), [5])
    assert (pop.p25, pop.p50, pop.p75) == (3, 5, 8)
    assert (pop.p90, pop.p99, pop.maximum) == (9, 10, 10)
    assert pop.mean == 5.5


def test_a_grid_with_population_says_nothing():
    """El banner se imprime siempre, pero **grita** sólo cuando hay algo que
    declarar: una grilla entera con población no tiene avisos."""
    pop = grid_population(_tenencias(d3=500, d20=500), [3, 10, 20])
    assert pop.warnings() == []
    assert pop.viable == (3, 10, 20)


def test_a_grid_that_is_entirely_dead_says_so_once_more():
    """El caso extremo, que es el de la 51 leído en su peor forma: si **ningún**
    valor tiene población, el problema no es el brazo elegido — es la pregunta."""
    pop = grid_population(_tenencias(d3=1000), [10, 20, 40])
    assert pop.viable == ()
    assert any("NINGÚN valor" in w for w in pop.warnings())


def test_announce_grid_prints_the_table_and_returns_it(capsys):
    """El par de ``announce()``: aquél declara la config antes de simular, éste
    declara la muestra de la grilla apenas hay baseline."""
    pop = announce_grid(_tenencias(d3=900, d17=100), [10, 40], file=None)
    out = capsys.readouterr().out
    assert "Población de la grilla" in out and "1000 trades" in out
    assert "INERTE" in out
    assert pop.n_trades == 1000 and pop.maximum == 17


def test_an_empty_portfolio_is_an_error_not_an_empty_table():
    """Sin trades no hay población que medir, y devolver una tabla vacía dejaría
    pasar un barrido sobre la nada."""
    with pytest.raises(ValueError):
        grid_population([], [10])


def test_the_grid_runner_declares_its_grid_population():
    """Regresión del cableado de la 58: el runner que barre una grilla de topes
    tiene que **declararla**, igual que declara ventana (48) y población (52). Sin
    esto el instrumento existe pero no lo llama nadie, que es exactamente cómo la
    51 llegó a correr dos brazos inertes."""
    txt = (_REPO / "scripts" / "run_event_timestop_t51.py").read_text(encoding="utf-8")
    assert "announce_grid(" in txt
