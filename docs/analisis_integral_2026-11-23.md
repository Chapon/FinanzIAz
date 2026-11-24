# Análisis integral de FinanzIAs — lo bueno y lo malo · 2026-11-23

Pedido de Chapa (2026-11-23): *«hacer un análisis profundo de toda la aplicación buscando cosas buenas
y malas de lo que tenemos»*.

**Sólo lectura.** Una copia de `finanzias.db` (API de backup desde `mode=ro`, 2026-11-23 21:45),
`git`, el código y los docs. No se cambió nada. Cada afirmación lleva el comando o el archivo que la
sostiene. **No es exhaustivo**, porque el repo no se puede barrer entero en una pasada: lo que se
miró va como lista en el §0, y lo que no, también.

## En una línea

**Lo mejor de FinanzIAs es cómo mide. Lo peor es lo que esa medición dice:** la estrategia
automática no le gana a tener SPY y caja, y sostener la medición se lleva más trabajo que el
producto.

## 0. Alcance

**Mirado:**

1. El tamaño y la forma del código: `git ls-files` por paquete, los archivos más grandes y las
   funciones más largas (AST sobre `analysis/`, `data/`, `paper_trading/`, `ui/`, `database/` y
   `config/`).
2. La suite: qué verifica cada archivo de test (si lee docs, skills o `CLAUDE.md`).
3. El historial de `git`: 1.010 commits, por tipo y por mes.
4. El backlog: tareas abiertas y cerradas, veredictos y origen.
5. La cuenta 2 (Sim Segundo) en la DB: órdenes, costos, rotación, P&L por motivo de salida,
   dividendos, caja y días con scan.
6. La investigación: la corrida de la 456 de hoy y los veredictos de la T170, la T219, la T385 y la
   T413.
7. El cohorte de los harness: la frescura que imprime el banner.
8. Las opiniones de Claude (`claude_opinions`).
9. Los imports cruzados entre `scripts/`.

**No mirado, y por qué:** la usabilidad y la estética de la GUI (no hubo revisión visual); seguridad
(para eso está `security-review`); el cuadre de la cartera real («Mis Acciones»); las versiones
instaladas contra el lock y `pip-audit`; el estado de AWS (desde acá no hay acceso); el censo del
log, salvo el de la tarde de hoy; el profiling. Cada uno tiene su área en `/audit`.

**Fase adversarial:** la hice yo, y no el agente `verificador`. Vale menos que una independiente, y
se marca en cada hallazgo (§4).

## 1. Lo bueno

**B1. El rigor de la investigación es de nivel profesional.** Toda idea de trading pasa por un
pre-registro congelado antes del código, con kill-criteria, un ancla de reproducción contra un número
ya publicado, brazos oráculo con su control igualado y mutaciones de los tests. Resultado: **27
NO-SHIP** documentados (`grep` sobre los títulos del backlog) que habrían sido plata perdida si se
cableaban. La T167 cazó un SHIP publicado que dejó de reproducirse. Hoy la 456 midió el dato más
importante del proyecto con un sanity que reprodujo la T170 al dígito (8,78% / 0,55 / 2.531).
Casi nadie que opera por su cuenta trabaja así.

**B2. Los datos y la contabilidad se cuidan en serio.** Señales point-in-time
(`data/pit_signals/`), fundamentals de EDGAR con su fecha de presentación (382), splits, spin-offs y
dividendos acreditados (222, 333, 350), y la caja y las posiciones cuadradas contra órdenes y
dividendos **en cada scan**, con un Slack si descuadra (266). Los tickers muertos se detectan (WBD,
369) y los precios corruptos se votan entre tres fuentes (241).

**B3. La red de seguridad del código es muy sólida.** 5.186 tests; un cortafuegos de red que cubre
también los subprocesos (209, 211); la DB, los settings y Slack aislados en los tests; un cuarto
comando que corre la suite con el home vacío, como el CI (176); y el CI leído, no supuesto
(`check_ci.py`, 300). La app se relanza sola con el `.venv` (432) y avisa cuando corre código sin
commitear (433).

**B4. Lo que no se modela, se dice.** El harness declara sus desvíos contra la cuenta viva en cada
corrida, con clave estable (152) y con el marco de cada número (242). El log marca el proceso de
origen de cada línea (288), y un vigía vuelca el stack cuando la GUI se traba (304, 380).

**B5. El producto tiene piezas útiles para decidir.** Home pone la cuenta contra su universo sin
elegir (377) y muestra lo que cuesta rotar (386). «Mis Acciones» tiene lotes, fechas reales y
dividendos (308, 324, 281). Analysis trae la valuación de Graham, *Buffettology* y Lynch, el puntaje
de calidad (383, 384) y la opinión de Claude con el commit que la produjo. Todo eso es display, como
manda la regla 3.

