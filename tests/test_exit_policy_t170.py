"""Tarea 170 (EXIT-POLICY-REDECIDE) — tests offline del runner, antes de correrlo.

El pre-registro (`docs/exit_policy_prereg_t170_2026-09-10.md`, commit `207b165`) congeló
dos cosas que estos tests custodian:

1. **El gate no selecciona.** Es la diferencia con el T37, cuyo `C1` mide *el
   procedimiento* (`wf["proc"] − wf["base"]`) y cuyo bootstrap corre sobre `wf["star"]`,
   el brazo que eligen los datos. Acá los dos brazos están **nombrados de antemano por
   procedencia**, y el test de abajo lo verifica **contando las simulaciones**: si
   apareciera un paso de selección, el conteo se iría de 2 por fold.
2. **Hacen falta las CINCO condiciones para mover la política viva.** La asimetría es
   deliberada: el que propone el cambio carga la prueba.
"""

from __future__ import annotations

import io

import pytest

import scripts.run_exit_policy_t170 as m

# ── Los brazos están congelados y son los que el pre-registro nombró ─────────


def test_los_dos_brazos_son_los_del_preregistro():
    """`soff_t2.0` es la política viva y `s2.0_t2.0` la que tenía evidencia antes del
    2026-08-27. Si alguien los cambia, cambió el experimento."""
    assert m.POLICY_ARM == "soff_t2.0"
    assert m.CHALLENGER_ARM == "s2.0_t2.0"


def test_la_celda_de_la_POLITICA_se_DERIVA_de_los_espejos():
    """**No se clava** (tarea 134, y el guard me cazó clavándola): sale de
    `LIVE_HARD_STOP_ENABLED` / `LIVE_STOP_MULT` / `LIVE_TRAIL_MULT`, que la tarea 130
    re-verifica contra el `settings.json` vivo.

    El literal `(NO_STOP, 2.0)` era correcto hoy y habría quedado viejo el día que Chapa
    mueva la política — exactamente el defecto que la **169** acaba de arreglar en el rótulo
    del T37. Con esto, mover la perilla mueve el brazo.
    """
    import analysis.harness_config as hc
    from scripts.run_stop_cal_replay_t26 import NO_STOP

    esperada = ((hc.LIVE_STOP_MULT if hc.LIVE_HARD_STOP_ENABLED else NO_STOP), hc.LIVE_TRAIL_MULT)
    assert esperada == m.POLICY_CELL
    # Y la contraprueba del lado que importa: hoy el stop duro está APAGADO en la cuenta 2,
    # así que el brazo de la política tiene que ser el del stop apagado.
    assert hc.LIVE_HARD_STOP_ENABLED is False
    assert m.POLICY_CELL[0] >= NO_STOP


def test_los_umbrales_son_LOS_DEL_T37():
    """*«Los umbrales son los del T37, sin tocar uno»* (§4). Mover un umbral para que una
    corrida pase sería arreglar el termómetro cambiándole las marcas."""
    import scripts.run_stop_value_t37 as t37

    assert m.D1_MIN_DCAGR_OOS == t37.KILL_MIN_DCAGR_OOS
    assert m.D2_MIN_FOLDS == t37.KILL_MIN_FOLD_AGREEMENT
    assert m.D3_TAIL_TOL_PTS == t37.KILL_TAIL_TOL_PTS
    assert m.D5_DD_TOL == t37.KILL_DD_TOL


# ── El gate: hacen falta las cinco ───────────────────────────────────────────


class _Boot:
    def __init__(self, lo, hi, p=0.01):
        self.ci_low, self.ci_high, self.p_value = lo, hi, p


def _wf(*, dcagr=0.02, folds=5, dd=0.0):
    return {"dcagr_oos": dcagr, "folds_won": folds, "dd_delta_oos": dd, "per_fold": [], "agg": {}}


def _sum(*, live_dd=0.30, chal_dd=0.30, live_cagr=0.08, chal_cagr=0.10):
    return {
        m.POLICY_ARM: {"cagr": live_cagr, "max_dd": live_dd, "accounting_ok": True},
        m.CHALLENGER_ARM: {"cagr": chal_cagr, "max_dd": chal_dd, "accounting_ok": True},
    }


def _tails(*, d_worst=0.0, d_p1=0.0):
    return {
        m.POLICY_ARM: {"worst": -20.0, "p1": -10.0},
        m.CHALLENGER_ARM: {"worst": -20.0 + d_worst, "p1": -10.0 + d_p1},
    }


def test_con_las_cinco_PASA_se_mueve():
    v = m.evaluate(_wf(), _sum(), _tails(), _Boot(0.5, 5.0))
    assert all(v[k] for k in ("D1", "D2", "D3", "D4", "D5"))
    assert v["mover"] is True
    assert "MOVER la política" in v["veredicto"]


