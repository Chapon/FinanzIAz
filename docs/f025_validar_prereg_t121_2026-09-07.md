# PRE-REGISTRO — Validar `f025` en el marco de la cuenta viva (Tarea 121, F025-VALIDAR)

**Escrito el 2026-09-07, antes de correr.** Runner: `scripts/run_sizing_exposure_t10_t20.py`.
Origen: `docs/t20_killgate_t115_2026-09-07.md` + la decisión de Chapa de bajar
`paper_regime_scale_factor` de 0.50 a **0.25** (commit `2a4404a`).

**Por qué hay pre-registro:** `f025` es el factor **cableado y activo** en la cuenta viva. Re-medirlo
toca una decisión de trading ⇒ regla 2.

---

## 0. Disclosure completo — y por qué esta tarea NO congela umbrales nuevos

**Ya vi los números de este marco.** La corrida B de la tarea 115 (10 slots, 127 tickers) quedó
**SIN VEREDICTO** por su §5.5, pero se reportó como descriptiva y yo la leí: `f025` da **ΔSharpe
−0.01**, **ΔCAGR −0.47 pp** y **maxDD 28.9% vs 33.7% (−4.8 pp)**, con PBO 0.647–0.817.

**Consecuencia metodológica, y es la decisión central de este pre-registro:** cualquier umbral nuevo
que yo congele hoy estaría **ajustado a números que ya vi**. Eso no es pre-registrar: es fitear con
un paso extra. Así que esta tarea **no inventa kill-criteria**. Hace dos cosas, las dos sin umbral
nuevo:

1. **Fact-check contra el criterio congelado de la T20** (§5, julio), que existe desde antes y no lo
   elegí yo. Cuatro criterios, evaluados sobre `f025`, en el marco de la cuenta.
2. **Reportar la evidencia sobre la que se apoyó la decisión** —el alivio de drawdown y su
   descomposición por régimen— **con el instrumento corregido** y en una corrida **válida**.

**Lo que esta tarea NO puede hacer, dicho antes:** declarar `f025` *"validado"*. Con la información
disponible eso requeriría un umbral que hoy no se puede fijar limpio. Lo que sí puede es decir con
números **si el criterio de julio se cumple o no en el marco de la cuenta**, y **cuánto vale el
alivio de DD** que motivó la decisión. Fijar un criterio limpio para la pregunta del drawdown pide
una muestra que no se haya usado para mirar — es otra tarea, y queda anotada como tal.

---

## 1. La pregunta

> ¿`R2b_f025` —el factor cableado y activo— cumple los cuatro kill-criteria congelados de la T20 en
> **el marco que la cuenta opera** (10 slots, 127 tickers), y cuánto vale ahí el alivio de drawdown
> sobre el que se apoyó la decisión del 2026-09-07?

## 2. Población y config (CONGELADO)

- Universo `data/harness_universe_live_acct2.txt` (**127 tickers**, 12404 entradas),
  `--period 10y`, `--warmup 250`, `--spacing 20`, `--cap-days 20`, `--capital 50000`,
  **`--max-positions 10`** (los slots de la cuenta viva).
- **`--live-gates`** ⇒ la regla que el engine ejecuta. Se reporta también la corrida sin gates, al
  lado, para poder atribuir.
- `--fill-mode decision` (el honesto).
- **Instrumento corregido hoy:** el sobregiro de cash está arreglado (tarea 123) y el criterio 4 está
  cableado (tarea 120). Es la primera corrida de este harness con las dos cosas.

## 3. Sanity del instrumento (si falla alguno, la corrida es INVÁLIDA y no hay veredicto)

1. **Contabilidad** equity-vs-cash ≤ `1e-4` en los siete brazos y el oráculo.
2. **Invariante de exits**: ninguna variante cambia la salida de una posición compartida.
3. **El oráculo se despega**: `CAGR(V_oracle_size) ≥ CAGR(B0) + 5.00 pp` — mismo umbral que usó la
   115, que a su vez lo tomó de la T26/T26b. No es nuevo.
