"""Tarea 459 — el precio del escalado por régimen se cita en el marco de la salida viva.

El desvío ``regime_scale`` decía que el factor vivo (×0,25 en risk-off) cuesta **−0,34 pp** de
CAGR, de la T121. La T121 corrió con ``AtrParams()`` por defecto, o sea con el stop duro
**prendido**: la política de salida anterior al 2026-08-27. Tenía los slots y los tickers de la
cuenta, así que pasaba la regla de marco de la 242, y medía otra estrategia. Con la salida viva,
la 456 midió **8,78% → 7,32%** (−1,46 pp), Sharpe 0,55 → 0,52 y caída 28,4% → 22,9%.

El mismo desvío decía *«0 de 80 BUY vivas lo dispararon al 2026-09-27»*: con fecha, como pedía
la 233, y vencido el 2026-11-20, cuando disparó. Al 2026-11-24 son 11 de 124. Un conteo escrito
a mano se vence, así que el texto da el hecho que no se vence (la primera vez) y dónde se cuenta
(la razón de la orden).

Lo que fija este archivo:

1. Los números del tramo vigente **son los de su medición**: se recalculan de la tabla §1 de
   ``docs/tajada_t464_2026-11-24.md``, no se comparan contra otro literal. **Era la 456 hasta la
   tarea 464**, que encontró que la 456 dimensionaba en secuencial: cada compra escalada del día
   agrandaba a la siguiente. Con el sizing del vivo el precio es −2,38 pp por −2,9 pp de caída.
   **Y la 464 hasta la 468**, que encontró que el harness cobraba 0,15% por lado y el vivo ~0,063%:
   con el costo del vivo es −2,37 pp por −8,1 pp, en ``docs/costos_t468_2026-11-25.md``.
2. El −0.34 pp de la T121, el −1.46 pp de la 456 y el −2.38 pp de la 464 sólo aparecen en tramos que
   dicen ``otro marco``.
3. El texto no lleva un conteo ``N de M BUY``.
4. La marca que el texto dice que se cuenta es la que el motor escribe en la razón.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from analysis.harness_config import (
    LIVE_MAX_POSITIONS,
    LIVE_REGIME_SCALE_FACTOR,
    LIVE_WATCHLIST_SIZE,
    HarnessConfig,
    deviations_keyed,
)
from config.settings_manager import settings
from paper_trading.strategies import generate_trades_analyze_single
from tests.test_regime_scale import _SPY_OFF, _account, _patch_analyze, _series

_DOCS = Path(__file__).resolve().parent.parent / "docs"
_VEREDICTO_456 = _DOCS / "activo_pasivo_t456_2026-11-23.md"
_MEDICION_464 = _DOCS / "tajada_t464_2026-11-24.md"
_MEDICION_468 = _DOCS / "costos_t468_2026-11-25.md"
_TRAMOS = re.compile(r";\s|\.\s")


def _texto() -> str:
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE)
    (d,) = [d for d in deviations_keyed(cfg) if d.clave == "regime_scale"]
    return d.texto


def _fila(tabla: str, nombre: str) -> tuple[float, float, float]:
    """(CAGR %, Sharpe, caída %) de la fila del brazo en una tabla de brazos."""
    for linea in tabla.splitlines():
        celdas = [c.strip().replace("*", "").replace("`", "") for c in linea.strip("|").split("|")]
        if len(celdas) == 4 and celdas[0].split(" ")[0] == nombre:
            cagr, sharpe, caida = (float(c.rstrip("%").replace(",", ".")) for c in celdas[1:])
            return cagr, sharpe, caida
    raise AssertionError(f"la tabla no tiene la fila {nombre!r}")


def _seccion(doc: Path, titulo: str) -> str:
    texto = doc.read_text(encoding="utf-8")
    inicio = texto.index(titulo)
    return texto[inicio : texto.index("\n## ", inicio + 1)]


def _tabla_vigente() -> str:
    """La tabla del precio vigente: la 468 (salida, sizing y costo del vivo)."""
    return _seccion(_MEDICION_468, "## 1. El precio con el costo del vivo")


def _num(patron: str, tramo: str) -> float:
    m = re.search(patron, tramo)
    assert m, f"el tramo no tiene {patron!r}: {tramo}"
    return float(m.group(1).replace("−", "-"))


def test_el_precio_citado_es_el_de_la_medicion_vigente_la_468():
    """Mutaciones: los textos de la 464 (costo del harness), de la 459 (la 456 como si fuera el vivo)
    y de antes (la T121) no tienen tramo de la 468 → rojo. Los números salen de la tabla."""
    tramos = [t for t in _TRAMOS.split(_texto()) if "la 468" in t]
    assert len(tramos) == 1, "el desvío tiene que citar el precio de la 468 en un solo tramo"
    (tramo,) = tramos
    con, sharpe_con, caida_con = _fila(_tabla_vigente(), "vivo")
    sin, sharpe_sin, caida_sin = _fila(_tabla_vigente(), "vivo_sin_regimen")
    # Cada celda de la tabla está redondeada: la resta de dos redondeos puede correrse una unidad del
    # último dígito (en la 464, 6,41 − 8,78 = −2,37 y el Δ exacto daba −2,38): la tolerancia es una.
    assert _num(r"([+−-]?\d+\.\d+)pp de CAGR", tramo) == pytest.approx(con - sin, abs=0.0101)
    assert _num(r"([+−-]?\d+\.\d+) de Sharpe", tramo) == pytest.approx(sharpe_con - sharpe_sin, abs=0.0101)
    assert _num(r"([+−-]?\d+\.\d+)pp de maxDD", tramo) == pytest.approx(caida_con - caida_sin, abs=0.101)
    assert "stop duro apagado" in tramo and f"{LIVE_MAX_POSITIONS} slots" in tramo
    assert "la misma tajada" in tramo, "el marco vivo incluye el sizing (tarea 464)"
    assert "0.063% por lado" in tramo, "y el costo (tarea 468)"


def test_la_caja_equivalente_citada_es_la_de_la_468():
    tramo = next(t for t in _TRAMOS.split(_texto()) if "la 468" in t)
    citado = _num(r"rinde ([+−-]?\d+\.\d+)pp más", tramo)
    fila = next(ln for ln in _seccion(_MEDICION_468, "## 3.").splitlines() if "(costo del vivo)" in ln)
    assert f"{citado:+.2f}".replace(".", ",") + " pp" in fila.replace("*", ""), (citado, fila)


def test_las_tablas_son_las_que_se_creen():
    """Contraprueba del parser: si leyera otra fila, los tests de arriba compararían contra basura."""
    assert _fila(_tabla_vigente(), "vivo") == (11.35, 0.77, 21.4)
    assert _fila(_tabla_vigente(), "vivo_sin_regimen") == (13.72, 0.79, 29.5)
    tabla_464 = _seccion(_MEDICION_464, "## 1. El precio con la tajada por día")
    assert _fila(tabla_464, "vivo") == (6.41, 0.47, 25.5)
    tabla_456 = _seccion(_VEREDICTO_456, "## 1. La muestra completa")
    assert _fila(tabla_456, "vivo") == (7.32, 0.52, 22.9)


def test_el_precio_de_la_464_se_declara_de_otro_marco():
    """El −2.38 pp de la 464 tiene el marco de la cuenta salvo el costo (0,15% por lado)."""
    tramos = [t for t in _TRAMOS.split(_texto()) if "−2.38pp" in t]
    assert tramos, "el desvío dejó de citar a la 464; si se saca a propósito, este test se va"
    for tramo in tramos:
        cita = tramo[tramo.index("−2.38pp") :]
        assert "otro marco" in cita and "0.15% por lado" in cita, tramo
        assert "la 456" not in cita[: cita.index("otro marco")], f"el «otro marco» es de otra cita: {tramo}"


def test_el_precio_de_la_456_se_declara_de_otro_marco():
    """El −1.46 pp de la 456 tiene los slots, los tickers y la salida de la cuenta, y el sizing
    secuencial del harness: es otro marco, y el «otro marco» tiene que ser el suyo."""
    tramos = [t for t in _TRAMOS.split(_texto()) if "−1.46pp" in t]
    assert tramos, "el desvío dejó de citar a la 456; si se saca a propósito, este test se va"
    for tramo in tramos:
        cita = tramo[tramo.index("−1.46pp") :]
        assert "otro marco" in cita and "secuencial" in cita, tramo
        assert "T121" not in cita[: cita.index("otro marco")], f"el «otro marco» es de otra cita: {tramo}"


def test_el_precio_de_la_T121_se_declara_de_otro_marco():
    """El «otro marco» tiene que ser el de la T121, no el de la T115 que venga detrás.

    Mutación que motivó la segunda condición: con las dos citas en un mismo tramo, sacarle el
    «otro marco» a la T121 seguía verde, porque el de la T115 satisfacía el ``in``.
    """
    tramos = [t for t in _TRAMOS.split(_texto()) if "−0.34pp" in t]
    assert tramos, "el desvío dejó de citar a la T121; si se saca a propósito, este test se va"
    for tramo in tramos:
        cita = tramo[tramo.index("−0.34pp") :]
        assert "otro marco" in cita and "stop duro prendido" in cita, tramo
        assert "T115" not in cita[: cita.index("otro marco")], f"el «otro marco» es de otra cita: {tramo}"


def test_no_lleva_un_conteo_de_BUY_vivas():
    """Mutación: el texto viejo («0 de 80 BUY vivas …») → rojo."""
    assert not re.search(r"\d+ de \d+ BUY", _texto()), _texto()


def test_la_marca_que_se_cuenta_es_la_que_escribe_el_motor(monkeypatch):
    """Si la razón de la orden cambia, el texto dice cómo contar algo que ya no existe."""
    (marca,) = re.findall(r"«([^»]+)»", _texto())
    settings.set("paper_regime_scale_enabled", True)
    settings.set("paper_regime_scale_factor", LIVE_REGIME_SCALE_FACTOR)
    _patch_analyze(monkeypatch, {"AAA": ("BUY", 0.60)})
    buy_df = _series(0.02, seed=1)
    trades = generate_trades_analyze_single(
        _account(), ["AAA"], [], {"AAA": 100.0}, lambda t: {"AAA": buy_df, "SPY": _SPY_OFF}.get(t)
    )
    (razon,) = [tr.reason for tr in trades if tr.ticker == "AAA"]
    assert marca in razon, (marca, razon)
