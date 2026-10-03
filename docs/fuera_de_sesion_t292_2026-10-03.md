# Fills fuera de sesión — tarea 292 — 2026-10-03

Origen: `docs/auditoria_tanda_2026-10-03.md` [C-1]. `paper_enforce_market_hours` está en `False` en vivo y nada lo registraba. El `verificador` bajó el hallazgo de ALTO a MEDIO: el *«costo en el P&L»* era un sesgo del instrumento, y el precio del fill **es** la convención del harness. Quedaban tres cosas: los defaults se contradicen, el valor vivo no estaba registrado, y el look-ahead de los scans fuera de sesión nunca se había medido.

## Decisión de Chapa

**El `False` es deliberado** (2026-10-03). Lo que se hizo con eso:

- **Documentado** en `docs/SETTINGS_REFERENCE.md`, en el `doc=` del spec y en la skill `finanzias-conventions` (Gate 1), cada uno con el **acople**: el cron diario de las 16:05 ET corre después del cierre, así que con el default `True` no llenaría nunca. El `False` es lo que lo hace funcionar.
- **Espejado:** `LIVE_ENFORCE_MARKET_HOURS = False` en `analysis/harness_config.py`, y en la tabla de la 130 en lugar de la clasificación *«NO_MODELABLE: horario de mercado real»* de la 185. Esa clasificación estaba al revés: el harness decide al close y llena al close, que es justamente lo que hace el vivo con `False` fuera de sesión. Si alguien vuelve el valor a `True`, el guard de la 130 lo acusa contra el `settings.json`.
- **Declarado:** `fills_fuera_de_sesion` en `deviations_keyed()`, condicional al `False`. Lo que el harness no tiene es la información posterior al cierre con la que decide un scan fuera de sesión.

## Medición del look-ahead

### Pre-registro

Escrito en la tarea 292 y commiteado en `a9d00f2` antes de escribir el instrumento.

- **Población:** los fills **fuera de sesión por calendario de la bolsa** (fin de semana, feriado, o fuera de 13:30–20:00 UTC en día hábil), de las dos cuentas, desde el 2026-05-01. Antes de esa fecha el flag no existía (`d5fa07d`).
- **Medida:** `s × (Open_siguiente / fill_sin_slippage − 1)`, con `s=+1` en BUY y `−1` en SELL, crudo contra crudo. Positivo = la decisión se benefició de lo que pasó después del cierre.
- **Primaria:** las órdenes por señal. Las de barrera ATR van aparte, porque son mecánicas.
- **Kill-criteria:** media primaria > **+0,25%** con el IC95 sin cruzar el 0 → tarea de corregir el fill fuera de sesión.

### Instrumento

`scripts/measure_lookahead_fuera_sesion_t292.py`. Lee la DB en sólo lectura y pide a Yahoo las barras crudas. El calendario son las ruedas de SPY, y no el día de la semana: por reloj, el fill de JNJ del **2026-09-07 (Labor Day)** a las 14:05 UTC caía «en sesión». `tests/test_fuera_de_sesion_t292.py` fija ese caso, el fin de semana y la madrugada (que abre ese mismo día); las dos mutaciones del calendario dan rojo. Verificado sobre la muestra real: los fills del sábado 2026-06-20 abren el lunes 22, y el de Labor Day, el martes 8.

### Resultado

De 245 fills desde el 2026-05-01, **67** fueron fuera de sesión.

| | n (días) | media | IC95 por día | mediana | a favor |
|---|---|---|---|---|---|
| **por señal (primaria)** | 56 (24) | **−0,16%** | **−0,62% a +0,26%** | +0,05% | 32/56 |
| por señal, BUY | 36 (20) | −0,00% | −0,81% a +0,54% | +0,17% | 24/36 |
| por señal, SELL | 20 (14) | −0,45% | −1,29% a +0,34% | −0,18% | 8/20 |
| por señal, sólo cuenta 2 | 35 (14) | +0,12% | −0,36% a +0,55% | +0,07% | 22/35 |
| barreras y otras | 11 (8) | −0,19% | −1,00% a +0,52% | +0,09% | 6/11 |

**El kill-criteria no se cumple:** la media primaria es negativa y el IC cruza el 0.

### Cómo se lee, sin estirarlo

- **No se detecta ventaja**, pero **la muestra tampoco descarta una de hasta +0,26%**, que es el extremo del IC y queda pegado al umbral. Con 24 días de scans fuera de sesión no se puede decir más. Por eso la declaración dice las dos cosas.
- El subconjunto de la cuenta 2 da positivo (+0,12%), y las SELL negativo (−0,45%), pero sus IC son todavía más anchos: ninguna de las dos diferencias se distingue de cero.
- **No se cablea nada** (regla 3). Si se quiere afinar, la muestra crece sola: cada scan fuera de sesión suma fills.

## Lo que NO se midió

- **El costo de oportunidad del fill fuera de sesión** contra llenar a la apertura siguiente. Es el mismo gap con el signo cambiado, y sale de la misma tabla: en promedio, llenar a la apertura habría dado +0,16% para la cuenta, sin significancia.
- **La cuenta 1 antes del 2026-05-01**, que incluye el SELL de META del 2026-04-30 (gap −7,44%): el flag no existía, así que no es un efecto de esta perilla.