4. **Los gates muerden**: `n_gate5_blocked > 0`.
5. **Los brazos BAJO TEST bloquean el mismo conjunto** — `B0` y los tres `R2b`, que son los que
   deciden acá y todos van por la rama `size_weight is None`.

> **§3.5 cambia respecto del §5.5 de la 115, y hay que decir exactamente por qué.** Aquél exigía la
> identidad en **los siete** brazos, como **predicción falsable** del §3 del doc de la tarea 36. Esa
> predicción **ya se puso a prueba y se falsificó** (115), **el mecanismo se midió** (118: es
> `n_no_cash`, no `max_weight`) y **los dos docs se corrigieron**. `S1_inverse_vol` diverge porque
> **genuinamente se queda sin plata** —112 rechazos que el arreglo de la 123 **no** elimina ni debe
> eliminar, porque el engine vivo tampoco puede comprar sin cash—. Arrastrar el §5.5 entero acá
> garantizaría una corrida inválida por un motivo ya entendido y ajeno a la pregunta.
>
> **Esto NO es aflojar un sanity porque falló.** Es reemplazar una predicción ya testeada por el
> enunciado corregido, y acotarla a los brazos bajo test. Si `B0` o cualquier `R2b` divergen, la
> corrida **es inválida** — ahí no hay indulto.

## 4. Qué se evalúa (CONGELADO — los criterios son los de julio, sin tocar)

Sobre **`R2b_f025` vs `B0_equal_weight`**, con los gates ON:

| # | criterio T20 §5 | umbral (de julio) |
|---|---|---|
| C1 | beneficio | ΔSharpe ≥ +0.10 **o** ΔCAGR ≥ +1.0 pp |
| C2 | riesgo (brazo de régimen) | maxDD **no sube** vs `B0` |
| C3 | robustez OOS | DSR > 0 **y** PBO < 0.5, los 7 brazos como intentos |
| C4 | no depende de un régimen | el beneficio no viene de una sola ventana (cableado por la 120) |

**Y se reporta, sin umbral porque no lo hay:** el **alivio de maxDD** de los tres factores, su
descomposición por régimen (`pnl_pts`, la métrica que sí discrimina desde la 120), y la comparación
contra el marco publicado.

## 5. Qué se hace con el resultado

**Nada automático, y nada en la cuenta viva desde esta tarea.** Igual que la 115: se mide, se
presenta, y **la decisión es de Chapa**. Los desenlaces previsibles y qué significan:

| desenlace | lectura |
|---|---|
| cumple los cuatro | el criterio de julio se sostiene también en el marco de la cuenta; nada que decidir |
| falla C1 y el alivio de DD **está** | es la situación que ya motivó la decisión, ahora con corrida válida: el factor se sostiene por drawdown, **no** por el criterio de julio, y eso queda escrito donde se lo lee |
| falla C1 y el alivio de DD **no está** | la decisión del 2026-09-07 pierde su respaldo en este marco ⇒ **se eleva a Chapa** con las opciones |
| falla C2, C3 o C4 | se nombra cuál y se eleva |

**No se re-decide después de ver resultados.** Los cuatro criterios vienen de julio y no se tocan;
y como este pre-registro **no congela umbrales nuevos**, tampoco hay nada que aflojar.

## 6. Qué NO se modela (caveats antes de correr)

Los mismos desvíos que declara el banner, con **uno que importa especialmente acá**: el **overlay de
volatilidad de cartera** muerde **todos los días** en la cuenta viva y hace **lo mismo que `R2b`** —
recortar el tamaño de las BUY nuevas—. No se modela, y es el siguiente sospechoso de estar
acreditándole al brazo un trabajo que no es suyo. Si `f025` sostiene el alivio de DD, medir el
overlay pasa a ser la pregunta que sigue.
