# Investigación: cómo mejorar la eficacia de la predicción — 2026-07-06

Investigación en internet pedida por Chapa: oportunidades de mejora, opciones nuevas y técnicas con evidencia para subir la eficacia predictiva del motor. Contexto interno: buy_score sin alpha (corr fwd5 ≈ −0.08), XGB per-ticker sobreajustado (val 40 muestras, gap 99/55), jun-jul malo. Cada hallazgo se mapea a FinanzIAs y a las tareas del backlog.

---

## Resumen ejecutivo

La literatura y la práctica de la industria apuntan a que **el problema de FinanzIAs no es raro, y tiene soluciones documentadas**: (1) el mayor salto de precisión documentado no viene de un modelo mejor sino de **cambiar la pregunta** — meta-labeling sobre barreras que ya tenemos implementadas; (2) el sobreajuste del XGB per-ticker es estructural y la solución estándar es **entrenar pooled sobre todos los tickers**; (3) los factores con evidencia viva hoy son **momentum y revisiones de estimaciones** — no los votos técnicos per-ticker que usamos; (4) el harness E4 puede validarse mejor con **CPCV + Deflated Sharpe**, diseñados exactamente para nuestro problema de muestras chicas y múltiples intentos.

---

## 1. Meta-labeling + triple barrier (López de Prado) — LA oportunidad  ·  prioridad MÁXIMA