**B6. En vivo, la cuenta 2 se defendió.** Desde el alta (2026-06-20) va **−0,91%** contra **−3,00%**
de SPY (`paper_equity_snapshots`, `SPY__2y__1d`). Los costos fueron US$ 697 (US$ 145 de comisión y
US$ 552 de slippage), o sea el 1,4% del capital en 155 días.

## 2. Lo malo

**M1. No hay una ventaja medida, y la pérdida está en las ventas.** · Severidad ALTA · Confianza ALTA
- En el simulador, la estrategia de la cuenta 2 rinde **7,32%** anual. SPY + caja con la misma caída
  rinde **9,99%**, y SPY solo, 15,19% (456). Fuera de muestra la diferencia es **+6,40 pp por año a
  favor del pasivo**, en 4 de 5 años y con menos caída, pero el intervalo cruza el cero: **no
  decidible**, no *«pierde»*.
- Comprar con la señal cuesta ~2,1 pp contra comprar al azar (T219, T21, T39). Vender y rotar cuesta
  ~6,4 pp contra quedarse con el universo (`docs/compras_ventas_efectividad_2026-11-23.md`).
- En vivo: las **66 ventas por señal suman −US$ 6.924, con 26% de aciertos**; los 17 take-profit,
  +US$ 8.208; el P&L realizado neto es **−US$ 759** en 155 días (copia de la DB, FIFO por ticker).
- De ~30 experimentos de compras y ventas se cablearon tres cosas: el escalado por régimen (T20),
  la política de salida de la T37 (que la 167 no pudo reproducir y la 170 decidió no mover) y el
  screen de universo E1b, que hoy no excluye a nadie. El escalado cuesta, bajo la política viva,
  cinco veces el precio declarado (**459**).

**M2. La app tiene que estar abierta para que el sistema exista.** · ALTA · ALTA
- Desde el alta de la cuenta 2, la app escaneó en **74 de 109 ruedas (68%)**
  (`paper_equity_snapshots`; el 3/7 y el 7/9 fueron feriado y no cuentan en ninguno de los dos). Un día de cada tres no hubo decisiones,
  stops ni recolección.
- El recolector de la nube está construido desde octubre (355, 362) y la app ya sabe bajarlo (356),
  pero **espera los pasos de AWS** de *Acciones manuales*. Por eso la temporada Q3 de T-CAT-5b quedó
  con huecos, y lo que juntó la nube vence por TTL desde el ~25/01/2027.

**M3. Hay frenos prendidos que deciden todos los días sin backtest.** · MEDIA-ALTA · ALTA
- El overlay de volatilidad recorta toda compra nueva (factor medio 0,74 desde septiembre, 0,59 en
  noviembre) y nunca se midió (**457**).
- El bloqueo de compras alrededor de los balances (Gate 6) tampoco. La 96 lo dio por no modelable, y
  Yahoo trae 49 trimestres de fechas (**458**).
- Hoy, con el risk-off, la cuenta tiene el **60% en caja**: cada compra entra a ~15% de un slot
  (×0,25 del régimen y ×0,59 del overlay), y 7 de las 10 posiciones valen entre US$ 517 y US$ 950.

**M4. Los datos gratis son frágiles, y lo más caro de procesarlos no decide nada.** · MEDIA · ALTA
- Las noticias de Yahoo se cayeron el 1/10 (354). Finnhub trae 7 días por pedido, y el 96% de lo que
  se baja ya estaba (413).
- Clasificar las noticias con qwen se llevó **49,6 h de GPU en dos meses**, y lo único que lo usa es
  el orden de la pestaña Noticias (413). El tono no predice el retorno (255 y 258, NO PASA). La
  decisión espera a la **451** (no antes del 2026-12-21).
- La opinión de Claude dijo **MANTENER en 20 de 21** (una VENDER, ninguna COMPRAR; confianza de 20
  a 55): con esa distribución la 321 no puede medir si acierta.

**M5. Sostener el proceso pesa más que el producto.** · MEDIA · ALTA (en los números; el juicio es mío)
- **504 de 1.010 commits son `docs`**, y desde septiembre **295 de 692 tocan sólo el backlog**.
- `docs/BACKLOG.md` pesa **2,5 MB**: 459 tareas, 442 cerradas, y cada cierre deja su texto entero.
- **98 de los 390 archivos de test** leen docs, skills o `CLAUDE.md`: verifican el proceso, no la app.
- El archivo más grande del repo es `analysis/harness_config.py` (**3.444 líneas**), casi todo prosa
  de desvíos que cada runner imprime: el banner de la 456 tuvo 12 desvíos y 5.763 caracteres, y el
  más largo, 1.791.
- Cada tarea se cierra con dos commits, dos corridas de los cuatro comandos (~13 min cada una) y dos
  esperas del CI (~9 min): unos **45 minutos fijos por tarea**, antes de cualquier trabajo.
