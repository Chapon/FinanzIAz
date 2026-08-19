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
  defaults de los runners    — regresión: ningún harness vuelve a heredar en
                               silencio los 5 slots de la cuenta pausada ni el fill
                               look-ahead de la barrera decidida al close
  refresh_live_universe      — filtra la watchlist por artefacto PIT disponible
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from analysis.harness_config import (
    HARNESS_FILL_MODE,
    LEGACY_FILL_MODE,
    LEGACY_MAX_POSITIONS,
    LIVE_ACCOUNT_ID,
    LIVE_MAX_POSITIONS,
    LIVE_WATCHLIST_SIZE,
    HarnessConfig,
    announce,
    config_banner,
    deviations,
    exit_rule_line,
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
REPLAY_RUNNERS = PORTFOLIO_RUNNERS + [
    "run_scaleout_replay_t7.py",
    "run_stop_price_replay_t26b.py",
]


# ── deviations / banner ──────────────────────────────────────────────────────


def test_legacy_config_declares_slots_and_universe():
    cfg = HarnessConfig(LEGACY_MAX_POSITIONS, "data/harness_universe_41_10y.txt", 41)
    devs = deviations(cfg)
    assert any("slots 5 vs 10" in d for d in devs)
    assert any("41 tickers" in d for d in devs)


def test_live_config_only_declares_the_structural_deviations():
    """Con la config viva quedan **cuatro** desvíos estructurales: la ventana de
    ``analyze()`` (T27), el precio de evaluación de las barreras (T32), el precio al
    que se llena esa barrera (T33) y los gates de re-entrada (T34). Son los que se
    declaran en vez de corregirse."""
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE)
    devs = deviations(cfg)
    assert len(devs) == 4
    assert any("ventana de analyze()" in d for d in devs)
    assert any("barreras ATR" in d for d in devs)
    assert any("fill de la barrera" in d for d in devs)
    assert any("gates de re-entrada" in d for d in devs)


def test_reentry_gates_deviation_is_declared_unless_modelled():
    """T34 — el sexto desvío. ``portfolio_sim`` nunca modeló los gates de re-entrada
    del engine, así que mientras no se los modele hay que decirlo, **con el número que
    vale**: el defecto no es que existan, es que el harness los ignore en silencio."""
    off = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE)
    dev = next(d for d in deviations(off) if "gates de re-entrada" in d)
    assert "Gate 5" in dev and "Gate 5b" in dev
    assert "21,15%-36,36%" in dev          # el costo medido, no una vaguedad
    assert "gates de re-entrada" in config_banner(off)


def test_modelling_the_reentry_gates_removes_the_deviation():
    """Con ``live_gates=True`` el harness deja de desviarse en ese eje, así que el
    desvío **no** se anuncia — mismo patrón que ``fill_mode`` bajo ``touch``."""
    on = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE, live_gates=True)
    devs = deviations(on)
    assert not any("gates de re-entrada" in d for d in devs)
    assert len(devs) == 3


def test_signal_window_deviation_is_always_declared():
    """No es condicional: mientras los artefactos PIT sean los actuales, la ventana
    difiere siempre y tiene que decirlo aunque todo lo demás coincida."""
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE + 50)
    assert any("ventana de analyze()" in d for d in deviations(cfg))


def test_exit_eval_price_deviation_is_always_declared():
    """T32 — el cuarto desvío: el harness decide las barreras ATR al **close** y el
    engine vivo al **precio intradía**. Es estructural de ``replay_cycle``, así que
    no depende de cómo se invoque al harness: se declara siempre."""
    for cfg in (HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE),
                HarnessConfig(LEGACY_MAX_POSITIONS, "y.txt", 41)):
        devs = deviations(cfg)
        assert any("barreras ATR" in d and "close diario" in d for d in devs)