@pytest.mark.parametrize(
    ("nombre", "kwargs_wf", "kwargs_sum", "kwargs_tails", "boot", "falla"),
    [
        ("D1 — el margen OOS no alcanza", {"dcagr": 0.005}, {}, {}, _Boot(0.5, 5.0), "D1"),
        ("D2 — gana en 3 de 5 folds", {"folds": 3}, {}, {}, _Boot(0.5, 5.0), "D2"),
        ("D3 — la cola empeora", {}, {}, {"d_worst": -3.0}, _Boot(0.5, 5.0), "D3"),
        ("D3 — el p1 empeora", {}, {}, {"d_p1": -2.5}, _Boot(0.5, 5.0), "D3"),
        ("D4 — el IC cruza el cero", {}, {}, {}, _Boot(-0.2, 5.0), "D4"),
        ("D5 — el maxDD in-sample empeora", {}, {"chal_dd": 0.35}, {}, _Boot(0.5, 5.0), "D5"),
        ("D5 — el maxDD OOS empeora", {"dd": 0.02}, {}, {}, _Boot(0.5, 5.0), "D5"),
    ],
)
def test_basta_que_UNA_falle_para_no_mover(nombre, kwargs_wf, kwargs_sum, kwargs_tails, boot, falla):
    """La conjunción, condición por condición. Cada fila apaga exactamente una."""
    v = m.evaluate(_wf(**kwargs_wf), _sum(**kwargs_sum), _tails(**kwargs_tails), boot)
    assert v[falla] is False, f"{nombre}: {falla} tenía que fallar"
    assert v["mover"] is False
    assert "NO MOVER" in v["veredicto"]


def test_sin_bootstrap_no_se_mueve():
    """Un D4 que no se pudo medir **no** es un D4 que pasa."""
    v = m.evaluate(_wf(), _sum(), _tails(), None)
    assert v["D4"] is False and v["mover"] is False


def test_el_delta_in_sample_NO_es_gate():
    """Está en el reporte como descriptivo. Si decidiera, volveríamos al defecto que la
    167 midió: in-sample el brazo vivo gana por +3.80 pp y su margen OOS no existe."""
    v = m.evaluate(_wf(dcagr=0.0), _sum(chal_cagr=0.50), _tails(), _Boot(0.5, 5.0))
    assert v["dcagr_insample"] > 0.0
    assert v["D1"] is False and v["mover"] is False


# ── El sanity es una conjunción, y la reproducción cuenta ────────────────────


def _repro(estado="OK"):
    return {"s2.0_t2.0": {"state": estado, "actual": 0.0498, "expected": 0.0498}}


def _sanity_sums(*, d_cagr=0.05, d_dd=-0.07, accounting=True):
    return {
        m.ORACLE_ARM: {"cagr": 0.10, "max_dd": 0.27, "accounting_ok": accounting},
        m.RANDOM_KEEP_ARM: {"cagr": 0.10 - d_cagr, "max_dd": 0.27 - d_dd, "accounting_ok": True},
    }


def test_el_sanity_pasa_cuando_las_dos_patas_del_oraculo_pasan():
    s = m.evaluate_sanity(_sanity_sums(), _repro())
    assert s["oracle_quality_cagr_ok"] and s["oracle_quality_dd_ok"] and s["all_ok"]


@pytest.mark.parametrize(
    ("kw", "clave"),
    [
        ({"d_cagr": 0.005}, "oracle_quality_cagr_ok"),
        ({"d_dd": -0.02}, "oracle_quality_dd_ok"),
        ({"accounting": False}, "accounting"),
    ],
)
def test_cada_pata_del_sanity_invalida_la_corrida(kw, clave):
    """Las dos patas del oráculo van **separadas** (tarea 164): el T47 las colapsaba en un
    booleano y mostraba el número de la que pasaba."""
    s = m.evaluate_sanity(_sanity_sums(**kw), _repro())
    assert s[clave] is False
    assert s["all_ok"] is False


def test_un_INDETERMINADO_de_reproduccion_no_es_OK():
    """Misma política que los siete runners: no se puede declarar reproducible lo que no
    se pudo verificar (T48/T52/T159)."""
    s = m.evaluate_sanity(_sanity_sums(), _repro("INDETERMINADO"))
    assert s["repro_ok"] is False and s["all_ok"] is False


# ── La estructura: NO HAY SELECCIÓN ──────────────────────────────────────────


def _bars(n: int, *, desde: str = "2019-01-01") -> list[tuple]:
    from datetime import date, timedelta

    d0 = date.fromisoformat(desde)
    return [((d0 + timedelta(days=i)).isoformat(), 100.0, 101.0, 99.0, 100.0) for i in range(n)]


