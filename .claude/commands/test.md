---
description: Corre la suite de tests (sin los que pegan a red)
allowed-tools: Bash(python -m pytest:*), Bash(python -m ruff:*)
---

Corré el criterio de **done** del proyecto y reportá el resultado. Son **tres** comandos,
no uno (tarea 106 — el job `lint` del CI estuvo en rojo mientras trece tareas se cerraban
declarando "suite verde", porque el done no incluía ruff):

```
python -m pytest tests/ -ra -m "not network" --tb=short
python -m ruff check .
python -m ruff format --check .
```

Si pasan todos, confirmá el conteo (`NNN passed, M skipped`) **y** que ruff salió limpio.
Si ruff falla, decilo aparte de la suite: se arregla con `ruff check --fix .` + `ruff format .`,
revisando el diff. Si hay fallos, mostrá los tests que fallaron y un diagnóstico breve de la causa probable. Recordá: el entorno real es Windows + Anaconda — un verde acá no equivale a "done" hasta correrlo en Windows (ver `CLAUDE.md`).
