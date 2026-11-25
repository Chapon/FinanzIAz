# Compra, venta y rendimiento: revisión profunda — 2026-11-24

Pedido de Chapa: *«revisar profundamente la app y buscar oportunidades de mejora en la compra y venta
y en los rendimientos»*. Parte de lo ya escrito (`docs/compras_ventas_efectividad_2026-11-23.md`,
`docs/rendimiento_app_vs_cartera_2026-10-20.md`) y no repite las ~30 perillas que ya se probaron.

## En una línea

**El harness cobra 2,4 veces el costo que paga la cuenta viva**, y con el costo real cambian los
números de casi todo lo que se concluyó: la estrategia rinde ~5 pp por año más de lo que decían los
harness, la ventaja del pasivo de la 456 baja de +6,49 a +1,66 pp, y el escalado por régimen deja de
estar dominado por la caja. La oportunidad más grande no es una perilla nueva: es **medir con el costo
correcto** antes de decidir nada más.

## 1. El hallazgo: el harness cobra 0,15% por lado y el vivo ~0,063%

- **El harness:** `CostModel()` (`analysis/scaleout_replay.py`) cobra 0,10% de comisión + 0,05% de
  slippage por lado. Su docstring dice *«espejo de la cuenta viva»*, y la auditoría del 2026-09-02
  (`docs/auditoria_desvios_2026-09-02.md` §5, P1) lo dio por *«coinciden exacto»*.
- **El vivo:** la cuenta 2 tiene `commission = 0.001`, pero ese valor es el modelo *legacy*. Desde el
  2026-05-18 (`e2d7e93`), el motor cobra con `get_active_commission_model()`, que por default es
  **IBKR Pro Tiered**, por acción y con mínimo. En `paper_orders`, lo pagado de verdad es **0,0118% en
  las compras y 0,0145% en las ventas** (la venta suma tasas regulatorias), más el 0,05% de slippage
  modelado: **~0,063% por lado**. Es lo mismo que midió y usó la 385 (0,064%).
- **Por qué pesa tanto:** la estrategia rota. El ancla de la T170 hace 2.531 operaciones en nueve
  años, y la cuenta viva compró por **26,5 veces su capital por año** (la rotación del harness es la
  real). Con 0,30% por ida y vuelta, cada año se va una parte grande del retorno en costos.

**Los mismos brazos con tres costos** (cohorte y config de la 456, tajada por día de la 464, muestra
completa 2017-09-08 → 2026-09-09, descriptivo):

| | costo cero | **costo del vivo (0,063%)** | costo del harness (0,15%) |
|---|--:|--:|--:|
| estrategia sin régimen | 18,45% / 1,01 / 30,3% | **13,72% / 0,79 / 29,5%** | 8,78% / 0,55 / 28,4% |
| estrategia con régimen ×0,25 (la cuenta 2) | 16,38% / 1,06 / 21,1% | **11,35% / 0,77 / 21,4%** | 6,41% / 0,47 / 25,5% |
| SPY + caja, `w` por la regla de la 456 | 9,25% / 0,86 / 20,9% | **8,49% / 0,86 / 19,2%** | 8,47% / 0,86 / 19,2% |

*(CAGR, crecimiento anual compuesto / Sharpe / caída máxima.)* Al costo del harness salen exactos el
ancla de la T170 (8,78% / 0,55, 2.531 operaciones) y el brazo de la 464 (6,41%): el instrumento es el
mismo, sólo cambia el costo.

**Lo que se mueve:**

- **El nivel de la estrategia.** Con el costo real rinde **13,72%** con Sharpe 0,79, contra SPY 15,19%
  y 0,85 en el mismo período. No es «SPY con caja le gana de lejos»: queda cerca de SPY en retorno
  ajustado por riesgo y le gana en CAGR a SPY con caja.
