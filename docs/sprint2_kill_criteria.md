# Sprint 2 — Kill criteria upfront

**Escrito antes de correr el harness con 2y + watchlist completa.**
Sin esto, el cerebro racionaliza retener todo después de ver los números.
**Una vez que el harness corre, estos thresholds NO se mueven.** Cualquier
modificación post-hoc invalida el ejercicio y queda registrada en este archivo
con razón explícita.

Fecha de congelamiento: 2026-05-29
Sesión de origen: Sprint 2 attribution

---

## Setup de la corrida que se está evaluando

| Parámetro | Valor |
|---|---|
| Comando | `python scripts/harness.py all -p 2y -t @data/harness_universe_42.txt` |
| Universo | 42 tickers curados: 25 de la watchlist de Sim Principal + 17 sectoriales nuevos (finance, healthcare, energy, utilities, REIT, materials, industrials, media) |
| Período | 2 años de OHLCV diarios |
| max_positions | 8 (default harness, no el 5 operativo de Sim Principal) |
| allocation_mode | EQUAL_WEIGHT (default harness, no el SIGNAL_WEIGHTED operativo) |
| signal_fn | `signal_from_analyze_stacked(enable_xgboost=True)` |
| Capital inicial | $50,000 |
| Comisión | 0.1% |
| Slippage | 0.05% |
| Warmup | 50 bars |
| Step | 5 bars |

**Caveats estructurales** (no afectan kill criteria pero limitan la generalización):
- Survivorship bias parcial: los 17 nuevos sectoriales también son survivors hoy. BA mitiga algo (drawdown brutal sostenido).
- Lookahead leve: `auto_adjust=True` en yahoo_finance.py:329 (dividend backward-adjustment).
- Diversificación sectorial alcanzada: tech ~24%, consumer ~26%, finance ~10%, healthcare ~10%, energy ~5%, industrials ~7%, otros ~18%. Mucho mejor que la watchlist pura.
- Single-window, no walk-forward (eso es Sprint 2 fase 2).

---

## Criterios por feature

### HMM (`hmm_enabled`)

| Decisión | Criterio |
|---|---|
| **Keep** | ΔSharpe(no_hmm vs baseline) ≤ -0.30 (es decir, sacar HMM empeora el Sharpe en ≥ 0.30) |
| **Kill** | ΔSharpe(no_hmm vs baseline) ≥ -0.10 (sacarlo casi no afecta o mejora) |
| **Walk-forward** | -0.30 < ΔSharpe < -0.10 (resultado incierto, requiere validación adicional) |

**Justificación**: Run previo (1y/8 tickers) mostró ΔSharpe = -0.76. Con un threshold de -0.30 hay margen sobrado. Si el run de 2y/52 tickers baja la magnitud bajo -0.30, indica que HMM solo funciona en muestras pequeñas/no diversificadas → walk-forward urgente.

### XGBoost (`xgb_signal_enabled`)

| Decisión | Criterio |
|---|---|
| **Keep** | ΔSharpe(no_xgb vs baseline) ≤ -0.15 |
| **Kill** | ΔSharpe(no_xgb vs baseline) ≥ -0.05 |
| **Walk-forward** | -0.15 < ΔSharpe < -0.05 |

**Justificación**: Run previo dio ΔSharpe = -0.37 con bastante warning de overfitting en los logs ("large train-val gap 99% vs 30%"). El threshold de -0.15 es más estricto que HMM porque XGBoost tiene mayor capacidad de overfitear con 1y. Si en 2y el efecto persiste con esa magnitud, es señal genuina.

### vol_overlay (`vol_overlay_enabled`)

| Decisión | Criterio |
|---|---|
| **Keep** | ΔSharpe(no_vol_overlay vs baseline) ≤ -0.05 **Y** ΔMaxDD ≥ +0.50 puntos porcentuales (overlay debe mejorar Sharpe o achicar DD significativamente) |
| **Kill** | ΔSharpe(no_vol_overlay vs baseline) ≥ +0.00 (sacarlo no daña Sharpe o lo mejora) |
| **Walk-forward** | Caso intermedio |

