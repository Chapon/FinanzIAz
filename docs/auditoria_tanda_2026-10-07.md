# Auditoría — tanda 2026-10-07 (12 áreas)

Tarea **335**. Kill-criteria congelados antes de abrir el primer archivo:
`docs/auditoria_tanda_killcriteria_2026-10-07.md`. Ventana: tareas **307–334** (desde la tanda
306, `557ae6a`) más el estado vivo: DB copiada con la API de backup desde `mode=ro` (la app estaba
abierta), `~/.finanzias/finanzias.log` desde 2026-10-05, `settings.json`, y los runs de `main`.

**Conflicto declarado:** las tareas 324–334 las hizo la misma sesión que corre la tanda. Los dos
HIGH pasaron por el `verificador` (§3), y las áreas que tocan esas tareas se contrastaron contra
la DB calculando a mano, no releyendo el código propio. Aun así, tres de los nueve hallazgos son
sobre código mío de hoy ([F-1], [A-2], [D-1]).

## 1. Hallazgos (ordenados por severidad)

### [F-1] Home subvalúa el valor y la ganancia de «Mis Acciones» durante todo el primer año
Severidad: HIGH · Confianza: ALTA (ver §3) · Categoría: pantalla (con raíz en estado)
Ubicación: `database/cartera_real.py::cierres_del_cache` y `::valor_diario`
Evidencia: sobre una copia de la DB, `resumen_home()`: el valor salta **+$1.464** el 2025-10-07 y
**+$3.343** el 2025-10-08 con el costo abierto **constante en $18.193**. `parquet_cache.all_1d`:
TEAM tiene un frame 2025-10-08→2026-10-07 (el elegido) y otro 2024-07-01→2026-07-01; AAPL tiene
2025-10-07→2026-10-07 (elegido), 2016→2026-09-01, 2024-07→2026-07 y 2021→2026-06; EMBJ, sólo el de
1 año.
Razonamiento: `cierres_del_cache` se queda con **un** frame por ticker —el que termina más tarde—,
que para cinco tickers es el de 1 año. `valor_diario` vale en **0** a un ticker en cartera los días
anteriores a su primer cierre (`ultimo_cierre.get(t, 0.0)`), aunque su docstring promete que un
ticker sin cierres *«queda afuera… en vez de valuarse en cero»*: eso vale para el que no tiene
**ningún** cierre, no para el que tiene historia parcial. `ganancias_diarias` (332) suma el costo
de esos lotes y no su valor, así que la no realizada sale ~$4.800 abajo.
Impacto (ampliado por el `verificador`): la curva de valor (305) y la de ganancia (332) de Home
están **subvaluadas del 2024-10-08 al 2025-10-07**, y el escalón se lee como una suba. El hueco no
es constante: ~$3,5k (estimado) mientras sólo faltan AAPL y TEAM, ~$4,9k (medido) con MLTX y EMBJ.
Y dos patas más: **(1)** la serie arranca el 2024-10-08 aunque la primera compra es del 2024-02-21
(NVDA): **7,5 meses no se grafican**, porque todos los frames elegidos empiezan después, aunque
NVDA, INTC, META, MO y MSFT tienen frames 2016→2026; **(2)** la elección es frágil: con dos frames
que terminan el mismo día gana el primero de `all_1d`, y el día que se refresque el 1y y no el 2y
la serie entera pasa a arrancar en 2025-10 sin que cambie ningún dato. Es la pantalla que Chapa
mira primero.
Verificación: ver §3.
¿Por qué no antes? **(c-metodo)** para el valor: la tanda del 05/10 recalculó la curva de Home a
mano «igual a `valor_diario`» —el instrumento contra sí mismo— sobre una cartera de un solo día
de compra, donde no hay historia parcial que ver. **(a)** para la ganancia (332, de hoy). Y la
sesión que shipeó la 332 vio el escalón en la captura y no lo miró: fue un descarte sin argumento.
Acción: unir los frames de cada ticker en vez de elegir uno, y en `valor_diario` no valuar en cero
un ticker en cartera sin cierre: o la serie arranca donde todos los tickers en cartera tienen
historia, o el ticker se reporta como sin historia para esos días. → tarea **336**.

