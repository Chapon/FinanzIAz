---
description: Corre la suite de tests (sin los que pegan a red)
allowed-tools: Bash(python -m pytest:*), Bash(python -m ruff:*), Bash(python scripts/run_suite_sin_estado_vivo.py:*)
---

Corré el criterio de **done** del proyecto y reportá el resultado. Son **cuatro** comandos,
no uno. Los dos agregados salieron del mismo defecto encontrado dos veces — el CI en rojo
mientras las tareas se cerraban en verde: ruff por la **tarea 106** (trece tareas) y el modo
sin estado vivo por la **tarea 176** (treinta y seis tareas, 35 corridas):

```
python -m pytest tests/ -ra -m "not network" --tb=short
python -m ruff check .
python -m ruff format --check .
python scripts/run_suite_sin_estado_vivo.py
```

Si pasan todos, confirmá el conteo (`NNN passed, M skipped`) **y** que ruff salió limpio
**y** que el modo sin estado vivo pasó. Ese último corre la misma suite con `HOME` apuntando a
un directorio vacío, o sea en la condición del CI: es el que caza un test que lea
`~/.finanzias/settings.json` —que en la máquina de Chapa **existe**— y por lo tanto pase acá y
falle allá. Su conteo normal difiere en 1 skip del primero, y eso es correcto: el test que
compara contra el settings vivo se saltea cuando no hay con qué comparar.
Si ruff falla, decilo aparte de la suite: se arregla con `ruff check --fix .` + `ruff format .`,
revisando el diff. Si hay fallos, mostrá los tests que fallaron y un diagnóstico breve de la causa probable. Recordá: el entorno real es Windows + Anaconda — un verde acá no equivale a "done" hasta correrlo en Windows (ver `CLAUDE.md`).
