---
name: git-workflow
description: Convención de git de FinanzIAs — formato de mensajes de commit, qué se agrupa en un commit, flujo de ramas y push. Usar SIEMPRE antes de hacer git commit o git push en este repo, para que el mensaje y el flujo coincidan con el historial existente.
---

# Git workflow — FinanzIAs

Convención extraída del historial real del repo. Mantener consistencia con los commits previos.

## Antes de commitear

- **La suite tiene que estar verde en Windows** (`python -m pytest tests/ -ra -m "not network" --tb=short`). No se commitea con tests rojos. Ver skill `finanzias-conventions`.
- Verificar que no entren artefactos no deseados (`.bat` con LF en vez de CRLF, archivos con null-bytes, la DB viva). `git status` y `git diff --stat` antes de `git add`.

## Formato del subject (primera línea)

Dos estilos válidos, según el tipo de cambio:

1. **Conventional Commits** para cambios generales:
   `tipo(scope): descripcion`
   Tipos usados: `feat`, `fix`, `perf`, `chore`, `docs`.
   Ejemplos reales:
   - `feat(exits): modelar fill realista (gap/touch) en salidas ATR + no expirar avisos de riesgo`
   - `fix(db): WAL + busy_timeout para evitar "database is locked"`
   - `perf(data): batch yfinance downloads + scan cache warm-up to cut 401`
   - `chore(catalyst): refresh surprise_profiles.json (datos yfinance actualizados)`

2. **Prefijo de tarea** para trabajo del roadmap (sprints / T-CAT):
   `T<n>.<m>: descripcion` o `T-CAT-<n> <fase>: descripcion`
   Ejemplos reales:
   - `T6.4: score-hysteresis en exits — SELLs de señal esperan 3 días hábiles salvo score < 0.25`
   - `T-CAT-4: Impact Score heurístico v1 + exit-veto (Gate 2c, default OFF)`

Reglas del subject:
- En **español** (rioplatense). Los subjects llevan tildes normales (`Métricas`, `señal`, `días`).
- Sin punto final. Imperativo/descriptivo. Conciso pero específico.
- Se permite `+` para unir dos cambios relacionados en un subject.

## Cuerpo del commit (opcional pero habitual en cambios grandes)

- Separado del subject por una línea en blanco. Envuelto a ~72 columnas.
- Explica **qué cambió y por qué**, no el cómo obvio. Bullets con `-` para listar cambios.
- Si corresponde, una línea con el resultado de la suite: `Suite: 855 passed, 1 skipped`.
- Observación del historial: los **cuerpos tienden a ASCII sin tildes** (`historica`, `via`, `Ademas`) — probablemente para evitar problemas de encoding en consola Windows. Seguir ese patrón en el cuerpo si hay dudas de encoding.

## Trailer

Agregar al final, separado por línea en blanco:
```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```
(Usar el modelo que corresponda; el historial tiene `Claude Opus 4.8`.)

## Agrupación (qué va en un commit)

- **Un commit = una unidad lógica completa y testeada**: código + sus tests + docs relacionados juntos. Ej.: `feat(ui): add Métricas tab` incluyó la tab, `analysis/metrics_panel.py`, `tests/test_metrics_panel.py` y el doc de auditoría.
- Las migraciones alembic van con el código que las necesita.
- Refactors de comportamiento neutro pueden ir en su propio commit (`perf(data): ...` separó el batch download).

## Ramas y push

- **Trunk-based**: se trabaja directo sobre `main`. No hay ramas de feature ni PRs en el historial.
- Push directo: `git push` a `origin/main`.
- Pushear sólo después de que la suite pase en Windows y el commit esté completo (no fragmentos a medias).
- **Al cerrar una tarea, después de actualizar el backlog, se pushea a `main`** (orden de Chapa 2026-07-15). El cierre completo es: suite verde → commit → mover la tarea a *Hecho reciente* en el BACKLOG con el hash → `git push origin main`. No dejar tareas cerradas sin pushear.

## Checklist rápido

1. Suite verde en Windows.
2. `git status` / `git diff --stat` — sin artefactos basura.
3. `git add` de la unidad lógica completa (código + tests + docs).
4. Commit con subject en el formato correcto + cuerpo si el cambio es grande + trailer Co-Authored-By.
5. Actualizar el BACKLOG (mover la tarea a *Hecho reciente* con el hash) si corresponde.
6. `git push` a origin/main — **siempre al cerrar una tarea, no queda nada cerrado sin pushear**.
