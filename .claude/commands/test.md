---
description: Corre la suite de tests (sin los que pegan a red)
allowed-tools: Bash(python -m pytest:*)
---

Corré la suite de tests del proyecto y reportá el resultado:

```
python -m pytest tests/ -ra -m "not network" --tb=short
```

Si pasan todos, confirmá el conteo (`NNN passed, M skipped`). Si hay fallos, mostrá los tests que fallaron y un diagnóstico breve de la causa probable. Recordá: el entorno real es Windows + Anaconda — un verde acá no equivale a "done" hasta correrlo en Windows (ver `CLAUDE.md`).
