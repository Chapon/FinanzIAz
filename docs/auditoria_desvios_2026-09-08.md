# Auditoría READ-ONLY — área `desvios` — 2026-09-08

Sexta corrida de `/audit`. Área: **desvíos harness↔engine que `deviations()` no declara**.
Corrida anterior de esta área: `docs/auditoria_desvios_2026-09-02.md` (dejó las tareas 92–96).

---

## 1. Kill-criteria — CONGELADO 2026-09-08, antes de abrir ningún archivo

> Este bloque se escribió **antes** de mirar `harness_config.py`, los runners, el
> `settings.json` vivo o la DB. Lo que sigue después es el barrido; esto no se toca.

### 1.1 Por qué esta área y por qué ahora

El disparador es concreto, no *"hace rato que no se audita"*: **el 2026-09-07 se movieron
dos perillas vivas** y ninguna corrida de harness se re-leyó después.

- `paper_regime_scale_factor` pasó de **0.50 a 0.25** (tareas 115 / 121 / 124).
- `paper_universe_screen_enabled` pasó de **OFF a ON**, con la pata de liquidez apagada
  (`paper_universe_min_adv_dollars=0.0`) — acción manual de Chapa, *«hagamos todas»*.

La cuarta corrida de esta misma área (2026-09-02) cerró con el titular *«el desvío más caro
del día estaba en una perilla que Chapa cambió hace seis días»*. Hoy estamos exactamente a
un día de dos cambios del mismo tipo, así que la hipótesis de trabajo es que el modo de
falla se repite.

### 1.2 Qué se busca — una frase por sub-categoría

- **[D-perilla]** Una perilla viva que se movió y el harness sigue modelando el valor viejo,
  o `deviations()` sigue **citando el número viejo**.
- **[D-nuevo]** Un desvío **N+1** sin declarar: un eje que el engine ejecuta (gates, sizing,
  costos, cash, re-entrada, blackout de earnings, cap por ADV, overlay de volatilidad) y que
  el harness ni modela ni nombra. **El N se cuenta en el fuente**, no se toma de la skill
  ni de este documento — es la lección del hallazgo A-1 de la primera corrida.
- **[D-cobertura]** Un runner que produce un número comparable contra la cuenta viva y **no
  llama al banner** de desvíos, o lo llama con un alcance que no lo cubre (el caso del T7 en
  la tarea 116).
- **[D-valor]** Una declaración que existe pero cuyo **número** ya no es el que se ejecuta
  (el caso de la tarea 119: el banner declaraba un costo de gates 30× mayor que el real).

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. **Bugs de código.** Para eso están la suite, el CI y `/code-review`. Si aparece uno se
   anota como tarea (regla 6) pero **no** es un hallazgo de esta corrida.
2. **Las otras cuatro áreas** (claims, muestra, guards, estado), salvo cuando el defecto sea
   la consecuencia directa de un desvío no declarado.
3. **Correr o re-correr cualquier harness.** Es READ-ONLY y además caro; si un desvío obliga
   a re-leer un veredicto, eso se anota como tarea, no se ejecuta acá.
4. **La UI y el scheduler.** No producen números comparables contra un harness.
5. **Re-abrir veredictos publicados.** Un desvío puede *pedir* una re-lectura; decidirla es
   de Chapa.

### 1.4 Qué contaría como "acá no hay nada" — condición de barrido limpio

La corrida cierra **limpia** —y se dice, sin llenar el informe— si se cumplen las cuatro:

1. El número de desvíos declarados en `deviations()` **coincide con los que el fuente
   enumera**, y no aparece ningún eje del engine fuera de esa lista.
2. **Todo flag del `settings.json` vivo que toque una decisión de trading** está en uno de
   estos tres estados, verificable: (a) modelado por el harness, (b) declarado como desvío,
   o (c) escrito como fuera del marco. Ninguno en un cuarto estado silencioso.
3. **Ningún runner** que produzca un número comparable contra la cuenta viva queda sin
   banner de desvíos.
4. Los **valores citados** en las declaraciones coinciden con los que hoy devuelve el
   `SettingsManager` real y con los de la cuenta activa (id=2).