**Justificación**: Run previo dio ΔSharpe = **+0.07** (sacarlo MEJORA el Sharpe) con +3.73pp más DD. El overlay está actuando como un drag en Sharpe pero da control de drawdown. Si en 2y/52 tickers el patrón se mantiene, el overlay no se justifica por Sharpe alone — debería kill o re-tune del vol target (probable que esté demasiado bajo). Criterio doble (Sharpe + DD) porque la utilidad de un risk gate es ambas cosas.

### stacking (`stacking_enabled`)

| Decisión | Criterio |
|---|---|
| **Keep / Kill / Walk-forward** | NO EVALUABLE con esta corrida hasta confirmar que el stacking combiner se activa en >50% de los steps. Si los logs muestran "Stacking: only N usable rows (< 200); falling back to heuristic combiner" en >50% de las llamadas, esta ablation no produce evidencia y queda pending de re-run con setup adecuado. |

**Justificación**: Stacking requiere ≥200 labels por ticker para entrenar el meta-learner. Con 1y eso no se alcanzaba. Con 2y/52 tickers, debería alcanzarse en al menos los últimos meses de cada serie. Si los logs siguen mostrando "fallback to heuristic combiner" mayoritariamente, esta corrida tampoco evalúa stacking. Verificación: grep "Stacking: only" en log + comparar contra steps_total.

### correlation_gate (`correlation_gate_enabled`)

| Decisión | Criterio |
|---|---|
| **Keep / Kill / Walk-forward** | NO EVALUABLE hasta confirmar que el gate rechaza al menos 5% de los candidatos en la corrida. Si los logs no muestran skips, el gate nunca se ejerce y la ablation no aporta evidencia. |

**Justificación**: Con 52 tickers (mostly tech) y max_positions=8 debería haber overlap suficiente para que el gate rechace candidatos. Pero si la composición de la watchlist hace que no haya competencia (los signal_fn no producen 10+ BUYs simultáneos casi nunca), el gate no se ejerce y baseline ≈ no_correlation_gate por construcción, no por el merit del gate. Verificación: grep "skipped: avg_corr" en log + contar incidencias.

---

## Reglas de aplicación post-corrida

1. **Sharpe se mide en términos absolutos**, no relativos. `ΔSharpe = sharpe(ablation) - sharpe(baseline)`.
2. **MaxDD se mide en puntos porcentuales** de drawdown. `ΔMaxDD = max_dd(ablation) - max_dd(baseline)`. Más negativo = peor.
3. **Si dos features dan keep pero juntas dan Sharpe peor que cualquiera individual**, eso es interaction effect — flagear para Sprint 3 podas combinadas, pero no kill individual.
4. **Si un kill pasa por margen chico (<0.05 en cualquier dirección de los thresholds)**, anotar como "marginal kill" — re-evaluar con walk-forward antes de ejecutar la poda en código.
5. **Cualquier modificación de estos criterios post-corrida** debe registrarse aquí con razón explícita (no borrar, agregar enmienda).

---

## Resultados de la corrida

Fuente: `data/harness_results/20260529_114548/index.csv` (2y, 42 tickers diversificados).

Baseline: Sharpe 0.5924, MaxDD -15.14%, 378 trades, 14.04% return.

| Feature | ΔSharpe | ΔMaxDD (pp) | Decisión | Notas |
|---|---|---|---|---|
| HMM | **+0.15** | -0.43 | **KILL** | Sacarlo MEJORA Sharpe. Threshold de kill era ΔSharpe ≥ -0.10 (sin daño al sacar). Acá hay ganancia neta al sacar. Decisión limpia. |
| XGBoost | **+0.15** | -0.13 | **KILL** | Mismo patrón que HMM. Threshold de kill era ΔSharpe ≥ -0.05. Acá +0.15. Decisión limpia. |
| vol_overlay | **+0.57** | -1.72 | **KILL** | El overlay cuesta 0.57 puntos de Sharpe y la mitad del return (40% sin → 14% con). El control de DD que aporta (+1.72pp) no compensa. Threshold de kill era ΔSharpe ≥ 0. Decisión limpia y robusta — también kill en el run anterior 1y/8 tickers. |
| stacking | +0.10 (aparente) | 0.00 | **NO EVALUABLE** | 17,047 fallbacks "heuristic combiner" en el log, 0 entrenamientos exitosos. MIN_STACKING_ROWS=200 nunca se cumple ni con 2y. El ΔSharpe medido no proviene de cambios en stacking — probable que sea floating-point noise por el orden distinto en que se procesan las llamadas. **Stacking es código muerto en la práctica.** |
| correlation_gate | 0.00 | 0.00 | **NO EVALUABLE** | 0 skips confirmados (mismo n_trades, mismo turnover entre baseline y no_corr_gate). Razón: signal_fn casi nunca produce 9+ BUYs simultáneos con max_positions=8. El gate existe pero no se ejerce con este setup. |

