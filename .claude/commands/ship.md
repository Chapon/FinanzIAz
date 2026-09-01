---
description: Corre la suite y, si está verde, commitea según la convención del repo
allowed-tools: Bash(python -m pytest:*), Bash(python scripts/check_repo_health.py:*), Bash(git:*)
---

Cerrá el trabajo en curso siguiendo el flujo del proyecto:

1. Corré la suite: `python -m pytest tests/ -ra -m "not network" --tb=short`.
2. **Si hay algún fallo, PARÁ** y mostrame qué falló. No commitees con tests rojos.
3. Si pasa todo:
   a. Corré el guard de salud: `python scripts/check_repo_health.py --staged`. Si reporta problemas (CRLF en .bat, null-bytes, DB desde no-Windows), **PARÁ** y arreglalos.
   b. Mostrame `git status --short` y `git diff --stat` para confirmar qué entra.
   c. Hacé `git add` de la unidad lógica completa (código + tests + docs).
   d. Commiteá siguiendo la skill `git-workflow`: subject `tipo(scope): ...` o `T<n>: ...` en español, cuerpo con qué/por qué + línea `Suite: NNN passed`, y trailer `Co-Authored-By`.
4. **Si el cambio movió una CONSTANTE, un DEFAULT o el nombre de un símbolo, barré el corpus
   operativo antes de commitear** — `CLAUDE.md`, las skills de `.claude/`, los commands, los
   agents y `docs/SETTINGS_REFERENCE.md`. El barrido **no termina en el código**: eso es lo
   que dejó la 68 mandando a usar una constante que ella misma había borrado, y a la 30
   corrigiendo su claim de "cuenta activa" en **dos de tres** lugares. Un test cubre la mitad
   mecánica (`tests/test_corpus_operativo_t72.py` caza un símbolo que no existe); lo que **no**
   cubre y hay que mirar a ojo son los **números y las afirmaciones en presente** — una skill
   se lee cada sesión, así que cuando su número deja de valer, **dirige mal**.
5. Si la tarea estaba en `docs/BACKLOG.md`, movela a *Hecho reciente* con el hash del commit.
6. NO hagas `git push` salvo que te lo pida.

Recordá que el verde definitivo es en Windows (Anaconda); avisame si esto corre en otro entorno.
