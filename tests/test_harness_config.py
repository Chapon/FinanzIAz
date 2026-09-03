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
  stale_artifacts            — la frescura del COHORTE de artefactos (T30): la ventana
                               es min(starts)..max(ends), así que uno congelado entra
                               en ella sin que nada lo declare — y uno refrescado de
                               más la corre. Se miran los dos lados
  effective_population       — la población EFECTIVA (T62): cuántas salidas cambian
                               de verdad, contra las que el umbral toca. La cruzada
                               es una cota superior —la 54 la midió sobrestimando
                               13×— y esto declara cuánto de esa cota se realiza.
                               Sanity POST-CORRIDA: no puede fijar la grilla
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from analysis.harness_config import (
    ARTIFACT_MAX_LAG_DAYS,
    ARTIFACT_REFRESH_EXCEPTIONS,
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
    WINDOW_REFRESH_2026_09_01_LEGACY,
    WINDOW_REFRESH_2026_09_01_LIVE,
    ArtifactPopulation,
    ArtifactWindow,
    HarnessConfig,
    StaleArtifactError,
    announce,
    announce_artifacts,
    announce_effective,
    announce_grid,
    artifact_population,
    artifact_window,
    cohort_end,
    config_banner,
    deviations,
    effective_population,
    exit_rule_line,
    grid_population,
    reproduction_check,
    stale_artifacts,
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
    """Con la config viva quedan **nueve** desvíos estructurales: la ventana de
    ``analyze()`` (T27), el precio de evaluación de las barreras (T32), el precio al
    que se llena esa barrera (T33), los gates de re-entrada (T34), la ventana
    RODANTE de los artefactos (T48) y la **política de salida** (T92: la cuenta
    apagó el stop duro el 2026-08-27 y el default del harness lo dejó encendido).
    Son los que se declaran en vez de corregirse."""
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE)
    devs = deviations(cfg)
    assert len(devs) == 9
    assert any("stop duro" in d for d in devs)
    # +3 (T94/95/96): overlay de vol, escalado por régimen y blackout de earnings
    assert any("overlay de volatilidad" in d for d in devs)
    assert any("escalado por régimen" in d for d in devs)
    assert any("blackout de earnings" in d for d in devs)
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
    assert len(devs) == 8  # +1 la política de salida (T92), +3 sizing y gates (T94/95/96)


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
# Con entradas en las DOS puntas: la única forma de que el sanity pueda acusar
# a la cañería (tarea 87).
_P_VIVO_CON_ENTRADAS = ArtifactPopulation(_LIVE_U, 127, 142_670)
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
        population=_P_VIVO_CON_ENTRADAS,
        measured_over=_P_VIVO_CON_ENTRADAS,
    )
    assert st == REPRO_FAIL
    assert "cañería" in why


def test_no_acusa_a_la_caneria_sin_poder_comparar_las_entradas():
    """**Tarea 87.** Misma ventana y mismo universo, pero el ancla NO declara sus
    entradas ⇒ no se puede confirmar que la muestra sea la misma, así que no se
    acusa.

    `matches()` devuelve `True` cuando alguna de las dos puntas no declara
    `n_entries` —*"no se puede acusar por un dato que nadie publicó"*—, pero ese
    `True` entraba como si fuera evidencia: **no declarar volvía al chequeo más
    confiado, exactamente al revés de su objetivo**. Y las dos anclas compartidas
    no lo declaran, así que ésta era la rama por default de los 8 call sites."""
    st, why = reproduction_check(
        0.1277,
        0.1289,
        tol=0.0005,
        current=_W_HOY,
        measured_on=_W_HOY,
        population=ArtifactPopulation(_LIVE_U, 127, 138_000),
        measured_over=_P_VIVO,  # el ancla no declara entradas
    )
    assert st == REPRO_INDETERMINATE
    assert "no se puede confirmar" in why
    assert "cañería" not in why or "acusar a la cañería" in why


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


