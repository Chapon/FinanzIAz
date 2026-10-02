# Auditoría — G · cuentas — 2026-10-02

Tarea **261** (primera corrida del área, creada por la 260). Skill `auditoria`, categoría G. READ-ONLY.

## 1. Kill-criteria

**Congelado:** 2026-10-02, junto con los de `pantalla` y `cuentas`/`operacion` (los tres a la vez, antes de abrir el primer archivo de código), aprobado por Chapa con un «seguir».

**Contaminación declarada:** antes de congelar ya se había visto (tarea 260) que la caja y las posiciones de las cuentas 1 y 2 cuadran al centavo contra fills, comisiones y dividendos, que `reconcile_account` sólo expira pendientes, y que `ui/news_tab.py` abre la URL de la noticia con `QDesktopServices`. Nada más.

### Alcance

- **Alcance (lista):** cuentas 1 y 2; tablas `paper_accounts`, `paper_orders`, `paper_positions`, `paper_equity_snapshots`, `paper_dividend_credits`, `paper_scan_candidates`; las reglas de cuenta del motor (`paper_trading/engine.py`, `strategies.py`, `account.py`).
- **Afuera:** si las decisiones fueron buenas (es trading: backtest con kill-criteria, regla 2).

### Qué se busca

- **G1** caja o posiciones que no cuadran con el historial.
- **G2** un momento de la historia en que se violó un límite declarado: posiciones > `max_positions`, caja < 0, órdenes en la cuenta 1 después de su pausa (2026-07-01).
- **G3** un flujo de plata que el harness modela y el motor no (splits, costos, dividendos), sin desvío declarado.
- **G4** snapshots que no coinciden con caja + posiciones del momento.

### Barrido limpio (las dos direcciones)

- **Dirección 1:** cero violaciones de cada límite **después** del arreglo correspondiente, y cuadre exacto.
- **Dirección 2:** cada flujo que el harness modela tiene su par en el motor o un desvío declarado en `deviations()`.

## 2. Alcance real

**Mirado:**
- La reconstrucción orden por orden de las cuentas 1 y 2: fills, comisiones y dividendos, ordenados por `filled_at`/`credited_at`. Contra eso: el pico de posiciones, la caja mínima y cada snapshot.
- Las órdenes de la cuenta 1 después del 2026-07-01.
- `_fill_trade` y `approve_order` (`paper_trading/engine.py`), que son el chequeo de caja.
- Las escrituras de `shares`, `avg_cost` y `high_water_mark` en `paper_trading/`, `data/`, `ui/` y `scripts/`.
- El camino de split de `data/yahoo_finance.py`.
- Las claves de `deviations_keyed`.
- Los settings vivos de las barreras ATR.

**NO mirado:**
- El modelo de costos del harness contra el del motor, comisión por comisión. Motivo: los desvíos de costos ya se auditaron en `desvios`.
- `paper_scan_candidates` más allá de su conteo. Motivo: tiene un día de vida.

## 3. Hallazgos

### [G-1] El motor vivo no ajusta las posiciones por split, y el harness corre sobre series split-neutrales
Severidad: **CRITICAL** · Confianza: **ALTA** en el mecanismo, **MEDIA** en la frecuencia · Categoría: G3 (flujo que el harness modela y el motor no)

**Ubicación:**
- `paper_trading/engine.py:657-675` (`_update_high_water_marks`) y `:2125` (la única escritura de `avg_cost`, que ocurre en la compra).
- `data/yahoo_finance.py:1213-1228`.
- `analysis/harness_config.py` (`deviations_keyed`).

**Evidencia:**
- Ninguna línea de `paper_trading/` ajusta `shares`, `avg_cost` ni `high_water_mark` por split.
- Ante un split plausible, el guard de precio invalida el cache y **acepta** el precio nuevo. Eso pasa al tercer rechazo (~45 min, `_ESCALATE_AFTER=3`), o antes si el cache ya se rebajó.
- BKNG tuvo un split 25:1 el 2026-04-06 (yfinance), así que el caso existe en el universo este año.

