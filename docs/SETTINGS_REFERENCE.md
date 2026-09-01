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
| `paper_adv_lookback_days` | `20` | Sesiones para estimar el ADV$ (media de Close×Volume). Consultado por el ADV cap y por el piso de liquidez de E1b. |

## Escalado de exposición por régimen (R2b, tarea 20) — ON
Valida­do por harness (`docs/sizing_exposure_t10_t20_2026-07-22.md`, SHIP): en risk-off, escalar las BUYs nuevas a medio tamaño mejora Sharpe/CAGR y baja el max DD de cartera (a diferencia de suprimirlas, que destruye el compounding — R2a). Activado por decisión de Chapa 2026-07-22. Solo toca BUYs nuevas; nunca posiciones tenidas ni SELLs.
| Flag | Default | Qué hace |
|------|---------|----------|
| `paper_regime_scale_enabled` | `True` (ON) | Cuando el mercado está risk-off (SPY < SMA200, PIT sobre el último close), cada BUY nueva entra a `paper_regime_scale_factor` del tamaño. Fail-open: tamaño pleno si no hay SPY o < 200 barras. |
| `paper_regime_scale_factor` | `0.5` | Multiplicador de tamaño de las BUYs en risk-off. 0.50 = medio tamaño (valor validado). 1.0 = sin escalado. 0.0 = suprimir BUYs en risk-off (NO recomendado — R2a midió que destruye el compounding). |

## Screen de universo (E1b, anti-MLTX) — opt-in
Filtra **candidatos de BUY** (nunca posiciones tenidas) por liquidez y calidad fundamental **antes** de que entren. Validado 2026-07-02 contra la watchlist real (52 nombres): excluye MLTX sin sacar ningún nombre bueno (INTC/TEAM con pérdidas pero revenue real, ASML/TSM sin facts EDGAR → fail-open, todos conservados). Ver `docs/universe_screen_e1b_2026-07-02.md`.
| Flag | Default | Qué hace |
|------|---------|----------|
| `paper_universe_screen_enabled` | `False` (OFF) | Master switch. ON → cada candidato de BUY se filtra por ADV$ (liquidez) y fundamentals EDGAR XBRL (pérdidas sostenidas + revenue nulo/bajo → frágil). OFF = sin cambio de comportamiento ni red. |
| `paper_universe_min_adv_dollars` | `0.0` (OFF) | Piso de ADV$: excluye candidatos con ADV$ (Close×Volume) por debajo. 0 = pata de liquidez apagada. Fail-open si el histórico es muy fino. |
| `paper_universe_fundamentals_enabled` | `True` | Pata fundamental: excluye nombres con net income anual sostenidamente < 0 **y** revenue ausente o < `paper_universe_revenue_floor_dollars`. Fail-open ante facts EDGAR faltantes. |
| `paper_universe_min_negative_years` | `2` | Cuántos años anuales recientes de net income, todos < 0, hacen falta para llamar frágil a un nombre (evita excluir por una pérdida puntual). |
| `paper_universe_revenue_floor_dollars` | `10_000_000` | Un nombre con pérdidas sostenidas es frágil solo si su revenue anual más reciente está por debajo de este piso (≈ pre-revenue). Nombres no rentables pero con revenue real NO se excluyen. |

## Sanity de precios (E5)
| Flag | Default | Qué hace |
|------|---------|----------|
| `price_sanity_band_pct` | `0.5` | Descarta cotizaciones cuya escala difiera del último close diario cacheado por > esta fracción (0.5 = ±50%). Ataca la basura ~10× de Yahoo (KLAC 2026-06-01). Guard en `data/yahoo_finance` (fetch) + `paper_trading/engine` (antes de fillar). `0` desactiva. Fail-open si no hay histórico de referencia. |
| `scale_drift_tolerance_pct` | `0.10` | **(T64)** Desvío relativo entre dos frames `1d` cacheados del mismo ticker a partir del cual se declara **drift de escala**. Cubre la zona muerta **debajo** de la banda de arriba: un split fantasma chico (1.3) deja el histórico fuera de escala con el precio **adentro** de la banda, y el ATR sale de ahí. Se compara sobre las fechas que **solapan**. Declara en cada scan (`_declare_scale_drift`) y **bloquea la ENTRADA, no la salida** (`_price_out_of_band`). **Calibrado**, no elegido: sobre 365 pares del cache real el drift legítimo llega a 1,72% y el único caso real está en 64,2% (`docs/scale_drift_t64_2026-09-01.md`). `0` desactiva. |

