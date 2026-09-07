"""Tarea 125 — el footgun del ``squeeze()`` sobre una columna, y su guard de poblacion.

``df["Close"].squeeze()`` devuelve un **escalar** con un frame de una sola fila, y
ahi todo lo que viene despues (`.diff`, `.rolling`, `.ewm`, `.pct_change`) revienta
con ``AttributeError`` en pleno scan.

La **tarea 19** ya lo habia diagnosticado y lo centralizo en
``garch_signals._close_series`` — **solo para ese modulo**. Quedaron **26** llamadas
crudas en cinco modulos. Es el patron que la 99 dejo escrito: *la poblacion del
arreglo se definio por donde se encontro el defecto, no por la propiedad*.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
import pytest

from analysis.frames import series

_REPO = Path(__file__).resolve().parent.parent

# `data/` NO importa de `analysis/` (direccion de capas), asi que su copia queda
# fuera a proposito y con el motivo escrito en su propio docstring.
_FUERA_DE_ALCANCE = {"data/quality.py"}


def _una_fila() -> pd.DataFrame:
    return pd.DataFrame(
        {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.0], "Volume": [1_000_000]},
        index=pd.date_range("2026-01-01", periods=1),
    )


def test_series_devuelve_Series_con_UNA_fila():
    """El caso que rompia: `squeeze()` daba `numpy.float64` y `.diff()` explotaba."""
    s = series(_una_fila(), "Close")
    assert isinstance(s, pd.Series) and len(s) == 1
    s.diff()  # no levanta


def test_series_aplana_la_columna_DUPLICADA():
    """Contraprueba: `squeeze` estaba ahi por esto, y el reemplazo tiene que
    conservarlo o cambia un bug por otro."""
    df = _una_fila()
    df = pd.concat([df, df["Close"]], axis=1)
    assert list(df.columns).count("Close") == 2
    s = series(df, "Close")
    assert isinstance(s, pd.Series) and len(s) == 1


def test_los_indicadores_del_camino_CALIENTE_no_revientan_con_una_barra():
    """Los seis de `technical` mas `get_cached_indicators`, que es el que llama
    `analyze()`. Medido antes del arreglo: los siete explotaban."""
    from analysis import technical as T

    df = _una_fila()
    T.compute_rsi(df)
    T.compute_macd(df)
    T.compute_bollinger_bands(df)
    T.compute_sma(df, 20)
    T.compute_ema(df, 20)
    T.compute_volume_sma(df)
    T.get_cached_indicators("XXX", df)


def test_NINGUN_modulo_de_analysis_vuelve_al_squeeze_sobre_una_columna():
    """El guard de **poblacion**, que es lo que la 19 no tuvo.

    Barre `analysis/` con **AST** y no con grep: `ruff format` parte las llamadas en
    varias lineas y un substring literal se rompe sin que nada deje de estar mal.
    Falla ante cualquier `<algo>[<col>].squeeze()`, que es la forma exacta del
    footgun — `squeeze()` sobre un DataFrame entero es otra cosa y no se toca.
    """
    ofensores = []
    for f in sorted((_REPO / "analysis").rglob("*.py")):
        rel = f.relative_to(_REPO).as_posix()
        if rel in _FUERA_DE_ALCANCE:
            continue
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "squeeze"
                and isinstance(n.func.value, ast.Subscript)
            ):
                ofensores.append(f"{rel}:{n.lineno}")
    assert ofensores == [], (
        f"volvio el `col.squeeze()` en {len(ofensores)} lugar(es): {ofensores}. "
        f"Usar `analysis.frames.series(df, col)` — revienta con un frame de una fila."
    )


def test_el_barrido_NO_pasa_por_no_haber_mirado_nada():
    """La contraprueba del guard: sin esto, un barrido que no encuentra archivos
    tambien da la lista vacia y pasa en verde 'demostrando' que no hay ofensores.
    Es el defecto que la 99 tuvo que cerrar con su propio test de contraprueba."""
    archivos = list((_REPO / "analysis").rglob("*.py"))
    assert len(archivos) > 20, f"el barrido miro {len(archivos)} archivos, algo esta mal"


def test_el_helper_de_garch_delega_y_no_duplica():
    """La 19 dejo su propia copia; la 125 la hace delegar. Si vuelve a tener logica
    propia, vuelven a poder separarse."""
    src = (_REPO / "analysis" / "garch_signals.py").read_text(encoding="utf-8")
    i = src.find("def _close_series(")
    cuerpo = src[i : src.find("\ndef ", i + 1)]
    assert "series(df" in cuerpo, "garch_signals._close_series dejo de delegar"
    assert "iloc[:, 0]" not in cuerpo, "volvio a duplicar la logica de aplanado"


@pytest.mark.parametrize("modulo", ["technical", "ml_signals", "meta_labeling", "regime_detector"])
def test_los_modulos_migrados_importan_el_helper(modulo):
    src = (_REPO / "analysis" / f"{modulo}.py").read_text(encoding="utf-8")
    assert "from analysis.frames import series" in src
