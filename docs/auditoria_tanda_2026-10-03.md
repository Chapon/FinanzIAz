# Segunda tanda completa de auditorías — informe consolidado — 2026-10-03

Tarea **291**. Pedido de Chapa: *«correr todas las auditorías nuevamente»*. Skill `auditoria`, READ-ONLY. Kill-criteria congelado antes de mirar: `docs/auditoria_tanda_killcriteria_2026-10-03.md`, con el diseño de re-corrida (lo que cambió desde la tanda de ayer, los arreglos medidos en vivo después del reinicio de hoy a las 04:46, y cada *NO mirado* de ayer re-verificado).

**Resultado:** las trece corridas (doce áreas y `seguridad`) se hicieron. Salieron **7 hallazgos publicados** (0 CRITICAL, 0 HIGH, 4 MEDIUM, 3 LOW) y **1 rechazado como HIGH**, que el `verificador` reformuló a MEDIUM. Cinco áreas cierran con barrido limpio: `muestra`, `rendimiento`, `dependencias`, `seguridad` y `cuentas`.

---

## 1. Hallazgos

### [C-1] `paper_enforce_market_hours` está en `False` en vivo, y nada lo declara: los defaults se contradicen y la opción de look-ahead de los scans fuera de sesión nunca se midió
Severidad: **MEDIUM** (propuesta HIGH, el `verificador` la recortó) · Confianza: **ALTA** · Categoría: desvíos / cuentas

- **Ubicación:**
  - `~/.finanzias/settings.json`: `"paper_enforce_market_hours": false`, igual que en `backups/settings_pre_soff_t2.0_20260827_195731.json` y en los `.bak_*` de septiembre;
  - `paper_trading/engine.py:1026,1114`;
  - `paper_trading/scheduler.py:520,640-649`;
  - `config/settings_manager.py:109-113`;
  - `docs/SETTINGS_REFERENCE.md:22`.
- **Evidencia:**
  - **74 de 253 fills (29%) se hicieron con el mercado cerrado:** 42 de la cuenta 2 (de 162), 19 de ellos en fin de semana (2026-06-20, 08-09, 09-20 y 09-27, scans de arranque).
  - **8 de los 74 no son imputables al flag:** son fills de la cuenta 1 en abril, anteriores a `d5fa07d` (2026-05-01).
  - **El precio del fill** es `fast_info.last_price`, o sea el cierre de la sesión regular más el slippage (`data/yahoo_finance.py:1528`); no hay precio after-hours.
- **Lo que el `verificador` refutó, y se borra del enunciado:**
  - *«costo en el P&L»*: medido con el instrumento corregido (gap `Open_siguiente / Close_previo` sobre el mismo frame, sin el sesgo de `auto_adjust`), la cuenta 2 da **+0,05% con signo, |·| 0,69%, neto −$32 en 42 fills**. Es ruido simétrico, no un costo.
  - *«el vivo se aleja del harness»*: va al revés. El harness entra al close (`analysis/portfolio_sim.py:580`), así que un fill fuera de hora al cierre oficial **es** su convención.
  - *«nada lo declara»*: tal cual está escrito es falso. Es un toggle visible en Settings (`ui/settings_tab.py:353-362`), con un tooltip que explica el efecto, y la auditoría del 2026-09-03 lo vio en vivo (`docs/auditoria_guards_2026-09-03.md:481-484`).
