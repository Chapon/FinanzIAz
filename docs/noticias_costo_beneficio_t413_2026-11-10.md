# Noticias: cuánto cuestan y quién usa lo que producen — tarea 413 (spike)

Fecha: 2026-11-10. **Sólo lectura**: una copia de `finanzias.db` del 2026-11-09 17:52 y una copia de
`~/.finanzias/finanzias.log` (hora local, del 2026-09-07 al 2026-11-09). No cambia nada.

**Todos los números salen de** `python scripts/measure_news_cost_benefit_t413.py --db <copia> --log <copia>`
(`medir_db`, `medir_log` y `acuerdo_heuristica`; las consultas SQL están en el script). Cada número de
abajo dice de qué clave del JSON sale. El script tiene su test (`tests/test_news_cost_benefit_t413.py`),
probado por mutación: sin normalizar títulos, contando el dry-run o ignorando las ventas, da rojo.

## En una línea

**Las noticias no alimentan ninguna decisión de trading; lo único que las usa es la pantalla.** El
costo grande es la clasificación con qwen (**49,6 h** de GPU en dos meses, contra **9,5 h** de
descarga), y lo único que la usa es el orden de la pestaña Noticias. El harvest no se puede apagar:
el mismo proceso baja el **consenso de analistas**, que sí alimenta el surprise score y el PEAD. Hay
un desperdicio claro (el harvest horario vuelve a bajar el consenso en cada corrida y no guarda nada),
y una cosa que no se puede medir: **si alguien mira la pestaña**, porque nada lo registra.

## 1. El costo, por etapa y por fuente

### Descarga (harvest) — `log.harvest`

| | corridas | recibidas | nuevas | % nuevas | horas medidas¹ | mediana |
|---|---|---|---|---|---|---|
| **Total** | 134 | 1.576.904 | 65.554 | **4,2 %** | 9,5 h (104 corridas) | 318 s |
| Diario (harvest + clasificación) | 51 | 575.413 | 51.388 | 8,9 % | 4,2 h (42) | 345 s |
| Horario (sólo harvest, en horario de mercado) | 83 | 1.001.491 | 14.166 | **1,4 %** | 5,3 h (62) | 306 s |

¹ Las corridas de antes de que el resumen trajera la duración (`en NNNs`) no se cuentan en las horas.

- **El 96 % de lo que se baja ya estaba.** No es un defecto de dedup: Finnhub contesta la ventana de
  7 días entera en cada pedido, y eso es lo que permite recuperar los días con la app cerrada.
- **El horario se lleva el 56 % del tiempo de descarga y trae el 22 % de lo nuevo.** Casi todo eso lo
  traería igual el diario siguiente (la ventana es de 7 días): lo que compra es **frescura** en la
  pestaña, no cobertura.
- **El consenso.** El diario guardó 47.890 filas de consenso. El horario **recibió 104.895 y guardó
  29** (`por_disparo.horario.est_*`): `_insert_estimate_if_new_today` se queda con la primera foto
  del día, así que cada corrida horaria vuelve a pedirle a Yahoo cuatro propiedades de 127 tickers
  para tirarlas. → **tarea 414**.
- **Días.** De los 64 días del log, hubo log en 41 y harvest en 39 (`dias_con_log`,
  `dias_con_harvest`): los días sin harvest son los días con la app cerrada. Las noticias se
  recuperan solas hasta 7 días; el consenso no (eso lo resuelve la nube, 355/356).

### Clasificación (qwen2.5:14b local) — `log.clasificacion`

- **40 corridas, 60.303 noticias, 49,6 h → 2,96 s por noticia.** Es **cinco veces** el tiempo de
  descarga, y es GPU: mientras corre, la máquina está ocupada (la 409 le agregó un botón para
  detenerla, y el 06/11 se detuvo a pedido con 4.334 pendientes).
- **La mitad se clasifica tarde.** De las 39.784 clasificadas en la escala de 7 niveles,
  **20.476 (51 %) tenían más de 1 día** al clasificarse y 11.781 (30 %) más de 3
  (`uso.qwen7n_con_mas_de_*`). La pestaña abre en una ventana de **1 día** (se puede subir a 14).
  Es el atraso que dejan los días con la app cerrada.
- **El 31 % sale `other`** (35.283 de 113.338, `por_tipo`): un tercio del trabajo termina en «no es
  ninguna categoría».

### Disco — `db.news_events`

- **113.338 filas** desde el 2026-06-06, de 131 tickers. El texto (título + contenido + URL) suma
  **40,1 MB**, el 34 % de los 119,5 MB de la DB; crece ~0,26 MB por día (≈ 95 MB por año). Es
  barato: no es donde está el costo.

### Por fuente: lo que trae cada una y lo que **sólo** trae ella — `por_fuente`

«Sólo esta fuente» = filas cuyo (ticker, título normalizado) no aparece en ninguna otra fuente.

