# Benchmark de plataformas de inversión con motor de análisis — 2026-07-06

Investigación de mercado pedida por Chapa: principales apps de gestión de inversiones (acciones, FX, commodities) con motor de análisis y sugerencias; features consolidadas y priorizadas; gap analysis contra FinanzIAs.

---

## 1. Principales plataformas del mercado

### Brokers con análisis integrado
| Plataforma | Foco | Motor de análisis / sugerencias |
|---|---|---|
| **thinkorswim (Schwab)** | Trading activo multi-asset (acciones, opciones, futuros, FX) | Charting pro, probability cones, thinkBack (backtest), custom studies |
| **Interactive Brokers (TWS)** | Profesional, multi-asset global | Screeners, risk navigator (exposición por factor), algos de ejecución |
| **Fidelity / Moomoo / Webull** | Retail con research | Research de terceros agregado, order book, charting avanzado |
| **eToro** | Multi-asset (acciones, FX, cripto, commodities) | Copy/social trading: la "sugerencia" es replicar traders top |

### Plataformas de análisis y señales (sin ejecución propia)
| Plataforma | Foco | Motor |
|---|---|---|
| **TradingView** | Charting multi-asset universal | 100+ indicadores, screeners, alertas condicionales, Pine Script (estrategias propias + backtest), señales técnicas de entrada/salida |
| **MetaTrader 5** | FX/CFD/commodities, ejecución automática | Expert Advisors (bots), señales suscribibles, backtest integrado |
| **Trade Ideas (Holly AI)** | Day/swing trading acciones | 60+ estrategias re-backtesteadas **cada noche**; detección de régimen (vol/trend/sector) elige las estrategias activas del día siguiente; señales con entry + stop + target; filtro: win-rate backtesteado >60% y R:R ≥ 2:1 |
| **TrendSpider** | Análisis técnico automatizado | Detección automática de trendlines/patrones, análisis multi-timeframe, alertas dinámicas, backtest de estrategias |

### Scoring / research cuantitativo
| Plataforma | Foco | Motor |
|---|---|---|
| **Danelfin** | Score explicable por acción | ML sobre ~10.000 features/día (600 técnicas + 150 fundamentales + 150 sentiment) → score 1-10 de probabilidad de batir al mercado, **con desglose visible de qué factores pesan** |
| **Kavout (Kai Score)** | Score cuantitativo | Red neuronal sobre miles de millones de datapoints; score 9 históricamente bate al S&P |
| **Zacks** | Fundamentals | Rank basado en **revisiones de estimaciones de EPS** + earnings surprises + cambios de recomendación de brokers |
| **TipRanks (Smart Score)** | Agregación de señales | Score 1-10 sobre 8 factores: ratings de analistas (ponderados por track record del analista), insiders, sentiment de noticias, hedge funds, bloggers, técnicos, fundamentals |
| **Simply Wall St** | Fundamentals visual | Fair value automático (DCF/múltiplos) + snowflake de calidad, reportes auto-generados |
| **WallStreetZen (Zen Ratings)** | Score gratuito | 115 factores fundamentales+técnicos+IA sobre 4.600 acciones diarias |
| **Prospero.ai** | Señales institucionales | Options flow, dark pool activity, sentiment social en tiempo real |

### Gestión de cartera / riesgo
| Plataforma | Foco | Motor |
|---|---|---|
| **Portfolio Visualizer** | Análisis de cartera | Backtests de asignación, Monte Carlo, factor analysis, optimización |
| **Koyfin / FactSet (pro)** | Analytics | Stress testing, modelado de riesgo Monte Carlo, exposición por factor, rebalanceo por reglas |

---

## 2. Features consolidadas (unión de lo que ofrecen)

**Datos y cobertura**
- F1. Datos en tiempo real / intradía (ticks, order book, opciones)
- F2. Multi-asset: acciones, FX, commodities, cripto, opciones/futuros
- F3. Fundamentals profundos point-in-time (estados financieros, estimaciones, revisiones)
- F4. Datos alternativos: insiders, options flow, dark pool, sentiment social/noticias

