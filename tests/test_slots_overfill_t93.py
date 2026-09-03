"""Tarea 93 — la cuenta no puede pasarse de sus propios `max_positions`.

`strategies.py` contaba los slots libres como `held_tickers - forced_exits`:
descontaba las ventas de **esta misma pasada**, dando por hecho que se iban a
ejecutar. No siempre se ejecutan — `forced_exits` contiene *sólo* `analyze SELL`,
que es exactamente la clase que el **Gate 2** (min holding) y el **Gate 2b**
(histéresis de score, 3 días hábiles) pueden frenar río abajo. Cuando la venta se
frenaba, la compra ya se había llevado el slot.

**Medido sobre `paper_orders` de la cuenta 2 antes de arreglarlo:** 9 episodios,
pico de **12 posiciones con `max_positions=10`**, **269 horas** acumuladas en
exceso y hasta **$51.093** de exposición al costo sobre $50.000 de capital
inicial. El último terminó el **2026-09-02** — era conducta actual.

**Por qué no hace falta backtestearlo:** `analysis/portfolio_sim.py:385-388` ya
contaba los slots así (estricto, sin descontar ventas propuestas). La corrección
**acerca el motor vivo a lo que ya asumían todas las corridas publicadas**.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import paper_trading.strategies as st

_REPO = Path(__file__).resolve().parent.parent


def _fuente_de_la_funcion() -> str:
    return inspect.getsource(st.generate_trades_analyze_single)


def _codigo(txt: str) -> str:
    return "\n".join(ln for ln in txt.splitlines() if not ln.lstrip().startswith("#"))


def test_los_slots_se_cuentan_sobre_lo_que_esta_en_cartera():
    """El invariante: `free_slots` sale de `held_tickers`, no de una resta optimista.

    Se mira el **código**, no los comentarios — el comentario cita la fórmula
    vieja a propósito, para que quien lea el arreglo vea qué decía antes."""
    codigo = _codigo(_fuente_de_la_funcion())
    assert "account.max_positions - len(held_tickers)" in codigo
    assert "held_tickers - forced_exits" not in codigo


def test_la_formula_vieja_queda_citada_en_el_comentario():
    """La contraprueba del test de arriba: si el comentario desapareciera, el
    próximo que lea la línea no sabría que hubo un defecto acá."""
    fuente = _fuente_de_la_funcion()
    assert "held_tickers - forced_exits" in fuente  # en el comentario
    assert "Gate 2b" in fuente


def test_el_harness_cuenta_igual_que_el_motor_arreglado():
    """**El argumento por el que esto no necesita backtest.** Si el simulador y el
    motor dejan de contar igual, vuelve a haber un desvío no declarado — y esta
    vez del lado del vivo."""
    sim = (_REPO / "analysis" / "portfolio_sim.py").read_text(encoding="utf-8")
    assert "free_slots = max_positions - len(open_positions)" in sim


def test_las_ventas_de_senal_son_gateables_y_por_eso_no_liberan_slot():
    """El porqué del arreglo, fijado: `forced_exits` sólo se llena con
    `analyze SELL`, y ésos son los que el engine puede frenar. Si algún día se le
    agregan exits de riesgo —que **no** son gateables— la resta volvería a ser
    defendible, y este test obliga a re-pensarlo en vez de asumirlo."""
    fuente = _fuente_de_la_funcion()
    adds = [ln.strip() for ln in fuente.splitlines() if "forced_exits.add(" in ln]
    assert len(adds) == 1, f"cambió quién puebla forced_exits: {adds}"
    # y ese único add cuelga de la rama de `analyze SELL`
    assert 'reason=f"analyze SELL' in fuente


def test_el_engine_puede_frenar_esa_venta():
    """La otra mitad del mecanismo, del lado del engine: el Gate 2b existe y mira
    la edad de la posición. Sin esto, el arreglo de arriba no tendría motivo."""
    eng = (_REPO / "paper_trading" / "engine.py").read_text(encoding="utf-8")
    assert "paper_signal_sell_min_age_bdays" in eng
    assert "Gate 2b" in eng
