# Auditoría de datos — 2026-05-26

**Contexto**: cierre de Sprint 0 ([[roadmap_sprint_validation]]). Tres chequeos sobre `historical_data_cache` y `paper_watchlist` para identificar sesgos silenciosos antes de construir el harness de Sprint 1.

**Alcance**: cuenta Sim Principal (`account_id=1`), 52 tickers, ventana 2024-05-23 → 2026-05-22 (501 trading days, `period=2y`, `interval=1d`).

---

## Resumen ejecutivo

| Chequeo | Severidad | Bite ahora | Bite en Sprint 1 |
|---|---|---|---|
| 1. Lookahead por `auto_adjust=True` | MEDIA | Bajo (paper live forward) | **ALTO** en backtest |
| 2. Survivorship en watchlist | ALTA-para-backtest | Bajo (paper live forward) | **ALTO** en backtest |
| 3. Gaps / NaN / outliers / calendario | NULA | — | — |

Conclusión: **la data está limpia mecánicamente, pero contiene dos sesgos estructurales que inflarán el Sharpe del backtest si no se manejan explícitamente al construir el harness**. Como estamos en paper-trading forward-only, ninguno de los dos está afectando decisiones hoy.

---

## 1. Lookahead por `auto_adjust=True`

**Hallazgo**: `data/yahoo_finance.py:329` llama `yf.download(..., auto_adjust=True)`. Esto retorna precios **adjusted retroactively** por **splits Y dividendos** usando todas las corporate actions hasta la fecha de fetch.

**Verificación concreta** (cached values vs. raw printed prices):

| Ticker | Fecha | Cached Close | Real unadjusted | Causa |
|---|---|---|---|---|
| AVGO | 2024-05-23 | $136.54 | ~$1365 | 10:1 split del 2024-07-15 |
| NVDA | 2024-06-05 | $122.37 | ~$1224 | 10:1 split del 2024-06-10 |
| KO | 2024-05-23 | $58.59 | ~$63.00 | 8 dividendos trimestrales descontados hacia atrás |

El **split adjustment** es necesario y correcto (sin él los indicadores explotan en la fecha del split). El **dividend backward-adjustment** es el problema: para cualquier fecha histórica `t`, el `Close` cacheado conoce todos los dividendos pagados entre `t` y `today`. En un backtest que "vive" en `t`, esa información es lookahead.

**Magnitud del sesgo**:
- En tickers con yield bajo (NVDA, AMZN, TSLA, META) el efecto es trivial.
- En staples y utilities (KO, PG, PM, MO, KMB, MDLZ) el efecto se acumula a ~5-10% en 2 años — significativo para metric absolutas (CAGR, max DD en dólares).
- Para señales relativas (RSI, MACD, Bollinger, momentum percentile) el efecto es **mínimo** porque el discount se aplica casi uniformemente sobre la ventana.

**Bite real**:
- **Ahora (paper live)**: nulo. El motor opera forward, ve precios live actuales, no retroactivos. La cache se usa solo para indicators que se calculan sobre la ventana completa con la última corrección.
- **Sprint 1 (harness con walk-forward)**: alto si no se neutraliza. Un backtest sobre KO 2024-2026 usando precios cacheados va a "comprar" implícitamente a $58.59 cuando el precio real-time del 2024-05-23 era $63. La diferencia es retorno fantasma capturado por el rebalanceo.

**Remediación recomendada** (no implementar en este Sprint — son tareas del harness de Sprint 1):
1. En el harness, fetch separado con `auto_adjust=False` + `actions=True` para construir total-return correctamente con dividendos pagados en sus fechas reales.
2. Alternativa más simple: aceptar el sesgo y documentarlo. Para señales técnicas el sesgo es ~indistinguible de ruido y construir un pipeline de unadjusted prices duplica complejidad. Lo crítico es **no reportar Sharpe sin esta nota** al cerrar Sprint 2.
3. Documento de decisión: pendiente al inicio del Sprint 1.

---

## 2. Survivorship bias en la watchlist

**Hallazgo**: los 52 tickers de Sim Principal vienen de presets en `paper_trading/presets.py` ("Magníficos 7", "Tecnología", "Semiconductores", "Consumo defensivo", "Consumo discrecional"). Todos los presets son listas curadas de mega-caps representativas de cada sector — selección implícitamente sesgada por **performance histórica** y **supervivencia**.

**Evidencia de sesgo**:
- 52/52 tickers **siguen listados y vivos hoy** (2026-05-26). Cero attrition.
- La ventana es 2024-05-23 → 2026-05-22. En esos 2 años hubo de-listings y bancarrotas materiales en US large-cap (ej. WBA fuera del Dow, ALLY downgrade, varios biotechs, etc.) — **ninguno está en la watchlist**.
- Caso límite confirmado: **MLTX cayó −89.9% en un solo día (2025-09-29)** — probablemente Phase 2 fail / FDA setback. Sigue en la watchlist. Es la excepción que prueba la regla: la curación humana toleró sobrevivientes catastróficos pero no incluyó nombres que dejaron de existir.
- Los presets se editan post-hoc en código: cada vez que se actualiza `presets.py`, los tickers de hoy reflejan "qué sectores tienen sentido HOY", no "qué tickers eran plausibles en 2024".