### 1.5 Alcance que se va a mirar

`analysis/harness_config.py`, `paper_trading/engine.py`, `paper_trading/strategies.py`,
`analysis/portfolio_sim.py`, el `replay_cycle`, los runners de `scripts/run_*.py` y
`scripts/measure_*.py`, el `~/.finanzias/settings.json` vivo (lectura) y la fila de la
cuenta 2 en la DB (lectura sobre copia, regla 5).

---

## 2. Alcance real de la corrida

### 2.1 Lo que se miró

| qué | cómo |
|---|---|
| `analysis/harness_config.py` (2.477 líneas) | `HarnessConfig`, `deviations()`, `config_banner()` y las 30 constantes `LIVE_*` |
| El settings vivo | `C:\Users\chapa\.finanzias\settings.json`, leído con `utf-8-sig`, **sólo lectura** |
| La DB viva | `finanzias.db` abierta `mode=ro`: `paper_accounts` y `paper_watchlist` de las dos cuentas |
| Los gates del engine | `paper_trading/engine.py` (Gates 1, 2, 2b, 2c, 3, 3b, 4, 5, 5b, 6), `paper_trading/gates.py`, `paper_trading/strategies.py`, `paper_trading/universe.py` |
| Lo que el harness modela | `analysis/portfolio_sim.py`, `analysis/scaleout_replay.py`, `analysis/exit_replay.py` |
| Cobertura de runners | los 39 `scripts/run_*.py` + `scripts/measure_*.py`, **por AST** y no por grep |
| Los guards de todo esto | `tests/test_harness_config.py`, `test_exit_policy_t92.py`, `test_desvios_declarados_t94_96.py`, `test_volpen_t42.py`, `test_watchlist_size_t89.py`, `test_account_defaults_t99.py`, `tests/conftest.py` |

**Instrumentos validados antes de creerles al número** (lección de la tarea 110): el conteo
de runners de cartera se hizo recorriendo el AST en busca de llamadas reales a
`simulate_portfolio`, no con `grep` —que cuenta menciones en comentarios—; y el conteo de
desvíos se sacó **ejecutando** `deviations()` con una config idéntica a la cuenta viva, no
leyendo el fuente.

### 2.2 Lo que NO se miró — y queda declarado

1. **No se corrió ningún harness.** Ningún número de veredicto se re-midió; si un desvío
   pide re-lectura, eso queda como tarea.
2. **No se midió el efecto del screen E1b sobre los 79 tickers no validados.** Requiere una
   ronda de EDGAR viva por ticker y no hay cache persistente (`_FACTS_CACHE` es por proceso,
   `data/edgar_fundamentals.py:209`). Lo que sí se estableció es la **población**, que es
   aritmética de conjuntos sobre la DB.
3. **Gates 1, 2, 2c, 3 y 4** (market hours, min-holding en minutos, exit-veto de catalysts,
   anti-flap y trade mínimo) se miraron sólo lo suficiente para descartar que fueran
   modelables sobre barras diarias. **No** se auditó si su ausencia debería declararse.
4. **Gate 3b (cap por ADV)** no se auditó a fondo: su fail-open mudo ya fue la tarea 103.
5. **`atr_tp_mult`** (take-profit, vivo en 4.0) coincide hoy con `AtrParams.tp_mult`, pero
   **no** tiene espejo en `HarnessConfig` ni línea en `deviations()`. Cae dentro de [D-2] como
   caso, no se abrió aparte.
6. **Las otras cuatro áreas** (`claims`, `muestra`, `guards`, `estado`) sólo se tocaron donde
   el defecto era consecuencia directa de un desvío.

---

## 3. Hallazgos

Ocho publicados. Los cuatro sustantivos pasaron por el agente `verificador` con mandato de
**refutarlos**: los cuatro sobrevivieron, tres con correcciones que están incorporadas abajo,
y la fase adversarial agregó dos hallazgos propios ([D-5] y [D-7]).

**La hipótesis con la que se abrió la corrida se confirmó:** de los ocho hallazgos, cinco
cuelgan de las dos perillas que Chapa movió el **2026-09-07**, o sea el día anterior.

---

