# Auditoría READ-ONLY — área `muestra` — 2026-09-30

Segunda corrida de la **tanda del 2026-09-30**. Área: **chequeos por cantidad, ciegos a la ventana
o a la población**. Corrida anterior de esta área: `docs/auditoria_muestra_2026-09-11.md` (dejó las
tareas 183 y 189, las dos cerradas).

---

## 1. Kill-criteria — CONGELADO 2026-09-30, antes de abrir ningún archivo

> Congelado **junto con los otros cuatro** de la tanda y antes de empezar ninguna corrida.

### 1.1 Por qué ahora

1. **La ventana rodó tres semanas sin refresh de cohorte declarado.** El último refresh del
   cohorte es el del 2026-09-09 y el último re-precómputo del store PIT de riesgo el del
   2026-09-12 (tarea 192). Todo chequeo que decide *«la muestra es ésta»* contando, hoy cuenta
   sobre una ventana que en vivo ya se movió.
2. **Entraron poblaciones nuevas decididas por código**: los tickers que la segunda opinión consulta
   (206), la población del barrido AST de la 238, la de archivos del guard 185 (231), la ventana
   del guard de valores vivos «calibrada contra la población» (214), y el umbral de salud de fuente
   del harvest «sacado de la población» (207).
3. **Las métricas de la cuenta se rehicieron sobre ventanas** (VS SPY sobre la ventana de la cuenta,
   224; meses que encadenan, 230; inicio de la serie de SPY, 225): son chequeos de ventana nuevos.
4. **La 189** creó *«una tabla única de sobre qué muestra se validó esto»*: es exactamente el objeto
   que esta área audita, y nadie la re-leyó desde que existe.

### 1.2 Qué se busca — una frase por sub-categoría

- **[M-cantidad]** Un invariante decidido contando donde importa **cuáles** elementos.
- **[M-ventana]** Un chequeo verdadero con la ventana vieja y falso con la rodada, sin declararlo.
- **[M-poblacion]** Una población de una **lista** o convención de nombre donde existe un
  **predicado** (familia 133/141/147/161/231).
- **[M-inerte]** Un miembro que cuenta como sano sin aportar (el caso AVB).
- **[M-vacio]** Un chequeo que pasa **por población vacía** y se lee como *«no hay violaciones»*.
- **[M-sinReverificar]** *«Esta operación movió la muestra — ¿qué quedó sin re-verificar?»*:
  veredictos de la tabla de la 189 cuya muestra ya no es la vigente, cruzado **por contenido**.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. Bugs de código y **re-correr harness**.
2. Si un guard degrada en silencio (área `guards`); desvíos harness↔engine (área `desvios`);
   frescura de artefactos como problema de regeneración (área `estado`).

### 1.4 Qué contaría como "acá no hay nada" — en las DOS direcciones

**Dirección 1 — lo escrito es falso.** Todo conteo pinneado en tests/runners y toda fila de la
tabla de la 189 coincide con lo que la muestra mide hoy, o declara su fecha.

**Dirección 2 — lo verdadero no está escrito.** Todo `len(...)`/conteo/umbral que decide *«la
muestra es ésta»* o *«la población es ésta»* en el código agregado desde el 2026-09-11 tiene al lado
una comparación de identidad (fechas, claves o huella) o declara por qué no hace falta; y ninguna
población nueva sale de una lista donde existe un predicado.

### 1.5 Cada hallazgo declara POR QUÉ no lo encontró la corrida anterior

Mismo protocolo que el §1.5 de `docs/auditoria_claims_2026-09-30.md`.

### 1.6 Alcance — qué se mira

1. La tabla de la 189 y los veredictos que la sostienen.
2. `analysis/harness_config.py` — chequeos de población, ventana y store.
3. Las ventanas nuevas de métricas: `analysis/metrics_panel.py` y lo que calcule VS SPY / meses.
4. Las poblaciones nuevas de §1.1.2 (guards 185/231, 214, 238; salud de fuente de la 207).
5. Los conteos pinneados en `tests/` y `scripts/` agregados desde el 2026-09-11.
6. `analysis/exit_replay.py` y `analysis/scaleout_replay.py` **leídos**, no por grep — la corrida
   anterior los difirió a grep.

