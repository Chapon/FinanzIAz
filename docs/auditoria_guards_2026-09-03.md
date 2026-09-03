# Auditoría `guards` — 2026-09-03

**Quinta corrida de `/audit`, y la última de las cinco áreas.** READ-ONLY: no se modificó
código, config, esquema ni tests. Commit base `544b2fb`. Suite corrida por el verificador
como control: **2608 passed, 3 skipped** en Windows (`.venv`), sin cambios en el árbol.

Áreas previas: `claims` (2026-09-01), `estado`, `muestra` y `desvios` (2026-09-02).

---

## 1. Kill-criteria — congelado ANTES de abrir un archivo

**Área.** Todo chequeo **defensivo**: guards de datos (escala, split, staleness, cache),
guards de reproducción de los harness (`reproduction_check`, `ArtifactPopulation`,
`announce_artifacts`, cobertura PIT), guards de proceso (`check_backlog_integrity`, hooks de
pre-commit) y guards del engine (los 6 gates, whipsaw, breaker), más el manejo de excepciones
que los envuelve.

**Qué se busca**, una frase por sub-categoría:

1. **Fail-open mudo** — ante error o dato faltante deja pasar y no loguea, o loguea donde nadie mira.
2. **Rechaza el dato bueno** — la pregunta que destapó la 63: ¿el criterio puede marcar como corrupto un dato sano, y qué cuesta?
3. **`except` que traga** — captura y devuelve un default **indistinguible** del caso legítimo.
4. **Aviso que no escala** — un WARNING que se repite 927 veces sin cambiar de nivel.
5. **Cableado a medias** — guard escrito en un consumidor y ausente en sus hermanos (familia 76/84/86/90).
6. **Se auto-satisface** — el criterio de éxito es una constante que el propio código puede mover, o compara algo contra sí mismo.

**Fuera de alcance, declarado.** Bugs de código en general (suite, CI, `/code-review`); las
otras cuatro áreas (si aparece uno de refilón se anota, no se barre); seguridad, performance,
dead code, dependencias; la GUI salvo donde un guard decide mostrar o no un dato.

**Condición de barrido limpio.** Que para **cada** guard alcanzado se puedan contestar las
tres preguntas — (a) cuando falla, ¿queda registro donde alguien mira?; (b) ¿puede rechazar el
dato bueno, y a qué costo?; (c) ¿está cableado en todos los consumidores de su familia? — y
que **ninguna** respuesta sea "no" con costo concreto. Un `except` amplio que loguea y
re-lanza **no** es hallazgo. Un default enmascarante que igual queda declarado en el banner
**no** es hallazgo.

**El barrido NO salió limpio: diez hallazgos, uno HIGH.**

---

## 2. Alcance

**Mirado.** Los 81 `except` amplios/desnudos **silenciosos** de `analysis/`, `data/`,
`paper_trading/`, `scripts/`, `database/`, `alerts/`, `integrations/` y `config/`, más los 33
de `ui/`, barridos con **AST** y no con grep (un handler cuenta como silencioso si no llama a
nada con pinta de log ni re-lanza). Los guards de `analysis/harness_config.py` uno por uno.
Los 6 gates de `paper_trading/engine.py` en su camino de "sin dato". El guard E5 de precios y
el breaker de throttle de `data/yahoo_finance.py`. `scripts/check_backlog_integrity.py` y su
cableado real. El cableado de `announce_artifacts` / `announce_signal_store` sobre los 32
`run_*.py` y sobre los otros lectores del cohorte. El log de producción del 2026-09-02 12:48
en adelante.

**NO mirado, y queda dicho.** Los ~281 `except` **no amplios** (con tipo declarado).
`alembic/` y las migraciones. El interior de `technical.py`, `ml_signals.py` y
`garch_signals.py` más allá del warning de inestabilidad. Si `ml_probability` llega a una
decisión viva. `_lock_exclusive` bajo contención real en Windows (leído, no ejercitado).
`integrations/slack.py` más allá de un vistazo. Las otras cuatro áreas.

---

## 3. Hallazgos

### [G-1] En este repo NO corre ningún hook de git, así que la mitad `--staged` del guard de la 66 nunca se ejecutó

**Severidad: HIGH · Confianza: ALTA · Categoría: guard cableado a medias**

**Ubicación.** `.git/hooks/` · `.pre-commit-config.yaml:26-42` · `tests/test_backlog_integrity.py:153` · `CLAUDE.md:34` · `docs/BACKLOG.md:9`, `:295`, `:935`

**Evidencia.**

