"""Refresca el artifact del dashboard de Sim Principal en un paso.

Lee ``finanzias.db`` (en Windows la DB se lee coherente, sin el problema de
virtiofs del sandbox), genera el snapshot JSON con ``build_payload`` y lo
inyecta reemplazando la línea ``const DATA = ...;`` del index.html del
artifact. Al reabrir el artifact muestra los datos frescos.

Dos formas de uso:

* **CLI / runner manual** (``refrescar_dashboard.bat``)::

      python scripts\\refresh_dashboard.py [ruta_index.html] [account_id]

* **In-app** (``PaperScheduler``, trigger 7): :func:`refresh_dashboard` corre
  en un ``QThread`` una vez al día al abrir y tras cada scan de la cuenta
  (decisión "Ambos", Chapa 2026-07-12), reemplazando la tarea del Windows Task
  Scheduler que corría este script a las 8:00. Es puramente local (sin red) y
  **no lanza** ante DB/artifact faltante: devuelve ``{"ok": False, "reason": ...}``
  para que el scheduler lo loguee y siga.

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


def _default_db_path() -> Path:
    return REPO / "finanzias.db"


def targets_ready(artifact: Path | None = None, db_path: Path | None = None) -> bool:
    """¿Existen la DB y el index.html del artifact? Barato (dos ``exists``).

    El trigger in-app lo usa para no spawnear un ``QThread`` que no tiene nada
    que hacer (p. ej. una máquina sin el artifact del dashboard descargado).
    """
    artifact = Path(artifact) if artifact else DEFAULT_ARTIFACT
    db_path = Path(db_path) if db_path else _default_db_path()
    return db_path.exists() and artifact.exists()


def refresh_dashboard(
    artifact: Path | None = None,
    account_id: int = DEFAULT_ACCOUNT_ID,
    db_path: Path | None = None,
) -> dict:
    """Genera el snapshot fresco e inyecta ``const DATA`` en el index.html.

    Reutilizable desde la CLI y desde el ``PaperScheduler``. **No lanza** por
    condiciones esperables (DB/artifact faltante, sin línea ``DATA``): devuelve
    ``{"ok": False, "reason": str}``. En éxito devuelve ``{"ok": True,
    "positions": int, "generated_at": str, "artifact": str}``.
    """
    artifact = Path(artifact) if artifact else DEFAULT_ARTIFACT
    db_path = Path(db_path) if db_path else _default_db_path()

    if not db_path.exists():
        return {"ok": False, "reason": f"no encuentro la DB en {db_path}"}
    if not artifact.exists():
        return {"ok": False, "reason": f"no encuentro el index.html del artifact en {artifact}"}

    payload = build_payload(db_path, account_id)
    js = json.dumps(payload, ensure_ascii=False, default=_json_default)
    new_line = "const DATA = " + js + ";"

    html = artifact.read_text(encoding="utf-8")
    html2, n = DATA_LINE_RE.subn(lambda _m: new_line, html, count=1)
    if n != 1:
        return {
            "ok": False,
            "reason": f"encontré {n} líneas 'const DATA = ...;' (esperaba 1); no toco el archivo",
        }

    # Snapshot de respaldo al lado del repo (para inspección / debug).
    (REPO / "dashboard_snapshot.json").write_text(js, encoding="utf-8")
    artifact.write_text(html2, encoding="utf-8")

    return {
        "ok": True,
        "positions": len(payload.get("positions", [])),
        "generated_at": payload.get("generated_at", "?"),
        "artifact": str(artifact),
    }


def main(argv: list[str]) -> int:
    artifact = Path(argv[1]) if len(argv) > 1 else None
    account_id = int(argv[2]) if len(argv) > 2 else DEFAULT_ACCOUNT_ID

    res = refresh_dashboard(artifact=artifact, account_id=account_id)
    if not res.get("ok"):
        print(f"ERROR: {res.get('reason')}")
        return 1

    print(f"OK: snapshot {res['generated_at']} inyectado · {res['positions']} posiciones abiertas.")
    print("Reabri el artifact del dashboard para ver los datos frescos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
