# Auditoría `claims` — 2026-09-01

**Área:** afirmaciones y números que el proyecto **usa hoy para decidir** y que pueden haber
dejado de ser ciertos · **READ-ONLY**, no se modificó nada · **Primera corrida** de la skill
`auditoria` · Fase adversarial: agente `verificador`

---

## 1. Kill-criteria — congelado ANTES de abrir un archivo

**Corpus (cerrado):** `CLAUDE.md` · las 8 skills de `.claude/skills/` · `docs/BACKLOG.md`
(header + tareas **abiertas** + *Acciones manuales pendientes*) · los 2 agents y los 4
commands · `docs/SETTINGS_REFERENCE.md`, `ARCHITECTURE.md`, `DB_SCHEMA.md` · y todo número
que aparezca en **dos o más lugares** del corpus.

**Explícitamente afuera:** los docs de veredicto (`docs/*_tNN_*.md`) — citan números de su
propia corrida, correctamente atribuidos, y **eso no es claim-decay**; sólo entran si afirman
algo sobre el *estado actual* en vez de sobre su corrida. También afuera: las tareas cerradas
del backlog, la corrección de código, y las otras cuatro áreas de la skill.

**Barrido limpio ⇔ (1)** toda afirmación fáctica del corpus verifica **verdadera** contra
código/datos/DB de hoy, **y (2)** ningún número aparece en dos lugares con valores distintos
sin que al menos uno declare su muestra.

**Resultado: NO fue un barrido limpio.** Siete hallazgos, ninguno refutado.

## 2. Las predicciones declaradas antes de mirar, y cómo salieron

Se declararon para no poder vender después como hallazgo lo ya sospechado. **Salieron mal, y
eso es lo que hace que la corrida haya valido la pena:**

| | predicción | resultado |
|---|---|---|
| **P1** | `backtest-replay-harness` cita 9.17% / 36,5% como vigentes | **imprecisa** — acertó la *familia* (números de la muestra vieja citados en presente) pero **erró los números**: los que están son **1.97%** y **3.23%** |
| **P2** | `CLAUDE.md` cita *"buy_score no predice el fwd5"* (jun-2026) como hecho vivo | **NO VERIFICADA** — exigiría re-correr la medición. No se reporta como hallazgo |
| **P3** | discrepancia 127 vs 128 tickers | **REFUTADA** — la watchlist de la cuenta 2 tiene exactamente **128** filas, y el desvío está **declarado** como el #1 de `deviations()` |

**Y el hallazgo de mayor severidad no estaba en ninguna predicción** (§4). Ésa es la
respuesta a *"¿el barrido aportó algo más allá de lo que ya sabía?"*: **sí, y era lo más
grande.**

## 3. Fase adversarial

Los cinco hallazgos con severidad ≥ MEDIA fueron al agente `verificador` con mandato de
**refutar**. **Ninguno se cayó**, pero el resultado no fue una confirmación pasiva:

- **bajó dos** (C-2 y C-5, de MEDIA a BAJA),
- **subió dos** (C-6 y C-7, a MEDIA-ALTA, tras probarlas en vivo),
- **agregó dos** que el barrido no había visto (B-1, B-2),
- **acotó la redacción de C-2**, que publicada como estaba se habría leído como una acusación
  al veredicto de la T39 — y **eso sí habría sido falso**.

Ese último punto es el que justifica la fase: el riesgo no era publicar un hallazgo
inexistente, era publicar uno cierto **con la conclusión equivocada pegada**.

---

## 4. El hallazgo raíz — y no estaba en ninguna predicción

### [R-1] Todos los jobs de fondo con alcance de cuenta defaultean a la cuenta PAUSADA

**Severidad: MEDIA-ALTA · Confianza: ALTA · Categoría: claims caducados → conducta viva**

Lo que empezó como tres claims caducados sueltos resultó ser **un solo defecto**: *todo* job
de fondo con alcance de cuenta apunta por default a la **1**, que está `is_active=0` desde el
2026-07-01, y **ninguno mira `is_active`**.

| | dónde | default |
|---|---|--:|
| refresh diario del dashboard | `paper_trading/scheduler.py:692` | 1 |
| rebuild de `surprise_profiles` | `paper_trading/scheduler.py:555` | 1 |
| harvest de catalysts | `scripts/harvest_catalysts.py:56` | 1 |

y el harvest lo heredan `analysis/news_digest.py:439,469` (el horario y el diario del
scheduler, que llaman **sin** `--account-id`), `scripts/daily_catalyst_harvest.bat:34`,
`build_surprise_profiles.py:41` y `scripts/news_feed.py:68`. Ninguno de los dos flags está
seteado en `~/.finanzias/settings.json`, así que todos toman el default.

**Probado en vivo, no deducido:**