class _Res:
    """Lo mínimo que `fixed_arms_walk_forward` le pide a un PortfolioResult."""

    def __init__(self, curve, final):
        self.equity_curve = curve
        self.final_equity = final


def test_el_walk_forward_simula_EXACTAMENTE_dos_brazos_por_fold(monkeypatch):
    """**El test estructural de la tarea.** Si apareciera un paso de selección —correr las
    15 celdas en train para elegir una— el conteo se iría de 2 por fold. Acá se cuenta, no
    se confía en leer el código.
    """
    bars_by = {"AAA": _bars(3000)}
    entries = [("AAA", i) for i in range(300, 2900, 37)]
    vistos: list[str] = []

    def _fake_sim(tag, ent, bars, sigs, **kw):
        vistos.append(tag.split("|")[2])  # el nombre del brazo
        return _Res([(d, 50_000.0) for d, *_ in bars_by["AAA"][:10]], 50_000.0)

    monkeypatch.setattr(m, "_sim", _fake_sim)
    wf = m.fixed_arms_walk_forward(
        entries, bars_by, {}, {"initial_capital": 50_000.0}, tag="t", log=io.StringIO()
    )
    assert len(vistos) == 2 * len(m.FOLDS), f"se simularon {len(vistos)} brazos, no {2 * len(m.FOLDS)}"
    assert set(vistos) == {m.POLICY_ARM, m.CHALLENGER_ARM}, (
        f"apareció un brazo que no es del gate: {set(vistos)}"
    )
    assert len(wf["per_fold"]) == len(m.FOLDS)


def test_el_walk_forward_COMPONE_el_equity_entre_folds(monkeypatch):
    """Mismo tratamiento que el T37: el capital con el que arranca cada fold es el que
    dejó el anterior, por brazo. Si no compusiera, los cinco folds serían cinco corridas
    independientes y el agregado no sería una curva."""
    bars_by = {"AAA": _bars(3000)}
    entries = [("AAA", i) for i in range(300, 2900, 37)]
    caps: list[float] = []

    def _fake_sim(tag, ent, bars, sigs, **kw):
        caps.append(kw["initial_capital"])
        final = kw["initial_capital"] * 1.10
        return _Res([(d, final) for d, *_ in bars_by["AAA"][:5]], final)

    monkeypatch.setattr(m, "_sim", _fake_sim)
    m.fixed_arms_walk_forward(entries, bars_by, {}, {"initial_capital": 1000.0}, tag="t", log=io.StringIO())
    # Dos brazos × 5 folds, y cada brazo arranca donde quedó: 1000 → 1100 → 1210 …
    por_brazo = [caps[i::2] for i in (0, 1)]
    for serie in por_brazo:
        assert serie == pytest.approx([1000.0, 1100.0, 1210.0, 1331.0, 1464.1])


# ── §7 — la regla de lectura de la rejilla, congelada ───────────────────────


def _grid_con(monkeypatch, *, ic_por_celda: dict[str, tuple[float, float]]):
    """Corre `grid_descriptive` con simulaciones y bootstrap falsos, para ejercitar **la
    regla de lectura** y no un dict escrito a mano.

    La primera versión de estos dos tests asserteaba un literal —o sea, se testeaba a sí
    misma—, que es el defecto que la tarea 145 vino a cerrar.
    """
    bars_by = {"AAA": _bars(3000)}
    entries = [("AAA", i) for i in range(300, 2900, 37)]

    def _fake_sim(tag, ent, bars, sigs, **kw):
        return _Res([(d, kw["initial_capital"]) for d, *_ in bars_by["AAA"][:5]], kw["initial_capital"])

    def _fake_boot(xs, ys, **kw):
        # El nombre de la celda se recupera del orden de llamada: `grid_descriptive`
        # bootstrapea una vez por celda, en el orden de `grid_cells()`.
        nombre = _fake_boot.pendientes.pop(0)
        lo, hi = ic_por_celda.get(nombre, (-0.01, 0.05))
        return _Boot(lo, hi)

    from scripts.run_stop_value_t37 import arm_name, grid_cells

    _fake_boot.pendientes = [arm_name(*c) for c in grid_cells() if arm_name(*c) != m.POLICY_ARM]
    monkeypatch.setattr(m, "_sim", _fake_sim)
    monkeypatch.setattr(m, "paired_block_bootstrap", _fake_boot)
    monkeypatch.setattr(m, "aligned_daily", lambda res, arms: {a: [("2020-01-01", 0.0)] for a in arms})
    return m.grid_descriptive(
        entries, bars_by, {}, {"initial_capital": 1000.0}, {}, tag="t", resamples=10, log=io.StringIO()
    )


