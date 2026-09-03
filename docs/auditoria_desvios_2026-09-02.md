# Auditoría `desvios` — 2026-09-02

**Área:** desvíos **harness↔engine** que `analysis/harness_config.deviations()` **no
declara** · **READ-ONLY**, no se modifica nada · Cuarta corrida de la skill `auditoria` ·
Fase adversarial: agente `verificador`

---

## 1. Kill-criteria — congelado ANTES de abrir un archivo

*(Escrito y guardado antes del primer `grep`.)*

### La pregunta, formulada SIN número

> **¿Hay alguna perilla que cambie una decisión en el engine vivo y que el harness no
> modele ni `deviations()` declare?**

La skill pregunta por *"un octavo desvío"*. **No uso ese número**: su propia primera corrida
cazó que preguntaba por un *«séptimo»* cuando el fuente ya numeraba siete (hallazgo A-1), y
además **hoy toqué `deviations()`** en la tarea 89, así que cualquier número escrito antes
de esta sesión es sospechoso por construcción. El conteo sale del fuente, y **cuántos hay es
parte del resultado**, no del enunciado.

### Qué se compara, eje por eje

1. **Config de cartera** — slots, capital, universo, `cap_days`, modo de asignación.
2. **Costos** — comisión, slippage: los de la cuenta viva contra los del harness.
3. **Gates de entrada** — cuáles corren en `run_scan` y cuáles modela `portfolio_sim`.
4. **Sizing** — escalado por régimen, vol targeting, vol penalty, trim.
5. **Salidas** — barreras ATR (precio de decisión y de fill), trailing, stop duro,
   take-profit, tope de tenencia, whipsaw, scale-out.
6. **Datos** — período de barras, origen de la señal, precio de referencia.

### Corpus

`paper_trading/engine.py` y `paper_trading/gates.py` · `paper_trading/strategies.py` ·
`analysis/harness_config.py` (`deviations`, `config_banner`) · `analysis/portfolio_sim.py` ·
`analysis/scaleout_replay.py` · `analysis/exit_replay.py` · `~/.finanzias/settings.json`
(la config **viva**, no el SCHEMA) y la cuenta 2 en la DB.

### Qué queda explícitamente AFUERA

- **Los siete (o los que sean) ya declarados.** Re-verificar que sigan siendo ciertos es
  área `claims`, no ésta. Acá sólo se cuentan para saber contra qué comparar.
- **Diferencias que no cambian una decisión** (logging, telemetría, nombres).
- **El motor de catalysts** (`paper_catalyst_exit_veto_enabled`): la auditoría `estado` del
  2026-09-01 ya midió que está OFF y sin provider inyectado. Si aparece encendido, entra.
- Performance, dead code, seguridad.

### Qué contaría como "acá no hay nada"

Barrido limpio **⇔** para **cada** perilla del §2 que hoy cambie una decisión en vivo, se
cumple una de:

- **(a)** el harness la **modela** con el mismo valor;
- **(b)** `deviations()` la **declara**;
- **(c)** está **inerte hoy** (flag apagado, sin consumidor) **y eso está escrito**.

Si las tres fallan para alguna, hay hallazgo. Si ninguna falla, se cierra en limpio con la
lista de perillas miradas, para que el "no hay nada" sea auditable.

## 2. Predicciones — declaradas antes de mirar

| | predicción |
|---|---|
| **P1** | Los **costos** difieren: la cuenta viva tiene su comisión/slippage y el harness usa los defaults de `CostModel()`, sin que nada lo declare. |
| **P2** | Hay **gates de entrada** que corren en vivo y el harness no modela ni declara. Lo declarado (T34) son los de **re-entrada** (Gate 5/5b); el de **earnings** (Gate 6) y el de **correlación** quedarían afuera. |
| **P3** | El **escalado por régimen** (R2b, activo con factor 0.50 según el backlog) no lo modela `portfolio_sim` y no está declarado. |

