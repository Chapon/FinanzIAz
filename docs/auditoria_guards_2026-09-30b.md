# Auditoría READ-ONLY — área `guards` — 2026-09-30 (segunda tanda)

Área: **guards que no ven lo que describen, que fallan mudos, o que rechazan el dato bueno**. Corrida anterior de esta área: `docs/auditoria_guards_2026-09-30.md` (esta mañana).

---

## 1. Kill-criteria — CONGELADO 2026-09-30, antes de abrir ningún archivo de código

> Los **cinco** kill-criteria de esta tanda se congelaron **juntos, antes** de abrir código, y se
> commitean solos. Lo único mirado antes: los informes de la tanda de la mañana
> (`docs/auditoria_*_2026-09-30.md`), sus secciones *NO mirado*, y los **títulos** de `git log
> f13e8a6..HEAD`.

### 1.1 Por qué ahora

Es la **segunda tanda del día**, pedida por Chapa después de cerrar las tareas de la primera (239 a
248, salvo la 245). Esas tareas cambiaron **39 archivos** en 11 commits, y un arreglo nuevo es
exactamente el sustrato que esta skill existe para auditar: texto recién escrito que nadie releyó con
otros ojos, guards nuevos que nadie intentó engañar, y **jobs nuevos que escriben estado** (el
archivo diario de la cinta, 244; el refresh del frame largo de SPY, 246). La corrida de la mañana no
pudo verlos: no existían.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Etiquetas (a) / (b) / (c-alcance) / (c-metodo) / (d). Con una corrida de **esta mañana**, se espera
que casi todo sea **(a)** —introducido por los arreglos—; un (a) acá es **deuda de la tarea que lo
introdujo**, no de la skill, y se dice cuál.

### 1.2 Qué se busca

- **[G-ciego]** Los guards **nuevos de hoy** (corpus único de la 239, marco en pp de la 242,
  lecciones del harness de la 240, aviso de key de la 241): **mutar en el sentido del falso
  positivo** —la declaración que dice lo contrario— y exigir rojo.
- **[G-mudo]** Los jobs nuevos (8 y 9): cuando fallan, ¿quién se entera?
- **[G-excluido]** Lo que la mañana dejó sin mirar: `scripts/check_backlog_integrity.py` y
  `scripts/check_repo_health.py` **por dentro**.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. Bugs de código que no sean de esta área; re-correr harness; decidir política.
2. Las otras cuatro áreas de la tanda.

### 1.4 Qué contaría como "acá no hay nada" — en las DOS direcciones

**Dirección 1.** Cada guard nuevo se pone rojo con una mutación en el sentido del falso positivo, y
cada falla de un job nuevo deja rastro nombrable.

**Dirección 2.** Todo punto ciego real de esos guards está declarado en su docstring.

### 1.6 Alcance — qué se mira, como LISTA

1. `tests/corpus_operativo.py` y sus tres consumidores; `tests/test_marco_de_los_desvios_t242.py`;
   `tests/test_skill_harness_registra_veredictos_t240.py`; `data/providers.py` (aviso de key).
2. Los jobs 8 y 9 de `paper_trading/scheduler.py`.
3. `scripts/check_backlog_integrity.py` y `scripts/check_repo_health.py`.

### 1.7 Alcance — qué NO se mira, dicho antes

- Los guards de la UI.

---

## 2. Alcance real

**Mirado, como lista:** `tests/corpus_operativo.py` y sus tres consumidores (72, 137, 198);
`tests/test_marco_de_los_desvios_t242.py`; `tests/test_skill_harness_registra_veredictos_t240.py`;
el aviso de key de `data/providers.py`; los jobs 8 y 9 de `paper_trading/scheduler.py`;
`scripts/check_repo_health.py` y `scripts/check_backlog_integrity.py` por dentro.

**NO mirado:** los guards de la UI.

**Fase adversarial: PROPIA**, porque ningún hallazgo de esta área llegó a HIGH. Las dos
evidencias son mutaciones en el sentido del falso positivo, no lecturas.

---

## 3. Hallazgos

### [G-1] El corpus de la 239 deja afuera TODO el backlog, y sus secciones operativas son donde vivían dos hallazgos de esta mañana

Severidad: **MEDIA** · Confianza: ALTA · Categoría: [G-ciego] (población)
Ubicación: `tests/corpus_operativo.py` (`FUERA_DEL_CORPUS["docs/BACKLOG.md"]`)

