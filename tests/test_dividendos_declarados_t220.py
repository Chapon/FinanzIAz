"""Tarea 220 — el desvío de dividendos queda DECLARADO, con su número derivado.

**Las dos patas, verificadas por separado al medirlo:**

* ``data/yahoo_finance.py`` baja **todo** con ``auto_adjust=True`` (``:1805``, ``:1867``),
  así que cada barra cacheada es una serie **total-return**: los dividendos ya están
  reinvertidos en el precio y **todo lo que el harness simula los cobra**.
* ``paper_trading/`` **no menciona dividendos en ninguna línea**. Cuando una posición
  pasa por su ex-date el precio cae y la cuenta **no recibe el efectivo**: lo pierde.

**Medido el 2026-09-21** sobre las tenencias reales de la cuenta 2 (79 tenencias, 54
tickers, contando sólo los ex-dates dentro de cada período de tenencia):
**$322,77 = 0,65% del capital en 3,05 meses ≈ 2,54% anual**, que es el **62%** de todo
el P&L neto realizado de la cuenta en la misma ventana ($521,38). Los dos tickers sin
historial de dividendos —AMD y WBD— **no pagan**, así que el total no está subestimado.

**Por qué se declara en vez de arreglarse acá.** Cerrarlo es una decisión de trading y
tiene tres salidas que **no son equivalentes**: acreditar dividendos en el motor, correr
el harness sin ajustar (re-escribe la base de todos los veredictos publicados, incluida
la T20 que es lo único cableado), o declarar el desvío y corregir sólo el VS SPY. Es la
tarea **221** y la elección es de Chapa. Mientras tanto el desvío **se nombra**, que es
lo que la 152 puso como contrato: un desvío sin clave es un desvío que un pre-registro
puede citar mal.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import analysis.harness_config as hc
from analysis.harness_config import HarnessConfig, deviations_keyed, dividendos_desc

_REPO = Path(__file__).resolve().parent.parent


def _cfg(**kw) -> HarnessConfig:
    """La misma forma que usa ``test_desvios_claves_t152``, para no inventar una."""
    return HarnessConfig(hc.LIVE_MAX_POSITIONS, "x.txt", hc.LIVE_WATCHLIST_SIZE, **kw)


# ── Que esté declarado, y en TODA corrida ────────────────────────────────────


def test_el_desvio_de_dividendos_se_declara():
    claves = {d.clave for d in deviations_keyed(_cfg())}
    assert "dividendos" in claves


@pytest.mark.parametrize("per_trade", [False, True])
def test_se_declara_sea_cual_sea_la_config(per_trade):
    """**Es incondicional, y eso es el punto.** No depende de ningún flag: el harness no
    tiene forma de no cobrarlos (las barras vienen ajustadas) y el motor no tiene forma
    de cobrarlos (no los mira). Un desvío que se declarara sólo en algunas corridas
    dejaría a las otras citándolo de menos."""
    claves = {d.clave for d in deviations_keyed(_cfg(per_trade=per_trade))}
    assert "dividendos" in claves


# ── Los números se DERIVAN, no se escriben ───────────────────────────────────


def test_los_numeros_del_texto_salen_de_las_constantes():
    """Mismo contrato que ``adv_cap_desc`` (tarea 184): cuatro números que un re-medición
    mueve juntos, escritos a mano derivan por separado."""
    txt = dividendos_desc()

    assert f"${hc.DIVIDENDOS_NO_COBRADOS_USD:,.2f}" in txt
    pct = hc.DIVIDENDOS_NO_COBRADOS_USD / hc.DIVIDENDOS_CAPITAL * 100
    assert f"{pct:.2f}%" in txt
    anual = pct * 12.0 / hc.DIVIDENDOS_VENTANA_MESES
    assert f"{anual:.2f}%/año" in txt
    del_pnl = hc.DIVIDENDOS_NO_COBRADOS_USD / hc.DIVIDENDOS_PNL_REALIZADO_USD * 100
    assert f"{del_pnl:.0f}%" in txt


def test_si_se_re_mide_el_monto_el_texto_lo_SIGUE(monkeypatch):
    """La contraprueba del test de arriba: si los números estuvieran escritos a mano,
    esto pasaría igual y el desvío empezaría a mentir en silencio."""
    monkeypatch.setattr(hc, "DIVIDENDOS_NO_COBRADOS_USD", 1_000.0)
    txt = dividendos_desc()

    assert "$1,000.00" in txt
    assert "2.00%" in txt, "1000/50000 = 2,00% del capital"
    assert f"{hc.DIVIDENDOS_NO_COBRADOS_USD / hc.DIVIDENDOS_PNL_REALIZADO_USD * 100:.0f}%" in txt


# ── El texto dice CÓMO LEERLO, que es la mitad que sirve ─────────────────────


def test_el_texto_distingue_cifra_absoluta_de_diferencia_entre_brazos():
    """**La precisión que evita el error de lectura fácil.** El sesgo NO es simétrico:
    sobre el CAGR de un brazo sobrestima, pero sobre la diferencia entre dos brazos es
    en buena medida común porque corren sobre las mismas barras. Decir sólo lo primero
    haría creer que todos los veredictos publicados están mal."""
    txt = dividendos_desc()

    assert "ABSOLUTA" in txt
    assert "DIFERENCIA" in txt


def test_el_texto_NO_afirma_que_el_sesgo_se_cancele_del_todo():
    """Y la otra mitad, que es la honesta: *«en buena medida común»* no es *«común»*. Un
    brazo que cambie el tiempo en mercado cobra distinto dividendo — y el escalado por
    régimen (T20), que es **lo único cableado**, cambia justamente eso. Esa parte **no
    está medida**, y el texto tiene que decirlo en vez de dejarlo implícito."""
    txt = dividendos_desc()

    assert "NO es exactamente común" in txt
    assert "tiempo en mercado" in txt
    assert "NO está medida" in txt


# ── Las dos patas del desvío, fijadas sobre el código y no sobre la prosa ────


def test_el_cache_se_baja_AJUSTADO():
    """Pata 1, atada al código: si algún día se bajara sin ajustar, el desvío cambia de
    signo y este test lo dice antes de que el texto mienta."""
    codigo = (_REPO / "data" / "yahoo_finance.py").read_text(encoding="utf-8")
    assert "auto_adjust=True" in codigo


def test_el_motor_vivo_NO_mira_dividendos():
    """Pata 2, y por AST para no confundir prosa con código.

    Un ``grep`` de ``dividend`` sobre ``paper_trading/`` se satisface con un comentario
    que explique el desvío — es la trampa de las tareas 128/135/216, y la piso seguido.
    Así que se miran **nombres e identificadores**, no texto: si el motor empezara a
    acreditar dividendos (opción (a) de la 221) esto se pone rojo y hay que venir a
    cerrar el desvío en vez de dejarlo declarado de más.
    """
    sospechosos: list[str] = []
    for f in sorted((_REPO / "paper_trading").glob("*.py")):
        arbol = ast.parse(f.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            nombre = None
            if isinstance(nodo, ast.Name):
                nombre = nodo.id
            elif isinstance(nodo, ast.Attribute):
                nombre = nodo.attr
            elif isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nombre = nodo.name
            if nombre and "dividend" in nombre.lower():
                sospechosos.append(f"{f.name}:{nombre}")
    assert not sospechosos, (
        f"el motor vivo parece mirar dividendos: {sospechosos}. Si es la opción (a) de la "
        f"tarea 221, hay que CERRAR el desvío `dividendos`, no dejarlo declarado"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