def test_the_anchor_constants_match_the_measured_windows():
    """Las constantes de reproducción de los runners están ancladas a estas ventanas.

    **Son dos, una por universo (tarea 68).** El ancla anterior era una sola para
    los dos, y después del refresh de la 30 quedó demostrado que no se sostiene: la
    ventana viva y la legacy **difieren en el start**. Es el defecto que la 52
    corrigió para la población, un eje más allá."""
    assert str(WINDOW_REFRESH_2026_09_01_LIVE) == "2016-08-08..2026-09-01 (2514 barras)"
    assert str(WINDOW_REFRESH_2026_09_01_LEGACY) == "2016-09-01..2026-09-01 (2513 barras)"
    assert WINDOW_REFRESH_2026_09_01_LIVE != WINDOW_REFRESH_2026_09_01_LEGACY


def test_every_runner_anchors_to_a_window_that_declares_its_universe():
    """Regresión de la 68: ningún runner puede volver a importar un ancla de ventana
    que no diga sobre qué universo se midió. El nombre viejo no existe más **a
    propósito** — dejarlo como alias habría dejado pasar la elección equivocada en
    silencio, que es justo el modo de falla."""
    for script in sorted((_REPO / "scripts").glob("run_*.py")):
        txt = script.read_text(encoding="utf-8")
        assert "WINDOW_REFRESH_2026_08_09" not in txt, script.name


def test_the_live_window_start_rides_on_the_declared_refresh_exception():
    """El `start` de la ventana viva lo fija **AVB**, que a propósito no se refresca
    (tarea 63, declarada en `ARTIFACT_REFRESH_EXCEPTIONS`). O sea que este ancla
    depende de una excepción: si algún día AVB se refresca, se mueve **sola** y hay
    que re-anclar de nuevo. Queda fijado acá para que no se re-descubra."""
    assert "AVB" in ARTIFACT_REFRESH_EXCEPTIONS
    assert WINDOW_REFRESH_2026_09_01_LIVE.start < WINDOW_REFRESH_2026_09_01_LEGACY.start


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


# ── Población EFECTIVA — Tarea 62 (EXITPOP) ──────────────────────────────────
#
# La cruzada (58) es una **cota superior**: cuenta los trades que el umbral toca,
# no los que terminan saliendo distinto. La 54 midió las dos sobre la misma corrida
# y la brecha fue de 13×. Estos tests fijan las dos mitades de la decisión de la
# 62: qué se declara (las dos poblaciones y el factor de sobrestimación) y qué NO
# se convierte en gate (todo, menos la efectiva CERO).


def _sig(**por_trade):
    """``{clave: firma_de_salida}`` — ``T1="a|stop"`` ⇒ salida (a, stop)."""
    return {(k, "d1"): tuple(v.split("|")) for k, v in por_trade.items()}


def test_crossing_the_threshold_is_not_changing_the_exit():
    """El hallazgo de la 54: un trailing armado que **nunca dispara** deja la salida
    idéntica. Los tres cruzan el umbral; uno solo cambia de salida."""
    base = _sig(T1="a|stop", T2="b|tp", T3="c|signal")
    cand = _sig(T1="a|stop", T2="b|tp", T3="z|trail")
    pop = effective_population(base, cand, crossed=base.keys())
    assert pop.n_crossed == 3 and pop.n_changed == 1
    assert pop.crossed_share == 1.0 and pop.share == 1 / 3
    assert pop.realization == 1 / 3
    assert any("SOBRESTIMA 3.0×" in w for w in pop.warnings())


def test_an_arm_that_changes_no_exit_is_inert_not_insignificant():
    """El único estado terminante de la 62, y no necesita umbral: si no cambia NI
    UNA salida, es el baseline con otro nombre en la punta que importa."""
    base = _sig(T1="a|stop", T2="b|tp")
    pop = effective_population(base, dict(base), crossed=base.keys())
    assert pop.inert and not pop.thin
    assert pop.share == 0.0
    ws = pop.warnings()
    assert any("NI UNA salida" in w for w in ws)
    # y el factor de sobrestimación no explota en el borde: cruzan dos, realiza cero
    assert pop.realization == 0.0
    assert any("cota superior de cero" in w for w in ws)