- **Lo que queda, y es mejor que lo que se había escrito:**
  1. **Los defaults se contradicen.** El cron diario viene prendido a las 16:05 ET, *«scan end-of-day»* (`config/settings_manager.py:109`), y `_on_daily_tick` lo dispara pasadas las 16:05 a cualquier hora de un día hábil. Con `paper_enforce_market_hours=True`, el default, ese cron **no puede llenar nunca**. El `False` vivo es lo único que hace funcionar el cron tal como está documentado, y ni `SETTINGS_REFERENCE.md` ni el `doc=` del spec dicen ese acople.
  2. **El valor vivo no está registrado.** Falta en `SETTINGS_REFERENCE.md`, que da el default `True` y *«el engine no llena con mercado cerrado»*. Falta en el registro de desvíos. Y el guard de la 185 lo clasifica *«NO_MODELABLE: horario de mercado real»*, cuando el harness modela justamente `enforce=False` más un scan al cierre. No hay ningún doc con el **porqué** del `False` (`git log -S`, el backlog, `CLAUDE.md`).
  3. **Look-ahead sin medir.** Los scans nocturnos y de fin de semana deciden con información **posterior** al cierre: noticias cosechadas después, y en los de 16:0x una barra que todavía no asentó. Igual llenan al cierre. En la cuenta 2 no se detecta ventaja (+0,05%, n=42), pero con esa muestra tampoco se puede descartar. El caso de manual es de la cuenta 1, anterior al flag: un SELL de META el 2026-04-30 a las 01:03 ET, a 668,79, contra una apertura de 618,26 (gap −7,44%).
- **¿Por qué no antes?**
  - **(d) SE VIO Y SE DESCARTÓ MAL**, el 2026-09-03: se vio el valor vivo `False` y se dio por *«inerte»*, mirando **otro** defecto (que `_is_market_open_safe` no se llama).
  - **(c-metodo)** ayer: `desvios` leyó la clasificación *NO_MODELABLE* sin contrastar el valor vivo de la perilla, y la skill pide hacerlo con **cada** perilla que gobierna una afirmación sobre el motor.
- **Acción:** es una decisión de Chapa.
  - Si el `False` es deliberado: escribirlo en `SETTINGS_REFERENCE.md` y en el spec, junto con el acople con el cron, y reclasificar la perilla en el guard de la 185.
  - Si no lo es: definir qué hace el cron de las 16:05.
  - En los dos casos: medir el look-ahead de los scans fuera de sesión con más muestra.
- → tarea **292**.

### [C-2] El vivo decide y llena DURANTE la sesión sobre la barra parcial del día; el harness decide y entra al close sobre la barra completa. No hay clave en `deviations_keyed()`
Severidad: **MEDIUM** · Confianza: **ALTA** en el mecanismo, **sin medir** la magnitud · Categoría: desvíos

- **Ubicación:**
  - harness: `scripts/run_scaleout_replay_t7.py:140-150` (la entrada es el índice de la barra con señal BUY) y `analysis/scaleout_replay.py:268` (*«entrada al close»*);
  - vivo: el scan intradía usa la barra de la sesión en curso. El repo ya lo sabe para los caches (la 24: *«durante la rueda la barra parcial de hoy cambia de valor»*), y está el warning de la 112 *«cachean la barra de la sesión de HOY, que todavía no asentó»*.
- **Evidencia:**
  - de los fills BUY de la cuenta 2, la mayoría cae entre las 14 y las 19 UTC, en plena sesión;
  - las 13 claves de `deviations_keyed()` cubren la evaluación y el fill de las **barreras** (`barrier_eval` y `barrier_fill`), no la **entrada**;
  - el *NO mirado* de ayer era justamente *«el precio de entrada harness↔vivo re-derivado»*.
- **Impacto:** cada veredicto del harness supone que la señal BUY y el precio son los del close. Una señal intradía puede no existir al cierre, y el precio intradía difiere del close. La magnitud no se sabe: **no se afirma que sea grande; se dice que nunca se midió**. Los fills fuera de sesión de [C-1] **sí** coinciden con la convención del harness, así que el desvío se limita a los fills en sesión.
- **¿Por qué no antes?** (b) FUERA DE ALCANCE: ayer quedó afuera con un motivo (*«es el eje de la T33»*) que no era una razón para no mirarlo.
- **Acción:** declarar la clave, y medir sobre los fills BUY en sesión de la cuenta 2 dos cosas: si la señal seguía siendo BUY con la barra completa, y la diferencia entre el fill y el close.
- → tarea **293**.

