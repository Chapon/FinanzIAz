"""Tarea 303 — un spin-off se ajusta a mano con un script, y el cuadre sigue cerrando.

El defecto: el aviso de la 297 mandaba a *«revisar a mano»* y no había ninguna forma de ajustar
una posición paper sin editar ``finanzias.db``, edición que el cuadre de la 266 habría marcado
como descuadre. Decisión de Chapa (2026-10-05): la escindida se acredita **como caja**.

El caso es el de HON 2026 (``q=0,5``, ``r=0,5``: Honeywell Aerospace 1 por cada 2 y un reverse
1:2), con **11** acciones para que la mitad no sea entera y el *cash in lieu* tenga que aparecer.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from paper_trading.spinoffs import SpinoffNoAplicable, acciones_a_la_fecha, calcular_ajuste

EX = "2026-06-29"
PM, PC = 200.0, 100.0  # cierres del ex-date: matriz y escindida (sintéticos)


# ── La cuenta pura ───────────────────────────────────────────────────────────


def test_hon_2026_acciones_caja_costo_y_maximo():
    aj = calcular_ajuste(11, 380.0, 420.0, 11, 0.5, 0.5, PM, PC)
    assert aj.shares_after == 5  # floor(5,5)
    assert aj.cash_fraccion == pytest.approx(0.5 * PM)  # la media acción, al precio de la matriz
    assert aj.cash_escindida == pytest.approx(11 * 0.5 * PC)
    assert aj.cash == pytest.approx(650.0)
    assert aj.avg_cost_after == pytest.approx((11 * 380.0 - 650.0) / 5)
    assert aj.factor == pytest.approx(0.75)
    assert aj.hwm_after == pytest.approx(420.0 / 0.75)
    assert aj.share_ratio == pytest.approx(5 / 11)


def test_la_ganancia_no_realizada_queda_IDENTICA():
    """Devolución de capital: lo que se gana o se pierde no cambia por el evento."""
    shares, avg = 11, 380.0
    aj = calcular_ajuste(shares, avg, None, shares, 0.5, 0.5, PM, PC)
    precio_viejo = PM * aj.factor  # lo que valía una acción vieja el día anterior
    antes = shares * precio_viejo - shares * avg
    despues = aj.shares_after * PM - aj.shares_after * aj.avg_cost_after
    assert despues == pytest.approx(antes)
    # Y la plata total también: posición + caja nueva = posición vieja.
    assert aj.shares_after * PM + aj.cash == pytest.approx(shares * precio_viejo)


def test_un_spin_off_puro_no_toca_las_acciones():
    aj = calcular_ajuste(10, 100.0, None, 10, 1.0, 0.25, 80.0, 40.0)
    assert aj.shares_after == 10 and aj.cash_fraccion == 0.0
    assert aj.cash == pytest.approx(10 * 0.25 * 40.0)


def test_un_lote_comprado_DESDE_el_ex_date_no_se_toca():
    """6 de antes y 4 del ex-date en adelante: sólo las 6 pasan por q."""
    aj = calcular_ajuste(10, 300.0, None, 6, 0.5, 0.5, PM, PC)
    assert aj.shares_after == 3 + 4
    assert aj.cash == pytest.approx(6 * 0.5 * PC)


@pytest.mark.parametrize(
    "args, motivo",
    [
        ((10, 100.0, None, 0, 0.5, 0.5, PM, PC), "no tenía acciones antes"),
        ((10, 100.0, None, 10, 0.0, 0.5, PM, PC), "q tiene que ser > 0"),
        ((10, 100.0, None, 10, 1.0, 0.0, PM, PC), "no es un evento"),
        ((10, 10.0, None, 10, 1.0, 1.0, PM, PC), "supera el costo"),
        ((1, 100.0, None, 1, 0.5, 0.5, PM, PC), "no llega a una acción entera"),
    ],
)
def test_lo_que_no_se_puede_ajustar_se_rechaza(args, motivo):
    with pytest.raises(SpinoffNoAplicable, match=motivo):
        calcular_ajuste(*args)


def test_acciones_a_la_fecha_un_fill_del_ex_date_ya_es_posterior():
    fills = [("2026-06-01", 6.0), (EX, 4.0)]
    assert acciones_a_la_fecha(fills, [], EX) == 6
    assert acciones_a_la_fecha(fills, [], None) == 10
    assert acciones_a_la_fecha(fills, [("2026-06-10", 2.0)], EX) == 12


# ── Contra la DB, con el script ──────────────────────────────────────────────


def _cuenta_hon(test_db, *, mas_fills=()):
    from database.models import session_scope
    from paper_trading.account import create_account
    from paper_trading.models import PaperAccount, PaperOrder, PaperPosition

    acct = create_account(name="Spin", initial_capital=10_000.0)
    fills = [("BUY", 11.0, 380.0, datetime(2026, 6, 1, 15, 0)), *mas_fills]
    caja = 10_000.0
    acciones = 0.0
    with session_scope() as s:
        for side, n, px, cuando in fills:
            s.add(
                PaperOrder(
                    account_id=acct.id,
                    ticker="HON",
                    side=side,
                    status="filled",
                    fill_shares=n,
                    fill_price=px,
                    commission_paid=1.0,
                    filled_at=cuando,
                )
            )
            caja += (-n * px - 1.0) if side == "BUY" else (n * px - 1.0)
            acciones += n if side == "BUY" else -n
        s.query(PaperAccount).filter(PaperAccount.id == acct.id).one().cash = caja
        s.add(
            PaperPosition(
                account_id=acct.id,
                ticker="HON",
                shares=acciones,
                avg_cost=380.0 + 1 / 11,
                high_water_mark=420.0,
            )
        )
    return acct.id


def _correr(aid, monkeypatch, *extra):
    from database import models as db_models
    from scripts import ajustar_spinoff

    monkeypatch.setattr(db_models, "init_db", lambda: None)
    return ajustar_spinoff.main(
        [
            "--account-id",
            str(aid),
            "--ticker",
            "HON",
            "--ex-date",
            EX,
            "--q",
            "0.5",
            "--r",
            "0.5",
            "--precio-matriz",
            str(PM),
            "--precio-escindida",
            str(PC),
            *extra,
        ]
    )


def _estado(aid):
    from database.models import session_scope
    from paper_trading.models import PaperAccount, PaperPosition, PaperSpinoffAdjustment

    with session_scope() as s:
        pos = s.query(PaperPosition).filter(PaperPosition.account_id == aid).one()
        caja = s.query(PaperAccount).filter(PaperAccount.id == aid).one().cash
        filas = s.query(PaperSpinoffAdjustment).filter(PaperSpinoffAdjustment.account_id == aid).count()
        return pos.shares, pos.avg_cost, pos.high_water_mark, caja, filas


def test_el_default_es_DRY_RUN_y_no_escribe_nada(test_db, monkeypatch):
    aid = _cuenta_hon(test_db)
    antes = _estado(aid)
    assert _correr(aid, monkeypatch) == 0
    assert _estado(aid) == antes


def test_con_aplicar_ajusta_acredita_la_caja_y_el_cuadre_CIERRA(test_db, monkeypatch):
    from paper_trading.cuadre import cuadrar_cuenta

    aid = _cuenta_hon(test_db)
    _, avg, _, caja_antes, _ = _estado(aid)
    assert cuadrar_cuenta(aid) == []
    assert _correr(aid, monkeypatch, "--aplicar") == 0
    shares, avg_d, hwm, caja, filas = _estado(aid)
    assert shares == 5 and filas == 1
    assert caja == pytest.approx(caja_antes + 650.0, abs=0.005)
    assert avg_d == pytest.approx((11 * avg - 650.0) / 5)
    assert hwm == pytest.approx(420.0 / 0.75)
    assert cuadrar_cuenta(aid) == []


def test_SIN_el_ledger_la_misma_edicion_DESCUADRA(test_db):
    """La mutación del kill-criteria: ajustar la posición y la caja sin escribir el registro."""
    from database.models import session_scope
    from paper_trading.cuadre import cuadrar_cuenta
    from paper_trading.models import PaperAccount, PaperPosition

    aid = _cuenta_hon(test_db)
    with session_scope() as s:
        s.query(PaperPosition).filter(PaperPosition.account_id == aid).one().shares = 5.0
        acct = s.query(PaperAccount).filter(PaperAccount.id == aid).one()
        acct.cash = float(acct.cash) + 650.0
    pr = cuadrar_cuenta(aid)
    assert any("caja" in p for p in pr) and any("HON" in p for p in pr)


def test_correrlo_DOS_veces_no_ajusta_dos_veces(test_db, monkeypatch):
    aid = _cuenta_hon(test_db)
    assert _correr(aid, monkeypatch, "--aplicar") == 0
    despues = _estado(aid)
    assert _correr(aid, monkeypatch, "--aplicar") == 1
    assert _estado(aid) == despues


def test_una_venta_DESPUES_del_ex_date_no_se_ajusta(test_db, monkeypatch):
    """Vende 3 y compra 5 después del evento: hoy tiene 13, más que las 11 del ex-date, así que
    sólo el chequeo de la venta lo frena (con vender solamente, lo frenaba la cantidad)."""
    aid = _cuenta_hon(
        test_db,
        mas_fills=[
            ("SELL", 3.0, 200.0, datetime(2026, 7, 2, 15, 0)),
            ("BUY", 5.0, 200.0, datetime(2026, 7, 6, 15, 0)),
        ],
    )
    antes = _estado(aid)
    assert _correr(aid, monkeypatch, "--aplicar") == 1
    assert _estado(aid) == antes


def test_una_cuenta_que_ya_no_cuadra_no_se_toca(test_db, monkeypatch):
    from database.models import session_scope
    from paper_trading.models import PaperAccount

    aid = _cuenta_hon(test_db)
    with session_scope() as s:
        s.query(PaperAccount).filter(PaperAccount.id == aid).one().cash = 1.0
    antes = _estado(aid)
    assert _correr(aid, monkeypatch, "--aplicar") == 1
    assert _estado(aid) == antes


# ── Lo que el scan hace después ──────────────────────────────────────────────


def test_un_evento_ajustado_a_mano_deja_de_avisarse():
    from paper_trading.splits import factores_sin_tratar

    fills = [("HON", "BUY", 11.0, "2026-06-01")]
    eventos = {"HON": [(EX, 0.9535)]}
    assert factores_sin_tratar(fills, eventos, {"HON": 5.0}, "2026-07-01", dias=7) != []
    assert (
        factores_sin_tratar(fills, eventos, {"HON": 5.0}, "2026-07-01", dias=7, tratados={("HON", EX)}) == []
    )


def test_un_split_POSTERIOR_al_spin_off_sigue_ajustandose():
    """Sin contar el spin-off como aplicado, la historia daría 11 acciones contra 5 y el split
    siguiente quedaría bloqueado como «posición inconsistente»."""
    from paper_trading.splits import ajustes_pendientes

    fills = [("HON", "BUY", 11.0, "2026-06-01")]
    eventos = {"HON": [(EX, 0.9535), ("2026-09-01", 2.0)]}
    ratio = 5 / 11
    pend, inc = ajustes_pendientes(
        fills, eventos, {("HON", EX)}, {"HON": 5.0}, "2026-09-15", {("HON", EX): ratio}
    )
    assert inc == []
    assert [(p.acciones_antes, p.acciones_despues) for p in pend] == [(5.0, 10.0)]
    _, inc_sin = ajustes_pendientes(fills, eventos, set(), {"HON": 5.0}, "2026-09-15")
    assert inc_sin != []


def test_el_aviso_del_scan_nombra_el_script():
    from paper_trading.engine import _texto_factor_sin_tratar
    from paper_trading.splits import FactorSinTratar

    texto = _texto_factor_sin_tratar(FactorSinTratar("HON", EX, 0.9535, 11.0))
    assert "scripts/ajustar_spinoff.py" in texto
    assert (
        __import__("pathlib").Path(__file__).resolve().parent.parent / "scripts" / "ajustar_spinoff.py"
    ).exists()


def test_el_scan_lee_el_ledger_split_posterior_y_aviso_apagado(test_db, monkeypatch):
    """Lo mismo, por ``aplicar_splits`` (el camino del scan) y contra la DB."""
    from database.models import session_scope
    from paper_trading import splits
    from paper_trading.models import PaperAccount, PaperPosition

    aid = _cuenta_hon(test_db)
    assert _correr(aid, monkeypatch, "--aplicar") == 0
    monkeypatch.setattr(splits, "utcnow_naive", lambda: datetime(2026, 7, 3, 12, 0))
    with session_scope() as s:
        acct = s.query(PaperAccount).filter(PaperAccount.id == aid).one()
        pos = s.query(PaperPosition).filter(PaperPosition.account_id == aid).all()
        ajustes, avisos, sin_tratar = splits.aplicar_splits(
            s, acct, pos, {"HON": [(EX, 0.9535), ("2026-07-01", 2.0)]}
        )
    assert avisos == [] and sin_tratar == []
    assert [(a["shares_before"], a["shares_after"]) for a in ajustes] == [(5.0, 10.0)]