## Stops ATR (T01) — opt-in
| Flag | Default | Qué hace |
|------|---------|----------|
| `atr_stops_enabled` | `False` | Activa stops/TP basados en ATR. |
| `atr_period` | `14` | Período del ATR. |
| `atr_stop_mult` | (ver código) | Múltiplo ATR para el stop. |
| `atr_tp_mult` | (ver código) | Múltiplo ATR para el take-profit. |
| `atr_trail_enabled` | `True` | Trailing stop. |
| `atr_trail_mult` | `0.0` | **T53** — múltiplo ATR del *trailing*, desacoplado del stop duro. `0.0` = seguir a `atr_stop_mult` (acople histórico, sin cambio de comportamiento). Valor validado por la T37: `2.0`. |
| `atr_hard_stop_enabled` | `True` | **T53** — sub-switch del *stop duro* desde la entrada. `False` = no dispara nunca, la única barrera de abajo es el trailing (candidato `soff_t2.0` de la T37). Se shipea en `True` (comportamiento histórico); prenderlo/apagarlo es decisión de Chapa (`docs/stop_value_t37_2026-08-27.md`). |

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

## Catalyst harvest horario in-app (tarea 10)
| Flag | Default | Qué hace |
|------|---------|----------|
| `catalyst_hourly_harvest_enabled` | `True` | Harvest-only (sin classify/GPU) cada N min durante RTH, **solo con la app abierta** (rides el tick por minuto del scheduler). El pipeline completo (harvest+classify) corre 1×/día in-app vía `catalyst_refresh_on_open`. (Antes había además una tarea del Windows Task Scheduler a las 15:00; se removió 2026-07-12 — todo corre in-app.) |
| `catalyst_hourly_harvest_minutes` | `60` | Intervalo del harvest horario (piso 15 min). |
| `catalyst_refresh_on_open` | `True` | Refresh diario in-app (harvest+classify) la primera vez que la app abre en el día, si `refresh_due`. Harvest con `--sources yfinance,sec,finnhub` (idéntico al harvest horario y al `.bat` removido; finnhub se saltea solo sin API key). |

## Dashboard refresh in-app (trigger 7 — reemplaza la tarea de Windows)
Regenera el snapshot del artifact del dashboard (`scripts/refresh_dashboard.py`) leyendo `finanzias.db`. Reemplaza la tarea del Windows Task Scheduler que lo corría a las 8:00 (removida 2026-07-12): ahora **solo corre con la app abierta**. Puramente local (sin red); no-op si la DB o el artifact no existen.
| Flag | Default | Qué hace |
|------|---------|----------|
| `dashboard_refresh_enabled` | `True` | Master switch del trigger 7. "Ambos" (Chapa 2026-07-12): refresca 1×/día calendario al abrir la app **y** tras cada scan de la cuenta del dashboard. |
| `dashboard_refresh_account_id` | `1` | Cuenta cuyo snapshot se regenera (Sim Principal). Solo dispara el refresh post-scan de esa cuenta. |

## Catalyst exit-veto (T-CAT-4, Gate 2c) — DEFAULT OFF
Leídos en `engine.py` (proveedor inyectable). Default OFF por kill-criteria no superado (ver skill `backtest-replay-harness`):
`paper_catalyst_exit_veto_enabled` (off), `paper_catalyst_veto_min_score`, `paper_catalyst_veto_gray_high`.

## Notificaciones Slack
El **bot token NUNCA vive acá** — se lee de la env var `SLACK_BOT_TOKEN`. Solo el canal (no secreto) va en settings o en la env var `SLACK_CHANNEL`. Todo fail-open: sin token/canal, cada aviso es no-op. Ver `integrations/slack.py` y `scripts/setup_slack.py`.

| Flag | Default | Qué hace |
|------|---------|----------|
| `slack_notifications_enabled` | `False` | Master switch de órdenes: `run_scan` manda un resumen por escaneo con las órdenes nuevas. |
| `slack_notify_on` | `"both"` | Qué órdenes avisan: `pending` / `filled` / `both`. |
| `slack_channel` | `""` | Canal id/nombre destino (p.ej. `#trading`). Overridable con `SLACK_CHANNEL`. Vacío + sin env ⇒ no manda. |
| `slack_data_outage_enabled` | `True` | Avisa cuando Yahoo se cae de forma sostenida (breaker NET1 nivel ≥2) y al recuperarse. Independiente del master de órdenes. |
| `slack_price_alerts_enabled` | `True` | Avisa cuando una **alerta de precio** dispara (`AlertManager.check_alerts`), batcheado 1 mensaje por chequeo, además del popup. Independiente del master de órdenes. (NOTIF1) |

> Sizing (cuando aplique): `kelly_fraction`, `vol_target_annual`, `max_position_weight`, `ibkr_commission_plan`. Ver el código para defaults exactos.