### [D-1] El screen de universo E1b decide en vivo desde el 2026-09-07 y `deviations()` no lo nombra

Severidad: **MEDIA-ALTA** · Confianza: **ALTA** · Categoría: desvío no declarado (D-nuevo)
Ubicación: `analysis/harness_config.py:1604` (`deviations`) · `paper_trading/strategies.py:290`

**Evidencia.** `paper_universe_screen_enabled=True` en el settings vivo desde el 2026-09-07.
`_screen_out_candidate` (`strategies.py:290`) dropea **candidatos de BUY** cuando está ON, y
se aplica a todo candidato del universo, no sólo a nombres de afuera de la watchlist. Buscar
`screen|E1b|fundamental` en `analysis/harness_config.py`, `analysis/portfolio_sim.py` y
`analysis/scaleout_replay.py` da **vacío**; ningún runner lo menciona salvo su propio
validador. No hay campo `models_universe_screen` en `HarnessConfig` ni constante
`LIVE_UNIVERSE_SCREEN_*`.

**Razonamiento.** Es la misma forma exacta que las tareas 94, 95 y 96 —una perilla viva de
sizing/gates que el harness no modela— y el remedio del proyecto para esas tres fue
declararla, no modelarla. El desvío de `n_tickers` **no** lo cubre: ése compara **tamaños**
(127 vs 128, o sea la ausencia de ASML), mientras el screen es un drop **dinámico por scan**.
Y el argumento de que podría ser inerte no aplica bajo el estándar del propio repo: el
escalado por régimen se declara igual, con *«0 de 62 BUY vivas lo dispararon»*.

**Lo que corrigió el verificador, y es la mitad más interesante:** no es cierto que no lo
declarara **nadie**. Tres pre-registros viejos lo declaraban a mano, y los tres envejecieron
mal:

- `docs/meta_labeling_t9_2026-07-21.md:276` — correcto entonces, pero su razón **caducó el
  2026-09-07**: dice *«`paper_universe_screen_enabled` sigue false en el schema vivo»*.
- `docs/anomaly_signal_prereg_t11b_2026-07-23.md:171` y
  `docs/anom_profile_prereg_t45_2026-08-20.md:261` — lo declaran **describiéndolo mal**, como
  *«concern de producción»* del sourcing de nombres fuera de watchlist. Apuntan al riesgo
  equivocado.

**Y el agravante:** los dos pre-registros **más nuevos**, ambos del **2026-09-07** —el mismo
día del flip— delegan explícitamente en el banner.
`docs/t20_killgate_prereg_t115_2026-09-07.md:187` enumera cinco desvíos *«que el banner
declara»* y el screen no está; `docs/pead_prereg_t11a_2026-09-07.md:142` dice *«los desvíos
harness↔engine de siempre los declara el banner»*. Es literalmente el modo de falla que
advierte `analysis/harness_config.py:66-70`: **«lo que acá no se diga, no lo dice nadie»**.

**Impacto.** Desde el 2026-09-07 ningún pre-registro nuevo declara el screen, porque todos
confían en un banner que no lo conoce. El harness entra en BUYs que el engine puede bloquear.

**Nota de precisión.** Cuántas líneas emite `deviations()` **depende de la config**: 9 con los
defaults del harness y **6** con una config que espeja la cuenta viva
(`touch` + `live_gates=True` + stop duro apagado + trail 2.0). En ninguna de las dos aparece
el screen.

**Acción mínima.** Un `LIVE_UNIVERSE_SCREEN_ENABLED` + campo `models_universe_screen` en
`HarnessConfig` + la línea en `deviations()`, igual que 94/95/96. Y corregir el texto de los
dos pre-registros que lo describen como problema de sourcing.

---

### [D-2] Los espejos de la política viva se verifican contra el REPO, no contra lo vivo — y el repo ya dice otra cosa en cuatro claves

Severidad: **ALTA** · Confianza: **ALTA** · Categoría: guard que mide la cosa equivocada
Ubicación: `tests/test_exit_policy_t92.py:106-112` · `tests/test_desvios_declarados_t94_96.py:67-75` · `tests/test_volpen_t42.py:99-104`