- El dashboard: `…/Artifacts/finanzias-sim-principal-dashboard/index.html` tiene mtime de
  **hoy 15:51** y su `const DATA` dice `generated_at: 2026-09-01T18:51Z` con
  `account: {id: 1, is_active: 0}`, las 5 posiciones zombie y `last trade: 2026-07-01`. **Se
  re-estampa todos los días con fecha fresca mostrando una cartera congelada hace dos meses,
  y la cuenta viva no aparece nunca.**
- El harvest: la última fila de `news_events` es de **hoy 19:53**, sobre el universo de la
  cuenta 1 (**52** tickers) en vez del de la 2 (**128**). **79 de los 128** nombres del
  universo vivo no tienen **una sola** noticia en 45 días, y los 79 están fuera del universo
  de la cuenta 1. `data/catalyst/surprise_profiles.json` tiene exactamente **52** tickers.

**Lo que acota la severidad, y va publicado al lado o el informe exagera:** hoy esto **no
toca ninguna decisión de trading**. El único consumidor en el engine es el veto de salida
(`paper_trading/engine.py:1054-1061`), que exige `paper_catalyst_exit_veto_enabled` (default
`False`, no seteado) **y** un `catalyst_signal_provider` inyectado que ningún caller vivo
inyecta. El daño real es **cobertura de datos**, red gastada en el universo muerto, un
dashboard que miente con timestamp fresco — y una **bomba de tiempo**: el día que se prenda
el veto, arranca ciego sobre el **62%** del universo vivo.

**Y el encuadre que lo hace accionable:** del lado harness esto ya está resuelto —
`analysis/harness_config.py:71` tiene `LIVE_ACCOUNT_ID = 2` con banner y tests, que es
literalmente la tarea 27 — y **del lado app no existe el equivalente**. La corrección no es
arreglar tres defaults: es **una sola fuente de verdad para "la cuenta viva" en el lado app,
o un guard que grite cuando un job de fondo apunta a una cuenta con `is_active=0`**.

**Ojo con el arreglo:** poner el dashboard en 2 inyecta datos de la cuenta 2 en un artifact
llamado y titulado `sim-principal`. Hay que tocar también `DEFAULT_ARTIFACT` y el título, o
el dashboard pasa a mentir en la otra dirección.

---

## 5. Los hallazgos restantes

### [C-1] La skill manda usar una constante que la 68 borró — MEDIA · ALTA

`.claude/skills/backtest-replay-harness/SKILL.md:436` le indica a quien escriba un runner
nuevo usar `measured_on=WINDOW_REFRESH_2026_08_09`. Esa constante **no existe**:
`analysis/harness_config.py:1231-1232` define sólo `..._2026_09_01_LIVE` / `_LEGACY`, sin
alias ni `__getattr__` (verificado en runtime: `hasattr → False`), y
`tests/test_harness_config.py:475-482` **prohíbe activamente** el nombre viejo en todos los
`scripts/run_*.py`.

**Agravante:** la skill **nunca nombra las constantes nuevas** (`grep 2026_09_01` → cero), así
que desde ahí no hay camino al nombre correcto. Y la skill se tocó **hoy** (`7e67634`, tarea
62): no es un doc abandonado, es un archivo vivo que la 68 no barrió.

**Atenuante:** el modo de falla es **ruidoso** — ImportError al primer run, más el test rojo.
Por eso queda en MEDIA y no sube.

### [C-2] La skill afirma en presente un número que hoy no reproduce — BAJA · ALTA

`…/backtest-replay-harness/SKILL.md:166-167`: *"el sanity de reproducción devuelve el 1.97%
publicado al dígito"*. Tras la 68 devuelve **0.81%** (`SANITY_T33_CAGR` en
`run_rank_neutral_t39.py:97` y `run_prio_event_t49.py:118`).

**Redacción acotada a propósito** (lo pidió el verificador y tiene razón): el hallazgo es
*"la skill afirma en presente un número que hoy no reproduce, y es el único número que le da
al lector"*. **NO** es *"el veredicto de la T39 quedó mal"* — eso sería **falso**: aquella
corrida fue limpia y `docs/reanchor_t68_2026-09-01.md` §6 declara explícitamente que ningún
veredicto se re-publica.

### [C-5] `SETTINGS_REFERENCE.md` llama "cuenta activa" a la pausada — BAJA · ALTA

Línea 5: *"La cuenta activa «Sim Principal» corre en modo kill_only"*. La activa es la 2.

**Pero el contenido del párrafo es correcto** y está verificado: en el settings vivo
`hmm_enabled=False`, `stacking_enabled=False`, `xgb_signal_enabled=True`,
`vol_overlay_enabled=True`, y como `hmm`/`stacking` tienen default `True` en el spec, la
advertencia *"kill_only pisa defaults"* sigue siendo útil y verdadera. Es una **etiqueta
caduca en un párrafo cierto**, no una afirmación operativa falsa — de ahí la severidad baja.

Segundo eje, más fino: **`kill_only` no es un atributo de cuenta**. No existe como flag
(`config/settings_manager.py:194`, sólo un comentario); es un perfil del `settings.json`, que
es **global**. Colgarlo de un nombre de cuenta es impreciso en dos ejes, no en uno.

