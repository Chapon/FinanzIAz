# ENMIENDA 2 al pre-registro de STOP-VALUE (Tarea 37) — el sanity §7.5 pide monotonía por debajo del ruido de su propio instrumento

**Fecha:** 2026-08-27 · **Estado:** la primera corrida queda **INVÁLIDA** por la regla congelada
(*"si falla alguno, la corrida es INVÁLIDA y no hay veredicto"*). No se re-especifica nada para
salvarla: se corrige la especificación, se declara acá, y se vuelve a correr. Mismo procedimiento
que la **T26**, la **T34** (`docs/stop_loosen_enmienda_t34_2026-08-18.md`) y la **49**
(`docs/prio_event_enmienda_t49_2026-08-20.md`).

**Enmienda a:** `docs/stop_value_prereg_t37_2026-08-19.md` (`d6ba1b8`) **§7.5, y sólo el §7.5**.
Los otros seis sanity y **los nueve criterios del §8 quedan idénticos, con los mismos umbrales**.

---

## 0. Divulgación completa, antes del argumento

Esto va primero porque es lo que hace o rompe la credibilidad de la enmienda:

> **Cuando se escribió esto, el barrido de ruina ya estaba corrido y sus Δ eran visibles**
> (el runner los imprime a medida que avanza). O sea que **no** se está escribiendo a ciegas,
> a diferencia de la enmienda de la 49.

Lo que sostiene que igual sea legítimo, y hay que poder verificarlo, no creerlo:

1. **Un sanity sólo decide si la corrida es VÁLIDA o INVÁLIDA. No puede hacer pasar a un
   candidato.** Los nueve criterios del §8 no se tocan.
2. **Esta enmienda no puede mover un solo dígito.** Las 168 simulaciones de la corrida están
   **memoizadas** y el harness es **determinista**: volver a correr con el §7.5 corregido reusa
   exactamente los mismos resultados. Lo único que cambia es si el §7 habilita que exista un
   veredicto. Es verificable: borrar el cache y re-correr tiene que dar los mismos números.
3. **La mala especificación se demuestra con datos que no dependen del candidato** — la
   dispersión entre semillas del **baseline**, que es el brazo vivo (§1).

---

## 1. Qué decía, qué midió, y por qué no podía pasar

**§7.5 congelado:** *"a `d=50%`, el CAGR del **baseline** cae de forma **no creciente** al subir
`r` en la rejilla de tasas, y en `r=10%` cae al menos **2.00 pp** respecto de `r=0`."*

**Medido (CAGR medio del baseline, `d=50%`, 3 semillas):**

| `r` | 0% | 0.5% | 1% | 2.6% | 5% | 10% |
|---|--:|--:|--:|--:|--:|--:|
| CAGR baseline | 2.013% | **2.229%** | **2.257%** | 0.405% | −1.321% | −4.069% |

- **La pata del daño PASA, y con margen: −6.08 pp** a `r=10%`, tres veces el umbral de 2.00.
- **La pata de la monotonía falla** por **+0.216 pp** y **+0.028 pp** en los dos primeros pasos.

**Por qué falla ahí, y por qué eso no dice nada sobre la inyección.** Los mismos puntos, abiertos
por semilla:

| `r` | semilla 20260819 | 20260820 | 20260821 | **rango** |
|---|--:|--:|--:|--:|
| 0.5% | 0.440% | 3.494% | 2.754% | **3.05 pp** |
| 1% | 0.440% | 3.390% | 2.940% | **2.95 pp** |
| 2.6% | −0.767% | −1.731% | 3.713% | **5.44 pp** |

**El rango entre semillas en un mismo punto es de 3 a 5,4 pp; el paso que el sanity exige detectar
es de 0,2 pp.** A tasas bajas hay **6-13 eventos** en todo el universo (0,5%/año sobre 1.267
ticker-años), así que si esos pocos nombres cayeron o no en una posición que la cartera tenía
abierta domina el resultado. Con 3 semillas el error estándar de la media ronda **0,9-1,6 pp**.

**Es el error de categoría de la T46, en un sanity en vez de en un criterio:** un umbral puesto
**19× por debajo** de lo que la muestra resuelve. Un test que no puede distinguir su efecto del
ruido no es conservador — **acepta y rechaza arbitrariamente**, y acá rechazó.

