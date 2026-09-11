# Auditoría READ-ONLY — área `guards` — 2026-09-11

Corrida de la tanda del **2026-09-11** (las cinco áreas). Área: **guards que degradan en
silencio**. Corrida anterior de esta área: `docs/auditoria_guards_2026-09-08.md` (dejó las
tareas 139, 140 y 141).

---

## 1. Kill-criteria — CONGELADO 2026-09-11, antes de abrir ningún archivo

> Congelado junto con los otros cuatro de la tanda.

### 1.1 Por qué ahora

**Porque hoy mismo fallaron cuatro guards, y los cuatro por la misma razón.** En las tareas
173, 150, 176 y 177 apareció el mismo defecto: **el guard verifica sobre algo que no
discrimina el caso que busca** — un substring que lo satisface una línea que dice lo
contrario (173), una pertenencia a lista que no dice nada del orden que decide (150), un
`in doc` que satisface el frontmatter en vez del cuerpo (176), y una población real que no
contiene el caso que separa las dos semánticas (177).

Y el **175** es peor: el guard de la 130 —escrito precisamente para que los espejos no
mintieran— estuvo **rojo en el CI 35 corridas** y verde en la máquina de Chapa, y nadie se
enteró porque el criterio de done no mira el CI.

O sea que esta área tiene, hoy, evidencia fresca de que **la forma de fallar de los guards
de este repo es sistemática**, no anecdótica.

### 1.2 Qué se busca — una frase por sub-categoría

- **[G-mudo]** Un guard cuyo fallo no llega a nadie: `except` que traga, fail-open sin log,
  aviso que no escala si se repite.
- **[G-ciego]** Un guard que **no puede ver** el defecto que describe: su referencia sale de
  lo mismo que chequea, o compara el nombre en vez del valor.
- **[G-inerte]** Un guard **declarado y no cableado**, o cableado a algo que nadie corre
  (la forma de la 97: *«declarado» no es «cableado»*).
- **[G-bueno]** Un guard que puede estar rechazando el **dato bueno** — la pregunta que
  destapó la 63.
- **[G-entorno]** Un guard que pasa en una máquina y falla en otra por estado vivo, o al
  revés (la forma de la 175).

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. **Bugs de código** y **re-correr harness**.
2. Los guards **de trading** en cuanto a si su umbral es el correcto: eso es una decisión
   con backtest, no una auditoría.
3. Las otras cuatro áreas de la tanda.

### 1.4 Qué contaría como "acá no hay nada"

Cierra limpia si, por cada guard barrido:

- se puede nombrar quién se entera cuando falla;
- su referencia viene de un eje distinto del que chequea;
- está cableado a algo que corre de verdad (suite, `/ship`, CI, scheduler);
- y se dice cuáles no se barrieron.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Mismo protocolo que el §1.5 de `docs/auditoria_claims_2026-09-11.md`. **En esta área en
particular se espera encontrar (c-metodo)**, porque los cuatro defectos de hoy son de una
forma que la corrida del 2026-09-08 tenía en su alcance.

### 1.6 Alcance — qué se mira

1. `scripts/check_repo_health.py`, `scripts/check_backlog_integrity.py`.
2. Los `announce_*` y los chequeos de `analysis/harness_config.py`.
3. Los guards de datos: `data/quality.py`, los de split/escala, el circuito de tickers
   muertos.
4. `tests/conftest.py` — los cuatro aislamientos (red, DB, log, Slack).
5. El cableado: `.claude/commands/ship.md`, `.pre-commit-config.yaml`, `.github/workflows/`.

### 1.7 Alcance — qué NO se mira, dicho antes

- Los guards de la UI.
- Los asserts internos de los tests que no son guards de invariante vivo.
- El pipeline de catalysts.

---

## 2. Alcance real

**Mirado:** `.git/hooks/` y `.pre-commit-config.yaml`, `scripts/check_repo_health.py`,
`scripts/check_backlog_integrity.py`, los `announce_*` de `analysis/harness_config.py`,
`tests/conftest.py` (los cuatro aislamientos), el cableado de `/ship` y `/test`, y un barrido AST
de **43** guards que verifican una declaración buscando un substring en el contenido de un
archivo.

**NO mirado, y queda declarado:** los guards de la UI; los asserts internos de tests que no son
invariantes vivos; el pipeline de catalysts.

---

## 3. Hallazgos

### Barrido limpio en [G-mudo], [G-inerte] y [G-bueno]

Se publica como resultado, que es lo que la skill pide:

