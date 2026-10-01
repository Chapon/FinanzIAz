# Auditoría READ-ONLY — área `desvios` — 2026-09-30 (segunda tanda)

Área: **desvíos harness↔engine que `deviations_keyed()` no declara, o declara mal**. Corrida anterior de esta área: `docs/auditoria_desvios_2026-09-30.md` (esta mañana).

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

- **[D-falta]** Una conducta nueva del motor o de sus datos, de los arreglos de hoy, que el harness
  no tiene y nada declara.
- **[D-sustrato]** Un job nuevo que **reescribe un archivo que el harness lee** como parte de su
  muestra congelada (foco: el frame largo de SPY que refresca el job 9, y si algún runner lo lee).
- **[D-texto]** Los textos reescritos por la 242: que cada número diga su marco **y** que el número
  sea el del doc de veredicto, no el de un enunciado.

### 1.3 Qué queda EXPLÍCITAMENTE afuera

1. Bugs de código que no sean de esta área; re-correr harness; decidir política.
2. Las otras cuatro áreas de la tanda.

### 1.4 Qué contaría como "acá no hay nada" — en las DOS direcciones

**Dirección 1.** Ningún texto de `deviations_keyed()` afirma algo que el código, el valor vivo o el
doc de veredicto que cita contradiga.

**Dirección 2.** Ningún artefacto que lea un runner es reescrito por un proceso vivo sin que el
runner lo declare o lo excluya.

### 1.6 Alcance — qué se mira, como LISTA

1. `analysis/harness_config.py` (textos) contra los docs de veredicto que citan.
2. Quién lee `data/parquet/SPY__*` entre los runners y `analysis/`, contra lo que escribe el job 9.

### 1.7 Alcance — qué NO se mira, dicho antes

- `run_scan` entero; la cuenta 1.

---

## 2. Alcance real

**Mirado:** los textos de `deviations_keyed()` reescritos por la 242 contra los docs de veredicto que
citan (T115 Corrida A, T121, T26b §1, T37 §2); quién lee `data/parquet/SPY__*` entre runners y
`analysis/`; lo que escribe el job 9.

**NO mirado:** `run_scan` entero; la cuenta 1.

**Fase adversarial: INDEPENDIENTE.** [D-1] entró como **HIGH** y pasó por el agente `verificador`
con el mandato de refutarlo. **Lo redujo a BAJA, con medición**; ver §3.

---

## 3. Hallazgos

### [D-1] La serie de régimen de SPY no tiene chequeo de alineación con el cohorte — hoy está corrida 6 ruedas, y el job 9 la reescribe por fuera de `refresh_cohort`

Severidad: **BAJA** (era HIGH; reducida por el `verificador`) · Confianza: ALTA · Categoría: [D-sustrato]
Ubicación: `scripts/run_market_regime_r2.py:79` (`load_spy_bars`), que usan también
`run_sizing_exposure_t10_t20.py` y `run_anom_regime_t38.py`; `analysis/harness_config.py:776`
(`stale_artifacts`); `data/historical_series.py` (`refrescar_benchmark_largo`, job 9).

**Evidencia.** Los tres runners de régimen leen `data/parquet/SPY__10y__1d.parquet` como serie de
régimen (`SPY < SMA200`). El chequeo de frescura del cohorte recorre `bars_by` —los tickers del
universo— y SPY no está en el universo, así que **su alineación con el cohorte no la mira nadie**.
`refresh_cohort.py` tampoco la refresca. Hoy SPY termina el **2026-09-01** y el cohorte el
**2026-09-09**: 6 ruedas, y en ese tramo `is_risk_off` arrastra la última bandera (bisect) sin aviso.
El job 9 que agregó la **246** reescribe ese mismo archivo cuando tiene más de 90 días.

**Lo que el `verificador` refutó — la consecuencia, no el mecanismo.** Midió el régimen que ven los
runners recortando SPY a distintos inicios: **0 días distintos** con inicio en 2016-12, 2017-03,
2017-06 y 2017-09 (las entradas arrancan a las 250 ruedas de warmup, 2017-08-30), y recién **29**
con inicio en 2018-03. Hacen falta ~6 refreshes del job 9 sin un refresh del cohorte en el medio
(~18 meses). Y los ajustes por dividendo no mueven `close < SMA200` (es invariante a la escala). Es
reversible (SPY se re-baja entero; no es el caso AVB de la 156). **Lo único que se mueve desde el
primer refresh es cosmético:** el `risk_off_share` impreso se calcula sobre toda la serie de SPY.
Y trajo un matiz mejor: el job 9 **achica** el desvío del final (hoy 6 ruedas) a cambio de mover el
inicio, que mientras haya holgura no cuenta.

**¿Por qué no antes?** La mitad del cohorte es **(c-alcance)**: las corridas de `desvios` miraron los
textos y el camino del motor, no qué artefacto lee cada runner de régimen. La mitad del job 9 es
**(a)**, introducida por la **246** esta tarde.

**Acción.** Meter SPY en el chequeo de cohorte de los runners de régimen (o abortar si `spy[-1]` es
anterior al final de `artifact_window`), y que el job 9 lo deje dicho en su docstring.

---

## 4. Barrido limpio en el resto del área

- Los cuatro números en pp del banner coinciden con su doc de veredicto y su marco: +0,93/−4,5 (T115
  Corrida A, 5 slots/41), −0,34/−4,8 (T121, gates ON, 10 slots/127), +3,39 (T26b, 10 slots/127),
  7,16 (T37 §2, 10 slots/127).
- Los jobs 8 y 9, el aviso de key y el de barra provisional no tocan órdenes, precio, tamaño ni caja.

---

## 5. Mapeo hallazgo → tarea

| hallazgo | severidad | tarea |
|---|---|---|
| [D-1] SPY de régimen sin chequeo de cohorte; el job 9 la reescribe | BAJA | **251** |

---

## 6. Deuda de método

Ninguna (c-metodo). Una nota: el HIGH con el que entró [D-1] salió de medir **que se escribe** y no
**qué cambia en el resultado** —el agujero de instrumento que el `verificador` atacó primero—. La
severidad de un desvío de sustrato se mide en el veredicto, no en el archivo.
