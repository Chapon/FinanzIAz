"""Tarea 283 — ningún toggle visible deja de hacer lo que su rótulo promete.

El defecto (``docs/auditoria_pantalla_resto_2026-10-02.md`` [ST-1]): ``notif`` (*«Notificaciones al
disparar alertas»*) sólo lo leía la tarjeta de Home, que repetía el toggle, y apagarlo no apagaba
nada; ``pre_market`` y ``realtime`` no tenían ningún lector. Este archivo barre los toggles de las
dos pantallas y exige un lector real en el resto del código, para que no nazca otro.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parent.parent
_PANTALLAS = ("ui/settings_tab.py", "ui/home_tab.py")
_NO_CUENTAN = set(_PANTALLAS) | {"config/settings_manager.py"}
# Toggles que no hacen nada **y lo dicen** en su propio rótulo.
_DECLARADOS = {
    "perf_log": "su texto dice «función futura»",
    "rsi_alerts": "su efecto vive en settings_tab._on_toggle: al prenderlo abre el escáner RSI",
}


def _claves_de_toggles() -> set[str]:
    claves: set[str] = set()
    for rel in _PANTALLAS:
        arbol = ast.parse((_REPO / rel).read_text(encoding="utf-8"))
        for n in ast.walk(arbol):
            # Las listas de filas: tuplas (clave, rótulo, …) dentro de una lista.
            if isinstance(n, ast.List):
                for el in n.elts:
                    # Filas de toggle: (clave, rótulo, tooltip|default) — tres elementos. Las
                    # opciones de un desplegable son pares y no cuentan (la primera versión del
                    # barrido las agarraba: «both», «tiered»…).
                    if (
                        isinstance(el, ast.Tuple)
                        and len(el.elts) == 3
                        and isinstance(el.elts[0], ast.Constant)
                        and isinstance(el.elts[0].value, str)
                        and re.fullmatch(r"[a-z_]+", el.elts[0].value)
                        and isinstance(el.elts[1], ast.Constant)
                        and isinstance(el.elts[1].value, str)
                        and " " in el.elts[1].value
                    ):
                        claves.add(el.elts[0].value)
    return claves


def _lectores(clave: str) -> list[str]:
    patron = re.compile(rf"""settings\.get\(\s*["']{clave}["']""")
    out = []
    for f in _REPO.rglob("*.py"):
        rel = f.relative_to(_REPO).as_posix()
        if rel.startswith(("tests/", ".venv/")) or rel in _NO_CUENTAN:
            continue
        if patron.search(f.read_text(encoding="utf-8", errors="replace")):
            out.append(rel)
    return out


def test_el_barrido_encuentra_los_toggles_conocidos():
    """Valida el instrumento antes de creerle: tiene que ver toggles que sabemos que existen."""
    claves = _claves_de_toggles()
    assert {"notif", "confirm_sell", "perf_log", "auto_refresh"} <= claves


def test_cada_toggle_visible_tiene_un_lector_fuera_de_las_pantallas():
    sin_lector = {c for c in _claves_de_toggles() if c not in _DECLARADOS and not _lectores(c)}
    assert not sin_lector, f"toggles que no hacen nada: {sorted(sin_lector)}"


def test_los_toggles_sacados_no_volvieron():
    claves = _claves_de_toggles()
    assert "pre_market" not in claves and "realtime" not in claves


@pytest.mark.parametrize("prendido,popups", [(True, 1), (False, 0)])
def test_notif_gobierna_el_popup_de_alerta(monkeypatch, prendido, popups):
    from config.settings_manager import settings
    from ui import alerts_tab

    settings.set("notif", prendido)
    llamadas = []
    # Desde la 323 el aviso es no modal (`aviso_no_modal`), no `QMessageBox.information`.
    caja = SimpleNamespace(destroyed=SimpleNamespace(connect=lambda f: None))
    monkeypatch.setattr(alerts_tab, "aviso_no_modal", lambda *a, **k: llamadas.append(a) or caja)
    aviso = SimpleNamespace(
        ticker="AAA", current_price=10.0, alert_type="ABOVE", target_value=9.0, message=""
    )
    falso = SimpleNamespace(window=lambda: None, _avisos=[])
    alerts_tab.AlertsTab._avisar(falso, [aviso])
    assert len(llamadas) == popups
