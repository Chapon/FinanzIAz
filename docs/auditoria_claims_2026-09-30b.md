# Auditoría READ-ONLY — área `claims` — 2026-09-30 (segunda tanda)

Área: **afirmaciones y números que el proyecto usa hoy y no son ciertos**. Corrida anterior de esta área: `docs/auditoria_claims_2026-09-30.md` (esta mañana).

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

- **[C-nuevo]** Una afirmación o número escrito **por los arreglos de hoy** (backlog, skills,
  docstrings, `CLAUDE.md`, `SETTINGS_REFERENCE.md`, `DB_SCHEMA.md`) que el código o los datos
  contradicen. Foco: lo que se escribió como *«verificado»* o *«medido»*.
- **[C-presente]**, **[C-dosLugares]**, **[C-simbolo]** como en la corrida de la mañana, sobre el
  corpus que ahora es el de la 239.
- **[C-excluido]** Lo que la corrida de la mañana no miró: el **README** y los textos de `ui/` al
  usuario sobre VS SPY y la segunda opinión.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. Bugs de código que no sean de esta área; re-correr harness; decidir política.
2. Las otras cuatro áreas de la tanda.

### 1.4 Qué contaría como "acá no hay nada" — en las DOS direcciones

**Dirección 1 — lo escrito es falso.** Toda afirmación escrita por los commits `f13e8a6..HEAD`
coincide con el código y los datos de ahora.

**Dirección 2 — lo verdadero no está escrito.** Todo mecanismo nuevo de esos commits (jobs 8 y 9,
empalme, aviso de key, aviso de barra provisional) aparece donde el operador lo busca:
`SETTINGS_REFERENCE.md` si tiene perilla, el docstring del scheduler, la skill del área.

### 1.6 Alcance — qué se mira, como LISTA

1. Los textos agregados por `git diff f13e8a6..HEAD` (todos los archivos).
2. `README.md` y `tests/README.md`.
3. Los textos de `ui/` que muestran VS SPY o la segunda opinión.

### 1.7 Alcance — qué NO se mira, dicho antes

- Los docs de veredicto de tareas cerradas.
- Lo ya barrido esta mañana y no tocado después.

---

## 2. Alcance real

**Mirado:** los textos agregados por `git diff f13e8a6..HEAD` en los 39 archivos (backlog, skills,
`CLAUDE.md`, `SETTINGS_REFERENCE.md`, `DB_SCHEMA.md`, docstrings de los módulos tocados); `README.md`
y `tests/README.md`; los textos de `ui/` sobre VS SPY y fuentes de noticias.

**NO mirado:** docs de veredicto de tareas cerradas.

**Fase adversarial: PROPIA.** Ningún hallazgo llegó a HIGH.

---

## 3. Hallazgos

### [C-1] `tests/README.md` repite el claim que la 247 corrigió en `CLAUDE.md`, y su tabla de cobertura es de mayo

Severidad: **BAJA** · Confianza: ALTA · Categoría: [C-dosLugares] + [C-presente]
Ubicación: `tests/README.md:40-43` y `:16-27`

**Evidencia.** *«Tests marked `@pytest.mark.network` … None are marked yet»*: hay uno desde la 211, el
mismo que la **247** nombró en `CLAUDE.md` esta tarde. La tabla *«What's covered»* lista **8**
archivos de test; hay cientos. El *Quick start* no menciona los cuatro comandos del *done*.

**¿Por qué no antes?** **(b)** para la corrida de la mañana, que excluyó el README de forma
explícita. Pero la mitad del *«None are marked»* es **deuda de la tarea 247**: corrigió la frase en
`CLAUDE.md` sin buscarla en el resto del repo, que es exactamente la lección que la tanda de la
mañana escribió en la skill (*«las correcciones viejas se BUSCAN, no se leen»*).

**Acción.** Corregir la frase, reemplazar la tabla por una remisión (`pytest --collect-only`) y
apuntar el quick start al `/test`.

---

## 4. Barrido limpio en el resto del área — las dos direcciones

**Dirección 1.** Lo que los arreglos escribieron como verificado lo está: el Task Scheduler vacío
(`Get-ScheduledTask`), las keys como variables de usuario, la serie empalmada desde 2016-09-01 con la
junta al decimal, el solape mínimo de ~21 meses (2 años − 90 días), los dos marcos de la T115/T121.
**Una excepción, reportada en `guards`:** `finanzias-conventions` anuncia que `check_repo_health`
chequea *«DB desde no-Windows»*, y ese chequeo es inerte ([G-2] de ese informe).

**Dirección 2.** Los mecanismos nuevos están donde se buscan: la perilla del job 8 en
`SETTINGS_REFERENCE.md`, los jobs 8 y 9 en el docstring del scheduler, el aviso de key en la fila de
la segunda opinión. El job 9 no tiene perilla (no hace falta fila).

---

## 5. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [C-1] `tests/README.md`: «None are marked», tabla de mayo | BAJA | **252** |

---

## 6. Deuda de método

Ninguna de la skill. **Una de mi trabajo de la tarde:** la 247 no aplicó la lección que la tanda de la
mañana acababa de escribir. Una lección en la skill no la aplica sola quien no relee la skill al
cerrar una tarea de texto; queda dicho acá, no como tarea.
