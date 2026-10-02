# Tanda completa de auditorías — kill-criteria congelado — 2026-10-02

Tareas **272**, **273**, **267** y **275**. Pedido de Chapa: *«correr todas las auditorías, quiero 100% de cobertura o cercano»*. Skill `auditoria`, READ-ONLY.

**Congelado:** 2026-10-02, a la vez para las doce corridas, antes de abrir el primer archivo de la primera (regla de la skill: *congelá los kill-criteria de TODAS las áreas juntos*). Cada informe de área remite acá y no lo reescribe.

**Contaminación declarada:** esta misma sesión corrió la 261 (pantalla, cuentas paper, operación) y la medición de cobertura de la 271: ya se vio que las 29 posiciones reales cuadran con sus 29 transacciones, que el docstring de `dd_breaker.py` afirma un gate que no existe (270), y los hallazgos de la 261. Nada de eso se re-publica como hallazgo nuevo.

**Sobre el «100%»:** no es un número que una auditoría pueda afirmar. Lo que esta tanda promete es que **ninguna área de la skill queda sin correr**, que cada informe lista qué miró y qué no, y que cada exclusión lleva motivo y, si es un diferimiento, tarea.

---

## 1. `seguridad` (272) — `/security-review` + historia de git

- **Alcance:** el árbol versionado entero; la **historia** de git (todas las revisiones) buscando secretos; `.github/workflows/`; los puntos de entrada no confiables (CSV importado, texto de noticias que llega a un prompt de LLM, respuestas de APIs externas); qué termina en el log y en artefactos versionados.
- **Afuera:** la seguridad de servicios de terceros (Slack, Yahoo, AWS) y de la máquina de Chapa.
- **Se busca:** un secreto (token, key, password, contacto personal) en el árbol o en la historia; una entrada externa que llegue a `eval`/`exec`/SQL armado con strings/un shell; un workflow que exponga secretos o corra código de PRs ajenos con permisos de escritura.
- **Limpio (1):** ningún patrón de secreto en la historia, verificado con un barrido de patrones validado contra un secreto sintético; ningún sumidero peligroso alcanzable desde una entrada externa. **Limpio (2):** todo secreto que el código usa se lee del entorno o de un archivo fuera del repo.

## 2. `cuentas` — cartera real (273)

- **Alcance:** `portfolios`, `positions`, `transactions`; la importación de CSV (`ui/import_dialog.py` y su parser); el cruce paper→real (`ui/paper/real_portfolio.py` y sus llamadores).
- **Afuera:** si las inversiones reales fueron buenas.
- **Se busca:** `quantity` o `avg_buy_price` que no salen de las transacciones; un import que duplique, pierda o redondee; un cruce paper→real que registre dos veces o contra la cartera equivocada.
- **Limpio (1):** cada posición cuadra con sus transacciones en cantidad y precio promedio. **Limpio (2):** cada camino que escribe `positions` escribe también su `transaction`.

## 3. `operacion` — backups, restore y migraciones (273)

- **Alcance:** `database/backup.py` (backup diario, rotación, `restore_database`), el botón de restore de Settings, `backups/`, `alembic/` + `init_db`/`_alembic_sync`.
- **Afuera:** ejecutar un restore de verdad sobre la DB viva (regla READ-ONLY): se razona sobre el código y se prueba sólo sobre copias en el scratchpad.
- **Se busca:** un backup que no se toma o no se puede restaurar; un restore que acepta un backup de otro esquema o con la DB abierta y deja la app rota; una rotación que no corre; una migración que a medio fallar deja un estado que `init_db` no reconoce.
- **Limpio (1):** el último backup existe, es una DB SQLite íntegra (`PRAGMA integrity_check` sobre una copia) y está en el esquema actual o `init_db` lo migra. **Limpio (2):** cada falla de backup o restore deja un aviso visible.

## 4. `datos` (273)

- **Alcance:** `news_events` (tipo, polaridad, confianza), `analyst_estimate_snapshots`, los facts de EDGAR que usa el screen, y el universo vivo (watchlist de la cuenta 2).
- **Afuera:** si el dato predice (eso es medición con pre-registro).
- **Se busca:** distribuciones degeneradas; huecos de cobertura por ticker del universo vivo que no avisan; filas que contradicen la fuente primaria en una muestra al azar; dos fuentes del mismo dato que no coinciden.
- **Limpio (1):** cada campo en alcance tiene una distribución plausible y cobertura completa del universo, o el hueco avisa. **Limpio (2):** la muestra contra la fuente primaria coincide.

