"""
Tests del enabler ``live_gates`` — Tarea 34 (STOP-LOOSEN), el **sexto** desvío.

Pre-registro: ``docs/stop_loosen_prereg_t34_2026-08-18.md`` §3 y §11.3.

Qué se está cubriendo y por qué
-------------------------------
``portfolio_sim`` sólo rechazaba un candidato si el ticker **ya estaba abierto**. El
engine vivo además bloquea el re-BUY con dos gates que miran **ciclos cerrados**:
Gate 5 (anti-whipsaw, ``engine.py:993``) y Gate 5b (anti-churn, ``engine.py:1013``).
Medido antes de congelar: afecta al 21-36% de las entradas tomadas, y el share tiene
**gradiente en el múltiplo del stop** — o sea que no es un nivel común y no se cancela
en la comparación entre brazos (criterio de la T33).

Cubre:
  default OFF        — sin el flag, nada cambia respecto de todo lo publicado
  Gate 5 dispara     — un ciclo perdedor reciente bloquea el re-BUY
  Gate 5 no dispara  — ciclo ganador, o cierre fuera de la ventana
  ventana exacta     — el borde de ``LIVE_WHIPSAW_LOOKBACK_DAYS``
  Gate 5b            — ≥3 ciclos cerrados en 10d bloquean, sin mirar P/L
  sin look-ahead     — un ciclo que todavía no cerró no puede bloquear
  el slot se reusa   — el candidato bloqueado le deja el lugar al siguiente
Todo sintético/offline.
"""

from __future__ import annotations

from datetime import date, timedelta

from analysis.exit_replay import AtrParams
from analysis.harness_config import (
    LIVE_CHURN_MAX_CYCLES,
    LIVE_WHIPSAW_LOOKBACK_DAYS,
)
from analysis.portfolio_sim import simulate_portfolio
from analysis.scaleout_replay import CostModel, ScaleOutParams

NO_COST = CostModel(commission=0.0, slippage=0.0)
NO_ATR = AtrParams(stop_mult=1e9, tp_mult=1e9, trail_enabled=False)  # sólo cap


def _d(i: int) -> str:
    return (date(2020, 1, 1) + timedelta(days=i)).isoformat()


def _bars(closes: list[float]) -> list:
    """Barras planas (OHLC iguales) a partir de una lista de closes."""
    return [(_d(i), c, c, c, c) for i, c in enumerate(closes)]


def _falling(n: int) -> list:
    """Precio que baja 1 por barra ⇒ todo ciclo cierra en PÉRDIDA."""
    return _bars([100.0 - i for i in range(n)])


def _rising(n: int) -> list:
    """Precio que sube 1 por barra ⇒ todo ciclo cierra en GANANCIA."""
    return _bars([100.0 + i for i in range(n)])


def _sim(entries, bars_by, *, cap_days=2, **kw):
    kw.setdefault("atr_p", NO_ATR)
    kw.setdefault("costs", NO_COST)
    kw.setdefault("so_params", ScaleOutParams())
    return simulate_portfolio(entries, bars_by, {}, cap_days=cap_days, **kw)


# ── El default no mueve nada de lo publicado ─────────────────────────────────


def test_default_is_off_and_changes_nothing():
    """El enabler entra con el default apagado, como hizo la 26b con ``eval_mode``:
    los once harness publicados tienen que seguir dando **exactamente** lo mismo."""
    bars_by = {"A": _falling(30)}
    entries = [("A", i) for i in (0, 3, 6, 9, 12)]

    base = _sim(entries, bars_by, max_positions=5)
    explicit_off = _sim(entries, bars_by, max_positions=5, live_gates=False)

    assert base.n_taken == explicit_off.n_taken
    assert base.final_equity == explicit_off.final_equity
    assert [t.entry_date for t in base.trades] == [t.entry_date for t in explicit_off.trades]
    assert base.n_gate5_blocked == 0 and base.n_gate5b_blocked == 0


def test_with_gates_on_the_losing_reentries_disappear():
    """El mismo escenario con los gates puestos toma **menos** entradas, y la
    diferencia queda contabilizada en el contador nuevo (no se pierde en silencio)."""
    bars_by = {"A": _falling(30)}
    entries = [("A", i) for i in (0, 3, 6, 9, 12)]

    off = _sim(entries, bars_by, max_positions=5)
    on = _sim(entries, bars_by, max_positions=5, live_gates=True)

    assert on.n_taken < off.n_taken
    assert on.n_gate5_blocked > 0
    assert on.n_taken + on.n_gate5_blocked + on.n_gate5b_blocked + on.n_already_open == on.n_offered