**Motor de elección (qué comprar)**
- F5. Score compuesto multi-factor (técnico + fundamental + sentiment) por acción
- F6. **Explicabilidad del score** (qué factores lo empujan) — diferenciador clave de Danelfin vs black-box
- F7. Screener multi-factor sobre todo el mercado
- F8. Revisiones de estimaciones de earnings como señal (Zacks)
- F9. Analyst consensus ponderado por track record del analista (TipRanks)
- F10. Fair value automático (DCF/múltiplos) con upside vs precio
- F11. Detección automática de patrones técnicos / trendlines multi-timeframe

**Motor de sugerencias (cuándo y cuánto)**
- F12. Señales completas: entrada + stop + target con R:R explícito
- F13. **Re-backtesting nocturno de estrategias** + rotación por régimen de mercado (Holly)
- F14. Filtro de calidad de señal: solo emitir si win-rate backtesteado y R:R superan umbral
- F15. Position sizing por riesgo (vol targeting / % riesgo por trade)
- F16. Alertas condicionales configurables (precio, indicador, evento) con push
- F17. Backtest/paper trading integrado para validar antes de arriesgar

**Gestión de cartera y riesgo**
- F18. Analytics de cartera: exposición por factor/sector, correlaciones, VaR, stress testing, Monte Carlo
- F19. Rebalanceo sugerido por reglas / optimización de asignación
- F20. Trade journal + métricas de efectividad (win-rate, payoff, atribución)

**Capa social / UX**
- F21. Copy/social trading
- F22. Estrategias programables por el usuario (Pine Script / EAs)
- F23. Asistente IA conversacional de research
- F24. Acceso móvil/web + charting interactivo pro

---

## 3. Priorización — impacto en la calidad de elección y eficiencia de sugerencias

Criterio: cuánto mejora la **selección de nombres** y la **calidad de la señal accionable**, no el confort de UX. Coincide con lo que los reviews destacan como diferenciadores de los líderes.

### Tier 1 — Críticas (definen si las sugerencias sirven)
1. **F14 — Filtro de calidad de señal pre-emisión** (Holly: win-rate >60% + R:R ≥2:1 backtesteados). Sin esto, las señales son ruido con formato.
2. **F13 — Re-backtesting periódico + rotación por régimen.** El alpha decae; los líderes re-validan estrategias contra data reciente en vez de asumir que siguen funcionando.
3. **F5+F6 — Score multi-factor explicable.** Combinar técnico+fundamental+sentiment supera a cualquier señal única, y la explicabilidad permite auditar cuándo desconfiar.
4. **F12 — Señal completa (entry+stop+target).** Una sugerencia sin nivel de invalidación ni objetivo no es accionable.
5. **F15 — Sizing por riesgo.** Determinante del resultado a igual señal; estándar pro (vol targeting / risk parity).
6. **F1 — Datos intradía/tiempo real** para ejecución de stops y señales. Con EOD, los stops se ejecutan tarde y el backtest miente.

### Tier 2 — Altas (mejoran materialmente la elección)
7. **F8 — Revisiones de estimaciones** (la señal fundamental con mejor evidencia — base del Zacks Rank).
8. **F3 — Fundamentals point-in-time** (sin esto todo backtest fundamental tiene lookahead).
9. **F7 — Screener multi-factor amplio** (el universo importa tanto como el ranking).
10. **F18 — Risk analytics de cartera** (concentración, correlaciones, stress: evita que un nombre hunda el book).
11. **F10 — Fair value con upside** (ancla la elección en valuación, no solo momentum).
12. **F4 — Datos alternativos** (insiders/options flow/sentiment: alpha marginal real pero costoso de conseguir gratis).
13. **F16 — Alertas condicionales** (eficiencia operativa: la señal llega cuando ocurre, no cuando mirás).

### Tier 3 — Complementarias
14. F9 (consensus ponderado por track record) · F11 (patrones automáticos) · F17 (paper trading) · F19 (rebalanceo) · F20 (journal) · F22 (estrategias custom).

