"""Tarea 128 (ACCT1-VALIDADOR) — el instrumento con el que se mide la 129.

``scripts/run_universe_screen_validation.py`` es el validador del kill-criteria de
E1b, y la tarea 129 lo necesita para responder si el screen —encendido en vivo el
2026-09-07 sobre los 128 tickers de la cuenta 2— recorta nombres buenos. Estaba
roto por los dos lados:

* **apuntaba a la cuenta pausada.** ``--account-id`` defaulteaba a
  ``DEFAULT_ACCOUNT_ID = 1``, y la 1 está en ``is_active=0`` desde el 2026-07-01.
  Sin flag medía la watchlist de una cuenta muerta, y —peor— no daba vacío: daba
  una tabla de 52 nombres perfectamente plausible.
* **reportaba un NO-SHIP falso.** El ``--expect-fragile MLTX`` por default exige
  que MLTX quede excluido, y MLTX **no está en la watchlist de la cuenta 2**. Contra
  el universo vivo eso da ``fragile_missed=["MLTX"]`` ⇒ ``kill_pass=False`` ⇒
  **exit 1**, salvo que alguien supiera pasarle ``--expect-fragile ""``.

El guard que tenía que cazar el primero vive en ``test_account_defaults_t99.py`` y
tenía su propio punto ciego (leía el fallo de lectura como aprobación); ahí está el
arreglo del guard y su batería de mutación. Acá se prueba el **comportamiento del
script**, que es lo que la 129 va a correr.

No usa red: ``get_fundamental_facts`` y el ADV$ salen de stubs, así que lo que se
mide es la lógica del veredicto y no EDGAR.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import data.yahoo_finance as yf
import scripts.run_universe_screen_validation as runner
from data.edgar_fundamentals import FundamentalFacts

# ── Andamios ─────────────────────────────────────────────────────────────────


def _facts(ticker: str, ni: tuple[float, ...], revenue: float | None) -> FundamentalFacts:
    """Hechos anuales sintéticos, más nuevo primero (el orden que usa el screen)."""
    return FundamentalFacts(
        ticker=ticker,
        net_income_annual=tuple((f"{2025 - i}-12-31", v) for i, v in enumerate(ni)),
        revenue_annual=() if revenue is None else ((("2025-12-31", revenue),)),
    )


# MLTX: pérdidas sostenidas + sin revenue ⇒ el nombre frágil que E1b existe para sacar.
_FRAGIL = {"MLTX": _facts("MLTX", (-90e6, -75e6), None)}


@pytest.fixture
def sin_red(monkeypatch):
    """El screen corre con hechos de laboratorio: nada de EDGAR ni de yfinance.

    Por default **todos los nombres son sanos** (revenue grande, ganancias), así
    que un veredicto de exclusión en un test sale de lo que ese test declara en
    ``_FRAGIL`` o en su propio stub, y no de un dato de fondo.
    """

    def _fake_facts(ticker: str) -> FundamentalFacts:
        return _FRAGIL.get(ticker, _facts(ticker, (5e9, 4e9), 90e9))

    monkeypatch.setattr(runner, "get_fundamental_facts", _fake_facts)
    monkeypatch.setattr(runner, "recent_adv_dollars", lambda *a, **kw: 5e8)
    monkeypatch.setattr(yf, "get_historical_data", lambda *a, **kw: object())
    monkeypatch.setattr(yf, "get_historical_data_batch", lambda *a, **kw: {})


@pytest.fixture
def db(tmp_path) -> Path:
    """La 1 PAUSADA con watchlist propia y la 2 activa con la suya — el estado real."""
    ruta = tmp_path / "finanzias.db"
    con = sqlite3.connect(ruta)
    con.execute(
        "CREATE TABLE paper_accounts (id INTEGER PRIMARY KEY, name TEXT, initial_capital REAL, "
        "cash REAL, is_active INTEGER, allocation_mode TEXT, strategy TEXT, created_at TEXT)"
    )
    con.executemany(
        "INSERT INTO paper_accounts VALUES (?,?,?,?,?,?,?,?)",
        [
            (1, "Sim Principal", 50_000.0, 0.0, 0, "equal_weight", "auto", "2026-05-01"),
            (2, "Sim Segundo", 50_000.0, 0.0, 1, "equal_weight", "auto", "2026-07-01"),
        ],
    )
    con.execute("CREATE TABLE paper_watchlist (id INTEGER PRIMARY KEY, account_id INTEGER, ticker TEXT)")
    con.executemany(
        "INSERT INTO paper_watchlist (account_id, ticker) VALUES (?,?)",
        [(1, "MLTX"), (1, "AAPL"), (2, "AAPL"), (2, "JPM"), (2, "DUK")],
    )
    con.commit()
    con.close()
    return ruta


def _corrida(capsys, *argv: str) -> tuple[int, dict]:
    """``(exit_code, json)`` de una corrida. El JSON es el contrato que lee la 129."""
    code = runner.main([*argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


# ── Qué cuenta mide ──────────────────────────────────────────────────────────


def test_sin_flag_mide_la_cuenta_VIVA_y_no_la_pausada(sin_red, db, capsys):
    """El corazón del arreglo. Antes esto devolvía la watchlist de la cuenta 1."""
    code, out = _corrida(capsys, "--db", str(db))
    assert out["account_id"] == 2
    assert {r["ticker"] for r in out["results"]} == {"AAPL", "JPM", "DUK"}
    assert code == 0


def test_un_flag_explicito_a_la_pausada_se_respeta_pero_avisa(sin_red, db, capsys):
    """Mandó el operador —reproducir un número histórico es legítimo— pero **no en
    silencio**: es la decisión de diseño de la tarea 70 que la 99 dejó cableada."""
    code = runner.main(["--db", str(db), "--account-id", "1", "--json"])
    salida = capsys.readouterr()
    assert json.loads(salida.out)["account_id"] == 1
    assert "PAUSADA" in salida.err
    assert code == 0


def test_sin_ninguna_cuenta_activa_NO_adivina(sin_red, db, capsys):
    """Levanta y se corta con un mensaje, en vez de elegir una cuenta por su cuenta."""
    con = sqlite3.connect(db)
    con.execute("UPDATE paper_accounts SET is_active = 0")
    con.commit()
    con.close()

    assert runner.main(["--db", str(db)]) == 2
    assert "No se pudo resolver la cuenta" in capsys.readouterr().err


# ── El NO-SHIP falso ─────────────────────────────────────────────────────────


def test_un_fragil_esperado_AUSENTE_del_universo_no_produce_un_NO_SHIP(sin_red, capsys):
    """El segundo defecto, en su forma exacta: MLTX no está en la watchlist de la
    cuenta 2, y exigirle al screen que lo excluya daba **exit 1** contra el universo
    vivo. A un nombre que el screen nunca miró no se le puede exigir nada."""
    code, out = _corrida(capsys, "--tickers", "AAPL,JPM,DUK")
    assert out["fragile_missed"] == []
    assert out["fragile_not_in_universe"] == ["MLTX"]
    assert out["kill_pass"] is True
    assert code == 0


def test_la_ausencia_del_fragil_se_DECLARA_y_no_pasa_por_medida(sin_red, capsys):
    """Y la contracara, que es lo que hace honesto al PASS anterior: sin ningún
    frágil en el universo, la corrida **no ejercita** el lado verdadero-positivo del
    kill-criteria. Un PASS mudo se leería como si hubiera medido las dos cosas."""
    _, out = _corrida(capsys, "--tickers", "AAPL,JPM,DUK")
    assert out["true_positive_exercised"] is False

    runner.main(["--tickers", "AAPL,JPM,DUK"])
    assert "NO ejercita el verdadero-positivo" in capsys.readouterr().out


def test_un_fragil_PRESENTE_y_no_excluido_sigue_siendo_NO_SHIP(sin_red, monkeypatch, capsys):
    """La mutación en el otro sentido: el arreglo no puede volver mudo al criterio.
    Si MLTX está en el universo y el screen lo deja pasar, eso es una FALLA."""
    monkeypatch.setattr(runner, "get_fundamental_facts", lambda t: _facts(t, (5e9, 4e9), 90e9))
    code, out = _corrida(capsys, "--tickers", "MLTX,AAPL")
    assert out["fragile_missed"] == ["MLTX"]
    assert out["true_positive_exercised"] is True
    assert out["kill_pass"] is False
    assert code == 1


def test_un_fragil_PRESENTE_y_excluido_da_PASS_y_ejercita_el_criterio(sin_red, capsys):
    code, out = _corrida(capsys, "--tickers", "MLTX,AAPL")
    assert out["fragile_caught"] == ["MLTX"]
    assert out["fragile_not_in_universe"] == []
    assert out["true_positive_exercised"] is True
    assert code == 0


# ── El lado que la tarea 129 va a mirar ──────────────────────────────────────


def test_un_nombre_BUENO_excluido_por_fundamentals_es_NO_SHIP(sin_red, monkeypatch, capsys):
    """El riesgo vivo de la 129: un banco cuyo revenue no resuelve con los cinco
    conceptos XBRL actuales queda con ``revenue_latest=None``, y una ausencia de
    revenue cuenta como *debajo del piso*. Si eso pasa, el validador tiene que
    gritar — es el lado falso-positivo del kill-criteria."""
    facts = {"JPM": _facts("JPM", (-1e6, -2e6), None)}
    monkeypatch.setattr(
        runner,
        "get_fundamental_facts",
        lambda t: facts.get(t, _facts(t, (5e9, 4e9), 90e9)),
    )
    code, out = _corrida(capsys, "--tickers", "AAPL,JPM,DUK")
    assert out["other_exclusions"] == ["JPM"]
    assert out["kill_pass"] is False
    assert code == 1


def test_una_exclusion_por_ADV_no_dispara_el_NO_SHIP(sin_red, monkeypatch, capsys):
    """Un ilíquido puede ser legítimo: el piso de ADV$ se lista para revisión humana
    pero no falla el criterio. Queda fijado porque la 129 lee esta distinción."""
    monkeypatch.setattr(runner, "recent_adv_dollars", lambda *a, **kw: 1.0)
    code, out = _corrida(capsys, "--tickers", "AAPL,JPM", "--min-adv", "1000000")
    assert sorted(out["other_exclusions"]) == ["AAPL", "JPM"]
    assert out["kill_pass"] is True
    assert code == 0
