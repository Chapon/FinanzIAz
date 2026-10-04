# Tercera tanda completa de auditorías — informe consolidado — 2026-10-04

Tarea **299**. Pedido de Chapa: *«ejecutar todas las auditorías en orden»*. Skill `auditoria`, READ-ONLY. Kill-criteria de las doce áreas congelado **antes** de abrir el primer archivo: `docs/auditoria_tanda_killcriteria_2026-10-04.md`. Alcance común: lo que cambió desde la tanda del 2026-10-03 (tareas 292–297) más el estado vivo (DB copiada con la API de backup desde `mode=ro`, log de producción, `settings.json`, la app abierta desde las 18:17).

**Resultado:** 4 hallazgos publicados (0 CRITICAL, **1 HIGH**, 0 MEDIUM, 3 LOW). El HIGH pasó por el `verificador`, que lo sostuvo y le recortó tres partes del enunciado (§2). Nueve áreas cierran con barrido limpio: `muestra`, `desvios`, `estado`, `pantalla`, `cuentas`, `operacion`, `rendimiento`, `dependencias` y `logs`.

---

## 1. Hallazgos

### [D-1] El CI está rojo desde el cierre de la 288: 19 corridas y 17 tareas cerradas con el done en verde. Es la tercera vez que pasa (106, 175), después de que la 176 descartara leer el CI
Severidad: **HIGH** · Confianza: **ALTA** · Categoría: guards (el CI es un guard de proceso)

- **Ubicación:**
  - `tests/test_log_con_origen_t288.py:34,37`: los casos `argv0` y `argv3` le pasan a `origen_del_proceso` rutas de Windows literales (`D:\…\main.py`, `C:\x\scripts\….py`);
  - `.claude/commands/ship.md` y `.claude/skills/git-workflow/SKILL.md` (paso 6): el cierre termina en `git push` y nada lee el resultado del pipeline;
  - `docs/BACKLOG.md`, tarea 176: la opción (a) (*«leer la conclusión del último run en `/ship`»*) quedó **descartada** porque avisa con retraso uno.
- **Evidencia:** API pública de Actions (`actions/runs?per_page=60`, sin filtrar por rama ni por workflow, para que el filtro no esconda nada):
  - el último verde es `7ccd8c5`, 2026-10-03 00:13Z, padre de `6f8eb36`;
  - siguen **19 rojas sin ninguna verde en el medio**, de `7ba8278` a `7e51a5a` (HEAD);
  - el job `pytest` (sin `continue-on-error`) falla en las cuatro corridas leídas (la primera, dos del medio y HEAD) en los **mismos dos** casos y en nada más: `2 failed, 4240 passed`.
