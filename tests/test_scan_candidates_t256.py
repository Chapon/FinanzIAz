"""Tarea 256 — cada scan registra los candidatos a compra que evaluó y cómo terminó cada uno.

Lo que se fija:

1. **Sin un scan colectando, anotar es un no-op:** el harness y cualquier otro llamador de la
   estrategia no cambian.
2. **El resultado de cada elegido sale de lo que hizo el engine:** comprado, encolado o
   bloqueado con el texto del gate. Un aviso de **recorte** por ADV no es un bloqueo: el caso
   de prueba tiene los dos para el mismo ticker, donde tomar «el primer aviso del ticker» daría
   el equivocado.
3. **De punta a punta por ``run_scan``:** un BUY frenado por el anti-whipsaw queda como
   ``bloqueado`` con el motivo, uno ejecutado como ``comprado``, y uno que perdió el ranking
   como ``sin_lugar``. Las filas de más de 90 días se podan.
4. **La estrategia real** anota el ranking con más candidatos que lugares libres.
5. **El registro nunca tumba un scan.**
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd

from config.settings_manager import settings
from database.models import session_scope, utcnow_naive
from paper_trading import scan_candidates as cl
from paper_trading.account import create_account
from paper_trading.models import PaperOrder, PaperScanCandidate, PaperWatchlistItem


def test_sin_colector_anotar_no_hace_nada():
    cl.note("AAPL", cl.ELEGIDO, score=0.8)
    cl.mark("AAPL", cl.SIN_TAMANO)
    with cl.collecting() as filas:
        cl.note("AAPL", cl.ELEGIDO, score=0.8, rank=1)
        cl.mark("AAPL", cl.SIN_TAMANO, "sin caja")
    assert filas == [
        {"ticker": "AAPL", "outcome": cl.SIN_TAMANO, "score": 0.8, "rank": 1, "detail": "sin caja"}
    ]
    cl.note("MSFT", cl.ELEGIDO)  # el colector ya se cerró
    assert len(filas) == 1


def _orden(ticker, status, side="BUY"):
    return SimpleNamespace(ticker=ticker, side=side, status=status)


def test_resolver_distingue_recorte_de_bloqueo():
    filas = [
        {"ticker": "AAA", "outcome": cl.ELEGIDO, "detail": None},
        {"ticker": "BBB", "outcome": cl.ELEGIDO, "detail": None},
        {"ticker": "CCC", "outcome": cl.ELEGIDO, "detail": None},
        {"ticker": "DDD", "outcome": cl.ELEGIDO, "detail": None},
        {"ticker": "EEE", "outcome": cl.SIN_LUGAR, "detail": "x"},
    ]
    warnings = [
        "AAA BUY recortado por ADV: $5,000 → $40 (1% de ADV $4,000).",  # no bloquea
        "AAA BUY bloqueado: tamaño $40.00 < mínimo $100.00.",
        "BBB BUY recortado por ADV: $5,000 → $3,000 (1% de ADV $300,000).",
        "DDD: sin precio, trade omitido.",
    ]
    cl.resolve_engine_outcomes(
        filas, [_orden("BBB", "filled"), _orden("CCC", "pending")], warnings, market_blocked=False
    )
    r = {f["ticker"]: (f["outcome"], f["detail"]) for f in filas}
    assert r["AAA"] == (cl.BLOQUEADO, "AAA BUY bloqueado: tamaño $40.00 < mínimo $100.00.")
    assert r["BBB"][0] == cl.COMPRADO  # recortado y comprado: no es un bloqueo
    assert r["CCC"][0] == cl.ENCOLADO
    assert r["DDD"] == (cl.BLOQUEADO, "DDD: sin precio, trade omitido.")
    assert r["EEE"] == (cl.SIN_LUGAR, "x")  # lo que no era elegido no se toca


def test_resolver_con_mercado_cerrado():
    filas = [{"ticker": "AAA", "outcome": cl.ELEGIDO, "detail": None}]
    cl.resolve_engine_outcomes(filas, [], [], market_blocked=True)
    assert filas[0]["outcome"] == cl.BLOQUEADO and "Gate 1" in filas[0]["detail"]


def _cerrar_ciclo_perdedor(s, account_id, ticker):
    for side, px, horas in (("BUY", 100.0, 72), ("SELL", 90.0, 24)):
        when = utcnow_naive() - timedelta(hours=horas)
        s.add(
            PaperOrder(
                account_id=account_id,
                ticker=ticker,
                side=side,
                target_shares=10.0 if side == "SELL" else None,
                target_dollars=1000.0 if side == "BUY" else None,
                reason=f"test {side}",
                source="analyze_single",
                status="filled",
                created_at=when,
                decided_at=when,
                filled_at=when,
                fill_price=px,
                fill_shares=10.0,
                commission_paid=0.0,
                slippage_cost=0.0,
            )
        )


def test_run_scan_registra_comprado_bloqueado_y_sin_lugar_y_poda(test_db, monkeypatch):
    from paper_trading import engine
    from paper_trading.strategies import TargetTrade

    a = create_account(name="C", initial_capital=10_000.0)
    settings.set("paper_whipsaw_lookback_days", 7)
    settings.set("paper_whipsaw_min_loss_pct", 0.0)
    settings.set("paper_enforce_market_hours", False)
    settings.set("paper_anti_flap_minutes", 0)
    viejo = utcnow_naive() - timedelta(days=91)
    with session_scope() as s:
        for t in ("AAPL", "MSFT", "NVDA"):
            s.add(PaperWatchlistItem(account_id=a.id, ticker=t))
        _cerrar_ciclo_perdedor(s, a.id, "AAPL")
        s.add(PaperScanCandidate(account_id=a.id, scan_at=viejo, ticker="OLD", outcome=cl.SIN_LUGAR))

    def strat(account, watchlist, positions, prices, history_provider):
        cl.note("AAPL", cl.ELEGIDO, score=0.9, rank=1, detail="3 candidatos BUY · 2 lugar(es) libre(s)")
        cl.note("MSFT", cl.ELEGIDO, score=0.8, rank=2, detail="3 candidatos BUY · 2 lugar(es) libre(s)")
        cl.note("NVDA", cl.SIN_LUGAR, score=0.7, rank=3, detail="3 candidatos BUY · 2 lugar(es) libre(s)")
        return [
            TargetTrade(ticker=t, side="BUY", target_shares=None, target_dollars=1_000.0, reason="analyze BUY", source="analyze_single", signal_score=sc)
            for t, sc in (("AAPL", 0.9), ("MSFT", 0.8))
        ]  # fmt: skip

    monkeypatch.setattr(engine, "get_strategy_fn", lambda _: strat)
    result = engine.run_scan(
        a.id,
        prices_provider=lambda _t: {"AAPL": 95.0, "MSFT": 300.0, "NVDA": 100.0},
        history_provider=lambda _t: None,
        earnings_provider=lambda _t: utcnow_naive() + timedelta(days=90),
    )
    assert result is not None and result.filled == 1

    with session_scope() as s:
        filas = s.query(PaperScanCandidate).filter(PaperScanCandidate.account_id == a.id).all()
        r = {f.ticker: (f.outcome, f.rank, f.detail, f.scan_at) for f in filas}
    assert "OLD" not in r, "la fila de 91 días tenía que podarse"
    assert r["MSFT"][:2] == (cl.COMPRADO, 2)
    assert r["AAPL"][0] == cl.BLOQUEADO and "anti-whipsaw" in r["AAPL"][2]
    assert r["NVDA"][:2] == (cl.SIN_LUGAR, 3)
    assert {v[3] for v in r.values()} == {result.scan_at}


def test_la_estrategia_real_anota_el_ranking(monkeypatch):
    import analysis.technical as tech
    from paper_trading import strategies

    prob = {"AAA": 0.9, "BBB": 0.7, "CCC": 0.8, "DDD": None}
    señal = {"AAA": "BUY", "BBB": "BUY", "CCC": "BUY", "DDD": "HOLD"}
    monkeypatch.setattr(
        tech, "analyze", lambda t, df: SimpleNamespace(overall_signal=señal[t], ml_probability=prob[t])
    )
    idx = pd.bdate_range("2025-01-01", periods=300)
    df = pd.DataFrame({"Close": np.linspace(100, 130, 300)}, index=idx)

    def hist(t):
        return None if t == "EEE" else df

    cuenta = SimpleNamespace(
        max_positions=2, cash=10_000.0, commission=0.001, allocation_mode="equal_weight", fixed_amount=1000.0
    )
    with cl.collecting() as filas:
        trades = strategies.generate_trades_analyze_single(
            cuenta, ["AAA", "BBB", "CCC", "DDD", "EEE"], [], {"AAA": 1.0, "BBB": 1.0, "CCC": 1.0}, hist
        )
    r = {f["ticker"]: (f["outcome"], f["rank"]) for f in filas}
    assert r == {
        "EEE": (cl.SIN_DATOS, None),
        "AAA": (cl.ELEGIDO, 1),
        "CCC": (cl.ELEGIDO, 2),
        "BBB": (cl.SIN_LUGAR, 3),
    }, "DDD (HOLD) no se registra; el resto, por ranking"
    assert sorted(t.ticker for t in trades if t.side == "BUY") == ["AAA", "CCC"]


def test_el_registro_no_tumba_nada(monkeypatch):
    import database.models as dbm

    def boom():
        raise RuntimeError("DB caída")

    monkeypatch.setattr(dbm, "session_scope", boom)
    assert cl.persist(1, utcnow_naive(), [{"ticker": "X", "outcome": cl.SIN_LUGAR}]) == 0


# ── La consulta: scripts/por_que_no_compramos.py ──────────────────────────────


def test_la_consulta_distingue_no_candidato_de_app_cerrada():
    from scripts.por_que_no_compramos import leyenda, resumen_por_dia

    filas = [
        ("2026-10-02 15:00:00", "sin_lugar", 0.71, 4, "9 candidatos BUY · 1 lugar(es) libre(s)"),
        (
            "2026-10-02 15:15:00",
            "bloqueado",
            0.74,
            1,
            "ACN BUY bloqueado: earnings el 2026-10-05 dentro de ±2d (blackout).",
        ),
        ("2026-10-02 15:30:00", "sin_lugar", 0.69, 3, "8 candidatos BUY · 0 lugar(es) libre(s)"),
    ]
    scans = {"2026-10-02": 20, "2026-10-03": 18}  # el 04 no hubo scans
    r = {x["dia"]: x for x in resumen_por_dia(filas, scans)}
    assert r["2026-10-02"]["resultados"] == {"bloqueado": 1, "sin_lugar": 2}
    assert r["2026-10-02"]["score_max"] == 0.74 and r["2026-10-02"]["mejor_rank"] == 1
    assert "blackout" in leyenda(r["2026-10-02"])
    assert "nunca fue candidato" in leyenda(r["2026-10-03"])
    assert "2026-10-04" not in r
    assert "sin scans completados" in leyenda({"scans": 0, "apariciones": 0})


def test_la_consulta_contra_una_db_con_el_esquema_real(tmp_path, capsys):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    import paper_trading.models  # noqa: F401 — registra las tablas en Base
    from database.models import Base
    from paper_trading.models import PaperAccount, PaperEquitySnapshot
    from scripts.por_que_no_compramos import main

    db = tmp_path / "f.db"
    eng = create_engine(f"sqlite:///{db.as_posix()}")
    Base.metadata.create_all(eng)
    t0 = pd.Timestamp("2026-10-02 15:00:00").to_pydatetime()
    with Session(eng) as s:
        s.add(PaperAccount(id=2, name="Viva", is_active=True, cash=1.0, initial_capital=1.0))
        s.add(PaperAccount(id=1, name="Cerrada", is_active=False, cash=1.0, initial_capital=1.0))
        for i in range(3):
            s.add(
                PaperEquitySnapshot(
                    account_id=2,
                    snapshot_at=t0 + timedelta(minutes=15 * i),
                    cash=1.0,
                    positions_value=0.0,
                    total_equity=1.0,
                )
            )
        s.add(
            PaperEquitySnapshot(
                account_id=2,
                snapshot_at=t0 + timedelta(days=1),
                cash=1.0,
                positions_value=0.0,
                total_equity=1.0,
            )
        )
        s.add(
            PaperScanCandidate(
                account_id=2,
                scan_at=t0,
                ticker="ACN",
                outcome=cl.SIN_LUGAR,
                signal_score=0.7,
                rank=3,
                detail="5 candidatos BUY · 1 lugar(es) libre(s)",
            )
        )
        s.add(
            PaperScanCandidate(account_id=1, scan_at=t0, ticker="ACN", outcome=cl.COMPRADO, rank=1)
        )  # otra cuenta
        s.commit()
    eng.dispose()

    assert main(["acn", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "cuenta 2" in out  # la viva, no la 1
    assert "2026-10-02  3 scans, candidato en 1: sin_lugar 1" in out
    assert "2026-10-03  1 scans: nunca fue candidato" in out
    assert "comprado" not in out
