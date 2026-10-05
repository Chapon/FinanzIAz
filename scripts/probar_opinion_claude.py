"""Prueba REAL de la opinión de Claude, en la condición de la app (tarea 322).

Por qué existe
--------------
La 320 se verificó corriendo ``claude -p`` desde adentro de una sesión de Claude Code. Esa sesión
le pasa al hijo sus variables ``CLAUDE_CODE_*``, y el hijo se autenticaba por ella: la prueba anduvo
y la app, que no corre adentro de ninguna sesión, fallaba con *«401 API key is invalid»* porque
Claude Code usaba una ``ANTHROPIC_API_KEY`` inválida del usuario. Los tests no lo podían ver: usan
un runner falso.

Este script hace la llamada real con el mismo entorno que la app (``opinion_claude.entorno()``,
sin credenciales de API ni variables de sesión), aunque se lo corra desde una sesión de Claude Code.
Descuenta de la cuota de la suscripción (una pregunta chica, unos segundos).

Uso::

    python scripts/probar_opinion_claude.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from analysis import opinion_claude as oc

    exe = oc.ubicar_claude()
    if not exe:
        print("No se encontró Claude Code.")
        return 2
    print(f"Claude Code: {exe}")
    datos = {
        "ticker": "PRUEBA",
        "precio": 100.0,
        "nota": "Prueba de conexión: respondé MANTENER con confianza 0 y una tesis de una oración.",
    }
    try:
        op = oc.pedir_opinion(datos, exe=exe, timeout_s=120)
    except oc.OpinionError as e:
        print(f"FALLA: {e}")
        return 1
    print(f"OK en {op.segundos:.0f} s: {op.recomendacion} ({op.confianza}) — {op.tesis[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
