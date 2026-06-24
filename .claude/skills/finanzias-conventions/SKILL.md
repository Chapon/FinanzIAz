---
name: finanzias-conventions
description: Convenciones de trabajo y mapa de arquitectura de FinanzIAs. Usar SIEMPRE al empezar cualquier tarea de desarrollo en este repo — antes de codear, testear, commitear o tocar la base de datos. Cubre el flujo de "done", reglas de .bat/CRLF, seguridad de la DB y el motor de 5 gates.
---

# FinanzIAs — Convenciones del proyecto

App de paper-trading en Python (PyQt6 + SQLite + yfinance). El usuario, Chapa, trabaja en **español rioplatense** y es full-stack. Comunicate en español.

## Regla de oro: qué significa "done"

Una tarea NO está terminada hasta que:

1. **La suite completa pasa en Windows.** El entorno real es Windows con Anaconda. Comando:
   `python -m pytest tests/ -ra -m "not network" --tb=short`
   Los tests marcados `network` pegan a Yahoo de verdad y se saltean (ver `pyproject.toml`). `tests/conftest.py` bloquea cualquier llamada de red accidental en unit tests.
2. **Se commiteó** con mensaje descriptivo en español (`feat(scope): ...`, `fix(scope): ...`, `perf(scope): ...`).
3. Si hay GUI, **revisión visual** antes de cerrar.

Nunca declarar "listo" con tests rojos, implementación parcial o sin correr la suite en Windows.

## Metodología: kill-criteria upfront

Toda feature que toque decisiones de trading se diseña con **criterios de aceptación/kill ANTES de codear**. Si el backtest/replay no supera el umbral pre-registrado, se documenta y **no se shipea**. Ejemplos: `docs/exit_replay_t61_2026-06-10.md`, `docs/catalyst_t_cat_6_reeval_2026-06-12.md`. No se construyen features especulativas sin justificación medida. Roadmap debt máximo: 2 meses.

Features nuevas de scoring/valuación entran primero como **display-only**, NO cableadas a sizing ni a los gates, hasta validarlas con backtest. Razón medida: la auditoría 2026-06-17 mostró que `buy_score` no predice el forward-return a 5 días.

## Trampas conocidas (no repetir)

- **.bat requieren CRLF.** Las herramientas de edición escriben LF y `cmd.exe` parsea mal el batch y muere en silencio. Escribir .bat con CRLF binario explícito y verificar.
- **No escribir la DB desde Linux/sandbox.** `finanzias.db` devuelve "malformed" intermitente vía mounts de Linux mientras el engine de Windows escribe. Para leerla desde un entorno no-Windows: copiar a /tmp primero. Backup sano en `backups/`.
- **Null-byte padding tras edits grandes.** Las ediciones que achican un archivo pueden dejar nulls al final. Verificar con `read_bytes().count(b'\x00')`.

**Guard automático:** `python scripts/check_repo_health.py` chequea las tres trampas de arriba (CRLF en .bat, null-bytes, DB desde no-Windows). Corré `--staged` antes de commitear (lo hace el comando `/ship`).

## Arquitectura del motor (5+ gates)

Núcleo de decisiones en `paper_trading/engine.py`, función `run_scan`. Cuenta activa: **"Sim Principal" (id=1)**. Modo **kill_only** (hmm_enabled=False, stacking_enabled=False; XGBoost y vol_overlay siempre ON).

Gates en orden (ver comentarios en `engine.py`):
- **Gate 1** — market hours.
- **Gate 2** — min holding period (bloquea SELLs prematuros).
- **Gate 2b** — histéresis por score (T6.4): SELLs de señal esperan 3 días hábiles salvo score < 0.25.
- **Gate 2c** — exit-veto por catalyst (T-CAT-4). **DEFAULT OFF.**
- **Gate 3** — anti-flap (bloquea BUY justo tras un SELL del mismo ticker).
- **Gate 3b** — ADV liquidity cap (T10): trimea BUYs con notional > cap×ADV$.
- **Gate 4** — minimum trade size.
- **Gate 5 / 5b** — anti-whipsaw / anti-churn por frecuencia (T6.5).
- **Gate 6** — earnings blackout (bloquea BUYs y SELLs de señal cerca de earnings).

`approve_order` re-aplica Gates 1 y 6 a órdenes viejas. `reconcile_account` barre órdenes en limbo.

Módulos clave: `paper_trading/{engine,gates,account,strategies,costs,models}.py`, `analysis/` (technical, metrics_panel, leads, impact_score, surprise_score), `data/{yahoo_finance,news_sources}.py`, `ui/` (PyQt6), `database/models.py` (SQLite con WAL + busy_timeout).

## Migraciones

Esquema único vía **alembic** (no `_migrate()` manual). `init_db` corre `_alembic_sync`. Ver `docs/schema_management.md`.

## Backlog y roadmap

**Tareas operativas (qué sigue):** `docs/BACKLOG.md` — leerlo al empezar; mover lo cerrado a *Hecho reciente* con el hash del commit; *En curso* máximo 1.

**Estratégico (el por qué):** `docs/roadmap_v3_2026-06-09.md`. Auditorías: `docs/ops_logic_audit_2026-06-17.md`, `docs/trade_decision_audit_2026-06-09.md`.