**Evidencia.** Los tres guards que existen para que los espejos `LIVE_*` sigan a la cuenta
viva comparan contra el **repo**:

| guard | contra qué compara | qué puede ver |
|---|---|---|
| `test_exit_policy_t92.py:110` | un literal escrito en el test | que alguien edite `harness_config.py` |
| `test_desvios_declarados_t94_96.py:70-74` | un literal escrito en el test | ídem |
| `test_volpen_t42.py:103` | `DEFAULTS["paper_vol_penalty_coef"]` | que alguien edite el **schema del repo** |
| `test_watchlist_size_t89.py:96` | **la DB viva**, con `skip` si no está | **el cambio real** ✔ |

Ningún script de `scripts/` compara contra el settings vivo; `scripts/check_repo_health.py`
no lo lee; el paso 4 de `/ship` es un barrido **manual y a ojo** que se dispara cuando cambia
una constante **del repo**; y no hay hooks de git instalados (tarea 97).

**La prueba más limpia está escrita adentro del propio test.**
`tests/test_desvios_declarados_t94_96.py:71-72` dice: *«Este test **hizo su trabajo**:
pinneaba el 0.5 y falló al cambiar el valor vivo»*. `git show --stat 2a4404a` muestra que
`analysis/harness_config.py` y el assert del test **cambiaron en el mismo commit**. El test
disparó sobre la edición del repo; nunca vio la edición del `settings.json`.

**Y el repo ya divergió del vivo en cuatro claves**, medido hoy:

| clave | DEFAULT del repo | VIVO |
|---|---|---|
| `atr_hard_stop_enabled` | `True` | **`False`** |
| `atr_trail_mult` | `0.0` | **`2.0`** |
| `atr_stops_enabled` | `False` | **`True`** |
| `paper_universe_screen_enabled` | `False` | **`True`** |

**Impacto.** Es exactamente el defecto de la tarea 92 —el harness declaró la política de
salida **al revés** durante seis días, y valía **7,16 pp de CAGR**— y los tres guards escritos
para que no volviera a pasar **no pueden verlo**. Hoy los 13 espejos coinciden con el vivo:
lo que falta es el guard, no la corrección.

**Verificación (lo que se intentó para refutarlo).** Se buscó guard, script, hook o paso de
`/ship` que leyera el settings vivo: no hay. Lo más cercano es
`scripts/run_exit_replay_t61.py:61-99`, que **sí** lee la config viva para armar sus
`AtrParams` — pero es consumidor, no guard, y juega **a favor**: prueba que leerla desde un
script ya se hace y es trivial.

**Corrección incorporada.** Decir que *«el conftest impide que un test lea el settings vivo»*
es **demasiado fuerte**: `tests/conftest.py:269-289` sólo monkeypatchea
`_CONFIG_PATH`; un test puede abrir `Path.home()/".finanzias"/"settings.json"` directo, que es
justo el patrón de `test_watchlist_size_t89.py` con la DB. **El arreglo está disponible y es
barato.** Y el caso de `paper_vol_penalty_coef` está bien **por accidente**: la clave está
ausente del json vivo, así que el default *es* el valor efectivo — basta que alguien la
escriba en el settings para que el guard quede verde con el espejo podrido.

**Acción mínima.** Un guard que lea el settings vivo y compare los 13 espejos, con `skip`
cuando el archivo no está (patrón exacto de la tarea 89).

---

### [D-3] El screen se prendió sobre un universo que su validación cubre en un 38%, y justo los sectores que faltan son donde puede fallar

Severidad: **ALTA** · Confianza: **ALTA** (la población y el mecanismo; el efecto sobre los 79 **no se midió**)
Ubicación: `docs/universe_screen_e1b_2026-07-02.md:31` · `data/edgar_fundamentals.py:46-52` · `paper_trading/universe.py:_fragile_fundamentals`

**Evidencia.** El kill-criteria de E1b (*«excluye los nombres tipo MLTX sin sacar nombres
buenos»*) se validó el 2026-07-02 sobre **la watchlist de Sim Principal, 52 nombres**. La
cuenta viva es la 2, con **128**. Aritmética de conjuntos sobre la DB (`mode=ro`):

