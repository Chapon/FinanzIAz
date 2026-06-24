# Referencia de settings — FinanzIAs

Flags definidos en `config/settings_manager.py` (cada uno es un `SettingSpec(tipo, default, ...)` con `doc=`). Acceso vía `settings.get("clave")`. Esta tabla es un resumen; la fuente de verdad es el código.

> **kill_only pisa defaults.** La cuenta activa "Sim Principal" corre en modo kill_only: aunque `hmm_enabled` y `stacking_enabled` tengan default `True` en el spec, en kill_only quedan **OFF**. XGBoost y vol_overlay quedan **ON**.

## Scheduler
| Flag | Default | Qué hace |
|------|---------|----------|
| `paper_scheduler_enabled` | `True` | Master switch del scheduler. |
| `paper_scan_interval_minutes` | `15` | Intervalo del QTimer de fondo (1–1440). |
| `paper_daily_scan_enabled` | `True` | Scan end-of-day estilo cron. |
| `paper_daily_scan_time_et` | `"16:05"` | HH:MM en US/Eastern. |
| `paper_scan_on_startup` | `True` | Escanea todas las cuentas activas al abrir. |
| `paper_market_hours_only` | `True` | Los ticks de intervalo se saltean fuera de RTH. |

## Gates de ejecución
| Flag | Default | Gate | Qué hace |
|------|---------|------|----------|
| `paper_enforce_market_hours` | `True` | 1 | El engine no llena con mercado cerrado. |
| `paper_min_holding_minutes` | `60` | 2 | No vender una posición abierta hace < N min. |
| `paper_signal_sell_min_age_bdays` | `3` | 2b | SELLs de señal esperan esta edad (días hábiles). 0=off. (T6.4) |
| `paper_signal_sell_bypass_score` | `0.25` | 2b | SELLs con score < umbral ejecutan directo (convicción alta). |
| `paper_anti_flap_minutes` | `30` | 3 | No comprar un ticker que recién vendimos (< N min). |
| `paper_min_trade_dollars` | `250.0` | 4 | Saltea BUYs con target < esto (fees dominan). |
| `paper_whipsaw_lookback_days` | `7` | 5 | Bloquea re-BUY si el último ciclo cerró en pérdida dentro de N días. 0=off. |
| `paper_whipsaw_min_loss_pct` | `0.0` | 5 | Solo bloquear si la pérdida fue peor que −X%. 0=cualquier pérdida. |
| `paper_churn_max_cycles` | `3` | 5b | Bloquea re-BUY si ya cerró ≥N ciclos en la ventana, sin importar P/L. (T6.5) |
| `paper_churn_lookback_days` | `10` | 5b | Ventana (días corridos) para contar ciclos del anti-churn. |
| `earnings_blackout_days` | `2` | 6 | Bloquea BUYs cerca de earnings (±N días). |
| `earnings_blackout_block_sells` | `False` | 6 | Si además bloquea SELLs de señal en blackout. |

## Liquidez (ADV cap, T10)
| Flag | Default | Qué hace |
|------|---------|----------|
| `paper_adv_cap_pct` | `0.0` (OFF) | Cap del notional de cada BUY como fracción del ADV$. 0.05 = máx 5% del ADV. Trimea (no bloquea). Opt-in. |
| `paper_adv_lookback_days` | `20` | Sesiones para estimar el ADV$ (media de Close×Volume). Solo si cap > 0. |

## Stops ATR (T01) — opt-in
| Flag | Default | Qué hace |
|------|---------|----------|
| `atr_stops_enabled` | `False` | Activa stops/TP basados en ATR. |
| `atr_period` | `14` | Período del ATR. |
| `atr_stop_mult` | (ver código) | Múltiplo ATR para el stop. |
| `atr_tp_mult` | (ver código) | Múltiplo ATR para el take-profit. |
| `atr_trail_enabled` | `True` | Trailing stop. |

## Señal / overlays
| Flag | Default | Qué hace |
|------|---------|----------|
| `xgb_signal_enabled` | `True` | XGBoost en la señal. (ON en kill_only) |
| `vol_overlay_enabled` | `True` | Vol overlay. (ON en kill_only) |
| `vol_overlay_trim_enabled` | `False` | De-risking activo: trimea el book cuando σ > target (T09). |
| `hmm_enabled` | spec `True` / kill_only **OFF** | Detección de régimen HMM. Killeado. |
| `stacking_enabled` | spec `True` / kill_only **OFF** | Stacking de modelos. Killeado (no determinístico). |
| `cross_sectional_enabled` | `False` | Ranking cross-sectional. KILLED (ruido, T05); dead-code. |
| `paper_history_period` | `"2y"` | Ventana que el scanner pasa a `analyze()`/XGBoost (6mo/1y/2y/5y/10y). |

## Catalyst exit-veto (T-CAT-4, Gate 2c) — DEFAULT OFF
Leídos en `engine.py` (proveedor inyectable). Default OFF por kill-criteria no superado (ver skill `backtest-replay-harness`):
`paper_catalyst_exit_veto_enabled` (off), `paper_catalyst_veto_min_score`, `paper_catalyst_veto_gray_high`.

> Sizing (cuando aplique): `kelly_fraction`, `vol_target_annual`, `max_position_weight`, `ibkr_commission_plan`. Ver el código para defaults exactos.