- `ls -la .git/hooks/` → **sólo 14 archivos `.sample`**. No existe `.git/hooks/pre-commit`.
- `git config --get core.hooksPath` vacío en `--local`, `--global` **y** `--system`. `git rev-parse --git-path hooks` → `.git/hooks`. `git worktree list` → un solo worktree.
- `pre-commit` **sí** está instalado como paquete (`.venv/Scripts/pre-commit.EXE`); lo que nunca se corrió es `pre-commit install` — y ese paso no está escrito en **ningún** `.md` del repo, ni en *Acciones manuales pendientes*.
- No hay `Makefile`, `justfile`, `noxfile`, `tox.ini`, husky ni alias de git que lo invoque.
- `.github/workflows/ci.yml` tiene 4 jobs (`lint`, `typecheck`, `audit`, `tests`) y **ninguno corre `pre-commit`**.
- `/ship`, que es como se commitea acá de verdad, corre `python scripts/check_repo_health.py --staged` (`.claude/commands/ship.md:11`) — **otro** guard, no éste.
- El escape hatch documentado (`pre-commit run --all-files`) **tampoco** puede disparar la mitad del shrink: no stagea nada, y `check_staged_shrink` lee `git diff --cached --numstat`, que con el índice vacío devuelve `[]` en silencio.
- `tests/test_backlog_integrity.py:153` `test_the_precommit_hook_is_wired` sólo hace `assert "check_backlog_integrity.py --staged" in cfg` **sobre el texto del YAML**.
- Y la parte que faltaba: **la lógica de `check_staged_shrink` no tiene ni un test.** El único que la toca (`:140`) assertea el **fail-open** fuera de un repo; el otro (`:146`) assertea `0 < MAX_LINES_LOST < 767`, una propiedad de la **constante**. El parseo del `--numstat`, la resta `borradas - agregadas` y la comparación contra el umbral no están cubiertos por nada.

**Razonamiento.** El guard de la 66 tiene dos mitades. La que se puede ver leyendo el archivo
(secciones, punteros) corre en la suite y por lo tanto en el CI: **esa funciona**. La que
necesita el diff —*«este commit le saca N líneas»*, que es **la que habría frenado el commit
que motivó la tarea entera**— vive sólo en un hook que no está instalado, y no existe ningún
camino en el repo, automático ni manual, que la ejercite. El test que se escribió justamente
para fijar el cableado verifica **la declaración** (el YAML), no **la condición que hace que
el hook corra** (el archivo en `.git/hooks/`). Su propio docstring dice *"si el instrumento
existe y no lo llama nadie, el archivo se sigue pudiendo vaciar"* — que es, literalmente, el
estado actual.

**Impacto.** Un commit que le saque 767 líneas al backlog pasa igual que el 2026-08-31. Y
tres documentos —`CLAUDE.md:34`, el header del backlog y la retro de cierre— lo afirman **en
presente indicativo**: *"frena un commit que le saque más de 60 líneas netas"*. La lectura
caritativa ("corre en pre-commit" = "está declarado en la config") se muere en la misma
oración, porque lo que sigue es una afirmación sobre conducta de bloqueo.

**De paso, la misma cuadra:** con el hook sin instalar tampoco corren `debug-statements`,
`check-added-large-files --maxkb=500`, `check-merge-conflict`, `trailing-whitespace`,
`end-of-file-fixer`, `check-yaml/toml/json`. Los de `ruff` **sí** están replicados en el CI;
estos no corren en ningún lado. Y `debug-statements` **no tiene sustituto**: el `select` de
ruff en `pyproject.toml:52` es `["E","W","F","I","B","UP","SIM","RUF"]`, sin `T10`
(flake8-debugger), así que un `breakpoint()` commiteado no lo caza nada.

**Verificación (qué se intentó para refutarlo).** Se buscó un `core.hooksPath` en los tres
niveles, otro worktree, un wrapper de commit, un alias, husky, un caller en el CI, un test que
ejercite la función contra un índice real, y una lectura de `CLAUDE.md` bajo la cual el claim
sea cierto. **Ninguna abre.** El grep de `check_backlog_integrity` en todo el repo devuelve 8
hits: el YAML, `CLAUDE.md`, tres del backlog, el propio script y dos del test. Cero
invocaciones operativas.

**Acción.** Correr `pre-commit install` (y anotarlo donde se lee al montar el entorno);
cambiar el test para que verifique el **hook instalado** y no el YAML; y cubrir la lógica de
`check_staged_shrink` con un test contra un índice real.

---

### [G-2] `check_repo_health.py` —el guard de las reglas 4 y 5 de CLAUDE.md— no está cableado a nada automático, y una skill lo llama "Guard automático"

**Severidad: MEDIA-ALTA · Confianza: ALTA · Categoría: guard cableado a medias + claim caducado**

**Ubicación.** `scripts/check_repo_health.py` · `.claude/commands/ship.md:11` · `.claude/skills/finanzias-conventions/SKILL.md:34`