- **Razonamiento:**
  - En Linux, `Path("D:\\…\\main.py").name` devuelve la ruta entera, porque `\` no separa. La función está bien en las dos plataformas: en Linux `argv[0]` viene con `/`. Lo único no portable es la **entrada** del test.
  - El cuarto comando del done declara en su docstring este mismo punto ciego (*«separadores de path… lo ve únicamente el CI»*), y ningún paso mira el CI.
- **Impacto:**
  - El guard del pipeline está **inoperante desde hace 17 cierres**: 288, 280, 283, 268, 269, 289, 270, 285, 286, 259, 291, 294, 295, 293, 296, 292 y 297, todos declarando los cuatro comandos en verde.
  - Hoy el rojo no esconde **otra** regresión de Linux (las corridas muestreadas fallan sólo en esos dos casos). Pero cualquier regresión nueva quedaría tapada.
  - **Y la auditoría que tenía el CI en alcance tampoco lo vio:** la tanda del 2026-10-03 (`docs/auditoria_tanda_2026-10-03.md`, §3 `guards`) escribió *«el CI no cambió desde la tanda»* con el CI rojo hacía 13 corridas. Era cierto para `ci.yml` y falso como verificación del guard.
- **Lo que el `verificador` recortó** (y se corrigió arriba):
  1. el conteo: eran 17 cierres, faltaba la 269;
  2. *«ningún paso lee el CI»* no es un descuido sino un **riesgo aceptado por escrito** en la 176. Lo accionable es **reabrir esa decisión con este dato**: la 176 calculó que la (a) habría acotado el daño a 1 tarea en vez de 36, y acá serían 1 en vez de 17;
  3. *«tapa otras regresiones»* es potencial, no actual.
- **¿Por qué no antes?** **(c-metodo):** la tanda del 2026-10-03 tenía el CI en alcance, y la skill (*«El CI es un guard de proceso»*) sólo pregunta por la **configuración** del workflow, nunca por la **conclusión** de sus corridas.
- **Acción:**
  1. que el test sea portable (sólo el test);
  2. que Chapa reabra la decisión de la 176: verificación de retraso uno al abrir o cerrar una tarea, leyendo la conclusión del último run en `main` por la API pública;
  3. agregar a la sección CI de la skill de auditoría la pregunta por la conclusión de las corridas recientes;
  4. anotar en `docs/auditoria_tanda_2026-10-03.md` que la frase del CI no verificó el resultado.
- → tarea **300**.

### [A-1] La descripción de la skill `finanzias-conventions` dice *«el motor de 5 gates»*, y el engine tiene seis (el Gate 6, earnings blackout)
Severidad: **LOW** · Confianza: **ALTA** · Categoría: claims

- **Ubicación:** `.claude/skills/finanzias-conventions/SKILL.md:3`, en el frontmatter, que es lo que se lee al decidir si cargar la skill. El cuerpo de la misma skill dice *«5+ gates»* y lista hasta el Gate 6. `grep -oE "Gate [0-9]+[a-z]?" paper_trading/engine.py` da del Gate 1 al Gate 6.
- **Impacto:** documental. Quien lea sólo la descripción subestima la cadena de gates.
- **¿Por qué no antes?** (c-alcance): está así desde `ba6366e` (2026-06-24), y las corridas de `claims` leyeron el cuerpo, no el frontmatter.
- → tarea **301**.

### [A-2] `ARCHITECTURE.md` describe un scan donde la caja y las posiciones sólo cambian por órdenes. Desde el 09-25 el scan también acredita dividendos (222), ajusta splits (262), cuadra la cuenta (266) y registra candidatos (256)
Severidad: **LOW** · Confianza: **ALTA** · Categoría: claims (la verdad no escrita)

- **Ubicación:** `docs/ARCHITECTURE.md:5-28`, el diagrama *«Flujo de datos»*, y la lista de `paper_trading/` (`:32-35`). La última edición es `a136e0c` (2026-09-21). No nombra `dividends.py`, `splits.py`, `cuadre.py`, `scan_candidates.py` ni `scan_health.py`.
- **Impacto:** quien busque en el doc de flujo por dónde se mueve la caja ve un solo camino, y hay tres. La skill `auditoria` (área `cuentas`) sí los nombra; el doc de referencia, no.
- **¿Por qué no antes?** (a) para la 256, 262 y 266 (posteriores a la última corrida que miró el doc); (c-alcance) para la 222: la corrida del 09-30 miró `ARCHITECTURE.md` *«sólo en las secciones que tocan módulos cambiados»*.
- → tarea **301**.

### [I-1] 51 noticias clasificadas tienen un rótulo de sentimiento que contradice el signo de su puntaje, y la pestaña Noticias muestra los dos
Severidad: **LOW** · Confianza: **ALTA** · Categoría: datos

- **Evidencia** (copia de la DB): `sentiment` contra el signo de `sentiment_score` por clasificador:
  - `ollama`: **50** incoherentes de 68.544;
  - `ollama-7n`: **1** de 861 (id 72859, ON, `positive` con −1/3, *«…ON Semi Sweetens Deal With All-Cash Offer»*);
  - `heuristic`: 0 de 1.729.
- **Razonamiento:** `ui/news_tab.py:347` pinta el **rótulo y el color** desde `sentiment`, y `analysis/news_digest.py:221` (`tone_level`) calcula el **tono** desde `sentiment_score`. qwen devuelve los dos campos por separado y `data/catalyst_classifier.py:337-345` no exige que coincidan.
- **Impacto:** en el 0,07% de las filas Chapa ve, por ejemplo, «Positivo» en verde con tono −1. No hay ningún consumidor de decisión: es display-only (regla 3).
- **¿Por qué no antes?** (c-alcance): la 259 y la 290 miran la **distribución** del puntaje, no su coherencia con el rótulo.
- **Acción:** derivar el rótulo del signo del puntaje en la escala de 7 niveles (o marcar la fila), y decidir si se recalculan las 50 viejas.
- → tarea **302**.

---

## 2. Rechazados y corregidos

- **[D-1], tres partes del enunciado original.** Las tumbó el `verificador`. Se corrigieron arriba y no se degradó el hallazgo:
  - *«15 tareas»* eran 17;
  - *«ningún paso lee el CI»* es una decisión de la 176, no un descuido;
  - *«tapa otras regresiones»* es potencial, no actual.
- **Instrumentos míos que no sostuvieron un hallazgo**, que se publican para que nadie los reuse:
  - **`DB_SCHEMA.md` «le faltan 30 columnas».** Medido por substring. El doc describe las tablas generales con una línea por tabla, a propósito, y sólo enumera columnas en las `paper_*`.
  - **«`SETTINGS_REFERENCE.md` no tiene 12 perillas».** Son perillas de la UI (`bb`, `notif`…), y el doc declara que cubre `paper_*` y engine.
  - **«`ARCHITECTURE.md` no nombra 80 módulos».** El doc es de flujo, no un inventario. Lo que sobrevive es [A-2], que mira el **flujo**.
  - **«Hueco en la cinta intradía entre 09-24 y 09-27».** El log está en hora local y `price_cache` en UTC: las 21:39 del 09-27 son las 00:39Z del 09-28, donde arranca la cinta. Tampoco hay atraso de archivo: retiene **7** días (`DEFAULT_KEEP_DAYS`), no 5 como dijo la tanda de ayer.
  - **«TSM no cobró el dividendo del 09-16».** `acreditar_dividendos` acredita sólo los ex-dates posteriores al scan anterior, sin retroactivo. Es lo que Chapa eligió el 09-25.
  - **«TSM con 1 acción viola el `equal_weight`».** La orden se creó por $844 (`target_dollars`): es el recorte del overlay y de la caja, no una violación.
  - **«El lock difiere de la Anaconda en 64 paquetes».** Es la decisión escrita de la 284 (*«el lock describe el `.venv`, y está bien»*); el guard que dejó exige los rangos de `requirements.txt`. La única diferencia de runtime con algo de riesgo es `tzdata` 2023.3 contra 2026.2, y las reglas de `America/New_York` no cambian desde 2007: sin costo.

## 3. Barrido limpio, por área (alcance mirado, como lista)

- **`claims`:**
  - las frases que corrigieron la 292–297 no sobreviven en el repo (`git grep` de *«no llena con mercado cerrado»*, *«NO_MODELABLE: horario»*, `historical_reaction` atribuido al scheduler, `FINANZIAS_LOG_FILE` vacía, `slack_data_outage_enabled`);
  - `CLAUDE.md`: la cuenta 2 viva con `auto`/`equal_weight`/10, la 1 con `is_active=0`, hmm y stacking OFF, **un** test con `@pytest.mark.network` (`t211:93`; los otros dos son texto de `pytester`);
  - `DB_SCHEMA.md`: 22 de 23 tablas (falta `alembic_version`, que es de alembic), y las `paper_*` con 0016;
  - `SETTINGS_REFERENCE.md` en las dos direcciones contra las 82 `SettingSpec` y el `settings.json` vivo;
  - las skills en disco: `auditoria`, `backtest-replay-harness`, `catalyst-pipeline`, `fair-value-feature`, `finanzias-conventions`, `git-workflow`, `hallazgo-a-backlog` y `testing`, en sus claims numéricos (*«hoy son 126»* es el universo del harness: correcto).
- **`muestra`:**
  - los dos scripts nuevos (`measure_entrada_intradia_t293.py`, `measure_lookahead_fuera_sesion_t292.py`) no tienen chequeos de completitud por conteo; la mediana sale de una lista ordenada;
  - la 293 midió la señal con `analyze()` sobre los frames `2y`, con un control de 22 sobre 22, **no** sobre `data/pit_signals` (congelado en 2026-09-09 por diseño, T48);
  - ninguna operación movió la muestra desde ayer.
- **`desvios`:**
  - las claves de `deviations_keyed()` con la config viva por defecto;
  - `entrada_intradia` y `fills_fuera_de_sesion` coinciden con el valor vivo y están fechadas;
  - `paper_market_hours_only=True` gobierna los ticks de intervalo, no el fill, y está documentada;
  - *«hoy no excluye a nadie»* del screen E1b: 0 líneas `E1b` en el log desde el 09-07;
  - el texto de dividendos ya dice *«los dos cobran, uno reinvierte»* (222);
  - la comparación de los `LIVE_*` contra el `settings.json` real la hace la suite (guard de la 130), y el settings no cambia desde el 09-13.
- **`guards`:**
  - el de la 294 (redirige `HOME`, con control positivo) **y su efecto en vivo**: 0 líneas de subprocesos en el log de producción desde el cierre, con cinco corridas del done después;
  - los de la 292, 295 y 297 se mutaron al cerrarlos (3, sin registro y 6 mutaciones, todas rojas);
  - `ci.yml` no cambia desde el 09-14 → [D-1].
- **`estado`:**
  - `parquet` refrescado hoy por el scan;
  - `pit_signals` y `pit_risk` congelados por diseño;
  - `price_tape` sin hueco ni atraso (ver §2);
  - `earnings_cache` con fecha futura en las 10 posiciones;
  - `surprise_profiles.json`: el rebuild semanal toca el 10-05;
  - el árbol está limpio.
- **`pantalla`:** la equity de la cuenta 2 recalculada a mano (caja $6.849,91 + posiciones $44.333,93 = $51.183,84) es igual al snapshot y al scan de hoy, al centavo.
- **`cuentas`:**
  - cuadre independiente, sin `cuadre.py`: las cuentas 1 y 2 cierran al centavo en caja y en acciones por ticker;
  - la 2 está en 10/10;
  - el scan del domingo generó 0 órdenes;
  - 0 créditos de dividendo, correcto (§2);
  - la cartera real: 29 posiciones, todas cuadran con su transacción.
- **`operacion`:**
  - el arranque de hoy: backup diario, rotación (quedan 7), dashboard, scan de 150 s, harvest 127/127 en 351 s con `fuentes 4/4 limpias`, y classify de 512 noticias, todas `ollama-7n`, `rc=0`;
  - los días hábiles sin snapshot (09-22, 09-24, 09-25 y 09-29) son la app cerrada, que es la **245**.
- **`datos`:**
  - consenso 127/127 por día desde el 09-28;
  - la escala de 7 niveles usa 6 de los 7 valores (−1 nunca aparece: es lo que mide la **290**);
  - incoherencia rótulo↔puntaje → [I-1].
- **`rendimiento`:**
  - scan de 150 s contra 15 min;
  - 0 `database is locked` desde el 09-28 (los 6 que hay son del 09-23 al 09-28, ubicados por el timestamp anterior al traceback).
  - **Observación, no hallazgo:** el classify no tiene techo propio (sólo 60 s por llamada a qwen); hoy tardó 25 min para 512 noticias (~2,9 s cada una), y mientras corre se saltea la cosecha horaria. No se encontró costo.
- **`dependencias`:** los imports de terceros de los archivos que cambiaron desde ayer (PyQt6, alembic, numpy, pandas, sqlalchemy, yfinance y pytest) están todos declarados. Lo del lock, en §2.
- **`logs`:**
  - el censo desde 2026-10-03 05:09 (línea 26480) hasta el final: **una** firma WARNING+, XGBoost *unstable model* ×21 (conocida, por diseño), y 0 tracebacks;
  - `dashboard_data` ×2 a las 14:11 del 10-03, anteriores al commit de la 294 (14:29): explicadas por esa tarea.

## 4. NO mirado, con motivo

- **El canal de Slack:** no hay acceso desde la sesión. Lo que se ve en el log no muestra avisos fallidos.
- **La pantalla abierta** (render, tarjetas de Portfolio/Analysis/Alerts número por número): sólo se contrastó la equity de Paper contra la DB. Las tarjetas se verificaron al cerrar sus tareas (264, 268, 281–283), y ninguna cambió desde ayer.
- **El aviso de factor sin tratar de la 297 en vivo:** ninguna posición abierta atravesó un factor no plausible en los últimos 7 días, así que no hay caso que observar.
- **La muestra contra la fuente primaria de noticias (I-3 de la skill):** sólo se leyó el título de la fila de [I-1]. Un muestreo a mano contra el texto completo queda para la **290**, que ya mide la escala de 7 niveles sobre dos semanas.
- **La mutación de los guards de la 295 y la 297:** se tomó el registro de su cierre (seis rojas en la 297) en vez de re-mutar. Ninguno cambió después.

## 5. Para la skill (§ «¿Por qué no antes?»)

- **[D-1] (c-metodo):** la sección *«El CI es un guard de proceso»* pregunta por `continue-on-error`, por la paridad con el done y por las versiones, pero **no por la conclusión de las corridas recientes**. Una tanda con el CI en alcance lo dio por limpio con 13 rojas. Mejora: leer la conclusión del último run en `main` y de las N anteriores (API pública), antes que el yml. → tarea **300**.

## 6. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| [D-1] CI rojo 19 corridas / 17 cierres; test de la 288 no portable; reabrir la decisión de la 176 | **300** |
| [A-1] la descripción de `finanzias-conventions` dice «5 gates» | **301** |
| [A-2] el flujo de `ARCHITECTURE.md` sin dividendos, splits, cuadre ni candidatos | **301** |
| [I-1] rótulo de sentimiento contra el signo del puntaje en 51 noticias | **302** |
| §5, la pregunta del CI en la skill de auditoría | **300** |
| la frase *«el CI no cambió»* de la tanda del 2026-10-03, sin verificar el resultado | **300** |