- **49 de 128** tickers vivos estaban en la población validada (**38%**);
- **79 no estuvieron nunca**;
- **MLTX** —el único nombre que el screen excluyó en esa validación, y la razón de existir de
  la feature— está en la watchlist de la cuenta **1** y **no** en la 2.

**El mecanismo por el que esto muerde, y lo aportó el verificador.**
`_fragile_fundamentals` excluye si los dos últimos net income anuales son < 0 **y**
`revenue_latest` es `None` **o** < $10M — y *una ausencia de revenue cuenta como debajo del
piso*. `data/edgar_fundamentals.py:46-52` prueba **cinco** conceptos XBRL: `Revenues`,
`RevenueFromContractWithCustomer{Excluding,Including}AssessedTax`, `SalesRevenueNet` y
`SalesRevenueGoodsNet`. **Ninguno es el tag primario de un banco**
(`RevenuesNetOfInterestExpense`), **de una utility regulada**
(`RegulatedAndUnregulatedOperatingRevenue`) **ni de una aseguradora** (`PremiumsEarnedNet`).

**Y ésa es exactamente la composición de los 79 que no se validaron:** C, GS, MS, JPM, BAC,
WFC, SCHW, AXP, BLK · AEP, D, DUK, EXC, SO, XEL, PCG, SRE, NEE · AMT, CCI, EQIX, O, PLD, PSA,
SPG, WELL · COP, CVX, XOM, OXY, SLB, HAL, BKR, KMI, OKE, WMB, MPC, PSX, VLO. Los 52 validados
eran **todos tech y consumo**: ni un banco, ni una utility, ni un REIT, ni una aseguradora.

Los **únicos dos** nombres que ejercitaron la rama *«pérdidas sostenidas + revenue real ⇒
CONSERVAR»* fueron INTC y TEAM — y **TEAM es uno de los tres que salieron del universo**
(los que están en la 1 y no en la 2 son AAPL, MLTX y TEAM). Queda **una sola** regresión viva.

**Bonus verificado en código: la herramienta para re-validarlo reporta un NO-SHIP falso.**
`scripts/run_universe_screen_validation.py` con `--account-id 2` y su `--expect-fragile MLTX`
por default da `fragile_missed=["MLTX"]` (MLTX no está en esa watchlist) ⇒ `kill_pass=False`
⇒ exit 1. Contra el universo vivo la herramienta **falla siempre** salvo que se le pase
`--expect-fragile ""`.

**Lo que el log NO puede decidir, y queda escrito.** En el log vivo desde el flip hay **cero**
líneas `E1b: candidato BUY … excluido`, pero también **sólo dos scans** (2026-09-07 21:20 con
`generated=0`; 2026-09-08 22:45 con `generated=1 filled=1`), así que la ausencia **no tiene
poder**: ni confirma ni refuta. Y las 118 líneas E1b de `finanzias.log.1` son **fugas de la
suite** al log de producción (tickers sintéticos `FRAG`/`ILLQ`, piso `50.000.000`, anteriores
al guard de la tarea 78) — no son evidencia de nada vivo.

**La refutación más seria que se intentó, y por qué no alcanza.** `docs/BACKLOG.md:774` dice
*«Efecto conocido hoy: NINGUNO — la única exclusión que el screen tenía medida era MLTX, y ya
no está en el universo vivo»*. Eso argumenta sólo el lado **verdadero-positivo** (que no
excluya lo que debía excluir). **No dice una palabra del lado falso-positivo**, y encima
re-cita la validación de 52 nombres —*«ya validado, kill-criteria PASS»*— como si cubriera el
universo vivo.

**Lo que NO se midió.** De los 79: cuáles resuelven revenue con los cinco conceptos actuales y
cuáles tienen dos net income anuales negativos seguidos. Requiere EDGAR vivo por ticker y no
hay cache persistente (`_FACTS_CACHE` es por proceso, `data/edgar_fundamentals.py:209`).
**No se afirma que el screen esté sacando nombres buenos: se afirma que nadie lo verificó
sobre el universo que filtra hoy, y que el mecanismo para que pase está identificado.**

---