**Evidencia.** No aparece en `.pre-commit-config.yaml` **en absoluto**, no está en `ci.yml`, y
no lo llama ningún test. Su único invocador es una **instrucción de prompt**
(`.claude/commands/ship.md:11`). Su propio docstring dice *"Pensado para correr a mano **o como
hook pre-commit**"*, y no está registrado como hook. `finanzias-conventions/SKILL.md:34` lo
llama **"Guard automático"**.

**Razonamiento.** Es peor que G-1 por un escalón: G-1 tiene el hook declarado en el YAML y le
falta la instalación; éste no está declarado en ningún lado. Lo que protege son las reglas
**4** (`.bat` sin CRLF ⇒ `cmd.exe` los mata en silencio) y **5** (no escribir `finanzias.db`
desde Linux/sandbox ⇒ corrupción intermitente) — las dos no-negociables, las dos con modo de
falla silencioso.

**Impacto.** La protección de dos reglas no-negociables depende de que el agente se acuerde
del paso 3a de `/ship`. Y la skill que se lee al empezar cualquier tarea dice que es
automático, o sea que dirige activamente a **no** verificarlo.

**Verificación.** Se corrió: sin problemas sobre 2714 archivos. El guard funciona; lo que no
existe es su cableado.

**Acción.** Decidir dónde va (hook, CI, o suite) y corregir el adjetivo de la skill.

---

### [G-3] Siete runners tienen `--account` con default en la cuenta PAUSADA, y no dan vacío: dan una tabla creíble sobre una cuenta muerta

**Severidad: MEDIA-ALTA · Confianza: ALTA · Categoría: default que enmascara**

**Ubicación.** `scripts/run_exit_replay_t61.py:238` · `scripts/run_atr_stop_recalib.py:203` · `scripts/run_catalyst_exit_veto_backtest.py:359` · `scripts/run_earnings_blackout_replay.py:202` · `scripts/run_exposure_cap_replay.py:126` · `scripts/run_risk_exit_autofill_replay.py:233` · `scripts/analyze_expired_buys_financing.py:169`

**Evidencia.** Los siete declaran `default=1`. Medido sobre la DB viva:

| cuenta | nombre | `is_active` | fills | último fill |
|---|---|---|---|---|
| 1 | Sim Principal | **0** | 91 | **2026-07-01 17:39** |
| 2 | Sim Segundo | 1 | 115 | **2026-09-03 20:58** |