def test_the_effective_population_is_an_aviso_and_the_crossed_one_stays_the_gate():
    """La decisión de la 62 escrita como test: el ≥5% se calibró sobre la cruzada,
    así que leerlo sobre la efectiva es un **aviso**, no un criterio. El aviso usa
    la misma constante a propósito — es el listón que la corrida declaró pasar."""
    base = {(f"T{i}", "d1"): ("a", "stop") for i in range(100)}
    cand = dict(base)
    cand[("T0", "d1")] = ("z", "trail")  # 1 de 100 = 1% efectiva
    pop = effective_population(base, cand, crossed=[(f"T{i}", "d1") for i in range(40)])
    assert pop.crossed_share == 0.40  # la cruzada pasa el gate con holgura
    assert pop.share == 0.01 and pop.thin and not pop.inert
    assert pop.min_share == GRID_MIN_POPULATION
    aviso = next(w for w in pop.warnings() if "EFECTIVA" in w)
    assert "NO es un gate" in aviso and "casi no se ejecutó" in aviso


def test_a_trade_the_arm_never_took_is_not_a_changed_exit():
    """Sólo se comparan los trades **comunes**: en los que el brazo no tomó no hay
    con qué comparar, y contarlos como *cambiados* inflaría la efectiva justo
    donde la cascada de slots ya mueve la cartera entera."""
    base = _sig(T1="a|stop", T2="b|tp", T3="c|signal")
    cand = _sig(T1="a|stop", T3="z|trail")
    pop = effective_population(base, cand)
    assert pop.n_common == 2 and pop.n_changed == 1
    assert pop.realization is None  # sin cruzada declarada, sin factor


def test_the_crossed_population_only_counts_keys_both_sides_took():
    """Una clave cruzada que el brazo no tomó no es población de nada: el factor de
    sobrestimación se mide sobre lo comparable, o mentiría hacia arriba."""
    base = _sig(T1="a|stop", T2="b|tp")
    cand = _sig(T1="z|trail")
    pop = effective_population(base, cand, crossed=[("T1", "d1"), ("T2", "d1")])
    assert pop.n_crossed == 1 and pop.n_changed_in_crossed == 1
    assert pop.realization == 1.0


def test_no_common_trades_says_it_cannot_be_measured():
    """El borde: sin trades comunes la efectiva **no se puede medir**, y decir 0%
    la haría pasar por *inerte* — que es una afirmación mucho más fuerte."""
    pop = effective_population(_sig(T1="a|stop"), _sig(T9="b|tp"))
    assert pop.n_common == 0 and not pop.inert and not pop.thin
    assert any("NINGÚN trade en común" in w for w in pop.warnings())


def test_announce_effective_prints_both_populations(capsys):
    """El banner declara **las dos**: la cota y lo que se realizó. Es el tercer
    momento del harness y el único que no se puede adelantar."""
    base = _sig(T1="a|stop", T2="b|tp", T3="c|signal", T4="d|tp")
    cand = _sig(T1="a|stop", T2="b|tp", T3="c|signal", T4="z|trail")
    pop = announce_effective(base, cand, crossed=base.keys(), file=None)
    out = capsys.readouterr().out
    assert "Población EFECTIVA" in out and "POST-CORRIDA" in out
    assert "cruzada (cota sup.)" in out and "efectiva" in out
    assert pop.n_changed == 1 and pop.n_crossed == 4


def test_the_effective_population_cannot_be_computed_before_the_arm_runs():
    """La regla de orden, fijada donde se puede fijar: ``announce_grid`` sólo pide
    la cartera del **baseline** (se puede llamar antes de congelar el pre-registro)
    y ``announce_effective`` pide **las dos**, o sea el brazo ya corrido. Si alguien
    le sacara el segundo argumento, un pre-registro podría pedirla como criterio de
    grilla — que es el error que la 62 vino a dejar por escrito."""
    import inspect

    grid_args = list(inspect.signature(announce_grid).parameters)
    eff_args = list(inspect.signature(announce_effective).parameters)
    assert grid_args[:2] == ["per_trade", "grid"]
    assert eff_args[:2] == ["base_exits", "cand_exits"]


def test_the_exit_runner_declares_its_effective_population():
    """Regresión del cableado de la 62, con el mismo criterio que la 58: si el
    instrumento existe pero no lo llama nadie, la próxima corrida vuelve a publicar
    la cota superior como si fuera la muestra."""
    txt = (_REPO / "scripts" / "run_trail_arm_t54.py").read_text(encoding="utf-8")
    assert "announce_effective(" in txt
    assert '"effective_population": eff_pop.as_dict()' in txt