### 1.7 Alcance — qué NO se mira, dicho antes

- El motor vivo salvo donde comparta un chequeo con el harness.
- `ui/` y la calidad de los datos de Yahoo en sí.

---

## 2. Alcance real

**Mirado:** `docs/VALIDEZ_VEREDICTOS.md` y su guard (`tests/test_validez_veredictos_t189.py`,
población por predicado); los runners que anclan su sanity (8, por `grep measured_on=|WINDOW_*`); las
ventanas nuevas de VS SPY (`analysis/metrics_panel.py`: `benchmark_stale_bdays`,
`benchmark_start_gap_bdays`, commits de la 218/223/224/225/230); los guards con población nueva (185/231
en `desvios` 2026-09-27, 214, 238); los conteos pinneados en los **50** archivos de `tests/` y
`scripts/` agregados desde el 2026-09-11; `analysis/exit_replay.py` **leído** en sus chequeos de
barras y de veredicto (`:255-300`, `:600-656`), `analysis/scaleout_replay.py` en el diff de la 232.

**NO mirado, y queda declarado:** `analysis/portfolio_sim.py` por dentro (sin cambios de chequeo
desde el 2026-09-11); `analysis/scaleout_replay.py` fuera del diff. **Se difiere con dueño:** va en
el enunciado de la **246**.

**Fase adversarial: PROPIA, no independiente.** Ningún hallazgo llegó a HIGH.

---

## 3. Hallazgos

### [M-1] El VS SPY tiene fecha de vencimiento, medida, y se cerró sin tarea

Severidad: **BAJA** · Confianza: ALTA · Categoría: [M-ventana]
Ubicación: `analysis/metrics_panel.py` (`_benchmark_panel`, guard de la 225); backlog, cierre de la 225

**Evidencia.** El propio cierre de la 225 lo midió: *«el cache es una ventana **rodante** que avanza
~1 rueda por día mientras el arranque de la cuenta queda **fijo**, así que el colchón se achica
monótonamente. Al 2026-09-24: … la cuenta 2 tiene **453** días hábiles de colchón»* — y cerró
*«No deja tareas nuevas»*. Con 453 días hábiles, el guard apaga el VS SPY de la cuenta 2 **para
siempre** hacia mediados de 2028.

**Razonamiento.** El guard está bien: apaga y lo dice. Lo que no tiene dueño es la **causa**: una
métrica de ventana creciente leída de un cache de ventana fija. Es un chequeo que es verdad hoy y
deja de serlo cuando la ventana rueda — la definición de [M-ventana] — con el agravante de que la
fecha está calculada.

**¿Por qué no antes? (a) NO EXISTÍA** — la 225 es del 2026-09-24.

**Acción.** Una tarea chica: que la serie de SPY del panel salga de un store que no rote (o que el
warm-up baje desde el arranque de la cuenta), con la fecha de vencimiento escrita en el enunciado.

### [M-2] Un test de la 81 depende del calendario: está rojo HOY, y lo está 12 días por año

Severidad: **MEDIA** (rompe el *done* y el CI esos días) · Confianza: ALTA · Categoría: [M-ventana]
Ubicación: `tests/test_archive_price_cache_t81.py:104-119`

**Evidencia.** No lo buscó el barrido: apareció al correr los cuatro comandos para cerrar esta
tanda. `test_una_segunda_corrida_suma_al_mismo_mes_sin_pisar` siembra una fila a `_cuando(30)` y otra
a `_cuando(29)` —relativas a `datetime.now()`— y lee **un** Parquet (`next(glob("*.parquet"))`). El
2026-09-30 esas fechas son el **31/08 y el 01/09**: dos meses, dos archivos, y el test ve sólo
AAPL. Rojo en la suite (Anaconda: **1 failed, 3889 passed, 1 skipped**) y en el modo sin estado
(**1 failed, 3886 passed, 4 skipped**). Barriendo 2026 día por día, la condición se da **12 veces**:
el 30 de cada mes salvo febrero, y el 2 de marzo.