**Razonamiento.** Es el defecto que cerró la **70** (*"todos los jobs de fondo apuntan a la
cuenta PAUSADA, y ninguno mira `is_active`"*), un directorio más allá: la 70 arregló el
harvest y los jobs de fondo, y estos siete quedaron afuera. La forma peligrosa es que la
cuenta 1 **no está vacía**: tiene 91 fills reales, así que ninguno de los siete falla ni avisa
— producen un replay completo y plausible de una cuenta que dejó de operar hace dos meses.

**Impacto.** Cualquiera de esos siete corrido sin `--account 2` mide la cuenta equivocada, en
silencio. `run_exit_replay_t61.py` es el caso vivo: se tocó hace seis commits (T92) y su
default sigue en 1.

**Verificación.** Se confirmó que no hay ninguna resolución por `is_active` en esos scripts y
que la 70 no los tocó.

**Acción.** El mismo patrón que la 70: resolver el default contra `is_active`.

---

### [G-4] La tarea 87 borró la única comparación viva de `n_tickers`, y dejó falsa su propia justificación — una corrida sobre 98 de 127 tickers se declara "mismo universo"

**Severidad: MEDIA · Confianza: ALTA · Categoría: guard que se auto-satisface**

**Ubicación.** `analysis/harness_config.py:663-665` (`same_universe_as`) · `:707` (docstring de `universe_fingerprint`) · `:915-930` (`HarnessConfig.population`) · `:1621-1622` (anclas)

**Lo que NO es el hallazgo, y por qué.** Que la huella sea del **archivo** de universo y no
del conjunto que cargó **no es un defecto**: es una decisión deliberada, documentada en
`universe_fingerprint` con las dos alternativas descartadas, y **fijada por un test**
(`tests/test_poblacion_conjunto_t87.py:124`). Esa mitad se probó y **se cae**; se borra del
informe en vez de degradarse.

**Lo que sí sobrevive.** El corolario que la 87 no pagó. Al hacer que `same_universe_as` corte
por `tickers_fp`, **borró la única comparación de `n_tickers` que existía**, mientras que la
justificación escrita para elegir la semántica del archivo se apoya **explícitamente** en que
ese eje lo sigue llevando `n_tickers`:

> `analysis/harness_config.py:705` — *"…eso no es un cambio de universo, es un hipo. **El eje «qué cargó» ya lo lleva `n_tickers`, por separado.**"*

**Ese enunciado hoy es falso.** Los únicos dos sitios que comparan `n_tickers` son
`harness_config.py:665` —**inalcanzable en producción**, porque `HarnessConfig.population()`
siempre setea `tickers_fp` y las dos anclas compartidas lo traen hardcodeado— y
`deviations():964`, que sólo imprime.

**Evidencia, contra el ancla real que consumen los runners:**

```
HarnessConfig(10, LIVE_UNIVERSE_FILE, 98).population(90000)
    .same_universe_as(POPULATION_LIVE_ACCT2)          -> True     (el ancla declara 127)
reproduction_check(0.0347, 0.0347, tol=0.0005, ...)   -> ('OK', ...)
```

Con el código previo a la 87 (`git show 6eafd2f~1`, línea 578:
`self.universe_file == other.universe_file and self.n_tickers == other.n_tickers`) eso daba
`False` → **`REPRO_NA`**. Es un cambio de conducta real, introducido en `6eafd2f`.

**Impacto, en dos escalones.** El frecuente: cuando el número **no** reproduce, la corrida
encogida sale `INDETERMINADO` afirmando literalmente *"mismo universo"* sobre una muestra de
98 de 127 — se perdió el estado honesto que existía antes (`NO APLICA — re-medí la referencia
sobre esta población`). El agudo: cuando el número **sí** entra en `tol` —y `tol=0.0005` de
CAGR es holgado para la merma de un puñado de tickers, que es justo el "hipo de carga" que
invoca el docstring— sale **`REPRO_OK`**, o sea que una corrida sobre otra muestra se certifica
como reproducida. Y el repo ya rechazó por escrito el argumento de "es coincidencia":
`tests/test_harness_config.py:562`, `test_not_applicable_wins_over_a_number_that_happens_to_match`
— *"que el número coincida es coincidencia: sigue sin haber reproducción que reportar"*. En
`reproduction_check` el chequeo de NA está **antes** de la comparación contra `tol`
exactamente por eso; la 87 le sacó ese veto al eje del conteo.

**Lo que NO se afirma** (se probó y no se sostiene): que una corrida encogida salga `FALLA`
acusando a la cañería. Lo bloquea la precondición `entradas_comparables` de la otra mitad de
la 87, porque las anclas compartidas no declaran `n_entries`. Verificado.

**Por qué `deviations()` no alcanza como mitigación.** No es que "sólo imprime": es que **ya
dispara en toda corrida sana**. El archivo de universo tiene **127** tickers y
`LIVE_WATCHLIST_SIZE = 128`, porque **ASML** está en la watchlist viva y no en el archivo. Una
corrida sana ya imprime *"universo 127 tickers vs 128 de la watchlist viva"*; una encogida a
98 imprime **la misma línea con otro número**. La línea no discrimina sano de encogido.

**Por qué no lo atrapa ningún otro guard.** `announce_artifacts` y `announce_signal_store`
abortan (`strict=True` por default), pero los dos iteran `bars_by.items()`: **un ticker que no
cargó no es una clave, así que no existe para ellos**. Lo único que ve el encogimiento es el
`print` a stderr del loader (*"AVISO: N tickers sin señal/barras"*), sin abort — y tres líneas
después `announce()` declara el conteo encogido como el universo de la corrida.

**Y no hay ningún test que lo cubra.** No existe un solo caso de *"mismo archivo, distinto
`n_tickers`"*. Los tests de la 52 que assertean NA comparan **archivos distintos** (saldría NA
bajo cualquier versión) y **ninguna de las dos poblaciones declara `tickers_fp`**, así que
ejercitan la rama de fallback que producción nunca toma. Por eso la regresión entró silenciosa
en un commit que sumó 22 tests.

**Acción.** Que `same_universe_as` compare **las dos cosas** cuando las dos están disponibles
(huella **y** conteo), en vez de que la huella reemplace al conteo; y un test de "mismo
archivo, distinto `n_tickers`".

---

### [G-5] El guard de frescura del cohorte se cableó por PREFIJO DE NOMBRE, y quedaron afuera los cuatro `measure_*` — incluido el que produjo el número de la regla 3 de CLAUDE.md

**Severidad: MEDIA · Confianza: ALTA · Categoría: guard cableado a medias**

**Ubicación.** `scripts/measure_buyscore_fwd5_t73.py:57` · `scripts/measure_sell_bias_t31.py:55` · `scripts/measure_garch_fragil_t67.py:80` · `scripts/measure_garch_intraday_t29.py:75`

**Evidencia.** Barrido por AST sobre `scripts/`: los `run_*.py` que leen el cohorte son **21 de
32** y **los 21** llaman `announce_artifacts` — el número de la 76 reproduce exacto. Pero
además del prefijo `run_` hay **siete** lectores del mismo cohorte, y ninguno lo chequea:

| script | qué es | ¿en alcance? |
|---|---|---|
| `measure_buyscore_fwd5_t73.py` | instrumento de `docs/buyscore_fwd5_t73_2026-09-01.md`, citado por **CLAUDE.md regla 3** | **sí** |
| `measure_sell_bias_t31.py` | instrumento de `docs/sell_bias_t31_2026-09-01.md` | **sí** |
| `measure_garch_fragil_t67.py` | instrumento de `docs/garch_fragil_t67_2026-09-01.md` | **sí** |
| `measure_garch_intraday_t29.py` | instrumento de `docs/garch_intraday_t29_2026-09-01.md` | **sí** |
| `precompute_pit_signals.py`, `precompute_pit_risk_score.py` | **productores** del store | no — son los que arreglan el cohorte |
| `benchmark_historical_cache.py` | mide costo de I/O por backend | no — no produce un número de trading |

Los cuatro leen con `ttl_hours=None`, o sea sin ningún chequeo de frescura, y ninguno declara
su ventana (lo que la 83 cableó a los 21).

**Razonamiento.** La 76 cerró con este argumento, textual: *"el `announce_artifacts` de la 30
es sobre el **sustrato compartido**: los runners leen **el mismo cohorte de artefactos**. Un
guard de sustrato cableado en 1 de 32 no protege nada; sólo hace creer que sí."* El argumento
es correcto y la población se eligió por `run_*.py`, que es una **convención de nombre**, no
la propiedad que al guard le importa (*"lee el cohorte compartido"*).

**Impacto.** El número que sostiene una regla **no-negociable** de `CLAUDE.md`
(`corr(buy_score, fwd5) = −0.05`, n=85) se midió con un instrumento que no chequea si el
cohorte estaba alineado — que es exactamente la condición que la 30 declaró que invalida una
corrida entera.

**Medido, y esto acota el hallazgo:** corrí `stale_artifacts` sobre el cohorte `2y` de los 127
tickers del universo vivo. **0 desalineados**, `cohort_end = 2026-09-03`, con AVB como la única
excepción declarada (8 ruedas atrás, `ARTIFACT_REFRESH_EXCEPTIONS`). **Ningún número publicado
está contaminado.** Lo que falta es el guard, no está mal el número — y nadie lo sabía hasta
que se midió acá a mano.

**Acción.** Cablear `announce_artifacts` a los cuatro `measure_*`, y cambiar el criterio de la
lista de "empieza con `run_`" a "lee el cohorte", dejando escrito por qué los `precompute_*` y
el benchmark quedan afuera.

---

### [G-6] `run_exit_replay_t61.py` lee de una tabla con CERO filas, y el contador que lo diría se calcula y no se imprime

**Severidad: MEDIA · Confianza: ALTA · Categoría: fail-open mudo**

**Ubicación.** `scripts/run_exit_replay_t61.py:76-107` (`make_bar_loader`) · `:215-230` (`render_table`) · `:72` (`_atr_params_from_settings`) · `analysis/exit_replay.py:529`, `:644`

**Evidencia.** Tres cosas, apiladas:

1. `make_bar_loader` lee **exclusivamente** de `historical_data_cache`, y esa tabla tiene **0 filas** (medido sobre la DB viva; el backend vivo es `parquet`). Todo lookup devuelve `None`, y el `except Exception: bars = None` de `:103` mete cualquier otro fallo en el mismo cubo.
2. `simulate_variant` cuenta los eventos salteados por falta de datos en `ReplayReport.n_skipped_no_data` (`analysis/exit_replay.py:529`, poblado en `:644`) — y ese campo **no aparece en `render_table`**. Las columnas son `mod`, `ΔP/L $`, `ΔP/L pts`, `DD real`, `DD sim`, `ratio`, `extra ret`, `capture`, `PASS`.
3. `_atr_params_from_settings()` termina en `except Exception: return AtrParams()`, o sea el default **con stop duro encendido a 2.0×ATR** — el desvío que la 92 midió en **7,16 pp de CAGR** — en el único runner que la 92 describe como *"el que lee la config viva"*.

**Razonamiento.** Con la fuente vacía, la salida muestra `mod=0` y `Δ=0` en las cuatro
variantes, que se lee como *"la variante no cambia nada"*. El número que distingue **"no tuvo
efecto"** de **"no había datos"** existe, está calculado, y es el único que no se imprime.

**Impacto.** Un veredicto de exit-replay que dice "ninguna variante pasa el kill-criteria"
cuando lo que pasó es que no se evaluó ni un evento. Sumado a G-3, el mismo runner además
apunta por default a la cuenta pausada.

**Acción.** Imprimir `n_skipped_no_data` (y abortar si es el 100%); apuntar el loader al
backend vivo o declarar la dependencia; y que el fallback de `_atr_params_from_settings`
levante en vez de devolver el default que representa el desvío más caro medido.

---

### [G-7] El Gate 3b (cap por ADV) falla abierto sin dejar rastro, y el Gate 6 —200 líneas más arriba, en el mismo archivo— lo hace bien

**Severidad: MEDIA · Confianza: ALTA (latente) · Categoría: fail-open mudo**

