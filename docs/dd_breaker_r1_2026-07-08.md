# R1 — Circuit breaker de drawdown a nivel cuenta (pre-registro)

**Fecha:** 2026-07-08 · **Estado:** **CERRADO NO-SHIP (2026-07-09)** — el harness falló el kill-criteria de stress (ver *Veredicto* abajo). El detector puro quedó shippeado como enabler (hash `7bdb4c8`); el **gate/flags/UI NO se cablean** (regla 2). El detector permanece disponible como aviso visual sin acción.

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

## Veredicto del harness (2026-07-09) — **NO-SHIP**

Harness: `scripts/run_dd_breaker_validation.py` sobre `data/harness_universe_41_10y.txt` (41 tickers, cartera `analyze_single` equal-weight, 5 slots, step=5, `enable_xgboost=False`, capital inicial $50k). Una sola corrida 10y baseline vs breaker (contexto de equity continuo, warmup resuelto). Semántica del breaker en el replay: stateful, se arma al cruzar DD ≥ 15% y se desarma a un nuevo peak de la ventana de 90d (proxy **más permisivo** que el rearme manual vivo — reabre BUYs antes, no después). Artefacto: `data/dd_breaker_validation/20260709_154647/summary.json` (no versionado, igual que el resto de `data/*_validation/`).

| Ventana de stress | max DD baseline | max DD breaker | reducción rel. |
|---|---|---|---|
| 2018 Q4 | −30.4% | −30.4% | **0.0%** |
| COVID 2020 | −32.9% | −32.9% | **0.0%** |
| Bear 2022 | −35.8% | −33.6% | 6.1% |
| **MEDIA** | −33.0% | −32.3% | **2.2%** |

- **Kill-criteria STRESS: reducción media de DD 2.2% (requiere ≥ 20%) → FAIL.**
- Kill-criteria NORMAL: recorte medio de P/L −1.0 pt (mejoró; requiere ≤ 0.5 pts de recorte) → PASS. Irrelevante ante el FAIL de stress.
- Costo corroborante: el equity terminal 10y cayó **$732.890 → $536.054 (−27%)** suprimiendo 39 steps de entrada, a cambio de ~2% de DD de stress ahorrado. Trade pésimo.

### Causa raíz (por qué era estructuralmente improbable que pasara)

Un breaker que suprime **solo entradas nuevas** no puede reducir un drawdown que proviene del **book ya tenido**. En 2018Q4 y COVID-2020 la reducción fue exactamente **0.0%**: el DD lo generan las 5 posiciones que ya estaban abiertas al entrar el crash, y el breaker —por diseño (regla del pre-registro: "nunca frena una salida", no fuerza exits ni reduce lo tenido)— no las toca. Solo 2022, un bear lento y prolongado, dio algo (6.1%) porque hubo tiempo para que la supresión de entradas evitara *abrir* posiciones nuevas dentro de la caída.

Peor aún, el rearme a nuevo peak de 90d mantiene el breaker armado durante toda la recuperación temprana post-crash (un nuevo peak tras un −35% tarda meses), justo cuando están las mejores entradas del rebote — de ahí el −27% de equity terminal. Las ventanas de "normal" (años calendario 2017/2019/2021) no capturan ese costo porque los rebotes caen en los huecos entre ventanas; el equity terminal sí.

**Reencuadre de R1:** el guardrail estándar de desk "degradar: menos sizing → solo exits → halt" tiene tres escalones. Lo que se testeó es el escalón **"solo exits" (suprimir entradas nuevas)** y resulta **insuficiente para controlar DD** en un book long-only concentrado. Los escalones que sí cortan DD —**reducir sizing / de-grossing (forzar salidas parciales del book)**— son un diseño distinto y más invasivo, y quedaron fuera del alcance pre-registrado a propósito (el breaker "nunca frena una salida"). Un R1-v2 que quiera reducir DD de verdad tendría que des-apalancar lo tenido, lo cual choca con ese principio y necesitaría su propio pre-registro + kill-criteria.

## Etapas

1. **Pre-registro + detector puro + tests** (hash `7bdb4c8`) — no toca decisiones (regla 3). ✅
2. **Validación harness** (hook `breaker_fn` en `portfolio_backtest.py` + `run_dd_breaker_validation.py` + tests). ✅ **Veredicto NO-SHIP** (arriba).
3. **Cableado** (gate/flags/banner) — **NO se ejecuta** (kill-criteria de stress FAIL). El detector queda como aviso visual sin acción; su re-uso o descarte, y un eventual R1-v2 de-grossing, quedan como decisión de Chapa en el backlog.

## Notas de diseño

- **Fuente de verdad = `paper_equity_snapshots`**: ya existe (uno por scan), con índice `(account_id, snapshot_at)`. No hace falta esquema nuevo.
- **Peak incluye el equity actual**: evita marcar DD cuando se acaba de hacer un nuevo máximo intra-scan (el snapshot del scan actual todavía no está persistido cuando corre el gate).
- **Ventana rolling vs all-time**: elegida rolling (90d) a propósito — un peak all-time de hace meses dejaría el breaker armado sobre una caída ya digerida. La ventana lo ata al régimen reciente de la cuenta.
- **Rearme manual, no automático**: un rebote transitorio no debe reabrir los BUYs solo. Decisión de Chapa para rearmar (mismo patrón que cualquier halt de desk).
