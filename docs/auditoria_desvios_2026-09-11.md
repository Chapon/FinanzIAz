# Auditoría READ-ONLY — área `desvios` — 2026-09-11

Corrida de la tanda del **2026-09-11** (las cinco áreas). Área: **desvíos harness↔engine que
`deviations()` no declara**. Corrida anterior de esta área:
`docs/auditoria_desvios_2026-09-08.md` (dejó las tareas 128 a 135).

---

## 1. Kill-criteria — CONGELADO 2026-09-11, antes de abrir ningún archivo

> Congelado junto con los otros cuatro de la tanda.

### 1.1 Por qué ahora

Dos motivos, y el segundo es el que manda:

1. **La política de salida viva quedó apoyada en un veredicto que se dio vuelta.** El T37
   era SHIP por los nueve criterios; re-corrido sobre la muestra refrescada dio **NO-SHIP**
   (tarea 167). Chapa decidió **no mover** la política y pre-registrar la 170, que cerró
   **NO MOVER** con la rejilla **cerrada**. O sea que hoy el harness modela una política que
   el harness mismo ya no valida, y eso es exactamente el tipo de cosa que `deviations()`
   tiene que nombrar o que hay que declarar que no es un desvío.
2. **Se movieron perillas y símbolos.** La 156 sacó AVB del universo; la 158 cambió el
   default del productor PIT; la 161 y la 177 unificaron el parseo de universo; la 163
   renombró las anclas. Cada una de esas toca el contrato productor↔consumidor.

### 1.2 Qué se busca — una frase por sub-categoría

- **[D-falta]** Una perilla **viva** que el harness no modela y que `deviations_keyed()`
  **no nombra** con una clave. *(Sin ordinal, tarea 135: la pregunta es «¿falta alguno?»)*
- **[D-espejo]** Un `LIVE_*` que dejó de describir a la cuenta viva — o una perilla viva sin
  espejo (las dos mitades de la 130 / 131 / 132).
- **[D-texto]** Un desvío declarado cuyo **texto** describe mal lo que pasa, o que se
  contradice con otra línea del mismo banner (la forma de la 169).
- **[D-veredicto]** Un desvío que existía cuando se midió un veredicto publicado y que hoy
  no existe (o al revés), sin que nadie lo haya declarado al re-leer ese veredicto.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. **Bugs de código**, **re-correr harness** y **decidir política**.
2. Si un desvío **debería** cerrarse: eso es una decisión de trading, no de auditoría.
3. Las otras cuatro áreas de la tanda.
4. **El conteo de desvíos como número.** Desde la 152 cada uno tiene clave estable; se
   compara la **clave**, no la cantidad. El ordinal histórico y el conteo vivo son cosas
   distintas y confundirlas fabrica un hallazgo falso (casi pasó el 2026-09-08).

### 1.4 Qué contaría como "acá no hay nada"

Cierra limpia si, poniendo al lado la config viva (DB + `settings.json`) y la del harness:

- toda diferencia tiene su clave en `deviations_keyed()`;
- todo `LIVE_*` coincide con su fuente viva;
- ningún texto de desvío afirma algo que el código contradice;
- y se dice qué no se pudo verificar.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Mismo protocolo que el §1.5 de `docs/auditoria_claims_2026-09-11.md`.

### 1.6 Alcance — qué se mira

1. `analysis/harness_config.py` — `deviations()`, `deviations_keyed()`, los `LIVE_*`.
2. `paper_trading/engine.py` — los gates y lo que efectivamente lee.
3. `~/.finanzias/settings.json` y la cuenta viva en `finanzias.db` (lectura).
4. `analysis/portfolio_sim.py` y `replay_cycle` — qué modelan de verdad.
5. Los banners que los runners imprimen.

### 1.7 Alcance — qué NO se mira, dicho antes

- El pipeline de catalysts y el Gate 2c (está OFF y sin provider — tarea 162).
- `ui/`, `alembic/`.
- Los runners que **no** corren sobre la cuenta viva.

---

## 2. Alcance real

**Mirado:** `deviations_keyed()` y sus 10 claves, los 25 símbolos `LIVE_*`, el
`~/.finanzias/settings.json` vivo contra la cuenta 2 de la DB, `paper_trading/engine.py` y
`paper_trading/gates.py` para los gates que efectivamente corren, y `analysis/portfolio_sim.py` +
`analysis/exit_replay.py` para lo que el harness modela.

**NO mirado, y queda declarado:** el Gate 2c / catalyst (está OFF y sin provider — tarea 162);
`ui/`; `alembic/`; los runners que no corren sobre la cuenta viva.

---

## 3. Hallazgos

### [D-1] `paper_adv_cap_pct` está ON en la cuenta viva, el harness no lo modela y nadie lo declara

Severidad: **MEDIA** (latente) · Confianza: ALTA · Categoría: [D-falta]
Ubicación: `paper_trading/engine.py:1147-1169`, `paper_trading/gates.py:565`

**Evidencia.** El `settings.json` vivo tiene `paper_adv_cap_pct = 0.05` (el **default del schema
es 0.0**, o sea que Chapa lo prendió a mano). `engine.py:1147` lo aplica a cada BUY:
`adv_capped_notional(target_dollars, adv, adv_cap_pct)`. Y ni `analysis/portfolio_sim.py` ni
`analysis/harness_config.py` mencionan `adv_cap` — grep vacío. Las 10 claves de
`deviations_keyed()` son `analyze_window`, `barrier_eval`, `barrier_fill`,
`artifact_window_undeclared`, `atr_hard_stop`, `vol_overlay`, `regime_scale`, `universe_screen`,
`earnings_blackout`, `reentry_gates`. **Ninguna es el ADV cap.**