**Ubicación.** `paper_trading/engine.py:915-921` (`_history_for`) · `:1120-1128` (Gate 3b) · `paper_trading/gates.py:532-563`, `:565-590`

**Evidencia.** `_history_for` devuelve `None` si el provider levanta (`except Exception`, sin
log). `recent_adv_dollars(None, …)` → `None`. `adv_capped_notional(target, None, cap_pct)` →
`(target, **False**)`. Y el call site sólo escribe una advertencia `if was_capped:`. O sea que
`was_capped=False` es **indistinguible** entre *"la orden entraba bajo el techo"* y *"no pude
medir la liquidez, así que no apliqué el gate"*. El cap está **encendido en vivo**:
`paper_adv_cap_pct = 0.05`, `paper_adv_lookback_days = 20`.

**El contraste que lo vuelve hallazgo y no estilo:** el Gate 6 (earnings), en el mismo scan y
el mismo archivo (`engine.py:899-908`), falla abierto y **lo dice**:
`log.warning("earnings gate: provider failed for %s — failing open (no block).")`. Y
`engine.py:786` hace lo propio para los precios faltantes (*"posiciones SIN evaluar (stops no
corridos)"*). El patrón correcto está escrito al lado.

**Impacto.** Una BUY a tamaño completo sobre un nombre cuya liquidez no se pudo medir —o sea,
justo los nombres más propensos a ser finos— sin ninguna huella de que el gate no corrió.
Después del hecho no hay forma de saber si el cap aplicó.

**Medido, y esto lo acota a latente:** sobre la watchlist viva (128 tickers) leyendo el cache
Parquet, `recent_adv_dollars` devuelve un valor para **128 de 128**. Hoy no está pasando.

**Acción.** Loguear el salto del gate con el mismo texto que el Gate 6, o devolver un tercer
estado que distinga "no capeado" de "no evaluado".

---

### [G-8] `_now_et()` cae a UTC en silencio, y su `except ImportError` no puede atrapar el fallo para el que se escribió

**Severidad: MEDIA · Confianza: ALTA (latente) · Categoría: default que enmascara**

**Ubicación.** `paper_trading/scheduler.py:95-107`, usado en `:448`

**Evidencia.** El fallback es `except Exception: return utcnow_naive()` — **sin log**. Y la
cadena de fallback está mal cableada: el fallo realista en Windows es que
`ZoneInfo("America/New_York")` no encuentre la base IANA, y eso levanta
`ZoneInfoNotFoundError`, que es subclase de **`KeyError`**, no de `ImportError` (verificado:
`ZoneInfo('Zona/Inexistente')` → `(ZoneInfoNotFoundError, KeyError, LookupError, Exception)`).
O sea que **la rama de `pytz` es inalcanzable** en ese escenario y se va directo a UTC.

**Impacto.** `_now_et()` decide el disparo del scan diario (`paper_daily_scan_time_et`, default
`16:05`). Con UTC, las 16:05 caen **12:05 ET**: el scan diario se dispararía en pleno mercado
en vez de después del cierre, y como `_last_daily_run` marca el día como hecho, el scan de las
16:05 ET **no correría**. Sin una línea de log que lo diga.

**Medido, y esto lo acota a latente:** los dos intérpretes que usa el proyecto resuelven bien
—`.venv` (tzdata 2026.2) y Anaconda (pytz 2024.1)— y `requirements.lock` pinea `tzdata` y
`pytz`. Hoy no está pasando.

**Acción.** Atrapar `ZoneInfoNotFoundError` en la rama de `pytz` y loguear el fallback a UTC en
WARNING.

---

### [G-9] `signal_store_gaps` saltea el ticker sin artefacto apoyándose en un comentario que es falso justo en el runner donde importa

**Severidad: BAJA-MEDIA · Confianza: ALTA · Categoría: `except`/skip justificado por un claim falso**

**Ubicación.** `analysis/harness_config.py:570` · `scripts/run_insider_cluster_replay_t12.py:161-197`, `:492`, `:513-517`

**Evidencia.** El guard saltea:

```python
if not cubiertas:
    continue  # sin artefacto: el loader ya lo excluye y lo reporta como `missing`
```

Y 20 líneas más abajo en el t12, el comentario de la **88** dice lo contrario, por escrito:
*"en este runner un ticker sin artefacto **no se excluye** —a diferencia de los otros loaders,
que lo mandan a `missing`— sino que corre **ATR-only en silencio**"*. Confirmado en
`load_bars` (`:188-196`): el ticker entra a `bars_by` con `sigs_by[t] = {}`. Además,
`_load_existing` devuelve `{}` por **tres** causas distintas —archivo ausente, JSON ilegible y
`schema_version` distinta— y el guard las trata a las tres igual.