- **[G-inerte]** — `.git/hooks/` tiene sólo archivos `.sample`, o sea que **ningún hook de git
  está instalado**. Pero eso **no es un hallazgo**: el propio `.pre-commit-config.yaml` lo
  declara en mayúsculas (*«OJO — ESTE HOOK NO ES EL CABLEADO OPERATIVO (tarea 97). Nadie corrió
  `pre-commit install`»*) y el cableado real es el paso 3a de `/ship`. La 97 lo dejó honesto.
- **[G-mudo]** — no apareció ningún `except` que trague sin log en los guards barridos.
- **[G-bueno]** — la pregunta de la 63 (*¿el guard rechaza el dato bueno?*) se re-miró sobre los
  guards de datos; el caso vivo era AVB y hoy está declarado como miembro inerte.

### [G-1] Los guards de este repo fallan por una forma repetida, y hoy falló CUATRO veces

Severidad: **MEDIA-ALTA** · Confianza: ALTA · Categoría: [G-ciego]
Ubicación: transversal — ver la tabla

**Esto no abre tareas nuevas**: las cuatro ya se arreglaron hoy y tienen su tarea. Se publica
porque **el patrón** es el hallazgo, y el patrón sí es accionable.

| tarea | el guard preguntaba | lo satisfacía |
|---|---|---|
| **173** | `glob in attrs` (¿`.gitattributes` declara este path?) | una línea que declara **`eol=lf`**, lo contrario del permiso que la excepción suponía |
| **150** | `concepto in REVENUE_CONCEPTS` | la pertenencia, cuando lo que decide es el **orden** (el parser corta en el primero que resuelve) |
| **176** | `comando in doc` | el **frontmatter** `allowed-tools`, no la instrucción del cuerpo |
| **177** | los 5 universos reales | ninguno tiene una coma, así que la población **no contenía el caso** que separa las dos semánticas |

**El eje común.** Las cuatro veces el guard verificó sobre algo que **no discrimina el caso que
busca**: tres por comparar el **nombre** en vez del **valor**, y la cuarta por usar una población
real que no contiene el caso distinguidor. Y las cuatro veces el guard estaba **bien
intencionado y escrito**, a veces con el comentario correcto al lado.

**Verificación.** Barrido AST de los 43 guards con forma `X in <contenido de archivo>`: el resto
son **estructurales legítimos** (*«¿el fuente contiene esta llamada?»*), donde el substring es
la pregunta correcta. El único de riesgo es
`tests/test_harness_config.py:322` (`assert "--max-positions 5" in txt`, con el `5` literal en
vez de `LEGACY_MAX_POSITIONS`), y **falla ruidoso** si la constante cambia, así que es LOW y no
se abre tarea.

**¿Por qué no antes? (c-metodo)** — las cuatro tenían esta forma el 2026-09-08 y el área
`guards` las tenía en su alcance. La skill no tenía —hasta hoy— ninguna instrucción que dijera
*cómo* se caza un guard ciego. **Deuda de skill — ver §6.**

**Acción.** Ninguna tarea nueva; la acción es la mejora de la skill de §6.

### [G-2] Cuando un guard declara su propio punto ciego, ese punto ciego no se convierte en nada

Severidad: MEDIA-ALTA · Confianza: ALTA · Categoría: [G-ciego]
Ubicación: `tests/test_espejos_vivos_t130.py:34-42`

Es el mismo hallazgo que **[D-2]** del área `desvios` visto desde acá, así que **la tarea es una
sola (185)** y no se duplica. Se anota en esta área porque la lección es de guards: el guard de
la 130 **escribió** su punto ciego (*«una perilla viva que no tiene espejo le es invisible»*),
las tareas 131 y 132 taparon los dos casos conocidos, y **nunca se shipeó el mecanismo que
encuentra el próximo**. Un punto ciego declarado y no cerrado es una promesa, no un guard.

---

## 4. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [G-1] el patrón de guard ciego (4 casos hoy) | MEDIA-ALTA | **ninguna nueva** — las 4 ya cerradas (173/150/176/177); la acción es §6 |
| [G-2] el punto ciego declarado de la 130 | MEDIA-ALTA | **185** (compartida con `desvios` [D-2]) |

---

## 6. DEUDA DE MÉTODO CONSOLIDADA — la mejora de la skill `auditoria`

Acá se junta lo **(c-metodo)** de las cinco áreas. Son **tres** huecos, y los tres produjeron
hallazgos en esta tanda.

### 6.1 Un cross-check tiene que correr en las DOS direcciones

**Lo que pasó.** Las condiciones de barrido limpio de las corridas anteriores están escritas
como *«toda afirmación de la doc coincide con el código»*. Eso caza **«lo escrito es falso»** y
es estructuralmente incapaz de cazar **«lo verdadero no está escrito»**.

