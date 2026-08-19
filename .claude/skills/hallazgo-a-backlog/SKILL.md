---
name: hallazgo-a-backlog
description: Todo defecto encontrado durante un análisis, auditoría, backtest o code review tiene que quedar como TAREA en docs/BACKLOG.md antes de cerrar lo que se estaba haciendo. Usar cada vez que aparece un bug, un desvío harness↔engine, un supuesto falso o un número que no cierra — incluso (sobre todo) si no es el tema de la tarea en curso.
---

# Hallazgo → tarea en el backlog

**Regla de Chapa:** si lo encontraste, se anota. Un defecto que vive sólo en un doc de
análisis, en un comentario de código o en el chat **no existe** — se pierde. El único lugar
que se lee al empezar una sesión es `docs/BACKLOG.md` (ver `CLAUDE.md`), así que ahí tiene
que aterrizar.

Esto **no** es opcional ni depende de la severidad. Un hallazgo chico se anota como tarea
chica; uno grande, como tarea grande. Lo que no se hace nunca es dejarlo sin anotar porque
"era menor" o porque "no era el tema de esta tarea".

## Qué cuenta como hallazgo

- **Bug** de código (excepción, resultado incorrecto, condición de borde).
- **Desvío harness↔engine**: el backtest simula algo distinto de lo que ejecuta producción.
  La serie T27/T32/T33/T34 son exactamente esto, y **dos de ellos dieron vuelta veredictos
  enteros** (T33 dio vuelta la T23 y caducó la T26).
- **Supuesto falso escrito en un doc o en un banner** — la frase *"el fill sí está modelado;
  la decisión no"* de la T32 era falsa en modo `close` y tapó un look-ahead durante cinco
  harness.
- **Número que no cierra** contra otra fuente (panel vs DB, harness vs cuenta viva, doc vs
  código).
- **Config que difiere** de la cuenta viva sin estar declarada.
- **Deuda que ya causó un error de lectura real** (ej.: `CLAUDE.md` desactualizado, T30).

## Qué hacer, en orden

1. **Terminá de verificarlo.** Un hallazgo se anota con evidencia: `archivo:línea` del
   código, o el número medido y cómo se midió. Nada de "me parece que". Si hace falta una
   sonda, corrés la sonda (barata, en el scratchpad) y anotás el número.
2. **Decidí el alcance — y es una decisión, no un reflejo:**
   - **Tarea nueva en el backlog** si es independiente de lo que estás haciendo, o si toca
     veredictos/decisiones ya publicadas. Es el default.
   - **Adentro de la tarea en curso** sólo si es un enabler que esa tarea **necesita** para
     poder medir bien (patrón: `eval_mode` en la 26b, `live_gates` en la 34). Aun así **se
     anota en el backlog** como parte del alcance de la tarea en curso, con el número medido.
   - Nunca "lo arreglo de paso y no lo anoto".
3. **Escribí la entrada** con el formato de abajo, en `docs/BACKLOG.md`, sección
   *Próximo* (priorizada) o *Bugs / robustez de datos* según corresponda.
4. **Priorizá con la política de Chapa** (ver `CLAUDE.md` y el encabezado del backlog):
   calidad de datos y guardrails que no dependen de alpha primero; features especulativas
   nunca. Si el hallazgo invalida o ensucia una medición futura, va **antes** que la
   medición — ése es el patrón de la T32/T33, que se metieron adelante de la 26b y la 34.
5. **Si el hallazgo toca un veredicto ya publicado**, decilo explícitamente en la entrada y
   marcá si obliga a re-leerlo. Re-leer es su propia decisión, con su propio criterio
   (T33 §"el criterio que queda": *¿los brazos disparan a tasas distintas?* Si no, el
   defecto es un nivel común y se cancela; si sí, puede dar vuelta el signo).

## Formato de la entrada

```markdown
### <n>. <SLUG-CORTO> — <una línea de qué está mal>  ·  ref `<doc o archivo:línea>` · severidad <BAJA|MEDIA|ALTA> · **<por qué importa en 3-6 palabras>**
- **Qué:** el defecto, con `archivo:función` o `archivo:línea`. Verificado en código, no asumido.
- **Cuánto vale (medido):** el número, y cómo se midió. Si no se midió todavía, decir que no.
- **Por qué NO es automáticamente X:** la lectura alternativa defendible, si la hay.
- **Alcance:** qué se tocaría, y qué explícitamente NO.
- **Dependencias:** qué lo bloquea o qué destraba.
```

El slug va en MAYÚSCULAS-CON-GUIONES (`FILL-LOOKAHEAD`, `STOP-PRICE`, `CACHE-IND`) y se
reusa después en los mensajes de commit y en el nombre del doc.

## Qué NO hacer

- **No arreglar en silencio** un defecto que encontraste mientras hacías otra cosa. Aunque
  sea una línea. Se anota, y si es trivial se arregla en su propio commit citando la entrada.
- **No dejarlo sólo en el doc de la tarea.** El veredicto de la 26b abrió la 33 y la 34
  **en el backlog**, no sólo en su §6.
- **No inflar la severidad** para que se haga antes. La severidad es del defecto; la
  prioridad la decide el orden del backlog.
- **No abrir una tarea sin evidencia.** Una sospecha sin verificar va a *Backlog / ideas
  (sin priorizar)*, no a *Próximo*, y dice que es sospecha.

## Cierre

La tarea en curso **no se declara terminada** hasta que sus hallazgos laterales estén
anotados. Al cerrar: suite verde → commit → backlog actualizado (la tarea cerrada a *Hecho
reciente* con el hash **y** las tareas nuevas que abrió) → `git push`. Ver `git-workflow`.
