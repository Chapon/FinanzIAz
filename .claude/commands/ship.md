---
description: Corre la suite y, si está verde, commitea según la convención del repo
allowed-tools: Bash(python -m pytest:*), Bash(python scripts/run_suite_sin_estado_vivo.py:*), Bash(python scripts/check_repo_health.py:*), Bash(python scripts/check_backlog_integrity.py:*), Bash(python scripts/check_ci.py:*), Bash(python -m ruff:*), Bash(git:*)
---

Cerrá el trabajo en curso siguiendo el flujo del proyecto:

0. **Primero el backlog, después el done** (tarea 339). Si la tarea está en `docs/BACKLOG.md`,
   escribí **ahora** todo lo que el cierre le agrega: el registro con el detalle, la nota de
   repriorización y las tareas que dejan los hallazgos (regla 6). Entra en el commit de la tarea;
   el hash se agrega después (paso 8), porque todavía no existe.
   **Por qué va antes:** el backlog es parte del corpus que leen los guards de la suite. La 322
   dejó el CI en ROJO (`9884a4e`) porque los cuatro comandos corrieron **antes** de escribir el
   backlog y después sólo los tests de backlog: el guard de la 72 tomó un nombre del texto nuevo.
   **Regla: el done va después de la ÚLTIMA edición, también la del backlog.** Si después del
   paso 1 cambia cualquier archivo —el backlog incluido, por chico que sea el cambio—, se vuelven
   a correr los cuatro comandos. Correr sólo `pytest -k backlog` no alcanza: así se cerró cinco
   veces el 2026-10-07 y no dio rojo por suerte.
1. Corré el criterio de **done**, que son cuatro comandos y no uno:
   - `python -m pytest tests/ -ra -m "not network" --tb=short`
   - `python -m ruff check .`
   - `python -m ruff format --check .`
   - `python scripts/run_suite_sin_estado_vivo.py`

   **Los dos últimos entraron por el MISMO defecto, encontrado dos veces:** el CI en rojo
   mientras las tareas se cerraban en verde, porque el done no lo miraba.
   - **Ruff, tarea 106:** el 2026-09-02 el job `lint` quedó en rojo y **trece tareas** se
     cerraron declarando "suite verde" — lo estaban, pero el done no incluía ruff. Si
     `ruff check` falla, arreglalo con `ruff check --fix .` + `ruff format .` y **revisá el
     diff** antes de seguir.
   - **Modo sin estado vivo, tarea 176:** el 2026-09-09 el job `pytest` quedó en rojo —en el
     mismo commit que shipeó el guard de la tarea 130— y **36 tareas** se cerraron declarando
     "suite Windows verde", que era **verdad**: el test leía `~/.finanzias/settings.json`, que
     en la máquina de Chapa **existe** y en el CI no. 35 corridas; lo reportó Chapa, no el
     proceso. Este comando corre la misma suite con `HOME`/`USERPROFILE` en un directorio
     vacío. Si falla, el fallo es real y estaría rojo en el CI aunque los otros tres pasen.
2. **Si hay algún fallo, PARÁ** y mostrame qué falló. No commitees con tests rojos.
3. Si pasa todo:
   a. Corré los **dos** guards de `--staged`, que son el único cableado operativo que tienen
      (no hay hooks de git instalados en este repo — tarea 97):
      - `python scripts/check_repo_health.py --staged` — regla 4 de `CLAUDE.md` y los null-bytes.
        Si reporta problemas (CRLF en .bat, CRLF en versionados, null-bytes), **PARÁ** y arreglalos.
        La regla 5 (no escribir la DB desde Linux) **no** la chequea: es manual (tarea 250).
      - `python scripts/check_backlog_integrity.py --staged` — integridad de `docs/BACKLOG.md`.
        Es la mitad del guard de la tarea 66 que **necesita el diff** y por lo tanto no puede
        correr en la suite: frena un commit que le saque más de 60 líneas netas al backlog,
        que es exactamente lo que pasó el 2026-08-31 y pasó invisible cuatro commits. Y desde
        la tarea 195, frena también un commit que **escriba una repriorización** dejando fuera
        del `El orden queda …` una tarea abierta — así se perdió la 180 el 2026-09-12.
   b. Mostrame `git status --short` y `git diff --stat` para confirmar qué entra.
      **Si aparece `data/catalyst/surprise_profiles.json` modificado y la tarea no lo tocó**
      (tarea 286): lo reescribe el rebuild semanal del scheduler, y es versionado por decisión (la
      173). Va en un commit **aparte**, antes del de la tarea:
      `chore(catalyst): refresh surprise_profiles.json (rebuild del scheduler <fecha>)` —la fecha es `_meta.built_at`—, como
      `6d19390`. Nunca dentro del commit de la tarea —así se coló en el de la 262— y nunca
      descartados con `git checkout`: es el artefacto que lee la app. (`historical_reaction.json`
      **no** lo reescribe ningún job: sólo `scripts/build_historical_reaction.py`, a mano, y lo lee
      un backtest. Si aparece modificado, alguien corrió ese script — tarea 296.)
   c. Hacé `git add` de la unidad lógica completa (código + tests + docs).
   d. Commiteá siguiendo la skill `git-workflow`: subject `tipo(scope): ...` o `T<n>: ...` en español, cuerpo con qué/por qué + línea `Suite: NNN passed`, y trailer `Co-Authored-By`.
