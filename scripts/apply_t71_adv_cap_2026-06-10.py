"""T7.1 (roadmap v3): activar ADV liquidity cap al 5%.

Corre desde la raiz del repo en Windows:

    python scripts/apply_t71_adv_cap_2026-06-10.py

Idempotente. Setea paper_adv_cap_pct = 0.05 (persiste a ~/.finanzias/settings.json)
y muestra el estado final. Con el cap activo, el Gate 3b de run_scan trimea
cualquier BUY cuyo notional supere 5% del ADV$ reciente del ticker.

Verificacion posterior: en el proximo scan, si algun BUY se trimea, el log
muestra el warning de adv_capped_notional. Suite relacionada:

    python -m pytest tests/test_adv_cap.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings_manager import settings

TARGET = 0.05


def main() -> None:
    before = settings.get("paper_adv_cap_pct")
    if before != TARGET:
        settings.set("paper_adv_cap_pct", TARGET)
        print(f"paper_adv_cap_pct: {before} -> {settings.get('paper_adv_cap_pct')}")
    else:
        print(f"paper_adv_cap_pct ya en {before} (no-op)")

    print("estado final:")
    print(f"    paper_adv_cap_pct       = {settings.get('paper_adv_cap_pct')}")
    print(f"    paper_min_trade_dollars = {settings.get('paper_min_trade_dollars')}")


if __name__ == "__main__":
    main()