## 5. `pantalla` — resto (267)

- **Alcance:** Analysis, Leads, Portfolio, Failed tickers, News, Alerts, y en Settings el cruce de cada fila contra el fallback con que la lee el motor (validando primero el extractor contra una clave conocida).
- **Afuera:** lo que ya cubrió la 261 (Home, Paper, Metrics, Reports); estética, layout, performance.
- **Se busca y limpio:** F1–F4 de la skill, en las dos direcciones, igual que en la 261.

## 6. `rendimiento` (275)

- **Alcance:** las duraciones de scan y los `database is locked` del log vivo (`finanzias.log`, desde 2026-09-07); `EXPLAIN QUERY PLAN` de las consultas de `run_scan` y de los refrescos de Home/Paper/Metrics/News sobre una **copia** de la DB; el techo de tiempo de cada worker del scheduler.
- **Afuera:** optimizaciones que no cambian conducta.
- **Se busca:** un scan que tarda más que su intervalo; un lock que frena una escritura; un `SCAN TABLE` sobre una tabla que crece en un camino de cada scan o refresco; un job sin techo.
- **Limpio (1):** ningún scan por encima de su intervalo y ningún lock en la ventana; ninguna consulta caliente sin índice. **Limpio (2):** todo job de fondo tiene techo o no puede solaparse consigo mismo.

## 7. `dependencias` (275)

- **Alcance:** `requirements.txt`, `requirements-dev.txt`, `requirements.lock`; todos los imports de terceros del código (incluidos los locales y opcionales); la Anaconda de Chapa, el `.venv` y el CI (`.github/workflows/ci.yml`).
- **Afuera:** actualizar versiones (es la tarea de *Ideas*).
- **Se busca:** un import no declarado; algo declarado que no se instala en algún entorno; una versión distinta entre entornos para un paquete que usa el camino vivo; un pin cuyo motivo caducó.
- **Limpio (1):** todo import de terceros está declarado y todo lo declarado está instalado en la Anaconda con la versión del lock. **Limpio (2):** cada diferencia entre entornos está dicha en algún lado.

## 8–12. Las cinco originales (275)

Alcance común: **lo que cambió desde las corridas del 2026-09-30b** (`git log` desde 2026-10-01: la 251–258, la 256 con su tabla y su script, el probe de la 196, y esta tanda) **más** lo que esas corridas declararon como *NO mirado*. Cada exclusión de entonces se re-verifica, no se copia.

- **`claims`:** los claims nuevos de `CLAUDE.md`, el header y las secciones operativas del backlog, las skills (la de auditoría creció hoy) y los docstrings tocados desde el 2026-10-01; más *«docs de veredicto de tareas cerradas»*, que la 09-30b dejó afuera. Busca afirmaciones falsas **y** verdades no escritas. Limpio: cada claim en alcance coincide con el código o los datos de hoy, buscado con `grep` en todo el repo.
- **`muestra`:** los chequeos por cantidad del código nuevo (la 256 cuenta scans con `paper_equity_snapshots`; la 258 mide por nivel) y los veredictos que el refresh de SPY de la 251/253 pudo mover. Limpio: ningún `len()`/conteo decide «esto está completo» sin comparar identidad o fechas, y ningún veredicto movido quedó sin re-mirar.
- **`desvios`:** la config del engine contra la del harness, con la cuenta viva; la 256 (¿registrar candidatos cambia algo del lado del harness?); y **`run_scan` entero**, que la 09-30b dejó afuera. Limpio: ningún desvío sin clave en `deviations_keyed`, y cada texto de desvío contrastado contra el valor vivo y contra el registro (la lección de la 261).
- **`guards`:** los guards nuevos (los de la 251, la 252/253, la 256) y **el CI** (`continue-on-error`, qué corre contra el *done*, versiones); más *«los guards de la UI»*, que la 09-30b dejó afuera. Limpio: cada guard en alcance se pone rojo ante el caso que describe, verificado por mutación en el sentido del falso positivo, y su falla avisa.
- **`estado`:** stores y artefactos regenerables tocados desde el 2026-10-01 (`paper_scan_candidates` y su poda, el cohorte con SPY refrescado, `surprise_profiles.json` modificado sin commitear), y el esquema `alembic` en lo que toca a tablas regenerables, que la 09-30 dejó afuera. Limpio: cada store en alcance tiene quién lo regenera, cada cuánto y qué pasa si no.
