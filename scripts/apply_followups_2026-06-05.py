"""One-shot: cerrar pendientes baratos post-Sprint 4 (2026-06-05).

Corre desde la raíz del repo en Windows:

    python scripts/apply_followups_2026-06-05.py

Hace tres cosas, idempotentes:
  1. paper_min_trade_dollars 50 -> 250 (via settings.set, persiste a ~/.finanzias/settings.json).
  2. Borra entradas stale de settings.json: correlation_gate_enabled, max_avg_correlation
     (el codigo ya no las lee desde el kill del gate en Sprint 3).
  3. Imprime el estado final para confirmar.

Despues de correr esto, validar la suite T10 (necesita el venv con SQLAlchemy):

    python -m pytest tests/test_adv_cap.py tests/test_paper_gates.py tests/test_correlation_gate.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Repo root al path para que `config` sea importable corriendo `python scripts/...`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings_manager import settings

STALE_KEYS = ("correlation_gate_enabled", "max_avg_correlation")
CONFIG_PATH = Path.home() / ".finanzias" / "settings.json"


def main() -> None:
    # 1. paper_min_trade_dollars -> 250
    before = settings.get("paper_min_trade_dollars")
    if before != 250.0:
        settings.set("paper_min_trade_dollars", 250.0)
        print(f"[1] paper_min_trade_dollars: {before} -> {settings.get('paper_min_trade_dollars')}")
    else:
        print(f"[1] paper_min_trade_dollars ya en {before} (no-op)")

    # 2. Borrar stale keys directo del JSON (settings.set no remueve claves)
    if CONFIG_PATH.exists():
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        removed = [k for k in STALE_KEYS if k in raw]
        for k in removed:
            raw.pop(k, None)
        if removed:
            CONFIG_PATH.write_text(json.dumps(raw, indent=2), encoding="utf-8")
            print(f"[2] stale keys removidas: {removed}")
        else:
            print("[2] no habia stale keys (no-op)")
    else:
        print(f"[2] WARN: {CONFIG_PATH} no existe todavia")

    # 3. Estado final (reload desde disco)
    settings.reload() if hasattr(settings, "reload") else None
    print("[3] estado final:")
    print(f"    paper_min_trade_dollars = {settings.get('paper_min_trade_dollars')}")
    print(f"    paper_adv_cap_pct       = {settings.get('paper_adv_cap_pct')}")


if __name__ == "__main__":
    main()
