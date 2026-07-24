# ¿El take-profit ATR (`atr_tp_mult=4.0`) está bien calibrado?

_Análisis 2026-07-22 (pedido de Chapa). Disparador: XOM salió por `atr_tp` en la
cuenta 2 mientras el panel de Analysis marcaba "Compra Fuerte". Research/display
only — no toca engine ni DB. Harness: `scripts/tp_mult_sweep_2026-07-22.py`._

---

## TL;DR

El take-profit fijo en **4×ATR (R:R 2:1)** está **subcalibrado**: **corta la cola
derecha de las posiciones ganadoras sin ninguna contrapartida de riesgo.** Porque
el TP solo actúa sobre la punta de arriba (stop y trailing gobiernan la de abajo),
aflojarlo o quitarlo **no empeora el drawdown ni la cola de pérdidas** — solo deja
correr a los ganadores. El barrido sobre 4560 entradas 10y da una mejora
**monótona, DD-neutral y robusta por régimen**: pasar de 4.0 a 6.0 vale
**+0.165 pts por trade [IC95% +0.10, +0.23]**, y quitarlo del todo un poco más.

**Recomendación:** subir `atr_tp_mult` a **~6.0** (o desactivar el TP y dejar que
manden trailing + stop), **pero validándolo con el harness pre-registrado de la
Tarea 7 antes de cablearlo** (reglas 2 y 3 de `CLAUDE.md`). No es un cambio para
shipear a ojo.

---

## 1. Qué pasó con XOM (el disparador)

La orden real (`paper_orders` id 165, cuenta 2 "Sim Segundo", auto):

```
SELL XOM · atr_tp @ 154.30 ≥ 153.48 (entry 140.18 + 4.0×ATR 3.33) | fill≈153.86
```

No fue un SELL de señal: fue **toma de ganancia por nivel**. Compró a 140.18, el TP
quedó en 140.18 + 4×3.33 = 153.48, el precio lo cruzó y cerró. El badge "Compra
Fuerte" del panel Analysis es **display técnico** (agregación RSI/MACD/BB/SMA, sin
efecto sobre trades). Son dos sistemas distintos: el panel dice "el momentum sigue
fuerte", el engine dice "llegaste a tu objetivo, embolsá". La contradicción es
aparente.

> **Corrección a una creencia previa:** el `signal_score=1.0` de estas órdenes NO
> significa que la señal siguiera alcista al vender. Es un **centinela hardcodeado**
> que el gate ATR estampa a todo forced-exit (`engine.py:403`, "max conviction")
> para que bypasee los gates de score río abajo.

## 2. La mecánica (y por qué A4 estaba medio equivocado)

Niveles (`gates.atr_exit_decision`), orden de evaluación **stop → trail → TP**,
gana el primero:

| nivel | fórmula | mult actual | qué punta toca |
|---|---|---|---|
| hard stop | `entry − stop_mult×ATR` | 2.0 | abajo |
| trailing | `HWM − stop_mult×ATR` (activo si HWM > entry+1×ATR) | 2.0 | abajo |
| take-profit | `entry + tp_mult×ATR` | **4.0** | **arriba** |

El R:R implícito es `tp_mult/stop_mult = 4.0/2.0 = **2:1**`.

El hallazgo A4 (`deep_gap_analysis_2026-07-06`) decía *"el atr_tp jamás ejecuta,
la señal preempta al nivel"*. Medido hoy, eso es **solo cierto para la cuenta 1
(manual, 0 `atr_tp`)**. En la **cuenta 2 (auto)** el `atr_tp` disparó **6 veces**
(JNJ, WELL, SPG, O, PSX, XOM entre el 26/06 y el 22/07). Y la dirección de la
jerarquía está **al revés** de lo que sugería A4: el engine calcula los exits ATR
**antes** que la estrategia y descarta el SELL de señal cuando el nivel dispara en
el mismo scan (`engine.py:638-644`). **Dentro de un scan, el nivel preempta a la
señal.** Entre scans distintos la señal sí puede cerrar antes de que el precio
alcance el TP — por eso la cuenta manual, más pesimista y con SELLs de señal
efectivos, nunca llega al TP.

## 3. Cómo lo hacen los sistemas profesionales

La respuesta depende del **signo de la asimetría (skew) de la estrategia**:

- **Momentum / trend-following (skew positivo):** el P&L lo hacen unos pocos
  ganadores enormes. La regla canónica es *"cut losses short, let winners run"*.
  Los CTAs y trend-followers sistemáticos **no usan take-profit fijo**: usan
  **trailing stops de volatilidad** (Chandelier Exit de LeBeau, ATR-trailing),
  time stops y scale-out. Un TP fijo hace exactamente lo contrario de "dejar
  correr": convierte a los outliers raros en trades promedio y **aplasta el skew
  positivo** del que vive la estrategia. La evidencia pública lo respalda: los
  trailing stops rinden más que los targets fijos en mercados con Hurst > ~0.55
  (tendenciales) y suben el skew; en régimen mean-reverting son de expectancy
  negativa.
- **Mean-reversion (skew negativo):** muchas ganancias chicas, pocas pérdidas
  grandes. Ahí el **TP fijo sí tiene sentido**: el edge es el rebote, no hay cola
  derecha que capturar, y esperar de más devuelve la ganancia.

`analyze_single` de FinanzIAs es **momentum-ish** (XGBoost de suba a 5 días, cruce
SMA, MACD) y su distribución es de **skew positivo** medido: Tarea 7 mostró que el
**69% de la ganancia bruta viene de 4 trades que corrieron 12–27 días**. Un TP fijo
en 2R está peleado con la naturaleza del edge — corta justo a los pocos que pagan.

## 4. El experimento (lo que Tarea 7 NO barrió)

Tarea 7 barrió `sell_fraction` (1.0→0.0) y `trail_mult` (2.0/2.5/3.0) pero **dejó
el TP fijo en 4.0 en todos los brazos**. Así que el múltiplo del TP nunca se testeó
de forma aislada. Este es ese barrido.

**Diseño** (`scripts/tp_mult_sweep_2026-07-22.py`):
- **Población:** 4560 entradas neutras (cada 20 barras, warmup 250) sobre el grid
  **41×10y en parquet** — misma fuente que E4/Tarea 7. Entrada incondicional
  (aísla el efecto de la **política de salida**, no del `buy_score` — que no tiene
  alpha medido, ref A3).
- **Salidas:** solo niveles ATR (mundo C_A4, la señal no preempta), maquinaria pura
  reusada de `analysis/exit_replay.py` (`atr_series`, `atr_exit`, fills gap/touch).
- **Fijo:** stop 2.0, trail 2.0, cap 20d, comisión 0.1% + slippage 0.05% dos puntas.
- **Barrido:** `tp_mult ∈ {3, 4, 5, 6, 8, sin-TP}`.

### 4.1 Resultado — monótono, DD-neutral

| tp_mult | mean % | mediana % | win % | payoff | días | **ret/día (bp)** | maxDD % | p5 % | %salida TP |
|---|---|---|---|---|---|---|---|---|---|
| 3.0 | 0.83 | −0.02 | 49.7 | 1.42 | 11.7 | 7.10 | 24.9 | −7.28 | 31.1 |
| **4.0 (actual)** | 1.12 | −0.04 | 49.7 | 1.57 | 12.9 | 8.69 | 24.4 | −7.28 | 20.0 |
| 5.0 | 1.22 | −0.05 | 49.6 | 1.62 | 13.5 | 9.00 | 24.8 | −7.28 | 10.9 |
| 6.0 | 1.28 | −0.05 | 49.5 | 1.66 | 13.8 | 9.28 | 24.3 | −7.28 | 5.3 |
| 8.0 | 1.35 | −0.05 | 49.5 | 1.69 | 14.0 | 9.61 | 24.4 | −7.28 | 0.9 |
| sin-TP | 1.35 | −0.05 | 49.5 | 1.69 | 14.1 | 9.61 | 24.4 | −7.28 | 0.0 |

**Lecturas clave:**
1. **La cola de pérdidas es idéntica** en todos los brazos: p5 = −7.28% y maxDD ≈
   24.4% no se mueven. Lógico: el TP no toca el downside. Aflojarlo es **gratis en
   riesgo**.
2. **El retorno medio sube monótono** con el TP (0.83 → 1.35%), y el **payoff**
   también (1.42 → 1.69). La mediana es plana y ~0: el TP solo mueve la cola
   derecha, no al trade típico.
