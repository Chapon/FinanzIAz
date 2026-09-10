"""Tarea 154 (SETTINGS-FANTASMA) — ningún flag vivo se lee con un fallback inline.

Cinco flags funcionaban sin estar en el `SCHEMA`: el código hacía
``settings.get(clave, fallback)`` y el fallback vivía **al lado del call site**
(``data/yahoo_finance.py:492``, ``:802``; ``paper_trading/scheduler.py:606``, ``:668``,
``:671``).

**Funcionaban, y ése es el problema.** Tres costos, ninguno visible:

* **no salían en `docs/SETTINGS_REFERENCE.md` ni en el schema**, o sea que eran
  invisibles por los dos lados (acá decía *«no salían en la pestaña Settings, que se
  arma del schema»*, y la 160 midió que eso es **falso**: `ui/` no lee el `SCHEMA`);
* su default documentado en ``docs/SETTINGS_REFERENCE.md`` era una **copia a mano** del
  fallback, o sea el defecto de la tarea **137** un nivel más abajo;
* eran las **únicas cinco filas** de esa referencia que el guard de la 137 tuvo que
  exceptuar — el chequeo mecánico existía y no las alcanzaba.

**Y dos no son menores:** ``price_sanity_band_pct`` es la banda del guard que atajó el
caso KLAC (un precio ~10× corrupto que llegó a ejecutar un trade) y
``scale_drift_tolerance_pct`` es el umbral de la tarea 64.

**Comportamiento sin cambios, y verificado como tal.** Los defaults del schema son
**exactamente** los fallbacks que ya corrían, y ninguna de las cinco está escrita en el
``settings.json`` vivo (medido el 2026-09-09), así que ``get`` devuelve el mismo número
por otro camino. Los fallbacks inline se dejan como defensa en profundidad.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from config.settings_manager import DEFAULTS, SCHEMA

_REPO = Path(__file__).resolve().parent.parent

# Los cinco de la tarea, con el fallback que tenían escrito al lado del call site. Es
# la contraprueba de que "declarar" no fue "cambiar el valor".
_FALLBACKS_HISTORICOS = {
    "price_sanity_band_pct": 0.5,
    "scale_drift_tolerance_pct": 0.10,
    "catalyst_refresh_on_open": True,
    "catalyst_hourly_harvest_enabled": True,
    "catalyst_hourly_harvest_minutes": 60,
}


@pytest.mark.parametrize(("clave", "fallback"), _FALLBACKS_HISTORICOS.items())
def test_los_cinco_estan_en_el_schema_con_SU_valor(clave, fallback):
    """Declararlas no puede haber movido ninguna perilla viva.

    Si el default del schema difiere del fallback que corría, esto **cambió el
    comportamiento** de un guard de precios o del scheduler sin que nadie lo pidiera.
    """
    assert clave in SCHEMA, f"{clave} no está declarada en el SCHEMA"
    assert DEFAULTS[clave] == fallback, (
        f"{clave}: el schema dice {DEFAULTS[clave]!r} y el fallback era {fallback!r}"
    )


@pytest.mark.parametrize("clave", _FALLBACKS_HISTORICOS)
def test_cada_una_esta_DOCUMENTADA(clave):
    """Un flag en el schema sin `doc` no aparece explicado en ningún lado, y la
    pestaña Settings lo muestra pelado."""
    assert SCHEMA[clave].doc and len(SCHEMA[clave].doc) > 40


# ── El predicado, que es lo que evita la próxima ─────────────────────────────


# Las que el barrido encontró y **esta** tarea no cerraba. **Quedó vacío el 2026-09-10
# con la tarea 160**, que declaró los seis que eran configuración y sacó del settings el
# séptimo, que era ESTADO (`surprise_last_build`, la marca del último build de
# surprise_profiles: ahora sale del `_meta.built_at` del artefacto). Igual que el
# `_SIN_SCHEMA` del guard de la 137, no se tapó — se volvió innecesario.
#
# CORRECCIÓN de esta tarea, medida al cerrar la 160: acá decía que exponer un flag en la
# pestaña Settings era el costo de declararlo, y **no es así**. `ui/` no menciona `SCHEMA`
# en ninguna línea: `settings_tab.py` arma sus secciones con listas explícitas. Declarar
# no expone; ponerlos en la pestaña es una decisión aparte (tarea 162).
_PENDIENTES_T160: dict[str, str] = {}


def _lecturas_con_fallback() -> list[str]:
    """``settings.get("clave", <algo>)`` con una clave que **no** está en el schema.

    Por AST: un ``settings.get`` con **dos** argumentos y una clave literal. Ése es
    justo el patrón que deja vivir a un flag fuera del schema — el fallback tapa la
    ausencia y nada falla.
    """
    out = []
    for paquete in ("data", "paper_trading", "analysis", "scripts", "ui", "alerts"):
        for p in sorted((_REPO / paquete).rglob("*.py")):
            try:
                arbol = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover
                continue
            for n in ast.walk(arbol):
                if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
                    continue
                if n.func.attr != "get" or len(n.args) != 2:
                    continue
                clave = n.args[0]
                if not (isinstance(clave, ast.Constant) and isinstance(clave.value, str)):
                    continue
                # Sólo nos interesan las lecturas de settings, no `dict.get`.
                receptor = ast.unparse(n.func.value)
                if "settings" not in receptor.lower():
                    continue
                if clave.value not in SCHEMA and clave.value not in _PENDIENTES_T160:
                    out.append(f"{p.relative_to(_REPO).as_posix()}: settings.get({clave.value!r}, …)")
    return out


def test_ninguna_lectura_de_settings_usa_una_clave_fuera_del_schema():
    """**El invariante.** Un flag que se lee con fallback y no está declarado es
    invisible para la UI, para la referencia y para el guard de la 137.

    Si esto se pone rojo, el arreglo casi nunca es agregarle el fallback: es
    **declarar el flag** con el valor que ya corría.
    """
    assert not (fuera := _lecturas_con_fallback()), (
        "estas lecturas de settings usan una clave que NO está en el SCHEMA, así que el "
        "flag no sale en la pestaña Settings ni lo contrasta ningún guard (tarea 154):\n  "
        + "\n  ".join(fuera)
    )


def test_el_barrido_encuentra_lecturas_de_verdad(tmp_path, monkeypatch):
    """Contraprueba del instrumento: sin esto el test de arriba podría estar pasando
    porque el barrido **no mira nada** — el defecto que la 133 y la 141 tuvieron."""
    paquete = tmp_path / "data"
    paquete.mkdir()
    (paquete / "x.py").write_text(
        "from config.settings_manager import settings\n"
        "v = settings.get('clave_que_no_existe_en_el_schema', 42)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("tests.test_settings_fantasma_t154._REPO", tmp_path)
    fuera = _lecturas_con_fallback()
    assert any("clave_que_no_existe_en_el_schema" in f for f in fuera)


def test_la_referencia_documenta_las_cinco():
    """Y que la tabla de `SETTINGS_REFERENCE.md` las siga trayendo: el guard de la 137
    ya las contrasta contra el schema, pero sólo a las que **están** en la tabla."""
    txt = (_REPO / "docs" / "SETTINGS_REFERENCE.md").read_text(encoding="utf-8")
    for clave in _FALLBACKS_HISTORICOS:
        assert re.search(rf"^\|\s*`{clave}`\s*\|", txt, re.M), f"{clave} salió de la referencia"


def test_cada_pendiente_de_la_160_dice_por_que():
    """Una excepción sin motivo escrito es una lista disfrazada de predicado.

    Y con la contraprueba del otro lado: si alguna se declara en el `SCHEMA`, sale de
    acá. Si no, el dict crece y el guard se afloja sin que nadie lo note — que es
    exactamente cómo envejeció el párrafo de la tarea 135.
    """
    for clave, motivo in _PENDIENTES_T160.items():
        assert len(motivo) > 30, f"{clave} sin motivo escrito"
        assert clave not in SCHEMA, f"{clave} ya está en el SCHEMA: sacala de _PENDIENTES_T160"
