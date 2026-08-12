"""
Tests de ``analysis/harness_config`` y del universo vivo — Tarea 27 (HARNESS-CFG).

Todo offline: sin DB, sin red. Los tests del refresh usan una DB SQLite temporal.

Cubre:
  deviations / config_banner — los tres desvíos del §1 del análisis profundo:
                               slots, tamaño de universo y ventana de analyze()
  verdict_max_positions      — el aviso de reproducibilidad cuando el default nuevo
                               no reproduce el veredicto publicado
  announce                   — imprime y devuelve la config
  defaults de los runners    — regresión: ningún harness vuelve a heredar en
                               silencio los 5 slots de la cuenta pausada
  refresh_live_universe      — filtra la watchlist por artefacto PIT disponible
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from analysis.harness_config import (
    LEGACY_MAX_POSITIONS,
    LIVE_ACCOUNT_ID,
    LIVE_MAX_POSITIONS,
    LIVE_WATCHLIST_SIZE,
    HarnessConfig,
    announce,
    config_banner,
    deviations,
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
]


# ── deviations / banner ──────────────────────────────────────────────────────


def test_legacy_config_declares_slots_and_universe():
    cfg = HarnessConfig(LEGACY_MAX_POSITIONS, "data/harness_universe_41_10y.txt", 41)
    devs = deviations(cfg)
    assert any("slots 5 vs 10" in d for d in devs)
    assert any("41 tickers" in d for d in devs)


def test_live_config_only_declares_the_signal_window():
    """Con la config viva no debería quedar más desvío que la ventana de
    ``analyze()``, que es el que esta tarea declara en vez de corregir."""
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE)
    devs = deviations(cfg)
    assert len(devs) == 1
    assert "ventana de analyze()" in devs[0]


def test_signal_window_deviation_is_always_declared():
    """No es condicional: mientras los artefactos PIT sean los actuales, la ventana
    difiere siempre y tiene que decirlo aunque todo lo demás coincida."""
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE + 50)
    assert any("ventana de analyze()" in d for d in deviations(cfg))


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
