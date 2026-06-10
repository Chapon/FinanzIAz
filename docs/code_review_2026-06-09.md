# Code review integral — 2026-06-09

Alcance: arquitectura, correctness del engine, capa de datos y sesgos quant, calidad de código, tests y deuda técnica. Base: `main` @ `af3cd15` (~42k líneas de Python propio, 572 tests en 46 archivos).

## Veredicto general

El proyecto está en muy buen estado. No se encontró ningún bug crítico en el camino de trading. Las fortalezas estructurales son reales y consistentes: los gates viven como funciones puras en `paper_trading/gates.py` (sin DB, sin settings, sin logger — todo inyectado), los providers de precios/historia/earnings son callables intercambiables que hacen el engine testeable offline, la política fail-open está aplicada de forma uniforme y siempre con logging, y el guard de idempotencia en `_stamp_order_filled` previene double-fill en retries de `approve_order`. `expire_on_commit=False` en el sessionmaker hace seguro el acceso detached a `positions_after` post-commit (verificado — no es bug). El dead code está señalizado explícitamente como vestigial en docstrings con referencia al documento de kill criteria, que es la manera correcta de mantenerlo.

## Hallazgos — severidad media

**M1. Gestión de esquema dual: alembic abandonado de facto vs parches manuales en `init_db()`.** Alembic tiene solo 3 migraciones (la última `0003_paper_positions_high_water_mark`), pero el esquema siguió evolucionando vía `Base.metadata.create_all()` + `ALTER TABLE` manuales en `database/models.py` (líneas ~445-467: `purchase_date`, `signal_score`, `portfolio_sigma`, `slack_notify`). Las tablas nuevas (news_events, snapshots de estimates) solo existen vía create_all. Funciona, pero hay dos fuentes de verdad y el día que se necesite una migración destructiva o un downgrade, alembic va a estar desincronizado. Recomendación: decidir explícitamente — o se retira alembic del repo (y se documenta que el esquema se gestiona por create_all+parches), o se genera una migración catch-up y se vuelve a alembic como único camino.

**M2. T-CAT-3: la entrada al close del mismo día del evento mezcla dos sesgos según la hora de publicación.** `forward_return()` en `analysis/catalyst_reaction.py` entra en el primer día hábil en-o-después de `published_at` normalizado a medianoche. Para una noticia publicada after-hours (ej. 8-K a las 17:30), la "entrada" es el close de ese día — un precio que imprimió antes de la noticia — así que el retorno a 1 día incluye el gap del anuncio: correcto si se quiere medir la reacción del mercado, pero sobreestima el alpha capturable si T-CAT-4 lo usa como expectativa de entrada real. Para una noticia intradía (10:00), el close del día ya absorbió parte de la reacción y el forward return la subestima. Recomendación: dejar el comportamiento actual para "medir reacción" pero documentarlo en el módulo, y cuando T-CAT-4 derive entradas tradeables, usar next-day open (o close del día siguiente) como entry para el componente de alpha esperado.

**M3. Degradación silenciosa del classifier cuando Ollama está caído.** (Arrastrado del review del commit 63e492a.) El scheduler usa `hybrid-ollama`; si Ollama no corre, cada headline cae al heurístico con confidence de hasta 0.60 y el tag de proveniencia (`Classification.classifier`) no se persiste — después no hay forma de saber qué filas etiquetó qwen y cuáles el fallback, y un upgrade posterior con `--max-confidence 0.3` no las retoca. Mitigación barata: grepear "Ollama backend failed" en el log del .bat tras cada corrida; fix real: persistir el tag (columna `classified_by` en news_events).

**M4. `approve_order` no re-aplica los gates al momento de aprobar.** Una orden pendiente creada en modo manual puede aprobarse horas o días después, y el fill ocurre sin re-chequear earnings blackout, market hours ni anti-flap (solo valida precio vivo y cash). Probablemente sea decisión consciente — la aprobación es una acción explícita del usuario — pero no está documentada en el docstring de `approve_order`, y el caso "quedó pendiente del viernes, se aprueba el lunes dentro del blackout de earnings" es exactamente el mousetrap que el Gate 6 existe para prevenir. Recomendación mínima: documentar la decisión; alternativa: re-correr Gates 1 y 6 en la aprobación con override explícito.

