"""
Smoke test end-to-end del flujo run_scan → Slack (roadmap T12).

Ejercita el camino REAL del motor: corre ``engine.run_scan`` con el notifier
de producción (``default_notifier``), así que **te llega un mensaje de Slack
de verdad** si todo está bien configurado. Para no ensuciar tu estado real,
todo corre contra una **SQLite en memoria descartable** — NO toca
``finanzias.db`` ni la cuenta Sim Principal, y las órdenes se crean en esa DB
temporal que se descarta al terminar.

Requisitos
----------
- ``slack_notifications_enabled = True`` en ~/.finanzias/settings.json
  (lo dejó así ``scripts/setup_slack.py``).
- ``SLACK_BOT_TOKEN`` seteado en el entorno (y ``slack_channel`` en settings,
  o ``SLACK_CHANNEL`` en el entorno).

Uso
---
    python scripts/slack_smoke_run.py
    python scripts/slack_smoke_run.py --ticker NVDA --mode auto

``--mode manual`` (default) encola una orden pending; ``--mode auto`` la filea.
El mensaje de Slack reflejará [pending] o [filled] según el modo.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _bind_memory_db():
    """Rebindea ENGINE/SessionLocal a SQLite in-memory y crea las tablas."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import paper_trading.models  # noqa: F401  (registra las tablas en Base.metadata)
    from database import models as db_models

    engine = create_engine("sqlite:///:memory:", echo=False)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db_models.ENGINE = engine
    db_models.SessionLocal = maker
    db_models.Base.metadata.create_all(engine)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test run_scan → Slack (DB en memoria).")
    parser.add_argument("--ticker", default="AAPL", help="Ticker a comprar (default: AAPL).")
    parser.add_argument("--mode", choices=("manual", "auto"), default="manual")
    parser.add_argument("--price", type=float, default=100.0, help="Precio simulado (default: 100).")
    args = parser.parse_args()

    from config.settings_manager import settings

    if not settings.get("slack_notifications_enabled", False):
        print("AVISO: slack_notifications_enabled = False → el motor NO va a notificar.")
        print("Corré antes:  python scripts/setup_slack.py --channel <canal>")
        return 2

    _bind_memory_db()

    from paper_trading import engine
    from paper_trading.account import create_account
    from paper_trading.models import PaperWatchlistItem
    from paper_trading.strategies import TargetTrade
    from database.models import session_scope

    acct = create_account(
        name="SMOKE Slack (temporal)",
        initial_capital=10_000.0,
        mode=args.mode,
    )
    with session_scope() as s:
        s.add(PaperWatchlistItem(account_id=acct.id, ticker=args.ticker))

    # Estrategia sintética: un BUY del ticker, con conviction de ejemplo.
    def _buy_strategy(account, watchlist, positions, prices, history_provider):
        return [
            TargetTrade(
                ticker=args.ticker,
                side="BUY",
                target_shares=None,
                target_dollars=1_000.0,
                reason="SMOKE TEST run_scan→Slack",
                source="analyze_single",
                signal_score=0.77,
            )
        ]

    # Override del dispatcher de estrategia y relax de gates que tapan el BUY.
    engine.get_strategy_fn = lambda _name: _buy_strategy
    settings.set("paper_enforce_market_hours", False)
    settings.set("earnings_blackout_days", 0)

    print(f"Corriendo run_scan sobre cuenta temporal (mode={args.mode}, ticker={args.ticker})…")
    print("Notifier: default_notifier (Slack REAL). DB: in-memory (descartable).")
    print("-" * 60)

    # slack_notifier=None → el motor usa default_notifier (Slack real).
    result = engine.run_scan(
        acct.id,
        prices_provider=lambda _t: {args.ticker: args.price},
        history_provider=lambda _t: None,
    )

    if result is None:
        print("run_scan devolvió None (cuenta inactiva?).")
        return 1

    print(result.summary())
    print(f"  generated={result.generated} queued={result.queued} filled={result.filled} skipped={result.skipped}")
    print(f"  órdenes capturadas para Slack: {len(result.new_orders)}")
    for n in result.new_orders:
        print(f"    - {n.side} {n.ticker} [{n.status}] score={n.signal_score}")

    sent = result.queued + result.filled
    if sent == 0:
        print("\nNo se generó ninguna orden → no se envió nada a Slack. Revisá los gates.")
        return 1

    print("\nListo. Si Slack está bien configurado, te debería haber llegado UN mensaje")
    print(f"resumen al canal con la orden de {args.ticker}. Revisá #finanziaz.")
    print("(Esta corrida NO tocó finanzias.db; la cuenta temporal vive solo en memoria.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