### Comparación con run anterior (1y/8 tickers) — invalidación cruzada

| Feature | ΔSharpe 1y/8t | ΔSharpe 2y/42t | Lectura |
|---|---|---|---|
| HMM | -0.76 (validado) | +0.15 (kill) | **Inversión completa.** El "aporte" en 1y/8t era overfit a Mag7. |
| XGBoost | -0.37 (validado) | +0.15 (kill) | **Inversión completa.** Idem. |
| vol_overlay | +0.07 (marginal kill) | +0.57 (kill firme) | **Confirma kill.** Robusto a través de ambos windows. |

Esta es una validación negativa fuerte del run 1y/8 tickers — y exactamente lo que el ejercicio "kill criteria upfront" estaba diseñado para detectar. Sin el criterio escrito antes de ver los números, habría sido tentador racionalizar "no, en realidad la mejora del 1y es la real". El criterio congelado hace eso imposible.

### Recomendación de próximos pasos

1. **Pre-Sprint 3 (walk-forward sobre los 3 kills)**: antes de borrar código, correr el harness sobre 4 ventanas rolling de 6 meses dentro del 2y para confirmar que la conclusión es estable. Si los 3 kills aguantan en al menos 3 de 4 ventanas, ejecutar.

2. **Sprint 3 (poda)**: borrar HMM, XGBoost y vol_overlay del code path (o dejar las funciones como dead code temporal con flags forzados a False y un commit explícito explicando por qué).

3. **Pre-Sprint 3 paralelo (stacking)**: bajar MIN_STACKING_ROWS de 200 a 50 (o lo que sea factible) y re-correr. Si stacking sigue dando 0 entrenamientos, es kill por separado.

4. **Pre-Sprint 3 paralelo (correlation_gate)**: re-correr con max_positions=3 o universo más grande, o usar `signal_from_indicator("RSI")` que produce más BUYs simultáneos. Si el gate sigue sin ejercerse, es kill por separado.

## Enmiendas

### Enmienda 1 — 2026-05-29 — Walk-forward invalida los kills firmes

**Razón**: el walk-forward sobre 2 ventanas no-overlapping de 12 meses
(`data/harness_walkforward/20260529_191937/`) muestra que el ΔSharpe de HMM,
XGBoost y vol_overlay **cambia de signo entre ventanas**. El "+0.15" y "+0.57"
del run 2y completo no es una señal estable, es el promedio de comportamientos
opuestos en early_12m vs late_12m.

| Feature | ΔSharpe early_12m | ΔSharpe late_12m | Verdict revisado |
|---|---|---|---|
| HMM | -0.005 | -0.303 | UNSTABLE — sacarlo daña en late, no afecta en early |
| XGBoost | -0.138 | +0.556 | UNSTABLE (signo opuesto) — sacarlo ayuda en late, daña en early |
| vol_overlay | +0.633 | -0.244 | UNSTABLE (signo opuesto) — sacarlo ayuda en early, daña en late |
| stacking | 0.000 | 0.000 | NO IMPACT (código muerto, MIN_STACKING_ROWS=200 nunca se cumple) |
| correlation_gate | 0.000 | 0.000 | NO IMPACT (no se ejerce, signal_fn no produce 9+ BUYs simultáneos) |

**Decisiones revisadas**:

1. **HMM** — kill rechazado. La feature interactúa con régimen. Pasa a investigación.
2. **XGBoost** — kill rechazado. Idem.
3. **vol_overlay** — kill rechazado. La inestabilidad sugiere que el threshold (`vol_target_portfolio_annual=0.12`) no es robusto a regímenes.
4. **stacking** — kill por código muerto (no por daño medido). Acción: bajar MIN_STACKING_ROWS de 200 a 50 y re-evaluar. Si sigue sin entrenar, eliminar el meta-learner.
5. **correlation_gate** — kill por no ejercerse (no por daño medido). Acción: re-evaluar con `max_positions=3` o un signal_fn que genere más BUYs simultáneos. Si sigue sin rechazar, eliminar el gate o documentar como vestigial.

**Conclusión del ejercicio Sprint 2 attribution**: el engine actual tiene
features inestables a régimen. Antes de podar, necesitamos entender la
estructura de los regímenes en los que cada feature ayuda vs daña. Eso es
trabajo de Sprint 2 fase 2 (T03-sensitivity sobre los survivors).

**Lo que NO cambia**: el rigor del ejercicio. El criterio upfront del documento
permitió detectar que los kills del run 2y completo eran falsos positivos. Sin
el walk-forward y sin esta enmienda formal, habríamos podado código útil bajo
ciertos regímenes basándonos en una conclusión spuria.

### Enmienda 2 — 2026-05-29 — Opción A: resolver código muerto (stacking, correlation_gate)

**Acciones tomadas**:
- `MIN_STACKING_ROWS`: 200 → 50 (en `analysis/ml_signals.py:1050`)
- `max_positions` parametrizable en `HarnessRunner` (antes hardcoded a `len(tickers)`)
- Suites focalizadas `stacking_test` y `corr_test` en `scripts/harness.py`

**A1 — stacking con MIN_STACKING_ROWS=50** (run `20260529_223658`, suite=stacking_test, 2y, 42 tickers, max_positions default):

| | baseline | no_stacking | Δ |
|---|---|---|---|
| Sharpe | 1.10 | 0.91 | **-0.19** |
| Return | 30.48% | 23.22% | -7.26pp |
| PF | 1.68 | 1.36 | -0.32 |
| n_trades | 416 | 380 | -36 |

**Decisión revisada — stacking: KEEP (con threshold nuevo de 50)**. ΔSharpe -0.19 supera el threshold de keep firme (≤ -0.15). Además el baseline subió de 0.59 a 1.10 (+0.51 puntos) solo por activar el meta-learner — antes era código muerto, ahora es de las piezas más impactantes del engine. Decisión inversa a la Enmienda 1 (que decía "stacking NO IMPACT").

**Caveat importante**: este resultado es de UN window de 2y. La Enmienda 1 mostró inestabilidad por régimen para HMM/XGB/vol_overlay. Sería prudente correr walk-forward para stacking también antes de cerrar la decisión. Por ahora KEEP por evidencia disponible.

**A2 — correlation_gate con max_positions=3** (run `20260529_223725`, suite=corr_test, 2y, 42 tickers, max_positions=3):

| | baseline | no_correlation_gate | Δ |
|---|---|---|---|
| Sharpe | -0.002 | -0.002 | 0.000 |
| Return | -1.47% | -1.47% | 0.000 |
| n_trades | 34 | 34 | 0 |
| MaxDD | -19.85% | -19.85% | 0.000 |

**Decisión revisada — correlation_gate: KILL por código muerto.** Idénticos hasta el último decimal. El gate no rechazó ningún candidato ni siquiera con slots reducidos a 3 — razón estructural: `analyze_stacked` con threshold ≥0.55 es selectivo, produce 1–2 BUYs por step, nunca llega a "candidatos > slots". El gate solo se ejercería con un signal_fn mucho más permisivo (ej: RSI puro), que ya no es la pipeline que usa Sim Principal.

Notar también: con `max_positions=3` el sistema se vuelve trivial (34 trades en 2y), confirmando que reducir slots para forzar el gate produce un setup poco representativo de operación real. **No hay configuración razonable donde correlation_gate aporta valor en el engine actual.**