### [I-1] `claude_opinions.ticker` guarda el texto del campo con el nombre de la empresa
Severidad: HIGH · Confianza: ALTA (ver §3) · Categoría: datos (con un conteo de muestra)
Ubicación: `ui/analysis_tab.py:640` (`_on_analysis_done`) contra `:622` (`_run_analysis`)
Evidencia: 14 opiniones en la DB; cuatro con ticker «MU — MICRON TECHNOLOGY», «TSLA — TESLA INC.»,
«GOOGL — ALPHABET INC. (GOOGLE)», «PFE — PFIZER INC.», y MU y TSLA **también** con su ticker
limpio el mismo día (2026-10-06), pese al índice `UNIQUE (ticker, fecha)`
(`ux_claude_opinions_ticker_fecha`). Ninguna otra tabla tiene un ticker con « — ».
Razonamiento: `_run_analysis` corta el texto en « — »; `_on_analysis_done` lo vuelve a leer sin
cortar, y ese valor va a `opinion_card.set_contexto` → `OpinionWorker` → `opinion_claude.guardar`.
Impacto: (1) llamadas a Claude duplicadas: la segunda vez que se abre el ticker, `opinion_de_hoy`
busca con la otra clave y no encuentra la del día; (2) la 321 cuenta *«tickers distintos o días
distintos»* y cruza por ticker contra precios: esas filas se inflan como distintas o se pierden.
Hoy son 12 tickers, no 14. Ampliado por el `verificador`: **(3)** las cuatro opiniones sucias
se pidieron **sin noticias** (`noticias_recientes` busca con el ticker sucio; sus `datos_json` no
tienen la clave `noticias`, y las limpias del mismo día sí) y con `"ticker": "MU — MICRON…"` en el
prompt: son **otra población** y la 321 tiene que excluirlas; **(4)** riesgo, no observado:
`_on_analysis_done` lee el campo al terminar, así que si se escribe otro ticker mientras corre, la
opinión de A queda guardada como B. El texto sucio sale del autocompletar (`_COMPLETION_LIST`).
¿Por qué no antes? **(a)**: la 320 se shipeó el 05/10 a las 23:07, después de la tanda 306.
Acción: usar en `_on_analysis_done` el mismo ticker que `_run_analysis` (un solo lugar que lo
normalice), y corregir las cuatro filas o declararlas en la 321. → tarea **337**.

### [A-1] El backlog no cumple su propio contrato: *En curso* tiene 213 ítems y *Hecho reciente* se dejó de usar en julio
Severidad: MEDIUM · Confianza: ALTA · Categoría: claims
Ubicación: `docs/BACKLOG.md:5` (contrato), su título `## En curso (WIP, máx 1)`, `CLAUDE.md`
(§Backlog: *«movela a Hecho reciente con el hash… En curso máximo 1 ítem»*) y
`.claude/commands/ship.md` paso 5.
Evidencia: `awk` sobre la sección: **213** ítems «WIP», **199** con «CERRADA», 2.055 líneas; *Hecho
reciente* tiene 39 ítems, de julio. La línea 15 dice *«Última actualización: 2026-08-16»*. Ninguna
nota del backlog decide el cambio (`grep` de «Hecho reciente» y «En curso»).
Impacto: cuatro lugares mandan a hacer algo que nadie hace, y la sección que debería decir qué está
en marcha son dos mil líneas de historia. Un lector (o una sesión nueva) no encuentra lo vivo.
¿Por qué no antes? **(c-metodo)**: las corridas de `claims` contrastan afirmaciones contra el
código y la DB, y esto es el archivo contra su propio contrato.
Acción: decidir con Chapa (mover lo cerrado a *Hecho reciente*, o reescribir el contrato a la
práctica) y que los cuatro lugares digan lo mismo. → tarea **338**.

### [D-1] La lección de la 322 («el done va después de la última edición, también la del backlog») no está en `/ship`, y esta sesión la violó cinco veces
Severidad: MEDIUM · Confianza: ALTA · Categoría: guards (de proceso)
Ubicación: `.claude/commands/ship.md` (paso 1 = done, paso 5 = editar el backlog, sin volver al 1)
Evidencia: la lección está sólo en el registro de la 322 (`BACKLOG.md:65`), después del rojo de
`9884a4e`. En esta sesión los cierres de 324/325, 325 (fix), 330, 332 y 326/331 corrieron los
cuatro comandos **antes** de editar el backlog y después sólo `pytest -k backlog`. No dio rojo,
por suerte: el guard de la 72 podía tomar cualquier nombre nuevo del texto.
¿Por qué no antes? **(a)**: la lección es del 05/10, después de la tanda.
Acción: que `/ship` ordene el done después de la última edición (o que lo repita si el backlog
cambió), y que `git-workflow` lo diga igual. → tarea **339**.