### Tier 4 — Marginales para la calidad de sugerencia
15. F21 (copy trading) · F23 (asistente IA) · F24 (móvil/charting pro) · F2 (multi-asset — amplitud, no calidad).

---

## 4. Comparación con FinanzIAs

### Lo que FinanzIAs YA tiene (y varios líderes no)
- **F14 parcial pero superior en disciplina:** kill-criteria pre-registrados + validación por harness antes de shipear cualquier señal — más riguroso que la mayoría de las apps retail.
- **F17:** paper trading con motor de gates (ADV cap, anti-churn, hysteresis, earnings blackout, universe screen) — guardrails que ni thinkorswim ofrece out-of-the-box.
- **F20:** pestaña Métricas (round-trips FIFO, payoff ratio, sell timing, hit-rate por banda).
- **F4 parcial:** pipeline de catalysts (SEC 8-K + RSS + Finnhub), clasificador de 17 categorías, impact score, surprise score de earnings.
- **F9 parcial:** recos de analistas + Leads (ranking SP500 por consenso) — sin ponderar por track record.
- **F3 parcial:** EDGAR XBRL para calidad de universo; snapshots diarios de estimaciones acumulándose (T-CAT-5b desbloquea ~fines jul 2026).
- **F13 parcial:** el harness E4 (walk-forward + stress, en curso) es la infraestructura para esto.

### GAPS — lo que nos falta (ordenado por la priorización de §3)

**Tier 1 (atacan la raíz de la calidad de sugerencia)**
1. **G1 · F13 — Re-validación periódica automática de la señal.** Holly re-backtestea cada noche y rota estrategias por régimen. Nosotros validamos una vez al shipear y el alpha puede decaer sin que nadie lo note (el panel de alpha decay T06 lo mide, pero nada re-corre el harness ni ajusta). *Depende de E4.*
2. **G2 · F5/F6 — Score compuesto explicable.** El `buy_score` es solo ML técnico, corr(score, fwd5) ≈ −0.08, black-box (XGBoost inestable). Los líderes combinan técnico + fundamental (revisiones) + sentiment (catalysts que YA recolectamos pero no entran a la selección) y muestran el desglose. *Es la evolución natural de la tarea 3 del backlog.*
3. **G3 · F12 — Target/objetivo en las señales.** Tenemos entry + stop ATR, pero sin target ni R:R explícito → no se puede filtrar por R:R ≥ 2:1 como Holly ni medir payoff esperado ex-ante. *El scale-out+trailing (tarea 2) es medio camino.*
4. **G4 · F15 — Sizing por riesgo.** Hoy equal-weight de facto (config `signal_weighted` miente — tarea 4 del backlog). Ningún líder pro sizea equal-weight.
5. **G5 · F1 — Frecuencia intradía.** Scan discreto sobre EOD = raíz del gap de stops (A1/E4). Ya está en backlog como "subir la frecuencia de scan"; los límites de yfinance (~730d a 1h) acotan el backtest pero no la operación.

**Tier 2**
6. **G6 · F8 — Revisiones de estimaciones como señal de selección.** Recolectamos snapshots de estimaciones pero no calculamos el delta (¿suben o bajan las estimaciones?) ni lo usamos para rankear. Es la señal fundamental con mejor evidencia pública y el dato ya está entrando solo. *Desbloqueo natural post T-CAT-5b.*
7. **G7 · F7 — Screener multi-factor.** Leads rankea solo por consenso de analistas y solo SP500. Falta screener por factores combinados (momentum, calidad, valuación, revisiones) para construir el universo de candidatos.
8. **G8 · F18 — Risk analytics de cartera.** No hay vista de correlaciones entre posiciones, exposición sectorial, ni stress del book (la lección MU/AAPL/MLTX de E1a: concentración ~50% en un nombre pasó sin alarma). Display-only, bajo costo, alto valor defensivo.
9. **G9 · F10 — Fair value con upside.** Ya diseñado (track paralelo del backlog, EDGAR XBRL, display-only). El benchmark confirma que es feature estándar (Simply Wall St, Danelfin).
10. **G10 · F16 — Alertas.** Sin scan corriendo no pasa nada: no hay alertas de precio/condición/catalyst con notificación push o email. Eficiencia operativa pura.

