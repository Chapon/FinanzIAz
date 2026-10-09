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
- **Al cerrar una tarea, después de actualizar el backlog, se pushea a `main`** (orden de Chapa 2026-07-15). El cierre completo es: escribir el cierre en el BACKLOG (registro, repriorización, hallazgos) → **los cuatro comandos en verde** → commit → `git push origin main` → **`python scripts/check_ci.py --esperar` en verde** (regla 7 de `CLAUDE.md`, tarea 300) → el hash en el BACKLOG, en un commit aparte que repite el done y el CI. **El done va después de la última edición, también la del backlog** (tarea 339): la 322 dejó el CI rojo por correrlo antes de escribir el backlog. No dejar tareas cerradas sin pushear, ni darlas por cerradas con el CI en rojo.

## Checklist rápido

1. Escribir el cierre en el BACKLOG si corresponde (registro con el detalle, repriorización, tareas de los hallazgos) — **antes** del done, no después (tarea 339).
2. Los cuatro comandos en verde en Windows, **después de la última edición**. Si algo cambia después —el backlog incluido—, se corren de nuevo.
3. `git status` / `git diff --stat` — sin artefactos basura.
4. `git add` de la unidad lógica completa (código + tests + docs + backlog).
5. Commit con subject en el formato correcto + cuerpo si el cambio es grande + trailer Co-Authored-By.
6. `git push` a origin/main — **siempre al cerrar una tarea, no queda nada cerrado sin pushear**.
7. `python scripts/check_ci.py --esperar` — **el CI del commit pusheado en verde, leído y no supuesto.** Rojo ⇒ la tarea no está cerrada; *no se sabe* ⇒ el cierre dice *«CI sin verificar»*. Tres veces el CI quedó rojo con las tareas cerrándose en verde (106, 175, 300): este paso es el que faltaba.
8. Con el CI verde, el hash en el BACKLOG y el registro movido de *En curso* a la cabeza de *Hecho reciente* (máx 1 en *En curso*, lo verifica el guard — tarea 338): commit aparte `docs(backlog): hash de cierre de la tarea NN (CI verde)`, que es otra edición y repite los pasos 2, 6 y 7.
