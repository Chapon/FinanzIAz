# Ajuste por spin-off — tarea 298 — 2026-10-04

Origen: la 297, por decisión de Chapa. La 297 avisa cuando una posición atraviesa un factor de Yahoo que no es un split, pero no la ajusta, porque *«el sentido del factor no es confiable»* (HON 2025 = `1,061`, HON 2026 = `0,9535`) y el `2,793` de AVB es un dato podrido.

**Veredicto: NO PASA.** Ninguna regla basada en el factor de Yahoo cumple el kill-criteria: la magnitud de HON 2026 queda a 1,9–3,2 pp de la medida independiente, y el factor solo no separa el `2,793` podrido de AVB del `2,39` real de DuPont/Qnity. Queda el aviso de la 297.

**Pero la premisa de la 297 era falsa y se corrigió:** el sentido del factor es correcto en los siete casos. HON 2026 fue un spin-off **más un reverse split 1:2** el mismo día, y su factor menor que 1 es el correcto.

## Kill-criteria (pre-registrado en la tarea 298, antes de medir)

Una regla de ajuste entra sólo si explica el **sentido** en todos los casos del barrido y la magnitud dentro de **1 pp**, y deja afuera el `2,793` de AVB. Si no, queda el aviso de la 297 más el ajuste a mano, y se documenta.

## Instrumento

**Qué es el factor de Yahoo.** Por cada acción vieja, el tenedor queda con `q` acciones nuevas de la matriz y `r` de la escindida. Yahoo divide los precios previos por:

```
f = q + r · P_escindida / P_matriz
```

con `q = 1` en un spin-off puro y `q = 0,5` si el mismo día hay un reverse split 1:2. Un split puro es `f = q`.

**La medida independiente:**
- `q` y `r` salen de los 8-K y comunicados de las empresas (fuentes abajo), no de Yahoo;
- los precios son los del **ex-date o después**, que el ajuste de ese evento no toca, con apertura y cierre;
- la diferencia entre apertura y cierre estima el ruido del instrumento: el movimiento relativo matriz/escindida del primer día, que puede ser de varios puntos.

**Error del instrumento, corregido antes de creerle:** la primera pasada dio DD 2025 = 1,47 contra 2,39 de Yahoo. El precio de DD del 2025-11-03 venía ajustado por el reverse 1:3 **posterior** (2026-06-24), o sea ×3. Deshaciendo los splits posteriores al ex-date da **2,398**. Un precio de Yahoo de cualquier fecha está ajustado por todos los splits que vinieron después.

**Para HON 2026 y AVB hay un instrumento mejor:** la cinta intradía archivada (`data/price_tape/`), que son los precios crudos que vio el motor, sin ningún ajuste de Yahoo. Es lo mismo que usaría una regla de confirmación en producción. El primer dato del 06-29 de HON es anterior a la apertura (12:59 UTC = 2 × 232,21, el reverse split solo), así que se toma el primero en sesión.

## Resultado

| caso | evento (fuente no-Yahoo) | `q`, `r` | Yahoo | independiente (apertura / cierre) | diferencia en `1−1/f` |
|---|---|---|---|---|---|
| HON 2025-10-30 | Solstice (SOLS), 1 por 4 | 1, 0,25 | 1,0610 | 1,0602 / 1,0609 | +0,07 / +0,01 pp |
| **HON 2026-06-29** | Honeywell Aerospace (HONA), 1 por 2, **+ reverse 1:2** | 0,5, 0,5 | **0,9535** | 0,9779 / 0,9833; cinta 0,937 | **−2,61 / −3,18 pp; cinta +1,85 pp** |
| GE 2024-04-02 | GE Vernova (GEV), 1 por 4 | 1, 0,25 | 1,2530 | 1,2541 / 1,2565 | −0,07 / −0,22 pp |
| MMM 2024-04-01 | Solventum (SOLV), 1 por 4 | 1, 0,25 | 1,1960 | 1,1899 / 1,1837 | +0,43 / +0,87 pp |
| DHR 2023-10-02 | Veralto (VLTO), 1 por 3 | 1, 1/3 | 1,1280 | 1,1167 / 1,1213 (escindida del 10-04) | +0,90 / +0,53 pp |
| DD 2025-11-03 | Qnity (Q), 1 por 2 | 1, 0,5 | 2,3900 | 2,4544 / 2,3981 | −1,10 / −0,14 pp |
| LH 2023-07-03 | Fortrea (FTRE), 1 por 1 | 1, 1 | 1,1640 | 1,1640 / 1,1763 | +0,00 / −0,90 pp |
| AVB 2026-08-17 | **ninguno** (dato podrido) | 1, 0 | **2,793** | cinta: 184,49 → 184,06, **f = 1,0023** | +63,96 pp |
| DD 2026-06-24 | reverse split 1:3 | 1/3, 0 | 0,3333 | — | lo ajusta la 262 (fracción simple) |