def test_la_rejilla_NO_es_decidible_si_ningun_IC_excluye_el_cero(monkeypatch):
    """La regla congelada del §7: sin ningún intervalo que excluya el cero, la conclusión
    publicable es *«no es decidible con esta muestra»* y la rejilla queda cerrada."""
    grid = _grid_con(monkeypatch, ic_por_celda={})
    assert grid["decidibles"] == []
    assert grid["es_decidible"] is False
    assert len(grid["celdas"]) == 14, "la rejilla son 15 celdas menos la viva"


def test_una_celda_con_IC_que_excluye_el_cero_queda_MARCADA(monkeypatch):
    """La otra mitad de la regla: se marca, con su nombre, para que abra su propio
    pre-registro. Las dos direcciones cuentan — un IC enteramente negativo también
    excluye el cero."""
    grid = _grid_con(
        monkeypatch,
        ic_por_celda={"s3.0_t3.0": (0.4, 2.0), "s2.0_toff": (-3.0, -0.2)},
    )
    assert set(grid["decidibles"]) == {"s3.0_t3.0", "s2.0_toff"}
    assert grid["es_decidible"] is True


def test_el_GATE_no_mira_la_rejilla(monkeypatch):
    """Una celda marcada **no se cabla desde acá** (§7): `evaluate` no recibe el grid, así
    que el veredicto no puede depender de él. Se verifica por la firma, que es lo que lo
    hace estructural y no una promesa del docstring."""
    import inspect

    assert "grid" not in inspect.signature(m.evaluate).parameters
    grid = _grid_con(monkeypatch, ic_por_celda={"soff_toff": (1.0, 5.0)})
    assert grid["es_decidible"] is True
    v = m.evaluate(_wf(dcagr=0.0), _sum(), _tails(), _Boot(0.5, 5.0))
    assert v["mover"] is False  # el gate sólo mira los dos brazos nombrados


# ── La clave de cache describe el CÓMPUTO, no el nombre ──────────────────────


def test_la_huella_del_brazo_distingue_lo_que_el_nombre_NO():
    """**Regresión de un defecto que me costó una corrida inválida.**

    El tag de las simulaciones identificaba al brazo por **nombre**. Al corregir sobre qué
    celda se montan los brazos de sanity, el nombre siguió siendo `ORACULO_STOP` y la
    corrida **reusó del cache el resultado del brazo viejo**: salió `ΔCAGR +0.00` con el
    bug ya arreglado. Es textual lo que el T37 dice de su propio tag — *«un cache que
    sobrevive a un cambio de config es un bug de reproducibilidad»*.
    """
    from scripts.run_stop_cal_replay_t26 import (
        NO_STOP,
        RANDOM_KEEP_PROB,
        _oracle_stop_filter,
        random_stop_filter,
    )
    from scripts.run_stop_value_t37 import arm_params

    base = arm_params(2.0, 2.0)
    apagado = arm_params(NO_STOP, 2.0)
    # el caso exacto del bug: el MISMO filtro sobre dos celdas distintas
    assert m.arm_fingerprint({**base, "stop_filter": _oracle_stop_filter}) != m.arm_fingerprint(
        {**apagado, "stop_filter": _oracle_stop_filter}
    )
    # y dos filtros distintos sobre la misma celda
    assert m.arm_fingerprint({**base, "stop_filter": _oracle_stop_filter}) != m.arm_fingerprint(
        {**base, "stop_filter": random_stop_filter(RANDOM_KEEP_PROB)}
    )
    # sin filtro no es lo mismo que con filtro
    assert m.arm_fingerprint(base) != m.arm_fingerprint({**base, "stop_filter": _oracle_stop_filter})
    # y el mismo cómputo da la misma huella (si no, el cache no serviría para nada)
    assert m.arm_fingerprint(arm_params(2.0, 2.0)) == m.arm_fingerprint(arm_params(2.0, 2.0))


def test_la_huella_entra_en_la_clave_que_el_cache_ve(monkeypatch):
    """Contraprueba: no alcanza con que la función exista — tiene que estar **en la clave**."""
    vistos: list[str] = []

    class _FakeCache:
        def run(self, tag, fn):
            vistos.append(tag)
            return fn()

    from scripts.run_stop_value_t37 import arm_params

    monkeypatch.setattr(m, "_CACHE", _FakeCache())
    monkeypatch.setattr(m, "simulate_portfolio", lambda *a, **k: "res")
    m._sim("grid|X|tag", [], {}, {}, **arm_params(2.0, 3.0))
    assert vistos and vistos[0].startswith("grid|X|tag|"), vistos
    assert "s2|t3" in vistos[0], f"la huella no entró en la clave: {vistos[0]}"