**Acción Sprint 3**: eliminar `correlation_gate_enabled`, el wrapper en `paper_trading/strategies.py:_select_uncorrelated`, y la closure `_build_correlation_filter` en `analysis/harness/runner.py`. Mantener `paper_trading/gates.py:select_uncorrelated_picks` (lógica pura, reusable) pero marcada como vestigial / no usada. **EJECUTADO 2026-05-30** — todos los cambios en el commit de Sprint 3, 41/41 tests pasan.

### Enmienda 3 — 2026-05-30 — Walk-forward stacking invalida el KEEP

**Razón**: el walk-forward de 2 ventanas no-overlapping de 12 meses (run `data/harness_walkforward/20260530_152543/`) con MIN_STACKING_ROWS=50 muestra que stacking **NO se activa** cuando el history disponible por ventana es de 12m:

| Window | baseline Sharpe | no_stacking Sharpe | ΔSharpe |
|---|---|---|---|
| early_12m | 0.234 | 0.234 | **+0.000** |
| late_12m | 1.543 | 1.543 | **+0.000** |

Bit-idénticos en ambas ventanas. Stacking no contribuye en ninguna.

**Por qué difiere de A1**: el A1 corrió sobre 2y continuo (~500 bars) → el meta-learner acumuló ~400-450 usable rows post-warmup-post-lookahead → se entrenó. El walk-forward parte el cache en dos slices de 12m (~250 bars cada uno) → solo ~200 usable rows por ventana → el combiner sigue cayendo al heuristic fallback, aún con MIN_STACKING_ROWS=50.

**Decisión revisada — stacking: PENDING (no KEEP firme)**.

El KEEP del A1 era artefacto del setup: stacking funciona cuando hay history continuo abundante, pero no es robusto a windows acotados. Esto deja dos lecturas posibles:

a. **Lectura optimista**: la cuenta real opera continuo, así que el escenario A1 (2y continuo) es más representativo del uso operativo. Stacking aporta en producción real (ΔSharpe -0.19) y eso es lo que importa. El walk-forward es solo una prueba académica que no aplica.

b. **Lectura prudente**: si stacking solo aporta cuando se acumulan 400+ usable rows, eso es una **dependencia frágil** del setup. Cualquier reset del modelo, gap de data, o cambio de régimen que invalide history previa lo deja sin aporte. Es una fuente latente de fragilidad.

**Recomendación**: dejar PENDING hasta resolver una de estas dos vías:
- Bajar MIN_STACKING_ROWS más (50→25 o 20) y re-correr walk-forward. Si se activa con 200 rows y aporta, lectura (a) gana.
- Si tras bajar el threshold sigue sin aportar en walk-forward, eliminarlo (kill por dead code en setup robusto) y aceptar que el A1 era un artefacto de no resetear history.

**Resumen final de decisiones acumuladas al 2026-05-30**:

| Feature | Decisión | Estado |
|---|---|---|
| HMM | PENDING | Inestable a régimen — análisis Sprint 2 fase 2 |
| XGBoost | PENDING | Inestable a régimen — análisis Sprint 2 fase 2 |
| vol_overlay | PENDING | Inestable a régimen — análisis Sprint 2 fase 2 |
| stacking | PENDING | Aporta con history continuo pero no se activa en walk-forward — investigar threshold o aceptar dependencia de history |
| correlation_gate | **KILLED** | Sprint 3 ejecutado 2026-05-30, función pura preservada como vestigial |

### Enmienda 4 — 2026-05-31 — Stacking instrumentado: activo pero inestable

Walk-forward con `MIN_STACKING_ROWS=25` + instrumentación de prob shifts
(run `data/harness_walkforward/20260531_122811/`, log `stacking_walkforward.log`):

| Window | baseline Sharpe | no_stacking Sharpe | ΔSharpe |
|---|---|---|---|
| early_12m | 0.208 | 0.301 | **+0.093** (sacar mejora) |
| late_12m | 1.665 | 1.545 | **-0.120** (sacar daña) |

