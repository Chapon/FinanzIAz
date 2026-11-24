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

1. Los números del tramo de la 456 **son los de su veredicto**: se recalculan de la tabla §1 de
   ``docs/activo_pasivo_t456_2026-11-23.md``, no se comparan contra otro literal.
2. El −0.34 pp de la T121 sólo aparece en un tramo que dice ``otro marco``.
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

_VEREDICTO_456 = Path(__file__).resolve().parent.parent / "docs" / "activo_pasivo_t456_2026-11-23.md"
_TRAMOS = re.compile(r";\s|\.\s")


def _texto() -> str:
    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE)
    (d,) = [d for d in deviations_keyed(cfg) if d.clave == "regime_scale"]
    return d.texto


def _fila(tabla: str, nombre: str) -> tuple[float, float, float]:
    """(CAGR %, Sharpe, caída %) de la fila del brazo en la tabla §1 del veredicto."""
    for linea in tabla.splitlines():
        celdas = [c.strip().replace("*", "").replace("`", "") for c in linea.strip("|").split("|")]
        if len(celdas) == 4 and celdas[0].split(" ")[0] == nombre:
            cagr, sharpe, caida = (float(c.rstrip("%").replace(",", ".")) for c in celdas[1:])
            return cagr, sharpe, caida
    raise AssertionError(f"la tabla §1 del veredicto de la 456 no tiene la fila {nombre!r}")


def _tabla_456() -> str:
    doc = _VEREDICTO_456.read_text(encoding="utf-8")
    inicio = doc.index("## 1. La muestra completa")
    return doc[inicio : doc.index("\n## ", inicio + 1)]


def _num(patron: str, tramo: str) -> float:
    m = re.search(patron, tramo)
    assert m, f"el tramo de la 456 no tiene {patron!r}: {tramo}"
    return float(m.group(1).replace("−", "-"))


def test_el_precio_citado_es_el_del_veredicto_de_la_456():
    """Mutación: el texto viejo (T121 como si fuera el vivo) no tiene tramo de la 456 → rojo."""
    tramos = [t for t in _TRAMOS.split(_texto()) if "la 456" in t]
    assert len(tramos) == 1, "el desvío tiene que citar el precio de la 456 en un solo tramo"
    (tramo,) = tramos
    con, sharpe_con, caida_con = _fila(_tabla_456(), "vivo")
    sin, sharpe_sin, caida_sin = _fila(_tabla_456(), "vivo_sin_regimen")
    assert _num(r"([+−-]?\d+\.\d+)pp de CAGR", tramo) == pytest.approx(con - sin, abs=0.005)
    assert _num(r"([+−-]?\d+\.\d+) de Sharpe", tramo) == pytest.approx(sharpe_con - sharpe_sin, abs=0.005)
    assert _num(r"([+−-]?\d+\.\d+)pp de maxDD", tramo) == pytest.approx(caida_con - caida_sin, abs=0.05)
    assert "stop duro apagado" in tramo and f"{LIVE_MAX_POSITIONS} slots" in tramo


def test_la_tabla_del_veredicto_es_la_que_se_cree():
    """Contraprueba del parser: si leyera otra fila, el test de arriba compararía contra basura."""
    assert _fila(_tabla_456(), "vivo") == (7.32, 0.52, 22.9)
    assert _fila(_tabla_456(), "vivo_sin_regimen") == (8.78, 0.55, 28.4)


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