- **El gate de la 456** (pasivo contra activo, fuera de muestra): con el costo del vivo, el pasivo
  rinde **+1,66 pp** por año (7,19% contra 5,52%), en 4 de 5 años, con IC95% **[−6,77, +10,25]**,
  p = 0,31. Sigue **no decidible**, pero el punto estimado baja de +6,49 a +1,66 pp: casi toda la
  ventaja del pasivo era costo sobrecobrado.
- **El escalado por régimen contra la caja fija**, a la misma caída:

  | costo | caja fija | régimen ×0,25 | caja − régimen |
  |---|---|---|--:|
  | cero | 12,37% / 1,02 | 16,38% / 1,06 | −4,01 pp |
  | **vivo** | **9,75% / 0,80** | **11,35% / 0,77** | **−1,60 pp** |
  | harness | 7,92% / 0,55 | 6,41% / 0,47 | +1,52 pp |

  La 464 concluyó que la caja fija compraba la misma caída 1,52 pp más barata. **Con el costo del vivo
  se da vuelta:** el escalado rinde 1,60 pp más que la caja, con un Sharpe apenas menor. También
  cambia su precio: cuesta 2,37 pp de CAGR por **8,1 pp** menos de caída, no por 2,9. La acción manual
  del factor ya está corregida.
- **Todo veredicto que comparó brazos con rotación distinta.** Un costo inflado favorece al brazo que
  opera menos. La 219 (demorar la venta por señal) encontró que *«el 61% es operar menos»*. La 170, la
  T7, la T37 (que eligió la salida viva), la T54 y la T121 compararon brazos con rotaciones distintas
  a 0,15%. Ninguno se re-decide solo por esto (regla 2), pero hay que releerlos con el costo correcto
  → **469**.

## 2. La cuenta viva, operación por operación

Copia de `finanzias.db`, cuenta 2, del 2026-06-20 al 2026-11-23: 124 compras, 114 ventas, equity
49.977 → 49.557 (−0,84%).

| salida | n | realizado (neto de costos) | retorno medio | ganadoras | tenencia mediana |
|---|--:|--:|--:|--:|--:|
| por señal (`analyze SELL`) | 66 | −$7.295,82 | −1,90% | 17/66 | 8,5 días |
| trailing | 22 | −$47,16 | −0,28% | 8/22 | 14,9 días |
| objetivo (TP, *take profit*) | 17 | +$8.117,73 | +11,31% | 17/17 | 17,0 días |
| stop duro | 9 | −$2.138,30 | −5,36% | 0/9 | 13,0 días |

- **Las nueve del stop duro son de antes del 2026-08-27**, cuando se apagó (T37/T53). Desde entonces
  no hubo ninguna, como tenía que ser.
- **La venta por señal pierde, pero eso no dice que venda mal.** Se da vuelta sobre posiciones que ya
  venían perdiendo, y lo vendido sigue cayendo después (octubre: −3,58% contra SPY a 20 ruedas). Es
  selección, no causa (`docs/rendimiento_app_vs_cartera_2026-10-20.md` §3).
- **Por tenencia:** lo vendido entre 3 y 10 días deja −$4.247 (43 ventas, 33 por señal), y lo
  vendido entre 10 y 30 días, +$2.594.
- **Costos:** $697,27 en cinco meses (comisión $145 + slippage $552), contra un realizado de −$1.364.
  Es la mitad de la pérdida realizada, aunque una parte es de compras de posiciones todavía abiertas.
  El slippage es modelado, porque la cuenta es paper.
- **Caja ociosa:** 7,6% de media en toda la vida de la cuenta, 25,9% en noviembre, 60% hoy (risk-off
  desde el 20/11, con régimen y overlay encadenados).

## 3. Dónde están las oportunidades, en orden

