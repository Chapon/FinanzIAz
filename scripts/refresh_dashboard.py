"""Refresca el artifact del dashboard de Sim Principal en un paso.

Lee ``finanzias.db`` (en Windows la DB se lee coherente, sin el problema de
virtiofs del sandbox), genera el snapshot JSON con ``build_payload`` y lo
inyecta reemplazando la línea ``const DATA = ...;`` del index.html del
artifact. Al reabrir el artifact muestra los datos frescos.

Uso:
    python scripts\\refresh_dashboard.py [ruta_index.html] [account_id]

Por defecto apunta al artifact "finanzias-sim-principal-dashboard" y account 1.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

from scripts.dashboard_data import build_payload, _json_default, DEFAULT_ACCOUNT_ID  # noqa: E402

DEFAULT_ARTIFACT = Path(
    r"C:\Users\chapa\Documents\Claude\Artifacts"
    r"\finanzias-sim-principal-dashboard\index.html"
)
DATA_LINE_RE = re.compile(r"(?m)^const DATA = .*;$")


def main(argv: list[str]) -> int:
    artifact = Path(argv[1]) if len(argv) > 1 else DEFAULT_ARTIFACT
    account_id = int(argv[2]) if len(argv) > 2 else DEFAULT_ACCOUNT_ID

    db_path = REPO / "finanzias.db"
    if not db_path.exists():
        print(f"ERROR: no encuentro la DB en {db_path}")
        return 1
    if not artifact.exists():
        print(f"ERROR: no encuentro el index.html del artifact en {artifact}")
        return 1

    payload = build_payload(db_path, account_id)
    js = json.dumps(payload, ensure_ascii=False, default=_json_default)
    new_line = "const DATA = " + js + ";"

    html = artifact.read_text(encoding="utf-8")
    html2, n = DATA_LINE_RE.subn(lambda _m: new_line, html, count=1)
    if n != 1:
        print(f"ERROR: encontré {n} líneas 'const DATA = ...;' (esperaba 1). "
              "No toco el archivo.")
        return 1

    # Snapshot de respaldo al lado del repo (para inspección / debug).
    (REPO / "dashboard_snapshot.json").write_text(js, encoding="utf-8")

    artifact.write_text(html2, encoding="utf-8")

    npos = len(payload.get("positions", []))
    gen = payload.get("generated_at", "?")
    print(f"OK: snapshot {gen} inyectado · {npos} posiciones abiertas.")
    print("Reabri el artifact del dashboard para ver los datos frescos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
