# Auditoría READ-ONLY — área `desvios` — 2026-09-27

Área: **desvíos harness↔engine que `deviations()` no declara, o declara mal**. Corrida anterior
de esta área: `docs/auditoria_desvios_2026-09-11.md` (dejó las tareas 184 y 185, las dos
cerradas).

---

## 1. Kill-criteria — CONGELADO 2026-09-27, antes de abrir ningún archivo del área

> Lo único mirado antes de escribir esta sección: el informe anterior de esta área y los
> **títulos** de `git log` sobre `paper_trading/`, `analysis/harness_config.py`,
> `analysis/portfolio_sim.py` y `analysis/exit_replay.py` desde el 2026-09-11 17:42.
> Ningún archivo de código abierto.

### 1.1 Por qué ahora

1. **El motor vivo cambió de contabilidad.** La 222 (`210b940`, 2026-09-25) acredita los
   dividendos a la caja al ex-date. El desvío `dividendos` se re-describió en ese mismo commit
   (*«los dos cobran, uno reinvierte»*). Un desvío re-escrito por la misma tarea que movió el
   motor es exactamente lo que hay que re-leer con ojos que no lo escribieron.
2. **El motor ganó un camino de precio condicional.** La 201 (`0a6bdac`): con
   `price_second_opinion_enabled` el scan usa el precio independiente y la venta por señal
   pasa a pedir aprobación. Hoy el flag está OFF, **pero prenderlo es una acción manual
   pendiente de Chapa** — o sea que el desvío, si existe, se enciende por una edición de
   `settings.json` y no por un commit.
3. Entraron otras cinco al contrato: 184 (ADV cap declarado), 215 (rastro del Gate 6), 219
   (demora de la salida por señal, NO-SHIP), 221 (clave `dividendos`), 181 (`kill_only`).

### 1.2 Qué se busca — una frase por sub-categoría

- **[D-falta]** Una conducta **viva** del engine que cambia qué se compra, qué se vende, a qué
  precio, cuánto, o cuánta caja hay, que el harness no modela y que `deviations_keyed()` **no
  nombra** con una clave.
- **[D-latente]** Un flag hoy OFF cuyo encendido está **pendiente o previsto** (acción manual
  de Chapa) y que, al prenderse, abre un desvío que **nada declararía** — ni la clave, ni el
  espejo, ni el guard de la 185.
- **[D-espejo]** Un `LIVE_*` que dejó de describir a la cuenta viva, o una perilla que el
  engine lee en una decisión sin espejo ni excepción con motivo.
- **[D-texto]** Un desvío declarado cuyo texto afirma algo que el código contradice, o que se
  contradice con otra línea del banner (forma de la 169). Foco: `dividendos` post-222.
- **[D-veredicto]** Un veredicto publicado que se lee hoy sin el desvío que existía cuando se
  midió (o al revés) — foco: todo lo publicado antes del 2026-09-25 con el desvío de
  dividendos en su forma vieja.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. Bugs de código, re-correr harness y decidir política.
2. Si un desvío **debería** cerrarse (decisión de trading).
3. Las otras cuatro áreas de `/audit`.
4. **El conteo de desvíos como número.** Se compara la **clave** de `deviations_keyed()`.
5. El Gate 2c / catalyst (OFF y sin provider, tarea 162), `ui/`, `alembic/`.

### 1.4 Qué contaría como "acá no hay nada" — en las DOS direcciones

**Dirección 1 — lo escrito es falso.** Ninguna clave de `deviations_keyed()` afirma algo que el
engine contradiga; todo `LIVE_*` coincide con `settings.json` vivo y la cuenta 2.

**Dirección 2 — lo verdadero no está escrito.** Recorriendo **el camino de `run_scan` en el
engine** (no la lista de claves), toda diferencia con `portfolio_sim`/`replay_cycle` que mueva
órdenes, precio, tamaño o caja tiene su clave; y todo flag con encendido pendiente tiene
prevista su declaración o una línea que diga por qué no hace falta.

