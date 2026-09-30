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
