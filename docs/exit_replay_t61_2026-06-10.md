# T6.1 — Exit replay sobre ciclos reales (2026-06-10)

Replay de los 32 SELLs filled de Sim Principal (28 por señal, 4 ATR) con
variantes de política de exit. Caso de negocio: la auditoría 2026-06-09
(SELLs descalibrados al pesimismo; mediana fwd5 post-SELL positiva).
Harness: `analysis/exit_replay.py` + `scripts/run_exit_replay_t61.py`
(25 tests en `tests/test_exit_replay.py`). Data: backup
`finanzias_2026-06-09_02-01-53_daily.db`, cache 1d hasta 2026-06-08.

## Método

Contrafáctico (decidido con Chapa): al saltear/deferir un SELL de señal, la
posición sigue bajo el **ATR trail real del engine** (espejo exacto de
`gates.atr_exit_decision`: stop → trail → tp, supresión del trail hasta
HWM > entry + 1×ATR, ATR Wilder 14, mults 2.0/4.0) hasta que dispare, llegue
el exit programado de la variante, o se cumpla el **cap de 20 días hábiles**.
Exits ATR reales no se tocan. Métricas: ΔP/L total (pts = % de capital
inicial 50k), max DD del equity ajustado (snapshots reales + MTM delta diario
de los ciclos extendidos), opportunity capture (capturado / rally máx 20d).

**Kill criteria (upfront)**: ship si ΔP/L ≥ +2 pts y DD ratio ≤ 1.5×.

### Limitaciones documentadas

1. **Señal persistente asumida**: no hay trail de señales scan-a-scan (ningún
   SELL quedó expired), así que los exits diferidos asumen que la señal seguía
   activa. Para la variante (a) esto es el peor caso.
2. **Sesgo fill-intradía vs close**: los fills reales son intradía; los exits
   simulados, al close. Mediana close_D vs fill: **−0.31%** (media −0.54%,
   17/28 cierran abajo del fill). Castiga ~0.3-0.5% por evento a todas las
   variantes (conservador: los resultados positivos lo son *a pesar* del bias).
3. **n = 28 eventos**, un solo régimen (abril-junio 2026, mayormente bull).
   No se recomputaron señales ML (modelos actuales ≠ modelos de entonces).

## Resultados (variantes pre-registradas del roadmap)

| variante | mod | ΔP/L $ | ΔP/L pts | DD sim (real 7.40%) | ratio | capture | PASS |
|---|---|---|---|---|---|---|---|
| (a) confirm_next_scan | 27 | −2,924 | **−5.85** | 9.85% | 1.33 | +5% | ❌ |
| (b) score_threshold 0.25 | 14 | +7,581 | **+15.16** | 11.11% | 1.502 | +67% | ❌ (DD por 0.002) |
| (c) min_holding 2d | 7 | +395 | +0.79 | 7.65% | 1.03 | +6% | ❌ (ΔP/L) |
| (c) min_holding 3d | 12 | +1,592 | **+3.18** | 6.78% | **0.92** | +18% | ✅ |

Exits de (b): 4 atr_tp, 6 atr_stop, 1 atr_trail, 3 cap_reached — el trail
contiene el riesgo; el DD 1.502 es exactamente borderline.

## Sensibilidad (post-hoc, exploratorio — NO pre-registrado)

| variante | mod | ΔP/L pts | DD ratio | PASS |
|---|---|---|---|---|
| b threshold **0.35** | 9 | **+17.19** | 1.34 | ✅ |
| b 0.25 cap 10d | 14 | +16.31 | 1.502 | ❌ |
| c min_holding **4d** | 16 | +6.65 | 0.99 | ✅ |
| c min_holding **5d** | 21 | **+9.28** | 1.00 | ✅ |

Lectura: el lift crece monótonamente con la edad mínima hasta 5d con DD
plano — **consistente con el horizonte 5d del label de entrenamiento**: el
modelo predice a 5 días y los exits a 1-3 días le cortan la predicción a la
mitad. Y los SELLs de score medio-alto (≥0.35, la "zona gris") son los que
más alpha regalan; los de score < 0.30 son los únicos que aciertan.

La variante (a) pierde plata incluso descontando el bias intradía: el D+1
post-SELL es débil en general (el rebote llega después). Delay de 1 scan no
sirve; edad mínima sí.

## Decisión propuesta

1. **SHIP (T6.4): min_holding 3 días hábiles para SELLs de señal** — única
   variante pre-registrada que pasa (+3.18 pts, DD ratio 0.92). El gate de
   min-holding ya existe (`paper_min_holding_minutes`) con bypass ATR/vol-trim
   — exactamente la semántica simulada.
2. **Input para diseño T6.4 (hysteresis)**: los datos exploratorios apoyan la
   forma que el roadmap ya hipotetizaba — SELLs con score < 0.25-0.30 ejecutan
   directo; zona gris ≥ 0.35 requiere edad mínima (3-5d) o confirmación. El
   threshold 0.35 y la edad 5d quedan como hipótesis a validar con el panel
   T6.2 en producción (n=28 no alcanza para fijarlos como parámetros).
3. **NO ship**: confirmación en scan siguiente (a) — refutada.

## Reproducir

    python scripts/run_exit_replay_t61.py [--db backups/...] [--json]
    python -m pytest tests/test_exit_replay.py -q