Si las dos se cumplen, la corrida cierra limpia y se dice. Lo que no se pudo verificar se
declara aparte, no se cuenta como limpio.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Etiquetas (a) / (b) / (c-alcance) / (c-metodo) / (d) de la skill `auditoria`.

### 1.6 Alcance — qué se mira

1. `analysis/harness_config.py` — `deviations()`, `deviations_keyed()`, los `LIVE_*`.
2. `paper_trading/engine.py` (`run_scan` de punta a punta), `paper_trading/gates.py`,
   `paper_trading/dividends.py`.
3. `~/.finanzias/settings.json` y la cuenta 2 en `finanzias.db` — **lectura, sobre copia**.
4. `analysis/portfolio_sim.py` y `analysis/exit_replay.py` — qué modelan de verdad.
5. El guard de espejos (`tests/test_espejos_vivos_t130.py` y el de la 185).

### 1.7 Alcance — qué NO se mira, dicho antes

- Los runners uno por uno (se mira el banner compartido, no los 30+ `print`).
- `data/providers.py` más allá de lo que el engine consume de él.
- La cuenta 1 (cerrada).

---

## 2. Alcance real

**Mirado:** las claves posibles de `deviations_keyed()` (`analysis/harness_config.py:2105-2293`)
y sus textos; `run_scan` de punta a punta (`paper_trading/engine.py:791-1579`), gate por gate;
`paper_trading/dividends.py`; `paper_trading/universe.py` (umbrales del screen); los valores vivos
de `~/.finanzias/settings.json` de las 17 perillas en juego; la cuenta 2 y el ledger de dividendos
en una **copia** de `finanzias.db`; los defaults de `ScaleOutParams`
(`analysis/scaleout_replay.py:119-120`); y los dos guards de espejos (130 y 185), incluyendo un
barrido AST propio de `paper_trading/`, `analysis/`, `data/` y `config/` para medir qué claves del
`SCHEMA` se leen fuera de la población del guard de la 185.

**NO mirado, y queda declarado:** los runners uno por uno; `data/providers.py` por dentro; la
cuenta 1; el Gate 2c.

**Fase adversarial: PROPIA, no independiente.** Ningún hallazgo llegó a HIGH, así que la skill no
obliga a pasar por el `verificador`. La refutación la hice yo con los ángulos de la skill (config
que lo explique, test que ya lo cubra, commit reciente que lo arregle) y va escrita en cada
hallazgo. Vale menos que una independiente, y el lector tiene que poder saberlo.

**Validación del instrumento.** El barrido AST de fuera-de-población **importa** las funciones del
propio guard (`claves_del_camino_vivo`, `SIN_ESPEJO`, `ESPEJOS`) en vez de copiarlas: la única
variable es el conjunto de archivos recorridos. Contraprueba: dentro de la población ve las mismas
**42** claves que ve el guard.

---

## 3. Hallazgos

### [D-1] El guard de la 185 enumera su población POR ARCHIVO, y seis perillas de decisión viven afuera — una con encendido pendiente

Severidad: **MEDIA** (latente) · Confianza: ALTA · Categoría: [D-latente] + [D-espejo]
Ubicación: `tests/test_espejos_direccion_faltante_t185.py:48-54` (`_CAMINO_VIVO`)

**Evidencia.** `_CAMINO_VIVO` es una tupla literal de **cinco archivos**. Barriendo con las mismas
funciones del guard el resto de `paper_trading/`, `analysis/`, `data/` y `config/`, aparecen claves
del `SCHEMA` que el guard **no ve**, sin espejo ni clasificación. Descontando scheduler, logging y
cache, las que **deciden una orden** son seis:

