---
name: backtest-replay-harness
description: Cómo correr y crear backtests/replays de exits y estrategia en FinanzIAs, con kill-criteria upfront. Usar al validar una feature de trading antes de shipear, reproducir el comportamiento histórico del motor sobre ciclos reales, o medir el impacto de una variante de salida/entrada.
---

# Backtest / Replay harness

Acá se valida si una feature **mejora las decisiones** antes de cablearla. Regla: **kill-criteria definidos ANTES de correr** (ver skill `finanzias-conventions`). Si no supera el umbral, se documenta en `docs/` y no se shipea.

## Harnesses existentes (`scripts/`)

- `run_exit_replay_t61.py` — replay de exits sobre los ciclos reales. Base del T6.1. Infra en `analysis/exit_replay.py`.
- `run_catalyst_exit_veto_backtest.py` — backtest del exit-veto por catalyst (T-CAT-6); reusa `analysis/exit_replay.py`.
- `harness.py`, `harness_walkforward.py` — backtest de estrategia (walk-forward).
- `run_switcher_validation.py`, `run_cross_sectional_validation.py` — validación de variantes de régimen / cross-sectional.
- `prefetch_harness_cache.py` — precarga el cache histórico (flag `-b` usa `get_historical_data_batch`) para no pegarle a Yahoo durante el backtest.

## Datos

- Correr **read-only sobre un backup limpio** de `finanzias.db` (carpeta `backups/`), NO sobre la DB viva. No escribir la DB desde Linux (ver `finanzias-conventions`).
- Precargar cache con `prefetch_harness_cache.py` antes de correr, para evitar 401 de Yahoo y resultados no-deterministas.
- Los harness deben ser **deterministas**. Ojo: el stacking XGBoost NO es determinístico entre runs (descubierto en T05) — está en modo kill_only justamente por eso.

## Config: contra qué cuenta corre (T27)

Los harness **no leen `paper_accounts`** (y está bien: un backtest de 10 años no puede correr sobre una cuenta viva de semanas). Pero entonces *"¿contra qué cuenta?"* = *"¿con qué config?"*, y hasta la T27 la respuesta era **la cuenta 1, pausada desde el 2026-07-01**.

- La config viva vive en **`analysis/harness_config.py`** (`LIVE_MAX_POSITIONS=10`, cuenta 2). Los runners toman de ahí el default de `--max-positions` — **no clavar literales**.
- Todo runner llama a **`announce(args.max_positions, args.universe, len(bars_by))`** antes de simular: imprime la config y **nombra los desvíos**. El objetivo no es que todo coincida a la fuerza, sino que **coincida o que el desvío esté escrito** en el pre-registro.
- Universo de la cuenta viva: **`data/harness_universe_live_acct2.txt`** (127 tickers), regenerable con `scripts/refresh_live_universe.py`. El de 41 (`harness_universe_41_10y.txt`) es el histórico de T7→T13.
- **Desvío que sigue vivo y hay que declarar:** `data/pit_signals/` se generó con ventana **expandida** (250 → ~2.514 barras) mientras el engine le pasa a `analyze()` **504 barras fijas** (`paper_history_period="2y"`). Cambian train set del XGBoost, fit de GARCH, régimen y warm-up de SMA200. Regenerar cuesta horas; cuál ventana da mejor señal es **otra pregunta, con pre-registro propio**.
- **Segundo desvío estructural (T32, lo destapó la T26):** `replay_cycle` decide **toda** salida ATR contra el **close diario**; el engine vivo la decide contra el **precio corriente intradía** (`get_bulk_prices`, scan ~15 min). O sea que una barra cuyo *mínimo* perforó el nivel pero cuyo *close* se recuperó **no dispara en el harness y sí en producción**. Ojo con la confusión fácil: `_exit_fill_price` modela el **fill** con open/low — lo que no está modelado es la **decisión**. Aplica a los cinco harness de salida (T7/T23/T13/T21/T26). **El sesgo es asimétrico y crece cuanto más ajustado el múltiplo**: el harness siempre sub-dispara, así que mide una barrera *confirmada al close*, más benigna que la viva. Corregirlo es la **26b**; hasta entonces, declararlo.
- **Reproducir un veredicto publicado de T7→T13 requiere `--max-positions 5`** (el banner lo avisa solo).

## Patrón para una variante nueva

1. **Definir kill-criteria upfront** en un doc `docs/<nombre>_<fecha>.md`: métrica (p.ej. ΔP/L total en puntos), umbral, y restricción de riesgo (p.ej. max DD no sube > 1.5×). **Declarar la config** (slots/universo/ventana) y sus desvíos.
2. Elegir el **contrafactual** explícito (p.ej. "la posición vetada sale al próximo scan con ATR activo"). El veredicto suele ser sensible a esto — dejarlo escrito.
3. Reusar `analysis/exit_replay.py` para no reimplementar el motor.
4. Correr sobre el backup + cache precargado.
5. Escribir resultados en el doc, incluyendo el veredicto (ship / no-ship) y por qué.
6. Tests offline del harness (ver `tests/` por convención de naming).

## Lecciones registradas

- Cross-sectional ranking (T05): **KILLED**, +0.124 ΔSharpe < umbral +0.15 → ruido. Quedó como dead-code.
- Exit-veto catalyst (T-CAT-6): flag OFF por razón **medida** (ΔP/L −0.25 < +1.5), no por ceguera.
- min_holding 3d (T6.1): única variante pre-registrada que PASÓ (+3.18 pts, DD 0.92) → shipeada en T6.4.

### Cómo NO construir un brazo oráculo (T26 — costó una corrida entera)

El oráculo existe para probar que **el instrumento ve lo que se le pide medir**. La T26 lo especificó mal y la corrida quedó inválida con los 6 criterios pasados. Dos reglas que salen de ahí:

1. **Un oráculo tiene que poder moverse en las DOS direcciones del eje.** El de la T26 sólo podía *suprimir* stops (saltearlos cuando el precio iba a rebotar), nunca *agregarlos*. Como en ese harness suprimir cuesta plata por sí solo, el brazo era **estructuralmente incapaz** de superar su umbral, por bien que eligiera. Si el oráculo sólo puede empujar hacia el lado que el eje penaliza, no está midiendo sensibilidad: está midiendo el costo de ese lado.
2. **El umbral del oráculo va contra un control IGUALADO, no contra el baseline.** Medido en T26: suprimir al azar a la misma tasa costó **−4.20 pp**, y elegir bien valió **+2.33 pp de CAGR / −11.1 pp de maxDD**. Contra el baseline el oráculo "fallaba" (−1.87 pp); contra el control igualado se veía clarísimo que el harness **sí** distingue calidad. Un oráculo que cambia el *número* de eventos además de *cuáles* necesita su control con el mismo número.

**Y la lección de lectura:** con ratio de selección alto (T26 midió **~55:1** — 143.096 candidatos BUY para 10 slots), una salida no compite contra la recuperación del propio nombre sino contra **el próximo candidato de la fila**. Toda métrica de "salimos antes de tiempo" (rebote post-salida, MFE no capturado) es engañosa si no se la pone contra el costo de oportunidad del slot.
