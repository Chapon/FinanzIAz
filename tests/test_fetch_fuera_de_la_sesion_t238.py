"""Tarea 238 — la regla «ningún fetch con una escritura pendiente» deja de ser un comentario.

El engine la aprendió en el incidente del 2026-07-13 y la dejó escrita en `run_scan`
(«Prefetch de red ANTES de abrir la ventana de escritura»). Dos meses y medio después, la 227
la violó en `alert_manager` con el mismo mecanismo, y costó cinco días de `database is locked`
hasta la 235. La lección vivía en un archivo; el que escribió el otro no tenía por qué leerlo.

**El guard, en dos piezas:**

1. **Barrido estático.** Ninguna llamada a un fetch puede quedar lexicamente adentro de un
   `with session_scope()` / `get_session()`, contando las funciones anidadas definidas ahí
   adentro (corren con la sesión abierta). La población se descubre en todo el código de la
   app, no se enumera.
2. **Excepciones con cobertura.** Un llamador que *necesita* pedir precios con la sesión
   abierta (el scan lee cuenta y watchlist, y el fetch tiene que ir antes del primer flush) se
   declara acá con el motivo y el test que fija su orden o lo corre contra un lock real
   (`tests/lock_real.py`). El guard verifica que ese test exista.

**Lo que NO ve, dicho:** un fetch llamado a través de un helper que no esté en `_FETCH` (por
ejemplo `self._pedir_precios()` que adentro llama a `get_current_price`). El barrido es
léxico. Por eso la lista incluye los providers inyectables del engine, que son el camino por
el que el scan pide red, y cada excepción apunta a un test que corre el código de verdad.
"""

from __future__ import annotations

import ast
import functools
from pathlib import Path

import pytest

from database.models import session_scope
from paper_trading.account import create_account
from paper_trading.engine import approve_order
from paper_trading.models import PaperOrder
from tests.lock_real import FetchQueEscribeElCache

_REPO = Path(__file__).resolve().parent.parent

# Todo el código de la app. Sin `tests/` (los tests abren sesiones para sembrar) ni `alembic/`.
_RAICES = (
    "alerts",
    "analysis",
    "config",
    "data",
    "database",
    "integrations",
    "paper_trading",
    "scripts",
    "ui",
)

# Las funciones que salen a la red Y escriben un cache propio, más los providers inyectables
# del engine, que son como el scan las llama.
_FETCH = frozenset(
    {
        "get_current_price",
        "get_bulk_prices",
        "get_next_earnings_date",
        "get_historical_data",
        "get_dividends_since",
        "prices_provider",
        "earnings_provider",
        "history_provider",
    }
)
_SESIONES = frozenset({"session_scope", "get_session"})

# Llamador → (motivo, test que lo cubre como `archivo::función`).
EXCEPCIONES: dict[str, tuple[str, str]] = {
    "paper_trading/engine.py::run_scan": (
        "lee cuenta, watchlist y posiciones en la misma sesión; precios, earnings e history se "
        "piden ANTES del primer flush (prefetch del incidente 2026-07-13)",
        "tests/test_scan_lock_window.py::test_providers_run_before_first_fill",
    ),
    "paper_trading/engine.py::approve_order": (
        "lee la orden en la sesión y pide el precio antes de cualquier flush; el único flush "
        "previo es el del re-gate bloqueado, que retorna sin pedir precio",
        "tests/test_fetch_fuera_de_la_sesion_t238.py::test_approve_order_pide_el_precio_sin_el_lock_tomado",
    ),
}


