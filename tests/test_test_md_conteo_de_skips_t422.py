"""Tarea 422 — el número de skips de más que anuncia ``/test`` es el que tiene la suite.

``.claude/commands/test.md`` decía que el modo sin estado vivo *«difiere en 1 skip del primero»*.
En el done de la 417 (2026-11-11) eran **3**: los tres tests que comparan contra el
``settings.json`` vivo y se saltean con el mismo motivo cuando no existe (130, 181 y 185). Un
número viejo en un texto que se lee en cada done manda a desconfiar de un verde correcto, o a
aceptar un skip de más sin mirarlo.
"""

from __future__ import annotations

import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
_TEST_MD = _RAIZ / ".claude" / "commands" / "test.md"
MOTIVO = "sin settings.json vivo en este entorno"


def skips_por_settings_vivo(carpeta: Path) -> list[str]:
    """Los ``pytest.skip("<MOTIVO>")`` de la suite, como ``archivo:línea``."""
    patron = re.compile(r"pytest\.skip\(\s*[\"']" + re.escape(MOTIVO) + r"[\"']")
    out = []
    for p in sorted(carpeta.glob("test_*.py")):
        texto = p.read_text(encoding="utf-8")
        # Sobre el texto entero, no por línea: un `pytest.skip(` partido en dos no se escapa.
        for m in patron.finditer(texto):
            out.append(f"{p.name}:{texto.count(chr(10), 0, m.start()) + 1}")
    return out


def anunciados(texto: str) -> int:
    """El número de skips de más que declara ``test.md``."""
    m = re.search(r"tiene \*\*(\d+)\*\* skips más que el primero", texto)
    assert m, "test.md ya no declara el número de skips de más con la frase esperada"
    return int(m.group(1))


def test_test_md_anuncia_los_skips_que_tiene_la_suite():
    reales = skips_por_settings_vivo(_RAIZ / "tests")
    texto = _TEST_MD.read_text(encoding="utf-8")
    assert anunciados(texto) == len(reales), f"test.md dice {anunciados(texto)}, la suite tiene {reales}"
    assert MOTIVO in texto, "test.md tiene que nombrar el motivo, para verificar por él"


def test_el_contador_ve_los_skips_y_no_otros(tmp_path):
    # Para que el de arriba no pase en vano: con el motivo (uno partido en dos líneas) y otro motivo.
    (tmp_path / "test_a.py").write_text(
        f'import pytest\npytest.skip("{MOTIVO}")\npytest.skip("otra cosa")\n', encoding="utf-8"
    )
    (tmp_path / "test_b.py").write_text(
        f"pytest.skip(\n    '{MOTIVO}')\npytest.skip('{MOTIVO}')\n", encoding="utf-8"
    )
    assert skips_por_settings_vivo(tmp_path) == ["test_a.py:2", "test_b.py:1", "test_b.py:3"]
