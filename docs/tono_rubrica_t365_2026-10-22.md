# Tarea 365 — la rúbrica del tono, más explícita: NO-SHIP (2026-10-22)

**Veredicto: NO-SHIP por el primer criterio.** El prompt candidato acierta el nivel exacto en **26 de 44** titulares; el vigente, en **27**. El criterio pedía *más*. El prompt de `data/catalyst_classifier.py` **no se cambia**, y no se reclasifica nada.

## El kill-criteria, fijado en el backlog antes de tocar el prompt

1. Sobre un set de ~40 titulares reales etiquetados a mano contra la rúbrica, con `qwen2.5:14b` y sin escribir la DB: el prompt nuevo acierta el nivel exacto en **más** titulares que el viejo, **y** queda a ±1 en ≥ 90%.
2. En 300 filas recientes, ningún nivel con menos del 1% de las no neutrales.
3. Si no mejora, no se cambia.

El (2) no se corrió: el (1) ya decide.

## El set

44 titulares de `news_events` clasificados `-7n` (copia de la DB del 2026-10-22, solo lectura), con una regla de muestreo declarada y semillas fijas: los casos de la 290 (4 de PepsiCo recortando guidance, 3 de Bank of America por el *miss* y la multa), 7 candidatos a −3 por palabras clave (*cuts/lowers guidance, slashes, plunge, bankrupt, fraud, recall, fails*), y al azar 10 de +3, 6 de +2, 6 de −2, 3 de +1, 3 de −1 y 2 de 0.

**Quién etiquetó:** Claude, no Chapa, contra la rúbrica **tal como está escrita** en el prompt vigente, y **antes** de escribir el candidato. Las etiquetas se congelaron con sha256 `c28c38175e8b3fe8`. Quedaron −3: 1, −2: 12, −1: 2, 0: 11, +1: 9, +2: 5, +3: 4. Que haya un solo −3 no es un sesgo del set: entre los siete candidatos por palabra clave, seis eran de otra empresa o de una caída del sector.

Decisiones de etiqueta que conviene ver, porque mueven el número: un recorte de guidance propio sin *beat* es −3 (la rúbrica: *results that miss and cut guidance*); *beat* más recorte es mixto (−2 si la acción cae, 0 si sube); una multa de $1.200 M a Bank of America es −2 (*a notable lawsuit or probe*), no −3; para el **comprador**, una adquisición es 0; las opiniones y predicciones son ±1.

## El candidato

La rúbrica vigente, sin niveles nuevos, con las reglas que pedía la tarea dichas explícitas: *a beat WITHOUT a raise is +2, not +3*; *the ticker CUTS or LOWERS its own guidance or outlook (that alone is -3; if the same headline also reports a beat, it is -2)*; ejemplos negativos tan concretos como los positivos (*a notable fine, lawsuit or probe, a rival entering its market*); y *opinion pieces, predictions, listicles and analyst commentary are at most +1 or -1*.

## Resultado

| | exacto | ±1 |
|---|---|---|
| guardado en la DB (prompt vigente, cuando se clasificó) | 24/44 | 40/44 (91%) |
| prompt vigente, ahora | **27/44** | 40/44 (91%) |
| candidato | **26/44** | 42/44 (95%) |

Temperatura 0; ninguna falla de parseo. Lo que el candidato arregla: los dos recortes de PepsiCo (−2 → −3 el puro; +2 → 0 el de *beat* y suba). Lo que rompe o no arregla: manda a −3 el de *beat* más recorte con caída (etiqueta −2); sigue poniendo +3 al **comprador** de Braze (Salesforce) y a dos *beats* sin *raise* (ASML, Tesla); baja a 0 la pérdida de KFC para PepsiCo (etiqueta −2, vigente −1).

**No se itera contra este set.** Ajustar un segundo prompt hasta que gane sobre los mismos 44 titulares, etiquetados por el mismo que escribe el prompt, sería sobreajustar al etiquetador: el número dejaría de medir la rúbrica.

## Lo que queda

El defecto de la 290 sigue: −3 es el 0,03% de las no neutrales (3 de 8.881 en esta copia) y +3 el 2,6%. Una próxima tarea que lo retome necesitaría etiquetas que no sean de quien escribe el prompt (Chapa, o dos etiquetadores) y un set nuevo, no éste.

