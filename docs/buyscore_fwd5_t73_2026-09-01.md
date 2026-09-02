# BUYSCORE-REVERIFY (tarea 73) — el número que sostiene la regla 3, re-medido

**Fecha:** 2026-09-01 · **Instrumento:** `scripts/measure_buyscore_fwd5_t73.py` (offline, reproducible)
· **Display-only:** no cablea nada, no toca sizing ni gates · **Origen:** hallazgo P2 de
`docs/auditoria_claims_2026-09-01.md`

---

## 1. Qué se estaba usando, y desde cuándo

`CLAUDE.md` justifica la **regla 3 no-negociable** —*"Display antes que sizing"*— con un
paréntesis: *"(`buy_score` no predice el fwd5 — auditoría 2026-06-17)"*. La skill
`fair-value-feature` cuelga de la misma regla su restricción dura de que la feature entra
display-only.

**Tres meses, y nadie lo re-verificó.** La auditoría de `claims` lo dejó explícitamente sin
verificar —comprobarlo exige re-correr la medición— y por eso **no** lo reportó como hallazgo;
lo que sí es un hecho verificable es que nadie lo re-chequeó, y de ahí salió esta tarea.

## 2. Qué midió el original, para medir LO MISMO

`docs/ops_logic_audit_2026-06-17.md` §4 y `ops_logic_deep_audit_2026-06-17.md` §A3:

> **corr(buy_score, fwd5) ≈ 0.00 (n=21).**

donde `buy_score = _default_strength("BUY", ml_probability)` = la `ml_probability` clampeada a
[0,1] — que es exactamente lo que persiste `paper_orders.signal_score`. La métrica se reproduce
sobre la misma cantidad, con la muestra de hoy.

**Un guard que el original no tenía:** `_default_strength` devuelve **1.0** cuando no hay
`ml_probability`, así que un `signal_score` de exactamente 1.0 puede ser *"sin score"* y no
*"máxima convicción"*. Se excluyen y se reportan. **Hoy son cero**, pero el guard queda.

## 3. Criterio de aceptación, congelado ANTES de computar la correlación

Declarado con tres desenlaces y qué se hace con cada uno:

| | condición | acción |
|---|---|---|
| **(A)** el claim se sostiene | IC95% de `r` contiene el 0 **y** efecto detectable al 80% ≤ **0.30** | actualizar el paréntesis con número y fecha |
| **(B)** el claim caducó | IC95% **no** contiene el 0 | retirar el paréntesis, abrir tarea |
| **(C)** nunca tuvo respaldo | detectable al 80% > 0.30 | corregir **la afirmación**, no el número |

**Predicción declarada:** (C), porque con n=21 el detectable es |r| ≈ 0.58.

## 4. El resultado

**94** órdenes BUY llenadas con score real · **0** excluidas por el fallback · **9** sin `fwd5`
(todas del **27-ago al 1-sep**: no llevan 5 ruedas cumplidas — truncamiento por recencia, no
sesgo de selección) ⇒ **n = 85**.

| muestra | n | r | IC95% | detectable 80% | fwd5 medio |
|---|--:|--:|---|--:|--:|
| **las dos cuentas** | **85** | **−0.046** | **[−0.26, +0.17]** | **0.300** | +0.93% |
| cuenta 2 (viva) | 53 | +0.100 | [−0.18, +0.36] | 0.38 | +0.58% |
| cuenta 1 (pausada) | 32 | −0.058 | [−0.40, +0.30] | 0.48 | +1.52% |
| *original 2026-06-17* | *21* | *≈0.00* | *—* | ***0.58*** | *—* |

## 5. El veredicto, y por qué no es el que imprime el script

**Por la letra del criterio congelado es (A)** — el IC95% contiene el 0 y el detectable es
**0.29972**, contra un umbral de 0.30. **Pasa por 0.00028.**

**Eso no es un aprobado: es un empate técnico**, y la conclusión honesta es (C). El criterio que
congelé era **demasiado laxo**, y eso se ve al preguntar qué descarta la muestra:

| |r| real | ¿lo descartaría esta muestra? |
|---|---|
| 0.10 | **no** |
| 0.15 | **no** |
| 0.20 | **no** |
| 0.30 | sí, apenas |

Una correlación real de **0.15** entre el score y el retorno a 5 días sería **económicamente
relevante**, y con 85 compras **no se puede descartar**. Así que la afirmación que la muestra
sostiene no es *"el `buy_score` no predice el fwd5"* sino **"con 85 compras no se detecta nada
por encima de |r| ≈ 0.30, que no alcanza para afirmar que no predice"**.

**No se mueve el umbral después de ver el dato** — queda registrado que el criterio congelado
dice (A). Lo que se reporta es que **el umbral estaba mal elegido**, que es una afirmación sobre
el criterio y no sobre el resultado. Y la **acción es la misma bajo las dos lecturas**, así que
la decisión es robusta al borde: el paréntesis pasa a decir qué se midió, con `n` y con poder.

## 6. Lo que sí queda establecido, y es el hallazgo

**El claim original nunca pudo sostener lo que afirmaba.** Con **n=21**, el efecto detectable al
80% es **|r| = 0.58** — una correlación que no existe en finanzas a 5 días. Aquella muestra **no
podía distinguir *"no predice"* de *"no se midió"***, cualquiera fuera el número que diera. El
`≈ 0.00` no era evidencia de ausencia: era ausencia de evidencia.

Es la misma lección que la **T46** dejó para el criterio de régimen —*"el criterio no es
inservible; el umbral sí"*— y por eso el instrumento reporta **siempre** el detectable al 80%
al lado del `r`.

**Y una advertencia sobre la métrica misma**, que vale para cualquier re-lectura futura: Pearson
mide lo **lineal**. Una relación en V es perfectamente determinística y da `r` **exactamente 0**
(está fijado en `tests/test_buyscore_fwd5_t73.py`). Un `r ≈ 0` dice *"no hay información
lineal"*, no *"no hay información"*.

## 7. Qué NO dice este documento

- **No toca la regla 3.** Su fundamento —no cablear a sizing lo que no se backtesteó— **no
  depende de este coeficiente**, y sigue en pie exactamente igual. Lo que se re-midió es la
  **evidencia citada**, no la política.
- **No dice que el score sirva.** El punto es que **no se sabe**, y que la muestra necesaria para
  saberlo es bastante más grande: para descartar |r| = 0.15 al 80% harían falta ~**350** compras.
- **No mide la cuenta 2 por separado con poder**: n=53 detecta 0.38. El `+0.100` de esa fila es
  descriptivo y **no se puede leer como señal**.
- **No es un backtest.** Mide las compras que el motor efectivamente hizo, no todos los
  candidatos. La versión con poder de verdad correría sobre el artefacto PIT (141k eventos) —
  otra población y otra pregunta, con su propio pre-registro.
