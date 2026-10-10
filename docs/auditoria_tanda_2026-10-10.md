# Auditoría — tanda 2026-10-10 (12 áreas)

Tarea **349**. Kill-criteria congelados antes de abrir el primer archivo:
`docs/auditoria_tanda_killcriteria_2026-10-10.md`. Ventana: tareas **336–348** (desde la tanda 335,
`f281d7b`) más el estado vivo: DB copiada con la API de backup desde `mode=ro` (la app estaba
abierta), `~/.finanzias/finanzias.log` y `congelamientos.log` desde 2026-10-07, `settings.json`, los
runs de `main` y la reimportación del CSV del 09/10.

**Conflicto declarado:** las 336–348 las hizo esta sesión o la inmediata anterior (la 338, 345, 347
y 348, en esta misma conversación). El único HIGH pasó por el `verificador` (§3), que **corrigió el
mecanismo** que yo había escrito; F, G e I se contrastaron contra la DB calculando a mano. Dos de los
cinco hallazgos son sobre trabajo de esta sesión ([A-1] lo dejó la 346/347 sin barrer la skill;
[A-2], la 338).

## 1. Hallazgos (ordenados por severidad)

### [G-1] El motor paper no acreditó ningún dividendo desde la 222, y el desvío `dividendos` afirma que sí
Severidad: **HIGH** · Confianza: **ALTA** (ver §3) · Categoría: cuentas (con una pata en desvíos)
Ubicación: `paper_trading/engine.py:876-895` (warm-up + `acreditar_dividendos` con ventana
`(día de last_scan_at, hoy]`), `paper_trading/dividends.py:147` (`desde < ex_date <= hasta`),
`analysis/harness_config.py::dividendos_desc`.
Evidencia: `paper_dividend_credits` tiene **0 filas** en la DB viva y en los 13 backups desde el
2026-10-03; `paper_accounts.cash` sólo se mueve con fills. La función pura del motor
(`creditos_pendientes`) sobre los fills de la cuenta 2 da tres ex-dates con la posición tomada antes:
**DHR 2026-09-30** (15 × 0,40), **BMY 2026-10-02** (115 × 0,63; vendió ese mismo día, cobra) y **GE
2026-10-05** (33 × 0,47) = **$93,96**. El ledger existe desde la migración 0014 (2026-09-27 21:39
local); la app scaneó 11, 16 y 31 veces esos tres días.
Razonamiento (**corregido por el `verificador`**): Yahoo publica el ex-date en `.dividends` **con uno
o más días de atraso** —en los backups, el fetch de GE de las 22:16 UTC del 10-05 (mercado ya
cerrado) todavía no lo traía y apareció el 10-07; el de BMY de las 16:26 UTC del 10-02, en plena
rueda, tampoco—, mientras la ventana avanza con cada scan: cuando el ex-date entra al cache ya quedó a
la izquierda de `desde`. **No depende del TTL** de 24 h: el primer scan del 09-30 llegó con el TTL
vencido (la app estuvo cerrada el 09-29) y no acreditó DHR. Sólo se cobraría con la app cerrada desde
antes del ex-date hasta después de que Yahoo lo publique.
Impacto: la caja, la equity, el P&L y el sizing de la cuenta 2 (`available / len(picks)`) no tienen
esos dividendos — **$93,96 es una cota inferior**: el warm-up sólo calienta posiciones abiertas, así
que un ex-date de un ticker ya vendido puede no estar ni en el cache. El desvío `dividendos`
(`harness_config.py:346-347, 2381-2387`) y el docstring de `dividends.py` afirman que el motor cobra
en caja desde el 2026-09-25 y que el desvío vale el 0,9%: en el tramo vivo es el **100%** de lo
devengado. Todo veredicto que lea el desvío como chico sobre la ventana posterior a la 222 lo lee
mal. Lo que sí lo incluye es el **VS SPY** del panel de Métricas (`_dividendos_devengados` suma lo
devengado que no está en el ledger); la pantalla no lo esconde, la cuenta no lo tiene.
Verificación: ver §3. No hay otro camino que acredite (un solo caller, `engine.py:890`).
`test_dividendos_al_motor_t222.py::test_run_scan_ACREDITA_el_dividendo_y_lo_reporta` siembra en el
cache el ex-date **de hoy** con `last_scan_at` = ayer: el oráculo supone que el calendario conoce el
ex-date en el primer scan del día, que es justo lo que los datos desmienten.
¿Por qué no antes? **(c-metodo)**: las tandas del 03, 04, 05 y 07/10 tenían `cuentas` en alcance e
hicieron el cuadre de caja, que **cierra al centavo** con el ledger vacío. El método verifica que lo
registrado cuadre, no que **lo que debió registrarse** esté: nadie preguntó cuántos créditos tenía que
haber. Y `desvios` contrastó el texto contra el código, no contra el ledger.
Acción: que el crédito no dependa de la ventana del último scan sino del ledger (todo ex-date
posterior a la 222 con acciones al ex-date y sin fila en `paper_dividend_credits`, idempotente), que el
warm-up cubra los tickers vendidos dentro del atraso de Yahoo, un test con el ex-date llegando
**después** de que la ventana lo pasó, y el texto del desvío y del docstring con lo que pasa. La
decisión de acreditar lo ya devengado desde la 222 (no es «retroactivo» en el sentido de la decisión
de Chapa: es posterior a ella) es de Chapa. → tarea **350**.

