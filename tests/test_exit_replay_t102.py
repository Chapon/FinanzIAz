"""Tarea 102 — el fail-open del T61 deja de ser mudo.

El runner leía las barras de ``historical_data_cache``, que tiene **cero filas**
desde que la ARQ1 movió el cache histórico a Parquet. Como un evento sin barras
*pasa sin modificar*, las cuatro variantes salían con ``mod=0`` y ``Δ=0`` — que se
lee como *«la variante no cambia nada»* y era *«no había datos»*.

**El número que separa las dos lecturas existía, estaba calculado, y era el único
que no se imprimía:** ``ReplayReport.n_skipped_no_data``. Estos tests fijan las tres
capas del arreglo — que se imprima, que aborte cuando es todo, y que la config viva
no se pueda caer en silencio a un default que representa un desvío de 7,16 pp.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.run_exit_replay_t61 import (
    DEFAULT_PERIOD,
    _atr_params_from_settings,
    render_table,
    sin_datos_del_todo,
)

_REPO = Path(__file__).resolve().parent.parent


class _Rep:
    """Lo mínimo que ``render_table`` y el predicado consumen de un ``ReplayReport``."""

    def __init__(self, variant: str, n_modified: int, n_skipped_no_data: int):
        self.variant = variant
        self.n_modified = n_modified
        self.n_skipped_no_data = n_skipped_no_data
        self.pnl_delta_total = 0.0
        self.pnl_delta_pts = 0.0
        self.max_dd_real = 0.05
        self.max_dd_sim = 0.05
        self.dd_ratio = 1.0
        self.median_extra_return = None
        self.capture_ratio_median = None
        self.passes_kill_criteria = False
        self.exits_by_reason = {}


_CTX = {
    "n_sell_events": 53,
    "n_signal_sells": 29,
    "cap_days": 20,
    "initial_capital": 50_000.0,
    "period": "10y",
}


# ── El predicado del abort ──────────────────────────────────────────────────


def test_sin_una_sola_barra_es_SIN_DATOS_y_no_un_resultado():
    """El caso exacto que tenía el runner: cuatro variantes en `mod=0` porque la
    fuente estaba vacía. Eso **no** es «ninguna variante mueve la aguja»."""
    reps = [_Rep(f"v{i}", n_modified=0, n_skipped_no_data=29) for i in range(4)]
    assert sin_datos_del_todo(reps) is True


def test_con_UNA_variante_que_pudo_medir_ya_no_es_sin_datos():
    """El control positivo. Si alcanza con que todas den `mod=0`, un resultado
    legítimo donde ninguna variante modifica nada abortaría — y sería falso."""
    reps = [_Rep("a", 24, 5), _Rep("b", 0, 5), _Rep("c", 0, 0)]
    assert sin_datos_del_todo(reps) is False


def test_un_mod_CERO_con_skipped_CERO_no_es_falta_de_datos():
    """La distinción entera de la tarea, en su forma más chica: `mod=0, s/dato=0`
    **sí** es «la variante no cambia nada» y no tiene que abortar. Es el caso real
    de `c_min_holding_2d` (ningún SELL de señal tenía menos de 2 días)."""
    assert sin_datos_del_todo([_Rep("c_min_holding_2d", 0, 0)]) is False


def test_sin_eventos_modificables_no_hay_nada_que_acusar():
    """Una cuenta sin SELLs de señal no es un fallo de datos: no hay denominador."""
    assert sin_datos_del_todo([_Rep("a", 0, 0), _Rep("b", 0, 0)]) is False


def test_sin_reports_tampoco_explota():
    assert sin_datos_del_todo([]) is False


# ── La columna que no se imprimía ───────────────────────────────────────────


def test_la_tabla_IMPRIME_los_salteados():
    """Era el único campo del `ReplayReport` que no llegaba a la salida.

    Se asserta la **celda**, no `"5" in salida`: el 5 aparece en el capital, en el
    DD y en el kill-criteria, así que un `in` sobre el texto entero pasaría aunque
    la columna no existiera — que es el defecto que este test viene a impedir."""
    salida = render_table([_Rep("a_confirm_next_scan", 24, 5)], _CTX)
    encabezado = next(ln for ln in salida.split("\n") if "s/dato" in ln)
    assert "mod" in encabezado, "la columna tiene que estar al lado de `mod`"
    fila = next(ln for ln in salida.split("\n") if ln.startswith("a_confirm_next_scan"))
    assert fila.split()[1:3] == ["24", "5"], fila


def test_la_tabla_distingue_los_dos_ceros():
    """Las dos filas que se leían igual y no lo son, una al lado de la otra."""
    salida = render_table([_Rep("sin_efecto", 0, 0), _Rep("sin_datos", 0, 12)], _CTX)
    fila_efecto = next(ln for ln in salida.split("\n") if ln.startswith("sin_efecto"))
    fila_datos = next(ln for ln in salida.split("\n") if ln.startswith("sin_datos"))
    assert fila_efecto.split()[1:3] == ["0", "0"]
    assert fila_datos.split()[1:3] == ["0", "12"]


def test_la_tabla_declara_de_que_period_salieron_las_barras():
    """Sin esto, dos corridas con distinto `--period` son indistinguibles en el doc."""
    assert f"period {DEFAULT_PERIOD}" in render_table([_Rep("a", 1, 0)], _CTX)


# ── El fallback que devolvía el desvío más caro medido ──────────────────────


def test_sin_config_viva_LEVANTA_en_vez_de_devolver_el_default(monkeypatch):
    """`except Exception: return AtrParams()` devolvía el default del engine —stop
    duro a 2.0×ATR, el desvío que la 92 midió en **7,16 pp de CAGR**— convirtiendo
    "no pude leer la config" en un número creíble.

    ``sys.modules[x] = None`` hace que el ``import x`` levante ``ImportError``: es la
    forma de simular el módulo ausente sin tocar el disco."""
    monkeypatch.setitem(sys.modules, "config.settings_manager", None)
    with pytest.raises(RuntimeError, match="config viva"):
        _atr_params_from_settings()


def test_el_mensaje_dice_el_costo_y_la_salida():
    """Un error que no dice qué hacer manda a poner el `except` de vuelta."""
    import inspect

    fuente = inspect.getsource(_atr_params_from_settings)
    assert "--atr-from-defaults" in fuente
    assert "7,16 pp" in fuente


# ── Regresión: la tabla muerta no puede volver ──────────────────────────────


def test_el_runner_NO_lee_de_la_tabla_vacia():
    """`historical_data_cache` tiene 0 filas y es el backend viejo. Que el nombre
    vuelva a aparecer en una consulta es el defecto entero de esta tarea."""
    txt = (_REPO / "scripts" / "run_exit_replay_t61.py").read_text(encoding="utf-8")
    codigo = "\n".join(ln for ln in txt.splitlines() if not ln.lstrip().startswith("#"))
    assert "SELECT data_json FROM historical_data_cache" not in codigo
    assert "parquet_cache.read(" in codigo