| # | qué | qué esperamos | cómo se decide |
|---|---|---|---|
| 1 | **Medir con el costo del vivo** (468) | Ninguna mejora de la cuenta en sí: corrige el instrumento con el que se decide todo lo demás. Es la de más peso, porque cambia el signo de una conclusión de hoy. | gate técnico: el harness reproduce el costo de `paper_orders` |
| 2 | **Releer lo que dependió de la rotación** (469) | Con el costo bajo, operar menos rinde menos que lo medido: lo esperable es que la familia de salidas siga cerrada. La que más importa es la T37, que eligió la política viva. | re-lectura con el pre-registro de cada una, sin re-decidir |
| 3 | **El factor de régimen** (acción manual, 465) | Con el costo corregido, el escalado le gana a la caja fija por 1,60 pp a igual caída. La 465 lo confirma o no fuera de muestra. | decisión de Chapa; la 465 con pre-registro |
| 4 | **El overlay de volatilidad** (457) | Sin medir. Hay que medirlo con el costo del vivo: con el de la 456, el mismo tipo de freno daba lo opuesto. | pre-registro, con el costo del vivo |
| 5 | **El Gate 6, cerca de los balances** (458) | Sin dirección esperada. | pre-registro |
| 6 | **La caja no rinde nada** (470) | En la cuenta paper la caja rinde 0%. En un broker rendiría la tasa corta, y con 26–60% en caja en risk-off la diferencia es material. Es contabilidad, no una señal. | display-only (regla 3) |

**Lo que no cambia:**
- Elegir qué comprar sigue sin ventaja medida. A costo cero la estrategia da 18,45%, contra 17,27% del
  universo en partes iguales (con sesgo de supervivencia). En vivo, las compras no se distinguen del
  universo del mismo día (octubre).
- No se proponen perillas nuevas de ranking ni de salidas: esas familias están cerradas. Lo que la 469
  hace es releerlas, no reabrirlas.

## 4. Límites

- **Todo lo del §1 es descriptivo y sobre la muestra completa**, salvo el gate de la 456. No hay
  intervalo para la tabla del régimen contra la caja, y la `w` de la caja se eligió mirando la caída
  de la muestra entera (lo corrige la 465).
- **El costo «del vivo» es un porcentaje medio.** IBKR Tiered cobra por acción con mínimo, así que el
  porcentaje efectivo depende del precio y del tamaño. Con posiciones de $500 a $6.000 da ~0,013%, y
  con más capital bajaría. El slippage de 0,05% es el modelado, no uno medido en un mercado real.
- **Cinco meses de cuenta viva** alcanzan para describir, no para afirmar una ventaja en ninguna
  dirección.

## Instrumento

- Harness: `scripts/run_activo_pasivo_t456.py` y su maquinaria (`_common_kwargs` de la T219,
  `simulate_portfolio(tajada_del_dia=True)`, `evaluar`, `w_por_regla`, `mezcla_constante`), cohorte
  `10y` de 126 tickers (artefactos al 2026-09-09), SPY `max`. Costos: `CostModel(0, 0)`,
  `CostModel(commission=0.00013, slippage=0.0005)` y `CostModel()`. Caja fija:
  `caja_hasta_la_caida` de `scripts/medir_tajada_t464.py`. Scripts de un solo uso en el scratchpad
  de la sesión; la 468 los convierte en instrumento del repo.
- Cuenta viva: copia de `finanzias.db` (`paper_orders`, `paper_equity_snapshots`, `paper_accounts`
  de la cuenta 2). El realizado por venta usa el costo medio de la posición, con comisión y slippage
  de las compras incluidos.

## Hallazgo → tarea

- **468** — el harness cobra 0,15% por lado y el vivo ~0,063%. **ALTA.**
- **469** — releer los veredictos que compararon brazos con rotación distinta. **MEDIA-ALTA.**
- **470** — la caja de la cuenta paper no rinde interés. **BAJA**, display-only.
- **Corregido acá mismo:** la acción manual del factor de régimen, que decía lo contrario de lo que
  da el costo del vivo.