### [L-1] «XGBoost: unstable model» aparece en todos los scans, no en el primero del día como midió la 25
Severidad: MEDIUM · Confianza: MEDIA · Categoría: logs (y rendimiento)
Evidencia: 246 WARNING del 05 al 07/10 (117, 63, 66 por día), ~10 por scan, en todas las horas;
66 el 28/09 y 67 el 02/10. La 25 (`f4f59c6`) midió *«6 WARNING en el primer scan del día y 0 en
los siguientes»*. El mensaje no nombra el ticker.
Razonamiento: si el aviso sale en cada scan, el modelo se re-entrena en cada scan (el cache de la
24 no sobrevive), o la consulta manual de Análisis lo dispara. No se distinguió: el mensaje no
tiene ticker.
Impacto: ruido que tapa errores (lo que vino a evitar la 25) y, si es re-entrenamiento, cómputo
por scan que la 24 había sacado.
¿Por qué no antes? **(d)**: las tandas del 04 y 05/10 lo contaron (×21, ×22) y lo dieron por
*«conocida, por diseño»*, con el triple de lo que el diseño dice.
Acción: tarea de **medición** —poner el ticker en el mensaje y contar re-entrenamientos por scan—
con el límite escrito: *no se afirma que la 24 se rompió; no se sabe*. → tarea **340**.

### [I-2] Las 14 opiniones de Claude son «MANTENER»: la 321 está 0/8 en COMPRAR y 0/8 en VENDER, y la cola sólo dice «30 opiniones»
Severidad: MEDIUM · Confianza: ALTA · Categoría: datos
Evidencia: `select recomendacion from claude_opinions` → 14 «MANTENER», confianza 35–55. El
pre-registro de la 321 exige **al menos 8 COMPRAR y 8 VENDER**; las notas de repriorización dicen
*«treinta opiniones con veinte ruedas»* (y yo lo resumí igual a Chapa).
Impacto: la condición que de verdad frena la 321 no figura donde se lee qué espera cada tarea; a
este ritmo la medición no llega nunca, y nadie lo va a notar contando opiniones.
¿Por qué no antes? **(a)**.
Acción: escribirlo en el enunciado de la 321 y en la cola. → tarea **321** (enunciado).

### [A-2] `DB_SCHEMA.md:59` repite «sin ajustar por splits» para `dividend_calendar_cache`
Severidad: LOW · Confianza: ALTA · Categoría: claims
Evidencia: `git grep -n "sin ajustar por splits"`. La 331 corrigió `database/models.py` y
`data/yahoo_finance.py` y dejó este (y el comentario de la migración `0013`, que es historia).
Segunda evidencia independiente de que los montos están ajustados: AAPL 2020-02-07 = **0,1925**
(= $0,77 / 4, el split de agosto de 2020).
¿Por qué no antes? **(a)** como corrección incompleta de hoy (la 331 corrigió dos de tres, la
forma exacta de la 73 y la 181); la frase falsa es más vieja y era **(c-alcance)**: sólo se ve
contra los datos.
Acción: → tarea **341** (junto con [A-3]).

### [A-3] `ARCHITECTURE.md` no nombra la opinión de Claude ni la cartera real
Severidad: LOW · Confianza: ALTA · Categoría: claims (dirección «lo verdadero no escrito») y dependencias
Evidencia: `docs/ARCHITECTURE.md` lista los módulos de `analysis/` y `paper_trading/` uno por uno
y no nombra `analysis/opinion_claude.py` (320) ni su dependencia externa —el CLI `claude`, que en
la máquina de Chapa sale de la extensión de VS Code (`ubicar_claude`)—; en `database/` nombra sólo
los models, no `cartera_real.py` (264, lo que arma Home), `lotes.py` (324) ni el desplegable
`ui/portfolio_detalle.py` (325).
¿Por qué no antes? **(a)** para 320/324/325; **(c-alcance)** para `cartera_real.py`: la tanda del
05/10 miraba lo nuevo de las 303–305.
Acción: → tarea **341**.

### [G-1] La compra de MLTX figura un sábado (2025-06-28)
Severidad: LOW · Confianza: ALTA · Categoría: cuentas (la regla de la 308)
Evidencia: `transactions` de MLTX: BUY 2025-06-28 (sábado). Viene así del CSV de Yahoo de Chapa
(`Trade Date 20250628`). El resto de la cartera real cuadra: cada posición coincide con el FIFO de
sus transacciones, y todo precio con barra cae en el rango del día (banda ±3–7%, porque los frames
están ajustados por dividendos).
Impacto: hoy ninguno (MLTX no paga dividendos y Home va por rueda); una fecha que no puede ser.
¿Por qué no antes? **(a)**: entró con la 324.
Acción: confirmar con Chapa la fecha real. → tarea **342** y *Acciones manuales pendientes*.