### Cómo se lee

- **Sentido: correcto en los 7 spin-offs.** HON 2026 es menor que 1 en la medida independiente también (0,94–0,98), por el reverse split. *«El sentido no es confiable»* (la 297) era la lectura de un factor **compuesto** como si fuera un spin-off puro.
- **Magnitud: dentro de 1 pp en 6 de 7** (en al menos una de las dos medidas). **HON 2026 no entra con ningún instrumento** (1,85 a 3,18 pp). HON cayó un 8% en la sesión del 06-29 (247,8 → 227,8), y no hay precios *when-issued* para fijar el factor a la hora del cierre previo: no se puede separar si el error es de Yahoo o del primer día. El criterio pide 1 pp en **todos**, así que no entra.
- **AVB: el factor solo no lo deja afuera.** El `2,39` de DuPont/Qnity es real (el 58% del valor distribuido) y está en la misma zona que el `2,793` podrido de AVB. Lo que sí lo deja afuera es el **salto observado** por el motor: la cinta da 1,0023 contra 2,793, a 64 pp. Una regla de ajuste necesitaría esa confirmación, y aun así fallaría por HON 2026.

## Lo que se corrigió adentro de esta tarea

Lo que el código afirmaba era falso, y el aviso le decía a Chapa qué mirar al revés:

- **`paper_trading/splits.py`** (docstring) y **`paper_trading/engine.py`** (comentario): ya no dicen *«el signo del factor no es confiable»*. Dicen la forma del factor, el caso compuesto de HON 2026 y por qué no se ajusta.
- **El texto del aviso** (`_texto_factor_sin_tratar`) decía sólo *«la caída del ex-date puede figurar como pérdida»*. En un evento compuesto pasa lo contrario: una posición de HON sin ajustar el 06-29 habría quedado con el **doble de acciones** de las reales, a un precio un 4,9% más alto, o sea con una **ganancia fantasma**, y una venta posterior habría vendido acciones que no existen. Ahora el aviso nombra las dos posibilidades, la cantidad de acciones, y contra qué revisarlo (el comunicado de la empresa). Hay un test que lo fija.
- El docstring de `tests/test_spinoff_aviso_t297.py`, por el mismo motivo.

## Lo que queda: el «ajuste a mano» no tiene mecanismo → tarea 303

El kill-criteria manda, si no pasa, a *«el aviso de la 297 y el ajuste a mano»*. **No existe un ajuste a mano:** ningún script ni pantalla permite cambiar acciones, costo y HWM de una posición paper. La única forma sería editar `finanzias.db` directamente, que es riesgoso con la app abierta, y el cuadre de la 266 lo marcaría como descuadre salvo que se escriba en `paper_split_adjustments`. → tarea **303**.

**Hoy es latente:** ninguna posición abierta de la cuenta 2 atravesó un factor no plausible (las 10 son posteriores a sus últimos eventos), y en los 70 tickers que operaron las dos cuentas el único evento desde marzo fue el de HON 2026, que la cuenta compró **el mismo** 06-29 (no lo atravesó).

## Fuentes (no-Yahoo)

- HON 2026: [8-K, comunicado del 2026-06-29](https://www.sec.gov/Archives/edgar/data/0000773840/000077384026000084/exhibit991-pressrelease629.htm) (1 HONA por cada 2; reverse split 1:2 de Honeywell Technologies).
- HON 2025: [8-K de Solstice](https://www.sec.gov/Archives/edgar/data/2064953/000162828025045287/exhibit991-8xk.htm) (1 por cada 4).
- GE 2024: [8-K de GE Vernova](https://www.sec.gov/Archives/edgar/data/1996810/000119312524063739/d808872dex991.htm) (1 por cada 4).
- MMM 2024: [3M, *Completes Spin-off of Solventum*](https://news.3m.com/2024-04-01-3M-Completes-Spin-off-of-Solventum) (1 por cada 4).
- DHR 2023: [8-K de Veralto](https://www.sec.gov/Archives/edgar/data/1967680/000196768023000005/exhibit991-informationstat.htm) (1 por cada 3).
- DD 2025: [DuPont, *Completes Separation of Qnity*](https://www.dupont.com/news/dupont-completes-separation-of-qnity-electronics.html) (1 por cada 2); y el reverse 1:3 del 2026-06-24.
- LH 2023: [8-K de Labcorp](https://www.sec.gov/Archives/edgar/data/920148/000092014823000050/formpr7323ex991fortreaclos.htm) (1 por 1).
- Los precios del ex-date y posteriores son de Yahoo (series de cada ticker, con los splits posteriores deshechos), y los de HON y AVB, de la cinta del motor.