### [L-1] Los tests que lanzan un subproceso escriben en el log de producción: en Windows, una variable de entorno vacía no se hereda
Severidad: **MEDIUM** · Confianza: **ALTA** (reproducido) · Categoría: logs

- **Ubicación:** `tests/conftest.py:34` (`os.environ.setdefault("FINANZIAS_LOG_FILE", "")`) y `config/logging_config.py:190-193`.
- **Evidencia:**
  - Correr sólo `tests/test_cli_dashboard_cuenta_viva_t228.py` agregó 2 líneas a `~/.finanzias/finanzias.log`, marcadas `[proceso: dashboard_data]`.
  - Las 22 líneas `dashboard_data` de anoche (21:15–01:25, con la app sin escribir) coinciden con los horarios de mis corridas del done.
  - La causa, medida: con `os.environ["FINANZIAS_LOG_FILE"] = ""`, el proceso ve `''` y el hijo ve `None`, porque el runtime de C de Windows borra una variable con valor vacío. El hijo cae al default `~/.finanzias/finanzias.log`.
- **Impacto:**
  - El corte de la 78 (*«la suite no escribe en el log de producción»*) rige dentro de la suite, pero no en sus subprocesos.
  - El log es evidencia de auditoría (`operacion`, `rendimiento`, `logs`). Hoy el volumen es chico (2 líneas por corrida, porque `dashboard_data` sólo loguea `numexpr`), pero un subproceso que falle deja su traceback en el log de la app.
  - La 288 lo hace **visible** (marca el proceso), pero no lo **corta**.
  - Es el único aislamiento del `conftest` con valor vacío; los de red y DB usan valores no vacíos (`1`, rutas).
- **¿Por qué no antes?** (c-metodo): el censo de ayer vio líneas de `numexpr` *«con la app cerrada»* y las atribuyó a corridas a mano (L-1 → la 288), sin identificar qué proceso las escribía. La marca de la 288, que es de ayer, es lo que permitió verlo hoy.
- **Acción:** que la suite marque *«sin archivo»* con un valor **no vacío** (por ejemplo un centinela que `setup_logging` entienda), más un test que lance un hijo y verifique que no escribió en el log real.
- → tarea **294**.

### [H-1] El restore programado de la 278 no avisa en pantalla si se aplicó o falló: Chapa reinicia y no tiene cómo saber con qué base arrancó
Severidad: **MEDIUM** · Confianza: **ALTA** · Categoría: operación (guard que degrada en silencio)

- **Ubicación:**
  - `main.py:41-46`: `apply_pending_restore()` y su resultado se descarta;
  - `database/backup.py:372-396`: el éxito va a WARNING y la falla a ERROR, **sólo en el log**;
  - `ui/settings_tab.py:295-306`: dice *«se restaura en el próximo arranque»*.
- **Evidencia:** leyendo el código. Si el restore falla, el marcador se renombra a `.failed`, la base queda como estaba y la app abre normal. Nada en la UI lo dice, en ninguno de los dos sentidos.
- **Impacto:** Chapa pidió volver a un backup, reinició y cree que está sobre ese backup. Si falló, sigue trabajando sobre la base que quería descartar. Y el log no se lee: es la lección de la 197 y la 234.
- **¿Por qué no antes?** (a) NO EXISTÍA: lo introdujo la 278 (`55300ae`), hoy.
- **Acción:** que `main.py` muestre el resultado al abrir la ventana: un aviso de éxito con el backup aplicado, o un error con el motivo.
- → tarea **295**.

### [A-1] `slack_data_outage_enabled` también silencia el aviso de descuadre de la 266, y su doc no lo dice
Severidad: **LOW** · Confianza: **ALTA** · Categoría: claims (la verdad no escrita)

- **Ubicación:**
  - `paper_trading/cuadre.py:168` lee la perilla;
  - `docs/SETTINGS_REFERENCE.md:145` nombra a Yahoo y al scan caído, no al cuadre;
  - el `doc=` de `config/settings_manager.py:716` nombra sólo a Yahoo.