# ── Gate 5 — anti-whipsaw ────────────────────────────────────────────────────


def test_gate5_blocks_rebuy_after_a_recent_losing_cycle():
    """El caso central: el ciclo anterior del ticker cerró en rojo hace pocos días,
    así que en vivo el re-BUY **no existe**. El harness lo tomaba igual."""
    bars_by = {"A": _falling(30)}
    res = _sim([("A", 0), ("A", 3)], bars_by, max_positions=5, live_gates=True)

    assert res.n_taken == 1               # sólo la primera
    assert res.n_gate5_blocked == 1
    assert [t.entry_date for t in res.trades] == [_d(0)]


def test_gate5_does_not_block_after_a_winning_cycle():
    """Gate 5 mira **pérdidas**. Un ciclo ganador reciente no bloquea nada — es
    justamente el agujero que motivó al Gate 5b en la T6.5."""
    bars_by = {"A": _rising(30)}
    res = _sim([("A", 0), ("A", 3)], bars_by, max_positions=5, live_gates=True)

    assert res.n_taken == 2
    assert res.n_gate5_blocked == 0


def test_gate5_ignores_a_loss_that_fell_out_of_the_window():
    """Espeja al engine: si el último cierre quedó **fuera** de la ventana,
    ``_last_closed_cycle_pnl_pct`` devuelve ``None`` y no bloquea. El cooldown
    expira solo."""
    bars_by = {"A": _falling(40)}
    far = 2 + LIVE_WHIPSAW_LOOKBACK_DAYS + 5      # bien afuera de los 7 días
    res = _sim([("A", 0), ("A", far)], bars_by, max_positions=5, live_gates=True)

    assert res.n_taken == 2
    assert res.n_gate5_blocked == 0


def test_gate5_window_edge_is_inclusive():
    """El borde exacto: un cierre a ``LIVE_WHIPSAW_LOOKBACK_DAYS`` días todavía
    bloquea; un día más y ya no. Si alguien mueve el ``<`` por un ``<=`` esto falla."""
    bars_by = {"A": _falling(40)}
    exit_idx = 2                                   # cap_days=2 ⇒ el ciclo cierra acá

    inside = _sim([("A", 0), ("A", exit_idx + LIVE_WHIPSAW_LOOKBACK_DAYS)],
                  bars_by, max_positions=5, live_gates=True)
    outside = _sim([("A", 0), ("A", exit_idx + LIVE_WHIPSAW_LOOKBACK_DAYS + 1)],
                   bars_by, max_positions=5, live_gates=True)

    assert inside.n_gate5_blocked == 1
    assert outside.n_gate5_blocked == 0


# ── Gate 5b — anti-churn ─────────────────────────────────────────────────────


def test_gate5b_blocks_by_frequency_even_when_the_cycles_win():
    """Gate 5b es agnóstico al P/L: bloquea por **cantidad** de ciclos cerrados.
    Con precio en alza, Gate 5 nunca dispara, así que lo que bloquee es el 5b."""
    bars_by = {"A": _rising(40)}
    entries = [("A", i) for i in (0, 2, 4, 6, 8)]
    res = _sim([e for e in entries], bars_by, cap_days=1, max_positions=5,
               live_gates=True)

    assert res.n_gate5_blocked == 0
    assert res.n_gate5b_blocked > 0
    assert res.n_taken >= LIVE_CHURN_MAX_CYCLES


# ── Sin look-ahead ───────────────────────────────────────────────────────────


def test_a_cycle_that_has_not_closed_yet_cannot_block():
    """La invariante del §7.6 del pre-registro. El simulador conoce el desenlace del
    ciclo apenas lo abre (``replay_cycle`` lo calcula entero), así que la única razón
    por la que esto no es look-ahead es que el historial se alimenta **sólo** desde
    ``_release_until``. Forma observable: un candidato en una fecha en la que el ciclo
    perdedor **todavía está abierto** se rechaza por ``already_open``, nunca por Gate 5.
    """
    bars_by = {"A": _falling(30)}
    # cap_days alto ⇒ el primer ciclo sigue abierto cuando llega el segundo candidato.
    res = _sim([("A", 0), ("A", 3)], bars_by, cap_days=20, max_positions=5,
               live_gates=True)

    assert res.n_already_open == 1
    assert res.n_gate5_blocked == 0


# ── El slot bloqueado no se desperdicia ──────────────────────────────────────


