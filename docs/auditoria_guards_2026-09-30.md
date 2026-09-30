# Auditoría READ-ONLY — área `guards` — 2026-09-30

Cuarta corrida de la **tanda del 2026-09-30**. Área: **guards que degradan en silencio, que no
pueden ver lo que describen, o que rechazan el dato bueno**. Corrida anterior de esta área:
`docs/auditoria_guards_2026-09-11.md` (dejó la 185, compartida con `desvios`, cerrada).

---

## 1. Kill-criteria — CONGELADO 2026-09-30, antes de abrir ningún archivo

> Congelado **junto con los otros cuatro** de la tanda y antes de empezar ninguna corrida.

### 1.1 Por qué ahora

Desde el 2026-09-11 entraron **más guards que en cualquier período anterior**, y varios de ellos
declaran en su docstring lo que **no** ven:

- el **cortafuegos de red** de la suite (209, 211, 213) — declara dos puntos ciegos (hijos sin
  `site.py`, DNS);
- el guard de **cola del backlog** (195), el de **constante de cuenta usada** (229), el de **inicio
  de la serie de SPY** (225), el **barrido AST de fetch en sesión** (238, *«el barrido es léxico»*),
  el de **archivos del 185** (231), la **ventana del guard de valores vivos** (214);
- los guards **de datos en vivo**: segunda opinión por mayoría (200/201/206), cache que no se puede
  escribir (234), y la salud de fuentes del harvest (207, 210, 217).

La skill dice que **un punto ciego declarado y no cerrado es un hallazgo**. Nunca hubo tantos
declarados a la vez.

### 1.2 Qué se busca — una frase por sub-categoría

- **[G-mudo]** Un guard cuyo fallo no llega a nadie: `except` que traga, fail-open sin log, aviso
  que no escala si se repite.
- **[G-ciego]** Un guard que **no puede ver** el defecto que describe: compara el nombre en vez del
  valor, o su población no contiene el caso distinguidor. **Se prueba mutando en el sentido del
  falso positivo**, no leyendo.
- **[G-inerte]** Un guard declarado y no cableado a nada que corra.
- **[G-bueno]** Un guard que puede estar rechazando el **dato bueno** (foco: *«sin mayoría»* de
  la 206 deja al scan sin precio).
- **[G-puntoCiego]** Un punto ciego **declarado** en un docstring, sin tarea que lo cierre ni
  argumento escrito de por qué no hace falta.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. Bugs de código y re-correr harness.
2. Si el **umbral** de un guard de trading es el correcto (decisión con backtest).
3. Las otras cuatro áreas; los guards de la UI.

### 1.4 Qué contaría como "acá no hay nada" — en las DOS direcciones

**Dirección 1 — lo escrito es falso.** Todo guard barrido hace lo que su docstring dice: una
mutación en el sentido del falso positivo lo pone rojo, y quien falla se entera (se puede nombrar).

**Dirección 2 — lo verdadero no está escrito.** Todo punto ciego **real** de los guards barridos
está declarado en su docstring **y** tiene tarea o argumento de por qué no hace falta.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Mismo protocolo. **Revisión de exclusiones:** el pipeline de catalysts estuvo **fuera de alcance**
en las dos corridas anteriores de esta área; desde entonces ganó cuatro guards de salud (207, 210,
212, 217), así que esta vez **entra**.

### 1.6 Alcance — qué se mira

1. `tests/conftest.py` y `tests/_cortafuegos/` — los cinco aislamientos.
2. `scripts/check_backlog_integrity.py` (con la cola de la 195).
3. Los guards de test nuevos desde el 2026-09-11: 185/231, 214, 225, 229, 238.
4. Guards de datos vivos: `data/yahoo_finance.py` (E5, segunda opinión, cache 234),
   `data/providers.py`.
5. Guards de salud del harvest: `scripts/harvest_catalysts.py` y lo que lo alimenta.
6. El cableado: `.claude/commands/ship.md`, `.github/workflows/`.

### 1.7 Alcance — qué NO se mira, dicho antes

- Los guards de la UI.
- Los asserts internos de tests que no son invariantes vivos.
- Los guards anteriores al 2026-09-11 que la corrida pasada ya barrió, salvo que un commit
  posterior los tocó.

---

## 2. Alcance real

**Mirado:** `tests/conftest.py` (los siete fixtures autouse y los aislamientos por variable de
entorno); los tres guards de corpus (`test_corpus_operativo_t72.py`,
`test_corpus_valores_vivos_t137.py`, `test_corpus_cuenta_y_killonly_t198.py`); el barrido de la 238
**re-corrido con una lista de fetch ampliada**; la segunda opinión de punta a punta
(`data/providers.py:300-453`, `data/yahoo_finance.py:990-1215`, `paper_trading/engine.py:1625-1740`);
la salud del harvest (207/210/217) y a dónde llega; el guard de la 214 (commit `26ce67d`); el guard
del inicio de SPY (225); las últimas 12 corridas del CI (API pública de Actions: **las 12 en
verde**); el log vivo `~/.finanzias/finanzias.log` (desde el 2026-09-07).