*(Resultado de las tres: §3.)*
## 3. Cómo salieron las predicciones

| | predicción | resultado |
|---|---|---|
| **P1** | Los **costos** difieren | **REFUTADA.** `CostModel()` (comisión 0.001, slippage 0.0005) coincide **exacto** con la cuenta 2 en `paper_accounts`, y el capital inicial (50.000) también. |
| **P2** | Hay **gates de entrada** sin modelar ni declarar | **ACERTADA en la familia, ERRADA en cuál.** Gate 2b **sí** está modelado (`scaleout_replay.py:99,410`: `min_age_bdays=3` + bypass 0.25, iguales a lo vivo). El que falta es **Gate 6** (§4, D-2). |
| **P3** | El **escalado por régimen** no se modela ni se declara | **ACERTADA en el mecanismo, ERRADA en la mitad que importa** (§4, D-1): es cierto que 17 de 21 runners no lo modelan y que `deviations()` no lo nombra, pero **14 pre-registros sí lo declaran en prosa** y **nunca disparó en vivo** (0 de 62 BUY). |

**El conteo de desvíos, hecho sobre el fuente y no sobre la skill:** `deviations()` declara
**siete** — slots, universo, ventana de `analyze()`, precio de decisión de las barreras ATR,
fill de esa barrera, ventana rodante de artefactos, y gates de re-entrada (5/5b vía
`live_gates`). La skill decía siete y esta vez **coincide**; se verificó igual, porque el
número ya caducó una vez.

## 4. Los hallazgos

Cinco. Los cuatro que mandé al `verificador` volvieron **uno refutado y borrado**, dos
reformulados con **errores de hecho míos corregidos**, y uno confirmado y **subido a
primero**. Los dos últimos los encontró él.

### [D-3] La política de salida viva cambió el 2026-08-27 y 16 runners siguen modelando la vieja
**Severidad: HIGH · Confianza: ALTA · Categoría: desvío harness↔engine no declarado**

**Ubicación.** `analysis/exit_replay.py:82-95` (`AtrParams`), los 16 runners que la usan
pelada, `analysis/harness_config.py` (`deviations`, que no la nombra).

**Evidencia.** La cuenta viva corre **`soff_t2.0`** desde el 2026-08-27:
`atr_hard_stop_enabled=False` y `atr_trail_mult=2.0`, **escritos en
`~/.finanzias/settings.json`** (no son defaults). El rastro del flip está en
`backups/settings_pre_soff_t2.0_20260827_195731.json`, que difiere de la config actual
**exactamente en esas dos claves**.

El harness: `AtrParams()` tiene `stop_mult: float = 2.0` y **ningún campo para apagar el
stop duro**. El propio repo documenta la equivalencia — `paper_trading/gates.py:113-117`:
*"`hard_stop_enabled=False` apaga el stop duro sin tocar `stop_mult` … es **equivalente
dígito por dígito al `stop_mult=1e9`** con que el harness corrió ese brazo"*.

**16 runners usan `AtrParams()` pelado** (t45, t38, t11b, t13, t51, t61, t12, r2, t9, t49,
t39, t21, t46, t7, t10/t20, walkforward), o sea modelan `s2.0` — stop duro **encendido**.

**Razonamiento — y el tamaño lo midió el propio proyecto.** La rejilla de
`docs/stop_value_t37_2026-08-27.md` §2:

| stop \ trail | 2.0 |
|---|--:|
| **2.0** (el default del harness) | **2.01%** |
| **off** (lo vivo) | **9.17%** |

**7,16 pp de CAGR.** Es **más grande que el look-ahead del fill** (5,01 pp) que se ganó una
tarea entera (la 33). Y no está dominado por el trailing: el trailing queda suprimido hasta
que el HWM supere `entry + 1.0×ATR` (`gates.py:108-112`), así que el stop duro es lo único
que cubre a los trades que **nunca despegan** — los perdedores.