**Lo que vale publicar es el encuadre:** la tarea 30 corrigió este mismo claim en `CLAUDE.md`
y en el header del backlog, y **no barrió `SETTINGS_REFERENCE.md`**. Es una **corrección
incompleta** — la misma clase de claim, en un tercer lugar.

### [C-7 · doc] `CLAUDE.md` se contradice consigo mismo — parte de R-1

`CLAUDE.md:20` manda `python scripts/harvest_catalysts.py --account-id 1`, y `CLAUDE.md:24`
dice que la cuenta 1 está pausada y que *"toda verificación en vivo va contra la 2"*. Ídem
`.claude/skills/catalyst-pipeline/SKILL.md:15`. La parte de conducta viva está en R-1.

### [B-1] El runner T49 se contradice a sí mismo en su propio log — MEDIA · ALTA

*(Hallazgo del verificador, no del barrido.)*
`scripts/run_prio_event_t49.py:544-551` tiene los valores esperados **hardcodeados como
literales de string**, no interpolados desde las constantes:

```python
f"E_analyze {100 * r_analyze['cagr']:.2f}% (esperado 3.71%) · "
f"E_merged_prio {100 * r_merged['cagr']:.2f}% (esperado 7.92%) · "
f"(esperado 1.97%) · {repro['t33_state']}",
```

Las constantes contra las que el chequeo **realmente** compara son `0.0347`, `0.0761` y
`0.0081` (líneas 118-124, re-ancladas por la 68). O sea que una corrida de hoy imprime
literalmente **`E_analyze 3.47% (esperado 3.71%) · OK`**: el runner se contradice y el `OK`
parece un bug de cañería. El patrón correcto está a dos archivos:
`run_rank_neutral_t39.py:631` y `run_anom_profile_t45.py:480-481` interpolan la constante.
Sin test que lo cubra. Menor: `run_rank_neutral_t39.py:20` también dice 1.97% en el docstring.

### [B-2] `SETTINGS_REFERENCE.md` documenta como `SettingSpec` dos flags que no existen — BAJA · ALTA

*(Hallazgo del verificador.)* El header del doc dice *"Flags definidos en
`config/settings_manager.py` (cada uno es un `SettingSpec`…)"*, pero `dashboard_refresh_enabled`
y `dashboard_refresh_account_id` (líneas 92-96) **no están en el `SCHEMA`**: sólo existen como
`settings.get(..., default)` en `scheduler.py:692,700,712`. Se pueden setear igual —
`config/settings_manager.py:650-657` acepta claves desconocidas — pero no están validadas.

### [A-1] La skill `auditoria` nació con un claim caducado — BAJA · ALTA

*(Hallazgo sobre trabajo propio, escrito hace 20 minutos.)*
`.claude/skills/auditoria/SKILL.md:111` pregunta *"¿Hay un **séptimo** desvío que
`deviations()` no nombra?"* y lista seis. Pero `analysis/harness_config.py:699` ya numera
**el séptimo** (la ventana rodante, T48). La pregunta correcta es *"¿hay un **octavo**?"*.
Se publica a propósito: es la demostración más barata de que el corpus operativo caduca
**en semanas**, no en meses.

---

## 6. Alcance NO mirado

- **`docs/*_tNN_*.md`** (los ~20 docs de veredicto), afuera por kill-criteria.
- **P2 sin verificar:** *"`buy_score` no predice el fwd5"* (`CLAUDE.md:11`) sigue citado como
  hecho vivo desde junio. Verificarlo exige re-correr la medición — **no se hizo, y por eso
  no se reporta como hallazgo**. Queda anotado como lo que es: un claim de tres meses que
  nadie re-chequeó y que sostiene la **regla 3** del proyecto.
- Las tareas **cerradas** del backlog.
- Las otras cuatro áreas de la skill: `muestra`, `desvios`, `guards`, `estado`.
- `docs/DB_SCHEMA.md` y `docs/ARCHITECTURE.md` se barrieron **sólo** por claims de cuenta
  activa/config, no exhaustivamente.

## 7. Lo que la corrida deja como método

**El corpus operativo caduca más rápido que los docs de veredicto, y es el que más se lee.**
Un doc de veredicto cita su propia muestra y envejece bien porque está atribuido. Una
**skill** afirma en presente y se lee **cada sesión**: cuando su número deja de valer, dirige
mal. Cinco de los siete hallazgos son de corpus operativo, y **dos los introdujo el trabajo
de hoy mismo** (C-1 por la 68, A-1 por la propia skill de auditoría).

**Corolario para el cierre de tareas:** cuando una tarea mueve una constante o un default, el
barrido no termina en el código — sigue en las skills, en `CLAUDE.md` y en los docs de
referencia. La 68 re-ancló 17 constantes en 7 runners y dejó la skill apuntando al nombre
muerto; la 30 corrigió el claim de cuenta activa en dos de **tres** lugares.