### [L-1] El cache de parquet falla al escribir en el arranque de la app: `os.replace` → `PermissionError`
Severidad: **MEDIUM** · Confianza: **MEDIA** · Categoría: logs (firma desconocida)
Ubicación: `data/parquet_cache.py:226` (`os.replace(tmp, path)`)
Evidencia: 4 `Parquet cache write failed` con `PermissionError: [WinError 5] Acceso denegado:
'…MDLZ__2y__1d.parquet.tmp.45504.46384' -> '…MDLZ__2y__1d.parquet'` (MDLZ, MRK, MRVL el 2026-10-08
00:27:53; BKNG el 2026-10-09 18:59:10). Las dos veces, a segundos del **arranque** (migración de
alembic → archivo de la cinta → falla). La firma **no aparece antes del 08/10** en un log que arranca
el 07/09.
Razonamiento: el temporal ya es único por proceso e hilo, así que no es la colisión de nombres
conocida; en Windows `os.replace` sobre un destino **abierto por otro** da acceso denegado. Algo tiene
abierto el parquet destino en el arranque (otro hilo de la app, el subproceso del dashboard, DuckDB o
un antivirus). No se sabe cuál.
Impacto: la escritura se pierde y queda el frame anterior hasta el próximo refetch (fail-open con
log). Hoy es poco; si el que lo abre es un lector de la app, la tasa crece con lo que se lea en el
arranque.
Verificación: grep de la firma en todo el log (sólo estas 4); el código del temporal único.
¿Por qué no antes? **(a)**: no existía antes del 08/10.
Acción: tarea de medición — identificar quién tiene abierto el destino en el arranque y qué cambió el
07–08/10 (candidatos: la 336, que lee **todos** los frames de cada ticker en Home; la limpieza de la
344). → tarea **351**.

### [A-1] La skill `auditoria` afirma que al `.venv` le faltan `platformdirs` y un parser de HTML
Severidad: **LOW** · Confianza: **ALTA** · Categoría: claims caducados
Ubicación: `.claude/skills/auditoria/SKILL.md:493`
Evidencia: *«al `.venv` le faltan `platformdirs` y un parser de HTML, y da otro conteo de tests»*. La
328/346 midieron que el `.venv` tiene `platformdirs` **4.10.0**; la 347 le instaló `lxml` 5.2.1.
Impacto: la skill se lee en cada corrida de `dependencias` y manda a buscar un faltante que no existe;
la divergencia real es la **versión** de `platformdirs`.
¿Por qué no antes? **(a)**: lo volvió falso la 346 (el paquete) y la 347 (el parser).
Acción: la frase con lo que diverge hoy. → tarea **352**.

### [A-2] `CLAUDE.md` enumera lo que el guard del backlog chequea en la suite y no nombra el eje 6 (máx 1 en *En curso*)
Severidad: **LOW** · Confianza: **ALTA** · Categoría: claims (lo verdadero no escrito)
Ubicación: `CLAUDE.md:37` (§Backlog)
Evidencia: la enumeración de *«la mitad que se ve leyendo el archivo»* lista secciones, vacías,
punteros y la cola de la 195; la 338 agregó `en_curso_items` / `MAX_EN_CURSO` en
`scripts/check_backlog_integrity.py`.
Impacto: chico: el mismo `CLAUDE.md` dice *«En curso máximo 1»* dos líneas arriba; pero la lista se
presenta como el inventario del guard.
¿Por qué no antes? **(a)**: lo introdujo la 338 (esta sesión), que barrió las skills y `/ship` y no
este párrafo.
Acción: agregar el eje a la enumeración. → tarea **352**.