def test_the_t54_descriptive_keeps_the_four_keys_it_published():
    """El cómputo se subió a ``harness_config``, pero el JSON publicado de la 54 se
    sigue leyendo igual: mover una clave rompería la lectura del artefacto sin que
    ningún número haya cambiado."""
    from dataclasses import dataclass

    from scripts.run_trail_arm_t54 import changed_exits

    @dataclass
    class _T:
        ticker: str
        entry_date: str
        exit_date: str
        exit_reason: str

    @dataclass
    class _R:
        trades: list

    base = _R([_T("A", "d1", "x", "stop"), _T("B", "d1", "y", "tp")])
    cand = _R([_T("A", "d1", "x", "stop"), _T("B", "d1", "z", "trail")])
    d = changed_exits(base, cand, {("B", "d1")})
    assert set(d) == {"n_common", "n_changed", "share", "n_changed_in_diff_pop"}
    assert d == {"n_common": 2, "n_changed": 1, "share": 0.5, "n_changed_in_diff_pop": 1}


# ── Frescura del cohorte de artefactos — Tarea 30 (DOC-SYNC) ─────────────────
#
# `artifact_window` declara min(starts)..max(ends), y esa agregación **esconde**
# el defecto: un artefacto congelado no mueve el max(ends) —lo tapan los otros
# 505— pero sí puede quedarse con el min(starts), y así entra en la ventana
# publicada sin que nada lo declare.
#
# Eso ya había pasado: el ancla de la T48 (`2016-07-11..2026-08-07`) tenía el
# **end** de los 503 artefactos sanos y el **start del artefacto congelado de
# TSM**. Estos tests fijan las tres decisiones de diseño que salen de ahí.


def _bars(fechas: list[str]) -> list[tuple]:
    return [(f, 1.0, 1.0, 1.0, 1.0, 1000.0) for f in fechas]


def _cohorte(n: int = 10, fin: str = "2026-08-07") -> dict[str, list]:
    return {f"T{i}": _bars(["2016-01-04", fin]) for i in range(n)}


def test_a_uniform_cohort_has_nothing_to_declare():
    assert stale_artifacts(_cohorte()) == ()
    assert cohort_end(_cohorte()) == "2026-08-07"


def test_a_frozen_artifact_is_caught_even_though_the_window_hides_it():
    """El caso literal de la 30: uno congelado entre 500 sanos. La ventana no se
    entera —el max(ends) lo tapan los otros— y por eso hace falta esto."""
    c = _cohorte()
    c["VIEJO"] = _bars(["2016-01-04", "2026-06-02"])
    fuera = stale_artifacts(c)
    assert [s.ticker for s in fuera] == ["VIEJO"]
    assert fuera[0].lag_days == 48 and not fuera[0].ahead

    # y la ventana efectivamente NO lo delata
    assert artifact_window(c).end == "2026-08-07"


def test_an_artifact_refreshed_AHEAD_is_just_as_broken():
    """La otra mitad, y es la que se destapó al refrescar TSM: un refresh **parcial**
    rompe la uniformidad igual que uno faltante — y encima corre el max(ends), así
    que es **más** visible en el resultado y **menos** en el diagnóstico."""
    c = _cohorte()
    c["NUEVO"] = _bars(["2016-01-04", "2026-09-01"])
    fuera = stale_artifacts(c)
    assert [s.ticker for s in fuera] == ["NUEVO"]
    assert fuera[0].ahead and fuera[0].lag_days == -17
    assert artifact_window(c).end == "2026-09-01"  # la ventana SÍ se movió


def test_the_reference_is_the_MODE_not_the_max():
    """Con el máximo, un solo artefacto refrescado de más haría aparecer a los otros
    505 como atrasados y el aviso señalaría a todo el mundo menos al culpable."""
    c = _cohorte(n=20)
    c["NUEVO"] = _bars(["2016-01-04", "2026-09-01"])
    assert cohort_end(c) == "2026-08-07"
    assert [s.ticker for s in stale_artifacts(c)] == ["NUEVO"]


def test_a_ticker_that_missed_a_day_is_not_a_stale_artifact():
    """La tolerancia existe para el ticker que no operó (halt, feriado propio). Los
    tres casos reales estaban a 14, 21 y 48 ruedas: muy lejos de este borde."""
    c = _cohorte()
    c["HALT"] = _bars(["2016-01-04", "2026-08-05"])  # 2 ruedas
    assert stale_artifacts(c) == ()