| perilla | se lee en | qué decide | vivo |
|---|---|---|---|
| `price_second_opinion_enabled` | `data/yahoo_finance.py:998` | con ON: bloquea BUYs y manda las SELL de señal a aprobación manual **también en cuentas `auto`** (`engine.py:1382-1419`) | OFF — **encendido pendiente** (acción manual de Chapa, tareas 127/200/201) |
| `price_sanity_band_pct` | `data/yahoo_finance.py:494` | banda del E5: rechaza fills | 0.5 (default) |
| `paper_universe_min_adv_dollars` | `paper_trading/universe.py:68` | pata de liquidez del screen | 0.0 |
| `paper_universe_fundamentals_enabled` | `paper_trading/universe.py:69` | pata fundamental del screen | True |
| `paper_universe_min_negative_years` | `paper_trading/universe.py:70` | ídem | 2 |
| `paper_universe_revenue_floor_dollars` | `paper_trading/universe.py:71` | ídem | 1e7 |

**Razonamiento.** El docstring del guard dice *«La población se descubre, no se enumera. Si esta
lista fuera un literal, sería el defecto de la 133 / 141 / 147 un nivel más arriba»*. Es cierto
para las **claves**, pero la lista de **archivos** es exactamente ese literal. El caso que importa
es el primero: cuando Chapa prenda la segunda opinión (lo que *Acciones manuales* le propone), el
motor gana una conducta que el harness no modela —no entra en nombres con precio en disputa,
demora las salidas por señal— y **ninguna** de las tres capas lo nota: no hay clave en
`deviations_keyed()`, no hay espejo, y el guard que existe para encontrar perillas sin espejo no
lee el archivo donde vive.

**Impacto.** Latente y probablemente chico en frecuencia (las disputas salen de cotizaciones
corruptas, del orden de los casos KLAC/AVB). El costo no es el tamaño del desvío sino que se
enciende **por una edición de `settings.json`**, sin commit, y en silencio. Los cuatro umbrales del
screen son parámetros de un gate **ya declarado** (`universe_screen`), así que el costo ahí es de
texto (ver [D-3]), no de modelo.

**Verificación.** Se buscó la segunda opinión en `deviations_keyed()`: no está. Se buscó si alguna
de las seis está en `ESPEJOS` o en `SIN_ESPEJO`: ninguna (sólo el master switch
`paper_universe_screen_enabled` tiene espejo).

**¿Por qué no antes? (a) NO EXISTÍA** — el guard lo shipeó la 185 después de la corrida del
2026-09-11, y la segunda opinión en el motor es de la 201 (2026-09-14).

**Acción.** Que la población de archivos también se descubra (todo `paper_trading/` + `data/` +
`analysis/` con exclusiones escritas, o los módulos alcanzables desde `run_scan`), y clasificar las
seis. Para `price_second_opinion_enabled`, decidir **antes** de que se prenda si lleva clave
condicional en `deviations_keyed()` o una línea de por qué no hace falta.

### [D-2] `paper_signal_sell_min_age_bdays` está marcada «YA_DECLARADO» por una clave que no la nombra — y el harness la modela con un literal

Severidad: **MEDIA** (latente) · Confianza: ALTA · Categoría: [D-espejo] + [D-texto]
Ubicación: `tests/test_espejos_direccion_faltante_t185.py:138`, `analysis/scaleout_replay.py:119-120`

**Evidencia.** La clasificación dice: *«YA_DECLARADO: parte del Gate 2b, que la clave
`reentry_gates` ya declara»*. El texto de `reentry_gates` (`harness_config.py:2283-2292`) nombra
**Gate 5 y Gate 5b** y ningún otro; el Gate 2b no es de re-entrada sino de **salida**
(`engine.py:1184-1202`). Y el harness **sí** lo modela: `ScaleOutParams.min_age_bdays: int = 3` y
`bypass_score: float = 0.25`, dos literales. El único test que fija el 3 lo compara contra otro
literal (`tests/test_signal_exit_delay_t219.py:189`), no contra el settings.

