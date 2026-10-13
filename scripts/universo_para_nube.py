"""
Arma el ítem ``universo/vivo`` de la tabla de la nube (tarea 355), para pegarlo a mano.

El recolector de Lambda recolecta sobre la lista que publica la app (§7.3 de
``docs/harvest_nube_t196_2026-09-14.md``: una lista estática se desincroniza y recolecta
creíblemente para el universo equivocado, como en la tarea 70). Hasta que la app la
publique sola (tarea 356), la primera lista se carga **a mano** desde la consola de
DynamoDB, y queda declarada como tal: ``origen = "manual"``.

Lee el universo vivo de ``finanzias.db`` (sólo lectura, como el harvest) y escribe el JSON
en el formato tipado de DynamoDB, que la consola acepta en *Create item → JSON view* con
*View DynamoDB JSON* prendido.

Uso:
    python scripts/universo_para_nube.py > universo.json
    python scripts/universo_para_nube.py --tickers AAPL,MSFT
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def item_universo(tickers, ahora: datetime, origen: str) -> dict:
    """El ítem, en JSON plano. Lo usa también la app cuando lo publique (tarea 356)."""
    lista = sorted({str(t).strip().upper() for t in tickers if str(t).strip()})
    if not lista:
        raise ValueError("universo vacío: el recolector no tendría sobre qué correr")
    return {
        "pk": "universo",
        "sk": "vivo",
        "tickers": lista,
        "publicado_at": ahora.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),
        "origen": origen,
    }


def a_dynamodb_json(item: dict) -> dict:
    """JSON plano → el JSON tipado de DynamoDB (sólo strings y listas de strings)."""
    out = {}
    for k, v in item.items():
        if isinstance(v, str):
            out[k] = {"S": v}
        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
            out[k] = {"L": [{"S": x} for x in v]}
        else:
            raise TypeError(f"{k}: tipo no soportado {type(v).__name__}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Arma el ítem universo/vivo para la consola de DynamoDB (T355).")
    ap.add_argument("--tickers", default=None, help="lista separada por comas (default: la cuenta viva)")
    args = ap.parse_args(argv)
    if args.tickers:
        tickers = [t for t in args.tickers.split(",") if t.strip()]
    else:
        from scripts.harvest_catalysts import resolve_universe

        tickers = resolve_universe()
    item = item_universo(tickers, datetime.now(timezone.utc), "manual")
    print(json.dumps(a_dynamodb_json(item), indent=2))
    print(f"{len(item['tickers'])} tickers", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