- **Impacto:** quien la apague para callar los avisos de Yahoo pierde, sin saberlo, el aviso de que la cuenta no cuadra.
- **¿Por qué no antes?** (a): la 266 es de hoy.
- → tarea **296**.

### [A-2] La skill `catalyst-pipeline` no dice ni el resumen de fallas de red de la 289 ni la escala de 7 niveles (`-7n`) de la 259
Severidad: **LOW** · Confianza: **ALTA** · Categoría: claims (la verdad no escrita)

- **Ubicación:** `.claude/skills/catalyst-pipeline/SKILL.md:23-63`. Es el lugar donde se diagnostica el harvest, y no menciona `harvest: fallas de red sin traceback …`, ni `classified_by` con sufijo `-7n`, ni que lo viejo tiene la escala agrupada.
- **¿Por qué no antes?** (a).
- → tarea **296**.

### [A-3] `.claude/commands/ship.md` (paso 3b, la 286) dice que el rebuild del scheduler reescribe `historical_reaction.json`, y ningún job lo reescribe
Severidad: **LOW** · Confianza: **ALTA** · Categoría: claims

- **Evidencia:**
  - `git grep historical_reaction paper_trading/` no da nada;
  - el archivo no cambia desde `19af52d` (2026-06-08) y sólo lo construye a mano `scripts/build_historical_reaction.py`;
  - en vivo no lo lee nadie: sólo `scripts/run_catalyst_exit_veto_backtest.py`. Por eso **no** hay hallazgo de estado.
- **¿Por qué no antes?** (a): lo escribí hoy.
- → tarea **296**.

---

## 2. Rechazados

- **[C-1] como HIGH, *«fills a precios no obtenibles, con costo en el P&L»*.** Lo refutó el `verificador`, atacando el instrumento:
  - El instrumento comparaba un `fill_price` crudo contra un `Open` del parquet con `auto_adjust=True`: en los que pagan dividendo, ese `Open` tiene descontados los dividendos posteriores, y eso sesga las compras hacia «desventaja» y agranda el |desvío|.
  - Corregido por gap sobre el mismo frame, la cuenta 2 da +0,05% con signo y −$32 netos.
  - Se publica reformulado como MEDIUM (arriba). **El sesgo del instrumento queda escrito acá** por si alguien lo reutiliza: un fill crudo no se compara contra un frame ajustado.
- **La instrumentación del censo de logs**, que es un error mío y no un hallazgo. El primer conteo dio 1.273 tracebacks desde anoche porque filtré con `awk '$0 >= "2026-10-02 21:13"'`, que deja pasar **toda** línea sin timestamp (`T` > `2`). Por número de línea fueron **0**.

## 3. Barrido limpio, por área (alcance mirado, como lista)

- **`logs`:**
  - el censo desde 2026-10-02 21:13 (línea 26422 del log) hasta 05:00 de hoy;
  - **una sola** firma WARNING+, XGBoost *unstable model* ×11 (conocida, por diseño), y **0 tracebacks**;
  - origen: `dashboard_data` ×22 (→ [L-1]) y `python -c` ×2 (pruebas mías de anoche);
  - las firmas de la 289 no volvieron a aparecer, pero tampoco hubo red caída ni cierre con fetch en vuelo desde el arreglo, así que **no** se puede decir que el arreglo se confirmó en vivo.
- **`operacion`:**
  - el arranque de las 04:46: backup `pre-migration` (la 278) → migración 0015→0016 (la 262) → backup diario → rotación (7) → poda de sueltos vencidos;
  - scan de la cuenta 2 completo;
  - harvest 127/127 en 315 s, con `fuentes 4/4 limpias`;
  - la cinta intradía rota (`price_cache` guarda 5 días);
  - ninguna falla de scan, así que el Slack de la 263 no tuvo que disparar;
  - los cinco workers que no son scan ni dashboard: archive y benchmark son silenciosos cuando no hay nada que hacer (verificado leyendo `_on_*_completed`); el surprise se reconstruye cada 7 días (último el 09-28).