def test_the_tolerance_sits_between_a_missed_day_and_the_real_cases():
    assert 2 < ARTIFACT_MAX_LAG_DAYS < 14


def test_the_lag_is_counted_in_TRADING_days_not_calendar_days():
    """21 ruedas entre el 2026-07-09 y el 2026-08-07 son **29 días** de calendario:
    contar corridos haría que la tolerancia signifique otra cosa según el mes."""
    c = _cohorte()
    c["TSM"] = _bars(["2016-01-04", "2026-07-09"])
    assert stale_artifacts(c)[0].lag_days == 21


def test_announce_prints_and_raises_by_default(capsys):
    """Política de la T22: fallar ruidoso, no degradar en silencio. Y **antes** de
    pagar la corrida: si la muestra está torcida, no vale la pena esperar 4 minutos
    para enterarse."""
    c = _cohorte()
    c["VIEJO"] = _bars(["2016-01-04", "2026-06-02"])
    with pytest.raises(StaleArtifactError, match="VIEJO"):
        announce_artifacts(c, file=None)
    out = capsys.readouterr().out
    assert "Frescura del cohorte" in out and "48 ruedas atrás del cohorte" in out


def test_announce_can_be_told_to_only_declare(capsys):
    """`strict=False` es para un harness que corre sobre un cohorte mezclado **a
    propósito** y lo dice en su pre-registro — no para tapar el aviso."""
    c = _cohorte()
    c["VIEJO"] = _bars(["2016-01-04", "2026-06-02"])
    fuera = announce_artifacts(c, strict=False, file=None)
    assert len(fuera) == 1
    assert "AVISO" in capsys.readouterr().out


def test_a_clean_cohort_says_so_out_loud(capsys):
    """Se imprime siempre, esté bien o mal — mismo precedente que la 48, la 52 y la
    58: la muestra se declara, no sólo cuando hay un problema."""
    announce_artifacts(_cohorte(), file=None)
    assert "todos alineados" in capsys.readouterr().out


def test_no_bars_is_not_an_accusation():
    assert stale_artifacts({}) == () and cohort_end({}) == ""
    assert stale_artifacts({"X": []}) == ()


def test_a_declared_exception_does_not_abort_but_IS_announced(capsys):
    """AVB no se refresca **a propósito** (tarea 63: su `10y` es la escala sana
    contra la que se detecta el split fantasma del `2y`). Una excepción declarada
    no puede abortar la corrida — pero tampoco puede quedarse callada, o vuelve a
    ser el defecto que la 30 vino a arreglar."""
    c = _cohorte()
    c["AVB"] = _bars(["2016-01-04", "2026-06-02"])
    assert stale_artifacts(c) == ()  # no acusa
    announce_artifacts(c, file=None)  # y NO levanta
    out = capsys.readouterr().out
    assert "[excepción declarada] AVB" in out
    assert "split FANTASMA" in out  # el motivo, no sólo el nombre


def test_the_exception_is_a_dict_so_adding_one_forces_writing_the_reason():
    """Una lista dejaría agregar un ticker sin explicar por qué, que es como se
    empieza a acumular deuda invisible en un guard."""
    assert isinstance(ARTIFACT_REFRESH_EXCEPTIONS, dict)
    assert all(len(v) > 40 for v in ARTIFACT_REFRESH_EXCEPTIONS.values())
    assert "AVB" in ARTIFACT_REFRESH_EXCEPTIONS


def test_an_exception_that_is_ALIGNED_is_not_announced_as_one(capsys):
    """Si el ticker exceptuado igual coincide con el cohorte, no hay nada que
    declarar: el aviso es para la desalineación, no para la etiqueta."""
    c = _cohorte()
    c["AVB"] = _bars(["2016-01-04", "2026-08-07"])
    announce_artifacts(c, file=None)
    assert "excepción declarada" not in capsys.readouterr().out


def _runners_que_leen_el_cohorte() -> list[tuple[str, str]]:
    """Los ``run_*.py`` que arman su muestra del cohorte de artefactos.

    El predicado es *"lee el sustrato compartido"*, no *"es un runner"*: de los 32
    ``run_*.py``, **21** construyen ``bars_by`` desde el Parquet (vía uno de los
    ``load_bars_*`` o leyendo ``parquet_cache`` a mano) o declaran su ventana con
    ``artifact_window``. Los otros 11 no tocan el cohorte y quedan afuera **a
    propósito** — exigirles el guard sería ruido.
    """
    import re as _re

    out = []
    for p in sorted((_REPO / "scripts").glob("run_*.py")):
        txt = p.read_text(encoding="utf-8")
        if _re.search(
            r"load_bars_signals|load_bars_and_signals|parquet_cache\.read|artifact_window\(", txt
        ):
            out.append((p.name, txt))
    return out