### [H-1] Un harvest que corre con la red caída cuenta como el del día, y el refresh diario no lo reintenta
Severidad: **LOW** · Confianza: **MEDIA** · Categoría: operación
Ubicación: `analysis/news_digest.py:426` (`refresh_due`: `not harvested_today() or unclassified > 0`)
Evidencia: el 2026-10-09 la app volvió de una suspensión de 9.127 s a las 23:25 local y lanzó el
refresh con la red todavía caída: `Harvest: … sin datos 32 | fuentes 0/4 limpias | FUENTES CAIDAS:
yfinance_news 33/127, sec 32/127, fin…`, y 95 de 127 tickers en `analyst_estimate_snapshots` del
`snapshot_date` 2026-10-10 (UTC). Con esa corrida registrada, `refresh_due` da falso el resto del día.
Razonamiento: el diseño supone que la corrida del día es representativa; una corrida con fuentes
caídas no lo es, y el horario sólo corre en RTH.
Impacto: probablemente chico y quizás autocorregido: el harvest del 10/10 escribe el mismo
`snapshot_date` UTC y las noticias se recuperan por la ventana del collector. **No se midió** cuánto
se pierde de verdad; por eso la confianza es MEDIA.
¿Por qué no antes? **(a)**: es el primer harvest lanzado al volver de una suspensión con la red caída
que aparece en la ventana.
Acción: que el refresh diario no cuente como hecho un harvest con `FUENTES CAIDAS` (o que lo reintente
una vez con red), y medir qué se perdió el 09/10. → tarea **353**.

## 2. Barridos limpios (con lo que se miró)

- **B. muestra:** `en_curso_items` (338) compara contra un máximo, no decide completitud;
  `cartera_real.valor_diario` (336) corta en `min(último cierre)` de los tickers en cartera, por fecha;
  `ml_signals` (340) es sólo log. Lo que movió la muestra —el CSV del 09/10, los frames `5y` de la
  343, las opiniones de la 337— se re-verificó en F, G e I.
- **C. desvíos:** fuera de [G-1], no se encontró otra diferencia sin clave: la 344 actúa en
  `clean_ohlcv`, que es común a los dos lados; la 333 sólo cambia la escala de un crédito que hoy no
  ocurre ([G-1]).
- **D. guards:** CI de `main` **verde** en `ec337bd` (= `origin/main`); el único rojo desde la 335,
  `73aa490`, tiene causa nombrada (la 348). El guard de la 344 sólo descarta filas posteriores al
  último Close válido: no puede tirar una barra buena. El eje 6 de la 338 se mutó en su tarea (dos
  rojos). El CI instala por rangos **por decisión de la 284** (*«prueba lo más nuevo que el proyecto
  admite»*); la 348 es esa decisión funcionando, no un hallazgo.
- **E. estado:** `limpiar_barra_rellenada.py` en seco: **0** barras rellenadas. La última barra de los
  10 tickers de la cartera real, los 9 de la cuenta 2 y SPY es la del 09/10 (los `10y` atrasados son
  del cohorte, con su refresh propio). Backups diarios tomados y rotados (`kept 7`).
- **F. pantalla:** Home contra cálculo a mano: costo FIFO **48.811,65** (a mano, ticker por ticker);
  último punto de la curva de valor = KPI (72.829,40); última ganancia no realizada = KPI (24.017,75);
  realizada **3.281,93** = FIFO neto de comisiones de compra y venta (a mano: 3.448,39 − 166,46); la
  vista «invertido» (334) usa el costo FIFO, no `invertido_neto`; la serie arranca en la primera compra
  (2024-02-21) y no hay tickers sin cierre. Opiniones de Claude: sin filas nuevas; las cuatro sucias
  siguen, declaradas en la 321 por la 337.
- **G. cuentas:** cuentas 1 y 2 cuadran **al centavo** en caja y acciones; la cuenta 1 no tiene órdenes
  desde el 13/09; la cuenta 2 llegó a 10 posiciones (su máximo) el 07/10 y nunca más. Cartera real: las
  10 posiciones abiertas coinciden con el FIFO de sus 20 transacciones; las dos compras del 07/10 (META
  726,13; PYPL 55,20) caen dentro del rango del día.