**Razonamiento.** Es la forma de `atr_tp_mult`, que el mismo archivo sí marca `FALTA_ESPEJO`: una
perilla de política de salida que el harness modela con un literal que **hoy coincide** con el vivo
(3 == 3). Pero está clasificada como cerrada, con un motivo falso por partida doble: ni la clave la
nombra, ni hay un desvío que declarar. Y el hermano `bypass_score` tiene espejo
(`LIVE_SIGNAL_SELL_BYPASS_SCORE`, desde la 219), pero el default de `ScaleOutParams` **no lo lee**:
es otro `0.25` escrito a mano, así que el guard de la 130 verifica un espejo que el harness no usa.

**Impacto.** Latente. Si Chapa mueve la edad mínima (la 219 la barrió como eje, así que es una
perilla que se considera mover), todo harness de salida sigue modelando 3 días y nada lo dice. Es
el defecto de la tarea 92 (7,16 pp de CAGR por una política de salida declarada al revés).

**Verificación.** Se buscó un test que ate `ScaleOutParams()` a un `LIVE_*` o al settings: no hay.
Se leyeron el texto completo de `reentry_gates` y los `REENTRY_GATES_*_DESC`: ninguno menciona el 2b.

**¿Por qué no antes? (a) NO EXISTÍA** — la clasificación la escribió la 185 (posterior a la
corrida) y el espejo del bypass la 219.

**Acción.** Espejo `LIVE_SIGNAL_SELL_MIN_AGE_BDAYS` en la tabla de la 130; que los defaults de
`ScaleOutParams` **lean** los dos espejos en vez de repetir el número; reclasificar la entrada.

### [D-3] El desvío `universe_screen` afirma una pata de ADV$ que en vivo está apagada

Severidad: **BAJA-MEDIA** · Confianza: ALTA · Categoría: [D-texto]
Ubicación: `analysis/harness_config.py:2254-2264`

**Evidencia.** El texto: *«en vivo dropea candidatos de BUY por ADV$/fragilidad fundamental»*.
`paper_trading/universe.py:47`: *«`min_adv_dollars` — recent ADV$ floor; 0 disables the liquidity
leg»*. Valor vivo: `paper_universe_min_adv_dollars = 0.0`.

**Razonamiento.** En vivo el screen sólo corre la pata fundamental. El texto describe un gate con
dos patas, y quien lea el banner para decidir si un brazo con filtro de liquidez replica lo vivo va
a concluir que sí.

**Impacto.** Chico: el mismo texto dice que hoy el screen no excluye a nadie. Pero es texto que
**dirige mal**, la clase que el repo viene sacando una por una.

**Verificación.** Se buscó otro piso de ADV$ que excluya candidatos: no hay. El
`paper_adv_cap_pct` (Gate 3b) es otra cosa —recorta, no excluye— y tiene su propia clave.

**¿Por qué no antes? (c-metodo)** — el texto es de la 131 (`ab89dc4`), anterior a la corrida del
2026-09-11, y esa corrida escribió *«se leyeron las 10 claves y sus textos contra el código:
ninguna afirma algo que el código contradiga»*. Es cierto: el texto no contradice al **código**,
contradice al **valor vivo** de una sub-perilla. Contrastar contra el código no puede verlo.

**Acción.** Que el texto derive qué patas están activas (de `UniverseThresholds.from_settings()` o
de un espejo), o como mínimo que nombre la que corre.

### [D-4] Dos restos de texto caducado en el registro de desvíos

Severidad: **BAJA** · Confianza: ALTA · Categoría: [D-texto]

1. `analysis/harness_config.py:2277-2279`, comentario sobre `dividendos`: *«el motor no tiene
   forma de cobrarlos (no los mira). Se declara siempre, hasta que la 221 lo cierre»*. Desde la
   222 el motor sí los cobra, y el desvío no se cerró: se re-describió. El `dividendos_desc()` de
   al lado está bien; el comentario quedó del estado anterior.
2. `analysis/harness_config.py:2248`, `regime_scale`: *«0 de 62 BUY vivas lo dispararon»*, sin
   fecha. Hoy son **0 de 80** (copia de la DB, 2026-09-27). La conclusión no cambia; el número se
   lee como actual y no lo es.

