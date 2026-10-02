# Auditoría — guards (con el CI) — 2026-10-02

Tarea **275**. READ-ONLY. Kill-criteria congelado en `docs/auditoria_tanda_killcriteria_2026-10-02.md` §8–12 (`guards`).

## 1. Alcance real

**Mirado:**
- **El guard nuevo de la 251**, `spy_coverage_problems` (`analysis/harness_config.py:824-848`), probado por **mutación en el sentido del falso positivo**: una SPY sintética que cubre los extremos y tiene un hueco **en el medio** del cohorte. Contra la SPY real, se midieron sus huecos contra el calendario del cohorte.
- **El CI** (`.github/workflows/ci.yml`), primera vez dentro de esta área (la 274):
  - los `continue-on-error`, qué corre contra el *done* de `CLAUDE.md` y las versiones;
  - las conclusiones de los jobs en la última corrida y en otras doce desde el 2026-09-07, leídas por la API pública de Actions.
- ***«Los guards de la UI»***, que la 2026-09-30b dejó afuera: los confirmes de restore, de venta y de re-arme de alertas.

**NO mirado:**
- Los guards de la 252/253 por mutación. Motivo: la 253 cerró con el refresh de SPY verificado por su propio chequeo de cobertura, el mismo que acá se mutó.

## 2. Hallazgos

### [GD-1] El guard de la 251 acepta una SPY con un hueco de 40 ruedas en medio del cohorte
Severidad: **LOW** · Confianza: **ALTA**

**Evidencia:** sobre un cohorte sintético, `spy_coverage_problems(spy_completa)` y `spy_coverage_problems(spy_sin_2026-06-17…2026-08-11)` devuelven los dos `[]`: *«cubre»*.

**Razonamiento:** el guard mira sólo dos cosas, que la **última** fecha de SPY no esté atrasada y que haya suficientes ruedas antes de la primera entrada (un conteo, `previas`). Un hueco interno congela la bandera de régimen en esas ruedas, que es exactamente el daño que la 251 vino a tapar en la cola. Es la forma de la categoría B: *el largo, no la ventana*.

**Exposición hoy:** ninguna. `SPY__10y` va del 2016-10-03 al 2026-10-01 y no le falta ninguna rueda del calendario de AAPL.

**Acción:** que el guard compare **fechas**: las ruedas del calendario del cohorte que no están en SPY.

→ tarea **285**.

## 3. Barrido limpio en lo demás

- **CI:**
  - los dos jobs que gatean (`lint + format`, `pytest`) cubren la suite y ruff;
  - el cuarto comando del *done* (la suite sin estado vivo) **es** la condición del CI, por construcción (la 176);
  - `mypy (best-effort)` sale en `failure` en todas las corridas miradas desde el 2026-09-07, tapado por `continue-on-error`. No es hallazgo: es deuda de tipado declarada (1.074 errores, la 65), con el motivo escrito en el workflow;
  - `pip-audit` sale `success`, pero audita las versiones del CI y no las de la Anaconda: eso es `dependencias` [K-4], con tarea.
- **Confirmes de la UI:**
  - la venta pide confirmación (`confirm_sell` → `dialogs.py:496`);
  - el re-arme de alertas es diario y en el mismo chequeo (la 227);
  - el confirme del restore existe, pero el restore no hace lo que confirma: eso es `operacion` [B-1], con tarea.

## 4. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| GD-1 | 285 |