**Razonamiento.** El invariante que fija el test (*«el mes se funde, no se reemplaza»*) es correcto;
lo que no es estable es la **muestra** que elige para probarlo: dos fechas relativas a hoy que
**casi siempre** caen en el mismo mes. Es la pregunta de esta área en su forma más literal: *¿esto
sigue siendo verdad si la ventana rueda?*

**Impacto.** Esos 12 días, todo cierre de tarea falla el *done* por una causa ajena, y el CI queda
rojo en cada push. Hoy, entre ellos, el de esta misma tanda.

**Verificación.** Los otros tests del archivo que usan `_cuando` siembran una sola fecha o leen
todos los Parquet; éste es el único que mezcla dos fechas relativas con un solo archivo.

**¿Por qué no antes? (c-alcance)** — el test es del 2026-09-02 y las corridas anteriores de esta
área barrieron chequeos de muestra **del harness**, no fechas relativas en tests. Y el 30/09 es el
primer día rojo desde que el test existe.

**Acción.** Fechas fijas del mismo mes (o leer todos los Parquet del directorio), y un barrido de
los tests que siembran fechas relativas a `now()` buscando la misma forma.

---

## 4. Barrido limpio en el resto del área — las dos direcciones

**Dirección 1 (lo escrito es falso).**
- La tabla de la 189 coincide con los docs que cita (T219 del 2026-09-22 incluida).
- Los conteos pinneados en los 50 archivos nuevos son de fixtures sintéticos (`rep.tickers == 127`
  en un reporte armado en el test, `TARGET_MONTHLY_USD == 4000`) o **pisos anti-vacío**
  (`len(documentadas) >= 50` en la 179). Ninguno pinnea la muestra viva.

**Dirección 2 (lo verdadero no está escrito).**
- **238:** la población de llamadores se descubre por AST en nueve raíces; la de fetch es una lista,
  **medida** sin caso fuera de ella (`docs/auditoria_guards_2026-09-30.md` §4).
- **214:** umbral medido contra la población (36× de separación), no elegido.
- **207:** el 20% sale de 72 corridas normales.
- **`exit_replay`:** `passes_kill_criteria` ignora `n_skipped_no_data`, pero el reporte lo publica al
  lado y el runner (T61) es histórico, sin consumidor vivo. No se publica.
- **Un veredicto citado como vigente y fuera de la tabla de la 189** —el +0,93 pp de la T115, que
  imprime el banner de todo runner— es un problema de **marco**, no de ventana: va en
  `docs/auditoria_desvios_2026-09-30.md` [D-1]. Que su runner no entre en la población de la 189 es
  una consecuencia del predicado (sólo runners con sanity anclado o de clase `magnitud`), y va en el
  enunciado de la **242**.

---

## 5. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [M-1] el VS SPY vence hacia mediados de 2028, sin tarea | BAJA | **246** |
| [M-2] test de la 81 rojo 12 días por año (hoy incluido) | MEDIA | **248** |

---

## 6. Deuda de método

Ninguna (c-metodo) ni (d). Dos notas. **[M-2] no lo encontró el barrido sino el cierre:** el alcance
de esta área mira chequeos de muestra del harness, y un test con fechas relativas a `now()` tiene la
misma forma —una muestra que rueda con el reloj— en otro lugar; la próxima corrida debería barrer
`tests/` buscando `now()` combinado con un corte por mes, día o ventana. Y el número que más
importaba del tema —un veredicto citado como vigente sobre otro marco— lo encontró `desvios`. La
pregunta *«¿sobre qué muestra se validó?»* tiene dos mitades, ventana y **marco** (slots, universo),
y la tabla de la 189 indexa sólo la primera.