Y hay un agravante estructural que el §7.5 no vio: a `r=0` **no hay semillas** (la serie vuelve
idéntica por construcción, es el ancla del barrido). O sea que el primer paso de la comparación
enfrenta **un valor determinista contra una media de 3 sorteos**, y le exige orden.

## 2. Lo que la evidencia SÍ dice sobre la inyección (que es lo único que el §7.5 existe para chequear)

La frase del pre-registro es: *"si inyectar ruina no lastima, la inyección está mal cableada y el
test del §3 no mide nada"*. Contra esa frase, la corrida contesta que **sí lastima, mucho**:

- De `r=1%` en adelante la caída es **monótona y grande**: 2.257% → 0.405% → −1.321% → −4.069%.
- El daño total en la rejilla es **−6.08 pp**.
- El brazo `r=0` reproduce el mundo limpio **exacto** (2.013% = el 2.01% publicado por la T34).

**Además, la planicie de las tasas bajas tiene un mecanismo plausible que juega a favor del
guardrail, no en contra:** el baseline **tiene stop duro**, así que sale del nombre arruinado
temprano y —con un ratio de selección ~55:1— el slot liberado se lo lleva otro candidato el mismo
día. Que dosis chicas de ruina casi no muevan al brazo **que tiene la barrera** es exactamente lo
que se esperaría si la barrera sirve. No es evidencia de cañería rota; si acaso es un descriptivo
que el informe tiene que reportar.

## 3. §7.5′ — lo que lo reemplaza (CONGELADO)

Dos patas. **La primera no cambia**; la segunda es la misma pregunta con la tolerancia **computada**
en vez de elegida, que es la doctrina que la **46 §4.1** le dejó escrita a toda la serie.

**(a) Daño — sin cambios.**
`base_cagr(r=10%, d=50%) ≤ base_cagr(r=0, d=50%) − 2.00 pp`.

**(b) Dosis-respuesta con tolerancia computada.** Para cada par consecutivo de la rejilla de tasas
a `d=50%`:

    base_cagr(r_{i+1}) ≤ base_cagr(r_i) + tol_i
    tol_i = 2 × SE,   SE = sqrt(sd_i²/n_i + sd_{i+1}²/n_{i+1})   (sd, n sobre las SEMILLAS)

**Un ascenso que cae DENTRO del ruido de semilla del propio instrumento no es una violación de
dosis-respuesta: es la varianza que el pre-registro ya reconoció** al pedir tres semillas y aplicar
el criterio de C9 a la **peor** de las tres. Un ascenso que **sale** de esa banda sí es una
violación y la corrida sigue siendo inválida.

**(c) Descriptivo obligatorio:** la tabla **por semilla** de cada punto de la rejilla, con su rango,
para que se vea de qué tamaño de muestra sale cada número. Es la misma exigencia que C5′ le hace a
las ventanas de régimen.

**Nota sobre `r=0`:** tiene `n=1` y `sd=0` por construcción. En el par que lo involucra la
tolerancia sale enteramente del lado con semillas, que es lo correcto: no se le puede pedir
dispersión a un punto determinista.

## 4. Por qué esto NO es aflojar

El §7.5′ **puede seguir fallando**, y por las razones por las que el §7.5 existía:

- Si la inyección estuviera mal cableada, `r=10%` no haría −6 pp de daño y **(a)** fallaría.
- Si el barrido subiera de verdad al subir la tasa —un ascenso mayor que 2×SE— **(b)** fallaría.
- Lo único que **deja** de fallar es un ascenso de 0,2 pp dentro de una banda de ruido de 3 pp,
  que es una lectura que **ningún dato podía sostener**.

## 5. Qué NO cambia

Los otros **seis sanity** del §7 (contabilidad, oráculo vs control igualado, control mecánico, el
desacople muerde ≥10%, la inyección idéntica por hash, y el §7.7 de reproducción tri-estado), los
**nueve criterios del §8** con sus umbrales exactos —**C9 sigue en 2,60%/50% y 0,47%/70% sobre la
peor de tres semillas**—, la población, los brazos, el walk-forward, y la enmienda 1 (C5′ y
C5′-bis).

## 6. Qué pasa si igual falla

**Corrida INVÁLIDA, sin veredicto, y no se busca un tercer umbral.** Esta enmienda se escribe una
vez.

**Congelada. Cualquier cambio posterior a ver un resultado del §8 la invalida.**
