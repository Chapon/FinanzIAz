# Auditoría — H · operación — 2026-10-02

Tarea **261** (primera corrida del área, creada por la 260). Skill `auditoria`, categoría H. READ-ONLY.

## 1. Kill-criteria

**Congelado:** 2026-10-02, junto con los de `pantalla` y `cuentas`/`operacion` (los tres a la vez, antes de abrir el primer archivo de código), aprobado por Chapa con un «seguir».

**Contaminación declarada:** antes de congelar ya se había visto (tarea 260) que la caja y las posiciones de las cuentas 1 y 2 cuadran al centavo contra fills, comisiones y dividendos, que `reconcile_account` sólo expira pendientes, y que `ui/news_tab.py` abre la URL de la noticia con `QDesktopServices`. Nada más.

### Alcance

- **Alcance (lista):** `~/.finanzias/finanzias.log`, `.log.1`, `.log.2`, `.log.3`, `catalyst_harvest.log`; los workers de `paper_trading/scheduler.py` (`PaperScanWorker`, `SurpriseBuildWorker`, `CatalystRefreshWorker`, `CatalystHarvestWorker`, `PriceTapeArchiveWorker`, `BenchmarkLargoWorker`, `DashboardRefreshWorker`); el canal de Slack (`alerts/`, `integrations/`).
- **Afuera:** la infraestructura de la 196 (Lambda/DynamoDB), porque todavía no existe.

### Qué se busca

- **H1** un mensaje WARNING/ERROR que se repite sin tope ni escalado.
- **H2** un job sin evidencia de corrida en un día hábil de la ventana del log.
- **H3** un `except` que loguea y sigue en un camino de fondo, y entrega después un dato viejo o vacío como si fuera bueno.
- **H4** un aviso de Slack que no sale, sale duplicado, o que debería existir y no existe.

### Barrido limpio (las dos direcciones)

- **Dirección 1:** ningún WARNING/ERROR repetido sin escalado; cada hueco de job explicado por la app cerrada (ya cubierto por la 245).
- **Dirección 2:** cada falla de fondo que entrega un dato degradado tiene un aviso que llega a Chapa.

## 2. Alcance real

**Mirado:**
- `finanzias.log`, del 2026-09-07 al 2026-10-02: 17 días con log y 21 arranques. Los WARNING/ERROR se agruparon por mensaje normalizado (tickers → `TK`, números → `N`).
- Los días hábiles sin snapshot de la cuenta 2, del 2026-07-01 al 2026-10-02.
- `PaperScanWorker`, `_launch_scan`, `_on_scan_completed` y `status()` de `paper_trading/scheduler.py`.
- `_on_paper_scan_failed` (`ui/main_window.py`) y `on_scan_failed` (`ui/paper_tab.py`).
- Los llamadores de `integrations/slack.py`.
- El dashboard externo, `scripts/refresh_dashboard.py` y su artifact.

**NO mirado:**
- `finanzias.log.1` a `.log.3`. Motivo: son anteriores a la 78 y están contaminados por la suite (`'Boom'`, `BROKEN`, 133 repeticiones idénticas). Un primer barrido que los incluía se descartó por eso.
- `catalyst_harvest.log`. Motivo: su última escritura es del 2026-07-12, cuando el harvest pasó a correr dentro de la app.
- Los cinco workers que no son el scan ni el dashboard, línea por línea. Su evidencia de corrida se miró sólo a través del log.

## 3. Hallazgos

### [H-2] Una excepción que se escapa de `run_scan` no queda en el log ni llega a Slack, y el vigilante de cuentas sin scan no tiene llamadores
Severidad: **HIGH** · Confianza: **ALTA** · Categoría: H3/H4

**Ubicación:**
- `paper_trading/scheduler.py:166-176`: `PaperScanWorker.run` atrapa la excepción y sólo hace `emit`.
- `ui/main_window.py:334`: barra de estado 10 s.
- `ui/paper_tab.py:1489-1497`: toast de 4 s, sólo si la cuenta está seleccionada.
- `paper_trading/scheduler.py:1061-1081`: `status()`/`stale_accounts`, sin llamadores.

**Evidencia:**
- `run_scan` (`engine.py:792`) no tiene `try` de nivel superior.
- `session_scope` hace rollback y relanza sin loguear.
- El excepthook global no ve una excepción ya atrapada en un `QThread`.
- Ningún test cubre `scan_failed`.
- 0 ocurrencias de *«Paper scan falló»* en el log, que es justamente lo que no se puede contar si no se loguea.

**Razonamiento:** si el scan empieza a fallar siempre (una migración, un esquema, un import), la cuenta deja de operar **y de correr stops**. La única señal es un texto de 10 segundos.

**Impacto:** una cuenta muerta durante días sin aviso. Las fallas parciales **dentro** de `run_scan` sí se loguean; el hueco son las de nivel superior.

