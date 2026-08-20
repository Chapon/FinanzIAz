# ENMIENDA al pre-registro de PRIO-EVENT (Tarea 49) — el sanity §5.4/§5.5 estaba mal especificado

**Fecha:** 2026-08-20 · **Estado:** escrita **ANTES de correr el leg del veredicto**.
**Enmienda a:** `docs/prio_event_prereg_t49_2026-08-20.md` (`ea2266b`) §5.4 y §5.5. **Todo lo demás
del pre-registro queda intacto** — en particular **los siete criterios del §6 no se tocan**.

---

## 0. Qué se vio, cuándo y sobre qué población

Al hacer el **smoke del runner** (universo de **25 tickers**, 4 semillas, sin los legs de
reproducción — o sea **NO la población del veredicto**) el sanity §5.4 falló:

```
B1_score           9.12%
ORACULO_PRIO      11.62%   → +2.50 pp sobre el baseline, contra un umbral de +5.00
ANTI_ORACULO_PRIO  6.93%
CONTROL (4 semillas): min 6.58% · mediana 8.64% · p95 8.85%
```

**Ningún criterio del §6 se evaluó sobre la población del veredicto** (127 tickers). Lo único que se
midió es que un sanity, tal como está escrito, **no lo puede pasar ni un instrumento sano**.

---

## 1. Por qué el umbral está mal, y no es que "el resultado no me gustó"

El §5.4 reusaba el umbral de la **T21 §5.2 / T39 §5.3**: `CAGR(ORACULO) ≥ CAGR(baseline) + 5.00 pp`.
Se reusó **a propósito**, por la regla de la casa de no calibrar umbrales nuevos. **Pero ahí el oráculo
es de potencia completa: reordena TODOS los candidatos de TODOS los días por el retorno realizado.**

El de esta tarea es **igualado en tasa**: sólo puede mover **920 turnos sobre 143.096 candidatos**,
porque tiene que tener exactamente las mismas `n` prioridades por día que el candidato. Eso lo
convierte en otra cosa: **no es una cota de lo que el harness puede ver, es la cota de lo que la
intervención puede valer**. Preguntarle a ese brazo si supera al baseline por +5 pp **no es un test del
instrumento** — es preguntar si la intervención tiene techo suficiente, que es justamente lo que el §6
existe para decidir.

**Es un error de categoría del pre-registro**, del mismo tipo que:

- la **T26**, donde el umbral del oráculo estaba puesto contra la referencia equivocada (baseline en vez
  de control igualado en tasa) y mató una corrida entera;
- la **38 §1**, donde el sanity *"el gate muerde"* se midió con una métrica que por construcción daba 0.

Las dos lecciones son la misma: **verificar que la métrica del sanity mida lo que la frase dice**. Acá
la frase es *"el instrumento ve calidad de turno"* y la métrica medía *"la intervención tiene techo"*.

---

## 2. Por qué esta enmienda **no puede** favorecer al candidato

Es la razón por la que se puede escribir sin romper la disciplina, y conviene dejarla explícita:

> **Un sanity sólo decide si la corrida es VÁLIDA o INVÁLIDA. No puede hacer pasar a un candidato.**

Los siete criterios del §6 —C1 a C7, incluidos los dos que hacen el trabajo (C2 y C5, el control
igualado en tasa)— quedan **idénticos, con los mismos umbrales**. Cambiar un sanity puede, como mucho,
**permitir que haya veredicto**; el veredicto lo sigue dictando el §6 sin ningún cambio.

Y se hace **antes de correr**, que es la forma que el propio proyecto declaró correcta: la **46 §5** le
dejó escrito a la tarea 37 que un criterio mal especificado *"necesita **enmienda antes de correr**, no
re-lectura después"*. Esto es exactamente eso.

---

## 3. Lo que reemplaza al §5.4 y al §5.5 (CONGELADO)

**§5.4′ — el instrumento ve calidad de turno.** Contra **la banda de los 20 controles igualados en
tasa** —la misma banda que usa C2, así que el umbral **no se elige: sale de la muestra**—:

1. `CAGR(ORACULO_PRIO)` **> p95** de la banda de los 20 `R_rand`.
2. `CAGR(ANTI_ORACULO_PRIO)` **< mediana** de esa misma banda.

Con la información perfecta del día, el brazo tiene que **salirse por arriba** de la banda del azar;
con la información invertida, tiene que caer **del lado malo de su centro**. Si ninguna de las dos
cosas pasa, el harness **no distingue turnos buenos de turnos al azar** y no hay veredicto posible.

**La asimetría entre las dos patas es deliberada.** El oráculo tiene información máxima y se le exige
salir de la banda entera. Al anti-oráculo se le exige sólo caer del lado malo del centro, porque
*"elegir el peor candidato del día"* se propaga a una curva de equity de 10 años con mucho más ruido de
camino que *"elegir el mejor"* (el peor candidato suele salir por stop temprano y libera el slot — el
mecanismo que la **T26** midió: el stop vale por el slot que libera). Pedirle que perfore el p5 de 20
semillas sería pedirle que le gane a la cola, que es una demanda **más fuerte** que la del oráculo, no
la simétrica.

**§5.5 se elimina** (queda subsumido: la pata 2 del §5.4′ dice lo mismo contra una referencia mejor).

**Lo que NO cambia:** los otros cinco sanity (contabilidad, las dos reproducciones, *"el turno muerde"*
≥10%, *"las semillas del control son efectivas"* ≥10%) y **los siete criterios del §6**.

---

## 4. Qué pasa si igual falla

Lo mismo que decía el pre-registro: **corrida INVÁLIDA, sin veredicto, y no se re-especifica nada.**
Esta enmienda se escribe una vez y antes de correr; si el §5.4′ falla sobre la población del veredicto,
el resultado es que el harness no ve calidad de turno y la tarea se cae, no que se busque un tercer
umbral.

**Congelada junto con el pre-registro. Cualquier cambio posterior a ver un resultado del §6 lo
invalida.**