**Impacto — es vivo, no latente.** `docs/event_timestop_t51_2026-08-28.md` fecha su corrida
el **2026-08-28**, un día después del flip, y `run_event_timestop_t51.py:569` pasa
`atr_p=AtrParams()`. Ya corrió una vez con la política que la cuenta había apagado 24 horas
antes.

**Dos agravantes que encontró el `verificador`:**

1. `scripts/run_stop_value_t37.py:116` → `LIVE_STOP, LIVE_TRAIL = 2.0, 2.0`. **La constante
   que se llama "LIVE" quedó falsa el mismo día que esa tarea shipeó.**
2. `scripts/run_exit_replay_t61.py:45-56` es el **único** que arma sus `AtrParams` leyendo
   los settings vivos… y lee `atr_stop_mult`/`atr_tp_mult`/`atr_trail_enabled` **ignorando
   `atr_hard_stop_enabled` y `atr_trail_mult`** — justo las dos que cambiaron. El camino
   *"leo la config viva"* **miente en silencio**.

**Verificación.** Los cinco intentos de refutación fallaron: ningún runner de los 16 pisa el
stop por otra vía (`stop_filter` sólo aparece en t26/t26b/t34/t37, los de salidas, que
parametrizan el stop porque **es** su tema); los settings son reales; y corrió después del
flip.

**Acción.** No es *"arreglar 16 runners"*: la política de salida viva **no vive en
`harness_config.py`** (0 matches de `hard_stop`/`stop duro`/`stop_mult`) sino duplicada en
constantes por script en cinco archivos. Lo que corresponde es subirla —
`LIVE_STOP_MULT`, `LIVE_TRAIL_MULT`, `LIVE_HARD_STOP_ENABLED`— y que `deviations()` compare
contra ella, **igual que ya hace con slots y universo**.

---

### [E-1] La cuenta viva llegó a 12 posiciones con `max_positions=10`, y el harness no puede
**Severidad: HIGH · Confianza: ALTA · Categoría: desvío… que además huele a bug**

*(Hallazgo del `verificador`.)*

**Evidencia.** Reconstruyendo el libro desde `paper_orders` **por ticker y con acciones** (no
por conteo de órdenes, que ignoraría las ventas parciales): **máximo 12 posiciones abiertas**,
y **15 momentos por encima de 10**, el primero el 2026-06-22. Re-medido de forma
independiente después de que lo reportara el verificador.

**Razonamiento.** `paper_trading/strategies.py:467` hace
`held_after = held_tickers - forced_exits`: **libera el slot antes de que la venta exista**.
Y `forced_exits` incluye los `analyze SELL` (`:406`), que río abajo pueden quedar
**bloqueados por el Gate 2b** (`engine.py:1047`, `paper_signal_sell_min_age_bdays=3`). O sea:
el sizing cuenta con un slot que el gate después no libera, y entra igual.

El harness es estricto: `portfolio_sim.py:385-388`, `free_slots = max_positions - len(open)`,
sin slot → `n_no_slot`. **Nunca puede pasarse.**

**Impacto.** Es el eje 1 del kill-criteria (config de cartera) y no lo declara nadie. Pero
además **no es sólo un desvío**: que una cuenta con 10 slots tenga 12 posiciones es una
violación de su propia config, con más exposición de la declarada.

**Acción.** Medir primero cuántas veces y con qué exposición; después decidir si el arreglo
va en `strategies.py` (no liberar el slot hasta que la venta se confirme) o en el engine.
**No** empezar por el harness: acá el que se desvía de lo declarado es el vivo.

---

### [E-2] El overlay de volatilidad de cartera está ON, muerde todos los días, y el harness no lo tiene
**Severidad: MEDIA-ALTA · Confianza: ALTA · Categoría: desvío harness↔engine no declarado**