| fuente | filas | MB | sólo esta fuente | activa |
|---|---|---|---|---|
| `finnhub:Yahoo` | 53.125 | 20,8 | 50.554 (95 %) | sí |
| `yfinance` | 26.844 | 10,5 | 24.379 (91 %) | hasta el 01/10 (404 de Yahoo, tarea 354) |
| `finnhub:Benzinga` | 12.845 | 4,1 | 12.526 (98 %) | sí |
| `yfinance:search` | 8.430 | 1,4 | 8.260 (98 %) | desde el 19/10 |
| `finnhub:SeekingAlpha` | 5.250 | 1,5 | 5.249 | sí |
| `sec_8k` | 2.898 | 0,6 | 2.898 | sí |
| `finnhub:CNBC` | 2.534 | 0,7 | 2.534 | sí |
| `finnhub:ChartMill` | 1.279 | 0,4 | 1.279 | sí |
| `finnhub:Fintel` | 133 | 0,0 | 133 | sí |

**Las fuentes casi no se pisan**: hay 107.647 titulares distintos en 113.338 filas, o sea que sólo
el 5 % es el mismo titular desde dos fuentes. Recortar una fuente recorta sus noticias casi enteras;
no hay una fuente redundante que sacar gratis. (Lo que esta cuenta no ve es la **misma historia con
otro titular**; eso pediría comparar por similitud, y no cambia la conclusión de que no hay ahorro
fácil por fuente.)

**El «raro, a mirar» de los 8-K, resuelto: no es un defecto.** La mediana publicada→vista de
`sec_8k` es 5.198 h porque el colector trae los últimos 20 8-K de un ticker la primera vez que lo ve:
1.028 filas entraron en junio y 1.578 el 2026-09-02 (la ampliación del universo), casi todas viejas
(`sec_8k_por_anio_publicado`: 1.433 publicadas antes de 2026). **Desde octubre, el 100 % entra
dentro de los 7 días** (159 de 159 en octubre, 48 de 48 en noviembre). Además, `published_at` de un
8-K es la fecha sin hora, que infla la latencia hasta un día.

## 2. Quién consume `news_events` y qué alimenta

| consumidor | qué lee | qué alimenta | ¿decisión de trading? |
|---|---|---|---|
| **Pestaña Noticias** (`ui/news_tab.py` → `analysis/news_digest.py`) | la ventana (1 día por default), con tipo y tono | tabla de las **50** de tono más fuerte | no — display |
| **Briefing de la pestaña** (`make_ollama_briefer`, qwen) | las 12 primeras de esa tabla | un párrafo | no — display |
| **Tarjeta de opinión de Claude** (`analysis/opinion_claude.py`) | 15 noticias de 14 días del ticker | el contexto que se le manda a Claude | no — display. **14 opiniones en la DB, todas del 2026-10-06** (`uso.opiniones_claude`) |
| **Gate 2c — exit-veto** (`paper_trading/engine.py`, `catalyst_signal_provider`) | — | nada: **OFF** por kill-criteria (T-CAT-6: ΔP/L −0,25 pts contra un umbral de +1,5) y **sin proveedor inyectado** en producción; y su base era la sorpresa (consenso), no la clasificación | no |
| `scripts/build_historical_reaction.py`, `run_catalyst_exit_veto_backtest.py` | tipo y fecha | `historical_reaction.json`, que sólo lee el backtest | no — a mano |
| `scripts/measure_news_*_t255/t258.py` | tono | las mediciones de abajo | no |
| **La nube (355/356)** | escribe, no lee | — | no; del lado de la app, la sincronización **no anda** (13 WARNING *«sin el perfil [finanzias-lector]»* en el log) |

**Lo que sí alimenta decisiones es el consenso, no las noticias**: `analyst_estimate_snapshots`
(83.161 filas) → surprise score y `surprise_profiles.json`, y el Brazo A de la 11 (PEAD). Lo baja el
mismo harvest (fuente `yfinance` = noticias + consenso), y por eso el harvest no se puede apagar
entero.

**Qué parte de las noticias toca la cartera:** el **7,0 %** de las filas (7.956) es de un ticker que
la cuenta viva tenía en cartera ese día (68 tickers distintos pasaron por la cartera). El 2,6 %
(2.926) es de tickers que ya no están en la watchlist viva.

## 3. El beneficio: lo medido y lo que no se puede medir

**Medido — sobre trading, y no pasa nada:**

- **255** (2026-10-01): el signo del sentimiento **no predice** el exceso a 5 días: Δ −0,42 pp, IC 95 %
  [−0,93, +0,10] (y con el signo contrario al esperado). `docs/noticias_impacto_t255_2026-10-01.md`.
- **258** (2026-10-01): el tono −3…+3 **no ordena** el exceso a 5 días: ρ de Spearman −0,018, IC 95 %
  [−0,055, +0,016], 4.082 unidades en 59 ruedas. `docs/noticias_tono_t258_2026-10-01.md`.