**NO mirado, y queda declarado:** los guards de la UI; `scripts/check_backlog_integrity.py` y
`scripts/check_repo_health.py` por dentro (no los tocó ningún commit posterior al 2026-09-11 salvo la
195, que tiene su propio barrido de mutación); el guard de valores vivos más allá del commit de la
214.

**Validación de los instrumentos.**
- **Barrido de la 238 ampliado:** se importaron las funciones del propio guard y sólo se cambió
  `_FETCH`. Contraprueba: con la lista original da **exactamente** lo que da el guard (`run_scan` y
  `approve_order`, las dos excepciones).
- **Corpus de la 198 sobre `DB_SCHEMA.md`:** se aplicaron `cuentas_que_no_son_la_viva` y
  `parrafos_killonly_sin_fuente` del propio guard, sin copiarlas.
- **Segunda opinión sin keys:** corrida con `TIINGO_API_KEY`/`FINNHUB_API_KEY` borradas del entorno.
  Sin key, las dos funciones retornan **antes** del request, así que no salió a la red.

**Fase adversarial: PROPIA, no independiente.** Ningún hallazgo llegó a HIGH. Ángulos probados en
[G-2]: un anuncio al arrancar de qué fuentes tienen key (no hay: `QUOTE_SOURCES` sólo se usa en
`data/providers.py`), un test que fije el aviso (los tests de la 206 borran las keys y verifican el
**veredicto**, no el log).

---

## 3. Hallazgos

### [G-1] Los tres guards de corpus enumeran su corpus con una lista literal, y ninguna incluye `DB_SCHEMA.md`

Severidad: **MEDIA** · Confianza: ALTA · Categoría: [G-ciego] (población)
Ubicación: `tests/test_corpus_operativo_t72.py:33-37`, `tests/test_corpus_valores_vivos_t137.py:67-71`,
`tests/test_corpus_cuenta_y_killonly_t198.py:41-46`

**Evidencia.** Tres listas escritas a mano, las tres distintas: la 72 y la 137 son `CLAUDE.md` +
`.claude/**/*.md` + `SETTINGS_REFERENCE.md` (la 137 dice *«igual que en la 72»*: es una copia); la
198 suma `ARCHITECTURE.md`. `CLAUDE.md` declara **cuatro** docs de referencia, y
`tests/test_claude_md_completo_t136.py:78` ya los tiene en una lista; `DB_SCHEMA.md` no está en
ningún corpus. Aplicando las funciones de la 198 a ese archivo, **los dos chequeos** lo marcan
(ver `docs/auditoria_claims_2026-09-30.md` [C-1]).

**Razonamiento.** Es la forma de la 231 un nivel más arriba: el guard descubre las **frases** y
enumera los **archivos**. Y es más fina que eso, porque el test de parseo de la 198 usa como
ejemplo, **textual**, la línea que no puede ver.

**Mutación en el sentido del falso positivo.** La afirmación falsa existe hoy en el repo y el guard
está verde: la mutación ya la hizo el repo.

**¿Por qué no antes? (a) NO EXISTÍA** para la 198 (2026-09-13). Para la 72 y la 137 la población ya
estaba así el 2026-09-11, pero sus criterios (constantes inexistentes, números en presente) no
habrían marcado esta línea: el defecto se volvió visible con el criterio de la 198.

**Acción.** Un corpus **único**, compartido por los tres guards y derivado de lo que `CLAUDE.md`
declara como referencia (o del `test_claude_md_completo_t136`), con un test que falle si
`CLAUDE.md` nombra un doc de referencia que el corpus no lee.

### [G-2] La regla de tres fuentes se degrada EN SILENCIO: sin keys, el caso KLAC pasa sin una línea de log

Severidad: **MEDIA** (latente: el flag está OFF y su encendido está pendiente) · Confianza: ALTA ·
Categoría: [G-mudo]
Ubicación: `data/providers.py:319-321` y `:346-348`; `data/yahoo_finance.py:1039-1052`

**Evidencia.** `second_opinion()` y `tiingo_quote()` devuelven `None` **sin log** cuando falta la
key. Reproducción (entorno sin las dos keys, sin red): `second_opinions("KLAC")` →
`{'finnhub': None, 'tiingo': None}`, `arbitrate_votes(4000.0, 400.0, …)` → `('sin_opinion', None)`,
y **cero** registros de log. `sin_opinion` es *«el guard queda como estaba»*: el precio ×10 se
acepta. Con **una** sola key la regla cae a la de dos fuentes, también sin decirlo. Y
`_arbitrate_price` convierte **cualquier** excepción de la regla en `sin_opinion` con un `except`
sin log (`data/yahoo_finance.py:1051-1052`).

**Razonamiento.** Con el flag ON, la feature puede estar **inerte** —en todo o en la mitad— y nada
lo distingue de *«no hubo disputa»*. Es la forma exacta que la **217** le sacó al harvest (*«una
fuente caída de RAÍZ deja de ser invisible»*: sin `FINNHUB_API_KEY` se iba el 56,6% de
`news_events`), en el camino de **precios**, donde el costo es un fill.

