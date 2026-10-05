# Kill-criteria — revisión de arquitectura 2026-10-05 (tarea 313), congelado antes de abrir el código

Pedido de Chapa (2026-10-05): *«¿tenemos una auditoría de arquitectura o performance? ¿sería
necesaria?»* → *«hacerlo»*. READ-ONLY, como las auditorías: no se toca código; lo accionable entra
al backlog. **No es un área nueva de `/audit`**: es una revisión puntual, la segunda después de
`docs/architecture_review_2026-07-07.md`.

## Qué se mira (tres partes)

### 1. Seguimiento de la revisión de julio
- **Población:** las 7 propuestas de su tabla de priorización + las de §4, §6 y §7 que no están en
  la tabla (upsert de `earnings_cache`, cola única de escritura, telemetría de scan, split de
  archivos grandes, hypothesis, structured outputs, eval del classify) y los 4 puntos de §8 (*lo
  que NO cambiaría*).
- **Por cada una:** estado verificado **en el código y la DB**, no en el backlog — hecha, parcial,
  descartada con decisión escrita, o abierta sin dueño. Una propuesta abierta sin tarea ni decisión
  es un hallazgo (*«declarado no es cableado»*, la 97).
- **Y §8 se re-verifica:** ¿sigue siendo cierto que no hace falta cambiar eso? (Una afirmación de
  julio que nadie volvió a mirar es la forma de la 73.)

### 2. Los archivos grandes
- **Población:** los archivos `.py` de producción (no tests) de más de 1.500 líneas al 2026-10-05,
  listados por `git ls-files | wc -l`, no elegidos a mano.
- **Por cada uno:** crecimiento desde julio, **churn** (commits que lo tocan desde el 07-07),
  **qué mezcla** (responsabilidades que no tienen que ver entre sí), y **el costo concreto** de no
  partirlo: un defecto real del backlog que el tamaño o la mezcla haya causado o escondido. Sin un
  costo concreto, no es hallazgo: *«no refactorizar por deporte»* (la propia revisión de julio).
- **Afuera:** estilo, nombres, longitud de funciones sin consecuencia.

### 3. El diseño de la 196 (Lambda + DynamoDB) antes de construirlo
- **Mira:** el enunciado de la 196 y la 245, el probe (`scripts/build_probe_lambda_t196.py` y su
  handler), y los puntos de la app que cambiarían de fuente (consenso, noticias, harvest).
- **Busca:** supuestos del diseño que el código o el historial contradicen; decisiones que
  faltan tomar antes de escribir el recolector (esquema, point-in-time, idempotencia, cómo
  sincroniza la app, qué pasa con la regla 5); y costo (free tier) contra el volumen medido.
- **Afuera:** desplegar nada. El probe sigue esperando a Chapa.

## Qué contaría como «acá no hay nada»

- **Parte 1:** toda propuesta de julio está hecha, o descartada/diferida con decisión escrita y
  fechada, o tiene tarea; y los puntos de §8 siguen valiendo. **En la otra dirección:** ninguna
  parte del código de hoy contradice un *«no cambiaría»* de §8.
- **Parte 2:** ningún archivo grande tiene un defecto del backlog atribuible a su tamaño o a su
  mezcla en los últimos tres meses. **En la otra dirección:** ninguno de los archivos que *no*
  pasan el corte de líneas concentra churn o defectos como si lo pasara (el corte no es el riesgo;
  el churn sí).
- **Parte 3:** el diseño de la 196 no tiene supuestos que el código contradiga ni decisiones
  pendientes que bloqueen escribir el recolector.

## Fase adversarial

Los hallazgos HIGH o CRITICAL pasan por el `verificador` con el mandato de refutarlos, atacando
primero el instrumento.