### [F-2] La sparkline de la tarjeta «VALOR Y P/L» de Home es el capital invertido neto
Severidad: LOW · Confianza: ALTA · Categoría: pantalla (el rótulo promete más de lo que mide)
Evidencia: `ui/home_tab.py`: `self.kpi_pl.set_series([v for _, v in r["invertido_neto"][-40:]])`,
compras − ventas acumuladas a precio de transacción, bajo un rótulo de valor y P&L.
¿Por qué no antes? **(c-alcance)**: la tanda del 05/10 contrastó la curva y el número de la
tarjeta, no su sparkline.
Acción: graficar el valor (o la ganancia) de `valor_diario`, o rotularla. Encaja con la 334 (el
selector de Home). → tarea **334** (enunciado).

## 2. Barridos por área (alcance real, como lista)

- **A claims:** `CLAUDE.md`; header, *En curso* y cola de `BACKLOG.md`; los comandos `audit`,
  `backlog`, `ship`, `test`; las skills en disco (`auditoria`, `backtest-replay-harness`,
  `catalyst-pipeline`, `fair-value-feature`, `finanzias-conventions`, `git-workflow`,
  `hallazgo-a-backlog`, `testing`) por `grep` de las frases corregidas; `ARCHITECTURE.md`
  (sección Paquetes) y `DB_SCHEMA.md` por `grep`. Frases buscadas en todo el repo: «sin ajustar
  por splits», «capital invertido neto», «no es valor de mercado», «Prob. venta», «solo
  grafica», «kill_only», «id=1». → [A-1], [A-2], [A-3]. Las otras aparecen sólo como historia.
- **B muestra:** `lotes.py` (`detectar_splits` compara la venta contra la **tenencia** y el
  nocional, no un conteo), `cartera_real.py` (`registrar_venta` exige que el FIFO de las
  transacciones **iguale** la tenencia antes de recalcular), `csv_importer.py`, el pre-registro de
  la 321 (cuenta opiniones: [I-1], [I-2]). La operación que movió una muestra, el reemplazo de
  «Mis Acciones» (324): nada referencia `positions.id` salvo `transactions` (FK), y las alertas van
  por `portfolio_id` + ticker. Limpio fuera de lo publicado.
- **C desvíos:** `settings.json` sin cambios desde 2026-09-13; en motor/harness sólo entró la 311
  (desvío `spinoffs`, declarado). La diferencia nueva —dividendos de una posición comprada antes de
  un split— es latente y ya tiene tarea (**333**). **Limpio.**
- **D guards:** CI de `main` en **verde** (`30d573c` = `origin/main`). Rojos desde la 306:
  `9884a4e` (322), `6522c2e` y `5e8f373` (segfault, 330): los tres con causa escrita. Los guards
  nuevos de 324–332 se mutaron al shipearse (rojos con el caso contrario). → [D-1].
- **E estado:** cierres de la cartera real frescos al 07/10 pero partidos en frames ([F-1]);
  `price_cache` 62.976 filas desde el 30/09 (archivado vigente); `claude_opinions` 14 filas;
  `~/.finanzias/`: `finanzias.log` 2,5 MB, `congelamientos.log` 8 KB. Limpio fuera de [F-1].
- **F pantalla:** Home (valor, ganancia, KPI) contra `resumen_home` y la DB → [F-1], [F-2];
  Portfolio: la realizada por posición coincide con la 324 (AAPL 782,17; INTC 853,41; KO 49,23;
  META 1.597,12); la opinión de Claude → [I-1].
- **G cuentas:** cuenta 1: caja $4.673,98 = cálculo, 5 de 5 posiciones, sin órdenes desde el 05/10;
  cuenta 2: caja $1.270,32 = cálculo, 10 de 10, acciones cuadradas; cartera real cuadrada contra
  el FIFO → [G-1].
- **H operación:** snapshots de la cuenta 2 los tres días hábiles (30, 11, 7); backups diarios y el
  de la 324 (`…15-37-56_pre-reemplazar-cartera-csv.db`); los `-shm/-wal` sueltos ya tienen tarea.
  `paper_dividend_credits` vacía es **correcta** (ninguna tenencia cruzó un ex-date desde la 222).
  **Limpio.**
