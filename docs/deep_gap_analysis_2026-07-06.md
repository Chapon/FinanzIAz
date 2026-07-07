# Análisis profundo de faltantes — 2026-07-06

Pedido de Chapa tras el mal junio-julio (win rate 31%→0%, P/L −$1.596; ver conversación 2026-07-06). Complementa `docs/benchmark_plataformas_2026-07-06.md` (gaps vs mercado) con una revisión del **código real**: qué existe, qué existe pero no opera, y qué no existe. Verificado contra `paper_trading/`, `analysis/`, `docs/SETTINGS_REFERENCE.md` y la DB viva (copia read-only).

**Contexto del disparador (medido en la DB, round-trips FIFO Sim Principal):**

| Mes venta | n | Win % | P/L |
|---|---|---|---|
| 2026-04 | 3 | 66.7% | +$1.010 |
| 2026-05 | 25 | 52.0% | +$544 |
| 2026-06 | 13 | 30.8% | −$648 |
| 2026-07 | 2 | 0.0% | −$948 |

Jun-jul por salida: signal 4/10 win (+0.34% medio), atr_stop 0/4 (−4.81%), atr_trail 0/1. Holding medio: ganadores 7.3d vs perdedores 6.8d (no se deja correr nada). 11 de los últimos 15 cierres fueron bajo el costo.

---

## A. Hallazgos nuevos (no estaban en backlog ni benchmark)

### A1. Las decisiones no ven el mercado — solo el propio ticker  ·  severidad ALTA
`analyze()` (analysis/technical.py:567) agrega RSI/MACD/SMA/volumen/GARCH/XGB **del ticker**; `detect_market_regime` y `detect_market_regime_hmm` (analysis/ml_signals.py:198/402) reciben el `df` del mismo ticker. **Ninguna decisión de compra consulta el estado del índice, breadth, ni vol de mercado (VIX).** Si el mercado entra en corrección, el sistema sigue comprando BUYs individuales contra la marea — consistente con el deterioro de junio. Los pros no operan long sin filtro de régimen de mercado (el clásico: no BUYs con SPY bajo su 200dma, o reducir exposición con breadth negativo).
- **Qué haría:** feature nueva pre-registrable para el harness E4: gate de régimen de índice (binario o escalador de exposición). Es distinto del HMM killeado (aquel era señal per-ticker). Kill-criteria natural: mejora P/L o DD en las ventanas de stress de E4.
- **Nota:** requiere cachear un índice (SPY/^GSPC) — hoy la DB no tiene ninguno (verificado).

### A2. No hay benchmark dentro de la app  ·  severidad ALTA · costo BAJO
No existe serie de índice en `historical_data_cache` ni comparación equity-vs-mercado en Métricas/dashboard — las comparaciones "E2 −3.96% vs mercado +1.66%" de las auditorías fueron ad hoc. Consecuencia práctica hoy mismo: **no pudimos distinguir si junio fue culpa del sistema o del mercado.** Sin benchmark continuo no hay forma honesta de saber si el motor agrega alpha.
- **Qué haría:** cachear SPY diario + línea de benchmark en la curva de equity + columna "vs SPY" en el panel mensual de Métricas. Display-only, sin riesgo, sin kill-criteria de trading.

### A3. No hay circuit breaker de drawdown a nivel cuenta  ·  severidad ALTA
Grep de `drawdown|circuit|halt` en `paper_trading/`: solo comentarios. Nada frena, reduce tamaño ni pide confirmación cuando la cuenta acumula pérdidas (jun-jul −$1.596 y el motor siguió idéntico). Todo desk profesional tiene límites de pérdida que degradan la operatoria automáticamente (reduce sizing → solo exits → halt).
- **Qué haría:** guardrail estructural (como los stops: no depende de alpha): p.ej. DD ≥ X% en N días → la cuenta pasa sola a modo "solo exits" + aviso en UI, con rearme manual. Validable en las ventanas de stress de E4.

### A4. El take-profit ATR existe pero jamás ejecuta — dos sistemas de salida en conflicto  ·  severidad MEDIA
`atr_tp_mult=4.0` está implementado y testeado (gates.py:102, engine.py:333) → con stop 2×ATR el diseño implícito ya es **R:R 2:1, exactamente lo que pedía G3**. Pero en la DB viva **no hay ni un solo exit `atr_tp`**: los `analyze SELL` cortan al ganador mucho antes (ganador medio +4.95% en 7.3d; 4×ATR queda lejos). El sistema de niveles (entry/stop/target) está subordinado de facto al flip de señal, que ya sabemos pesimista (post-SELL fwd5 +2.94%, mitad sigue subiendo).
- **Qué haría:** tratarlo junto con la tarea 2 (scale-out+trailing) como **rediseño de la jerarquía de salidas**: ¿quién manda — el nivel o la señal? Variante testeable en E4: SELLs de señal solo cierran parcial mientras el precio esté entre stop y TP; los niveles mandan en los extremos.
- **Bonus inmediato (display-only, sin E4):** mostrar el R:R implícito (dist. al TP / dist. al stop) en cada BUY propuesto — cubre G3 sin tocar decisiones.

