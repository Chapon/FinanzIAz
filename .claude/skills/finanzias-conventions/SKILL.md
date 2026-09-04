---
name: finanzias-conventions
description: Convenciones de trabajo y mapa de arquitectura de FinanzIAs. Usar SIEMPRE al empezar cualquier tarea de desarrollo en este repo — antes de codear, testear, commitear o tocar la base de datos. Cubre el flujo de "done", reglas de .bat/CRLF, seguridad de la DB y el motor de 5 gates.
---

# FinanzIAs — Convenciones del proyecto

App de paper-trading en Python (PyQt6 + SQLite + yfinance). El usuario, Chapa, trabaja en **español rioplatense** y es full-stack. Comunicate en español.

## Regla de oro: qué significa "done"

Una tarea NO está terminada hasta que:

1. **Los TRES comandos pasan en Windows.** El entorno real es Windows con Anaconda:
   ```
   python -m pytest tests/ -ra -m "not network" --tb=short
   python -m ruff check .
   python -m ruff format --check .
   ```
   Los tests marcados `network` pegan a Yahoo de verdad y se saltean (ver `pyproject.toml`). `tests/conftest.py` bloquea cualquier llamada de red accidental en unit tests.
   **Ruff entra acá el 2026-09-03 (tarea 106) y no es burocracia:** el done era la suite sola, el job `lint` del CI quedó en rojo el 2026-09-02, y **trece tareas se cerraron declarando "suite verde"** sin enterarse. No mentían — la suite estaba verde; el criterio estaba incompleto, y el único lugar donde ruff corría era un CI que nadie lee.
2. **Se commiteó** con mensaje descriptivo en español (`feat(scope): ...`, `fix(scope): ...`, `perf(scope): ...`), pasando antes los dos guards de `--staged` del paso 3a de `/ship` (`check_repo_health.py` y `check_backlog_integrity.py`) — que son **manuales**, ver *Trampas conocidas*.
3. Si hay GUI, **revisión visual** antes de cerrar.

Nunca declarar "listo" con tests rojos, ruff en rojo, implementación parcial o sin correr los tres comandos en Windows.

## Metodología: kill-criteria upfront

Toda feature que toque decisiones de trading se diseña con **criterios de aceptación/kill ANTES de codear**. Si el backtest/replay no supera el umbral pre-registrado, se documenta y **no se shipea**. Ejemplos: `docs/exit_replay_t61_2026-06-10.md`, `docs/catalyst_t_cat_6_reeval_2026-06-12.md`. No se construyen features especulativas sin justificación medida. Roadmap debt máximo: 2 meses.

Features nuevas de scoring/valuación entran primero como **display-only**, NO cableadas a sizing ni a los gates, hasta validarlas con backtest. Razón medida: la auditoría 2026-06-17 mostró que `buy_score` no predice el forward-return a 5 días.

## Trampas conocidas (no repetir)

- **.bat requieren CRLF.** Las herramientas de edición escriben LF y `cmd.exe` parsea mal el batch y muere en silencio. Escribir .bat con CRLF binario explícito y verificar.
- **No escribir la DB desde Linux/sandbox.** `finanzias.db` devuelve "malformed" intermitente vía mounts de Linux mientras el engine de Windows escribe. Para leerla desde un entorno no-Windows: copiar a /tmp primero. Backup sano en `backups/`.
- **Null-byte padding tras edits grandes.** Las ediciones que achican un archivo pueden dejar nulls al final. Verificar con `read_bytes().count(b'\x00')`.

**Guard MANUAL, y la palabra importa (tarea 98):** `python scripts/check_repo_health.py` chequea
las tres trampas de arriba (CRLF en .bat, null-bytes, DB desde no-Windows). Acá decía *"Guard
automático"* y **era falso**: no está en `.pre-commit-config.yaml`, no está en el CI y no lo
llama ningún test. Su único invocador es el **paso 3a de `/ship`**, o sea que depende de que
alguien lo corra. Un adjetivo equivocado en una skill que se lee cada sesión no es cosmético:
manda activamente a **no** verificar.

**Lo mismo vale para el guard del backlog.** `python scripts/check_backlog_integrity.py --staged`
es la mitad de la tarea 66 que **necesita el diff** —frena un commit que le saque más de 60
líneas netas a `docs/BACKLOG.md`— y también vive sólo en el paso 3a de `/ship`. Estuvo
declarada en `.pre-commit-config.yaml` desde el 2026-09-01 sin correr **ni una vez**, porque
en este repo **no hay ningún hook de git instalado** (tarea 97). La otra mitad (secciones,
punteros) sí corre sola, en la suite.

**Regla que sale de las dos:** en este proyecto **un guard declarado no es un guard cableado**.
Antes de escribir que algo "corre automáticamente", verificá quién lo llama.

## Arquitectura del motor (5+ gates)

Núcleo de decisiones en `paper_trading/engine.py`, función `run_scan`. **Cuenta activa: "Sim Segundo" (id=2)** — `auto`, `equal_weight`, `max_positions=10`. La **cuenta 1 ("Sim Principal") está pausada** (`is_active=0`, último scan 2026-07-01): docs viejos la llaman "la cuenta activa" — confirmar contra `paper_accounts.is_active` antes de sacar conclusiones de comportamiento vivo. Modo **kill_only** (hmm_enabled=False, stacking_enabled=False; XGBoost y vol_overlay siempre ON).

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