def test_the_cohort_runners_are_a_real_population():
    """Sanity: si el barrido diera 0 o 1, los dos tests de abajo pasarían vacíos."""
    assert len(_runners_que_leen_el_cohorte()) >= 20


def test_every_cohort_runner_checks_freshness_before_paying_for_the_run():
    """**Todos** los que leen el cohorte lo chequean — no sólo el que tenía la pregunta viva.

    El guard de la T30 es sobre el **sustrato compartido**: los runners leen el
    mismo cohorte de artefactos, así que cablearlo en uno solo no protege nada,
    sólo hace creer que sí (tarea 76). Es distinto del ``announce_grid`` de la 58,
    que sí es sobre la grilla **de ese** runner — el precedente no transfiere.
    """
    faltan = [
        n
        for n, txt in _runners_que_leen_el_cohorte()
        if "announce_artifacts(" not in txt or "--allow-stale-artifacts" not in txt
    ]
    assert faltan == [], f"leen el cohorte y no lo chequean: {faltan}"


def test_the_cohort_check_comes_before_announce():
    """Y va **antes** de `announce`, o el harness ya declaró una config que no va a honrar."""
    for n, txt in _runners_que_leen_el_cohorte():
        if "announce(" not in txt:
            continue  # no declara config (p.ej. el T7): igual chequea, pero no hay orden que fijar
        assert txt.index("announce_artifacts(") < txt.index("announce("), n


def test_every_cohort_runner_declares_its_window():
    """La tercera pata (tarea 83): el que lee el cohorte **dice sobre qué ventana corrió**.

    La ventana de los artefactos es **rodante** (T48), así que un veredicto que no
    la declara **no se puede reproducir después de un refresh** — no porque el
    número esté mal, sino porque no hay contra qué compararlo. Es lo que obligó a
    la 68 a re-anclar 17 constantes.

    Esta pata **no existía** cuando se cableó la 76: dos runners la incumplían (el
    T46 llamaba `announce` con `0` tickers y sin ventana, el T7 no declaraba
    nada), y escribirla entonces habría sido escribirla con dos excepciones
    adentro.
    """
    faltan = [n for n, txt in _runners_que_leen_el_cohorte() if "artifact_window(" not in txt]
    assert faltan == [], f"leen el cohorte y no declaran su ventana: {faltan}"


def test_the_cohort_check_sees_a_cohort_that_actually_exists():
    """El guard tiene que estar donde `bars_by` **está en alcance**, no donde se lee lindo.

    Regresión de un defecto que introdujo la propia 76: en `run_regime_power_t46`
    el bloque quedó en `main`, donde `bars_by` **no existe** —el cohorte lo arma
    la función de población, más abajo—, así que el runner moría con `NameError`
    al correrlo. El chequeo textual de la 76 no podía verlo: el nombre aparecía
    antes **en el archivo**, en otra función.
    """
    import ast

    rotos = []
    for n, txt in _runners_que_leen_el_cohorte():
        if "announce_artifacts(" not in txt:
            continue
        for fn in ast.walk(ast.parse(txt)):
            if not isinstance(fn, ast.FunctionDef):
                continue
            llamadas = [
                c
                for c in ast.walk(fn)
                if isinstance(c, ast.Call)
                and isinstance(c.func, ast.Name)
                and c.func.id == "announce_artifacts"
            ]
            if not llamadas:
                continue
            asignada = any(
                isinstance(nodo, ast.Assign)
                and nodo.lineno < llamadas[-1].lineno
                and any(
                    x.id == "bars_by"
                    for t in nodo.targets
                    for x in ([t] if isinstance(t, ast.Name) else [e for e in getattr(t, "elts", []) if isinstance(e, ast.Name)])
                )
                for nodo in ast.walk(fn)
            )
            if not asignada:
                rotos.append(f"{n}:{fn.name}")
    assert rotos == [], f"llaman announce_artifacts sin bars_by en alcance: {rotos}"