- **`cuentas`:**
  - cuadre independiente, sin usar `paper_trading/cuadre.py`: las cuentas 1 y 2 cierran **al centavo**, en caja y en acciones por ticker;
  - **0 créditos de dividendo, y es correcto:** ninguna posición en cartera pasó por un ex-date después del 2026-09-25 (LRCX tuvo el 09-23 y se compró el 09-28);
  - 0 ajustes de split, también correcto: ningún split en la ventana;
  - cartera real: 29 posiciones, todas cuadran en cantidad y precio promedio con sus transacciones, sin huérfanas y sin posiciones en cero;
  - `paper_scan_candidates`: 17 scans con candidatos contra 17 snapshots, ningún scan sin registro.
- **`pantalla`:**
  - Home (264) recalculado sobre una copia: 7 posiciones de «Mis Acciones», costo $21.805,78 igual al cálculo a mano, ninguna sin precio, 2 alertas disparadas (= `is_active=0` y `triggered_at` no nulo);
  - News (259): todavía no hay filas `-7n`, porque el classify de 349 noticias está en curso. Lo mide la 290.
- **`muestra`:**
  - los chequeos nuevos comparan identidad, no conteo: el cuadre por ticker, `huecos_de_spy` por fechas, el dedup de la 280 por título normalizado y ticker, `ruedas_de_atraso` por fecha;
  - ningún veredicto se movió: SPY tiene 0 huecos, así que los tres runners de régimen no cambian.
- **`desvios`:**
  - splits alineados después de la 262 (el motor ajusta y el harness es split-neutral);
  - el texto de `barrier_eval` (265) está fechado y medido;
  - [C-1] y [C-2] salen de esta área.
- **`guards`:**
  - muté en el sentido del falso positivo la 253 (un ticker del universo declarado como sustrato): hoy SPY no está en el universo (`data/harness_universe_live_acct2.txt`, 126 tickers; el que falta contra los 127 vivos es ASML, sin PIT, y está declarado en el archivo);
  - el CI no cambió desde la tanda; **corrección del 2026-10-04 (tarea 300):** esto miró `ci.yml`, no el resultado de las corridas. En ese momento el job `pytest` llevaba **13 corridas en rojo** (dos casos de `test_log_con_origen_t288.py` con rutas de Windows), y la frase no era una verificación del guard. Ver `docs/auditoria_tanda_2026-10-04.md` [D-1];
  - los guards de la 266, 270, 283, 284, 285 y 286 se mutaron al cerrarlos (cuatro a siete mutaciones cada uno, todas rojas, registradas en el backlog).
- **`estado`:**
  - el `pre-migration` entra a la poda de sueltos a los 30 días (`_fecha_del_nombre` lo lee);
  - el marcador de restore se limpia o se renombra a `.failed`;
  - `paper_split_adjustments` es un registro contable, no un cache;
  - `earnings_cache` se llena a demanda, cuando un candidato pasa por el Gate 6, con TTL, así que nunca lee una fecha vencida;
  - esquema `alembic`: la 0016 se aplicó.
- **`datos`:** `analyst_estimate_snapshots` está completo desde el 09-28 (127 de 127 por día); los huecos anteriores son los de la 245.
- **`rendimiento`:**
  - las siete consultas nuevas del camino caliente (cuadre, dividendos, último precio de Home, transacciones de Home, registro de splits, dedup de la 280, candidatos) usan índice (`EXPLAIN QUERY PLAN` sobre una copia);
  - scan de 118,5 s contra un intervalo de 15 min, harvest de 315 s contra un techo de 1200 s;
  - 0 `database is locked`.
- **`dependencias`:**
  - todos los imports de terceros agregados por los 24 commits están declarados;
  - la Anaconda coincide con el lock en los paquetes del runtime. La única diferencia es `platformdirs` (lock 4.10.0, Anaconda 3.10.0): transitiva, anterior a hoy, dentro de la exclusión declarada, y custodiada por la contraprueba de la 236.