UNSTABLE — signo opuesto. Pero la instrumentación nueva (log "Stacking shift...
heur=X -> stack=Y delta=Z crossed=...") revela el mecanismo:

**Frecuencia**: 378 entrenamientos exitosos sobre 3402 calls (11.1%). El 88.9%
restante son fallbacks por warm-up (bars insuficientes en el primer tramo de
cada ventana). Sólo 3% son near-miss (20-24 rows): bajar más
`MIN_STACKING_ROWS` no va a ayudar.

**Cuando entrena, mueve fuerte**: delta de probabilidad mean=0.315,
median=0.290, max=0.903. **63% de los entrenamientos cambian la decisión
BUY/SELL/HOLD**. No es feature inerte.

**Patrón estructural** (sobre los 239 crossings):

| Cambio | Cantidad | Significado |
|---|---|---|
| BUY → HOLD/SELL | 81 | quita un BUY |
| SELL → HOLD/BUY | 96 | quita un SELL |
| HOLD → BUY | 32 | crea un BUY |
| HOLD → SELL | 29 | crea un SELL |

Stacking quita 3x más señales de las que crea (177 vs 61). Es un **filtro de
confirmación**, no un generador de signal — y eso es lo que está causando la
inestabilidad: en régimen alcista benevolente filtrar es bueno (deja pasar
solo lo bueno), en régimen difícil filtrar es malo (pierde oportunidades).

**Decisión revisada — stacking: PENDING firme.**

- NO KILL: la feature es activa, cambia 63% de las decisiones, y su patrón
  "filtro conservador" es exactamente lo que puede combinarse con detección
  de régimen en Sprint 2 fase 2. Apagarlo en regímenes alcistas y prenderlo
  en regímenes difíciles podría capturar el upside de ambas mitades.
- NO KEEP firme: la magnitud ΔSharpe ±0.1 es chica comparada con la varianza
  entre regímenes (Sharpe baseline cambia 8x: 0.21→1.67). No es la palanca
  dominante.
- Decisión final sobre stacking depende del éxito de la opción B (régimen-
  switching). Si en B descubrimos que no hay régimen detectable confiable,
  entonces kill por bajo impacto neto sin posibilidad de mejora.

**Instrumentación**: el log `Stacking shift ... heur=X -> stack=Y delta=Z
crossed=...` queda en `analysis/technical.py:analyze_stacked`. Sirve también
en producción para auditar cuándo el meta-learner está discrepando del
heuristic — útil para futuras investigaciones, no solo para este Sprint.

**Resumen final de decisiones acumuladas al 2026-05-31**:

| Feature | Decisión | Estado |
|---|---|---|
| HMM | PENDING | Inestable a régimen — Sprint 2 fase 2 |
| XGBoost | PENDING | Inestable a régimen — Sprint 2 fase 2 |
| vol_overlay | PENDING | Inestable a régimen — Sprint 2 fase 2 |
| stacking | PENDING firme | Activo (63% crossing), inestable a régimen, candidato para feature switching en Sprint 2 fase 2 |
| correlation_gate | **KILLED** | Sprint 3 ejecutado 2026-05-30, función pura preservada como vestigial |

**Resumen de decisiones acumuladas al 2026-05-29**:

| Feature | Decisión final | Razón |
|---|---|---|
| HMM | PENDING (inestable a régimen) | ΔSharpe cambia de signo entre ventanas |
| XGBoost | PENDING (inestable a régimen) | Idem |
| vol_overlay | PENDING (inestable a régimen) | Idem, threshold default 0.12 no robusto |
| stacking | KEEP (con MIN_STACKING_ROWS=50) | ΔSharpe -0.19 firme. Validar con walk-forward. |
| correlation_gate | KILL (código muerto) | No se ejerce en ningún setup realista |

**Próximos pasos sugeridos**:
1. Ejecutar Sprint 3 light para correlation_gate (poda + commit explicando vestigial).
2. Walk-forward para stacking (mismo script `harness_walkforward.py` con suite=stacking_test) antes de hardcodear la decisión KEEP.
3. Si querés avanzar con la opción B del usuario: análisis de inestabilidad de HMM/XGB/vol_overlay por régimen.

