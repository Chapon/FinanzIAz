# Investigación #2: leads nuevos, reglas de entrada/salida, predicción — 2026-07-07

Segunda ronda de investigación pedida por Chapa. Complementa `docs/research_prediccion_2026-07-06.md` (meta-labeling, pooled, CPCV/DSR, PEAD) — acá: **dónde encontrar candidatos nuevos**, **cómo mejorar entradas y salidas**, y una técnica de predicción nueva (conformal/abstención).

---

## A. Dónde buscar leads nuevos

### A1. Insider cluster buys (SEC Form 4) — la mejor oportunidad gratis  ·  prioridad ALTA
**Evidencia:** las COMPRAS de insiders (no las ventas) predicen retornos en exceso de 4-8%/año según décadas de literatura; la señal fuerte es el **cluster** — 3+ insiders comprando la misma acción en ~15 días — con el exceso concentrado en los 6 meses siguientes ([Gross.AI research](https://gross.ai/research/sec-form-4-insider-filings-reveal-markets), [MarketTriage](https://markettriage.com/insider-trading-signals), [paper microcaps+GBM](https://arxiv.org/pdf/2602.06198)). Los Form 4 se publican en EDGAR a los 2 días hábiles de la operación — **gratis y point-in-time por diseño** (la fecha de filing es conocida).
**Encaje FinanzIAs:** tenemos TODA la infraestructura SEC ya escrita (`data/news_sources.py` consume EDGAR para 8-K; `edgar_fundamentals.py` companyfacts). Un collector de Form 4 + detector de cluster es incremental. Genera candidatos **fuera de la watchlist** (lead sourcing real) o prior direccional para los 52 actuales. Referencia de producto: [OpenInsider](http://openinsider.com/) (screener gratuito de Form 4). Se valida como fuente de candidatos en E4, igual que PEAD (tarea 9) — son señales hermanas: ambas event-driven, EOD-compatible, con drift de semanas.

### A2. Relative strength / rotación sectorial — embudo de candidatos  ·  prioridad MEDIA
**Evidencia:** screen jerárquico estándar: primero el **sector líder** por relative strength vs SPY (4-12 semanas), después los nombres líderes dentro de ese sector; RS normalizado por ATR es más limpio que RS crudo. En 2022 el RS de XLE lideró meses antes de que los nombres de energía fueran obvios ([StockCharts](https://chartschool.stockcharts.com/table-of-contents/market-analysis/sector-rotation-analysis), [Quantpedia sector momentum](https://quantpedia.com/strategies/sector-momentum-rotational-system), [QuantifiedStrategies RSC](https://www.quantifiedstrategies.com/relative-strength-comparative/)).
**Encaje:** es la capa de "universo dinámico" que le falta al screener (gap G7): en vez de rankear los 52 de siempre, el embudo sector→nombre renueva candidatos. Los ETFs sectoriales (XLE/XLK/...) entran por el mismo cache yfinance. Sinergia directa con el brazo momentum de la tarea 7.

### A3. 13F cloning (hedge funds) — descartar por ahora
**Evidencia mixta:** un paper 2024 reporta clones top-quartile batiendo al SP500, pero la crítica clásica es dura — lag de 45 días, solo el lado long, sin opciones/shorts, y varios estudios no encuentran beneficio ([Quantpedia](https://quantpedia.com/strategies/alpha-cloning-following-13f-fillings), [Bloomberg explainer](https://www.bloomberg.com/explainers/how-investors-read-13f-filings-hedge-funds)). Señal trimestral, vieja, y ya arbitrada por productos comerciales (WhaleWisdom). Form 4 domina en frescura y evidencia → invertir ahí.

## B. Reglas de entrada

### B1. Timing de entrada: pullback > chase, híbrido mejor  ·  prioridad MEDIA
**Evidencia:** entradas por pullback dan mejor win rate y R:R (entrada cerca del soporte → stop más corto) mientras breakouts tienen win ~50% pero capturan los runners; el patrón robusto es el **híbrido**: el breakout/momentum detecta la tendencia, el pullback da el punto de entrada ([QuantifiedStrategies](https://www.quantifiedstrategies.com/pullback-trading/), [TheRobustTrader](https://therobusttrader.com/swing-trading-strategies/)).
**Encaje:** hoy el BUY se ejecuta al scan siguiente de que la señal aparece, a precio de mercado — sin condición de entrada. Mejora testeable en E4: señal BUY activa → esperar pullback (p.ej. retroceso a la EMA20 o retorno negativo del día) antes de fillar, con expiración. Baja el costo de entrada promedio y acorta la distancia al stop → sube el R:R mecánicamente. Es barato de implementar sobre el pipeline de órdenes `pending` que ya existe.

## C. Reglas de salida

### C1. Chandelier exit — recalibrar el trailing que ya tenemos  ·  prioridad ALTA (con V1/MAE-MFE)
**Evidencia:** el trailing ATR adaptativo supera a stops fijos (backtest: profit factor 1.61 vs 1.28 del trailing 10% fijo); la parametrización canónica del chandelier es **highest-high(22) − 3.0×ATR(22)** para swing/position, y un stop 2.5× redujo salidas falsas 28% vs 1.5× con solo 12% más de pérdida media ([StockCharts](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/chandelier-exit), [QuantifiedStrategies](https://www.quantifiedstrategies.com/chandelier-exit-strategy/), [VolatilityBox](https://volatilitybox.com/research/volatility-adjusted-stop-losses/)).
**Encaje:** nuestro `atr_trail` ya ES un chandelier (peak − 2.0×ATR) — pero con multiplicador de day-trading, no de swing. Los datos propios gritan lo mismo: ganadores cortados a 7.3 días, LRCX stopeado por trail. **El multiplicador del trailing (2.0 → 2.5/3.0) es LA recalibración prioritaria** cuando estén MAE/MFE (V1) y el harness E4 — distinta de A1 (que era el stop inicial, NO-SHIP). Nota: aflojar el *trailing* no afloja el *stop inicial* — son riesgos distintos.

### C2. Time stop — la salida que no existe en FinanzIAs  ·  prioridad MEDIA
**Evidencia:** estándar en sistemas swing: si el trade no avanzó en N días, se libera el capital (el "costo de oportunidad" es real con max_positions=5). Complementa la barrera vertical del triple-barrier labeling (tarea 7) — el mismo N sirve para etiquetar y para operar.
**Encaje:** hoy una posición sin señal SELL y sin tocar stop puede quedar meses ociosa ocupando 1 de 5 slots. Testeable en E4 con el replay existente.

## D. Predicción: conformal prediction / abstención con garantías  ·  prioridad MEDIA (post tarea 7)

**Evidencia:** conformal prediction da intervalos/decisiones con **cobertura garantizada sin supuestos distribucionales**; la variante de *selective prediction* formaliza el "abstenerse cuando la incertidumbre es alta" con control del riesgo en lo que sí se opera ([gentle intro](https://arxiv.org/abs/2107.07511), [Selective Conformal Risk Control](https://arxiv.org/html/2512.12844)).
**Encaje:** es el complemento natural del meta-modelo de la tarea 7: en vez de un umbral fijo de probabilidad, un gate conformal que solo deja pasar BUYs cuando el modelo tiene evidencia suficiente — "no operar" como decisión de primera clase con garantía estadística. Barato de agregar sobre el meta-modelo (es un post-procesamiento del score de calibración).

## E. Datos: plan B para yfinance  ·  ver architecture review §2

La fragilidad de yfinance (401 crumb, throttle B3, corrupción E5) tiene alternativas gratis documentadas: **Tiingo** (EOD limpio para backtesting), **Stooq** (EOD global sin key), **Finnhub** (quotes real-time free tier, ya integrado para news), **Alpaca** (real-time gratis con cuenta paper) ([comparativa 2026](https://qveris.ai/guides/stock-api-free-comparison/?lang=en), [nb-data](https://www.nb-data.com/p/best-financial-data-apis-in-2026)). Detalle y diseño en `docs/architecture_review_2026-07-07.md`.

---

## Priorización

| # | Oportunidad | Tipo | Cuándo |
|---|---|---|---|
| 1 | C1 — Recalibrar trailing 2.0→2.5/3.0 (chandelier) | Salida | Con MAE/MFE (V1) + E4 — datos propios ya lo sugieren |
| 2 | A1 — Insider cluster buys (Form 4 EDGAR) | Lead sourcing | Collector ya; validación como señal en E4 (junto a tarea 9) |
| 3 | B1 — Entrada por pullback tras señal | Entrada | Harness E4; barato sobre pipeline pending |
| 4 | C2 — Time stop | Salida | Harness E4; comparte N con triple-barrier (tarea 7) |
| 5 | A2 — Embudo RS sectorial → nombres | Lead sourcing | Con el brazo momentum de tarea 7 (cubre G7) |
| 6 | D — Gate conformal de abstención | Predicción | Post meta-modelo (tarea 7) |
| 7 | A3 — 13F cloning | Lead sourcing | **Descartado** (lag 45d, evidencia mixta) |

Todo entra por harness con kill-criteria pre-registrado (y DSR/PBO de E4 contabilizando intentos).

---

## Fuentes

- Form 4 / insiders: [Gross.AI](https://gross.ai/research/sec-form-4-insider-filings-reveal-markets) · [MarketTriage](https://markettriage.com/insider-trading-signals) · [OpenInsider](http://openinsider.com/) · [GBM en microcaps (arXiv)](https://arxiv.org/pdf/2602.06198)
- 13F: [Quantpedia alpha cloning](https://quantpedia.com/strategies/alpha-cloning-following-13f-fillings) · [SSRN 2024](https://papers.ssrn.com/sol3/Delivery.cfm/5399672.pdf?abstractid=5399672&mirid=1) · [Bloomberg](https://www.bloomberg.com/explainers/how-investors-read-13f-filings-hedge-funds)
- Entradas: [QuantifiedStrategies pullback](https://www.quantifiedstrategies.com/pullback-trading/) · [TheRobustTrader swing](https://therobusttrader.com/swing-trading-strategies/) · [StokesTrades breakout](https://stokestrades.com/breakout-backtest-strategy/)
- Salidas: [StockCharts chandelier](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/chandelier-exit) · [QuantifiedStrategies chandelier](https://www.quantifiedstrategies.com/chandelier-exit-strategy/) · [VolatilityBox ATR stops](https://volatilitybox.com/research/volatility-adjusted-stop-losses/) · [StratBase](https://stratbase.ai/en/blog/average-true-range-trailing-stop)
- RS/sector: [StockCharts sector rotation](https://chartschool.stockcharts.com/table-of-contents/market-analysis/sector-rotation-analysis) · [Quantpedia sector momentum](https://quantpedia.com/strategies/sector-momentum-rotational-system) · [QuantifiedStrategies RSC](https://www.quantifiedstrategies.com/relative-strength-comparative/)
- Conformal: [arXiv 2107.07511](https://arxiv.org/abs/2107.07511) · [Selective Conformal Risk Control](https://arxiv.org/html/2512.12844)
- Data APIs: [qveris comparativa](https://qveris.ai/guides/stock-api-free-comparison/?lang=en) · [nb-data 2026](https://www.nb-data.com/p/best-financial-data-apis-in-2026) · [Medium beyond yfinance](https://medium.com/@trading.dude/beyond-yfinance-comparing-the-best-financial-data-apis-for-traders-and-developers-06a3b8bc07e2)