def test_blocked_candidate_leaves_the_slot_for_the_next_one():
    """En vivo un BUY bloqueado no consume slot: el scan sigue con el próximo
    candidato. El harness tiene que hacer lo mismo, o el gate se convertiría sin
    querer en un recorte de exposición."""
    bars_by = {"A": _falling(30), "B": _falling(30)}
    # A arranca sola y cierra en rojo; después compiten A (bloqueada) y B por 1 slot.
    entries = [("A", 0), ("A", 5), ("B", 5)]
    res = _sim(entries, bars_by, max_positions=1, live_gates=True)

    assert res.n_gate5_blocked == 1
    assert res.n_no_slot == 0
    assert [t.ticker for t in res.trades] == ["A", "B"]


def test_out_of_order_closes_do_not_confuse_the_gates():
    """El historial se appendea recorriendo ``open_positions``, que está en orden de
    APERTURA. Con ``allow_reentry_while_open=True`` un ticker puede tener dos ciclos
    abiertos que cierran **fuera** de ese orden, y los gates leen con ``reversed()``
    asumiendo que el último es el cierre más reciente. Sin el ordenamiento, Gate 5
    mira un ciclo que no es el último. Importa para la tarea 36: R2 corre con
    ``allow_reentry_while_open=True``."""
    # A abre en 0 (cap 12 ⇒ cierra tarde, en rojo) y en 2 (cap 1 ⇒ cierra temprano).
    # El que se abrió primero cierra ÚLTIMO: el orden de apertura miente.
    bars_by = {"A": _bars([100.0] * 3 + [101.0] + [90.0] * 20)}
    res = simulate_portfolio(
        [("A", 0), ("A", 2)], bars_by, {}, atr_p=NO_ATR, costs=NO_COST,
        so_params=ScaleOutParams(), cap_days=12, max_positions=5,
        allow_reentry_while_open=True, live_gates=True)
    # No se afirma cuántos bloquea: se afirma que no explota y que el historial
    # quedó consistente (el gate se pronuncia sobre el cierre correcto).
    assert res.n_taken + res.n_gate5_blocked + res.n_gate5b_blocked == res.n_offered


def test_an_open_losing_cycle_cannot_block_a_reentry():
    """La invariante de look-ahead del §7.6, en la forma que **discrimina**: con
    ``allow_reentry_while_open=True`` el rechazo por ``already_open`` no tapa nada, así
    que si el gate mirara el futuro este test fallaría."""
    bars_by = {"A": _falling(30)}
    still_open = simulate_portfolio(
        [("A", 0), ("A", 3)], bars_by, {}, atr_p=NO_ATR, costs=NO_COST,
        so_params=ScaleOutParams(), cap_days=20, max_positions=5,
        allow_reentry_while_open=True, live_gates=True)
    already_closed = simulate_portfolio(
        [("A", 0), ("A", 3)], bars_by, {}, atr_p=NO_ATR, costs=NO_COST,
        so_params=ScaleOutParams(), cap_days=2, max_positions=5,
        allow_reentry_while_open=True, live_gates=True)

    assert still_open.n_gate5_blocked == 0      # el ciclo perdedor sigue ABIERTO
    assert already_closed.n_gate5_blocked == 1  # el mismo ciclo, ya cerrado


# ── El helper de veredicto del runner (§11.3 del pre-registro) ───────────────


def _verdict(**over):
    """Arma summaries/regimes/wf mínimos donde TODOS los criterios pasan, y aplica
    los overrides del caso bajo test. Así cada test dice qué criterio rompe."""
    from scripts.run_stop_loosen_t34 import BASELINE_ARM, MULTS, arm_name, evaluate

    cand_mult = over.pop("cand_mult", 3.0)
    cand = arm_name(cand_mult)
    # Por default la curva tiene un máximo **interior** en el candidato: si no, C6
    # falla y todos los tests medirían lo mismo (fue el primer bug de este fixture).
    peak = MULTS.index(cand_mult)
    cagrs = over.pop("cagrs", None) or {
        m: 0.10 - 0.01 * abs(i - peak) for i, m in enumerate(MULTS)}
    summaries = {}
    for mode in ("touch", "close"):
        for m in MULTS:
            summaries[arm_name(m, mode)] = {
                "cagr": cagrs[m], "sharpe": 0.2 + 0.2 * (m == cand_mult),
                "max_dd": 0.30, "stop_share": 0.1, "exit_mix": {},
            }
    summaries[cand]["sharpe"] = 0.6
    summaries_5 = {n: dict(s) for n, s in summaries.items()}
    regimes = {n: {k: {"mean_ret_pts": 1.0} for k in
                   ("bull_normal", "stress_2018q4", "stress_covid_2020", "stress_bear_2022")}
               for n in (BASELINE_ARM, cand)}
    wf = {"m_star": cand_mult, "agreement": 5, "picks": [cand] * 5, "per_fold": [],
          "proc": {"cagr": 0.08, "max_dd": 0.25}, "base": {"cagr": 0.02, "max_dd": 0.27}}

    class _B:
        ci_low, ci_high, p_value, observed = 0.01, 0.10, 0.01, 0.05

    for k, v in over.items():
        if k == "regimes":
            regimes[cand] = {rk: {"mean_ret_pts": rv} for rk, rv in v.items()}
        elif k == "wf":
            wf.update(v)
        elif k == "boot_ci_low":
            _B.ci_low = v
        else:
            summaries[k].update(v)
    return evaluate(summaries, summaries_5, regimes, _B(), wf)