Y el mismo t12 relaja el guard con una condición extra que ningún otro runner tiene:
`strict=not args.allow_stale_artifacts and args.signals_mode == "analyze_flip"` (`:492`). El
default de `--signals-mode` **es** `analyze_flip`, así que en la práctica está estricto; pero
en cualquier otro modo el guard queda no-estricto **sin que nadie pase el flag**.

**Impacto acotado, y se dice.** Hoy no hay pérdida silenciosa: el t12 imprime *"N de M tickers
CON artefacto de señal utilizable; los otros K corren ATR-only"*, y los 127 del universo vivo
tienen artefacto `complete` (medido). Lo que está roto es el **razonamiento** que sostiene el
skip, y ése es el que hereda el próximo runner que se escriba mirando ese comentario — que es
exactamente cómo nacieron la 84 y la 90.

**Acción.** Corregir el comentario y decidir si el caso "sin artefacto" lo tiene que ver el
guard en vez de delegarlo.

---

### [G-10] Tres docstrings de `harness_config.py` dicen tres cosas distintas sobre qué mide `tickers_fp`

**Severidad: BAJA-MEDIA · Confianza: ALTA · Categoría: claim caducado dentro de un guard**

**Ubicación.** `analysis/harness_config.py:657` · `:742-746` · `:698-705` · `:751`

**Evidencia.**

- `:657` (`same_universe_as`): *"`tickers_fp` es la huella del **conjunto efectivo**"* — **falso**.
- `:742-746` (`artifact_population`): *"con `bars_by` se calcula además la huella del conjunto: es la de los tickers que **efectivamente cargaron**, no la del archivo"* — **falso**; el código de `:751` llama `universe_fingerprint(universe_file)` **ignorando `bars_by`** para la huella.
- `:698-705` (`universe_fingerprint`): dice lo contrario, y es lo que el código hace.

**Impacto.** Dos de las tres puntas mandan al próximo lector a arreglar la punta equivocada de
G-4. Y es reincidencia declarada: `tests/test_watchlist_size_t89.py:78` existe justamente para
fijar que *"lo que un chequeo no puede ver tiene que estar escrito al lado del código — si no,
el próximo lo lee como si comparara el conjunto (que es exactamente lo que pasó con
`same_universe_as`)"*. Volvió a pasar, en el mismo archivo y en el mismo commit.

---

## 4. Fase adversarial — lo que se rechazó, y por qué

Los dos candidatos más fuertes pasaron por el agente `verificador` con mandato de refutarlos.

| candidato | veredicto | motivo |
|---|---|---|
| **G-1** — el hook no corre | **SOBREVIVE, reforzado** | Se agotaron `core.hooksPath` en los tres niveles, worktrees, wrappers, alias, husky, el CI y la suite. Ninguna abre. Sumó tres refuerzos que están incorporados arriba: `/ship` corre **otro** guard; `pre-commit run --all-files` tampoco puede disparar el shrink; y la lógica de `check_staged_shrink` **no tiene ningún test**. |
| **"la huella de población es del ARCHIVO y ése es el defecto"** | **SE CAE — borrado** | Es una decisión deliberada, documentada con las alternativas descartadas y **fijada por `tests/test_poblacion_conjunto_t87.py:124`**. Se borra en vez de degradarse. Sobrevive el **corolario**, que es G-4. |
| **"una corrida encogida sale `FALLA` acusando a la cañería"** | **SE CAE — borrado** | Lo bloquea la precondición `entradas_comparables`, porque las anclas compartidas no declaran `n_entries`. Verificado: sale `INDETERMINADO`. El informe publica el síntoma real (afirma *"mismo universo"*) y el agudo (`REPRO_OK`). |
| **"`deviations()` mitiga imprimiendo el desvío de universo"** | **SE CAE como mitigación** | No es que sólo imprima: **ya dispara en toda corrida sana** (127 vs `LIVE_WATCHLIST_SIZE=128`, por ASML). No discrimina sano de encogido. |

**Y un número propio que se refutó a sí mismo.** Una primera medición dio *"1103 líneas de
tests en el log de producción después del 2026-09-02"*, lo que habría contradicho el cierre de
la **78**. **Era un artefacto del instrumento:** el `awk '$1>="2026-09-02"'` compara el campo 1
como **string**, y las líneas de traceback empiezan con `File`, que ordena después de
`2026-…`, así que pasaban todas sin filtrar. Re-medido con un parser de timestamps real: **973
líneas en total, la última a las 12:44:30 y CERO después del fix de las 12:48:14**. El arreglo
de la 78 se sostiene. Queda anotado porque es la tercera vez que un barrido ad-hoc da un
número limpio y falso.

**Dos candidatos más que no se publican, por no tener costo concreto:**

- **`_is_market_open_safe()` falla cerrado y mudo** (`engine.py:275-283`): en vivo
  `paper_enforce_market_hours=False`, y como el call site es
  `enforce_hours and not _is_market_open_safe()`, Python ni siquiera lo llama. Inerte.