4. **Si el cambio movió una CONSTANTE, un DEFAULT o el nombre de un símbolo, barré el corpus
   operativo antes de commitear** — `CLAUDE.md`, las skills de `.claude/`, los commands, los
   agents, `docs/SETTINGS_REFERENCE.md` **y la sección *Acciones manuales pendientes* de
   `docs/BACKLOG.md`**. Esa última entró el 2026-09-07 y por un motivo concreto: al bajar
   `paper_regime_scale_factor` de 0.50 a 0.25 el barrido cazó el `SettingSpec`, la referencia y
   el espejo de `harness_config`, y **dejó pasar** la nota de verificación de R2b, que seguía
   diciendo *"factor 0.50 · medio tamaño · ×0.5"*. Las acciones manuales **afirman en presente**
   igual que una skill, y encima son las que Chapa ejecuta a mano: una nota caducada ahí no
   confunde, **dirige mal**. El barrido **no termina en el código**: eso es lo
   que dejó la 68 mandando a usar una constante que ella misma había borrado, y a la 30
   corrigiendo su claim de "cuenta activa" en **dos de tres** lugares. Un test cubre la mitad
   mecánica (`tests/test_corpus_operativo_t72.py` caza un símbolo que no existe); lo que **no**
   cubre y hay que mirar a ojo son los **números y las afirmaciones en presente** — una skill
   se lee cada sesión, así que cuando su número deja de valer, **dirige mal**.
5. (El backlog ya se escribió en el paso 0, antes del done: acá no se edita.)
6. `git push` a `origin/main`: es parte del cierre (orden de Chapa del 2026-07-15, skill
   `git-workflow`). Hasta la tarea 300 este paso prohibía pushear sin un pedido explícito, que
   contradecía esa orden; se corrigió porque el paso 7 necesita el commit pusheado.
7. **Leé el CI del commit pusheado: `python scripts/check_ci.py --esperar`** (regla 7 de
   `CLAUDE.md`, tarea 300). Espera a que el run termine (hasta 15 min) y sale `0` verde, `1` rojo
   o `2` no se sabe.
   - **Rojo ⇒ la tarea NO está cerrada.** El script muestra el job y los tests que fallaron:
     arreglalo en un commit nuevo y volvé a este paso. No arranques otra tarea con el CI rojo.
   - **No se sabe** (sin red, cuota de la API, espera agotada) ⇒ el cierre dice *«CI sin
     verificar»*, nunca *«verde»*, y la próxima tarea arranca con `--ultimo`.
   - **Por qué:** los cuatro comandos corren en Windows y lo que sólo rompe en Linux lo ve
     únicamente el CI. Tres veces quedó rojo mientras las tareas se cerraban en verde: la 106
     (13 tareas), la 175 (36) y la 300 (17, por un test con rutas de Windows literales).
8. **Con el CI en verde, el hash.** Agregá el hash del commit de la tarea a su registro en el
   backlog (en el registro del cierre y en el título de la tarea), **mové el registro de
   *En curso* a la cabeza de *Hecho reciente*** —*En curso* queda con *«Nada en marcha»* o con
   la tarea que arranca; el guard acusa más de un ítem (tarea 338)— y commiteá aparte:
   `docs(backlog): hash de cierre de la tarea NN (CI verde)`. Es una edición **posterior** al
   done, así que vale la regla del paso 0: los cuatro comandos otra vez, los guards de `--staged`,
   push, y `check_ci.py --esperar` sobre ese commit también.

Recordá que el verde definitivo es en Windows (Anaconda); avisame si esto corre en otro entorno.