- **I. datos:** los frames `5y` de TEAM y EMBJ (343) coinciden **exacto** con los `1y` en las 250 fechas
  que comparten.
- **J. rendimiento:** scan más largo desde el 07/10: **409 s** contra un intervalo de 15 min; ningún
  `database is locked` desde el 28/09; `resumen_home` sobre la copia: **0,61 s**.
- **K. dependencias:** `test_entorno_cumple_requirements_t284` verde con Anaconda y con el `.venv`;
  ninguna dependencia directa sin techo choca hoy con `numpy<2` (PyPI: yfinance 1.7.0, duckdb 1.5.6,
  hmmlearn 0.3.3, arch 8.0.0, xgboost 3.4.1 —pide Python ≥3.12, el CI en 3.11 resuelve una anterior—,
  lxml 6.1.3, alembic 1.20.0).
- **L. logs** (fuera de [L-1]): XGBoost inestable → **340** abierta (96 el 07–08/10, 32 el 09/10, con
  ticker desde la parte 1); el ráfaga de red de las 23:25 del 09/10 (`possibly delisted` de EQIX/EMBJ,
  DNS de Yahoo/SEC/Finnhub) → **explicada**: el equipo volvió de una suspensión de 9.127 s (vigía) con
  la red caída, y su efecto es [H-1]; vigía 4,4 s ×3 → por debajo del umbral de la **304**; barra de la
  sesión de hoy → **243**; `Invalid Crumb` ×1 y timeouts de SEC (`fetch_company_facts` de C) →
  transitorios de red, sin repetición.

## 3. Fase adversarial

[G-1] pasó por el `verificador` con el mandato de refutar, atacando primero el instrumento. **Veredicto:
CONFIRMADO, con el mecanismo corregido.**

- **El instrumento resistió:** 0 créditos también en los 13 backups desde el 10-03; la cuenta 2 no tiene
  splits ni spin-offs aplicados, así que `splits=None` no cambiaba nada; las tres posiciones estaban
  tomadas antes de su ex-date (BMY vende el mismo día del ex-date, que cobra); el `desde` fijo no
  afecta, porque los tres ex-dates son posteriores a la 0014.
- **El mecanismo que yo había escrito cayó:** había propuesto que el TTL de 24 h tapaba un ex-date que
  Yahoo publica desde el mismo día. Midiendo en los backups cuándo aparece cada ex-date, Yahoo lo
  publica **días después** (GE: dos días), y DHR —con el TTL vencido en el primer scan de su ex-date—
  es el contraejemplo. La causa es la ventana contra el atraso de la fuente, con TTL o sin él.
- **Trajo dos patas nuevas:** el warm-up no recalienta los tickers vendidos (el monto es cota
  inferior) y el test del cableado de la 222 siembra el ex-date de antemano, por eso no lo ve.
- **Precisó la pantalla:** el VS SPY del panel sí incluye los devengados; la caja, la equity y el
  sizing no.

Ningún hallazgo fue retirado. Los MEDIUM y LOW no pasan por el `verificador` (regla de la skill).

## 4. Limitaciones

- La DB se copió con la app abierta (API de backup, consistente).
- [L-1] no identifica quién tiene abierto el destino; es una tarea de medición.
- [H-1] no midió lo perdido: el `snapshot_date` es UTC y el harvest siguiente puede completarlo.
- K no instaló un entorno limpio con Python 3.11: lo que resuelve el CI se dedujo de PyPI y de que el
  CI de `ec337bd` está verde.

## 5. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| [G-1] | 350 |
| [L-1] | 351 |
| [A-1] | 352 |
| [A-2] | 352 |
| [H-1] | 353 |

## 6. Deuda de la skill (los (c-metodo) y (d))

- **[G-1] (c-metodo):** `cuentas` cuadra lo que está registrado contra la caja, y un ledger **vacío**
  cuadra perfecto. Le faltaba: **por cada flujo que el motor declara cobrar o pagar (dividendos,
  splits, spin-offs), contar cuántos eventos debió registrar en la ventana —con la propia función del
  motor sobre los fills— y compararlo con los que registró.** Y en `desvios`: un texto que afirma que
  el motor hace algo se contrasta también contra el **registro** de que lo hizo (la forma de la 261,
  que la skill ya tiene para frecuencias y no para flujos de plata).