- **El WARNING de "unstable model" de XGBoost no tiene ningún consumidor**
  (`analysis/ml_signals.py:852-861`; 30 disparos en la ventana limpia del log, con
  `xgb_signal_enabled=True` en vivo): no se estableció que `ml_probability` llegue a una
  decisión viva, y sin ese eslabón no hay costo. Se deja anotado acá, no en la cola.

---

## 5. Lo que se miró y salió LIMPIO

Un barrido limpio es un resultado, y estos guards lo son:

- **Guard E5 de precios fuera de banda** (`data/yahoo_finance.py:1037-1100`): escala de
  WARNING a ERROR según la racha, deduplica el mensaje, **nombra el estado** (*"el ticker está
  INVISIBLE — sin precio para entrar ni para salir"*) y **acepta el precio** cuando la
  referencia no es confiable, con el motivo escrito (*"bloquear contra una referencia dudosa
  deja la posición sin salida"*). Es el patrón de referencia del repo.
- **Circuit-breaker de throttle** (`:189-271`): loguea apertura, escalada y recuperación.
- **`alerts/alert_manager.py:101`**: su único `except` amplio loguea y declara el fail-open.
- **Gate 6 (earnings)**: falla abierto **diciéndolo** en WARNING.
- **`ui/`**: los 33 `except` amplios barridos por AST — ninguno es un guard degradando en
  silencio; o llegan al usuario por `QMessageBox`, o son fallbacks cosméticos posteriores al
  log. `ui/error_handler.py:191` loguea CRITICAL antes de caer al excepthook original.
- **El arreglo de la 78**: verificado, cero líneas de la suite en el log de producción después
  del fix.
- **`check_backlog_integrity.check_text`**: sus cuatro chequeos son estructurales, sin un solo
  umbral que alguien tenga que ir subiendo, y leen el contrato del propio archivo.
- **Los tests que cuentan desvíos** (`assert len(devs) == 9`): son números fijos, pero fallan
  **hacia el lado seguro** — agregar un desvío rompe el test y obliga a mirar.
- **`announce_artifacts` sobre los `run_*.py`**: 21 de 21 de los que leen el cohorte. El
  número de la 76 reproduce exacto.

---

## 6. Limitaciones de esta corrida

- El barrido de `except` cubrió sólo los **amplios y desnudos** (`Exception`, `BaseException`,
  bare). Los ~281 con tipo declarado no se miraron.
- Los tres hallazgos **latentes** (G-7, G-8 y la mitad de G-9) se midieron sobre el estado de
  **hoy**. Que hoy no disparen no dice nada de mañana; lo que se afirma es el camino de código,
  no una incidencia.
- No se ejercitó ningún guard bajo contención real (concurrencia, red caída, disco lleno). Todo
  lo que se dice de esos caminos sale de leer el código, no de provocarlos.
- G-5 se acotó midiendo el cohorte `2y`. El `10y` y el `1y` no se midieron.

---

## 7. Mapeo hallazgo → tarea

Una fila por hallazgo publicado, verificada de a una contra `docs/BACKLOG.md`.

| hallazgo | severidad | tarea |
|---|---|---|
| **G-1** — ningún hook de git corre; la mitad `--staged` de la 66 nunca se ejecutó | HIGH | **97** (HOOK-INERTE) — incluye en su enunciado los hooks huérfanos y el hueco de `debug-statements`/`T10` |
| **G-2** — `check_repo_health.py` sin cableado, y la skill lo llama "Guard automático" | MEDIA-ALTA | **98** (REPOHEALTH-MANUAL) |
| **G-3** — siete runners con `--account default=1` (cuenta pausada) | MEDIA-ALTA | **99** (ACCT1-DEFAULTS) |
| **G-4** — la 87 borró la única comparación viva de `n_tickers` | MEDIA | **100** (NTICKERS-CIEGO) |
| **G-5** — guard de cohorte cableado por prefijo; cuatro `measure_*` afuera | MEDIA | **101** (ANNOUNCE-MEASURE) |
| **G-6** — el t61 lee una tabla vacía y no imprime `n_skipped_no_data` | MEDIA | **102** (T61-SINDATOS) |
| **G-7** — Gate 3b (ADV) falla abierto sin rastro | MEDIA | **103** (ADV-MUDO) |
| **G-8** — `_now_et()` cae a UTC en silencio con la rama de `pytz` inalcanzable | MEDIA | **104** (TZ-UTC-MUDO) |
| **G-9** — `signal_store_gaps` saltea con una justificación falsa para el t12 | BAJA-MEDIA | **105** (PITGAP-SKIP) |
| **G-10** — tres docstrings contradictorios sobre `tickers_fp` | BAJA-MEDIA | **parte de la 100** — nombrado explícitamente en su enunciado |