- 139 de las 459 tareas nacieron de auditorías y tandas, o sea del propio proceso.

  No digo que sobre: cada guard tiene su defecto real detrás, y la regla 7 es de Chapa. Digo que el
  costo existe y que nadie lo midió, mientras la pregunta de producto (**¿hay ventaja?**) sigue
  abierta. → **460**

**M6. Deuda de código en el lugar más sensible.** · MEDIA · ALTA
- `paper_trading/engine.py:847` **`run_scan` tiene 864 líneas**: el motor entero, gates incluidos, en
  una función. Es la más larga del repo por el doble (le sigue `portfolio_backtest` con 425). Cada
  gate nuevo se modela aparte en el harness, y así nacen los desvíos. → **461**
- **40 scripts importan de otros scripts.** `load_bars_signals` vive en el runner de la T23 y lo
  importan 15; `SimCache`, `FOLDS` y `NO_STOP` viven en runners de tareas cerradas; la 456 importa un
  helper privado de la T219. La librería de investigación está repartida entre experimentos viejos.
  → **462**
- El stack sigue pineado por debajo de lo actual (numpy < 2, scikit-learn < 1.8, PyQt6 < 6.8). Ya
  está en *Backlog / ideas*, con lo que hay que migrar.

**M7. El cohorte de investigación quedó congelado sin dueño.** · BAJA · ALTA
- Los artefactos terminan el **2026-09-09**, 53 ruedas atrás (el banner de la 456), y toda corrida
  nueva necesita `--allow-stale-artifacts`. Ninguna tarea abierta lo refresca, y ninguna dice que se
  congeló a propósito. Refrescar suma poca muestra (T48) y obliga a re-anclar constantes (157): la
  decisión puede ser no hacerlo, pero tiene que estar escrita. → **463**

**M8. No se sabe qué partes de la app se usan.** · BAJA · ALTA
- Doce pestañas, y nada registra cuál se abre (413). Sin eso no se puede decidir qué sacar. Lo trata
  la **451**, para las noticias.

## 3. Qué haría, en orden

1. **Conectar la nube (355 y 356).** Es lo único que hace que el sistema deje de perder un día de
   cada tres, y espera ~30 minutos de consola de AWS de Chapa.
2. **Decidir qué es la cuenta 2.** Con la 456 y la 459: seguir igual, cambiar el factor de régimen,
   o sumar una cuenta pasiva al lado como control vivo.
3. **Medir los dos frenos sin backtest** (457 y 458).
4. **Aliviar el proceso** (460), con lo que Chapa decida.
5. La deuda de código (461 y 462) y el cohorte (463), cuando no haya nada más arriba.

## 4. Fase adversarial (propia, no independiente)

- **M1.** ¿El instrumento sesga contra la estrategia? El ancla reprodujo la T170 al dígito y el
  control del pasivo dio un error de 1e-15. El sesgo de supervivencia no toca a SPY. Lo que **no** se
  sostiene es *«la estrategia pierde»*: el intervalo cruza el cero, y se escribe *«no hay ventaja
  medida»*. Contra M1 juega el vivo (−0,91% contra −3,00%): son cinco meses, y es consistente con la
  caída menor del escalado.
- **M2.** El instrumento cuenta los días con algún snapshot de la cuenta 2. Con
  `paper_enforce_market_hours=False` la app escanea también fuera de hora, así que un día abierto
  deja al menos uno: la cobertura no está subestimada. `pd.bdate_range` contaba dos feriados (3/7 y
  7/9), y la app escaneó esos dos días: el primer conteo daba 76/111. Sin los feriados, 74/109.
- **M5.** ¿El 50% de commits de `docs` lo infla la regla del commit de hash? En parte sí, por diseño:
  una tarea son dos commits. Por eso el costo se mide en tiempo por tarea y no en commits. Que un
  test lea un doc no lo hace inútil: el número dice dónde va el esfuerzo, no que sobre.
- **M6.** ¿Las 864 líneas de `run_scan` son mayormente comentarios? No lo separé. Muchos bloques
  llevan prosa larga, así que el código ejecutable es menos. El hallazgo es la función única, no el
  número exacto.

## 5. Hallazgo → tarea

| hallazgo | tarea |
|---|---|
| M1 | 456 (cerrada hoy, NO DECIDIBLE) y **459** |
| M2 | 355, 362 y 356 (esperan a Chapa en AWS) |
| M3 | **457** y **458** |
| M4 | 451 (noticias), 321 (opiniones) |
| M5 | **460** (nueva; la decisión es de Chapa) |
| M6 | **461** y **462** (nuevas); dependencias en *Backlog / ideas* |
| M7 | **463** (nueva) |
| M8 | 451 |
