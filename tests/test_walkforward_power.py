"""
Tests del walk-forward power harness (backlog E4).

Cubre el núcleo puro ``analysis.walkforward_power``: grilla de entradas PIT, tag
de régimen, replay stop-vs-no-stop desde una entrada sintética, corr/IC
cross-sectional y la matemática de power analysis. Todo offline: el conftest
bloquea red, así que el pipeline entero corriendo acá también prueba que el
módulo no toca red (guard implícito).
"""

from __future__ import annotations

import math

import pytest

from analysis.exit_replay import AtrParams
from analysis.walkforward_power import (
    A1_VARIANTS,
    EntrySample,
    _merge_intervals,
    _skew_kurt,
    achieved_power_mean,
    build_entry_grid,
    cohens_d_paired,
    cpcv_effect_distribution,
    cpcv_splits,
    cross_sectional_ic,
    deflated_sharpe_ratio,
    detectable_correlation,
    entry_intervals,
    n_for_correlation,
    n_for_mean_effect,
    pbo_cscv,
    pearson,
    per_entry_returns_by_config,
    pooled_correlation,
    regime_for_date,
    replay_from_entry,
    replay_stop_vs_nostop,
    sample_universe,
    stop_stats_by_regime,
)


def _d(i: int) -> str:
    """Fecha iso10 sintética 2021-01-.. extendida a meses para índices grandes."""
    month = 1 + i // 28
    day = 1 + i % 28
    return f"2021-{month:02d}-{day:02d}"


def bars_with_closes(closes, tr: float = 2.0, start: int = 0):
    return [(_d(start + i), c, c + tr / 2, c - tr / 2, c) for i, c in enumerate(closes)]


# ── Regímenes ────────────────────────────────────────────────────────────────


class TestRegime:
    @pytest.mark.parametrize(
        "date,expected",
        [
            ("2018-11-15", "stress_2018q4"),
            ("2020-03-20", "stress_covid_2020"),
            ("2022-06-01", "stress_bear_2022"),
            ("2019-07-01", "bull_normal"),
            ("2018-09-30", "bull_normal"),  # justo antes de 2018Q4
            ("2018-10-01", "stress_2018q4"),  # borde inclusive
            ("2022-10-31", "stress_bear_2022"),
            ("2022-11-01", "bull_normal"),  # justo después del bear 2022
        ],
    )
    def test_tag_por_fecha(self, date, expected):
        assert regime_for_date(date) == expected


# ── Grilla de entradas ───────────────────────────────────────────────────────


class TestEntryGrid:
    def test_spacing_y_warmup(self):
        bars = bars_with_closes([100.0] * 100)
        entries = build_entry_grid(bars, "AAA", spacing=20, warmup=30, fwd_long=20)
        assert [e.entry_idx for e in entries] == [30, 50, 70, 90]
        assert all(e.ticker == "AAA" for e in entries)

    def test_fwd_returns(self):
        closes = [100.0 + i for i in range(60)]  # crece de a 1
        bars = bars_with_closes(closes)
        entries = build_entry_grid(bars, "AAA", spacing=20, warmup=0, fwd_short=5, fwd_long=20)
        e0 = entries[0]  # idx 0, entry 100
        assert e0.fwd5 == pytest.approx(105 / 100 - 1)
        assert e0.fwd20 == pytest.approx(120 / 100 - 1)

    def test_fwd_none_al_final(self):
        bars = bars_with_closes([100.0] * 40)
        entries = build_entry_grid(bars, "AAA", spacing=10, warmup=0, fwd_short=5, fwd_long=20)
        last = entries[-1]  # idx 30 → fwd20 sale de rango (30+20=50 ≥ 40)
        assert last.entry_idx == 30
        assert last.fwd5 == pytest.approx(0.0)  # 35 dentro de rango, flat
        assert last.fwd20 is None

    def test_label_end(self):
        # label_end = fecha fwd_long barras después de la entrada; None si se sale
        bars = bars_with_closes([100.0] * 40)
        entries = build_entry_grid(bars, "AAA", spacing=10, warmup=0, fwd_short=5, fwd_long=20)
        e0 = entries[0]  # idx 0 → label_end en idx 20
        assert e0.label_end == bars[20][0]
        last = entries[-1]  # idx 30 → 30+20=50 fuera de rango
        assert last.label_end is None

    def test_vacio_sin_barras(self):
        assert build_entry_grid([], "AAA", warmup=0) == []

    def test_regimen_por_entrada(self):
        # una barra en la ventana COVID y otra en bull
        bars = [("2020-03-10", 100, 101, 99, 100), ("2019-05-01", 100, 101, 99, 100)]
        entries = build_entry_grid(bars, "AAA", spacing=1, warmup=0, fwd_long=1)
        assert entries[0].regime == "stress_covid_2020"
        assert entries[1].regime == "bull_normal"

    def test_sample_universe_concatena(self):
        data = {"AAA": bars_with_closes([100.0] * 60), "BBB": bars_with_closes([50.0] * 60)}
        entries = sample_universe(data, spacing=20, warmup=0, fwd_long=20)
        tickers = {e.ticker for e in entries}
        assert tickers == {"AAA", "BBB"}


