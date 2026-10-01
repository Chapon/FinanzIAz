"""Tarea 251 — la serie de régimen de SPY tiene que CUBRIR el cohorte, y el job 9 no la toca.

Los runners de régimen leen `SPY__10y` como serie de régimen y SPY no está en el universo, así que
`stale_artifacts` nunca lo miró: al 2026-09-30 terminaba 6 ruedas antes que el cohorte, con el
régimen congelado en esas ruedas. Y el job 9 de la 246 reescribía ese mismo archivo por fuera de
`refresh_cohort` (segunda tanda `/audit` del 2026-09-30, [D-1]).

La pregunta es de **cobertura**: una SPY más larga no cambia el régimen de la ventana (lo midió el
`verificador`); una más corta, sí. Lo que se fija:

1. ``spy_coverage_problems`` acusa a SPY que termina antes del cohorte o que no tiene la SMA
   antes de la primera entrada, y deja pasar a una SPY más larga.
2. Aborta por la misma vía que el cohorte (hereda de ``StaleArtifactError``).
3. Los tres runners lo llaman; ``refresh_cohort`` suma SPY al universo vivo.
"""

from __future__ import annotations

import inspect
from datetime import date, timedelta

import pytest

from analysis import harness_config as h


def _ruedas(desde: str, n: int) -> list[tuple[str]]:
    d = date.fromisoformat(desde)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append((d.isoformat(),))
        d += timedelta(days=1)
    return out


_COHORTE = _ruedas("2020-01-01", 600)
_BARS = {"AAA": _COHORTE, "BBB": _COHORTE}
_FIN = _COHORTE[-1][0]


def _spy(desde: str, hasta: str) -> list[tuple[str]]:
    return [r for r in _ruedas("2019-01-01", 1200) if desde <= r[0] <= hasta]


def test_una_spy_que_cubre_no_tiene_problemas():
    assert h.spy_coverage_problems(_spy("2019-01-01", _FIN), _BARS, warmup=250) == []


def test_una_spy_MAS_LARGA_por_las_dos_puntas_tampoco():
    """El hallazgo del verificador: lo que sobra no cambia el régimen de la ventana."""
    assert h.spy_coverage_problems(_spy("2019-01-01", "2022-12-30"), _BARS, warmup=250) == []


def test_una_spy_que_termina_ANTES_del_cohorte_se_acusa():
    """El caso real del 2026-09-30: 6 ruedas antes, con tolerancia 5."""
    corta = _spy("2019-01-01", _COHORTE[-7][0])
    probs = h.spy_coverage_problems(corta, _BARS, warmup=250)
    assert len(probs) == 1 and "6 ruedas antes" in probs[0], probs


def test_dentro_de_la_tolerancia_pasa():
    assert h.spy_coverage_problems(_spy("2019-01-01", _COHORTE[-6][0]), _BARS, warmup=250) == []


def test_una_spy_sin_SMA_antes_de_la_primera_entrada_se_acusa():
    primera = _COHORTE[250][0]
    tardia = [r for r in _spy("2019-01-01", _FIN) if r[0] >= _COHORTE[100][0]]
    probs = h.spy_coverage_problems(tardia, _BARS, warmup=250)
    assert len(probs) == 1 and primera in probs[0] and "SMA" in probs[0], probs


def test_aborta_por_la_misma_via_que_el_cohorte():
    corta = _spy("2019-01-01", _COHORTE[-20][0])
    with pytest.raises(h.StaleArtifactError):
        h.announce_spy_coverage(corta, _BARS, warmup=250, strict=True)
    assert issubclass(h.SpyCoverageError, h.StaleArtifactError)
    assert h.announce_spy_coverage(corta, _BARS, warmup=250, strict=False)  # declara y sigue


@pytest.mark.parametrize(
    "runner", ["run_market_regime_r2", "run_sizing_exposure_t10_t20", "run_anom_regime_t38"]
)
def test_los_tres_runners_de_regimen_lo_chequean(runner):
    import importlib

    fuente = inspect.getsource(importlib.import_module(f"scripts.{runner}"))
    assert "announce_spy_coverage(" in fuente


def test_refresh_cohort_suma_SPY_al_universo_vivo(tmp_path, monkeypatch, capsys):
    import scripts.refresh_cohort as rc

    universo = tmp_path / "u.txt"
    universo.write_text("AAA\nBBB\n", encoding="utf-8")
    vistos = []
    monkeypatch.setattr(rc, "particionar", lambda t, f: vistos.extend(t) or (list(t), []))
    assert rc.main(["--universe", str(universo), "--dry-run"]) == 0
    assert "SPY" in vistos and "AAA" in vistos


def test_con_tickers_explicitos_NO_se_agrega_SPY(monkeypatch):
    import scripts.refresh_cohort as rc

    vistos = []
    monkeypatch.setattr(rc, "particionar", lambda t, f: vistos.extend(t) or (list(t), []))
    assert rc.main(["--tickers", "AAA", "--dry-run"]) == 0
    assert vistos == ["AAA"]


def test_el_job_9_no_escribe_el_10y_del_cohorte():
    from data.historical_series import BENCHMARK_LARGO_PERIOD

    assert BENCHMARK_LARGO_PERIOD != h.ARTIFACT_PERIOD
