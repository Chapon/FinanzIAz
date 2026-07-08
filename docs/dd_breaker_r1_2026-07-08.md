# R1 — Circuit breaker de drawdown a nivel cuenta (pre-registro)

**Fecha:** 2026-07-08 · **Estado:** PRE-REGISTRO (umbral fijado antes de codear, regla 2) · detector puro shippeado como enabler; gate/UI pendientes del veredicto del harness E4.

## Contexto

Grep confirmado 2026-07-06: **no existe nada** que reduzca la operatoria de la cuenta ante pérdidas acumuladas — jun-jul −$1.596 y el motor siguió idéntico. Es el guardrail estándar de cualquier desk (degradar: menos sizing → solo exits → halt) y, como los stops, **no depende de que la señal tenga alpha**. Complementa `kill_only` (estático) con una respuesta dinámica al régimen propio de la cuenta.

**Urgencia (2026-07-07):** la cuenta está en su drawdown máximo histórico AHORA (~9.5% desde el peak del 14/5, equity 49.257 vs 54.415) — exactamente el escenario para el que este guardrail existe.

## Diseño

Cuando el drawdown de la cuenta supera el umbral desde el peak de una ventana rolling, la cuenta pasa **sola** a modo "solo exits":

- Los **BUYs se suprimen** con warning visible en el `ScanResult` + banner en UI.
- **Stops / ATR-exits / SELLs de señal siguen corriendo** — el breaker nunca frena una salida (misma filosofía que el screen E1b y el ADV cap: solo toca candidatos de entrada, jamás lo tenido).
- **Rearme manual** de Chapa (no se auto-desarma al recuperarse; una recuperación transitoria no debe reabrir la canilla de BUYs sola).

### Parámetros pre-registrados (decisión de Chapa, 2026-07-08)

| Flag | Default | Valor primario pre-registrado | Rol |
|------|---------|-------------------------------|-----|
| `paper_dd_breaker_enabled` | `False` | — | Master switch. OFF = sin cambio de comportamiento. |
| `paper_dd_breaker_pct` | `0.15` | **15%** | DD desde el peak de la ventana que arma el breaker. |
| `paper_dd_breaker_window_days` | `90` | **90 días** | Ventana rolling para el peak ("peak de los últimos N días"). |

Racional del **15% / 90d**: 15% es el estándar retail y da margen sobre el DD vivo de 9.5% (no corta cada pullback normal, dispara en un stress real). La ventana rolling de 90 días mide el DD contra el peak trimestral reciente, no contra un máximo histórico viejo que mantendría el breaker armado indefinidamente. **En vivo hoy (default OFF) no cambia nada; incluso encendido, con 9.5% < 15% todavía no dispararía.**

### Módulos

- `paper_trading/dd_breaker.py` — decisión **pura** `compute_drawdown_state(current_equity, snapshots, *, threshold_pct, window_days, now)` → `DrawdownState` (testeable offline, sin DB ni red). El peak se calcula sobre los `paper_equity_snapshots` dentro de la ventana **más** el equity actual (un nuevo máximo hoy ⇒ DD 0).
- **(pendiente, tras harness)** `paper_trading/engine.py` — gate nuevo en `run_scan` (estilo Gate 1) que lee `paper_equity_snapshots`, computa el estado y, si `triggered` y el master switch ON, filtra los BUYs del set de trades y agrega el warning. Nunca toca SELL/ATR-exits.
- **(pendiente, tras harness)** `config/settings_manager.py` — los tres `SettingSpec` de arriba.
- **(pendiente, tras harness)** `ui/paper_tab.py` — banner cuando el estado viene `triggered`.

## Kill-criteria (pre-registrado)

> En las ventanas de stress del harness E4 (2018Q4 / 2020 / 2022), el breaker **reduce el max DD ≥ 20% relativo** sin recortar el P/L de las ventanas normales **más de 0.5 pts**. Si no pasa, se documenta y **NO se shipea** el cableado (el detector queda como aviso visual sin acción, o se descarta).

Suite Windows verde es condición transversal de "done" en cada etapa.

## Etapas

1. **Pre-registro + detector puro + tests** (este commit) — no toca decisiones (regla 3). El gate y la UI NO se cablean todavía.
2. **Validación harness E4** — el breaker se evalúa como variante sobre las ventanas de stress; veredicto documentado acá.
3. **Cableado** (solo si PASS) — gate en `run_scan` + flags + banner, **default OFF**. Encenderlo vivo es decisión de Chapa (igual que E1b / ADV cap).

## Notas de diseño

- **Fuente de verdad = `paper_equity_snapshots`**: ya existe (uno por scan), con índice `(account_id, snapshot_at)`. No hace falta esquema nuevo.
- **Peak incluye el equity actual**: evita marcar DD cuando se acaba de hacer un nuevo máximo intra-scan (el snapshot del scan actual todavía no está persistido cuando corre el gate).
- **Ventana rolling vs all-time**: elegida rolling (90d) a propósito — un peak all-time de hace meses dejaría el breaker armado sobre una caída ya digerida. La ventana lo ata al régimen reciente de la cuenta.
- **Rearme manual, no automático**: un rebote transitorio no debe reabrir los BUYs solo. Decisión de Chapa para rearmar (mismo patrón que cualquier halt de desk).