# ── Replay stop-vs-no-stop ───────────────────────────────────────────────────


class TestReplayFromEntry:
    def test_stop_dispara(self):
        closes = [100.0] * 40
        closes[25] = 90.0  # cae bajo el hard stop (100 - 2·ATR2 ≈ 96)
        bars = bars_with_closes(closes)
        res = replay_from_entry(bars, 20, cap_days=15, atr_p=AtrParams())
        assert res is not None
        exit_idx, _price, reason = res
        assert reason == "atr_stop"
        assert exit_idx == 25

    def test_no_stops_llega_al_cap(self):
        closes = [100.0] * 40
        closes[25] = 90.0
        bars = bars_with_closes(closes)
        res = replay_from_entry(
            bars, 20, cap_days=10, atr_p=AtrParams(stop_mult=1e9, tp_mult=1e9, trail_enabled=False)
        )
        exit_idx, price, reason = res
        assert reason == "cap_reached"
        assert exit_idx == 30  # 20 + 10
        assert price == pytest.approx(100.0)

    def test_gap_open_fill(self):
        bars = bars_with_closes([100.0] * 40)
        bars[25] = ("g", 88.0, 92.0, 87.0, 90.0)  # open 88 < stop ≈96 → fill = open
        res = replay_from_entry(bars, 20, cap_days=15, atr_p=AtrParams())
        _idx, price, reason = res
        assert reason == "atr_stop"
        assert price == pytest.approx(88.0)

    def test_sin_dia_siguiente_none(self):
        bars = bars_with_closes([100.0] * 30)
        assert replay_from_entry(bars, 29, cap_days=10, atr_p=AtrParams()) is None

    def test_replay_stop_vs_nostop_delta(self):
        # precio que sigue subiendo tras un dip → sacar stops ayuda (Δ>0)
        closes = [100.0] * 40
        closes[25] = 95.0  # dip que gatilla el stop baseline
        for i in range(26, 40):
            closes[i] = 110.0  # rebote fuerte
        bars = bars_with_closes(closes)
        data = {"AAA": bars}
        entries = build_entry_grid(bars, "AAA", spacing=100, warmup=20, fwd_long=5)
        outs = replay_stop_vs_nostop(entries, data.get, cap_days=15)
        assert len(outs) == 1
        o = outs[0]
        assert o.ret_no_stops > o.ret_with_stops  # el stop cortó el rebote
        assert o.delta == pytest.approx(o.ret_no_stops - o.ret_with_stops)

    def test_salta_ticker_sin_barras(self):
        e = EntrySample("ZZZ", _d(10), 5, 100.0, "bull_normal", 0.0, 0.0)
        outs = replay_stop_vs_nostop([e], lambda t: None, cap_days=10)
        assert outs == []


# ── Correlación / IC ─────────────────────────────────────────────────────────


