# Veredicto — El simulador gastaba plata que no tenía, y no movió nada (Tarea 123, CASH-SOBREGIRO)

**Fecha:** 2026-09-07 · **Origen:** hallazgo al medir la tarea 122.
**Toca:** `analysis/portfolio_sim.simulate_portfolio` — el simulador que comparten los 26 lectores del
cohorte. **Re-lectura declarada, patrón T33** (`docs/fill_lookahead_t33_2026-08-16.md`).

---

## VEREDICTO: el defecto era real, el arreglo es correcto, y **ningún número publicado se mueve**

El efecto máximo sobre cualquier brazo en cualquier marco es **−0,04 pp de CAGR** (el oráculo).
Ningún veredicto cambia, ningún brazo seleccionado cambia, el PBO se mueve ≤0,004. La re-lectura se
hace igual y se publica igual: *"no movió nada"* es un resultado sólo si se muestra el antes y el
después.

**Y el hallazgo que sí vale es del instrumento, no del simulador:** el contador con el que la tarea
122 midió el radio de impacto **mentía en el caso más común**, y su número —*"cero en el
baseline"*— era un artefacto. La corrección está en §3.

---

## 1. El defecto

`buy_cost` cobra comisión y slippage **sobre** el gross: `entry_cost = notional × (1 + c + s)`.
El tope de cash topaba el **gross**:

```python
notional = min(notional, cash)          # ANTES
entry_cost = notional * (1 + fees)      # > cash
```

O sea que una entrada topada gastaba **más cash del que había**, dejaba el cash **negativo**, y todo
candidato posterior se rechazaba hasta el próximo cierre. Probado con el caso mínimo que quedó como
test: **capital 10.000 → invertido 10.015**.

**Es la misma línea que la T10 arregló una vez.** Aquélla cambió *rechazar* por *recortar* —rechazar
dejaba cash ocioso **y** perdía la entrada—. El recorte quedó corto por el monto de los fees.

**El arreglo:** topar por lo que se puede **pagar**, no por lo que se tiene.

```python
asequible = cash / (1.0 + costs.commission + costs.slippage)   # DESPUÉS
notional = min(notional, asequible)
```

Sin fees el divisor es 1.0 y no cambia nada, que es lo que fija uno de los tests.

## 2. La re-lectura (patrón T33) — los tres marcos

**Radio de impacto: un solo runner.** `run_sizing_exposure_t10_t20.py` es el **único** que pasa
`size_weight`; los demás van por la rama `size_weight is None`. Pero el defecto **no era exclusivo de
los brazos de sizing** (§3), así que se re-leyeron los tres marcos completos.

### A · 5 slots, 41 tickers, gates OFF — el marco del veredicto de la T10

| brazo | CAGR antes | CAGR después | Δ | Sharpe | entradas topadas |
|---|--:|--:|--:|--:|--:|
| `B0_equal_weight` | 14.05% | 14.04% | −0.01 pp | 0.81 → 0.81 | 791 |
| `S1_inverse_vol` | 10.53% | 10.52% | −0.00 pp | 0.72 → 0.72 | 270 |
| `S2_vol_target` | 10.34% | 10.34% | −0.00 pp | 0.75 → 0.75 | 112 |
| `R2b_f025` | 14.78% | 14.77% | −0.00 pp | 0.96 → 0.96 | 649 |
| `R2b_f050` | 14.57% | 14.56% | −0.01 pp | 0.89 → 0.89 | 649 |
| `R2b_f075` | 14.31% | 14.31% | −0.01 pp | 0.84 → 0.84 | 649 |
| `C_S2xf050` | 10.11% | 10.11% | −0.00 pp | 0.80 → 0.80 | 107 |
| **`V_oracle_size`** | 28.69% | **28.64%** | **−0.04 pp** | 1.51 → 1.51 | 305 |

PBO 0.115 → 0.111 · brazo seleccionado `R2b_f025` → `R2b_f025`.

### A · 5 slots, 41 tickers, gates ON — la corrida **VÁLIDA** de la tarea 115

