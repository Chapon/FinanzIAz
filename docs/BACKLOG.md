# Backlog — FinanzIAs

Lista **operativa** de tareas (el qué sigue). El por qué estratégico vive en `docs/roadmap_v3_2026-06-09.md`. Reglas de trabajo: ver `CLAUDE.md` y la skill `finanzias-conventions`.

**Contrato para Claude Code:** al empezar una sesión, leé este archivo. Al poner una tarea en marcha, movela a *En curso*. Al cerrarla (suite Windows verde + commit), movela a *Hecho reciente* con el hash del commit. Mantené *En curso* en máximo 1 ítem.

_Última actualización: 2026-06-24._

---

## En curso (WIP, máx 1)

- _(vacío)_

## Próximo (priorizado — el de arriba es el siguiente)

1. **Activar ADV cap en producción** — setear `paper_adv_cap_pct = 0.05` en el `settings.json` de Windows y verificar en el próximo scan que el warning de trim aparece. Reco #1 auditoría 2026-06-17 (ataca riesgo tipo MLTX). Kill-criteria: no rompe la baseline; verificar trim en un BUY ilíquido.
2. **Recalibrar stops ATR** — modelar slippage del gap y/o subir `atr_stop_mult` en baja-vol. Reco #2 auditoría: los stops ATR son el peor exit (ejecutan bajo el nivel). El modelado de fill ya está (commit `e5c2ff2`); falta la recalibración del múltiplo. Kill-criteria upfront + replay (skill `backtest-replay-harness`).
3. **Feature fair value en Analysis** — mostrar precio / fair value propio / target consenso lado a lado. 6 sub-tareas, ver skill `fair-value-feature`. Display-only, NO a sizing. Empieza por el diseño del ancla de PE.
4. **Validar/desacoplar `buy_score` del sizing** — reco #3 auditoría: no predice el fwd5 en la muestra. Confirmar poder predictivo o quitarlo del sizing.
5. **Confirmar anti-churn ON** en el `settings.json` de producción — reco #4 auditoría (verificación rápida).
6. **Revisar flujo de BUYs expired** — aprobación manual / pricing del límite. Reco #5 auditoría.

## Backlog / ideas (sin priorizar)

- **Gap fill manual #1** — `fill_price_override` solo se aplica en el camino auto-fill; "Sim Principal" es cuenta manual, así que el modelado de fill realista todavía no toca las salidas reales. Decidir si se cablea al fill manual.
- **Housekeeping** — `docs/catalyst_t_cat_6_reeval_2026-06-12.md` tiene cambios sin commitear que son **puro churn de CRLF** (cero cambios de contenido). Descartar (`git checkout`) o commitear y olvidar.
- **Experimento T-CAT-6 "hold hasta cap_days"** — variante del exit-veto en el mismo harness donde entraría el MRVL +52%. La mediana de capture del rally 20d es +5.99% → hay alpha sobre la mesa. Distinto del backtest ya hecho.

## Bloqueado (esperando datos/condiciones)

- **T-CAT-5b — consenso point-in-time** — reemplazar la fuente del surprise score por `analyst_estimate_snapshots` leídos el día antes de cada earnings. Desbloqueo: ≥1 temporada capturada (~40 pares), estimado **~fines jul 2026**. Mientras tanto: mantener el scheduler diario corriendo.

## Hecho reciente

- [x] Fill realista (gap/touch) en salidas ATR + avisos de riesgo no expiran — commit `e5c2ff2`
- [x] Pestaña Métricas (efectividad del modelo) + auditoría buy/sell 2026-06-17 — commit `1af89be`
- [x] Fuente Finnhub company-news + dedup por URL en el harvester — commit `10ac2f3`
- [x] Batch yfinance + warm-up de cache en el scan (anti-401) — commits `bec78e6`/`4688795`/`aa457fb`
- [x] WAL + busy_timeout (fix "database is locked") + retry de errores transitorios yfinance — commits `b4367e4`/`3f833bb`