- **`seguridad`:**
  - 0 credenciales en el log después de la máscara de la 276;
  - en la historia desde `6360ea7`, sólo placeholders y textos del backlog (el instrumento se validó contra un token sintético);
  - el marcador de restore exige acceso local de escritura;
  - el texto de las noticias llega a qwen con la salida acotada por schema, y el resultado es display-only (regla 3).
- **`claims`:**
  - las frases que corrigieron los 24 commits (*«consuming gate»*, *«Probabilidad cuantitativa»*, *«zona de compra probable»*, *«la app no corrió»*, `?token=`, los toggles que se sacaron) no sobreviven como claim vivo;
  - quedan *«cada ~15 min»* en docs de pre-registro **históricos** y en un docstring de `scaleout_replay.py`, que habla de la intención del muestreo y no de la frecuencia efectiva. No se publica.

## 4. NO mirado, con motivo

- **Leads contra Yahoo:** pide red por cada fila; el cache de 6 h no cambió.
- **Los docs de veredicto anteriores a la 251, y los runners anteriores a la 251:** los cubrió la 09-30b y nada de hoy los toca.
- **El render de la GUI:** no cambia conducta.
- **`catalyst_harvest.log` y `.log.1..3`:** **ya no existen** (se borraron el 2026-10-02 con la 276). El motivo de ayer caducó por otra vía.
- **Las transitivas más allá de `urllib3`/`certifi`:** sin cambios de dependencias hoy (salvo lo dicho de `platformdirs`).
- **El contenido de los backups:** fuera del repo; su integridad va en `operacion`.
- **Las tarjetas de Portfolio (281), Analysis (282), Paper (268) y Alerts (283), número por número:** Portfolio pide precios en vivo a la red; se verificaron a nivel de la función y de los tests de cada tarea, **no** contra la pantalla abierta. Es un límite de esta corrida, no un diferimiento: las cuatro tareas son de ayer y hoy, y cada una cerró con su contraste.
- **El consenso PIT ajustado por split (279) contra splits reales:** los frames del cache no traen `Stock Splits` y no hay otra tabla de splits, así que hace falta red. Sin splits en el universo desde junio en lo que se pudo ver, el ajuste hoy no tiene casos.

## 5. Para la skill (§ «¿Por qué no antes?»)

- **[C-1] (d) y (c-metodo):** la regla *«contrastar el valor vivo de cada perilla»* ya está en la skill (tarea 233). Lo que faltó es aplicarla también a las perillas que el guard de la 185 clasifica como `NO_MODELABLE`: una clasificación de *no modelable* es también una afirmación sobre el motor.
- **[L-1] (c-metodo):** el censo tiene que identificar el **proceso** de cada firma que aparece con la app cerrada, no sólo atribuirlo. Desde la 288 se puede.
- **El instrumento de [C-1]:** *«un precio crudo no se compara contra un frame `auto_adjust`»*. Va a la skill junto con la lección de la 275 (*reproducí con la configuración real*).

Estas tres van como una mejora concreta de `.claude/skills/auditoria/SKILL.md` en la tarea **296**.

## 6. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| [C-1] `enforce_market_hours=False` sin declarar, defaults contradictorios, look-ahead sin medir | **292** |
| [C-2] entrada intradía sobre barra parcial vs close, sin clave | **293** |
| [L-1] subprocesos de tests escriben en el log de producción | **294** |
| [H-1] el restore programado no avisa al arrancar | **295** |
| [A-1] `slack_data_outage_enabled` silencia el cuadre sin decirlo | **296** |
| [A-2] la skill `catalyst-pipeline` sin la 289 ni la 259 | **296** |
| [A-3] `ship.md` atribuye `historical_reaction.json` al scheduler | **296** |
| §5, las tres mejoras de la skill de auditoría | **296** |