**Impacto.** El día que Chapa prenda el flag, si la app arranca desde un entorno sin
`TIINGO_API_KEY` (un acceso directo, un servicio, la Pi de la 196), la regla que decidió no corre y
el aviso de *Acciones manuales* le promete que sí. El registro de la opinión (`_record_opinion`)
guarda `tiingo: None` igual que si Tiingo no hubiera contestado.

**¿Por qué no antes? (a) NO EXISTÍA** — la regla de tres es de la 206 (2026-09-28).

**Acción.** Antes de prender el flag: con `price_second_opinion_enabled` ON, avisar **una vez por
proceso** qué fuentes no tienen key (el `unavailable` de la 217) y loguear la excepción de
`_arbitrate_price`. Va en la misma tarea que [C-3] de `claims`.

### [G-3] La salud del harvest escala hasta un WARNING en un log que tiene 2.215, y el 68% es un aviso esperado

Severidad: **MEDIA-BAJA** · Confianza: ALTA · Categoría: [G-mudo]
Ubicación: `scripts/harvest_catalysts.py` (el resumen), `paper_trading/scheduler.py:804-808`

**Evidencia.** La 207/210/217 hicieron que una corrida con fuentes caídas salga a `WARNING` con
`FUENTES CAIDAS` o `FUENTE NO DISPONIBLE`. Ahí termina: el scheduler loguea `harvest_rc` a `INFO`, y
el Slack de outage (`integrations/slack.py:200`) es sólo para los precios de Yahoo (NET1). En el log
vivo (desde el 2026-09-07) hay **2.215** WARNING; **uno** es del harvest —el del 2026-09-21 21:09,
*«fuentes 0/4 limpias»*, `yfinance_news` caída en 121 de 127— y **1.506** (68%) son el aviso de
barra provisional de la tarea 112, que sale **132 veces por cada arranque en horario de mercado**
(`data/yahoo_finance.py:1809-1821`: una vez por ticker y por proceso, que en la práctica es por
arranque).

**Razonamiento.** El 2026-08-31 la tarea 63 fue *«927 WARNINGs en 4 días y nadie miró»*. Acá el
aviso que importa es 1 entre 2.215. La 196 va a mudar el harvest a una Pi sin nadie mirando su log.

**¿Por qué no antes? (b) FUERA DE ALCANCE** — el pipeline de catalysts quedó afuera en las dos
corridas anteriores de esta área. La exclusión ya no era razonable desde la 207 (2026-09-15), que le
dio al harvest un guard propio.

**Acción.** Decidir (Chapa) si la salud del harvest va al Slack de outage, y si el aviso de barra
provisional baja a `INFO` o se agrega por arranque en una línea. Emparenta con la 196.

---

## 4. Barrido limpio en el resto del área — las dos direcciones

**Dirección 1 (lo escrito es falso).**
- **238:** con la lista de fetch ampliada de 8 a 29 nombres (todas las funciones públicas de
  `data/` que tocan red), el barrido da **las mismas dos excepciones con los mismos fetch**. Su
  punto ciego declarado (*«un fetch detrás de un helper que no esté en `_FETCH`»*) no tiene caso
  hoy. Limpio.
- **214:** el umbral está medido contra la población (separación 36×) y fijado por los dos lados con
  mutación. Limpio.
- **225:** el guard del inicio de SPY apaga el número y lo dice (`benchmark_aviso`); su vencimiento
  es de `muestra` ([M-1] de ese informe).
- **CI:** 12 de 12 en verde, sobre los commits del 2026-09-25 al 2026-09-28.

**Dirección 2 (lo verdadero no está escrito).** Puntos ciegos declarados de los guards nuevos:
- cortafuegos de red — hijos sin `site.py` y DNS: declarados **con argumento** (bloquear
  `getaddrinfo` se lleva `localhost`). No es un hallazgo.
- 238 — el helper fuera de la lista: declarado con argumento y, medido, sin caso.
- 198 — *«una cuenta afirmada con otra forma no se parsea»*: declarado. **Lo que no declara es que
  su corpus es una lista** — eso es [G-1].

---

## 5. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [G-1] los tres corpus son listas literales sin `DB_SCHEMA.md` | MEDIA | **239** (con claims [C-1]) |
| [G-2] la regla de tres se degrada en silencio sin keys | MEDIA | **241** (con claims [C-3]) |
| [G-3] la salud del harvest termina en un WARNING enterrado | MEDIA-BAJA | **243** |

---

## 6. Deuda de método

Ningún (c-metodo) en esta área. El (b) de [G-3] **sí** es una lección sobre exclusiones: el catalyst
pipeline se excluyó el 2026-09-08 y el 2026-09-11 con razón (no tenía guards propios), y la razón
caducó el 2026-09-15 sin que nada la re-mirara. *Una exclusión de alcance lleva su motivo, y el
motivo se re-verifica en la corrida siguiente* — no alcanza con copiarla.
