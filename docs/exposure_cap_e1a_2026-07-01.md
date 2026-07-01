# E1a — Cap duro de exposición por nombre · replay + kill-criteria

_2026-07-01. Tarea E1 (anti-MLTX), primera capa. Backup usado:
`backups/finanzias_2026-07-01_00-59-13_daily.db` (Sim Principal, id=1), read-only._

## Motivación (medición previa)

El P/L realizado total es **+$278**; **sin MLTX es +$2.920**. MLTX (biotech
clínico, −89.9%) aportó **−$2.554** realizados. La hipótesis a validar: un cap
duro de exposición por nombre (% del book al comprar) habría desconcentrado a
MLTX y reducido esa pérdida.

**Hallazgo clave (reconstrucción cronológica del book, `%book` = notional de la
compra ÷ book marcado a mercado en el momento de comprar):** el sizing NO es
uniforme. Las compras tempranas (mucho cash + pocos picks → `available/n_picks`)
se llevaron 33–49% del book:

| ticker | max %book | P/L realizado |
|--------|-----------|---------------|
| MLTX   | **49.1%** | **−$2.554**   |
| MU     | 46.6%     | +$1.741       |
| KO     | 37.7%     | −$1.047       |
| META   | 33.3%     | +$235         |
| AAPL   | 33.3%     | +$1.230       |
| NVDA   | 33.3%     | +$827         |
| TJX    | 31.7%     | +$966         |
| …      | …         | …             |
| TSLA   | 16.2%     | +$1.396       |

Mediana de `%book` de las 47 compras: **15.8%**. MLTX fue **la posición más
concentrada de toda la historia** — exactamente lo que un cap por nombre ataca.
Pero MU/AAPL/META/NVDA/TJX (varios ganadores) también estaban sobre-cap, así que
el cap recorta captura de winners: el veredicto depende del nivel de cap.

## Contrafactual (explícito — el veredicto es sensible a esto)

- **Modelo:** el P/L de un round-trip escala **linealmente** con el notional de
  la compra (mismos precios de entrada/salida, menos acciones). Si la compra i
  supera el cap, su P/L realizado se multiplica por
  `s_i = min(1, cap_pct · book_at_buy_i / notional_i)`.
- **Cash liberado:** queda **ocioso** (no se redistribuye a otros nombres ni a
  scans futuros). Es la elección **conservadora**: no le acredita al cap ninguna
  ganancia hipotética por redeploy; solo cuenta la pérdida evitada en los
  perdedores sobre-cap y la ganancia resignada en los ganadores sobre-cap.
- **Book at buy:** reconstruido procesando las órdenes `filled` en orden
  cronológico, marcando a mercado con el último `fill_price` conocido de cada
  ticker. Solo P/L **realizado** (round-trips cerrados por FIFO); las porciones
  abiertas no tienen P/L realizado.
- **Grid de cap:** 20% / 25% / 33% (rango razonable "ningún nombre > X del book").

## Kill-criteria (PRE-REGISTRADO, antes de correr el replay del cap)

Se **shipea** E1a a un nivel de cap solo si, en ese nivel:

1. **No destruye valor:** ΔP/L realizado total ≥ **+1.0 pt** de capital inicial
   (≥ **+$500** sobre $50k).
2. **Reduce el peor nombre:** la pérdida realizada del peor nombre (MLTX) se
   reduce ≥ **30%**.
3. **No recorta materialmente los ganadores grandes:** la captura agregada de
   MU/TSLA/AAPL/TJX se retiene ≥ **75%** (P/L capado de los 4 ≥ 0.75× el actual).
4. **Robustez:** el signo del ΔP/L total se mantiene favorable en al menos 2 de
   los 3 niveles del grid (no un punto suelto y afortunado).
5. Suite Windows verde.

Si ningún nivel cumple 1–4 → **NO-SHIP**, se documenta y queda como guardrail
estructural OFF-by-default (a re-evaluar con E4 / muestra de stress).

## Resultados

Harness: `scripts/run_exposure_cap_replay.py` (determinístico, read-only).
Base (P/L realizado **bruto**, sin costos): **+$906**. MLTX **−$2.554**;
big-4 (MU+TSLA+AAPL+TJX) **+$5.334**. (El bruto difiere del +$278 neto del panel
por comisión/slippage; el veredicto usa el **Δ** cap-vs-sin-cap, donde los costos
se cancelan.)

| cap | ΔP/L total | worst_reduction (MLTX) | big-4 retenido |
|-----|-----------:|-----------------------:|---------------:|
| 20% | **−$428**  | 59%                    | 62%            |
| 25% | **−$118**  | 49%                    | 73%            |
| 30% | +$224      | 39%                    | 85%            |
| 33% | **+$371** (pico) | 33%              | 90%            |
| 35% | +$321      | 29%                    | 92%            |
| 40% | +$224      | 18%                    | 95%            |
| 45% | +$151      | 8%                     | 99%            |
| 48% | +$57       | 2%                     | 100%           |

Control sobre `backups/finanzias_2026-06-29_09-57-54_daily.db`: patrón idéntico
(20% Δ−$429, 25% Δ−$119, 33% Δ+$370) → el hallazgo es robusto entre backups.

## Veredicto: **NO-SHIP**

Ningún nivel de cap cumple el kill-criteria:

- **Criterio 1 (ΔP/L ≥ +$500):** el máximo alcanzable es **+$371** (a cap 33%),
  por debajo del umbral. Los caps protectores (20–25%) son **negativos**.
- **Criterio 4 (signo favorable en ≥2 de 3 niveles del grid 20/25/33):** 20% y
  25% son negativos → **falla**.
- Criterios 2 y 3 solo se cumplen a la vez en la zona 33–35%, donde el cap
  protege poco (worst_reduction 29–33%) y el ΔP/L es marginal.

**Causa raíz del NO-SHIP:** la sobre-concentración **no fue exclusiva del
perdedor**. MU (+$1.741, comprado a 46.6% del book) y AAPL (+$1.230 a 33.3%)
estaban tan sobre-cap como MLTX (49.1%). Un cap **ciego de tamaño** no distingue
ganador de perdedor: para proteger contra MLTX, recorta la captura de MU/AAPL en
la misma medida. El contrafactual conservador (cash liberado ocioso) no le
acredita ningún redeploy; incluso siendo generosos, la separación
ganador/perdedor no existe a nivel de *tamaño*.

## Implicancias / próximos pasos

1. **No se cablea el cap al sizing** (CLAUDE.md regla 3: nada a sizing sin pasar
   el backtest). El harness + doc + test quedan como evidencia (patrón A1).
2. **La defensa correcta es de universo, no de tamaño** → **E1b** (screen por
   ADV$ + calidad fundamental vía EDGAR XBRL): excluir estructuralmente los
   nombres tipo MLTX (biotech clínico con ingresos negativos sostenidos) **antes**
   de que entren, en vez de recortarlos después. Es la capa con valor real.
3. **Caveat de survivorship:** la watchlist son 52/52 vivos, así que la muestra
   subestima cuántos MLTX habría en producción. Si Chapa quiere la protección
   estructural igual (a pesar del ΔP/L neutro-a-negativo histórico), se puede
   agregar el cap como flag **OFF-by-default** `paper_name_exposure_cap_pct`
   (default 0.0), a re-evaluar con la muestra de stress de **E4**. Decisión de
   Chapa — no se shipea encendido por la regla de "sin features especulativas".

