# Auditoría — muestra — 2026-10-02

Tarea **275**. READ-ONLY. Kill-criteria congelado en `docs/auditoria_tanda_killcriteria_2026-10-02.md` §8–12 (`muestra`).

## 1. Alcance real

**Mirado:**
- **El código nuevo de la 256**: `paper_trading/scan_candidates.py` (poda y conteo) y `scripts/por_que_no_compramos.py`, que cuenta scans por día con `paper_equity_snapshots` y deriva *«sin scans»* y *«nunca fue candidato»*. Se corrió sobre una ventana **anterior** al registro (ACN, 2026-07-06 a 07-10), que es la que distingue un conteo bien acotado de uno ciego.
- **Las mediciones de la 255 y la 258**, en lo que toca a la muestra: la cobertura de frames, la `n` por grupo y las rondas.
- **El refresh de SPY de la 251/253**, como operación que mueve la muestra.

**NO mirado:**
- Los runners de harness anteriores a la 251. Motivo: los cubrió la 2026-09-30b.

## 2. Hallazgos

### [M-1] `por_que_no_compramos.py` rotula *«sin scans (la app no corrió)»* a todo día sin snapshot, y un scan que falla tampoco deja snapshot
Severidad: **LOW** · Confianza: **ALTA**

**Ubicación:** `scripts/por_que_no_compramos.py:68-69` (`leyenda`).

**Razonamiento:**
- `record_equity_snapshot` se llama sólo al final de un `run_scan` completado (`paper_trading/engine.py:1563`).
- Con la 263 abierta (un scan que lanza una excepción no deja rastro), un día de scans fallidos se lee como *«la app no corrió»*. El conteo es correcto; **la causa que afirma la leyenda, no siempre**.

**Acción:** rotular *«sin scans completados»*, o distinguir con el registro de fallas que agregue la 263.

→ va en el enunciado de la **263**.

## 3. Barrido limpio en lo demás

- **El acotamiento al registro está en el código:** los scans se cuentan desde `max(--desde, primer día con candidatos)` (`por_que_no_compramos.py:116`). Sobre julio el script imprime sólo *«registro desde 2026-10-02 16:29»* y ninguna línea de día: no puede afirmar *«nunca fue candidato»* para un día sin registro.
- **La poda** filtra por cuenta y fecha, y devuelve la cantidad de filas borradas (`scan_candidates.py:161-165`). No decide nada por conteo.
- **La 255 y la 258** miden cobertura **por fechas** (la última fecha de cada frame) y no por cantidad. La 255 detectó así que 123 de 131 frames `1y` terminaban el 2026-09-09 y repitió con `2y`. La `n` de cada grupo se reporta junto a las rondas y al MDE. El duplicado entre fuentes (2,7%, `docs/auditoria_datos_2026-10-02.md` [D-1]) infla la `n` sin cambiar los veredictos.
- **El refresh de SPY** (la 251/253): la 251 hizo que los runners de régimen **aborten** si la serie de SPY no cubre el cohorte, y el `verificador` de la 2026-09-30b midió que la desalineación no cambia el régimen en ningún día hasta ~18 meses. No queda ningún veredicto movido sin re-mirar.

## 4. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| M-1 | 263 (en el enunciado) |