**Evidencia — mutación en el sentido del falso positivo.** Se insertó *«Cuenta activa: "Sim
Principal" (id=1), modo kill_only.»* en *Acciones manuales pendientes*: la función del guard de la 198
la marca (`[('Sim Principal', 1)]`), pero el guard corre sobre el corpus y el corpus no incluye
`BACKLOG.md` ⇒ **verde**.

**Razonamiento.** El motivo de la exclusión (*«las cerradas citan a propósito las afirmaciones viejas
que corrigieron»*) vale para el **historial** de tareas cerradas, no para el **header**, *Acciones
manuales pendientes* ni *Bloqueado*, que son texto operativo en presente. Esta mañana dos hallazgos
vivían ahí: la instrucción de la segunda opinión ([C-3].5) y el *«modo kill_only»* del header
([C-6].5). El docstring declara como punto ciego *«un doc que `CLAUDE.md` no declare de
referencia»*; éste **sí** está declarado y quedó afuera entero.

**¿Por qué no antes? (a) NO EXISTÍA** — lo introdujo la tarea **239** (`d20b884`), esta tarde. Deuda
de la tarea, no de la skill.

**Acción.** Que el corpus incluya las secciones operativas del backlog (header, *Acciones manuales
pendientes*, *Bloqueado*, *Calidad de datos*), recortadas por encabezado, y excluya el historial.

### [G-2] El chequeo «DB desde no-Windows» de `check_repo_health.py` no puede dispararse nunca

Severidad: **MEDIA-BAJA** · Confianza: ALTA · Categoría: [G-inerte]
Ubicación: `scripts/check_repo_health.py` (`check_db_write_env`)

**Evidencia.** El chequeo sólo corre con `--staged` y busca `finanzias.db` entre los archivos
staged. `git check-ignore -v finanzias.db` → `.gitignore:40`; `git ls-files finanzias.db` → vacío.
Un archivo ignorado y no versionado **no puede** estar staged sin `git add -f`. Existe así desde que
se creó el guard (`ba6366e`, 2026-06-24) y ningún test lo ejercita.

**Razonamiento.** Además pregunta otra cosa que la regla: la regla 5 de `CLAUDE.md` prohíbe
**escribir** la DB desde Linux/sandbox (corrupción vía mounts); el chequeo mira si se **commitea**.
Y la skill `finanzias-conventions` lo vende como uno de *«las tres trampas»* que el guard chequea.

**Impacto.** Ninguna protección real para la regla 5, con un texto que dice que la hay. Hoy el riesgo
es bajo (el entorno es Windows), y el costo es el texto que dirige mal.

**¿Por qué no antes? (c-metodo)** — `check_repo_health.py` estuvo en el alcance de la corrida de
`guards` del 2026-09-11 (*«Mirado: … scripts/check_repo_health.py»*). Se leyó y no se preguntó si la
**condición de disparo es alcanzable**: la población (archivos staged) no puede contener el caso.
Es la forma de la 177 —una población real que no contiene el caso distinguidor— sobre un guard de
proceso. Ver §6.

**Acción.** O un chequeo que mire lo que la regla prohíbe (abrir la DB para escritura desde un
entorno no-Windows, en `database/models.py`), o sacar el chequeo y corregir los dos textos que lo
anuncian.

---

## 4. Barrido limpio en el resto del área

- **242:** su punto ciego —*«verifica que el marco esté nombrado, no que sea el correcto»*— no está
  escrito en el docstring con esas palabras, pero el test que pinnea el número del marco vivo
  (`test_regime_scale_cita_el_numero_del_marco_de_la_cuenta`) cubre el único caso que hoy importa.
- **240:** *«nombrar la tarea no garantiza la lección»* está declarado.
- **241:** una key vacía (`""`) cuenta como ausente, igual que en `second_opinion`; una key inválida
  no avisa como «sin key» pero sí loguea el fallo del request. Correcto.
- **Jobs 8 y 9:** sus fallas salen a `WARNING` en el log, que es el canal que Chapa eligió para la
  salud del harvest (243). Consistente con esa decisión.
- **`check_backlog_integrity.py`:** el freno de borrado es por líneas **netas**, como declara.

---

## 5. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [G-1] el corpus deja afuera las secciones operativas del backlog | MEDIA | **249** |
| [G-2] el chequeo «DB desde no-Windows» es inerte | MEDIA-BAJA | **250** |

---

## 6. Deuda de método

**[G-2] es (c-metodo):** leer un guard no dice si su condición de disparo es alcanzable. Lo que
faltaba: *por cada guard, construir el caso que lo debería disparar y ver si la población del guard
puede contenerlo* — la mutación en el sentido del falso positivo, aplicada también a los guards de
proceso (`scripts/check_*.py`), no sólo a los tests.