**Qué dice la evidencia.** En vez de predecir dirección, el modelo secundario aprende a decidir **si actuar o no sobre una señal primaria**, entrenado con etiquetas de la "triple barrera": cada trade histórico se etiqueta según qué tocó primero — take-profit (arriba), stop (abajo) o límite de tiempo (vertical). Hudson & Thames documenta saltos de precisión de 0.21 → 0.39 y accuracy 20% → 77% al filtrar falsos positivos de la señal primaria con un meta-modelo ([paper](https://hudsonthames.org/wp-content/uploads/2022/04/Does-Meta-Labeling-Add-to-Signal-Efficacy.pdf)).

**Por qué nos calza perfecto.**
- **La triple barrera YA existe en FinanzIAs**: stop 2×ATR + TP 4×ATR (`gates.py:69-128`) + el concepto de cap_days. Solo que nunca la usamos para *etiquetar datos de entrenamiento*.
- La arquitectura ya es de dos capas: señal primaria (votos RSI/MACD/SMA/GARCH) + XGB. Pero hoy XGB predice dirección de retorno — la pregunta difícil. Meta-labeling le da la pregunta fácil: *"dada esta señal BUY, ¿el trade tocaría el TP antes que el stop?"*
- Resuelve exactamente el diagnóstico de la tarea 7 (buy_score sin alpha): la señal primaria queda como generadora de candidatos (alto recall) y el meta-modelo filtra calidad (precisión) — y su probabilidad calibrada es el input natural para sizing (tarea 8), que es el uso que López de Prado le da.

**Cómo entraría:** re-etiquetar el histórico del cache con la triple barrera (puro, offline), entrenar el meta-modelo pooled (ver §2), validar en E4 contra el baseline actual. Kill-criteria natural: precisión de BUYs filtrados > sin filtrar, walk-forward OOS.

## 2. Entrenamiento pooled (universal) en vez de per-ticker  ·  prioridad MÁXIMA · arregla un defecto estructural

**Qué dice la evidencia.** Modelos entrenados sobre el pool de todas las acciones superan consistentemente a modelos por-acción; la ventaja es mayor justo donde hay menos datos. 1 año de datos pooled de 500 acciones ≈ 500 años de una sola ([Oxford JFE](https://academic.oup.com/jfec/article/22/2/492/7081291), [deep learning universal](https://arxiv.org/pdf/1803.06917)). El modelo universal generaliza incluso a tickers que no vio en el entrenamiento.

**Por qué nos calza.** Nuestro XGB entrena **un modelo por ticker** con ~500 muestras y val sets de 40 → el warning `val_acc std >8%` en casi todos los tickers y el gap 99/55 son la firma de este defecto. Con 52 tickers × 5-10y pooled, el set de entrenamiento crece ~50× y la calibración isotónica deja de degradar por falta de muestras. Features normalizadas cross-ticker (retornos, z-scores, vol relativa — no precios). Combina naturalmente con §1: el meta-modelo se entrena pooled.

## 3. Factores con evidencia viva: momentum + revisiones de estimaciones  ·  prioridad ALTA

**Qué dice la evidencia.** Momentum es el factor más robusto documentado: consistente en 46 países y >150 años, spread ~9.5% anual entre quintiles top/bottom en Norteamérica; el régimen actual está dominado por **persistencia de tendencia y revisiones de earnings**, mientras value y low-risk vienen rezagados ([Alpha Architect](https://alphaarchitect.com/momentum-factor-investing/), [CFA Institute](https://rpc.cfainstitute.org/blogs/enterprising-investor/2025/momentum-investing-a-stronger-more-resilient-framework-for-long-term-allocators), [JPM Factor Views](https://am.jpmorgan.com/us/en/asset-management/adv/insights/portfolio-insights/asset-class-views/factor/)). El crash risk del momentum se mitiga a ~la mitad con vol-scaling. El Zacks Rank entero se construye sobre revisiones de estimaciones.

**Por qué nos calza.** Es el reemplazo candidato de la señal de selección si el buy_score no pasa la tarea 7: ranking cross-sectional por momentum 12-1 + delta de revisiones. **Ojo:** T05 (cross-sectional) se mató en junio, pero aquel blendeaba momentum *con el score sin alpha* — la variante "momentum/revisiones puros como ranking" nunca se testeó sola. Las revisiones ya se acumulan solas en `analyst_estimate_snapshots` (idea G6, desbloqueo ~fines jul con T-CAT-5b).

## 4. PEAD — drift post-earnings como señal de entrada nueva  ·  prioridad ALTA · opción NUEVA

**Qué dice la evidencia.** El drift post-anuncio de earnings (comprar tras un beat fuerte, 30-60 días de outperformance) sigue vivo según papers 2025 (debate activo, magnitud menor que histórica); la variante EAR (reacción anormal del precio al anuncio) rinde ~7.55%/año anormal. Señales más fuertes: **beat de revenue > beat de EPS**, y "beat and raise" es la más potente ([Quantpedia](https://quantpedia.com/strategies/post-earnings-announcement-effect), [UCLA Anderson](https://anderson-review.ucla.edu/is-post-earnings-announcement-drift-a-thing-again/)).

**Por qué nos calza.** Tenemos TODA la infraestructura y ninguna señal de entrada la usa: surprise_profiles (track record de sorpresas EPS), harvest diario de earnings/news, impact_score, T-CAT-5b llegando con consenso point-in-time. Hoy los earnings solo *bloquean* BUYs (blackout). La opción nueva: **candidato de BUY event-driven post-beat** (entrada el día después del print con sorpresa positiva + reacción de precio positiva), validado en E4. Es además el régimen de señal más compatible con datos EOD gratis (el drift dura semanas, no minutos).

## 5. Filtro de régimen 200dma — evidencia externa para R2  ·  ya en backlog (tarea 6)

La evidencia pública cuantifica lo que R2 propone: SPY sobre/bajo su 200dma discrimina retornos forward (6m: +4.9% vs +2.6%) y el filtro baja el max DD de ~34% a ~19% cediendo CAGR en bull markets ([QuantifiedStrategies](https://www.quantifiedstrategies.com/200-day-moving-average-trading-strategy/)). Refuerza R2 tal como está especificada (validar en ventanas de stress; en rebote va a medir peor — esperable y documentado).

## 6. Vol targeting / inverse-vol sizing — evidencia para la tarea 8  ·  ya en backlog

Evidencia a favor para equities: Sharpe 0.40 → 0.48-0.51 con vol scaling ([Man Group](https://www.man.com/insights/the-impact-of-volatility-targeting)); un caso equal-weight → inverse-vol: Sharpe 0.99 → 1.54 con DD −30.8% → −13.8% ([Concretum](https://concretumgroup.com/position-sizing-in-trend-following-comparing-volatility-targeting-volatility-parity-and-pyramiding/)). **Contra-evidencia honesta:** sobre 103 estrategias, sin mejora sistemática ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0304405X2030132X)) → por eso la tarea 8 exige harness, no fe. Caveat interno: el vol_overlay sizea con GARCH degenerado (α+β=1 frecuente) — usar vol realizada simple como input, no GARCH basura.

## 7. Validación: CPCV + Deflated Sharpe + PBO — upgrade directo de E4  ·  prioridad ALTA

**Qué dice la evidencia.** Walk-forward simple es mejor que in-sample pero sigue siendo UNA partición; **Combinatorial Purged Cross-Validation** genera muchas particiones train/test respetando cronología y purgando solapamiento → menor probabilidad de backtest overfitting que K-Fold/walk-forward ([comparación controlada](https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110)). El **Deflated Sharpe Ratio** corrige el sesgo de selección por múltiples intentos (nuestro caso: cada re-eval A1/T05/T-CAT-6 es un intento más; el mejor de N intentos siempre luce bien por azar) ([López de Prado, 10 reasons ML funds fail](https://www.garp.org/hubfs/Whitepapers/a1Z1W0000054x6lUAA.pdf)).

**Por qué nos calza.** E4 está EN CURSO — es el momento exacto de incorporarlo: CPCV como generador de muestras (más particiones independientes del mismo cache = más poder con los mismos datos, que es literalmente el objetivo de E4) + DSR/PBO como métrica de veredicto en los kill-criteria, contabilizando cuántas variantes se probaron.

## 8. Sentiment con LLM — evidencia para G12  ·  prioridad MEDIA · ya en ideas

Scores de sentiment de LLMs sobre noticias muestran asociación significativa con retornos al día siguiente; long-short con OPT reporta Sharpe 3.05 en paper ([arXiv](https://arxiv.org/abs/2412.19245)) — con caveats fuertes de look-ahead y fragilidad que la propia literatura admite ([review hedge-fund perspective](https://arxiv.org/html/2605.05211v1)). Nuestro qwen local ya lee cada noticia para clasificarla: agregar un score de polaridad al mismo prompt es costo marginal ~cero. Entra como feature del meta-modelo (§1), nunca solo.

---

## Priorización integrada (qué mueve más la aguja de la predicción)

| # | Oportunidad | Evidencia | Costo | Encaja en |
|---|---|---|---|---|
| 1 | Meta-labeling con triple barrera | Precisión 0.21→0.39 documentada | Medio (infra ya existe) | Tarea 7 (redefine), tarea 8 (sizing) |
| 2 | Entrenamiento pooled cross-ticker | Universal > per-stock, robusto | Medio | Fix estructural del XGB |
| 3 | CPCV + DSR en el harness | Menor PBO que walk-forward | Bajo (E4 en curso) | **E4 ya mismo** |
| 4 | PEAD/EAR como entrada event-driven | ~7.5%/año anormal, vivo en 2025 | Medio | Nueva; usa catalyst pipeline ocioso |
| 5 | Momentum + revisiones como ranking | El factor más robusto conocido | Bajo-medio | Tarea 7 (plan B), G6 |
| 6 | Régimen 200dma | DD 34%→19% documentado | Bajo | R2 (tarea 6) — refuerza |
| 7 | Inverse-vol sizing | Sharpe +0.08-0.11 (equities) | Bajo | Tarea 8 — refuerza |
| 8 | Sentiment LLM como feature | Prometedor, frágil | Bajo | G12; feature de #1 |

**Secuencia sugerida:** #3 entra en E4 ahora (es el enabler del resto). #1+#2 son el rediseño del modelo predictivo y se validan con ese harness — juntos redefinen la tarea 7 de "validar o degradar el buy_score" a "reemplazar la pregunta que el modelo responde". #4 y #5 son las señales candidatas independientes. Todo con kill-criteria pre-registrado, como siempre.

**Advertencia transversal** (López de Prado, "10 reasons ML funds fail"): probar muchas variantes y quedarse con la mejor ES el mecanismo del overfitting — por eso #3 va primero: sin DSR/PBO, cada mejora nueva que "pase" el harness puede ser el mejor de N intentos por azar.

---

## Fuentes

- Meta-labeling / triple barrier: [Hudson & Thames — Does Meta-Labeling Add to Signal Efficacy?](https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy-triple-barrier-method/) · [paper PDF](https://hudsonthames.org/wp-content/uploads/2022/04/Does-Meta-Labeling-Add-to-Signal-Efficacy.pdf) · [Quantreo — Triple Barrier Labeling](https://www.newsletter.quantreo.com/p/the-triple-barrier-labeling-of-marco) · [mlfinpy docs](https://mlfinpy.readthedocs.io/en/latest/Labelling.html)
- Pooled/universal training: [Volatility forecasting with ML and intraday commonality (Oxford JFE)](https://academic.oup.com/jfec/article/22/2/492/7081291) · [Universal features of price formation](https://arxiv.org/pdf/1803.06917) · [Pooling and winsorizing ML forecasts](https://www.sciencedirect.com/science/article/pii/S0927539824000732)
- ML cross-sectional: [ML techniques for cross-sectional equity returns (OR Spectrum)](https://link.springer.com/article/10.1007/s00291-022-00693-w) · [Real-time ML in the cross-section](https://cfet.frankfurt-school.de/wp-content/uploads/2024/09/Real_Time_ML.pdf)
- Factores: [Alpha Architect — Momentum evidence](https://alphaarchitect.com/momentum-factor-investing/) · [CFA Institute — Momentum framework](https://rpc.cfainstitute.org/blogs/enterprising-investor/2025/momentum-investing-a-stronger-more-resilient-framework-for-long-term-allocators) · [JPM Factor Views 4Q25](https://am.jpmorgan.com/us/en/asset-management/adv/insights/portfolio-insights/asset-class-views/factor/) · [Morgan Stanley — Factor investing endures](https://www.morganstanley.com/im/en-fi/institutional-investor/insights/articles/factor-investing-endures.html)
- PEAD: [Quantpedia — Post-Earnings Announcement Effect](https://quantpedia.com/strategies/post-earnings-announcement-effect) · [UCLA Anderson Review](https://anderson-review.ucla.edu/is-post-earnings-announcement-drift-a-thing-again/) · [SSRN — earnings surprise + investor attention](https://papers.ssrn.com/sol3/Delivery.cfm/9412a06f-c6aa-4df1-bf29-370fe1bd0399-MECA.pdf?abstractid=4589824)
- Régimen 200dma: [QuantifiedStrategies — 200DMA backtest](https://www.quantifiedstrategies.com/200-day-moving-average-trading-strategy/) · [GraniteShares — 200MA strategy](https://graniteshares.com/institutional/us/en-us/research/the-200-moving-average-strategy-explained/)
- Vol targeting: [Man Group — Impact of Volatility Targeting](https://www.man.com/insights/the-impact-of-volatility-targeting) · [Conditional Volatility Targeting (FAJ)](https://www.tandfonline.com/doi/full/10.1080/0015198X.2020.1790853) · [contra: On the performance of volatility-managed portfolios](https://www.sciencedirect.com/science/article/abs/pii/S0304405X2030132X) · [Concretum — position sizing comparison](https://concretumgroup.com/position-sizing-in-trend-following-comparing-volatility-targeting-volatility-parity-and-pyramiding/)
- Validación: [López de Prado — 10 Reasons ML Funds Fail (GARP)](https://www.garp.org/hubfs/Whitepapers/a1Z1W0000054x6lUAA.pdf) · [Backtest overfitting in the ML era](https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110) · [Deflated Sharpe Ratio](https://www.researchgate.net/publication/286121118_The_Deflated_Sharpe_Ratio_Correcting_for_Selection_Bias_Backtest_Overfitting_and_Non-Normality) · [Purged CV (Wikipedia)](https://en.wikipedia.org/wiki/Purged_cross-validation)
- LLM sentiment: [Sentiment trading with LLMs (arXiv)](https://arxiv.org/abs/2412.19245) · [LLMs for stock forecasting, hedge-fund perspective (arXiv)](https://arxiv.org/html/2605.05211v1) · [LLMs in equity markets (Frontiers)](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1608365/full)