class TestCorrelation:
    def test_pearson_conocido(self):
        assert pearson([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
        assert pearson([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)

    def test_pearson_constante_none(self):
        assert pearson([1, 1, 1, 1], [1, 2, 3, 4]) is None

    def test_pearson_n_chico_none(self):
        assert pearson([1, 2], [3, 4]) is None

    def _scored(self, rows):
        # rows: list de (score, fwd5)
        return [
            EntrySample("T", _d(i), i, 100.0, "bull_normal", f, None, score=s)
            for i, (s, f) in enumerate(rows)
        ]

    def test_pooled_ignora_none(self):
        rows = [(0.5, 0.01), (0.6, 0.02), (0.7, 0.03), (None, 0.04), (0.8, None)]
        res = pooled_correlation(self._scored(rows), "fwd5")
        assert res.n == 3  # dos filas con None quedan afuera
        assert res.corr == pytest.approx(1.0)

    def test_ic_cross_sectional(self):
        # dos fechas, 5 nombres cada una, corr perfecta dentro de fecha
        entries = []
        for date_i in (10, 40):
            for k in range(5):
                entries.append(
                    EntrySample(
                        f"T{k}",
                        _d(date_i),
                        date_i,
                        100.0,
                        "bull_normal",
                        fwd5=0.01 * k,
                        fwd20=None,
                        score=0.1 * k,
                    )
                )
        ic = cross_sectional_ic(entries, horizon="fwd5", min_names=5)
        assert ic.n_dates == 2
        assert ic.mean_ic == pytest.approx(1.0)

    def test_ic_filtra_fechas_chicas(self):
        entries = [
            EntrySample(f"T{k}", _d(10), 10, 100.0, "bull_normal", fwd5=0.01 * k, fwd20=None, score=0.1 * k)
            for k in range(3)
        ]  # solo 3 nombres < min_names
        ic = cross_sectional_ic(entries, horizon="fwd5", min_names=5)
        assert ic.n_dates == 0
        assert ic.mean_ic is None


# ── Power analysis ───────────────────────────────────────────────────────────


class TestPowerMath:
    def test_n_for_correlation_valores(self):
        assert n_for_correlation(0.10) == pytest.approx(783, abs=2)
        assert n_for_correlation(0.20) == pytest.approx(194, abs=2)
        assert n_for_correlation(0.0) == math.inf

    def test_detectable_correlation_roundtrip(self):
        n = int(n_for_correlation(0.10))
        assert detectable_correlation(n) == pytest.approx(0.10, abs=0.005)

    def test_detectable_baja_con_n(self):
        assert detectable_correlation(1000) < detectable_correlation(100)
        assert detectable_correlation(3) == 1.0  # indefinido con n≤3

    def test_n_for_mean_effect(self):
        # d=0.2 → (2.8016/0.2)^2 ≈ 196.2 → 197
        assert n_for_mean_effect(0.2) == pytest.approx(197, abs=2)
        assert n_for_mean_effect(0.0) == math.inf

    def test_achieved_power_sube_con_n(self):
        p_small = achieved_power_mean(0.3, 30)
        p_big = achieved_power_mean(0.3, 300)
        assert 0.0 <= p_small < p_big <= 1.0

    def test_cohens_d_paired(self):
        assert cohens_d_paired([2.0, 2.0, 2.0, 2.0]) is None  # std 0
        d = cohens_d_paired([1.0, 2.0, 3.0, 4.0])
        assert d is not None and d > 0

    def test_cohens_d_n_chico_none(self):
        assert cohens_d_paired([1.0]) is None


# ── Agregado por régimen ─────────────────────────────────────────────────────


class TestStopStatsByRegime:
    def _bars_rebote(self, entry_close=100.0):
        closes = [entry_close] * 40
        closes[25] = 95.0
        for i in range(26, 40):
            closes[i] = 110.0
        return bars_with_closes(closes)

    def test_split_por_regimen_y_all(self):
        bars = self._bars_rebote()
        # forzar régimen distinto por fecha vía entradas manuales
        e_bull = EntrySample("AAA", "2019-05-01", 20, 100.0, "bull_normal", 0.0, 0.0)
        e_stress = EntrySample("AAA", "2020-03-10", 20, 100.0, "stress_covid_2020", 0.0, 0.0)
        outs = replay_stop_vs_nostop([e_bull, e_stress], lambda t: bars, cap_days=15)
        stats = stop_stats_by_regime(outs)
        assert stats["all"].n == 2
        assert "bull_normal" in stats and "stress_covid_2020" in stats
        assert stats["bull_normal"].n == 1

    def test_loo_saca_el_peor_ticker(self):
        # dos tickers: AAA con Δ enorme, BBB con Δ chico → LOO debe sacar AAA
        bars_big = self._bars_rebote()
        bars_small = bars_with_closes([100.0] * 40)  # sin dip → Δ≈0
        loader = {"AAA": bars_big, "BBB": bars_small}.get
        entries = [
            EntrySample("AAA", _d(1), 20, 100.0, "bull_normal", 0.0, 0.0),
            EntrySample("BBB", _d(1), 20, 100.0, "bull_normal", 0.0, 0.0),
            EntrySample("BBB", _d(2), 21, 100.0, "bull_normal", 0.0, 0.0),
        ]
        outs = replay_stop_vs_nostop(entries, loader, cap_days=15)
        stats = stop_stats_by_regime(outs)
        s = stats["all"]
        # el Δ medio con AAA es mayor que el LOO (que saca AAA)
        assert s.mean_delta > s.loo_worst_delta


# ── CPCV: particiones purgadas ───────────────────────────────────────────────


from datetime import date, timedelta


def _iso(base: str, days: int) -> str:
    return (date.fromisoformat(base) + timedelta(days=days)).isoformat()


class TestMergeIntervals:
    def test_une_solapados_y_adyacentes(self):
        assert _merge_intervals([(1, 5), (4, 8), (20, 22)]) == [(1, 8), (20, 22)]

    def test_vacio(self):
        assert _merge_intervals([]) == []


class TestCPCVSplits:
    def _intervals(self, n=9, step=3, label=5, base="2021-01-01"):
        """n samples, entrada cada ``step`` días, ventana de ``label`` días → los
        vecinos se solapan (para ejercitar la purga)."""
        return [(_iso(base, step * i), _iso(base, step * i + label)) for i in range(n)]

    def test_conteo_de_splits(self):
        # C(n_groups, k_test)
        splits = cpcv_splits(self._intervals(9), n_groups=3, k_test=1)
        assert len(splits) == 3
        splits2 = cpcv_splits(self._intervals(12), n_groups=4, k_test=2)
        assert len(splits2) == 6  # C(4,2)

    def test_train_test_disjuntos(self):
        for sp in cpcv_splits(self._intervals(12), n_groups=4, k_test=2):
            assert set(sp.train_idx).isdisjoint(sp.test_idx)

    def test_purga_saca_solapes(self):
        # INVARIANTE central: ningún train solapa (con embargo) a ningún test
        intervals = self._intervals(12, step=3, label=5)
        ords = [(date.fromisoformat(s).toordinal(), date.fromisoformat(e).toordinal()) for s, e in intervals]
        embargo = 5
        for sp in cpcv_splits(intervals, n_groups=4, k_test=1, embargo_days=embargo):
            test_spans = [(ords[i][0], ords[i][1] + embargo) for i in sp.test_idx]
            for i in sp.train_idx:
                si, ei = ords[i]
                assert not any(si <= te and ts <= ei for ts, te in test_spans)

    def test_purga_efectiva(self):
        # con ventanas solapadas, la purga debe descartar samples de borde
        intervals = self._intervals(12, step=1, label=6)  # muy solapadas
        for sp in cpcv_splits(intervals, n_groups=4, k_test=1, embargo_days=3):
            n_test = len(sp.test_idx)
            # train < (total - test): algo se purgó en los bordes del test
            assert len(sp.train_idx) < 12 - n_test

    def test_pocos_samples_vacio(self):
        assert cpcv_splits(self._intervals(2), n_groups=6, k_test=2) == []

    def test_entry_intervals_usa_label_end(self):
        e = EntrySample("T", "2021-03-01", 5, 100.0, "bull_normal", 0.0, 0.0, label_end="2021-03-20")
        assert entry_intervals([e]) == [("2021-03-01", "2021-03-20")]
        # sin label_end degrada a punto
        e2 = EntrySample("T", "2021-03-01", 5, 100.0, "bull_normal", 0.0, 0.0)
        assert entry_intervals([e2]) == [("2021-03-01", "2021-03-01")]


class TestCPCVEffect:
    def _outcome(self, ticker, date_iso, delta, regime="bull_normal"):
        from analysis.walkforward_power import StopReplayOutcome

        e = EntrySample(ticker, date_iso, 5, 100.0, regime, 0.0, 0.0, label_end=_iso(date_iso, 20))
        # ret_no_stops - ret_with_stops = delta
        return StopReplayOutcome(e, 0.0, delta, "cap_reached", 5)

    def test_efecto_positivo_estable(self):
        outs = [self._outcome("T", _iso("2021-01-01", 10 * i), 0.05) for i in range(12)]
        res = cpcv_effect_distribution(outs, n_groups=4, k_test=1)
        assert res.n_paths == 4
        assert res.frac_positive == pytest.approx(1.0)
        assert res.mean_delta == pytest.approx(0.05)

    def test_pocos_outcomes(self):
        outs = [self._outcome("T", _iso("2021-01-01", 10 * i), 0.05) for i in range(3)]
        res = cpcv_effect_distribution(outs, n_groups=6, k_test=2)
        assert res.n_paths == 0
        assert res.mean_delta is None


# ── PBO (CSCV) ───────────────────────────────────────────────────────────────


class TestPBO:
    def test_config_genuinamente_bueno_pbo_cero(self):
        # 'good' domina en todo bloque → el mejor IS aguanta OOS → PBO 0
        T = 16
        good = [1.0 + 0.01 * (-1) ** i for i in range(T)]
        bad = [0.0 + 0.01 * (-1) ** i for i in range(T)]
        res = pbo_cscv({"good": good, "bad": bad}, n_splits=4)
        assert res.n_combos == 6  # C(4,2)
        assert res.pbo == pytest.approx(0.0)
        assert res.best_is_counts["good"] == res.n_combos

    def test_anticorrelacion_pbo_uno(self):
        # A mejor en la 1ª mitad, B en la 2ª → el ganador IS siempre pierde OOS
        A = [1.0, 1.0, -1.0, -1.0]
        B = [-1.0, -1.0, 1.0, 1.0]
        res = pbo_cscv({"A": A, "B": B}, n_splits=2)
        assert res.n_combos == 2
        assert res.pbo == pytest.approx(1.0)

    def test_un_solo_config_nan(self):
        res = pbo_cscv({"solo": [1.0, 2.0, 3.0, 4.0]}, n_splits=2)
        assert math.isnan(res.pbo)

    def test_pbo_en_rango(self):
        res = pbo_cscv(
            {"a": [0.1 * i for i in range(20)], "b": [0.2 * (20 - i) for i in range(20)]}, n_splits=6
        )
        assert 0.0 <= res.pbo <= 1.0


# ── Deflated Sharpe Ratio ────────────────────────────────────────────────────


class TestDSR:
    def test_sin_multiples_intentos_no_deflacta(self):
        # n_trials<2 → sr0=0 → deflated == raw
        r = deflated_sharpe_ratio([0.1], n_obs=200)
        assert r.expected_max_sharpe == pytest.approx(0.0)
        assert r.deflated_sharpe == pytest.approx(r.prob_positive_raw)

    def test_mas_intentos_baja_el_dsr(self):
        pocos = deflated_sharpe_ratio([0.20, 0.10], n_obs=250, selected=0.20)
        muchos = deflated_sharpe_ratio(
            [0.20, 0.10, 0.15, 0.12, 0.18, 0.08, 0.14, 0.16], n_obs=250, selected=0.20
        )
        # más variantes probadas → mayor umbral esperado → menor DSR
        assert muchos.expected_max_sharpe > pocos.expected_max_sharpe
        assert muchos.deflated_sharpe < pocos.deflated_sharpe

    def test_dsr_en_cero_uno(self):
        r = deflated_sharpe_ratio([0.15, 0.05, 0.10], n_obs=300, selected=0.15)
        assert 0.0 <= r.deflated_sharpe <= 1.0
        assert r.n_trials == 3

    def test_selected_default_es_el_maximo(self):
        r = deflated_sharpe_ratio([0.05, 0.20, 0.10], n_obs=100)
        assert r.observed_sharpe == pytest.approx(0.20)


class TestSkewKurt:
    def test_simetrico_skew_cero(self):
        s, _k = _skew_kurt([-2, -1, 0, 1, 2] * 4)
        assert s == pytest.approx(0.0, abs=1e-9)

    def test_constante_default(self):
        assert _skew_kurt([3.0, 3.0, 3.0]) == (0.0, 3.0)


# ── A1 variantes: matriz de retornos por config ──────────────────────────────


class TestPerEntryReturnsByConfig:
    def test_matriz_rectangular_y_alineada(self):
        closes = [100.0] * 40
        closes[25] = 95.0
        for i in range(26, 40):
            closes[i] = 110.0
        bars = bars_with_closes(closes)
        entries = build_entry_grid(bars, "AAA", spacing=100, warmup=20, fwd_long=5)
        used, cols = per_entry_returns_by_config(entries, lambda t: bars, A1_VARIANTS, cap_days=15)
        assert set(cols.keys()) == set(A1_VARIANTS.keys())
        # todas las columnas del mismo largo que las entradas usadas
        assert all(len(v) == len(used) for v in cols.values())
        # no_stops captura el rebote → retorno ≥ baseline (que corta en el stop)
        assert cols["no_stops"][0] >= cols["baseline_2.0"][0]
