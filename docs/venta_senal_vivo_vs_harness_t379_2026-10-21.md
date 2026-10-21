# Venta por señal: el vivo contra el harness — tarea 379, 2026-10-21

**Veredicto: es la ventana (lectura a), no un desvío.** El veredicto de la 219, y con él el de la
familia de salidas, queda en pie. No entra ninguna clave nueva en `deviations_keyed()` ni se abre
una re-lectura de la 219.

## La pregunta

En la cuenta 2, lo vendido con `analyze SELL` le perdió a SPY 3,6% a 20 ruedas
(`docs/rendimiento_app_vs_cartera_2026-10-20.md` §3), y lo comprado en su lugar, 0,9%. En el vivo,
vender y reemplazar **sumó**. El harness de la T7 y de la 219 dice lo contrario: cuanto menos se le
obedece a la señal, mejor rinde la cartera. Hay dos lecturas: **(a)** la ventana, cuatro meses con
ventas superpuestas, o **(b)** un desvío harness↔engine, es decir, que el harness simula una venta
que el motor no hace.

## Instrumento

`scripts/measure_venta_senal_vivo_vs_harness_t379.py`. Sólo lectura: no escribe la DB ni pega a la
red.

- **Harness:** el brazo `age3` de la 219 (la política viva: `min_age` 3, bypass 0,25, trailing 2,0,
  TP 4,0, sin hard stop, fill honesto, `live_gates`) sobre el cohorte de la cuenta 2.
- **El cohorte termina el 2026-09-09.** No se refrescó para esto, porque mover la muestra obliga a
  re-anclar las constantes de reproducción de todos los runners. Los guards del cohorte (T76, T86)
  abortan con exit 3, y la medición corrió con `--allow-stale-artifacts`, declarado (ventana
  `2016-09-12..2026-09-09`, 2512 barras). El recorte comparable es **2026-06-20 → 2026-09-09**.
- **Vivo:** los fills de la cuenta 2, con la DB abierta en sólo lectura (`readonly_uri`).
- **Exceso sobre SPY** desde el cierre de la rueda de la operación. En el vivo, la rueda es la fecha
  de NY del fill; si fue antes de la apertura, la rueda anterior. El ticker y SPY salen siempre del
  mismo frame (`2y` si el evento cae adentro, si no `10y`), sin empalmar.
- **IC95%** por bootstrap de **bloques de `h` ruedas** de la fecha del evento. Las ventas del mismo
  día, y las de días con ventanas superpuestas, entran o salen juntas.
- **Validación del instrumento:** sobre el vivo completo da −0,74% / −1,96% / −3,67% a 5/10/20
  ruedas, contra −0,55% / −2,01% / −3,58% del doc de origen. La diferencia es la regla de la rueda
  base.

## Resultado

Exceso sobre SPY a **+20 ruedas** (la tabla entera, a 5 y 10, la imprime el script):

| | vendido | comprado | n ventas | bloques |
|---|---|---|---|---|
| harness, 10 años | **+0,25%** [−0,11, +0,61] | +0,33% [−0,01, +0,67] | 1.919 | 114 |
| harness, recorte | −0,72% [−2,39, +3,66] | −1,16% [−3,72, +1,55] | 56 | 3 |
| vivo, recorte | **−3,69%** [−7,20, −0,45] | −1,17% [−3,87, +0,91] | 33 | 3 |
| vivo, hasta hoy (referencia) | −3,67% [−6,06, −0,92] | −0,93% [−2,21, +0,50] | 42 | 4 |

Y la prueba que no depende de qué tenía cada cartera: **cada vez que la señal PIT de un ticker del
universo pasa a SELL**.

| giros a SELL del universo | +5 | +10 | +20 |
|---|---|---|---|
| 10 años sin el recorte (n = 28.287) | +0,02% | +0,06% | +0,15% [−0,11, +0,41] |
| recorte (n = 772) | +0,05% | −0,17% | **−0,79%** [−3,09, +1,28] |

## Lectura

1. **En diez años, lo que la señal vende no le pierde a SPY.** Da +0,25% en el harness y +0,15% en
   el universo entero, con IC que cruzan el cero. Vender y reemplazar da ≈ 0 (+0,33 contra +0,25).
   Es coherente con la T7 y la 219: obedecer a la señal no suma.
2. **La ventana entera se inclinó en contra de lo vendido.** En el recorte, los giros a SELL de todo
   el universo, sin cartera de por medio, dan −0,79%. El harness con su cartera da −0,72%. El signo
   es el del vivo.
3. **El vivo es el extremo de esa ventana, no otra cosa.** −3,69% con 33 ventas y **3 bloques**: el
   IC del harness en el recorte (−2,39 a +3,66) y el del vivo (−7,20 a −0,45) se solapan. Con 3
   bloques a 20 ruedas, el bootstrap apenas tiene con qué remuestrear, y el n efectivo es mucho
   menor que 33.
4. **No es la señal.** De las 33 ventas del vivo hasta el 09/09, **28** coinciden con un SELL de la
   señal PIT del harness (27 el mismo día y 1 el anterior). Esas 28 son justamente las peores:
   **−4,04%** a 20 ruedas, contra −1,69% de las otras 5. Lo que el vivo vendió de más mal no son
   ventas que el harness no haría. Son ventas que el harness también haría, sobre posiciones que su
   cartera, por camino, no tenía.

## Lo que deja medido, sin tarea nueva

**Las 5 ventas que el PIT no ve** (DE 30/06, EXC 08/07, SLB 24/07, JNJ 28/08 y DE 08/09) tienen la
señal PIT en BUY ese día y el anterior. DE el 08/09 se vendió a las 18:45 de NY, con la barra
completa, así que no es la barra parcial de la 293. Es el desvío **ya declarado** con clave de la
ventana de `analyze()` (504 barras fijas en vivo contra la ventana expandida del PIT: *«no es el
mismo generador de señal»*). Lo que no se tenía era el número del lado de las ventas: **28 de 33
(85%)** coinciden. Del lado de las compras, la 293 midió 63 de 64 contra el mismo `analyze()` con
ventana viva, que es otra comparación.

## Límites

- El harness termina el 2026-09-09. Las 14 ventas del vivo posteriores entran sólo en la
  referencia.
- La lectura (a) **no afirma que la ventana sea un régimen**. Afirma que con esta muestra no se
  distingue el vivo del harness, y que el número con potencia (10 años) dice ≈ 0.