## Hallazgos — severidad menor

**m1. Contrato implícito de `TargetTrade` para BUYs no validado.** `_fill_trade` con side BUY usa solo `target_dollars` (budget); un BUY con `target_shares` seteado y `target_dollars=None` se rechaza silenciosamente como "cash insuficiente". Hoy las dos estrategias siempre setean `target_dollars` en BUYs, así que no es bug activo, pero el contrato vive solo por convención. Un `log.warning` (o assert blando) en `_fill_trade` cuando llega un BUY sin `target_dollars` haría el contrato visible.

**m2. `_update_high_water_marks` avanza el HWM aun cuando el scan no ejecuta nada** (mercado cerrado con `paper_enforce_market_hours=True`). El trailing stop del próximo scan usa un peak tomado de un feed fuera de hora. Impacto mínimo en la práctica (precios de feed cerrado ≈ último close), pero si alguna vez se cambia el prices provider a uno con pre/post-market, conviene recordar esta interacción.

**m3. Doble llamada a `analyze()` para posiciones force-exited que están en watchlist** en `generate_trades_analyze_single` (loop de posiciones + loop de candidatos). Pocas filas por scan y el cache TTL 1h de historia lo amortigua; solo ineficiencia.

**m4. Semántica mixta del drift threshold en `portfolio_engine`:** drift relativo (`|actual−target|/target`) para targets > 0, pero absoluto (`actual_w > threshold`) para targets en 0. Es coherente con el backtester (misma lógica replicada), pero la dualidad merece una línea en el docstring porque un threshold de 0.05 significa cosas muy distintas en cada rama.

**m5. XGBoost no determinístico entre runs pese a `random_state=42`** en `analysis/ml_signals.py` — ya descubierto en T05 (Sprint 4). Causa probable: paralelismo interno con `tree_method=hist`. El stacking está killed así que no afecta producción, pero si algún día se reentrena para comparar runs, fijar `n_jobs=1` en la comparación.

**m6. 178 `except Exception` en código de producción.** La gran mayoría son fail-open deliberados y documentados (la concentración en `data/yahoo_finance.py` (29) y `data/news_sources.py` (16) es consistente con su contrato "never raises"), y no se encontró ningún `except:` desnudo ni TODO/FIXME pendiente — eso es notable a este tamaño. Vale un pase ocasional para confirmar que todos loguean (los revisados lo hacen).

## Sesgos quant conocidos (sin cambio de estado)

Siguen vigentes y aceptados los dos sesgos estructurales del data audit de 2026-05-26: lookahead por `auto_adjust=True` en `get_historical_data` (los ajustes por dividendos/splits reescriben el pasado) y survivorship en la watchlist (52/52 vivos). No son bugs — están documentados — pero cualquier lift medido contra el baseline hereda ambos. El catalyst stack (T-CAT-0..3) en cambio está construido genuinamente point-in-time (append-only, `published_at` real, dedup por content_hash con flush temprano) y es la parte del proyecto con mejor higiene de datos.

## Tests y deuda

572 tests en 46 archivos con buena cobertura del camino crítico (gates: 458 líneas de tests; ATR stops: 549; earnings gate: 421). El dead code (cross_sectional en `analysis/ranking.py` + harness, `feature_switch.py`, `select_uncorrelated_picks`) está correctamente aislado detrás de defaults en False y señalizado — no urge borrarlo, pero si en 2-3 sprints nadie lo revive, considerar podarlo para reducir superficie. Follow-up abierto previo al review: signal_score bypass sin implementar (decisión pendiente, no regresión).

## Acciones sugeridas, en orden

1. Documentar (o cerrar) la decisión de M4 en `approve_order` — es la única ventana real por donde un trade puede esquivar los guardrails.
2. Resolver M1 eligiendo un único camino de esquema antes de que la próxima tabla lo agrave.
3. Nota de M2 en `catalyst_reaction.py` ahora; entry next-day open cuando arranque T-CAT-4.
4. Columna `classified_by` en news_events (M3) — barata y desbloquea QA del classifier por backend.
5. Los menores, oportunísticamente cuando se toque cada archivo.