### [D-4] El guard de la tarea 99 convierte «no pude leer el default» en «está bien», y por ahí pasó el runner que apunta a la cuenta pausada

Severidad: **MEDIA-ALTA** · Confianza: **ALTA** · Categoría: guard que degrada en silencio
Ubicación: `tests/test_account_defaults_t99.py:118` · `scripts/run_universe_screen_validation.py:47`

**Evidencia.** `_defaults_de_cuenta` lee el default de cada `--account`/`--account-id` con
`getattr(kw.value, "value", "<no-literal>")`. Cuando el default es un `ast.Name` (una
constante de módulo) y no un `ast.Constant`, devuelve la **cadena** `"<no-literal>"`; y el
guard sólo acusa si `isinstance(default, int)`. O sea que **el fallo de lectura se lee como
aprobación**.

Corriendo su propio helper sobre los 39 scripts, **tres** devuelven `<no-literal>`:

| script | default real | ¿bien? |
|---|---|---|
| `build_surprise_profiles.py` | `DEFAULT_ACCOUNT_ID` de `harvest_catalysts` = `None` | ✔ |
| `refresh_live_universe.py` | `LIVE_ACCOUNT_ID` = `2` | ✔ |
| **`run_universe_screen_validation.py`** | **`DEFAULT_ACCOUNT_ID = 1`** | ✘ **la cuenta pausada** |

**Verificación (lo que se intentó para refutarlo).** ¿Otro test lo caza?
`tests/test_live_account_t70.py:118-134` es un guard de **literal de string**
(`"DEFAULT_ACCOUNT_ID = 1" not in txt`) parametrizado sobre **exactamente tres** archivos
(`harvest_catalysts.py`, `news_feed.py`, `dashboard_data.py`);
`run_universe_screen_validation.py` **no está en la lista y contiene ese literal textual en su
línea 47**. ¿Está excluido a propósito? No: ningún comentario, doc ni backlog lo excluye.
¿Resuelve por otro camino? No: `resolve_account_id` aparece **0** veces, y
`_load_watchlist(args.db, args.account_id)` va directo al `SELECT`. Los cinco archivos de test
relevantes corren **45 passed** con los defectos adentro.

**Impacto.** Es el mecanismo por el que [D-3] sobrevivió a la tarea 99: el único instrumento
que mide si el screen vivo saca nombres buenos mide, por default, **la watchlist de la cuenta
muerta**.

**Acción mínima.** Que el centinela de lectura fallida sea **un fallo del guard**, no un valor
que se cuela por `isinstance(..., int)` — o resolver el `ast.Name` contra las constantes del
módulo. El propio docstring del test (líneas 8-14) dice que la lección de la 99 era *«la
población, no el arreglo puntual»*, y el `getattr` reintroduce la misma ceguera un nivel más
abajo. **Sumar el archivo a una lista sería repetir el error.**

---

### [D-5] `atr_stops_enabled` es el master switch de las barreras ATR y es el único de la política de salida sin espejo

Severidad: **MEDIA-ALTA** · Confianza: **ALTA** · Categoría: espejo faltante (latente)
Ubicación: `analysis/harness_config.py:109-111` · `paper_trading/engine.py:491` y `:604`
Origen: **lo trajo el `verificador`**, no el barrido.

**Evidencia.** El engine chequea `atr_stops_enabled` **antes que todo lo demás** (*«Tarea 55 —
el MASTER SWITCH primero»*). El bloque de espejos de la política de salida de la T92 tiene
`LIVE_HARD_STOP_ENABLED`, `LIVE_STOP_MULT` y `LIVE_TRAIL_MULT`, pero **no** tiene espejo del
switch que vuelve a los tres irrelevantes. Verificado: `atr_stops_enabled` con DEFAULT `False`
y vivo `True`; ninguna constante `LIVE_*` lo refleja.

**Impacto.** Hoy está ON, así que los tres espejos significan lo que dicen. Si Chapa lo
apagara, `deviations()` seguiría declarando *«stop duro APAGADO / trailing 2.0×ATR en la
cuenta 2»* mientras la cuenta viva **no tendría barreras ATR en absoluto** — el desvío
declarado **al revés**, que es el modo de falla exacto que la T92 existe para prevenir.
Es latente, no activo.

