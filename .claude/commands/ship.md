---
description: Corre la suite y, si está verde, commitea según la convención del repo
allowed-tools: Bash(python -m pytest:*), Bash(python scripts/run_suite_sin_estado_vivo.py:*), Bash(python scripts/check_repo_health.py:*), Bash(python scripts/check_backlog_integrity.py:*), Bash(python -m ruff:*), Bash(git:*)
---

Cerrá el trabajo en curso siguiendo el flujo del proyecto:

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
      - `python scripts/check_repo_health.py --staged` — reglas 4 y 5 de `CLAUDE.md`. Si
        reporta problemas (CRLF en .bat, null-bytes, DB desde no-Windows), **PARÁ** y arreglalos.
      - `python scripts/check_backlog_integrity.py --staged` — integridad de `docs/BACKLOG.md`.
        Es la mitad del guard de la tarea 66 que **necesita el diff** y por lo tanto no puede
        correr en la suite: frena un commit que le saque más de 60 líneas netas al backlog,
        que es exactamente lo que pasó el 2026-08-31 y pasó invisible cuatro commits.
   b. Mostrame `git status --short` y `git diff --stat` para confirmar qué entra.
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
5. Si la tarea estaba en `docs/BACKLOG.md`, movela a *Hecho reciente* con el hash del commit.
6. NO hagas `git push` salvo que te lo pida.

Recordá que el verde definitivo es en Windows (Anaconda); avisame si esto corre en otro entorno.
