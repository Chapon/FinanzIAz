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
4. Si la tarea estaba en `docs/BACKLOG.md`, movela a *Hecho reciente* con el hash del commit.
5. NO hagas `git push` salvo que te lo pida.

Recordá que el verde definitivo es en Windows (Anaconda); avisame si esto corre en otro entorno.