**¿Por qué no antes?** (1) **(a)** — la 222 es del 2026-09-25. (2) **(c-metodo)**, la misma raíz
que [D-3]: un conteo vivo embebido sin fecha no se ve contrastando texto contra código.

**Acción.** Actualizar el comentario; fechar el conteo o derivarlo.

---

## 4. Barrido limpio en el resto del área — las dos direcciones

**Dirección 1 (lo escrito es falso)**, fuera de [D-2]–[D-4]:

- `dividendos` post-222: el mecanismo que describe coincide con `engine.py:843-868` (crédito antes
  de la estrategia, ventana `(último scan, hoy]`). El ledger `paper_dividend_credits` tiene **0**
  filas y **eso es correcto**: ninguna de las 8 tenencias de la cuenta 2 tuvo ex-date entre el
  2026-09-25 y el 2026-09-27 (el último, AVGO, fue el 09-21 y se compró ese mismo día, después del
  ex). El calendario de esas 8 se refrescó en el scan del 2026-09-28 00:41 UTC, así que el warm-up
  corre.
- `barrier_eval`: *«scan ~15 min»* coincide con `paper_scan_interval_minutes = 15`.
- `adv_cap`, `vol_overlay`, `earnings_blackout`, `atr_*`: sin contradicción con el código ni con
  los valores vivos.

**Dirección 2 (lo verdadero no está escrito)**, recorriendo `run_scan` gate por gate:

- Gates 1, 2, 3 (horario, holding mínimo, anti-flap): intradía, clasificados `NO_MODELABLE`.
- Gate 2b: lo modela el harness; el defecto es de espejo ([D-2]).
- Gates 3b, 4, 5, 5b, 6: declarados, o inertes y clasificados.
- E5 (`_price_out_of_band`) y segunda opinión: [D-1].
- Dividendos a caja: declarado.
- Fuera de la segunda opinión de [D-1] (hoy OFF), **no aparece ninguna conducta del motor** que
  mueva órdenes, precio, tamaño o caja sin clave.

**[D-veredicto]:** el texto de `dividendos` conserva el número viejo *«para leer cualquier veredicto
publicado antes de esa fecha»*, y no hay veredicto publicado después del 2026-09-25. Limpio.

---

## 5. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [D-1] población del guard 185 enumerada por archivo; 6 perillas afuera, segunda opinión con encendido pendiente | MEDIA | **231** |
| [D-2] `min_age_bdays` mal clasificada + literales en `ScaleOutParams` que no leen los espejos | MEDIA | **232** |
| [D-3] `universe_screen` afirma la pata de ADV$, apagada en vivo | BAJA-MEDIA | **233** |
| [D-4] comentario de dividendos anterior a la 222 + conteo «0 de 62» sin fecha | BAJA | **233** (en el enunciado) |

---

## 6. Deuda de método

**[D-3] y el punto (2) de [D-4] son (c-metodo), con la misma raíz.** La corrida anterior contrastó
cada texto de desvío **contra el código**, y eso no puede ver un texto que el código respalda pero
que el **valor vivo** de una sub-perilla desmiente, ni un conteo vivo embebido sin fecha. Lo que le
faltaba al método, y entra a la skill con la tarea 233: *para [D-texto], toda afirmación de un
desvío sobre lo que hace el motor se contrasta contra el valor vivo de **cada** perilla que la
gobierna, no sólo contra el código; y todo número que el texto presenta como estado actual lleva
fecha o se deriva.*

**[D-1] y [D-2] son (a)**, pero dejan una lección de guards que conviene escribir: el guard de la
185 descubre las **claves** y enumera los **archivos**; y su tabla de excepciones acepta un motivo
(*«ya lo declara la clave X»*) sin comprobar que la clave X lo nombre. Es la forma de
[[cross-check-por-substring-acepta-lo-contrario]] un nivel más arriba: el motivo es texto libre y
nadie lo compara con el objeto que cita.