*(Hallazgo del `verificador`.)*

**Evidencia.** `vol_overlay_enabled: true` y `vol_target_portfolio_annual: 0.12` en el
settings vivo (verificado leyendo el JSON). `strategies.py:525` lo aplica a **todas** las BUY
nuevas. En el log de producción: `portfolio vol overlay (analyze_single): σ=15.8% > target
12.0%, scaled new buys ×0.76` y `σ=37.2% … ×0.32`. El primer fill de la cuenta lo lleva
grabado: `target_dollars = 3.928 = 5.000 × 0,786`.

**Razonamiento — y el detalle que lo hace peor que el D-1.** Los pre-registros dicen *"sin
overlay T20"*, pero ése es el de **régimen**. A **este** overlay no lo nombra ningún
pre-registro (`grep -i vol_overlay` en `docs/*prereg*.md` → **0**). Y a diferencia del D-1,
que nunca disparó, **éste dispara todos los días**.

**Impacto.** El harness dimensiona posiciones sin el recorte que la cuenta aplica siempre.

**Acción.** Declararlo en `deviations()`. Modelarlo es otra decisión (requiere σ de cartera
rodante en el simulador).

---

### [D-1] El escalado por régimen no se modela y `deviations()` no lo declara
**Severidad: MEDIA · Confianza: ALTA · Categoría: desvío harness↔engine no declarado**

> **Reformulado y BAJADO de HIGH por el `verificador`**, con dos correcciones de hecho
> mías. Se publica su versión.

**Lo que aguanta.** `paper_regime_scale_enabled: true` / `factor: 0.5` están **escritos** en
el settings vivo; el escalado vive en `strategies.py:533-536`, dentro de
`generate_trades_analyze_single`, que es la estrategia de la cuenta 2. El harness **no tiene
otra vía**: `regime_of=` sólo **etiqueta** el trade para el reporte (`portfolio_sim.py:451`),
no toca el notional; el único canal es `entry_filter`, y lo pasan **4 de 21** runners. Y **no
es nominal en la ventana**: sobre `SPY__10y__1d.parquet` (2.513 barras), **15,96% de los días
son risk-off** (2022: 204/251).

**Lo que NO aguanta, y lo corrijo:**

1. **«ni lo declaran» era falso.** **14 pre-registros** lo declaran en prosa, con la frase
   casi calcada *"Sin overlay T20 (sizing por régimen), por atribución limpia"* (t13, t21,
   t23, t26, 26b, t34, t37, t38, t39, t45, t47, t49, t11b, t12). El hallazgo correcto es
   **«no lo modelan y `deviations()` no lo declara — la declaración depende de que el autor
   se acuerde de escribirla a mano»**, que es exactamente lo que la T27 vino a evitar.
2. **Nunca disparó en vivo.** **0 de 62** BUY filled de la cuenta 2 tienen razón `risk-off`
   (verificado por mí contra `paper_orders`); los 62 dicen `analyze BUY` a secas. SPY no
   estuvo bajo su SMA200 en ningún scan desde el 2026-06-20.
3. **El impacto está medido y es chico en CAGR:** `docs/sizing_exposure_t10_t20_2026-07-22.md`
   → `R2b_f050` da **ΔCAGR +0,59 pp** y **maxDD 21,6% → 19,1%**. El harness mide un libro con
   ~2,5 pp **más** de drawdown que el vivo, no un veredicto dado vuelta.

---

### [D-2] El earnings blackout (Gate 6) está activo, el harness no lo modela y `deviations()` no lo nombra
**Severidad: MEDIA · Confianza: ALTA · Categoría: desvío harness↔engine no declarado**

> Reformulado por el `verificador`, con **un error de hecho mío corregido**.

