"""Tarea 477 — Romano-Wolf sobre el mismo bootstrap pareado (el M1 del pre-registro, §5.7).

El §7 de la T170 congeló que una celda elegida entre 15 por su intervalo necesita un gate que
corrija por haber mirado a todas. ``romano_wolf_stepdown`` es ese gate. Los datos de estos tests
están elegidos para que una versión mal hecha dé otra cosa: un nulo donde el p sin corregir
rechaza y el ajustado no, candidatas idénticas (donde Bonferroni castigaría y Romano-Wolf no
tiene que hacerlo), y una sola candidata, donde tiene que coincidir con el test de siempre.
"""

from __future__ import annotations

import numpy as np
import pytest

from analysis.walkforward_power import paired_block_bootstrap, romano_wolf_stepdown


def _nulo(semilla: int, n_cand: int = 14, t: int = 750):
    """Una referencia y ``n_cand`` candidatas que son la referencia más ruido de media cero."""
    rng = np.random.default_rng(semilla)
    base = rng.normal(0.0004, 0.01, t)
    return base, {f"c{k:02d}": base + rng.normal(0.0, 0.004, t) for k in range(n_cand)}


def test_con_una_sola_candidata_es_el_p_de_paired_block_bootstrap():
    """§5.7: los mismos índices, la misma semilla; con una hipótesis no hay nada que corregir."""
    base, cands = _nulo(3, n_cand=1)
    serie = cands["c00"]
    rw = romano_wolf_stepdown(base, {"c00": serie}, n_resamples=500, seed=12345)
    pb = paired_block_bootstrap(base, serie, n_resamples=500, seed=12345)
    assert rw.p_raw["c00"] == pb.p_value
    assert rw.p_adjusted["c00"] == pb.p_value
    assert rw.observed["c00"] == pytest.approx(pb.observed, abs=1e-15)


def test_bajo_el_nulo_corrige_lo_que_el_p_sin_corregir_no():
    """14 candidatas sin ventaja: una da p = 0,0125 sin corregir, y ajustado ninguna rechaza."""
    base, cands = _nulo(7)
    rw = romano_wolf_stepdown(base, cands, n_resamples=400, seed=12345)
    assert min(rw.p_raw.values()) < 0.05
    assert min(rw.p_adjusted.values()) >= 0.05


def test_el_p_ajustado_nunca_es_menor_que_el_sin_corregir_y_sube_con_el_orden():
    base, cands = _nulo(11)
    rw = romano_wolf_stepdown(base, cands, n_resamples=300, seed=12345)
    for n in cands:
        assert rw.p_adjusted[n] >= rw.p_raw[n], n
    orden = sorted(cands, key=lambda n: -rw.observed[n])
    ajustados = [rw.p_adjusted[n] for n in orden]
    assert ajustados == sorted(ajustados)


def test_con_candidatas_identicas_no_castiga_la_multiplicidad():
    """Romano-Wolf aprovecha la correlación: cinco copias de la misma candidata son una sola
    hipótesis, y su p ajustado es el sin corregir. Bonferroni lo multiplicaría por cinco."""
    base, cands = _nulo(5, n_cand=1)
    buena = cands["c00"] + 0.0001
    rw = romano_wolf_stepdown(base, {f"copia{k}": buena for k in range(5)}, n_resamples=400, seed=12345)
    p = rw.p_raw["copia0"]
    # Rechaza sin corregir (0,035) y con Bonferroni dejaría de rechazar (×5 = 0,175).
    assert p < 0.05 <= 5 * p
    assert all(rw.p_adjusted[f"copia{k}"] == p for k in range(5))


def test_detecta_una_candidata_con_ventaja_real_entre_trece_nulas():
    base, cands = _nulo(9, n_cand=13)
    cands["buena"] = base + 0.002
    rw = romano_wolf_stepdown(base, cands, n_resamples=400, seed=12345)
    assert rw.p_adjusted["buena"] < 0.05
    assert all(rw.p_adjusted[n] >= 0.05 for n in cands if n != "buena")


def test_no_depende_del_orden_en_que_vienen_las_candidatas():
    base, cands = _nulo(13)
    al_reves = dict(reversed(list(cands.items())))
    a = romano_wolf_stepdown(base, cands, n_resamples=200, seed=12345)
    b = romano_wolf_stepdown(base, al_reves, n_resamples=200, seed=12345)
    assert a.p_adjusted == b.p_adjusted


def test_sin_candidatas_o_sin_datos_no_inventa_un_p():
    base, _ = _nulo(1, n_cand=2)
    vacio = romano_wolf_stepdown(base, {}, n_resamples=100)
    assert vacio.p_adjusted == {} and vacio.n_resamples == 0
    corto = romano_wolf_stepdown(base[:1], {"c": base[:1]}, n_resamples=100)
    assert corto.n_resamples == 0 and corto.p_adjusted["c"] != corto.p_adjusted["c"]  # NaN