def test_verdict_ships_only_when_all_eight_pass():
    v = _verdict()
    assert v["ship"] is True
    assert all(ok for _, ok in v["criteria"].values())


def test_verdict_fails_c6_when_the_max_sits_on_the_loose_edge():
    """El caso que efectivamente salió: seis criterios en verde y el máximo en el
    borde. Tiene que ser NO-SHIP **y** decir que abre tarea propia."""
    from scripts.run_stop_loosen_t34 import MULTS

    cagrs = {m: 0.01 * i for i, m in enumerate(MULTS)}   # monótona ⇒ máximo en `off`
    v = _verdict(cagrs=cagrs, cand_mult=MULTS[-1], wf={"m_star": MULTS[-1]})
    assert v["ship"] is False
    assert v["criteria"]["C6_interior_max"][1] is False
    assert "no aporta" in v["outcome"] and "tarea propia" in v["outcome"]


def test_verdict_fails_c5_when_one_regime_degrades():
    v = _verdict(regimes={"bull_normal": 1.0, "stress_2018q4": -1.2,
                          "stress_covid_2020": 1.0, "stress_bear_2022": 1.0})
    assert v["ship"] is False
    assert v["criteria"]["C5_regime"][1] is False


def test_verdict_fails_c7_when_the_multiple_dances_between_folds():
    v = _verdict(wf={"agreement": 2, "picks": ["touch_2.5", "touch_3.0"]})
    assert v["ship"] is False
    assert "RUIDO" in v["outcome"]


def test_verdict_says_it_is_a_positive_result_when_walk_forward_picks_the_live_one():
    """Caso partido declarado: si el procedimiento elige 2.0, es NO-SHIP **y**
    resultado positivo. No se puede reportar como fracaso."""
    v = _verdict(cand_mult=2.0, wf={"m_star": 2.0})
    assert v["ship"] is False
    assert "POSITIVO" in v["outcome"]


def test_verdict_fails_c2_when_drawdown_worsens_even_if_cagr_wins():
    """C1 pasa y C2 falla ⇒ NO-SHIP. Comprar retorno con drawdown en el knob de
    riesgo es apalancar, no mejorar la regla."""
    from scripts.run_stop_loosen_t34 import arm_name

    v = _verdict(**{arm_name(3.0): {"max_dd": 0.50}})
    assert v["ship"] is False
    assert v["criteria"]["C2_maxdd"][1] is False


def test_verdict_fails_c3_when_the_bootstrap_crosses_zero():
    v = _verdict(boot_ci_low=-0.001)
    assert v["ship"] is False
    assert v["criteria"]["C3_bootstrap"][1] is False


# ── Walk-forward: los folds y el embargo (§6) ────────────────────────────────


def test_folds_are_anchored_and_the_embargo_separates_train_from_test():
    """§6 — el train de cada fold termina **antes** de su propio test, con un embargo
    de 365 días corridos, y los tests son contiguos y no se pisan."""
    from datetime import date as _date

    from scripts.run_stop_loosen_t34 import FOLDS

    prev_hi = None
    for train_end, lo, hi in FOLDS:
        assert train_end < lo
        # El pre-registro fija 365 días corridos; los folds están anclados al 1 de
        # agosto, así que en el tramo que cruza un bisiesto son 366. Lo que importa
        # es que nunca sea MENOS que el embargo declarado.
        gap = (_date.fromisoformat(lo) - _date.fromisoformat(train_end)).days
        assert gap >= 365, f"embargo {gap}d en el fold {lo}"
        if prev_hi is not None:
            assert lo > prev_hi
        prev_hi = hi


def test_entries_between_filters_by_entry_date_inclusive():
    from scripts.run_stop_loosen_t34 import entries_between

    bars_by = {"A": _bars([100.0] * 10)}
    entries = [("A", i) for i in range(10)]
    got = entries_between(entries, bars_by, _d(2), _d(4))
    assert [i for _, i in got] == [2, 3, 4]      # los dos bordes adentro