---

### [D-6] `PORTFOLIO_RUNNERS` es una lista a mano de 10 sobre 21 llamadores reales

Severidad: **MEDIA** (latente) · Confianza: **ALTA** · Categoría: cobertura de guard
Ubicación: `tests/test_harness_config.py:91`

**Evidencia (por AST, no por grep).** Recorriendo el árbol de los 39 scripts en busca de
llamadas reales a `simulate_portfolio`: **21 llamadores**. `PORTFOLIO_RUNNERS` enumera **10**.
Quedan afuera de `test_runner_defaults_to_the_live_slot_count` y de
`test_runner_announces_its_config`: `measure_trail_arm_t54`, `run_anom_profile_t45`,
`run_anom_regime_t38`, `run_event_timestop_t51`, `run_prio_event_t49`, `run_rank_neutral_t39`,
`run_regime_power_t46`, `run_stop_price_redecide_t47`, `run_stop_price_replay_t26b`,
`run_stop_value_t37` y `run_trail_arm_t54`.

**Ya se parcheó a mano una vez.** El cierre de la tarea 32 lo dice con todas las letras:
*«Gap lateral tapado: `PORTFOLIO_RUNNERS` de la T27 listaba **7** runners y no incluía ni
`run_ranking_t21.py` ni `run_stop_cal_replay_t26.py`»*. Pasó de 7 a 10 por edición manual y
hoy está en 10 sobre 21. **Es la segunda vez que la lista queda atrás**, lo que dice que el
problema no es el contenido de la lista sino que sea una lista.

**Por qué es latente y no activo.** Se revisaron los 11: **los 11** declaran
`--max-positions` con default `LIVE_MAX_POSITIONS` y **los 11** llaman
`announce(args.max_positions, …)`. Hoy no hay ningún defecto detrás del hueco; lo que falta es
que el guard no dependa de que alguien acuerde de sumar el archivo a la lista.

---

### [D-7] Dos runners todavía definen su propio `LIVE_TRAIL_MULT = 2.0`

Severidad: **BAJA-MEDIA** (latente) · Confianza: **ALTA** · Categoría: espejo duplicado
Ubicación: `scripts/measure_trail_arm_t54.py:78` · `scripts/run_trail_arm_t54.py:96`
Origen: **lo trajo el `verificador`**.

**Evidencia.** Los dos definen la constante en vez de importar
`analysis.harness_config.LIVE_TRAIL_MULT`. Es la duplicación por script que
`analysis/harness_config.py:34-49` afirma haber eliminado (*«estaba repartida en constantes
por script en cinco archivos»*). Coinciden con lo vivo hoy. El test de la T92 guardó el
renombre de `run_stop_value_t37.py` pero no cubre estos dos.

---

### [D-8] Dos números caducados en las skills que se leen ANTES de escribir un pre-registro

Severidad: **BAJA-MEDIA** · Confianza: **ALTA** · Categoría: claim caducado
Ubicación: `.claude/skills/backtest-replay-harness/SKILL.md:453` · `.claude/skills/auditoria/SKILL.md:112`

**Evidencia.** La primera dice *«ya está cableado en los **16** runners de cartera»*; por AST,
**22** runners pasan `window=` a `announce()`. La segunda pregunta *«¿hay un **octavo** desvío
que `deviations()` no nombra?»* cuando el fuente **ya numera el octavo** (`harness_config.py`,
comentario *«OCTAVO desvío (Tarea 92)»*) y suma tres ejes más sin numerar (94/95/96).

**Lo irónico, y es el punto:** ese párrafo de la skill `auditoria` **existe para advertir que
ese número caduca** —*«el número de esta frase ya caducó una vez, en 20 minutos»*— y volvió a
caducar. El remedio que se eligió entonces (agregar una advertencia y pedir que se cuente en
el fuente) **funcionó** —esta corrida contó en el fuente y por eso lo detectó— pero **no
impidió la recurrencia**. La forma que no caduca es no poner el ordinal.

---

## 4. Lo que NO sobrevivió