## Las filas

| # | id | ticker | grupo | etiqueta | guardado | viejo | nuevo | titular |
|---|---|---|---|---|---|---|---|---|
| 0 | 77852 | PEP | 290_pepsico | -3 | -2 | -2 | -3 | PepsiCo Lowers Guidance on Mounting Costs in North America |
| 1 | 79757 | PEP | 290_pepsico | +0 | +1 | +1 | +1 | Pepsi shares rallied despite cutting profit guidance. Where Cramer stands on the stock now |
| 2 | 79755 | PEP | 290_pepsico | -2 | -2 | -2 | -3 | PepsiCo's Ongoing North America Weakness Drives Guidance Cut, Says Analyst |
| 3 | 77844 | PEP | 290_pepsico | +0 | +2 | +2 | +0 | PepsiCo beats earnings expectations, lowers guidance as it aims to stabilize North America |
| 4 | 83738 | BAC | 290_bac | -2 | -2 | -2 | -2 | Bank earnings, $1.2B in penalties: Who really pays the price? |
| 5 | 82609 | BAC | 290_bac | -2 | -2 | -2 | -2 | Bank of America Q3 Adj. EPS $1.08 Misses $1.11 Estimate, Sales $29.958B Miss $30.685B Esti |
| 6 | 83705 | BAC | 290_bac | -2 | -2 | -2 | -2 | Bank of America’s $1.2B Money Laundering Fine Raises Questions Over Warren’s Crypto Crackd |
| 7 | 81332 | DIS | cand_-3 | +1 | +1 | +1 | +1 | From Google Deal to Bankruptcy: Character.AI Files for Chapter 11, Puts Disney In Driver’s |
| 8 | 75472 | META | cand_-3 | -2 | -2 | -2 | -2 | Mark Cuban says Facebook knowingly runs AI deepfake scam ads as Meta docs reveal $16 billi |
| 9 | 74186 | META | cand_-3 | +0 | +0 | +0 | +0 | Reddit Plunges 36% Year to Date: Should You Buy the Stock on the Dip? |
| 10 | 75642 | AMZN | cand_-3 | +0 | -1 | -1 | -1 | Netflix Stock Plunges 26.8% Year to Date: 3 Key Reasons to Stay Away |
| 11 | 81398 | GOOGL | cand_-3 | +0 | -1 | +0 | -1 | Character.ai declares bankruptcy, citing legal and business woes |
| 12 | 85542 | TSM | cand_-3 | +0 | -1 | -1 | -1 | AI Stocks Plunge, but Jensen Huang Says Nvidia Gets New Chip Orders Almost Daily |
| 13 | 84928 | BLK | cand_-3 | +0 | +0 | +0 | +0 | Mike Novogratz Warns Nasdaq Could Plunge 30% in an ‘AI Catastrophe’ — Here’s Why He Still  |
| 14 | 77860 | PEP | lvl+3 | +2 | +3 | +2 | +2 | PepsiCo Q3 Adj. EPS $2.34 Beats $2.29 Estimate, Sales $25.274B Beat $24.962B Estimate |
| 15 | 80102 | BMY | lvl+3 | +3 | +3 | +3 | +3 | Bristol Myers Squibb Shares Jump 6.5% Following Positive Phase 3 Trial Results for Two The |
| 16 | 90036 | CRM | lvl+3 | +0 | +3 | +3 | +3 | Stock Market Today, Oct. 20: Salesforce Agrees to Acquire Braze for $5.66 Billion: BRZE St |
| 17 | 78949 | TSLA | lvl+3 | +1 | +3 | +3 | +2 | Unlike The EV Narrative, Cybercab Does Not Need Tesla To Overcome An Entire Industry |
| 18 | 82484 | ASML | lvl+3 | +2 | +3 | +3 | +3 | AI boom drives record sales at Dutch tech giant ASML |
| 19 | 88799 | GM | lvl+3 | +3 | +3 | +3 | +3 | What General Motors (GM) Said on Its Q3 Earnings Call |
| 20 | 89608 | TSM | lvl+3 | +3 | +3 | +3 | +3 | TSMC Stock: AI Demand Drives Strong Q3 Results |
| 21 | 89885 | ASML | lvl+3 | +2 | +3 | +3 | +2 | ASML Climbs After Record Q3 as CFO Fights China Curbs: “Common Sense Will Prevail” |
| 22 | 72668 | TSLA | lvl+3 | +2 | +3 | +3 | +3 | Why Tesla Stock Jumped Today |
| 23 | 78960 | TSM | lvl+3 | +1 | +3 | +3 | +2 | Taiwan Semiconductor (TSM) Grew Profits 77.4%. Is Its Premium Valuation Justified? |
| 24 | 83152 | MU | lvl+2 | +1 | +2 | +2 | +2 | MU Stock Edges Up Overnight: Elon Musk Says Micron Is Being ‘Reasonable’ On Memory Prices  |
| 25 | 86459 | GOOGL | lvl+2 | +1 | +2 | +1 | +1 | Prediction: Alphabet Will Be a Larger Company Than Apple by the End of 2027 |
| 26 | 76956 | AVGO | lvl+2 | +1 | +2 | +2 | +2 | Broadcom Is Financing Its AI Moat |
| 27 | 80099 | BMY | lvl+2 | +2 | +2 | +2 | +2 | Bristol Myers Stock Is Rising on a Double Dose of Good News |
| 28 | 82184 | UNH | lvl+2 | +3 | +2 | +2 | +2 | UnitedHealth Group stock jumps 5% on profit outlook raise |
| 29 | 87088 | SPG | lvl+2 | +1 | +2 | +2 | +2 | How Dividend Raise At Simon Property Group Stock Has Changed Its Investment Story |
| 30 | 83461 | WFC | lvl-2 | -2 | -2 | -2 | -2 | Wells Fargo Analysts Lower Their Forecasts After Q3 Results |
| 31 | 81837 | MU | lvl-2 | -2 | -2 | -2 | -2 | Micron Falls 5% as China’s CXMT Targets Server Memory; SanDisk Drops 4% |
| 32 | 82560 | BAC | lvl-2 | -2 | -2 | -2 | -1 | Bank of America CEO Attempts to Reassure Skittish Investors as Stock Sinks |
| 33 | 73802 | INTC | lvl-2 | -2 | -2 | -2 | -2 | Intel’s Terafab Opportunity Gets Crowded: Musk Confirms Talks With Taiwan Semiconductor |
| 34 | 73936 | NKE | lvl-2 | -2 | -2 | -2 | -2 | S&P Downgrades Nike From A+ To A On Protracted Turnaround, Expected Steep Cash Flow Declin |
| 35 | 74999 | NKE | lvl-2 | -2 | -2 | -2 | -2 | Nike Stock Gets Another Downgrade. Why the Market Shift Looks ‘Irreversible.’ |
| 36 | 90111 | DUK | lvl+1 | +1 | +1 | +1 | +1 | Morgan Stanley Adjusts Price Target on Duke Energy to $128 From $127 |
| 37 | 83389 | TMUS | lvl+1 | +1 | +1 | +1 | +0 | 3 Dividend Stocks Raising Payouts 3x Faster Than Social Security’s 3.6% COLA |
| 38 | 88620 | CRM | lvl+1 | +0 | +1 | +1 | +1 | Salesforce is buying Braze for $5.7 billion |
| 39 | 91433 | PEP | lvl-1 | -2 | -1 | -1 | +0 | Can Coca-Cola (KO) Stock Support 28 Times Earnings? |
| 40 | 77635 | MU | lvl-1 | -1 | -1 | -1 | -1 | Micron: The Party Is Coming To An End |
| 41 | 90698 | NKE | lvl-1 | -1 | -1 | -1 | -1 | How Nike’s China Woes Are Putting Pressure on the Broader Market |
| 42 | 84375 | TSLA | lvl0 | +0 | +0 | +0 | +0 | Analyst Sees TSLA-SPCX Merger Coming By December, but Prediction Markets Aren’t Buying It |
| 43 | 80633 | ORCL | lvl0 | +0 | +0 | +0 | +0 | Oracle (ORCL) Has $664B Lined Up. The Market Wants Cash First |