def _nombre(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _abre_sesion(nodo: ast.With) -> bool:
    return any(
        isinstance(i.context_expr, ast.Call) and _nombre(i.context_expr) in _SESIONES for i in nodo.items
    )


def fetches_en_sesion(fuente: str) -> list[tuple[str, int, str]]:
    """(función de nivel superior, línea, fetch) de cada fetch adentro de una sesión abierta."""
    hallados: list[tuple[str, int, str]] = []

    def visitar(nodo, funcion: str | None, en_sesion: bool) -> None:
        for hijo in ast.iter_child_nodes(nodo):
            f = funcion
            if isinstance(hijo, (ast.FunctionDef, ast.AsyncFunctionDef)) and funcion is None:
                f = hijo.name
            dentro = en_sesion or (isinstance(hijo, ast.With) and _abre_sesion(hijo))
            if dentro and isinstance(hijo, ast.Call) and _nombre(hijo) in _FETCH:
                hallados.append((f or "<módulo>", hijo.lineno, _nombre(hijo)))
            visitar(hijo, f, dentro)

    visitar(ast.parse(fuente), None, False)
    return hallados


def _metodo_de_clase(fuente: str) -> list[tuple[str, int, str]]:
    """Igual que `fetches_en_sesion`, pero nombrando `Clase.metodo` para los métodos."""
    arbol = ast.parse(fuente)
    out: list[tuple[str, int, str]] = []
    for nodo in arbol.body:
        if isinstance(nodo, ast.ClassDef):
            for m in nodo.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for _f, ln, fe in fetches_en_sesion(ast.unparse(m)):
                        out.append((f"{nodo.name}.{m.name}", m.lineno + ln - 1, fe))
        elif isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.extend(fetches_en_sesion(ast.unparse(nodo)))
    return out


@functools.cache
def barrido(repo: Path = _REPO) -> dict[str, list[str]]:
    """`archivo::función` → los fetch que encontró adentro de una sesión (con línea)."""
    out: dict[str, list[str]] = {}
    for raiz in _RAICES:
        for p in sorted((repo / raiz).rglob("*.py")):
            rel = p.relative_to(repo).as_posix()
            for funcion, linea, fetch in _metodo_de_clase(p.read_text(encoding="utf-8")):
                out.setdefault(f"{rel}::{funcion}", []).append(f"{fetch} (línea ~{linea})")
    return out


# ── El guard ─────────────────────────────────────────────────────────────────


def test_ningun_fetch_adentro_de_una_sesion_sin_declarar():
    sin_declarar = {k: v for k, v in barrido().items() if k not in EXCEPCIONES}
    assert not sin_declarar, (
        "fetch de red adentro de un `with session_scope()`: si la sesión ya escribió, el cache "
        "del fetch espera a su propio llamador hasta el busy_timeout (tareas 235/237). Sacá el "
        "fetch de la sesión, o declaralo en EXCEPCIONES con un test de `tests/lock_real.py`:\n  "
        + "\n  ".join(f"{k}: {v}" for k, v in sin_declarar.items())
    )


def test_no_hay_excepciones_FANTASMA():
    """Una excepción cuyo llamador ya no pide red adentro de la sesión se borra: si queda,
    el día que alguien reintroduzca el fetch ahí va a estar pre-autorizado."""
    fantasmas = set(EXCEPCIONES) - set(barrido())
    assert not fantasmas, f"excepciones sin fetch en sesión que las justifique: {sorted(fantasmas)}"


@pytest.mark.parametrize("llamador", sorted(EXCEPCIONES))
def test_cada_excepcion_apunta_a_un_test_que_EXISTE(llamador):
    _motivo, nodo = EXCEPCIONES[llamador]
    archivo, funcion = nodo.split("::")
    arbol = ast.parse((_REPO / archivo).read_text(encoding="utf-8"))
    nombres = {n.name for n in ast.walk(arbol) if isinstance(n, ast.FunctionDef)}
    assert funcion in nombres, f"{llamador} declara cobertura en {nodo}, que no existe"


# ── Contrapruebas del instrumento ────────────────────────────────────────────

_FORMA_DE_LA_227 = """
class AlertManager:
    def check_alerts(self):
        with session_scope() as session:
            self._rearmar_dia_nuevo(session)
            for ticker in tickers:
                data = get_current_price(ticker)
"""


def test_el_barrido_VE_la_forma_de_la_227():
    assert [(f, fe) for f, _ln, fe in _metodo_de_clase(_FORMA_DE_LA_227)] == [
        ("AlertManager.check_alerts", "get_current_price")
    ]


def test_el_barrido_VE_un_fetch_en_una_funcion_ANIDADA_adentro_de_la_sesion():
    """La forma de `run_scan._earnings_date_for`: la closure corre con la sesión abierta."""
    fuente = "def f():\n    with session_scope() as s:\n        def g(t):\n            return earnings_provider(t)\n"
    assert [(fn, fe) for fn, _ln, fe in fetches_en_sesion(fuente)] == [("f", "earnings_provider")]


def test_el_barrido_NO_acusa_un_fetch_DESPUES_de_la_sesion():
    """La forma de la 237: se sale del `with` y recién ahí se pide red."""
    fuente = "def f():\n    with session_scope() as s:\n        x = 1\n    get_current_price('A')\n"
    assert fetches_en_sesion(fuente) == []


def test_la_poblacion_del_barrido_es_de_verdad():
    """Sin esto, unas raíces mal escritas darían un barrido vacío y un guard verde."""
    archivos = sum(len(list((_REPO / r).rglob("*.py"))) for r in _RAICES)
    assert archivos > 150, f"sólo {archivos} archivos: ¿cambiaron las raíces?"
    assert set(barrido()) >= set(EXCEPCIONES)


# ── La cobertura de `approve_order`, contra el lock real ─────────────────────


def test_approve_order_pide_el_precio_sin_el_lock_tomado(db_archivo):
    a = create_account(name="LockApprove", initial_capital=50_000.0, mode="manual")
    with session_scope() as s:
        orden = PaperOrder(
            account_id=a.id, ticker="AAPL", side="BUY", target_dollars=500.0, status="pending", reason="t238"
        )
        s.add(orden)
        s.flush()
        order_id = orden.id

    fetch = FetchQueEscribeElCache(db_archivo, {"AAPL": 100.0})
    resultado = approve_order(
        order_id, prices_provider=fetch.provider, earnings_provider=lambda _t: None, override_gates=True
    )

    assert fetch.esperas, "el provider no se llamó: el test no probó nada"
    assert fetch.bloqueos == []
    assert resultado is not None and resultado.status != "pending"
