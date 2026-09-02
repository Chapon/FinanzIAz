"""GARCH-FRAGIL (tarea 67) — el no-fit deja de ser un `None` mudo.

`fit_garch_forecast` devolvía `None` por **ocho** razones distintas (nueve desde la T67, que partió
la de "parámetros fuera de región") —sin `arch`,
pocos datos, el optimizador que no converge, σ o varianza degeneradas, parámetros
fuera de la región estacionaria, o una excepción— y todas colapsaban al mismo
`None` en el borde, con los motivos sólo en `log.debug`.

Eso importa porque `train_garch_signal` no puede distinguir *"este ticker no tiene
régimen que reportar"* de *"el fit se cayó"*, así que la señal GARCH **entra o no
entra en la mezcla de `analyze()` sin que nada lo declare**. La 29(c) midió el
caso extremo: en 3 de 133 tickers el fit converge o no **según el valor del close
parcial** — de qué lado cae lo decide el precio del momento.

Estos tests fijan la telemetría (parte **1** de la tarea). **No hay fallback ni
remedio**: el enunciado pide medir el tamaño del problema antes de elegir uno, y
eso es la parte **2** (`scripts/measure_garch_fragil_t67.py`).
"""

from __future__ import annotations

import pytest

from analysis import garch_signals as G


@pytest.fixture(autouse=True)
def _limpio():
    G.reset_no_fit_counts()
    yield
    G.reset_no_fit_counts()


# ── El acumulador ────────────────────────────────────────────────────────────


def test_sin_no_fits_no_hay_linea_de_resumen():
    """El caso normal: en el barrido de la 29(c) fitearon 130 de 133. Que **no**
    aparezca la línea es la señal de que no hay nada que mirar."""
    assert G.drain_no_fit_summary() is None


def test_el_resumen_dice_cuantos_y_POR_QUE():
    """Lo que el `None` del borde no dejaba ver: *cuál* de los ocho motivos fue."""
    G._note_no_fit(G.NO_FIT_NO_CONVERGE)
    G._note_no_fit(G.NO_FIT_NO_CONVERGE)
    G._note_no_fit(G.NO_FIT_POCOS_DATOS)
    resumen = G.drain_no_fit_summary()
    assert resumen is not None
    assert "sin fit=3" in resumen
    assert "no_converge=2" in resumen and "pocos_datos=1" in resumen


def test_el_drain_resetea_para_que_el_proximo_scan_empiece_limpio():
    """Mismo contrato que la telemetría de entrenamiento de la 25a: el acumulador
    cuenta *desde el último drain*."""
    G._note_no_fit(G.NO_FIT_EXCEPCION)
    assert G.drain_no_fit_summary() is not None
    assert G.drain_no_fit_summary() is None


def test_no_fit_counts_NO_resetea():
    """La medición (parte 2) necesita leer el tally sin consumirlo — si leyera con
    `drain`, cada barra se llevaría el conteo de la anterior."""
    G._note_no_fit(G.NO_FIT_PARAMS_FUERA_REGION)
    assert G.no_fit_counts() == {G.NO_FIT_PARAMS_FUERA_REGION: 1}
    assert G.no_fit_counts() == {G.NO_FIT_PARAMS_FUERA_REGION: 1}  # sigue ahí


def test_los_nueve_motivos_son_distintos_entre_si():
    """Si dos motivos colapsaran al mismo string, la telemetría volvería a confundir
    *"no hay datos"* con *"no converge"* — que es el defecto que la tarea arregla."""
    motivos = {
        G.NO_FIT_SIN_ARCH,
        G.NO_FIT_POCOS_DATOS,
        G.NO_FIT_NO_CONVERGE,
        G.NO_FIT_SIGMA_DEGENERADA,
        G.NO_FIT_VARIANZA_INVALIDA,
        G.NO_FIT_FORECAST_DEGENERADO,
        G.NO_FIT_PARAMS_FUERA_REGION,
        G.NO_FIT_NO_ESTACIONARIO,
        G.NO_FIT_EXCEPCION,
    }
    assert len(motivos) == 9


# ── El cableado: que cada `return None` declare el suyo ─────────────────────


def test_cada_return_None_del_fit_declara_su_motivo():
    """Regresión del cableado. Si alguien agrega un `return None` sin `_note_no_fit`,
    ese camino vuelve a ser mudo y la telemetría miente por omisión."""
    from pathlib import Path

    fuente = (Path(__file__).resolve().parent.parent / "analysis" / "garch_signals.py").read_text(
        encoding="utf-8"
    )
    # Acotado a las DOS funciones del fit: más allá empieza `compute_annual_volatility`
    # y `train_garch_signal`, que tienen sus propios `return None` y no son no-fits.
    ini = fuente.index("def fit_garch_forecast")
    fin = fuente.index("def compute_annual_volatility")
    cuerpo = fuente[ini:fin]
    # Sobre CÓDIGO, no comentarios — es la tercera vez en el día que un chequeo así
    # se caza a sí mismo (ver los tests de la 69 y la 71): un comentario que explica
    # *"…must NOT propagate them — return None instead"* no es un `return None`.
    lineas = [ln.strip() for ln in cuerpo.splitlines() if not ln.lstrip().startswith("#")]
    n_returns_none = sum(1 for ln in lineas if ln == "return None")
    n_notes = sum(1 for ln in lineas if ln.startswith("_note_no_fit("))
    assert n_notes == n_returns_none, f"{n_notes} motivos declarados para {n_returns_none} `return None`"


def test_pocos_datos_se_registra_de_verdad():
    """End-to-end sobre el camino más barato de disparar: un frame corto."""
    import numpy as np
    import pandas as pd

    if not G._ARCH_OK:
        pytest.skip("arch no instalado")
    idx = pd.bdate_range("2026-01-05", periods=10)
    df = pd.DataFrame({"Close": np.linspace(100, 110, 10)}, index=idx)

    assert G.fit_garch_forecast(df) is None
    assert G.no_fit_counts().get(G.NO_FIT_POCOS_DATOS) == 1


# ── El engine lo emite ───────────────────────────────────────────────────────


def test_el_scan_result_sabe_mostrar_el_resumen():
    from datetime import datetime

    from paper_trading.engine import ScanResult

    r = ScanResult(
        account_id=2,
        scan_at=datetime(2026, 9, 1, 12, 0),
        mode="auto",
        strategy="analyze_single",
        prices={},
        garch_no_fit="GARCH sin fit=3 (no_converge=2 pocos_datos=1)",
    )
    assert "GARCH sin fit=3" in r.summary()


def test_el_engine_draina_el_resumen():
    """Cableado: si el instrumento existe y no lo llama nadie, el no-fit sigue mudo
    — mismo criterio que la 58, la 62, la 64 y la 66."""
    from pathlib import Path

    txt = (Path(__file__).resolve().parent.parent / "paper_trading" / "engine.py").read_text(encoding="utf-8")
    assert "drain_no_fit_summary" in txt
    assert "garch_no_fit=garch_no_fit" in txt
