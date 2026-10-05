# Cuarta tanda completa de auditorías — informe consolidado — 2026-10-05

Tarea **306**. Pedido de Chapa: *«correr todas las auditorías nuevamente»*. Skill `auditoria`, READ-ONLY. Kill-criteria de las doce áreas congelado **antes** de abrir el primer archivo: `docs/auditoria_tanda_killcriteria_2026-10-05.md`. Alcance común: lo que cambió desde la tanda del 2026-10-04 (299) —las tareas 300, 301, 302, 298, 304, 305 y 303, y el refresh de `surprise_profiles.json`— más el estado vivo: la DB copiada con la API de backup desde `mode=ro`, el log de producción, `settings.json` y el CI de `main`. La app estaba abierta desde las 10:13.

**Resultado:** 6 hallazgos publicados (0 CRITICAL, 0 HIGH, **4 MEDIUM**, 2 LOW). El único propuesto como HIGH ([D-1]) pasó por el `verificador`, que lo sostuvo, reprodujo el mecanismo de forma independiente y lo bajó a MEDIUM (§1). Seis áreas cierran con barrido limpio: `estado`, `cuentas`, `operacion`, `rendimiento`, `dependencias` y `logs`.

---

## 1. Hallazgos

### [D-1] `check_ci.py --ultimo` —el chequeo de apertura de la regla 7, y el que la skill de auditoría manda leer primero en `guards`— puede devolver el veredicto de un run de hace semanas: el filtro `branch=main` de la API devuelve un subconjunto viejo e intermitente
Severidad: **MEDIUM** (propuesto HIGH; el `verificador` lo bajó, ver abajo) · Confianza: **ALTA** (mecanismo, reproducido dos veces de forma independiente) · Categoría: guards