### A5. MAE/MFE no se mide  ·  severidad MEDIA · costo BAJO
No hay Maximum Adverse/Favorable Excursion por trade en `analysis/metrics_panel.py` ni en los harness. Es LA herramienta estándar para calibrar stops y targets con datos propios: cuánto fue lo peor/mejor que vio cada trade antes de cerrar. Habría respondido empíricamente: ¿el stop 2×ATR es tight? (A1 lo intentó con n=6; MAE usa TODOS los trades, no solo los que stopearon) ¿dónde debería estar el TP? El histórico para calcularlo ya está en cache.
- **Qué haría:** columna MAE/MFE en round-trips de Métricas + distribución. Alimenta la recalibración de stops (A1 NO-SHIP) y el diseño del target con muestra completa.

### A6. La concentración del book no tiene ni vista ni alarma  ·  severidad MEDIA
El gate de correlación T09 es **vestigial** (gates.py:232 — desconectado porque con 1-2 BUYs/step nunca rechazaba) y `analysis/portfolio_risk.mean_correlation` existe sin consumidor vivo. Pero el problema medido no es el candidato: es el **book** — MU llegó a 46.6%, AAPL 33.3%, MLTX 49.1% sin que nada lo mostrara (lección E1a). Refina el G8 del benchmark con lo que ya hay en el código.
- **Qué haría:** panel display-only en Paper/Métricas: peso por posición, exposición sectorial, correlación media del book, "P/L sin el nombre top" (ya existe la métrica). Sin gates (E1a demostró que caps ciegos recortan ganadores) — primero ver, después decidir.

### A7. Los costos de fricción se registran pero no se agregan  ·  severidad BAJA · costo MÍNIMO
`commission_paid` y `slippage_cost` viven en cada orden (paper_orders) pero ninguna métrica los suma: no sabemos cuánto del P/L se va en fricción (relevante con el churn medido: 41 trips en 2 meses). Card "costo total de fricción / % del P/L bruto" en Métricas.

## B. Confirmaciones de gaps ya conocidos (el código las respalda)

- **B1 · Entradas sin alpha (tarea 3):** el ranking de BUYs es solo `_default_strength("BUY", ml_probability)` (strategies.py:415) — XGB per-ticker con val set de ~40 muestras y gap train/val 99/55. Nada fundamental ni de catalysts entra a la selección, pese a que el pipeline de catalysts ya produce impact/surprise scores (solo se usan en el exit-veto OFF). El score compuesto G2 tiene la mitad de los insumos ya adentro de la app.
- **B2 · Sizing (tarea 4):** `cand_vol` y `cand_prob` ya se calculan por candidato (strategies.py:417-418) para los modos vol-target/Kelly — los hooks están, solo que el modo de la cuenta cae a equal-weight. El costo de activar inverse_vol tras validar en E4 es bajo.
- **B3 · Sin alertas (G10):** el scheduler escanea, pero si la app no está abierta no pasa nada y nadie se entera de un stop/señal. Ni email ni push.
- **B4 · Universo estático (G7):** watchlist curada de 52 nombres vivos (survivorship conocido); no hay screener que renueve candidatos.

## C. Qué NO falta (descartes explícitos)

- **Stops:** funcionan como deben (0/4 win en junio ES el diseño: cortan). A1 ya midió que aflojarlos no es robusto. No tocar por dolor reciente.
- **Guardrails de ejecución:** ADV cap, anti-churn, hysteresis, blackout, sanity de precios, universe screen — por encima del estándar retail.
- **Multi-asset / copy trading / móvil:** fuera de alcance deliberado (ver benchmark §4).

## D. Priorización sugerida (criterio: valor/costo, y qué no depende de E4)

**Sin esperar E4 (display-only o guardrail estructural):**
1. **A2 — Benchmark SPY en app** (barato, corrige ceguera de medición).
2. **A5 — MAE/MFE en Métricas** (barato, calibra stops/targets con muestra completa).
3. **A4-bonus — R:R implícito en cada BUY** (cubre G3 display-only).
4. **A6 — Panel de concentración del book** (la lección MU/MLTX).
5. **A7 — Fricción agregada en Métricas** (trivial).
6. **A3 — Circuit breaker de DD** (guardrail; pre-registrar umbral y validar en stress de E4 antes de default ON).

**Con E4 (tocan decisiones → harness + kill-criteria):**
7. **A1 — Filtro de régimen de mercado** para BUYs (candidato fuerte: explica junio).
8. **A4 — Jerarquía de salidas** nivel-vs-señal (junto con tarea 2).
9. B1/B2 ya están en el backlog como tareas 3 y 4.

---
*Método: exploración de código (engine.py, gates.py, strategies.py, technical.py, ml_signals.py, metrics_panel.py, SETTINGS_REFERENCE.md), DB viva copiada read-only a /tmp (regla 5 de CLAUDE.md), cruces con las auditorías 2026-06-09/17/30 y el benchmark 2026-07-06.*