**Lo que produjo:** [C-2'] (cuatro perillas vivas fuera de `SETTINGS_REFERENCE.md`, una de ellas
con espejo y con desvío declarado) y, un nivel más arriba, [D-2] (perillas vivas sin espejo).

**La mejora concreta:** la skill pasa a exigir que toda comparación doc↔código de una condición
de barrido limpio se escriba en **las dos direcciones**, y que el informe diga **las dos**.

### 6.2 Un guard ciego se caza mutando en el sentido del FALSO POSITIVO

**Lo que pasó.** Cuatro guards fallaron hoy por verificar sobre algo que no discrimina el caso
([G-1]). Ninguno se detectó leyéndolo: los cuatro se detectaron **mutando el repo en el sentido
del defecto y viendo que el guard seguía en verde**.

**La mejora concreta:** la skill pasa a nombrar esa técnica explícitamente para el área `guards`
— *poner la declaración que dice lo contrario, y exigir que el guard se ponga rojo. Si pasa en
verde, está matcheando el nombre y no el valor.* Y su corolario: **cuando un guard declara su
propio punto ciego, ese punto ciego es un hallazgo**, no una nota de color ([G-2]).

### 6.3 Un diferimiento declarado necesita dueño

**Lo que pasó.** La corrida del 2026-09-08 escribió *«`ARCHITECTURE.md` y `DB_SCHEMA.md` no
entraron; quedan para la próxima corrida de esta área»*. Eso funcionó — pero **por casualidad**:
sobrevivió porque esta corrida leyó el informe anterior. Nada lo garantizaba, y el hallazgo que
había ahí ([C-5], `kill_only`) es el de mayor severidad de la tanda.

Es la forma de la tarea **97** (*«declarado» no es «cableado»*) aplicada al propio informe de
auditoría.

**La mejora concreta:** un alcance diferido **entra al backlog como tarea**, igual que un
hallazgo. La regla existente dice *«todo hallazgo accionable termina en `docs/BACKLOG.md`»*;
pasa a decir también *«y todo alcance que se difiere»*.

### 6.4 Medir cobertura por NOMBRE DE ARCHIVO es el mismo defecto, y esta tanda lo cometió

**Lo que pasó, y es el hueco más incómodo de los cuatro porque lo cometió la auditoría.** La
corrida de `muestra` preguntó *«¿qué runners se re-corrieron después del refresh?»* y lo midió
con `ls docs/*2026-09-09* docs/*2026-09-10*` — o sea **por nombre de archivo**. Publicó tres
veredictos como *«nadie los re-chequeó»*; **dos de los tres sí lo habían sido**, y la evidencia
estaba en una línea de la entrada 164 del backlog y en una fila de tabla de un doc que se llama
por **otra** tarea.

Es literalmente la forma del §6.2 —**la referencia del chequeo no puede ver el objeto que
busca**— cometida por el proceso que existe para cazarla, y encontrada sólo porque un agente
independiente la atacó. La auditoría **no se detectó a sí misma**.

**La mejora concreta:** cuando una pregunta es sobre **contenido** (*«¿existe evidencia de X?»*),
el barrido va **por contenido** — `grep` sobre `docs/` **y** `docs/BACKLOG.md`, no un glob de
nombres. Un archivo que se llama como la tarea es una **convención**, no una garantía; y en este
repo el backlog es, de hecho, donde vive la mitad de la evidencia operativa.

**Y el corolario para la fase adversarial:** lo que el `verificador` tiene que atacar **primero**
no es la conclusión, es **el instrumento con que se midió**. Las dos correcciones grandes de esta
tanda —ésta y el hallazgo retirado de `claims`— fueron las dos del instrumento, no del
razonamiento.

### 6.5 Lo que NO se cambia, y por qué

- **La estructura de cinco áreas** funcionó: cada una produjo hallazgos de su propia forma y
  ninguna se pisó con otra.
- **El congelado del kill-criteria antes de mirar** funcionó, y congelarlos **los cinco juntos**
  —como se hizo hoy— es mejor que de a uno: ninguna corrida pudo calibrar su criterio con lo que
  encontró la anterior.
- **La fase adversarial** funcionó y **pagó**: refutó dos de las tres patas de impacto de [C-5] y
  bajó su severidad con un argumento de escala. Queda dicho, eso sí, que el segundo `verificador`
  **murió por límite de sesión** y que la refutación de [M-1] fue **propia y no independiente**
  — y aun así tumbó dos de los cinco runners del hallazgo.