- **Ubicación:** `scripts/check_ci.py:146` (`…/workflows/ci.yml/runs?branch=main&per_page=30`) y `:91-93` (`ultimo_terminado`: el máximo por `created_at` de lo que vuelve). Ni el script ni `tests/test_check_ci_t300.py:177` comparan el sha que imprime contra `origin/main`; el test usa un fetch falso, así que no puede ver la API.
- **Evidencia (2026-10-05, API pública, sin token):**
  - `check_ci.py --ultimo` imprimió **`CI 48430cd (2026-09-08T01:26:26Z): VERDE`**; el último run de `main` es `5189a2d` (13:34Z de hoy). Al arrancar la sesión, el mismo comando había dado `0138683`, que era el correcto en ese momento;
  - el endpoint exacto, llamado a mano dos veces con un minuto de diferencia: `total_count` **135** con el run más nuevo del **09-08**, y **357** con el más nuevo del **09-14**; el `verificador`, más tarde: **395** con el más nuevo del **09-25**;
  - sin `branch=` (`workflows/ci.yml/runs`) o por el endpoint del repo (`actions/runs?branch=main`): **493**/**496** y `5189a2d` primero, siempre;
  - todos los runs que devuelve el filtro son `head_branch=main` y `event=push`: no trae runs de otra rama, trae un subconjunto **atrasado**. Minutos después, cinco `--ultimo` seguidos dieron bien. La causa (un índice por workflow+rama que se reconstruye) es inferencia; el síntoma está medido.
- **Lo que el `verificador` recortó** (y se corrigió arriba):
  1. **No es un verde inventado:** es el veredicto real de un run viejo. Sólo engaña si `main` se puso rojo **después** de ese run;
  2. **en la apertura de una tarea es una segunda red:** el `--esperar` del cierre anterior filtra por el sha completo (`run_de_commit`, `:83`) y con el índice atrasado da «sin run» (exit 2), del lado seguro. Hoy dio bien (1 run, `success`). El hueco en la apertura queda acotado a un cierre anterior *«CI sin verificar»* o a commits que no pasaron por `/ship`;
  3. **severidad MEDIUM**, no HIGH: el camino de cierre está a salvo y la cabecera imprime sha y fecha.
- **Impacto, con el que trajo el `verificador`:** donde pesa es en `.claude/skills/auditoria/SKILL.md` (*«la PRIMERA pregunta es por el RESULTADO… `python scripts/check_ci.py --ultimo`»*) y en la decisión registrada en el backlog: ahí no hay un cierre anterior que lo respalde, y una auditoría puede escribir *«CI verde»* mirando un run de hace un mes. Es la forma exacta de lo que la 300 vino a cerrar (*«la tanda del 2026-10-03 escribió "el CI no cambió" con 13 rojas»*). **Esta misma corrida casi lo hace:** el primer `--ultimo` de la tanda dijo VERDE de `48430cd`.
- **¿Por qué no antes?** **(a) NO EXISTÍA:** `check_ci.py` es de la 300 (`cdc5ab5`), posterior a la tanda anterior.
- **Acción:**
  1. pedir los runs **sin** el filtro `branch` (o por `actions/runs`) y filtrar `head_branch == "main"` del lado del cliente;
  2. en `--ultimo`, si el sha del run no es `origin/main`, decirlo (*«el último run leído es de X, `main` está en Y»*) y devolver *no se sabe* cuando la distancia no se explica por un run en curso;
  3. un test con un fetch que devuelve un subconjunto viejo (el caso que separa las dos versiones).


### [I-1] El importador de CSV tira la fecha de compra: las seis posiciones importadas de «Mis Acciones» figuran compradas el 14/04 a las 03:19, que es la hora de la importación, y los dividendos cobrados se cuentan desde ahí
Severidad: **MEDIUM** · Confianza: **ALTA** · Categoría: datos (el contenido no dice lo que se cree)

- **Ubicación:**
  - `data/csv_importer.py:5-7`: el docstring declara como formato típico de Yahoo las columnas `Trade Date`, `Purchase Price`, `Quantity`…, y los alias (`:39-55`) no tienen ninguno de fecha: la columna se ignora;
  - `ui/import_dialog.py:443-465`: la `Transaction` se crea sin `date`, así que toma el default (`now`); la `Position`, con `purchase_date=utcnow_naive()`.
- **Evidencia** (copia de la DB, cartera 1, más el cierre del cache de ese día):

  | ticker | precio de la transacción | fecha guardada | cierre de esa fecha |
  |---|---|---|---|
  | AAPL | 203,30 | 2026-04-14 03:19 | 258,37 |
  | INTC | 30,62 | 2026-04-14 03:19 | 63,81 |
  | META | 463,38 | 2026-04-14 03:19 | 661,35 |
  | TEAM | 162,12 | 2026-04-14 03:19 | 59,71 |
  | MLTX | 47,52 | 2026-04-14 03:19 | 18,78 |
  | EMBJ | 57,48 | 2026-04-14 03:19 | 69,06 |

  Ningún precio está en el rango de ese día: son compras de otra fecha. NVDA (alta manual) sí tiene `purchase_date` 2026-04-14.
- **Razonamiento:** `transactions.date` es lo que usan los lotes de la cartera real. `ui/portfolio_tab.py:108-111` calcula los **dividendos cobrados** por ticker con `dividendos_cobrados` (`database/cartera_real.py:262`), que cobra cada ex-date sobre las acciones que había **antes** de esa fecha. Con la fecha de importación, los ex-dates entre la compra real y el 14/04 dan cero acciones.
- **Impacto:** Portfolio muestra *«dividendos cobrados»* subestimados en AAPL, META, INTC y EMBJ, sin decir que son desde la importación. La curva de Home (305) arranca el 14/04 por la misma razón; eso no es falso —es valor de mercado desde esa fecha—, pero Home no puede mostrar nada anterior. No toca la cuenta paper ni ninguna decisión.
- **Verificación:** se buscó la fecha en otra columna (`positions.purchase_date`: `NULL` en las seis importadas), en las notas (*«Importado desde CSV»*) y en el backlog (`grep` de *importado*, *fecha de importación*): nada.
- **¿Por qué no antes?** **(c-metodo):** la auditoría de la cartera real del 2026-10-02 y las tandas siguientes cuadraron cantidad y precio promedio contra las transacciones; ninguna contrastó la **fecha** de una transacción contra el precio de ese día. Y la [P-2] del 2026-10-02 (dividendos desde una sola fecha) arregló el cálculo sin preguntar de dónde sale la fecha.
- **Acción:** que el importador lea `Trade Date` (y sus alias en castellano) y lo use como fecha de la transacción y `purchase_date`; para las seis ya importadas, decidir con Chapa si se corrigen con la fecha real (del CSV original, si lo tiene) o se rotulan *«desde la importación»*.

### [B-1] La curva de Home termina en el último cierre del ticker MÁS ATRASADO de toda la historia de la cartera, vendidos incluidos: la primera venta de un ticker que el scan no refresca la congela en esa fecha
Severidad: **MEDIUM** · Confianza: **ALTA** (mecanismo) / **MEDIA** (exposición) · Categoría: muestra

- **Ubicación:** `database/cartera_real.py:94`, `hasta = min(max(d for d, _ in cierres[t]) for t in con_historia)`, donde `con_historia` sale de **todos** los eventos (`:88`, y `:214-222` arma los eventos con todas las transacciones de la cartera, también las de posiciones cerradas).
- **Evidencia** (la función pura, con datos sintéticos): A en cartera con cierres hasta el 02/10; B comprada el 14/04 y **vendida entera** el 01/06, con cierres hasta el 05/06 → `valor_diario` devuelve la última rueda **2026-06-05** y `sin_historia=[]`.
- **Exposición hoy:** «Mis Acciones» no tiene ventas (7 compras, 7 posiciones abiertas), así que no muerde todavía. Cuatro de sus tickers —AAPL, EMBJ, MLTX y TEAM— **no están en el universo del scan** (`paper_watchlist` de la cuenta 2): su cache `1d` sigue fresco (02/10) mientras están en cartera, porque los refresca la pestaña Portfolio; vendido, ninguno de los dos lo refresca.
- **Razonamiento:** la regla *«la serie termina donde la tienen todos»* (305) está pensada para no congelar a un ticker **en cartera** en su último cierre. Un ticker con 0 acciones no aporta valor después de la venta, y aun así recorta la serie de todos.
- **Impacto:** la primera vez que Chapa venda uno de esos cuatro, el gráfico de Home queda fijo en la fecha de la venta. El título dice *«hasta el dd/mm»*, pero no por qué, y cada día que pasa lo deja más atrás.
- **¿Por qué no antes?** **(a) NO EXISTÍA:** lo introdujo la 305 (`1b0d683`), posterior a la tanda anterior.
- **Acción:** que el corte de la serie considere sólo los tickers con acciones a esa fecha (o a hoy), y un test con un ticker vendido cuyo cache termina antes.

### [A-1] `finanzias-conventions` —la skill que se carga al empezar cualquier tarea— define *«Una tarea NO está terminada hasta que»* sin el push ni el CI; la regla 7 de `CLAUDE.md`, `/ship` y `git-workflow` lo exigen
Severidad: **MEDIUM** · Confianza: **ALTA** · Categoría: claims (un proceso declarado en varios lugares, comparado lugar contra lugar)

- **Ubicación:** `.claude/skills/finanzias-conventions/SKILL.md:12-31`: los pasos son (1) los cuatro comandos, (2) el commit, (3) la revisión visual, y *«Nunca declarar "listo" con…»* no nombra el CI. `grep check_ci` en el archivo: vacío. Contra: `CLAUDE.md` regla 7, `.claude/commands/ship.md:65-76` y `.claude/skills/git-workflow/SKILL.md:65,74-75`.
- **Razonamiento:** la 300 corrigió la contradicción de `ship.md` con `git-workflow` y escribió la regla 7, pero no tocó la definición de «terminada» de la skill de convenciones, que es la que se carga **siempre**.
- **Impacto:** quien sigue la skill de convenciones da una tarea por terminada sin leer el CI: es la forma exacta de los tres episodios (106, 175, 300) que la regla 7 vino a cerrar.
- **¿Por qué no antes?** **(a):** la regla 7 es de la 300, posterior a la tanda anterior.
- **Acción:** sumar el push y `check_ci.py --esperar` a la lista de la skill, o remitir a la regla 7.

### [A-2] `ARCHITECTURE.md` no nombra `spinoffs.py`, el cuarto camino por el que se mueve la caja de una cuenta paper fuera de `paper_orders`
Severidad: **LOW** · Confianza: **ALTA** · Categoría: claims (la verdad no escrita)

- **Ubicación:** `docs/ARCHITECTURE.md:48`: *«Los pasos del scan que mueven plata o la verifican fuera de `paper_orders`: `dividends.py` (222), `splits.py` (262, 297), `cuadre.py` (266)»*. Desde la 303, `paper_trading/spinoffs.py` + `scripts/ajustar_spinoff.py` acreditan caja y cambian acciones (a mano, no en el scan), y el doc no los nombra.
- **Impacto:** documental; es la granularidad que la 301 le dio al doc (los módulos que mueven caja).
- **¿Por qué no antes?** **(a):** lo introdujo la 303 (`b5928b3`), hoy.
- **Acción:** una línea en la lista de `paper_trading/`.

### [C-1] El tratamiento de un spin-off difiere entre el harness y la cuenta, y ninguna clave de `deviations_keyed()` lo declara
Severidad: **LOW** · Confianza: **ALTA** · Categoría: desvíos

- **Ubicación:** `analysis/harness_config.py` (`grep -i spin` vacío). El harness corre sobre frames `auto_adjust`, donde el ex-date de un spin-off está suavizado por el factor de Yahoo (equivale a **reinvertir** la escindida en la matriz). El motor no ajusta (la 298, NO PASA): hasta que alguien corre `scripts/ajustar_spinoff.py` (303), la posición ve la caída o la ganancia fantasma —y una caída puede disparar el stop—, y después de correrlo la escindida es **caja**.
- **Razonamiento:** es la misma forma que el desvío `dividendos` (*«los dos cobran, uno reinvierte»*), que sí está declarado.
- **Impacto:** sobre los veredictos, despreciable: en los 70 tickers que operaron las dos cuentas el único evento desde marzo es HON 2026, comprado el mismo día del ex-date (298). Lo que falta es la declaración.
- **¿Por qué no antes?** **(c-alcance):** el desvío existe desde que el harness corre sobre `auto_adjust`; ninguna corrida de `desvios` miró eventos corporativos distintos del split y el dividendo, y la 303 lo hizo explícito (*«como asume el harness con `auto_adjust`»*).
- **Acción:** una clave `spinoffs` en `deviations_keyed()` con el texto (reinvierte vs. caja a mano, y sin ajuste hasta entonces) y su magnitud fechada.

---

## 2. Rechazados y corregidos

- **[D-1], la severidad y dos patas del impacto.** Las recortó el `verificador` (detalle en el hallazgo): de HIGH a MEDIUM; *«reporta verde»* es el verde real de un run viejo, no uno inventado; y en la apertura de una tarea es una segunda red detrás del `--esperar` del cierre. No se degradó para salvarlo: se corrigió el enunciado.
- **Instrumentos míos que no sostuvieron un hallazgo:**
  - **«El 403 de la API es la cuota».** Con 53 de 60 requests libres (`/rate_limit`, que no consume), no lo era: la consulta que falló llevaba un `head_sha` **abreviado**, que puse yo; `check_ci.py` manda el sha completo.
  - **«La curva de Home arranca con un 45% de ganancia el día de la compra».** No es un error de la curva: es valor de mercado, y las compras no son de ese día. Lo que sobrevive es [I-1], que mira de dónde sale la fecha.
  - **«Un scan perdido entre 10:16 y 10:44».** Coincide con la cosecha horaria (10:30–10:36). No hay evidencia de que un scan con el mercado abierto se haya salteado con un costo; queda como observación.

## 3. Barrido limpio, por área (alcance mirado, como lista)

- **`claims`:**
  - la frase corregida por la 301 (*«el motor de 5 gates»*) no sobrevive (`git grep`); la de la 302 (el rótulo desde `sentiment`) tampoco;
  - el proceso de cierre, lugar contra lugar: `CLAUDE.md` regla 7, `ship.md`, `git-workflow` coinciden entre sí → la excepción es [A-1];
  - `DB_SCHEMA.md` nombra la 0017 (303); `SETTINGS_REFERENCE.md` no tiene perillas nuevas que cubrir (300–305 no agregaron ninguna);
  - comandos en disco: `audit.md`, `backlog.md`, `ship.md`, `test.md`; skills: `auditoria`, `backtest-replay-harness`, `catalyst-pipeline`, `fair-value-feature`, `finanzias-conventions`, `git-workflow`, `hallazgo-a-backlog`, `testing`.
- **`muestra`:** `valor_diario` → [B-1]; `spinoffs.py` reconstruye las acciones por fechas, no por conteo; `check_ci.py` → ver [D-1]; `vigia_interfaz.py` no decide nada por cantidad. Ninguna operación movió la muestra de los runners desde ayer.
- **`desvios`:** sin cambios en `harness_config.py` desde la 299; el texto de `dividendos` sigue con su marco y fecha → [C-1] es lo único nuevo.
- **`guards`:** el resultado primero → [D-1]. Los jobs del último run (`5189a2d`): `lint + format`, `pytest` y `security audit` en `success`; `mypy (best-effort)` en `failure`, advisory por diseño. `ci.yml` sin cambios desde la 299 y sigue corriendo los cuatro comandos. Los guards nuevos de la 302, 303, 304 y 305 se mutaron al cerrarlos (registro en el backlog).
- **`estado`:** `parquet` al 02/10 (viernes; hoy es lunes antes del cierre); la cinta intradía archivada hoy (6.660 filas de septiembre, job de la 244); `surprise_profiles.json` reconstruido el 10-04 (127/127) y commiteado; `~/.finanzias/congelamientos.log` existe, vacío (ningún congelamiento desde que corre el vigía) y sólo crece con un congelamiento.
- **`pantalla`:** la curva de Home recalculada a mano sobre la copia: 120 ruedas, del 14/04 ($31.622,05) al 02/10 ($39.165,40), igual a `valor_diario`; el KPI de valor ($39.663,45) es de `price_cache` de hoy, y el título dice *«hasta el 02/10»*.
- **`cuentas`:** cuadre independiente, sin `cuadre.py`: las cuentas 1 y 2 cierran **al centavo** en caja (diferencia 0,0000) y en acciones por ticker; la 2 en 10/10 (la SELL de TSM y la BUY de KO de hoy dejan 10); la 1 sin órdenes desde el 07-01; la cartera real: 29 posiciones, todas cuadran en cantidad y precio con sus transacciones. La DB viva está en la 0016: la app arrancó a las 10:13, antes de la 0017, y `init_db` la aplica en el próximo arranque.
- **`operacion`:** el arranque de hoy: backup diario y rotación (quedan 7), dashboard, archivo de la cinta, scan, cosecha horaria 127/127 con `fuentes 4/4 limpias`; el del 10-04: classify 512 + 27, todos `ollama-7n`, `rc=0`, y el rebuild de surprise 127/127.
- **`datos`:** desde la 302, 27 clasificaciones y **0** rótulos contra el signo del nivel; la escala de 7 niveles usa ahora 6 de 7 valores (−1: 128 filas; −3: ninguna, es lo que mide la **290**); consenso 127/127 por día desde el 09-28, salvo el 09-29 (app cerrada, la **245**) → lo nuevo es [I-1].
- **`rendimiento`:** scans de 134 s, 54 s y 4,5 s contra 15 min; 0 `database is locked` desde la tanda anterior; la lectura de cierres de la curva de Home tarda 0,45 s en frío y 0,05 s en caliente, contra los 5 s del umbral del vigía.
- **`dependencias`:** lo nuevo usa stdlib (`urllib`, `faulthandler`, `math`), PyQt6, pandas y sqlalchemy, todo declarado.
- **`logs`:** censo desde 2026-10-04 18:17 (línea 26507) hasta las 10:59 de hoy: siete firmas WARNING+ y **0** tracebacks. XGBoost *unstable model* ×22 (conocida, por diseño); *possibly delisted* PEP/PCG/PG y el breaker de throttle abriendo y cerrando en 0 min el 10-04 20:36 (explicada: un throttle transitorio de Yahoo, que el breaker NET1 maneja); AAPL `2y` atrasado con `[proceso: python -c]` (explicada: una prueba a mano, no la app); *«1/127 tickers sin precio»* en el scan de las 13:16Z, antes de la apertura (conocida: el aviso de la 263).

## 4. NO mirado, con motivo

- **El canal de Slack:** no hay acceso desde la sesión.
- **La pantalla abierta** (render y tarjetas de Portfolio número por número): se contrastaron la curva y el KPI de valor de Home; los dividendos cobrados de Portfolio se razonaron desde el código ([I-1]), no se leyeron en la pantalla.
- **El CSV original de la importación:** no está en el repo; por eso [I-1] no puede dar las fechas reales ni cuantificar los dividendos que faltan.
- **`earnings_cache` y los archivos de universo:** no cambiaron desde la tanda anterior (sin commits ni escrituras de la app que los toquen), que los dejó en limpio.
- **El vigía de la 304 en un congelamiento real:** no hubo ninguno desde que corre; no hay caso que observar.

## 5. Para la skill (§ «¿Por qué no antes?»)

- **[I-1] (c-metodo):** el método de `cuentas` para la cartera real cuadra **cantidad y precio** contra las transacciones, y nunca la **fecha**. Una transacción a $30,62 un día que cerró a $63,81 no pudo ocurrir ese día. Mejora: contrastar el precio de cada transacción contra el rango (o el cierre) de su fecha; un precio fuera de rango delata una fecha que no es la de la operación. → tarea **308**.
- **[D-1], aunque es (a):** la propia skill manda leer el CI con un instrumento que esta tanda encontró defectuoso, y la primera lectura de la corrida salió mal. Mejora: la pregunta por el resultado del CI se contesta con el sha del run **comparado contra `origin/main`**, no con el VERDE solo. → tarea **307**.

## 6. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| [D-1] `check_ci.py --ultimo` lee un subconjunto viejo de runs por el filtro `branch` | **307** |
| [I-1] el importador de CSV tira `Trade Date`: las compras importadas figuran del 14/04 y los dividendos cobrados se cuentan desde ahí | **308** |
| [B-1] la curva de Home termina en el último cierre del ticker más atrasado, vendidos incluidos | **309** |
| [A-1] `finanzias-conventions` define «terminada» sin push ni CI | **310** |
| [A-2] `ARCHITECTURE.md` no nombra `spinoffs.py` | **310** |
| [C-1] el spin-off (reinvierte vs. caja a mano) sin clave en `deviations_keyed()` | **311** |
| §5, [I-1]: contrastar la fecha de una transacción contra el precio de ese día, en la skill | **308** |
| §5, [D-1]: el resultado del CI se lee comparando el sha contra `origin/main`, en la skill | **307** |