3. **Sobrevive el ajuste por slot.** Este es el test que mató a C_A4 en Tarea 7
   (§8.3): retener más tiempo ocupa un slot de `max_positions=5`. Pero acá el
   **ret/día también mejora** (8.7 → 9.6 bp): el tiempo extra captura drift
   positivo, no capital muerto. A diferencia de deferir un SELL de señal, dejar
   correr a un ganador es eficiente por unidad de slot-tiempo.
4. **Saturación:** 8.0 ≈ sin-TP (a 8×ATR casi nada llega al TP dentro del cap de
   20d). El grueso de la mejora está entre 4.0 y 6.0.

### 4.2 Robustez

- **Paired 6.0 − 4.0 = +0.165 pts, IC95% [+0.103, +0.229]** (bootstrap 2000,
  n=4560). No cruza cero. 80% de los trades no cambian (salen por stop/trail/cap
  igual); de los que cambian, 11.8% mejoran vs 8.2% empeoran → **neto positivo**
  aun contando los que devuelven ganancia.
- **Por régimen** (lo que hundió al trailing sweep de Tarea 7): subir el TP es
  **positivo o neutro en los 4 regímenes** — no hay el signo negativo en stress que
  descalifica. Bull_normal 1.23→1.41, 2018Q4 −3.21→−2.98 (menos malo), COVID
  9.2→9.6, bear-2022 plano (−0.37→−0.38).
- **No depende de un ticker:** el efecto se concentra en nombres de alta vol
  (TSLA +1.40, AMD +0.61, BA +0.56, NVDA +0.55, LLY +0.40) pero **sobrevive sin
  ellos**: excluyendo TSLA/NVDA/AMD, mean ret sube igual 0.97% → 1.08% (6.0) →
  1.12% (sin-TP). Unos pocos mean-reverters pierden algo (NOW −0.26, GS −0.16),
  chico y compensado.

### 4.3 Por qué esto NO contradice a Tarea 7

Tarea 7 concluyó NO-SHIP para aflojar el **trailing** (2.5/3.0×ATR: negativo en
stress). Coherente: el trailing es **downside** — aflojarlo devuelve más en cada
reversa, y castiga en régimen choppy. El **TP es upside** — aflojarlo no toca la
cola de pérdidas. Son ejes opuestos. Y el hallazgo central de Tarea 7 (*"el SELL de
señal destruye valor; dejar correr al ganador es donde está el alpha"*) **apunta en
la misma dirección** que subir el TP. Todo es la misma historia de skew positivo.

## 5. Limitaciones (declaradas)

- Entradas **incondicionales**, no `analyze BUY`: aísla la política de salida pero
  no predice el P/L de la cuenta viva (población más ancha y neutra — deliberado).
- `auto_adjust=True` (lookahead) y **survivorship** (41 tickers vivos): sesgan el
  **nivel**, no el **ranking** entre brazos (aplican igual a todos). Ver
  `data_audit_2026-05-26`.
- **Sin intradía:** stops/TP al close con fills gap/touch modelados. Misma
  limitación estructural que A1.
- **No es un pre-registro con DSR/PBO/CPCV** como Tarea 7. Es un barrido
  exploratorio de una variable no testeada. Suficiente para *decidir que vale la
  pena testear en serio*, no para cablear.

## 6. Conclusión y próximo paso

El `atr_tp_mult=4.0` **merece ajustarse**: es un techo que corta ganadores sin
comprar nada de protección. La dirección (subir a ~6.0 o quitar el TP) es robusta,
DD-neutral, régimen-consistente y teóricamente correcta para una estrategia de skew
positivo. La magnitud (+0.16 pts/trade) es chica pero **es dinero gratis** — no hay
trade-off de riesgo que la compre.

**Pero no se shipea a ojo** (regla 3: display antes que sizing; regla 2:
kill-criteria upfront). El paso correcto es una **nueva tarea de backlog**
pre-registrada, reusando el harness PIT de Tarea 7 (señal `analyze()` completa) con
entradas del engine real y `max_positions=5` modelado:

- **Brazos:** `tp_mult ∈ {4.0 (baseline), 6.0, sin-TP}`, TODO lo demás igual.
- **Kill-criteria** (en CAGR/Sharpe **ajustado por slot**, no puntos acumulados —
  lección de la memoria R2): ship si ΔCAGR ≥ umbral **sin** empeorar maxDD ni el
  p5, y **sin** depender de un solo régimen.
- Lo que pase entra **detrás de flag, default = valor validado**.

Mientras tanto, cero cambios al engine. Este informe y el script quedan como
insumo de esa tarea.