**Bite real**:
- **Ahora (paper live)**: nulo en el sentido estricto. La cuenta operó forward desde 2026-04-24 (33 días). En ese período no hubo de-listings del universo, así que la decisión de qué ticker mirar fue contemporánea.
- **Sprint 1 (backtest)**: alto. Un walk-forward 2024-2026 sobre estos 52 tickers tiene Sharpe inflado por construcción — cero pérdidas catastróficas excepto MLTX (que estaba en la watchlist desde 2026-04-24, no desde 2024). Una corrección honesta exige construir el universo **point-in-time**: en `t`, mirar solo los tickers que un humano razonable habría incluido en `t`, sin saber lo que vendría.

**Remediación recomendada** (Sprint 1):
1. **No corregir el universo retroactivamente** — es costoso (necesita histórico de constituyentes S&P 500 / sectoriales por fecha).
2. En su lugar: al reportar resultados del harness, incluir un **survivorship disclaimer** estándar al pie de cada métrica. Forma sugerida: "Sharpe X.XX (universo fijo de 52 sobrevivientes; estimación pesimista −0.3 a −0.6 puntos por survivorship bias)".
3. Si en Sprint 4 (cross-sectional ranking) el Sharpe medido es 2+, asumir que ~1.5 es la realidad — y aún así es muy alto, ojo con conclusiones.
4. Opcional / barato: agregar a la watchlist algunos tickers conocidos como "vivos pero distressed en 2024-2026" (CVS, WBA, INTC ya está, BA, MMM) para diluir el sesgo. INTC ya está; WBA, CVS, BA valen la pena considerar.

---

## 3. Gaps, NaN, outliers, integridad temporal

**Hallazgo**: data mecánicamente limpia. Ninguna acción requerida.

**Resultados por ticker** (52/52):
- Filas: exactamente **501** en todos.
- Rango: **2024-05-23 → 2026-05-22** uniforme.
- NaN totales: **0** (Open, High, Low, Close, Volume).
- Precios ≤ 0: **0**.
- Volúmenes < 0: **0**.
- Volúmenes = 0: **0** en 8 tickers muestreados (AAPL, TSLA, META, NVDA, MSFT, MLTX, ON, MRVL).
- "Gaps" (business days esperados sin fila): **21 por ticker, idénticos en todos los tickers** → corresponden 1:1 con holidays de NYSE (Memorial Day, Juneteenth, July 4, Labor Day, Thanksgiving, Christmas, New Year, MLK, Presidents Day, Good Friday + 2025-01-09 = National Day of Mourning).
- Outliers verificados (`|daily return| > 30%`): NVDA 0, TSLA 0, **MLTX 1** (−89.9% el 2025-09-29, evento real no error de data).

**Bite real**: ninguno. La data está bien para ambos usos (forward live y backtest).

---

## Acciones de salida (qué hacer con esto)

1. **No bloquea el cierre de Sprint 0** — los hallazgos son sesgos estructurales que se manejan en el Sprint 1 con disclaimers explícitos y decisiones de scope, no parches al cache.
2. **Decisión pendiente para Sprint 1**: ¿hacemos pipeline `auto_adjust=False + actions` para el harness, o aceptamos sesgo de dividendo + survivorship con disclaimer? Recomendación: aceptar + disclaimer (el costo de pipeline correcto no se justifica antes de saber si el sistema tiene alpha medible).
3. **Kill criteria de Sprint 2 deben asumir survivorship inflado**: si una feature en attribution muestra Δ-Sharpe < 0.3 OOS, considerar el verdadero Δ entre 0.0 y 0.2 (la fracción del Sharpe total atribuible a survivorship contamina proporcionalmente).
4. **MLTX como red flag conceptual**: el sistema vio una caída de −89.9% en un ticker que estaba en watchlist. Cuando se haga attribution en Sprint 2, vale la pena verificar si los 5 gates pararon la entrada / forzaron la salida ese día, o si la posición existió en ese momento. Si la salida funcionó, es validación de los gates; si no, es una alerta para T01 (ATR stops).
5. **Watchlist debt**: registrar como pendiente para Sprint 1 la opción de agregar 3-5 "distressed survivors" (WBA, CVS, BA, MMM) para tener algo de drawdown realista en backtest.

---

## Cierre Sprint 0

- ✅ T11-flip ($50 → $250 min trade)
- ✅ T08-flip (earnings blackout permite SELLs señaladas)
- ✅ Baseline Sim Principal (`baseline_metrics.py` + tests; [[baseline_sim_principal_2026-05-26]])
- ✅ **Auditoría de datos** (este documento)

**Sprint 0 cerrado**. Siguiente: Sprint 1 (T-harness mínimo + walk-forward + dashboard vivo).