**Evidencia.** Gate 6 (`engine.py:1172-1196`) bloquea **BUY** cuando el ticker tiene earnings
dentro de ±N días; los SELL sólo si `earnings_blackout_block_sells` (**false** vivo), y los
exits ATR lo bypasean. `grep -ci earnings` sobre `portfolio_sim.py`, `scaleout_replay.py`,
`exit_replay.py` **y** `harness_config.py`: **0**.

**Mi error, corregido:** dije que `earnings_blackout_days` *"no está seteado y cae al default
2"*. **Está seteado**, en `settings.json:48`, con valor `2`. Llega al mismo número, pero el
argumento estaba mal.

**El lookup tiene datos, no falla-open siempre:** `earnings_cache` tiene 41 tickers, **39 con
fecha no nula**, y se pide **por candidato** (`engine.py:894`), no por universo — o sea que la
cobertura **efectiva** es prácticamente total. La hipótesis *"casi siempre falla el lookup"*
queda descartada.

**La población afectada está medida por el propio proyecto:**
`docs/earnings_blackout_replay_2026-06-25.md` → a ±2 días, **6 de 38 round-trips (15,8%)** son
near-earnings. *(El signo de ese estudio —−3,45% vs +1,19%— tiene n=6 y **no** sostiene nada;
lo que sostiene es el **share**.)*

**Declarado a mano en 7 pre-registros** (t26, 26b, t34, t37, t23, t11b, t12) — cobertura
**peor** que la del D-1: t45, t49, t51, t39, t21, t13, t9, r2 y t7 **no** lo mencionan.

**Caveat de factibilidad, que cambia la remediación:** **no hay fechas de earnings PIT a 10
años** en el repo (`earnings_cache` arranca el 2026-06-26, 41 tickers). Modelarlo pide un
dataset que no existe ⇒ el cierre honesto es **declararlo en `deviations()`**, no modelarlo.

## 5. Lo rechazado, y con qué motivo

### [D-4] La base del sizing (`picks` vs `free_slots`) — **REFUTADO, y borrado**

Lo publiqué como HIGH y **está mal**. Se cae por el paso que no miré:
`strategies.py:473` es `picks = [t for _, t in ranked][:free_slots]`, así que
**`len(picks) = min(candidatos, free_slots)`** y cuando hay al menos tantos candidatos como
slots —el caso normal— `available/len(picks)` **es idénticamente** `cash/free_slots`, la
fórmula del harness.

Verificado de los dos lados por el `verificador`: en vivo, **en los 29 días con compras el
número de compras iguala a los slots liberados ese día**, y la aritmética cierra (el primer
día 50.000/10 = 5.000, y el `target_dollars` grabado es 3.928 = 5.000 × 0,786 del overlay de
σ). En el harness, el pool de candidatos es de ~57/día para 10 slots — **ratio de selección
~55:1**, así que los slots siempre se llenan.

**Mi ejemplo del 5× exigía escasez de candidatos, y ninguno de los dos lados la tiene.** Se
borra, no se degrada. *(Sí es cierto que ninguno de los dos aplica el tope del 25% —el
harness no lo aplica sin `size_weight`, y `equal_weight` no está en `_VOL_SIZED_MODES`—:
coinciden en no topear, lo que **refuerza** la refutación.)*

- **P1 (costos)** — rechazado por mí antes de publicar: coinciden exacto.
- **Gate 2b** — rechazado: **sí** está modelado, con los mismos valores.
- **Gates 1 / 2 / 3** (market hours, min-holding 60 min, anti-flap 30 min) — rechazados:
  son **sub-diarios** y el harness trabaja a granularidad diaria ⇒ inertes por construcción.
- **Gate 3b (ADV cap)** — rechazado: está **ON** (0.05) y sin modelar, pero es **nominal** —
  el 5% del ADV en dólares de cualquier nombre de la watchlist está tres órdenes de magnitud
  por encima de una orden de ~5.000.
- **Gate 4 (min trade 250)** — rechazado: inerte con órdenes de ~5.000.

## 6. El hilo que une a los cinco

