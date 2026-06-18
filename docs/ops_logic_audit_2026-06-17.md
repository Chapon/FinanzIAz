# Auditoría de lógica de compras/ventas — 2026-06-17

Universo analizado: las **79 órdenes filled** de la cuenta *Sim Principal* (id=1), emparejadas
en **37 round-trips** por FIFO (neto de comisión + slippage). Forward returns calculados sobre
`historical_data_cache` (1d). Capital inicial $50.000; cash actual ~$6.332; 5 posiciones abiertas
(ASML, PEP, ROST, SBUX, TJX).

## Resumen ejecutivo

El sistema es **levemente positivo en plata real** (+$1.078 realizado, profit factor 1.16, win
rate 51%), pero ese número está **enmascarado por un solo nombre tóxico**: sin MLTX el realizado
sería **+$3.720**. La calidad de las *entradas* es mediocre (el score de compra no predice el
retorno de corto plazo) y el mayor daño concreto viene de los **stops ATR**, que como categoría
pierden plata y ejecutan sistemáticamente por debajo del nivel teórico.

## Hallazgos de lógica (ordenados por impacto)

### 1. Concentración de pérdidas en MLTX — calidad de universo + sizing
MLTX solo perdió **-$2.642** (dos round-trips). Es el microcap conocido (-89.9%, ver data audit
2026-05-26). El engine compró 540 y luego 1.457 acciones de un nombre ilíquido en derrumbe.
**Sin MLTX el realizado pasa de +$1.078 a +$3.720.** El `paper_adv_cap_pct` está en **0.0 (OFF)**,
así que el cap de liquidez que habría limitado esa posición no actúa. → Activar ADV cap y/o un
filtro de calidad mínima del universo.

### 2. Los stops ATR son el peor tipo de salida y ejecutan por debajo del nivel
Por tipo de salida (P/L total realizado):

| Tipo de salida | n | P/L total | P/L promedio |
|---|---|---|---|
| `signal_sell` | 31 | **+$3.218** | +$104 |
| `atr_trail` | 3 | -$290 | -$97 |
| `atr_stop` | 3 | **-$1.850** | **-$617** |

Los 3 `atr_stop` ejecutaron **0.5%–2% por DEBAJO** del stop teórico: WMT stop@124.46 → fill 121.99
(-2%), KO 80.78 → 80.24, MO 69.92 → 69.56. Causa raíz: el stop se evalúa sobre el **cierre diario
en el scan**, no es una orden stop real en mercado, así que se vuelve un *market-on-next-scan* que
regala el gap. → Evaluar stop intradía, o asumir el slippage del gap en el backtest, o subir
`atr_stop_mult` (hoy 2.0) para nombres de baja volatilidad donde 2×ATR es un % chico.

### 3. Las salidas ATR bypassean el min-holding → round-trips de 0-1 día con pérdida
Por diseño, los exits de riesgo saltan el Gate 2 (min holding). Combinado con timing de entrada
flojo produce trades como **WMT: entrada 131.12 (05-20), stop 121.99 (05-21) = -7.1% en 1 día**.
Correcto como guardrail, pero subraya que el problema está aguas arriba, en la *entrada*.

### 4. El score de compra no tiene poder predictivo de corto plazo
**corr(buy_score, fwd5) ≈ 0.00** (n=21). El `signal_score` que además **pondera el sizing**
(`allocation_mode = signal_weighted`) no se relaciona con el retorno a 5 días hábiles. Estás
asignando más capital según una señal que, en esta muestra, no anticipa el movimiento próximo.
→ Revisar la calibración del score de entrada o desacoplar sizing de score hasta validarlo.

### 5. SELLs de señal aún sesgados al pesimismo
En el **57%** de los signal-SELL el precio **siguió subiendo** después de vender (mean fwd5
**+3.92%**). Confirma la auditoría 2026-06-09. En P/L los signal-sells son los que ganan, pero
dejan upside sobre la mesa. La hysteresis (T6.4, espera 3 días hábiles salvo score < 0.25) mitiga
parcialmente; el exit-veto T-CAT-6 sigue OFF por razón medida.

### 6. Churn: vender y recomprar el mismo nombre en ≤7 días
7 re-compras dentro de 7 días de un SELL, varias con **gap de 0 días** (WMT SELL#41→BUY#44, KO
SELL#57→BUY#61): el modelo dice SELL (score ~0.34) y horas después dice BUY del mismo ticker.
La mayoría son de mayo, **previas** al Gate 5b anti-churn (shipped 2026-06-10, 3 ciclos/10d).
→ Verificar que `paper_churn_max_cycles`/`lookback` estén activos en `settings.json` de producción.

### 7. 12 BUYs expiraron sin llenarse
AAPL ×2, TJX ×2, AMD, GM, KO, META, MU, NVDA, PM, WMT. Órdenes que expiraron sin fill (cuenta en
modo `manual`). → Revisar el flujo de aprobación/pricing del límite: o son aprobaciones que no se
hicieron a tiempo, o el límite quedó fuera de mercado.

## Lo que está bien
Los winners son consistentes y de buen tamaño (MU +$1.715, TJX +$1.418, TSLA +$1.368, AAPL
+$1.179, NVDA +$763). La infraestructura de guardrails (hysteresis, anti-churn, ADV cap, exit-veto)
ya existe; varios están **desactivados o recién shipeados**, así que la oportunidad inmediata es de
*configuración* más que de código nuevo.

## Recomendaciones priorizadas
1. **Activar ADV cap** (`paper_adv_cap_pct` > 0) y/o filtro de calidad — ataca el riesgo tipo MLTX.
2. **Recalibrar los stops ATR**: modelar slippage del gap y/o subir `atr_stop_mult` en baja-vol.
3. **Validar/desacoplar el buy_score del sizing** hasta confirmar poder predictivo.
4. **Confirmar anti-churn ON** en el `settings.json` de producción.
5. **Revisar el flujo de BUYs expired** (aprobación manual / pricing del límite).