Δ de CAGR **−0.00 pp** en los siete candidatos y **−0.04 pp** en el oráculo (27.38% → 27.34%).
PBO 0.103 → 0.103, brazo seleccionado sin cambio.

**Lo que importa acá es el sanity §5.3 de la 115**, que exige `CAGR(oráculo) ≥ CAGR(B0) + 5.00 pp`:
pasa de **+14.66 pp** a **+14.63 pp**. La corrida A **sigue siendo VÁLIDA** y el veredicto de la 115
—`R2b_f050` falla C1 con ΔSharpe +0.08— **no se mueve ni en el tercer decimal**.

### B · 10 slots, 127 tickers — el marco vivo, donde la 121 va a correr

Δ de CAGR **≤0.01 pp** en los siete y −0.04 pp en el oráculo. PBO 0.647 → 0.651. Sin brazo
seleccionado en las dos corridas.

**`S1_inverse_vol` sigue con 116 rechazos por `n_no_cash` después del arreglo, y eso es correcto:**
el arreglo elimina el **sobregiro**, no el rechazo. Ese brazo genuinamente se queda sin plata porque
concentra, y el engine vivo tampoco podría comprar sin cash. El rechazo es fiel; lo que no lo era es
gastar de más.

## 3. La corrección que le debo a la tarea 122: el contador mentía

La 122 reportó *"muerde **sólo** a los brazos con `size_weight`: 267 en `inverse_vol`, 301 en el
oráculo, y **0 en `B0` y en los tres `R2b`**"*, y concluyó que **no era un nivel común**. Eso era un
artefacto del contador, no un hecho.

**Por qué:** el contador preguntaba `notional > cash` con `>` estricto. Cuando queda **un solo slot
libre**, `base = cash / 1 = cash` **exacto**, así que `cash > cash` es falso y no contaba — y ésa es
precisamente la entrada que sobregiraba. El contador era ciego justo en el caso más frecuente.

Con el predicado correcto (`notional > cash / (1+fees)`, que es **exactamente** la condición bajo la
cual el código viejo sobregiraba):

| brazo | 122 decía | de verdad era |
|---|--:|--:|
| `B0_equal_weight` | **0** | **791** |
| `R2b_f025/f050/f075` | **0** | **649** cada uno |
| `S1_inverse_vol` | 267 | 270 |
| `V_oracle_size` | 301 | 305 |

**Consecuencia para la lectura:** el defecto tocaba a **todos** los brazos, no sólo a los de sizing,
y por lo tanto estaba **mucho más cerca de un nivel común** de lo que la 122 afirmó — que es
justamente por lo que el Δ medido es ~0 en todos. La conclusión de la 122 (*"es la forma exacta del
quinto desvío"*) **queda retirada**; el paralelo con la T33 no se sostiene.

**La lección, que es la de siempre en este repo:** el instrumento se valida antes de creerle al
número. Un `>` estricto contra el borde exacto es la versión aritmética del *«guard que no puede ver
el defecto mayoritario»* de la 110 y la 101.

## 4. Qué NO cambia

- **Ningún veredicto publicado.** T10 (NO-SHIP de sizing), T20 (SHIP de régimen), y el de la 115
  (`f050` falla C1) se sostienen con los mismos dígitos.
- **El sanity del oráculo de la 115 sigue pasando** con margen de 9,6 pp sobre su umbral.
- **Los rechazos por cash** de `inverse_vol` en el marco vivo: son legítimos y se quedan.

## 5. Reproducir

```
python scripts/run_sizing_exposure_t10_t20.py --max-positions 5 [--live-gates] --json
python scripts/run_sizing_exposure_t10_t20.py --max-positions 10 \
    --universe data/harness_universe_live_acct2.txt --json
```

Ventanas `2016-09-01..2026-09-01` (2513 barras, 41 tickers, 4015 entradas) y
`2016-08-08..2026-09-01` (2514 barras, 127 tickers, 12404 entradas). **Son RODANTES** (T48).
