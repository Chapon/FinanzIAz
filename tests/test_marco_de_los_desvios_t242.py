"""Tarea 242 — todo número de magnitud del banner dice en qué MARCO se midió.

El desvío ``regime_scale`` imprimía en el banner de todo runner *«Vale +0.93pp de CAGR»*. Ese
número era de la T115 a **5 slots, 41 tickers**; con la config de la cuenta (10 slots, universo
vivo) la T121 midió −0.34 pp en una corrida válida. Tenía fuente, tarea y fecha —pasaba las
reglas de la 233— y era de otro marco. Lo encontró la auditoría del 2026-09-30 ([D-1] de
`docs/auditoria_desvios_2026-09-30.md`). Es la clase de la 43 y la 119.

La regla que se fija: en cada **tramo** de un texto de desvío (separado por ``;`` o por
``". "``) que tenga un número en ``pp``, tiene que haber un marco ``N slots, M tickers``; y si
``N`` no es el de la cuenta viva, el tramo tiene que decir ``otro marco``.

**Lo que NO ve, dicho:** una magnitud que no esté en ``pp`` (un porcentaje de ruedas, un
factor ``×0.76``). Son proporciones de la muestra, no efectos sobre el CAGR, y se dejan afuera
a propósito.
"""

from __future__ import annotations

import re

import pytest

from analysis import harness_config as h

_PP = re.compile(r"[+−-]?\d+(?:[.,]\d+)?pp")
_MARCO = re.compile(r"(\d+) slots, (\d+) tickers")
_TRAMOS = re.compile(r";\s|\.\s")


def _cfgs() -> list[h.HarnessConfig]:
    """Configs que, entre todas, hacen aparecer cada clave con número."""
    base = dict(max_positions=10, universe_file=h.LIVE_UNIVERSE_FILE, n_tickers=126)
    return [h.HarnessConfig(**base), h.HarnessConfig(**base, per_trade=True)]


def violaciones(texto: str) -> list[str]:
    """Los tramos con un número en ``pp`` sin marco, o con un marco ajeno no declarado."""
    malos = []
    for tramo in _TRAMOS.split(texto):
        if not _PP.search(tramo):
            continue
        marcos = _MARCO.findall(tramo)
        if not marcos:
            malos.append(f"sin marco: {tramo.strip()[:120]}")
        elif any(int(slots) != h.LIVE_MAX_POSITIONS for slots, _ in marcos) and "otro marco" not in tramo:
            malos.append(f"marco ajeno sin declarar: {tramo.strip()[:120]}")
    return malos


def _textos() -> dict[str, str]:
    out: dict[str, str] = {}
    for cfg in _cfgs():
        for d in h.deviations_keyed(cfg):
            out[d.clave] = d.texto
    return out


def test_todo_numero_en_pp_del_banner_dice_su_marco():
    malos = {clave: v for clave, t in _textos().items() if (v := violaciones(t))}
    assert not malos, malos


def test_la_poblacion_no_esta_vacia():
    """Contraprueba: si ningún texto tuviera un `pp`, el test de arriba pasaría sin mirar nada."""
    con_pp = [c for c, t in _textos().items() if _PP.search(t)]
    assert {"regime_scale", "barrier_eval", "atr_hard_stop"} <= set(con_pp), con_pp


@pytest.mark.parametrize(
    "texto",
    [
        "Vale +0.93pp de CAGR (T115)",  # el caso de la auditoría: sin marco
        "vale +0.93pp a 5 slots, 41 tickers (T115)",  # marco ajeno sin declarar
    ],
)
def test_el_texto_viejo_se_acusa(texto):
    """Mutación en el sentido del falso positivo: lo que el banner decía antes."""
    assert violaciones(texto)


def test_un_marco_ajeno_DECLARADO_pasa():
    assert not violaciones("el +0.93pp de la T115 es de 5 slots, 41 tickers (otro marco)")


def test_regime_scale_cita_el_numero_del_marco_de_la_cuenta():
    """El valor que corresponde a la config de la cuenta es el de la T121 con gates."""
    t = _textos()["regime_scale"]
    assert "−0.34pp" in t and "10 slots, 127 tickers" in t