def test_the_false_fill_claim_never_comes_back():
    """T33 — la T32 declaraba *"el fill sí está modelado; la decisión no"*, y esa
    media verdad tapó el look-ahead durante cinco harness: en modo ``close`` el fill
    **no** estaba modelado, estaba mal. Si alguien reintroduce la frase, esto falla."""
    for fm in (HARNESS_FILL_MODE, LEGACY_FILL_MODE):
        cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE,
                            fill_mode=fm)
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
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE,
                        fill_mode=LEGACY_FILL_MODE)
    dev = next(d for d in deviations(cfg) if "LOOK-AHEAD" in d)
    assert "NIVEL" in dev and "+5.01 pp" in dev
    assert "LOOK-AHEAD" in config_banner(cfg)


def test_at_touch_there_is_no_fill_deviation_at_all():
    """Bajo ``touch`` el precio que decide **es** el nivel, así que los dos fill_mode
    coinciden entre sí y con ``gates.model_exit_fill_price`` del engine: no hay nada
    que declarar, ni siquiera con el legacy."""
    for fm in (HARNESS_FILL_MODE, LEGACY_FILL_MODE):
        cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE,
                            eval_mode="touch", fill_mode=fm)
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
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", 41,
                        verdict_max_positions=LEGACY_MAX_POSITIONS)
    txt = config_banner(cfg)
    assert "--max-positions 5" in txt


def test_banner_is_quiet_when_verdict_config_matches():
    cfg = HarnessConfig(LEGACY_MAX_POSITIONS, "x.txt", 41,
                        verdict_max_positions=LEGACY_MAX_POSITIONS)
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
    txt = (_REPO / "scripts" / script).read_text(encoding="utf-8")
    assert "announce(args.max_positions" in txt


@pytest.mark.parametrize("script", REPLAY_RUNNERS)
def test_runner_exposes_fill_mode_and_defaults_to_the_honest_one(script):
    """T33 — el defecto que esta tarea arregla: el fill legacy era el default y un
    harness nuevo lo heredaba en silencio. Cada runner que corre sobre
    ``replay_cycle`` tiene que poder elegirlo **y** arrancar en el honesto, para que
    el veredicto publicado siga siendo reproducible sin volver a ser el default."""
    txt = (_REPO / "scripts" / script).read_text(encoding="utf-8")
    assert '"--fill-mode"' in txt
    assert f'default={LEGACY_FILL_MODE!r}' not in txt
    assert 'default="resting"' not in txt


def test_replay_library_defaults_to_the_honest_fill():
    """El default vive en la librería, no en los runners: si vuelve a ``resting``,
    todo harness nuevo escrito en modo ``close`` nace con look-ahead."""
    import inspect

    from analysis.portfolio_sim import simulate_portfolio
    from analysis.scaleout_replay import replay_cycle

    for fn in (replay_cycle, simulate_portfolio):
        assert (inspect.signature(fn).parameters["fill_mode"].default
                == HARNESS_FILL_MODE)


def test_live_universe_file_exists_and_is_parseable():
    from scripts.precompute_pit_signals import parse_universe_file
    from analysis.harness_config import LIVE_UNIVERSE_FILE

    path = _REPO / LIVE_UNIVERSE_FILE
    assert path.exists(), "correr scripts/refresh_live_universe.py"
    tickers = parse_universe_file(path)
    assert len(tickers) > 100
    assert len(tickers) == len(set(tickers))


# ── refresh_live_universe ────────────────────────────────────────────────────


def _make_db(path: Path, tickers: list[str], account_id: int = 2) -> None:
    con = sqlite3.connect(path)
    con.execute("create table paper_watchlist (account_id int, ticker text)")
    con.executemany("insert into paper_watchlist values (?, ?)",
                    [(account_id, t) for t in tickers])
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
    con.executemany("insert into paper_watchlist values (?, ?)",
                    [(1, "OLD"), (2, "NEW"), (2, "NEW")])
    con.commit()
    con.close()
    assert watchlist_tickers(db, 2) == ["NEW"]      # distinct
    assert watchlist_tickers(db, 1) == ["OLD"]


def test_pit_tickers_on_missing_dir_is_empty(tmp_path):
    from scripts.refresh_live_universe import pit_tickers

    assert pit_tickers(tmp_path / "nope") == set()