**Un candidato se cayó antes de publicarse, por auto-refutación.** Se estuvo por reportar como
caducado el *«**séptimo desvío**»* de `backtest-replay-harness/SKILL.md:453`, razonando que
hoy `deviations()` emite 9 líneas. **Es correcto y no es un hallazgo:** T48 (la ventana de los
artefactos) *es* el séptimo en la numeración histórica del proyecto —slots 1, universo 2,
ventana de `analyze()` 3, T32 4, T33 5, T34 6, T48 7— y esa numeración es un **ordinal
histórico**, no un conteo de líneas emitidas. Lo que sí caducó en esa misma frase es el «16».

Queda escrito porque es la trampa de la categoría: **el ordinal histórico y el conteo vivo son
dos números distintos**, y confundirlos fabrica un hallazgo falso.

**Ninguno de los ocho publicados fue rechazado por el `verificador`.** Los cuatro que se le
mandaron sobrevivieron; tres volvieron con correcciones, todas incorporadas arriba.

---

## 5. Limitaciones de esta corrida

1. **El efecto real del screen E1b sobre los 79 tickers no validados no se midió** — requiere
   EDGAR vivo. [D-3] afirma la población y el mecanismo, **no** que haya nombres buenos
   cayéndose.
2. **No se corrió ningún harness ni se re-midió ningún veredicto.**
3. **El log vivo no tiene poder** para decidir nada sobre el screen: dos scans desde el flip.
4. **Los Gates 1, 2, 2c, 3 y 4 no se auditaron a fondo** (ver §2.2).
5. Una corrida por área no es exhaustiva, y esta no pretende serlo.

---

## 6. Mapeo hallazgo → tarea

**Sin esta tabla la auditoría no está cerrada.** Una fila por hallazgo publicado, ninguna
vacía, verificada de a una contra `docs/BACKLOG.md` y no de memoria. (En la primera corrida de
esta skill se publicaron 7 hallazgos con 3 tareas y **dos quedaron sueltos**.)

| hallazgo | severidad | tarea | orden |
|---|---|---|---|
| [D-1] El screen E1b decide en vivo y `deviations()` no lo nombra | MEDIA-ALTA | **131** SCREEN-DESVIO | 4ª |
| [D-2] Los espejos `LIVE_*` se verifican contra el repo, no contra lo vivo | **ALTA** | **130** ESPEJOS-VIVOS | 3ª |
| [D-3] El screen se prendió sobre un universo validado al 38% | **ALTA** | **129** SCREEN-REVALIDAR | 2ª |
| [D-4] El guard de la 99 lee el fallo de lectura como aprobación | MEDIA-ALTA | **128** ACCT1-VALIDADOR | **1ª** |
| [D-5] `atr_stops_enabled` sin espejo | MEDIA-ALTA (latente) | **132** STOPSW-ESPEJO | 5ª |
| [D-6] `PORTFOLIO_RUNNERS`: lista a mano de 10 sobre 21 | MEDIA (latente) | **133** PORTFOLIO-LISTA | 6ª |
| [D-7] Dos runners con su propio `LIVE_TRAIL_MULT` | BAJA-MEDIA (latente) | **134** TRAILMULT-DUP | 7ª |
| [D-8] Dos números caducados en las skills | BAJA-MEDIA | **135** SKILLDECAY-DESVIOS | 8ª |

**Los dos casos que la skill avisa que se escapan, revisados:**

- **Ningún hallazgo quedó agrupado como *«parte de»* otro.** El mapeo es 1:1, ocho y ocho.
- **El hallazgo que esta corrida NO pudo verificar igual está en la cola.** [D-3] no midió
  cuántos de los 79 tickers excluye el screen —eso exige EDGAR vivo— pero lo accionable es
  *«nadie lo re-chequeó sobre el universo que filtra hoy»*, que es un hecho **sobre el
  proceso**, verificable con las fechas y la aritmética de conjuntos. La tarea **129** lo lleva
  escrito adelante: *no se afirma que el screen esté sacando nombres buenos*.

**Dos dependencias quedaron escritas en los enunciados, no sólo acá:** la 129 depende de la
128 (el instrumento), y la 131 y la 132 conviene hacerlas después de la 130 (para que los
espejos nuevos nazcan con guard).
