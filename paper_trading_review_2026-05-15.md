# Revisión de decisiones del paper trading

**Cuenta:** Sim Principal (id=1) — estrategia `analyze_single`, capital inicial $50,000.
**Período revisado:** 2026-04-24 → 2026-05-15
**Operaciones ejecutadas (`filled`):** 28 (3 NVDA/AAPL/META iniciales + 25 posteriores)
**Operaciones expiradas (no ejecutadas por falta de cash):** 2 (WMT y AMD)

Para cada operación se midió el precio de cierre +1, +3, +5 y +10 días posteriores. Se considera la "calidad" de la decisión así:

- **BUY**: buena si el precio subió después; mala si cayó por encima del costo (comisión + slippage ≈ 0.15%).
- **SELL**: buena si el precio cayó después (evitó pérdida); mala si subió (vendió antes de tiempo).

---

## 1. Decisiones que NO fueron buenas (a revisar)

### A. MLTX — compra y venta el mismo día (30-abr)
- BUY @ $16.12 → SELL @ $16.10 → **0 horas de diferencia**, pérdida −0.10%.
- En los 10 días siguientes MLTX subió **+14%** hasta $18.39.
- La segunda compra (12-may) fue a **$18.01**, es decir, se recompró un 11.8% más caro.
- **Conclusión:** la VENTA de MLTX el 30-abr fue una mala decisión. Si se hubiera mantenido la posición original (540 acciones), el portafolio tendría ~$1,050 más en plusvalía. Sospecha de whipsaw entre dos señales contradictorias del mismo motor.

### B. WMT — round-trip con pérdida
- BUY @ $132.47 (01-may) → SELL @ $129.41 (12-may) = **−2.3%** locked in.
- Cinco días después el sistema recomendó **RE-BUY @ $132.69 (14-may)**, es decir 2.54% por encima del precio de venta.
- **Conclusión:** la venta del 12-may fue prematura. El sistema vendió en mínimos y volvió a entrar más caro. Pérdida neta del ciclo ≈ −$220 más comisiones. Recomiendo revisar el umbral de la señal SELL (0.33 fue muy bajo para gatillar venta) o agregar un filtro anti-whipsaw (no recomprar el mismo ticker dentro de N días si la venta fue con pérdida).

### C. PEP — compra que se confirmó perdedora
- BUY @ $158.81 (01-may); 1 día después −2.7%, sostenidamente bajista hasta SELL @ $151.31 (12-may) = **−4.7%**.
- La señal BUY del 01-may no se sostuvo: PEP cayó de manera consistente y aún hoy cotiza alrededor de $148.93 (−6.2% vs el costo).
- **Conclusión:** mala decisión de compra. La SELL del 12-may sí fue acertada (frenó la pérdida), pero la entrada inicial no debió haberse aprobado. Vale la pena revisar qué señales se cruzaron para PEP ese día.

### D. SBUX y KO — flips intradía con margen mínimo
- SBUX: BUY @ $105.24 → SELL @ $106.39 (1.6 h después). Margen bruto 1.09%, neto ≈ 0.8% tras costos. KO en 7.6 horas con 1.41% bruto / ~1.1% neto.
- En los dos casos el sistema generó BUY y SELL casi consecutivos. KO siguió subiendo hasta $81 después de la venta (+1.3% adicional). SBUX se mantuvo plano.
- **Conclusión:** no son malas decisiones técnicamente (terminaron en positivo), pero el patrón sugiere que las dos señales se gatillaron con muy poco margen de confianza. **Recomiendo** introducir una "cool-down" mínima (ej. 24–48 h) o exigir un cambio relativo mínimo entre señales consecutivas para evitar fricción por costos.

---

## 2. Decisiones acertadas (confirmadas)

| Trade | Fecha | Resultado | Comentario |
|---|---|---|---|
| NVDA BUY @ 199.74 | 24-abr | +8.4% en 1 día | Excelente timing |
| NVDA SELL @ 209.15 | 30-abr | −6% en 3d, +12% en 10d | Acertada en corto plazo, salió antes del rally; aceptable |
| META BUY @ 659.48 | 24-abr | +2.9% en 1d | Buen entry |
| META SELL @ 668.79 | 30-abr | **−9% en 5d** | Excelente venta, evitó caída fuerte |
| AAPL BUY @ 273.57 → SELL @ 293.78 | 24-abr → 12-may | +7.4% en 19 días | Ambas decisiones correctas |
| TSLA BUY @ 372.99 → SELL @ 436.97 | 30-abr → 12-may | **+17.2%** | Mejor operación del período |
| AMAT BUY @ 420.59 → SELL @ 436.40 | 12-may → 15-may | +3.8% en 3 días | Buen ciclo |
| LRCX BUY @ 280.62 | 12-may | +5.3% en 1 día | Buen entry |
| COST BUY @ 1022.39 → SELL @ 1029.24 | 12-may → 14-may | +0.67% bruto | Acertada pero muy breve; ganancia neta marginal |
| GM BUY @ 76.55 → SELL @ 78.21 | 01-may → 14-may | +2.2% | Acertado |
| MLTX BUY @ 18.01 (recompra) | 12-may | −2.2% por ahora | Marginal, en pérdida leve |
| MO BUY @ 72.15 | 14-may | +0.95% | Demasiado reciente, sin señal mala |
| WMT BUY (re-entry) @ 132.69 | 14-may | −1.07% | Cuestionable por el round-trip previo |

---

## 3. Operaciones expiradas

- **WMT BUY (14-may)** y **AMD BUY (15-may)**: rechazadas por cash insuficiente. Si hubieran ejecutado podrían haber concentrado el portafolio. Vale comprobar que la regla de allocation_mode `signal_weighted` no esté pidiendo más cash del disponible repetidamente.

---

## 4. Recomendaciones para el motor de señales

1. **Cool-down entre BUY y SELL del mismo ticker:** mínimo 24 h o un umbral relativo (ej. la señal de venta debe ser ≥0.15 mayor en valor absoluto que la señal de compra que abrió la posición). Habría evitado los flips MLTX, SBUX y KO.
2. **Filtro anti-whipsaw**: si una posición se cerró con pérdida en los últimos 7 días, no permitir re-entrada en el mismo ticker salvo que la nueva señal sea fuertemente positiva (≥0.55). Habría evitado la recompra de WMT más cara.
3. **Revisar el umbral mínimo de aceptación para BUY**: la entrada en PEP el 01-may probablemente provino de una señal débil (no se grabó el score). Sugerir que las órdenes registren `signal_score` para auditoría posterior.
4. **Auditar la lógica de MLTX 30-abr**: BUY y SELL con 0 horas de diferencia indica que el job de scan corrió dos veces o que dos estrategias se contradijeron en el mismo ciclo.

---

## Resumen ejecutivo

De las **28 operaciones ejecutadas**:
- **19 fueron buenas decisiones** (≈68%): se confirmaron con el movimiento de precio posterior.
- **4 fueron claramente subóptimas**: MLTX SELL 30-abr (whipsaw), WMT SELL 12-may + recompra 14-may (whipsaw), PEP BUY 01-may (señal incorrecta), y el flip intradía KO (perdió upside).
- **5 quedaron marginales o sin suficiente historia** (operaciones de 14-15 mayo): MO, WMT recompra, MLTX recompra, AMAT SELL, COST SELL. Pendientes de confirmación.

El motor está acertando en la dirección general, pero pierde alfa en **whipsaws y flips intradía**. El cambio de mayor impacto sería un anti-whipsaw básico.
