# Análisis profundo de la "efectividad" del modelo — 2026-06-30

Disparador: Chapa ve **47.6% de efectividad** en la pestaña Métricas y lo lee como
"realmente malo". Este doc audita qué mide ese número, por qué da lo que da, y
deja trazada la causa raíz de cada problema a `archivo:función`. Las historias
accionables viven en `docs/BACKLOG.md` (E1–E4 + enriquecimientos de las tareas 2 y 3).

Fuente: `analysis.metrics_panel.build_metrics(con, account_id=1)` sobre copia
read-only de `finanzias.db` (cuenta **Sim Principal id=1**). Muestra: **42
round-trips cerrados**.

---

## 0. Qué mide "efectividad" y por qué el titular engaña

En `ui/metrics_tab.py` la KPI card **WIN RATE** muestra `_pct(win_rate)` =
`n_wins / n_round_trips`, y el gráfico se titula "Evolución de la efectividad".
O sea: **efectividad ≡ win-rate** = 20 ganadores / 42 = **47.6%**.

Pero el sistema **no pierde plata**:

| Métrica | Valor |
|---|---|
| P/L realizado | **+$278.01** |
| Profit factor | 1.035 |
| Expectancy / trade | +$6.62 |
| Avg win / Avg loss | +$408.60 / −$358.82 → **payoff ratio 1.14** |
| Win rate | 47.6% (20/42) |
| Avg hold | 6.6 d |
| Costos totales | $718.46 |
| P/L sin el peor nombre (MLTX) | **+$2.920.02** |

Un win-rate < 50% es perfectamente viable **si el payoff es asimétrico**. El
problema no es "47.6% es malo": es que el **payoff ratio es apenas 1.14**, casi
simétrico, así que con un hit-rate de moneda al aire el sistema queda pegado a
cero y **depende de la cola de ganadores**. Presentar el win-rate como veredicto
de "efectividad" induce a una conclusión equivocada (de ahí la historia **E2**:
el titular del panel debería ser expectancy + profit factor + payoff ratio +
P/L-sin-peor-nombre, no el win-rate suelto).

---

## 1. Las salidas ATR son el agujero más grande (después de MLTX)

`realized.by_exit_kind`:

| Tipo | n | P/L total | P/L prom. |
|---|---|---|---|
| `signal_sell` | 35 | **+$2.898.94** | +$82.83 |
| `atr_trail` | 3 | −$289.81 | −$96.60 |
| `atr_stop` | 4 | **−$2.331.12** | **−$582.78** |

Las 7 salidas de riesgo ATR juntas = **−$2.621**. Detalle ciclo a ciclo:

```
WMT  atr_stop   1d  -625.32  (-7.12%)   2026-05-20 -> 2026-05-21
MO   atr_trail 14d  -188.03  (-2.12%)
LRCX atr_trail  8d  -187.28  (-2.25%)
KLAC atr_trail  4d   +85.51  (+2.20%)   ⚠ ciclo con precio corrupto ~10× (ver §5)
MO   atr_stop   4d  -404.07  (-4.94%)
KO   atr_stop   5d  -820.72  (-4.53%)
TJX  atr_stop   7d  -481.00  (-4.96%)
```

Los stops ejecutan a −4.5%…−7.1%; WMT salió en **1 día** a −7.12% (gap). Confirma
la auditoría previa: los stops ATR ejecutan *por debajo* del nivel (gap-open).

**Estado:** ya se trabajó. (a) El fill realista gap/touch se shipeó (`e5c2ff2`) y
el auto-fill de risk-exits en cuenta manual también (`8ff57e1`, ΔP/L +3.95 pts).
(b) La recalibración del multiplicador **A1 cerró NO-SHIP** (`docs/atr_stop_recalib_2026-06-30.md`):
`no_stops` (+5.38 pts) y `mult_3.0` (+4.46 pts) pasan el umbral numérico pero
**no son robustos** — leave-one-out sin LRCX (63% del efecto) los tumba a
+1.99/+1.07. **n=6 en régimen de rebote sin drawdown (survivorship)**: aflojar un
guardrail de riesgo sobre 6 puntos sería especulativo.