**Verificación (`verificador`):** buscó un wrapper que loguee, otro `connect` de `scan_failed`, un test y un aviso de Slack por falta de scan. No encontró ninguno.

**¿Por qué no antes?** (b) FUERA DE ALCANCE: el área no existía. `guards` declaró *«NO mirado: los guards de la UI»*.

**Acción:** tarea **263**.

### [H-1] El desvío `barrier_eval` afirma que el motor vivo evalúa las barreras intradía cada ~15 min, y entre un cuarto y un tercio de los días hábiles no las evalúa nunca
Severidad: **MEDIUM** · Confianza: **ALTA** · Categoría: H2 (y C, por el texto del desvío)

**Ubicación:** `analysis/harness_config.py:417-424`. `LIVE_EXIT_EVAL_DESC` dice *«precio corriente intradía (scan ~N min)»*, y el comentario dice *«queda entre close y touch, más cerca de touch»*.

**Evidencia:**
- **22 días hábiles sin ningún snapshot** de la cuenta 2 del 2026-07-01 al 2026-10-02 (feriados NYSE excluidos: 07-03 y 09-07). El snapshot es la vara correcta, porque `record_equity_snapshot` se llama sólo al final de un `run_scan` completado (`engine.py:1563`).
- Recalculado en hora de Nueva York, siguen siendo 22.
- Contando sólo scans **dentro de la sesión**, son **34**.

**Razonamiento:** en un día sin scan el motor no evalúa ni al cierre. Queda **por debajo** de la cota *«close»* del propio desvío, y el texto afirma lo contrario como estado actual.

**Lo que el `verificador` tumbó:** *«nadie lo declara»* era falso **para el hecho**. Los huecos están en la 196 (*«app cerrada = no se scanea»*), en la 224/225 y en *Ideas* (*«Subir la frecuencia de scan — gap de stops»*). Sobrevive sólo la parte del **desvío**: ningún texto conecta los huecos con la regla de salida ni con el cotejo vivo↔harness.

**Impacto:** cualquier comparación vivo↔harness de salidas (la 220, la 26b) asume una frecuencia de evaluación que la cuenta no tiene.

**¿Por qué no antes?** **(c-metodo)** para el área `desvios`. La regla de la 233 obliga a contrastar el texto contra el valor vivo **de cada perilla**, y las corridas lo hicieron con `paper_scan_interval_minutes`. Pero la frecuencia **efectiva** no es una perilla: es un registro (`paper_equity_snapshots`). Ver §6.

**Acción:** tarea **265**.

## 4. Barrido limpio en lo demás

- **H1:** los mensajes más repetidos ya tienen tarea cerrada:
  - el rebuild de surprise (389, la 197);
  - las barras que «no asentaron» (1.495, consolidadas en un solo aviso desde el 2026-10-01);
  - el throttle de Yahoo, que escala por niveles y avisa por Slack (`format_outage_message`).
  - El *«possibly delisted»* sobre tickers vivos (AAPL, NVDA, META…) cae en los mismos días que el breaker de throttle: es throttle, no deslistado.
  - El aviso de XGBoost *«unstable model»* sale todos los días (5 a 66 por día). El modelo **sí** está en el camino vivo (`xgb_signal_enabled=true`; su probabilidad entra al ranking). La inestabilidad ya es conocida y tiene historia en el backlog: la 25 bajó el volumen del aviso y *Calidad de datos* la registra. No es un hallazgo nuevo de esta área. *(Una primera versión de este informe decía que el modelo no estaba cableado a decisiones: era falso y se corrigió antes de publicar, verificando `analysis/technical.py:714-721`.)*
  - Los fallos de noticias del 2026-09-21 (~120 por fuente, un solo día) no se repiten.
- **H2:** los días sin scan quedan explicados por la app cerrada (lo cubren la 196 y la 245). Lo que no estaba declarado es H-1.
- **H4:** Slack avisa de órdenes, resumen de scan, caídas de Yahoo, alertas de precio y segunda opinión. Lo que falta en la dirección 2 es H-2.
- **Dashboard externo:** se refresca con la cuenta viva (log 2026-10-02 14:25, 10 posiciones).

## 5. Hallazgos rechazados

- Ninguno retirado. El conteo de H1 se rehízo una vez: el primer barrido sobre los cuatro logs mezclaba la contaminación de la suite de antes de la 78.

## 6. Limitaciones y lecciones

- **Lección para `desvios` (c-metodo de H-1):** un texto de desvío que afirma una **frecuencia** del motor vivo se contrasta contra el **registro** de lo que corrió, no contra la perilla que la configura. La perilla dice cada cuánto *intenta*; el registro dice cada cuánto *corrió*. Va a la skill, categoría C.
- La fase adversarial la hizo el agente `verificador`, independiente.

## 7. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| H-1 | 265 |
| H-2 | 263 |