`docs/event_timestop_prereg_t51_2026-08-28.md:236` — el pre-registro **más nuevo** dejó de
enumerar los desvíos en prosa y **delegó en la función**: *"Los desvíos declarados del
harness (`analysis/harness_config.py`): ventana de `analyze()`, precio de decisión, fill,
gates de re-entrada y la ventana rodante"*.

**Ésa es la transición que convierte los huecos de `deviations()` en huecos del
pre-registro.** Mientras la declaración era prosa a mano, el D-1 estaba en 14 docs y el D-2
en 7. Desde que se delega, **lo que la función no dice no lo dice nadie**. Y la T51 corrió
ese mismo día con el stop duro que la cuenta había apagado 24 horas antes.

## 7. Alcance NO mirado

- **La cuenta 1** (pausada) y las estrategias que no son `analyze_single`.
- **`_apply_vol_overlay_to_buys` en detalle**: se verificó que existe, que está ON y que
  dispara; **no** se auditó su cálculo de σ ni su interacción con el escalado por régimen.
- **Los siete desvíos ya declarados**: no se re-verificó que sigan siendo ciertos — eso es
  área `claims`.
- **Gate 2c** (veto de catalysts): OFF y sin provider, ya medido por la auditoría `estado`.
- **El área `guards`**, que queda sin correr.

## 8. Cierre — mapeo hallazgo → tarea

**Una fila por hallazgo publicado, ninguna vacía.** Verificado de a uno con `grep` contra
`docs/BACKLOG.md` (que el `### NN.` exista y que su título cite el hallazgo), no de memoria.

| hallazgo | severidad | tarea | título |
|---|---|---|---|
| **D-3** | ALTA | **92** | EXITPOL-HARNESS — La política de salida viva cambió el 2026-08-27 y 16 runners siguen modelando la vieja |
| **E-1** | ALTA | **93** | SLOTS-OVERFILL — La cuenta viva llegó a 12 posiciones con `max_positions=10` |
| **E-2** | MEDIA-ALTA | **94** | VOLOVERLAY-DECL — El overlay de volatilidad está ON, muerde todos los días y no lo declara nadie |
| **D-1** | MEDIA | **95** | REGIME-DECL — El escalado por régimen no se modela y `deviations()` no lo declara |
| **D-2** | MEDIA | **96** | EARNINGS-DECL — El earnings blackout (Gate 6) está activo, el harness no lo modela y `deviations()` no lo nombra |

**Los dos casos que la skill avisa que se escapan, chequeados explícitamente:**

- **Hallazgo agrupado como "parte de" otro** — **ninguno**. El mapeo es **1:1**. Las tres de
  declaración (94, 95, 96) **comparten mecanismo** con la 92 —que es la que lo habilita— y
  eso está escrito **en el enunciado de cada una**, no sólo acá: ninguna se puede cerrar
  creyendo que otra la cubrió.
- **Hallazgo no verificado pero accionable** — **ninguno**. Los cinco se publican **medidos**:
  D-3 con la rejilla del T37 y el diff del backup de settings; E-1 re-contado por mí sobre
  `paper_orders` por ticker y con acciones; E-2 con el settings vivo, el log y el
  `target_dollars` del primer fill; D-1 con 0/62 BUY y el ΔCAGR de la T20; D-2 con la
  cobertura de `earnings_cache` y el 15,8% del replay de junio.

**Lo rechazado no lleva tarea, y eso es correcto:** D-4 (refutado y **borrado**, no
degradado), P1, Gate 2b, los gates sub-diarios, Gate 3b y Gate 4.

**Estado del repo al cerrar** (verificado por el `verificador`): suite **2581 passed, 3
skipped** en Windows, `check_repo_health.py` sin problemas sobre 2.711 archivos, árbol limpio
salvo este informe. **READ-ONLY cumplido: no se tocó código, config, esquema ni tests.**