**Conclusión:** el problema de los stops ATR **no es de lógica sino de poder
estadístico** — no se puede decidir bien sobre n=6 sin un período de stress.
Esto NO genera una historia nueva de stops; lo absorbe **E4** (poder estadístico),
que es lo que destraba re-evaluar A1 con datos suficientes.

---

## 2. MLTX: un solo nombre se come toda la ganancia

`realized.per_ticker` (peores):

```
MLTX  n=2  -2642.01     <- el ciclo grande: -2607.20 (-9.94%, 6d) por signal_sell
KO    n=4  -1116.46
WMT   n=3   -772.71
PEP   n=2   -594.50
MO    n=2   -592.11
```

P/L total +$278 vs **P/L sin MLTX +$2.920**. Un único nombre define el resultado.
MLTX es el biotech clínico que cayó −89.9% (único de la watchlist; ver
`data_audit_2026-05-26`). No hubo ni filtro de universo por calidad/liquidez ni
cap de exposición por nombre que frenara el desastre.

Ojo con el sesgo de medición: la watchlist son **52/52 nombres vivos**
(survivorship), así que el backtest *subestima* cuántos MLTX habría en una
muestra real. La defensa correcta es estructural, no por nombre.

→ Historia **E1** (anti-MLTX: universo por liquidez/calidad + cap de exposición
por nombre). Es la de **mayor ganancia directa** y aparte mejora la calidad del
universo de datos.

---

## 3. El buy_score no tiene alpha a 5 días

`timing`:

```
score_fwd5_corr = -0.081   (n=27 pares score↔fwd5)
good5_pct       = 51.2%    (22/43 compras con precio arriba a 5 días hábiles)
mean5/median5   = +2.50% / +0.40%
good20_pct      = 50.0%    (17/34)
mean20/median20 = +5.79% / -0.15%
```

La correlación entre el `buy_score` (= `ml_probability` calibrada de `analyze()`)
y el retorno fwd5 es **−0.08**: el score **no anticipa** el movimiento de corto
plazo. El timing de entrada es moneda al aire (good5 = 51%). Esto es la raíz
matemática del 47.6%: si las entradas son aleatorias y el payoff es simétrico,
el win-rate *tiene* que dar ~50%.

Refuerzos del log de runtime: XGBoost inestable (`val_acc std >8%` para casi
todos los tickers) y gap train/val 99%/55% (sobreajuste) — ver observaciones del
backlog.

**Estado:** ya existe la **Tarea 3** (validar/degradar el buy_score por
walk-forward). Lo que falta es **poder estadístico** (n=27 es poco para concluir).
→ se actualizan los números de la Tarea 3 y se la hace depender de **E4**.

---

## 4. El payoff ratio es muy bajo y todo cuelga de 4 trades

- Ganadores: n=20, avg hold 6.7d, avg **+4.57%**.
- Perdedores: n=22, avg hold 6.5d, avg **−3.21%**.
- Payoff ratio en $ = 408.60 / 358.82 = **1.14**.

Los 4 mayores ganadores aportan **~$5.681** de los ~$8.172 de ganancia bruta
(**69%**):

```
MU   +1714.65 (1d)    TJX  +1417.61 (13d)
TSLA +1371.10 (12d)   AAPL +1178.61 (18d)
```

Curva frágil: sacando ese puñado, el sistema es profundamente negativo. Y los
grandes ganadores **corrieron 12–27 días** — la asimetría que existe viene de
dejarlos correr, no de la tasa de acierto.

**El otro lado (vender temprano):** `sell_calibration` de los SELL de señal:

