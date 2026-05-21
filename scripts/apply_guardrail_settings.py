"""
Aplica los valores recomendados de los lite-pro guardrails al archivo de
configuración del usuario (~/.finanzias/settings.json).

Crea el directorio si no existe y respeta cualquier setting ya guardado;
solo sobrescribe las 4 claves de guardrails. Imprime un diff antes/después
para que sea evidente qué cambió.

Uso:
    python scripts/apply_guardrail_settings.py
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".finanzias" / "settings.json"

RECOMMENDED = {
    "paper_enforce_market_hours": True,
    "paper_min_holding_minutes": 1440,  # 24h: evita flips intradía como SBUX/KO
    "paper_anti_flap_minutes": 4320,  # 3 días: evita round-trips como WMT
    "paper_min_trade_dollars": 100.0,  # sube el umbral mínimo
}


def main() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    current: dict = {}
    if CONFIG_PATH.exists():
        try:
            current = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"WARN: {CONFIG_PATH} no es JSON válido, se reemplaza por completo.")
            current = {}

    print(f"Archivo: {CONFIG_PATH}")
    print("-" * 60)
    print(f"{'CLAVE':<35} {'ANTES':<12} {'DESPUÉS':<12}")
    print("-" * 60)
    for k, new in RECOMMENDED.items():
        before = current.get(k, "<default>")
        marker = "→" if str(before) != str(new) else " "
        print(f"{k:<35} {before!s:<12} {marker} {new}")

    current.update(RECOMMENDED)
    CONFIG_PATH.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    print("-" * 60)
    print(f"OK — settings.json guardado ({len(current)} claves en total).")


if __name__ == "__main__":
    main()