- **I datos:** el CSV de Chapa contra la DB (324, al centavo); `dividend_calendar_cache` ajustado
  (NVDA y AAPL); `company_info_cache` con los cinco nombres de la 329; `claude_opinions` →
  [I-1], [I-2].
- **J rendimiento:** `resumen_home` 0,57 s en frío y 0,10 s después; `EXPLAIN QUERY PLAN` de
  `opinion_de_hoy`, `calendario_del_cache`, `_armar_libros`, `completar_nombres` y las
  transacciones de Home: todos por índice. Las trabas del vigía del 07/10 (4,4 s y 2,2 s) quedaron
  bajo los 5 s y **no tienen stack**: no se pueden atribuir, y no se publican. **Limpio.**
- **K dependencias:** sin imports de terceros nuevos en 307–334; el CLI `claude` → [A-3].
- **L logs:** 405 líneas WARNING+ en 20 firmas, **0 tracebacks**, todas de la app. Clasificadas:
  barra provisional (243, por diseño, una línea por lote); vigía (304); Invalid Crumb y el 401
  *«unable to access»* (familia del crumb, con reintento); `possibly delisted` y el ERROR vacío de
  yfinance (cabecera de *«1 Failed download»*) cuando se tipeó REDDIT y PCGA en Análisis; un scan
  con un ticker sin precio. Ninguna firma de 322, 323 o 330 reaparece. → [L-1].

## 3. Fase adversarial

El `verificador` corrió (independiente, con su propia copia de la DB y el Python de Anaconda) con
el mandato de refutar, atacando primero el instrumento.

- **[F-1] CONFIRMADO, con el impacto ampliado y el número recortado.** El instrumento resistió: Home
  no usa otro proveedor de cierres en producción (`home_tab.py:312` → `cierres_del_cache`), y los
  frames listados son los elegidos. Recalculó los días del salto con los frames largos: los saltos
  no son movimientos de precio, son tickers que entran al cache. Recortó *«~$4.800 durante todo el
  primer año»* a *«de ~$3,5k a ~$4,9k según el tramo»*, y sumó dos patas (los 7,5 meses sin
  graficar y la elección frágil del frame). Las tres están en el enunciado de la **336**.
- **[I-1] CONFIRMADO, con el impacto ampliado.** Recorrió el camino entero (`analysis_tab.py:622,
  640, 683, 685` → `opinion_card.py:116, 127, 54` → `opinion_claude.py:381, 385, 405`): sólo
  `.upper()`, ninguna normalización. Confirmó las dos llamadas duplicadas (MU 03:41 sucio y 18:01
  limpio; TSLA 18:02 y 18:07), que la 321 no prevé normalizar, y sumó las opiniones sin noticias y
  el riesgo de atribución. Un menor: la columna es `VARCHAR(20)` y la fila de GOOGL tiene 30
  caracteres (SQLite no lo hace cumplir). Todo en el enunciado de la **337**.

Ningún hallazgo fue retirado.

## 4. Limitaciones

- El rango de precio por día ([G-1] y el barrido de G) se midió contra frames `auto_adjust`, con
  una banda que tolera el ajuste por dividendos; no detecta un precio corrido unos pocos puntos.
- La DB se copió con la app abierta (API de backup, consistente).
- [L-1] no distingue re-entrenamiento de consulta manual: el mensaje no trae ticker.

## 5. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| [F-1] | 336 |
| [I-1] | 337 |
| [A-1] | 338 |
| [D-1] | 339 |
| [L-1] | 340 |
| [I-2] | 321 (enunciado) |
| [A-2] | 341 |
| [A-3] | 341 |
| [G-1] | 342 |
| [F-2] | 334 (enunciado) |

## 6. Deuda de la skill (los (c-metodo) y (d))

- **[F-1] (c-metodo):** contrastar una curva «igual a `valor_diario`» es medir el instrumento con
  sí mismo. Le faltaba: **por cada ticker en cartera, ¿su historia cubre la serie desde su primera
  compra?** Y probarlo sobre una cartera con compras en fechas distintas.
- **[A-1] (c-metodo):** `claims` contrasta afirmaciones contra código y DB; un archivo que no
  cumple su propio contrato no es ninguna de las dos. Le faltaba: **los contratos de proceso se
  contrastan contra la práctica medida** (cuántos ítems tiene la sección que dice «máx 1»).
- **[L-1] (d):** una firma *«conocida, por diseño»* se clasificó sin comparar su **frecuencia**
  contra la que midió la tarea que la diseñó. Le faltaba: **una firma conocida se clasifica con
  su tasa, y una tasa mayor que la del cierre es «reaparece después del cierre»**.
