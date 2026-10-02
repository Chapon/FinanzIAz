# Auditoría — claims — 2026-10-02

Tarea **275**. READ-ONLY. Kill-criteria congelado en `docs/auditoria_tanda_killcriteria_2026-10-02.md` §8–12 (`claims`).

## 1. Alcance real

**Mirado:**
- **Docstrings que afirman cableado vivo.** El método generaliza la 270: el grafo de imports desde `main.py` (AST, imports locales incluidos; 97 módulos alcanzables) contra los docstrings de `paper_trading/`, `analysis/` y `data/` que mencionan `run_scan`, *en vivo*, *cableado* o *consuming gate*.
  - **Instrumento validado:** encuentra el caso conocido (`dd_breaker.py`).
- **Los claims vivos de `CLAUDE.md`**, contra el settings vivo y la DB: flags de modelo, cuenta activa, modo, slots, cuenta 1 inactiva, el `1 deselected`.
- **Los claims que agregaron hoy la 260, la 271 y la 274 a la skill de auditoría**, cada número contra su tarea de origen: 389 (la 197), 163 s (la 237), ~1.800× (la 74), 16× (la 204), 35 corridas (la 176), 22 días hábiles (la 261), nueve episodios y $51.093 (la 93), cuatro valores (la 259), cuatro nombres (la 149), 2,793 (la 63).
- ***«Docs de veredicto de tareas cerradas»***, que la 2026-09-30b dejó afuera: los números decimales de las entradas de la 255 y la 258 en el backlog, contra sus docs (`docs/noticias_impacto_t255_2026-10-01.md`, `docs/noticias_tono_t258_2026-10-01.md`).
- **Las frases que corrigieron las tareas cerradas desde el 2026-09-30**, buscadas con `grep` en todo el repo (*«impacto esperado»*, *«prefers id=1»*).

**NO mirado:**
- Los docs de veredicto anteriores a la 251. Motivo: los cubrió la corrida 2026-09-30b, salvo esta exclusión, que se cerró para lo nuevo.

## 2. Hallazgos

Ningún hallazgo **nuevo** en esta área. Los dos de esta forma ya tienen tarea:
- `paper_trading/dd_breaker.py` afirma un gate en `run_scan` que no existe → la **270**, de la medición de cobertura.
- Home resolvía *«prefers id=1»* → la **264** (la 261, [F-1]).

## 3. Barrido limpio en lo demás

- **Cableado declarado contra real:** fuera de `dd_breaker.py`, el único docstring que matchea y no es alcanzable es `analysis/meta_labeling.py`, y dice *«Nada de este módulo está cableado a decisiones»*: es cierto (falso positivo del patrón).
- **`CLAUDE.md`:**
  - `hmm_enabled = false` y `stacking_enabled = false` en el settings vivo, mientras el código los lee con `default=True` (`analysis/technical.py:733, 856`), como dice la 181;
  - cuenta 2 *Sim Segundo* `auto`, `equal_weight`, `max_positions = 10`, activa; cuenta 1 `is_active = 0`;
  - watchlist de 127;
  - el `1 deselected` de cada corrida es el test marcado `network`.
  - La línea 22 (*«recolectaba para 52 tickers en vez de 128»*) habla de antes de la 70 y es historia, no estado.
- **Los números nuevos de la skill** coinciden con sus tareas de origen.
- **Veredictos 255 y 258:** los dos decimales de la 255 que no estaban literal en el doc son **sumas de su tabla** (2.532 = 1.652 + 880; 3.720 = 2.485 + 1.235); el de la 258 (`1.0`) es texto de código. Ningún número difiere.
- **Frases corregidas:** *«impacto esperado»* queda sólo en el docstring que explica que se sacó (`analysis/news_digest.py:15`), en los tests que exigen su ausencia y en un doc histórico de junio.

## 4. Mapeo hallazgo → tarea

Sin hallazgos nuevos. Los dos de esta forma ya tienen tarea: la 270 y la 264.