**Razonamiento.** Es una perilla viva, encendida a mano, que **trima el tamaño de cada BUY**, y
el harness no la modela ni la declara. Es exactamente la familia de la tarea 94 (*«el overlay de
volatilidad está ON, muerde todos los días y no lo declara nadie»*).

**Impacto — medido, y por eso es MEDIA y no más.** La cuenta 2 tiene **$51.499 de equity con 10
slots**, o sea ~**$5.150 por BUY**. El cap de 5% sólo mordería con un `ADV$ < $103.000`, que para
nombres del S&P 500 no ocurre. **Hoy el desvío es inerte.** Muerde si la cuenta crece mucho o si
entra un nombre ilíquido, y ahí lo haría **en silencio**.

**Verificación.** Se comprobó que el cap se aplica sólo a BUY (`trade.side == "BUY"`), que falla
abierto sin ADV, y que la cuenta no tiene hoy ningún nombre donde el piso se acerque.

**¿Por qué no antes? (c-alcance)** — la corrida del 2026-09-08 no enumeró las perillas vivas una
por una contra `deviations_keyed()`; barrió los desvíos ya declarados. No es deuda de método:
es que el área se barre por muestreo y esta perilla no cayó en la muestra.

**Acción.** O declarar la clave con su número medido, o escribir por qué no hace falta.

### [D-2] Hay al menos cuatro perillas vivas sin espejo `LIVE_*`, y el guard que debería verlas es ciego por construcción

Severidad: **MEDIA-ALTA** (latente) · Confianza: ALTA · Categoría: [D-espejo]
Ubicación: `analysis/harness_config.py` (ausencia de espejos),
`tests/test_espejos_vivos_t130.py:34-42`

**Evidencia.** Perillas vivas que **no** tienen espejo `LIVE_*`:

| perilla | valor vivo | la modela el harness? |
|---|---|---|
| `atr_tp_mult` | `4.0` | **sí**, con un literal: `analysis/exit_replay.py:87` `tp_mult: float = 4.0` |
| `atr_trail_enabled` | `True` | sí, implícito |
| `hmm_enabled` | `False` | hereda el ambiente (ver [C-5] de `claims`) |
| `stacking_enabled` | `False` | hereda el ambiente (ídem) |

**Razonamiento.** `atr_tp_mult` es el caso más nítido: es una **perilla de política de salida**,
el harness la modela con un **literal hardcodeado que hoy coincide por casualidad** (4.0 == 4.0),
y no hay nada que ate los dos valores. Si Chapa mueve el take-profit, todos los harness de salida
siguen modelando 4.0 y **nada lo dice**. Ése es, byte por byte, el defecto de la tarea **92**,
que costó **7,16 pp de CAGR** por seis días de política declarada al revés.

**Y el guard no puede verlo, por su propia declaración.** `tests/test_espejos_vivos_t130.py:34-37`
dice: *«Su población son los `LIVE_*` que **existen**, así que una perilla viva que **no tiene
espejo** le es invisible. Esto cierra "el espejo dejó de seguir al vivo" y **no** "hay algo vivo
sin espejo"»*. Las dos que estaban en esa situación se cerraron una por una (tareas 131 y 132),
pero **nunca se shipeó el mecanismo que encuentra la próxima**.

**Impacto.** Latente hoy (los cuatro valores están alineados o son inertes). El costo aparece el
día que alguien mueva una de las cuatro, y ese día es silencioso.

**¿Por qué no antes? (c-metodo)** — el punto ciego está **escrito** en el guard desde la 130, y
las corridas de `desvios` del 2026-09-02 y del 2026-09-08 lo leyeron y cerraron los dos casos
conocidos **sin preguntar cómo se encuentra el tercero**. La skill no tiene ningún paso que diga
*«cuando un guard declara su punto ciego, el punto ciego es un hallazgo»*. **Deuda de skill —
ver §6.**

**Acción.** Un predicado que barra el `SCHEMA` y exija que toda clave que el engine lee en una
decisión tenga espejo o esté en una lista de excepciones con motivo — o sea, la dirección
**settings → espejos**, que es la que falta.

---

## 4. Barrido limpio en el resto del área

- **[D-texto]** — se leyeron las 10 claves y sus textos contra el código: ninguna afirma algo
  que el código contradiga. La contradicción de la tarea **169** (el banner del T37) ya está
  cerrada.
- **[D-veredicto]** — el caso vivo es el T37 (SHIP → NO-SHIP), y **está declarado** en los tres
  docs donde se lee, más la decisión de Chapa de no mover la política y el cierre de la 170.
  No hay desvío sin declarar por ese eje.

---

## 5. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [D-1] `paper_adv_cap_pct` vivo, no modelado, no declarado | MEDIA | **184** |
| [D-2] perillas vivas sin espejo + el guard ciego a ellas | MEDIA-ALTA | **185** |

---

## 6. Deuda de método

**[D-2] es (c-metodo)** y es la más importante de la tanda junto con la de `claims`: las dos son
**la misma dirección faltante**. Va consolidada en el §6 de
`docs/auditoria_guards_2026-09-11.md`.