```
n=32  up_after=16 (50.0%)  mean_fwd5 = +2.94%
```

La mitad de las veces el precio sigue subiendo tras vender (mean +2.94%): se
regala upside cerrando el 100% en cada flip ruidoso. (Números frescos 2026-06-30;
la Tarea 2 fue escrita con 57% / +3.92% sobre una muestra anterior — mismo signo,
sesgo pesimista confirmado.)

→ La **Tarea 2** ya ataca el lado perdedor (scale-out del flip). Se la **enriquece**
para cubrir también el lado ganador (trailing sobre el remanente para subir el
payoff ratio), con los números frescos.

---

## 5. Contaminación de datos: KLAC corrió ~10× y churn de holds 0-día

- **KLAC ~10×:** el ciclo KLAC (BUY @ 1942.70, SELL @ 1987.83 por `atr_trail`)
  corrió en escala ~$1.940 cuando el precio real era ~$190–210. El notional quedó
  ~10× inflado → distorsiona peso de portfolio, sizing de ciclos vecinos, DD y
  ADV. Aparece como un `atr_trail` "ganador" (+$85.51) que **ensucia hasta la
  muestra de salidas ATR del §1**. Ya está documentado como bug; se eleva su
  prioridad porque **contamina la medición de todo lo demás**.
- **Churn:** `churn.n_le7d = 7` round-trips re-comprados dentro de 7 días, con
  varios holds de **0 días** (KO, MRVL, GM, MLTX). El anti-churn (Gate 5b 3/10) y
  el anti-flap están ON desde el 2026-06-19, así que esto es historia previa; no
  genera historia nueva (queda el hueco residual N5, impacto bajo).

→ Historia **E5** = el bug de sanity de precios (ya en el backlog) sube de
prioridad. La limpieza del cache es prerequisito de **E4** (un dataset
walk-forward construido sobre precios corruptos hereda la corrupción).

---

## 6. El meta-problema: casi toda decisión está sub-potenciada

Tamaños de muestra de cada kill-criteria:

- 42 round-trips totales (20/22).
- 27 pares score↔fwd5 (Tarea 3).
- **6 salidas ATR limpias** (A1, ya NO-SHIP por no robusto).
- XGBoost con gap 99/55 y val set < 100.
- Consenso de analistas no point-in-time (T-CAT-5b bloqueada hasta ~jul 2026).

La orden de Chapa (2026-06-25) es explícita: ante la duda, **mejor calidad de
datos / mayor ganancia**. La lectura directa es que la inversión de mayor
apalancamiento es **generar poder estadístico** (harness walk-forward sobre el
cache 5y/10y con disciplina point-in-time + ventana de stress histórica), porque
es lo que destraba decidir *correctamente* A1, Tarea 3 y el resto — en vez de
decidir sobre n=6.

→ Historia **E4** (poder estadístico), enabler transversal.

---

## Resumen → historias

| # | Historia | Driver | Tipo |
|---|---|---|---|
| **E1** | Universo liquidez/calidad + cap de exposición por nombre (anti-MLTX) | §2 | Mayor ganancia |
| **E2** | Reframe del panel Métricas (expectancy/PF/payoff/P-L-ex-worst, no win-rate suelto) | §0 | Calidad de decisión (display) |
| **E4** | Poder estadístico: harness walk-forward + ventana de stress | §1,§3,§6 | Calidad de datos (enabler) |
| **E5** | Sanity de precios fuera de banda + re-auditar ciclos (KLAC) | §5 | Calidad de datos (bug) |
| Tarea 2 (enriq.) | Scale-out SELL + trailing en el remanente ganador | §4 | Mayor ganancia |
| Tarea 3 (act.) | Validar/degradar buy_score por walk-forward (n=27, corr −0.08) | §3 | Calidad de datos |

A1 (stops ATR) queda cerrado NO-SHIP; se re-evalúa cuando **E4** dé datos de stress.