- **T-CAT-6** (2026-06-12): el exit-veto **no pasa** (ΔP/L −0,25 pts, umbral +1,5).
  `docs/catalyst_t_cat_6_reeval_2026-06-12.md`.
- **11 / PEAD:** se apoya en el consenso point-in-time, no en las noticias ni en los 8-K. El Brazo A
  se cerró sin veredicto por falta de poder (`docs/pead_t11a_2026-09-07.md`). **Los 8-K no los usa
  nadie.**

**Medido — sobre la pantalla: qwen no es reemplazable por la heurística** (`heuristica_vs_qwen`).
La pestaña ya tiene un respaldo instantáneo y sin GPU (`classify_missing`, la heurística), que usa
para lo que qwen todavía no clasificó. Contra las 39.784 que qwen clasificó en 7 niveles:

| | |
|---|---|
| mismo tipo | **40,3 %** |
| mismo signo de tono | 59,7 % |
| tono a ≤ 1 nivel | 84,4 % |
| tono no neutro: qwen / heurística | **44,0 % / 15,0 %** |

La heurística deja neutras casi todas las noticias que qwen marca con tono, y la pestaña **ordena por
la intensidad del tono**. Apagar qwen y quedarse con la heurística no es «lo mismo, más barato»: es
otra pestaña, con el orden casi plano.

**No medible hoy: si la pestaña o la tarjeta se miran.** No hay ningún registro de que se abran: en
el log no aparece ni una línea de la pestaña salvo un error del briefing. Es la pregunta que decide
todo lo que sigue (las 49,6 h de GPU existen para ordenar una tabla de 50 filas), y no tiene
respuesta con lo que hay. → **tarea 415**.

## 4. Recomendación

Por etapa, del más claro al que depende de una decisión de Chapa:

1. **Harvest diario: seguir igual.** ~6 min por día, y baja el consenso, que es lo único del pipeline
   que alimenta decisiones. Recortar fuentes de noticias no ahorra casi nada (se pisan un 5 %) y le
   saca contenido a la pestaña.
2. **Harvest horario: dejar de bajar el consenso** (**tarea 414**). Es desperdicio puro: 104.895
   filas pedidas para guardar 29. No toca nada de trading: el consenso guardado es la primera foto
   del día, y ésa la toma el diario.
3. **Clasificación con qwen: decidir con datos de uso, no antes.** Es el 84 % del costo
   (49,6 h de 59,1 h medidas) y alimenta sólo la pantalla. Las opciones, en orden de cuánto cortan:
   - **(a) Seguir igual** — si la pestaña se mira seguido.
   - **(b) No clasificar lo viejo:** saltear las noticias de más de N días (con N = 3 se ahorraba
     el 30 %, con N = 1 el 51 %). Las viejas sólo se ven si se abre la ventana de más días, y ahí
     las tapa la heurística, marcada como provisional.
   - **(c) Un modelo más chico** (qwen2.5:7b o 3b): necesita su propio pre-registro de acuerdo
     contra el 14b antes de cambiar nada (**tarea 416**, condicionada a la 415).
   - **(d) Apagar la clasificación** y dejar la heurística — si la pestaña casi no se abre; con la
     tabla de arriba a la vista: el orden queda casi plano.
   La **415** (registrar cuándo se abre la pestaña y cuándo se pide una opinión) es la que elige entre
   (a)–(d). Con cuatro semanas de datos alcanza.
4. **Briefing y tarjeta de opinión: sin cambios.** El briefing es una llamada por actualización de la
   pestaña (12 titulares) y la tarjeta se usó un solo día; ninguno es un costo de peso.

**Ninguna recomendación toca algo que alimente una decisión de trading** (las noticias no alimentan
ninguna), así que ninguna necesita backtest. Las tres tareas que salen van al backlog con su propio
criterio de aceptación.

## Hallazgos (regla 6)

- **414** — el harvest horario vuelve a bajar el consenso de los 127 tickers en cada corrida y no
  guarda nada (104.895 recibidas, 29 nuevas en 83 corridas).
- **415** — no hay registro de uso de la pestaña Noticias ni de la tarjeta de opinión: el beneficio
  del 84 % del costo del pipeline no se puede medir.
- **416** — (condicionada a la 415) medir si un modelo más chico clasifica igual que el 14b.
- No es hallazgo: la latencia de los 8-K (backfill de la primera vez, explicado arriba) y las 2.278
  filas clasificadas con `classified_by` vacío (son de antes de que existiera la columna).
- **Diferencia con el panorama del enunciado:** decía 1.180.501 recibidas en 99 harvests y 31 días;
  el script cuenta 1.576.904 en 134 y 39 días con el mismo log. El enunciado no dejó su consulta; los
  números de este informe son los del script, que se puede volver a correr.