**Tier 3 (evaluar costo/beneficio, no urgentes)**
11. **G11 · F9 — Ponderar analistas por track record** (estilo TipRanks) en Leads, en vez de consenso crudo.
12. **G12 · F4 — Sentiment de noticias cuantificado** como feature del score (el clasificador + qwen ya procesan el texto; falta extraer polaridad y validarla). Options flow / dark pool / insiders: sin fuente gratis viable, descartar por ahora.
13. **G13 · F11 — Detección de patrones/trendlines automática** (TrendSpider). Valor marginal frente a lo anterior.

**Fuera de alcance deliberado (no son gaps, son decisiones)**
- F2 multi-asset (FX/commodities/cripto): el stack yfinance lo permitiría, pero diluye el foco antes de que el motor de acciones demuestre alpha.
- F21 copy/social, F24 móvil: irrelevantes para un sistema personal de escritorio.
- Ejecución real con broker: FinanzIAs es paper por diseño; se re-evalúa si el paper demuestra alpha sostenido.

### Lectura estratégica
El benchmark valida el rumbo del backlog actual: **E4 (poder estadístico) es el prerequisito de los tres gaps más importantes** (G1 re-validación, G2 score compuesto, G4 sizing por riesgo — tareas 2, 3 y 4 ya apuntan ahí). Los gaps nuevos que el backlog NO tiene y valdría agregar como ideas: **G3 (target/R:R en señales), G6 (delta de revisiones como señal), G8 (risk analytics del book) y G10 (alertas)**. La ventaja competitiva de FinanzIAs no es la cantidad de features sino la disciplina de validación — ninguna app retail pre-registra kill-criteria.

---

## Fuentes

- [NerdWallet — Best trading platforms 2026](https://www.nerdwallet.com/investing/best/online-brokers-platforms-for-day-trading) · [Forbes — Best online brokers 2026](https://www.forbes.com/advisor/financial-services/best-online-brokers/) · [Pro Trader Daily — comparación fees/features](https://protraderdaily.com/trading/stock-trading-platform-comparison)
- [WallStreetZen — Best AI stock pickers 2026](https://www.wallstreetzen.com/blog/best-ai-stock-picker/) · [Barebone — Best AI investing apps](https://barebone.ai/resources/best-ai-investing-apps) · [U.S. News — Can AI pick stocks?](https://money.usnews.com/investing/articles/can-ai-pick-stocks)
- [Trade Ideas — Holly AI](https://www.trade-ideas.com/ti-ai-virtual-trade-assistant/) · [DayTradingToolkit — cómo funciona Holly](https://daytradingtoolkit.com/trading-tools-tutorials/trade-ideas-holly-ai-explained) · [Liberated Stock Trader — review](https://www.liberatedstocktrader.com/trade-ideas-review/)
- [TradingView vs MetaTrader 5](https://newyorkcityservers.com/blog/tradingview-vs-metatrader) · [Vantage — MT vs TradingView](https://www.vantagemarkets.com/academy/metatrader-vs-tradingview/) · [ForexBrokers — copy trading 2026](https://www.forexbrokers.com/guides/social-copy-trading)
- [Comparativa Seeking Alpha / Simply Wall St / Zacks / TipRanks](https://www.earnmorelivefreely.com/seeking-alpha-vs-simply-wall-street-vs-morningstar-vs-zacks-tipranks/) · [Danelfin](https://danelfin.com) · [Zacks](https://www.zacks.com/stocks/)
- [WallStreetZen — portfolio risk tools](https://www.wallstreetzen.com/blog/best-portfolio-risk-management-tools/) · [Portfolio Visualizer](https://www.portfoliovisualizer.com/)