**Razonamiento** (con el impacto que corrigió el `verificador`):
- Desde el primer scan con precio aceptado, `compute_equity` valúa las acciones viejas al precio nuevo: la equity y el snapshot caen un (1−1/N) ficticio.
- Si el HWM alguna vez superó al `avg_cost`, el trailing (`gates.py:146-152`, que arma con `hwm > avg_cost + 1·ATR` usando la ATR nueva, N veces más chica) queda muy por encima del precio. Vende en ese mismo scan, y las salidas de riesgo no pasan por los gates.
- Si el HWM nunca lo superó, no hay venta ATR (con el hard stop OFF), pero la venta llega después por señal, con la misma pérdida.
- El harness corre sobre `auto_adjust=True`, donde un split no mueve nada, y `deviations()` no lo declara.

**Impacto:**
- Una pérdida realizada de, por ejemplo, el 50% (2:1) o el 96% (25:1) de la posición, que no existe en el mundo real.
- Además corrompe la curva de equity, Métricas y el cotejo vivo↔harness.

**Verificación:** el `verificador` buscó un ajuste en `dividends.py`, `reconcile`, la UI, `scripts/` y `data/`, un test con un split en una posición abierta, y algún guard que frenara la venta. No encontró ninguno.

**Exposición hoy:** ninguna. BKNG se compró después de su split, y MNST y AVB no tienen órdenes.

**¿Por qué no antes?** (b) FUERA DE ALCANCE: el área no existía. `desvios` miraba la config, no los flujos de plata.

**Acción:** tarea **262**.

### [G-2] Ningún chequeo cuadra la caja y las posiciones contra las órdenes
Severidad: **MEDIUM** · Confianza: **ALTA** · Categoría: G1 (en la dirección 2: lo verdadero que nada vigila)

**Ubicación:** `paper_trading/engine.py:2264` (`reconcile_account`, que sólo expira pendientes).

**Evidencia:** el cuadre a mano del 2026-10-02 cierra al centavo en las dos cuentas (cuenta 1: 91 fills; cuenta 2: 162), pero no lo corre nada.

**Razonamiento:** la caja ya se corrigió a mano una vez: las dos órdenes KLAC `voided` de la auditoría E5 (2026-07-01, *«caja revertida»*). Un descuadre futuro, ya sea por edición manual, por un bug de fill o por G-1, no avisaría.

**Trampa del instrumento**, que queda escrita en la skill: el slippage va **dentro** del `fill_price`, así que restar además `slippage_cost` descuadra una cuenta sana (cuenta 1 +$412, cuenta 2 +$374).

**Impacto:** un descuadre se descubre sólo si alguien rehace este cuadre a mano.

**¿Por qué no antes?** (b).

**Acción:** tarea **266**.

## 4. Barrido limpio en lo demás

- **G1:** el cuadre cierra al centavo en las dos cuentas.
- **G2:**
  - La cuenta 2 pasó `max_positions` en 15 momentos, hasta el 2026-09-02, que es el defecto que arregló la 93. **Después: ninguno.**
  - Caja negativa en la realidad: **nunca**. El −$64 de la cuenta 1 del 2026-06-29 que daba la reconstrucción es un artefacto: el snapshot de ese momento registró $7.866. La diferencia es la caja de las dos KLAC que E5 anuló el 2026-07-01.
  - La cuenta 1 no tiene órdenes después de su último scan (2026-07-01 16:20).
- **G4:** los 692 snapshots de la cuenta 2 coinciden con la caja reconstruida. Los 267 de junio de la cuenta 1 que no coinciden son las mismas dos KLAC: los snapshots muestran la caja **de ese día**, antes de la anulación. Es historia explicada, no un defecto vivo.
- **Dividendos:** el par motor↔harness existe desde la 222 y el desvío `dividendos` está declarado.

## 5. Hallazgos rechazados

- **«El chequeo de caja no cubre la aprobación manual»** (de la caja negativa de la cuenta 1). Retirado antes de pasar al `verificador`: `approve_order` llama al mismo `_fill_trade` (`engine.py:1901`), que tiene el chequeo desde `d5fa07d` (2026-05-01), y la caja negativa era un artefacto del instrumento (ver §4).

## 6. Limitaciones y lecciones

- **La reconstrucción ingenua confunde historia con defecto.** Una orden anulada después reescribe el pasado del ledger, pero no el de los snapshots. Comparar los dos sin modelar la anulación en su fecha fabrica caja negativa y 267 «descuadres». Se detectó contrastando contra el snapshot del momento, no confiando en la reconstrucción.
- La fase adversarial la hizo el agente `verificador`, independiente.

## 7. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| G-1 | 262 |
| G-2 | 266 |

