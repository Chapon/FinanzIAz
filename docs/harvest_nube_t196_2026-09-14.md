# T196 — ¿Puede la recolección correr en la nube a $0/mes?

**Fecha:** 2026-09-14 · **Tipo:** análisis, sin código de producción · **Decide:** Chapa.

Pregunta del enunciado: ¿se puede sacar la **recolección** (no las decisiones) a un
servicio de AWS que cueste **$0/mes**, con los datos esperando en la nube hasta que la
app abra y los importe?

**Ampliación pedida por Chapa el 2026-09-14:** evaluar también opciones fuera de la
nube, tipo Raspberry Pi. Está en §4.4, y no es un apéndice — **cambió la
recomendación**, porque una máquina propia sale por IP residencial y ahí el riesgo que
bloquea todo lo demás (§5) directamente no existe.

---

## 0. Veredicto contra el kill-criteria

El kill-criteria se fijó antes de mirar. Una opción es **viable** sólo si:
**(a)** su costo estimado con el volumen medido queda en $0/mes dentro del límite
gratuito que aplica a la cuenta, con margen declarado; **(b)** el smoke test demuestra
que **cada fuente** que se quiere mudar responde desde esa infraestructura; **(c)** la
importación a la app es idempotente y no escribe la DB desde fuera de Windows.

| Opción | (a) $0/mes | (b) smoke test | (c) import idempotente | Veredicto |
|---|---|---|---|---|
| **Raspberry Pi** en casa (u otra máquina propia siempre prendida) | **el criterio no le aplica** — ~€50-90 una vez + ~US$2/año de luz (§4.4) | **YA SATISFECHO** por 3 meses de producción: es la misma IP residencial (§5) | PASA *con un arreglo* (§6.2) | **la más fuerte** (§8) |
| Lambda + EventBridge + DynamoDB + SSM | **PASA**, margen 7,5× | **SIN EVALUAR** | idem | **sin veredicto** |
| Lambda + EventBridge + **S3** | **NO PASA** — el free tier de S3 de tu cuenta ya venció (§4.2) | SIN EVALUAR | idem | **no viable** |
| **EC2** chica | **NO PASA** — mismo motivo (§4.2) | SIN EVALUAR | idem | **no viable** |
| GitHub Actions (referencia de costo) | **PASA** — repo público, minutos ilimitados | SIN EVALUAR | idem | sirve para el probe, no para guardar (§4.3) |
| Oracle Cloud Always Free | aparente | SIN EVALUAR | idem | **descartada** — ver §4.5 |

**El criterio (a) quedó cerrado, y con tu respuesta quedó cerrado más fuerte de lo que
esperaba** (§4.2): tu cuenta de AWS es anterior a julio de 2025, así que tiene **más de
12 meses** y su free tier de 12 meses **ya venció**. S3 y EC2 no son $0 para vos — ni
ahora ni más adelante. Sobrevive sólo el bloque *always free*: Lambda, DynamoDB,
EventBridge, SSM.

**De las opciones en la nube, ninguna puede declararse viable hoy, y el motivo es uno
solo: el criterio (b) no se puede evaluar sin desplegar.** No es un detalle postergable
— es el riesgo que el propio enunciado puso primero ("si yfinance no responde desde
Lambda, la mitad del harvest no se puede mudar").

**La opción de hardware propio es la única que ya lo tiene resuelto**, y no por suerte:
un Raspberry Pi en tu casa sale por **la misma IP residencial desde la que la app
viene harvesteando hace tres meses** con 2 eventos de rate-limit en todo el log. El
riesgo #1 no es que no esté medido: es que **no existe** en esa rama. Eso, más que
cualquier tabla de costos, es lo que mueve la recomendación (§8).

---

## 1. Qué se recolecta, cuánto y cada cuánto (medido, no estimado)

Universo vivo: **127 tickers** (`paper_watchlist` de la cuenta 2; la cuenta 1, cerrada,
tiene 52). Medido contra `finanzias.db` el 2026-09-14, en lectura.

| Tabla | Filas totales | Bytes/fila | Filas/día | MB/día |
|---|---:|---:|---:|---:|
| `news_events` | 53.214 | 536 | 930 | 0,488 |
| `analyst_estimate_snapshots` | 42.843 | 81 | ~1.270 | 0,102 |
| `dividend_cache` | 950 | 62 | 7 | ~0 |
| `earnings_cache` | 44 | 55 | 2 | ~0 |
| `company_info_cache` | 138 | 86 | esporádico | ~0 |
| **Total perecedero** | | | **~2.200** | **~0,59** |

O sea **~18 MB/mes, ~215 MB/año** de payload. Es un volumen chico para cualquier
límite gratuito; **el costo no se va a decidir por almacenamiento** (§4).

Las filas/día de `analyst_estimate_snapshots` pasaron de ~515 a ~1.270 el 2026-09-02:
es el efecto de la **tarea 70** (el harvest dejó de apuntar a la cuenta pausada de 52
tickers y pasó a los 127 vivos). Todo lo que sigue usa los números post-T70.

Fuentes de noticias, últimos 30 días: `yfinance` 7.789, `finnhub:*` 12.027 (Yahoo,
Benzinga, SeekingAlpha, CNBC, ChartMill, Fintel), `sec_8k` 1.557.

**Cadencia real:** 6 harvests horarios en RTH + 1 refresh diario = **7 corridas/día**,
y sólo con la app abierta.

**Duración medida del harvest** (sólo harvest, sin clasificar; pares
*starting*/*done* del log):

| Población | n | Mediana | Máx |
|---|---:|---:|---:|
| 127 tickers (post-T70, 2026-09-04 a 09-11) | 20 | **5,0 min** | 5,8 min |
| 52 tickers (pre-T70) | 40 | 1,8 min | 1,9 min |
| **127→52 tickers, con la red caída** (2026-08-14) | 2 | — | **82 y 95 min** |

Esa última fila es el dato más importante de la sección y vuelve en §7.1: **el camino
lento no es el del éxito, es el de la falla.** El 2026-08-14 fallaron las tres fuentes
para todos los tickers y cada una se comió su presupuesto de timeout y reintentos:
~16× la mediana, con sólo 52 tickers.

---

## 2. Qué se pierde de verdad con la app cerrada (y no es lo que dice el enunciado)

El enunciado arranca de *"app cerrada = no se harvestea, no se snapshotea y no se
scanea"*, que es cierto. Pero **"no se recolecta" y "se pierde" no son lo mismo**, y la
diferencia decide el alcance del servicio.

**Cuánto estuvo cerrada la app** (2026-07-13 a 2026-09-13, 45 ruedas):

- **15 de 45 ruedas (33%) con CERO filas recolectadas.**
- Cobertura de RTH: **27,2%** de los baldes de 15 min tienen la app viva.
  (Es cota inferior: mide baldes con línea de log. Validado a mano — los días con
  noticias y 0/26 baldes son días en que la app abrió *después* del cierre.)

**Cuánto de eso es pérdida irreversible** (2026-06-08 a 2026-09-12, 70 ruedas). Las dos
tablas se comportan **al revés** una de otra:

| | Ruedas afectadas | ¿Se recupera? |
|---|---:|---|
| Noticias (por `published_at`) | **5 de 70 (7%)** | **Sí, hasta 7 días.** La fuente consulta `days_back=7` y `news_events` tiene UNIQUE en `content_hash`: al reabrir, la app re-baja la semana y deduplica sola. |
| Consenso (por `snapshot_date`) | **18 de 70 (26%)** | **No. Nunca.** Es la foto del consenso de *ese* día; yfinance sólo da la vista de hoy. |

La prueba del catch-up está en el corte de julio: al reabrir el 2026-08-09 entraron
3.220 noticias de golpe y reconstruyeron 08-03 a 08-09 con volumen normal
(322-647/día), mientras 07-28 a 08-02 volvieron con 3-38 filas — el resto de la ventana
de 7 días ya no existía. El hueco de 08-24 a 08-26 (3 días) se recuperó **entero**. En
la misma reapertura, `analyst_estimate_snapshots` trajo 518 filas: lo de un día normal.
**Cero catch-up.**

**Consecuencia para el alcance.** Lo irreversible es el snapshot de consenso: **~1.270
filas, 0,1 MB, una pasada por día** — el 17% del volumen y el trabajo más barato del
harvest. Las noticias, que son el 83% del volumen y casi todo el tiempo de corrida,
sólo se pierden en cortes de **más de 7 días**, que pasaron **una vez en tres meses**.

Y no es una tecnicidad: lo que **T-CAT-5b** venía acumulando es justamente el consenso
previo al reporte. El enunciado tiene razón en el fondo — el corte de julio se llevó la
Q2 — pero se la llevó por la tabla chica, no por la grande.

---

## 3. Qué NO puede mudarse (y por qué)

1. **La clasificación con `qwen2.5:14b`** — necesita un modelo local que no entra en
   ninguna free tier. Queda en la app, sobre lo que llegó. (Confirmado en el volumen:
   el refresh diario *con* clasificar tarda mediana 35 min contra 5 del harvest solo.)
2. **Scans y órdenes** — son decisiones y tocan la DB viva. No van, por definición.
3. **`price_cache` (precios intradía del scan)** — es subproducto de los scans; se va
   con ellos.
4. **El histórico de barras (`data/parquet`, 61 MB)** — *puede* mudarse, pero **no
   conviene**: no es perecedero. Un 10y de cualquier ticker se re-baja cuando se quiera.
   Mudar dato recuperable es gastar límite gratuito en nada.

El filtro que ordena la lista no es "qué corre en la app" sino **"qué no se puede
volver a bajar mañana"**. Con ese filtro, lo que se muda es: consenso diario (primero),
noticias (segundo), calendario de earnings (tercero, 2 filas/día).

---

## 4. Las opciones, contra su límite gratuito

### 4.1 Lo que consumiría el servicio, con el volumen medido

Supuesto declarado: 147 corridas de noticias/mes (7 × 21 ruedas) + 30 corridas de
consenso (1/día), = **177 invocaciones/mes**, a 300 s cada una (la mediana medida, que
es conservadora para la corrida de consenso sola).

| Recurso | Consumo estimado | Límite gratuito | Uso | Margen |
|---|---:|---:|---:|---:|
| Lambda — invocaciones | 177/mes | 1.000.000/mes | 0,018% | 5.600× |
| Lambda — cómputo @1.024 MB | 53.100 GB-s/mes | 400.000 GB-s/mes | 13,3% | **7,5×** |
| Lambda — cómputo @512 MB | 26.550 GB-s/mes | 400.000 GB-s/mes | 6,6% | 15× |
| EventBridge Scheduler | 177 invocaciones/mes | 14.000.000/mes | ~0% | enorme |
| DynamoDB — escrituras | 66.000 ítems/mes | ~64,8M/mes (25 WCU) | 0,1% | 980× |
| DynamoDB — storage | 215 MB/año | 25 GB | 0,9%/año | ~116 años |
| CloudWatch Logs | « 1 GB/mes | 5 GB/mes | bajo | amplio |
| Transferencia de salida | ~18 MB/mes | 100 GB/mes | 0,02% | enorme |
| SSM Parameter Store (standard) | 2 parámetros | gratis | — | — |

**El binding constraint es el cómputo de Lambda, y queda en 13,3% con 7,5× de margen.**
El universo podría crecer de 127 a ~950 tickers antes de que se pague un centavo.

### 4.2 Qué free tier aplica a TU cuenta — y por qué la respuesta cerró el criterio

**AWS cambió el esquema el 2025-07-15.** Las cuentas creadas **después** ya no tienen
los 12 meses gratis: reciben créditos ($100, hasta $200 completando actividades) sobre
un plan gratuito de **hasta 6 meses o hasta agotar el crédito**, lo que pase primero.
Lo que **no** cambió es el bloque *always free*, que no vence nunca.

> **Tu caso (respondido el 2026-09-14): cuenta anterior a julio de 2025.**
> Eso la deja bajo el esquema viejo — el de los 12 meses. Pero los 12 meses corren
> **desde el alta**, y una cuenta anterior al 2025-07-15 tiene hoy, como mínimo, **14
> meses**. O sea: **el free tier de 12 meses ya venció, y no vuelve.**
>
> La respuesta que parecía abrir opciones las cerró. Intuitivamente "cuenta vieja =
> mejor free tier", y es al revés: la cuenta vieja es la que ya lo **gastó**. S3 y EC2
> te facturan desde el primer byte. El único presupuesto que te queda es el *always
> free*, que no vence — y alcanza de sobra (§4.1).

| Servicio | ¿Always free? | En tu cuenta |
|---|---|---|
| **Lambda** (1M req + 400k GB-s/mes) | **Sí** | **gratis, para siempre** |
| **DynamoDB** (25 GB + 25 WCU/RCU) | **Sí** | **gratis, para siempre** |
| **EventBridge Scheduler** (14M/mes) | **Sí** | **gratis, para siempre** |
| **CloudWatch Logs** (5 GB/mes) | Sí | gratis |
| **SSM Parameter Store** (standard) | Sí | gratis — ahí va la key de Finnhub |
| **S3** (5 GB + 20k GET + 2k PUT) | **No — 12 meses** | **vencido** ⇒ factura |
| **EC2** t3/t4g micro | **No — 12 meses** | **vencido** ⇒ ~$3-4/mes |

Por eso la recomendación elige **DynamoDB sobre S3** aunque S3 sería más natural para
archivos JSON: **no es una preferencia técnica, es la única que en tu cuenta sigue
costando cero.** Sobre el volumen medido, S3 costaría centavos (215 MB/año) — pero
"centavos" no es "$0", y el criterio se fijó en $0 antes de mirar.

### 4.3 GitHub Actions, como referencia de costo

El repo `Chapon/FinanzIAz` es **público** (verificado contra la API de GitHub), así que
los minutos de runners estándar son **ilimitados y gratis**. Necesidad: 177 × 5 min =
**885 min/mes** — que además entrarían en los 2.000 min/mes del plan gratuito aunque el
repo pasara a privado. Ya hay CI andando y los secretos tienen dónde vivir.

Contras, y no son menores: **(i)** el cron de Actions es *best-effort* y se retrasa 5-30+
minutos bajo carga, que es justo lo que el harvest intradía existe para evitar (el caso
TSLA); **(ii)** los artifacts tienen retención de ≤90 días, así que el dato
point-in-time habría que commitearlo a una rama, y son ~215 MB/año creciendo para
siempre en un repo público; **(iii)** las IPs son de datacenter (Azure) — **el mismo
riesgo de Yahoo que AWS**, ni mejor ni peor.

De ahí sale una idea barata que sirve igual: §5.

### 4.4 Hardware propio: Raspberry Pi y parientes (pedido de Chapa, 2026-09-14)

Hasta acá todas las opciones comparten un rasgo que no salta a la vista porque no está
en ninguna tabla de precios: **salen por una IP de datacenter.** AWS, Oracle, GitHub
Actions, cualquier VPS. Y esa es, exactamente, la única variable que no se puede
evaluar (§5). Una máquina propia siempre prendida en tu casa **cambia de familia**: sale
por tu IP residencial, la misma desde la que la app viene harvesteando con éxito hace
tres meses.

**Los candidatos y lo que cuestan** (precios 2026 verificados; la Pi subió tres veces
entre nov-2025 y abr-2026):

| Equipo | Compra | Idle | Luz/año @ 24×7 | ¿Sirve? |
|---|---:|---:|---:|---|
| **Raspberry Pi 5** (4-8 GB) | €90-140 | ~2,7-3,0 W | ~26 kWh | **Sí, con holgura** |
| **Raspberry Pi 5** (1-2 GB) | €48-68 | ~2,7-3,0 W | ~26 kWh | Sí con 2 GB; 1 GB queda justo |
| **Raspberry Pi 4** (2-4 GB) | usada, menos | ~2,7-3,4 W | ~26-30 kWh | Sí, y consume casi igual |
| **Pi Zero 2 W** | €15-22 | ~0,7 W | ~6 kWh | **No.** 512 MB de RAM: pandas + 127 tickers no entra |
| PC/notebook viejo que ya tengas | €0 | 15-40 W | 130-350 kWh | Sí, y sale **cero** de compra |
| NAS que ya tengas (Synology y cía.) | €0 | ya está prendido | ~0 marginal | Sí, vía Docker — la mejor si existe |

La luz: 3 W × 24 × 365 = **26 kWh/año**. A US$0,05/kWh son ~**US$1,3/año**; a US$0,15,
~US$4. Con una notebook vieja a 25 W son 219 kWh/año — entre US$11 y US$33/año, que
sigue siendo poco pero ya es 10× la Pi.

**Las tres ventajas que no se ven en la tabla:**

1. **El riesgo #1 desaparece, no se mitiga.** No hace falta smoke test: la evidencia
   son los tres meses de log de la app corriendo sobre esa misma IP.
2. **Corre el código que ya existe.** `scripts/harvest_catalysts.py` anda tal cual en
   Raspberry Pi OS (ARM64; yfinance, pandas y numpy tienen ruedas ARM64). El camino de
   AWS, en cambio, pide reescribir: partir en lotes por el techo de 15 min (§7.1),
   empaquetar dependencias, cambiar el almacenamiento y escribir el import. **La
   diferencia de trabajo es de un orden de magnitud**, y esa es probablemente la
   segunda razón más fuerte después de la IP.
3. **Nadie te lo puede re-tarifar.** Ver §4.5, que no es una hipótesis.

**Las desventajas, que son reales:**

1. **No es $0, es capex.** €50-90 una vez. El criterio (a) se fijó en "$0/mes dentro
   del límite gratuito", que es una frase escrita pensando en un servicio en la nube:
   **al hardware propio no le aplica**, no lo pasa ni lo falla. Lo digo así en vez de
   estirar el criterio para que entre. Tu decisión es si €50-90 una vez valen más o
   menos que un $0/mes con un bloqueante sin medir.
2. **Depende de tu casa.** Corte de luz o de internet = misma pérdida que la app
   cerrada. Con la salvedad de que el piso a superar es **27% de cobertura de RTH**
   (§2): casi cualquier cosa mejora eso.
3. **Comparte IP con la app.** Si el Pi y la app harvestean a la vez, Yahoo ve el doble
   de tráfico desde una sola IP — que es justo lo que dispara el rate limit. Cuando el
   Pi entre, el harvest in-app se apaga. **No es opcional.**
4. **Mantenimiento.** Desgaste de SD (se mitiga con SSD por USB o `log2ram`),
   actualizaciones, y que alguien se acuerde de que existe.
5. **Regla 5 igual.** El Pi es Linux: **no monta ni escribe `finanzias.db`.** Escribe su
   propio store y la app, en Windows, importa. Misma disciplina que la nube (§6.3).

### 4.5 Oracle Cloud Always Free — descartada, y el motivo sirve para todo lo demás

Es el otro "always free" que suele aparecer, y con una ARM Ampere A1 correría el
harvest sin límites de tiempo ni de empaquetado. La descarto por dos motivos, y el
segundo importa más que el primero:

1. Sigue siendo **IP de datacenter**: mismo riesgo #1, sin resolver.
2. **En junio de 2026 Oracle redujo a la mitad la cuota always-free de Ampere A1** (de
   4 OCPU / 24 GB a 2 / 12) **sin anuncio público** —sólo cambió la documentación— y
   **terminó las instancias que quedaban por encima** a partir del 2026-08-18. Además,
   su política reclama instancias always-free **ociosas**, que es precisamente la forma
   de un recolector que duerme 23 horas por día.

El punto general: **"gratis para siempre" es una promesa del proveedor, revocable y
revocada.** No invalida la recomendación de AWS —el always-free de Lambda/DynamoDB
tiene otra historia— pero sí pone un piso de realismo, y es un argumento a favor de la
opción que nadie puede re-tarifar (§4.4).

---

## 5. El riesgo #1 — Yahoo desde IP de datacenter — SIN MEDIR

El enunciado lo puso primero y tenía razón. `yfinance` no es una API oficial: raspa
endpoints web, y Yahoo limita por IP y por patrón. Las IPs de datacenter son
exactamente las que más se bloquean. **Si yfinance no responde desde Lambda, se cae la
mitad del harvest** — noticias de yfinance (7.789/30d) y, sobre todo, el consenso, que
es 100% yfinance y es lo único irreversible (§2).

Las tres fuentes **no corren el mismo riesgo**, y conviene no meterlas en la misma bolsa:

| Fuente | Cómo accede | Riesgo desde datacenter |
|---|---|---|
| **Finnhub** | API con key documentada | **Bajo.** Free tier de 60 req/min; no le importa desde dónde. |
| **SEC EDGAR** | API pública con *fair access* | **Bajo.** Pide User-Agent descriptivo (ya está seteado en la máquina viva) y ≤10 req/s. La política es explícita y no discrimina por IP. |
| **yfinance** | scraping no oficial | **ALTO y sin medir.** |

Lo que hay de evidencia desde acá: el código ya tiene manejo explícito de 429 y un
rate-limiter global, y en ~2 meses de log **desde IP residencial** aparecen sólo 2
ocurrencias de "429". Eso dice que desde casa funciona; **no dice nada** sobre una IP de
AWS, y sería un error leerlo como que sí.

**Y esa misma frase, leída al revés, es el argumento de §4.4.** Los tres meses de log
son evidencia de producción de que las tres fuentes responden **desde la IP de la casa
de Chapa**. Un Raspberry Pi ahí no necesita smoke test porque no cambia la variable que
el smoke test mide. **La rama de hardware propio no tiene el riesgo #1: no lo mitiga,
no lo tiene.**

**Probe desde datacenter — escrito, pendiente de correr** (autorizado por Chapa el
2026-09-14). `scripts/probe_yahoo_datacenter_t196.py` +
`.github/workflows/probe_yahoo_datacenter_t196.yml`: baja `Ticker.news` y
`earnings_estimate` de 5 tickers y consulta EDGAR, desde los runners de GitHub (IPs de
Azure). Sale con código 0 siempre —es diagnóstico, no un gate— y emite el veredicto
como anotación, porque los logs de Actions piden token y la API de anotaciones no
(tarea 65). **No sustituye al smoke test desde AWS**: Yahoo bloquea por reputación de
rango y los rangos de AWS son los más castigados, así que un verde acá no prueba que
Lambda ande. Un **rojo**, en cambio, es concluyente en el sentido útil: ahorra abrir la
infraestructura entera. **Resultado: pendiente** — corre con el push que trae estos dos
archivos, y el número va acá cuando esté.

---

## 6. Point-in-time y la vuelta a la app

### 6.1 La marca de captura se estampa en la nube

`analyst_estimate_snapshots.snapshot_date` es **la fecha de captura**, no de publicación:
ahí vive todo el valor. El recolector de la nube tiene que estampar `snapshot_date` (y
`fetched_at`) **al recolectar**, y el importador tiene que respetarlos tal cual. Si el
import estampa la fecha de importación, el dato queda inservible para T-CAT-5b: dos
semanas de consenso entrarían todas con la fecha del día que abriste la app.

### 6.2 El import es idempotente en una tabla y **no** en la otra

- `news_events` tiene **`CREATE UNIQUE INDEX ix_news_content_hash`**. La idempotencia es
  del esquema: re-importar el mismo lote no duplica, lo garantice o no el importador.
- `analyst_estimate_snapshots` **no tiene ningún UNIQUE**. `ix_est_ticker_metric_date`
  existe pero no es único. Hoy no hay duplicados (verificado: 44.105 filas, 44.105
  claves distintas) porque `_insert_estimate_if_new_today()` hace un *read-then-write* en
  código Python, filtrando por `snapshot_date == today` con `today = _midnight(now)`.

Eso alcanza mientras el único escritor sea el harvest in-app. **Deja de alcanzar en
cuanto exista un segundo escritor**, que es exactamente lo que esta tarea propone: el
chequeo compara el datetime **exacto**, así que un importador que estampe
`snapshot_date` con hora (o en UTC contra un local) no encuentra la fila que ya está y
**la duplica en silencio** — sin error, sin log, y contaminando la serie que T-CAT-5b
necesita limpia.

**Por eso (c) pasa "con un arreglo": el UNIQUE que le falta a la tabla hermana.** Va como
tarea aparte (§10), y es prerrequisito de cualquier implementación, no del análisis.

### 6.3 La nube nunca escribe `finanzias.db`

La regla 5 se respeta sola con esta forma: la nube escribe **su** almacenamiento
(DynamoDB), y es **la app, en Windows**, la que lee de ahí e inserta. Nada monta ni toca
el archivo SQLite desde afuera. El import tiene que dejar rastro de qué trajo
(un cursor de "importado hasta X") para poder repetirse sin re-bajar todo.

---

## 7. Riesgos y trampas de costo

No todos aplican a las dos ramas, y conviene no mezclarlas: **7.1** y **7.2** son
específicos de AWS y el Pi no los tiene (no hay techo de ejecución ni VPC); **7.3**,
**7.5** y **7.6** aplican a las dos; **7.4** es de nube; y el Pi suma los suyos, que
están en §4.4 (luz, internet de casa, IP compartida con la app, mantenimiento).

**7.1 — El techo de 15 minutos de Lambda, y que la falla tarda 16× más.** Una corrida
normal son 5 min (33% del techo), pero **las dos corridas medidas con la red caída
tardaron 82 y 95 min, con 52 tickers** — con 127 serían ~3,5 h. Lambda las mata a los 15
min, y las mata **después de haber hecho trabajo parcial**, o sea justo cuando algo va
mal. Un diseño de "una Lambda para todo el harvest" es correcto el 95% de los días e
inútil el 5% que importa. Hay que **partir por lotes de tickers** (p. ej. 5 Lambdas de
~25) y ponerle techo de wall-clock por ticker. El costo de partir es cero: las
invocaciones sobran por 5.600×.

**7.2 — La NAT Gateway.** Una Lambda **dentro de una VPC** necesita NAT Gateway para
salir a internet: **~$32/mes + $0,045/GB**, y sola rompe el presupuesto 30 veces. Una
Lambda **fuera** de VPC tiene salida a internet gratis, y DynamoDB se accede por su API
pública. **El diseño no lleva VPC.** Es la trampa de costo más común y la más fácil de
pisar por copiar un tutorial.

**7.3 — Deriva del universo, otra vez.** El recolector necesita saber qué 127 tickers
mirar, y esa lista vive en `paper_watchlist` de la DB. Una lista estática en la nube se
desincroniza en cuanto agregás un ticker, y el síntoma es el mismo de la **tarea 70**:
no falla, recolecta creíblemente para el universo equivocado. La lista tiene que
**publicarse desde la app** en cada import, y el recolector tiene que declarar sobre
cuántos tickers corrió.

**7.4 — Créditos que vencen sin aviso.** Si la cuenta es nueva, los créditos tapan lo
que no es always-free durante hasta 6 meses. Un servicio armado sobre S3/EC2 va a
funcionar y costar $0 justo el tiempo suficiente para que nadie se acuerde. Es un
argumento más para quedarse **sólo** en always-free.

**7.5 — La clave de Finnhub sale de tu máquina.** Hoy `FINNHUB_API_KEY` vive en el
entorno de Windows. En la nube va a SSM Parameter Store (gratis; Secrets Manager cuesta
$0,40/secreto/mes y no hace falta). Es una key de free tier, pero igual: una sola copia,
rotable.

**7.6 — Un segundo recolector puede pisar al primero.** Con la app abierta *y* el
servicio andando, los dos harvestean. Para noticias no hay problema (UNIQUE en
`content_hash`). Para el consenso, sí — ver 6.2. Y aparte, duplica el pedido a Yahoo,
que es la fuente sensible al rate limit.

---

## 8. Recomendación

**Recomiendo un Raspberry Pi 5 (2-4 GB) en tu casa, corriendo el harvest que ya existe,
con el alcance recortado al snapshot de consenso diario.** Si no querés hardware, la
segunda es AWS always-free, y ahí sí no se avanza hasta tener el smoke test.

**Por qué el Pi, en orden de peso:**

1. **Elimina el único criterio que no se puede evaluar.** Todo lo demás en este doc está
   medido; (b) no, y no lo va a estar hasta desplegar. El Pi sale por la misma IP
   residencial que hace tres meses harvestea bien. No es que el riesgo esté controlado:
   **no está**.
2. **Corre `scripts/harvest_catalysts.py` tal cual.** AWS pide partir por lotes (§7.1),
   empaquetar, cambiar de almacenamiento y escribir un import. Un orden de magnitud más
   de trabajo, para resolver el mismo problema peor.
3. **Nadie te lo re-tarifa.** Oracle acaba de mostrar que "always free" es revocable
   (§4.5), y el free tier de 12 meses de tu cuenta ya venció sin que nadie avisara
   (§4.2). El hardware que comprás no cambia de precio después.
4. Cuesta **€50-90 una vez y ~US$2/año** de luz. Si tenés un NAS o una máquina vieja
   siempre prendida, cuesta **cero**: empezá por ahí antes de comprar nada.

**El alcance, y vale para las dos ramas:** empezar por **el snapshot de consenso diario
y nada más**. Es el 17% del volumen, una pasada por día, ~0,1 MB — y es **el 100% de la
pérdida irreversible** (§2). Las noticias, que son el trabajo caro y el riesgo de
timeouts, se recuperan solas hasta 7 días y se perdieron **una vez en tres meses**.
Mudarlas después, o no mudarlas nunca: la tabla de §2 dice que rinde poco. Recortado
así, el servicio es una corrida diaria de ~1-2 min contra 127 tickers, con una sola
fuente que validar.

**Cuándo elegiría AWS igual:** si no querés un aparato más en casa, o si te molesta que
la continuidad del dato dependa de tu luz y tu internet. En ese caso: Lambda **fuera de
VPC** + EventBridge Scheduler + DynamoDB + SSM Parameter Store (§4.1-4.2), y **el smoke
test va primero**. Si yfinance no responde desde AWS, esa rama se cae entera y no tiene
plan B: el consenso es 100% yfinance. Las salidas serían un proxy residencial (no es
$0) o comprar el consenso en otra fuente (Finnhub lo tiene en su tier pago) — las dos
son otra tarea y otra decisión.

**Contra GitHub Actions:** aun si el probe sale verde, no lo usaría para guardar. El
cron es *best-effort* (se retrasa 5-30+ min) y los artifacts retienen ≤90 días, que es
malo justamente para lo que hay que guardar: una serie diaria, sin huecos, para
siempre. Para **el probe** (§5) es perfecto, y ahí sí ya está escrito.

**Costo de no hacer nada:** 26% de las ruedas sin consenso, permanente y acumulativo.
En la ventana medida son 18 ruedas de 70; el desbloqueo de T-CAT-5b se corrió de Q2 a
Q3 una vez por esto.

---

## 9. Estado, y qué falta

**Contestado el 2026-09-14:**

- ✅ **Cuenta de AWS: anterior a julio de 2025.** Resuelve §4.2 — free tier de 12 meses
  vencido, queda sólo el always-free. El criterio (a) queda **cerrado**.
- ✅ **Probe desde datacenter: autorizado y escrito** (§5). Corre con el push que trae
  el workflow.
- ✅ **Evaluar hardware propio (Raspberry Pi):** pedido el mismo día, hecho en §4.4. Es
  lo que cambió la recomendación.

**Lo que falta:**

1. **El resultado del probe** (§5). Llega solo, con el push. Si sale **rojo**, la rama
   de nube se cae y el Pi queda como única opción; si sale verde, sigue sin decir nada
   definitivo sobre AWS, y lo que decide es §8.
2. **Tu decisión: Pi o AWS.** Si es Pi: ¿tenés ya un NAS o una máquina siempre prendida?
   Cambia el costo de €50-90 a cero y es lo primero que miraría.
3. **El smoke test desde AWS** — sólo si elegís esa rama. Una Lambda que baje
   `Ticker.news` y `earnings_estimate` de 5 tickers y reporte qué respondió.
4. **La tarea 203** (§6.2, §10) es prerrequisito de implementar **cualquiera** de las
   dos ramas, porque las dos agregan un segundo escritor a la tabla del consenso.

---

## 10. Hallazgos laterales (van al backlog, regla 6)

1. **`analyst_estimate_snapshots` no tiene UNIQUE y su dedup vive en código** (§6.2). La
   tabla hermana `news_events` sí lo tiene. Hoy no hay duplicados, pero el chequeo es
   *read-then-write*, no atómico, y compara el datetime exacto: cualquier segundo
   escritor que normalice `snapshot_date` distinto duplica en silencio. Es prerrequisito
   de esta tarea y defecto latente aunque la nube no se haga nunca.
2. **El harvest no tiene techo de duración** (§1, §7.1). Con la red caída, dos corridas
   medidas tardaron 82 y 95 min contra una mediana de 5, porque cada fuente de cada
   ticker agota su timeout. In-app sólo molesta (el gate de worker vivo evita que se
   apilen); en cualquier ejecución con límite de tiempo, es fatal.

---

## Anexo — cómo se midió

Los cinco scripts corrieron en lectura pura (`?mode=ro` sobre `finanzias.db`; los logs
sólo se leyeron). Ninguno escribió nada.

- **Volumen por tabla:** `COUNT(*)` + suma de `LENGTH(CAST(col AS BLOB))` de cada
  columna, agrupado por `DATE(fetched_at)`. `dbstat` no está compilado en este SQLite,
  así que los MB son **payload**, no páginas en disco (el archivo son 67,3 MB con
  índices y overhead).
- **Duración del harvest:** pares *"harvest starting"* / *"harvest done"* de
  `~/.finanzias/finanzias.log{,.1,.2,.archivo_pre_t78_20260907}`, que cubren
  2026-07-12 a 2026-09-14 sin hueco.
- **Cobertura de la app:** baldes de 15 min de RTH (10:30-17:00 ART = 9:30-16:00 ET) con
  al menos una línea de log.
- **Pérdida irreversible:** noticias por `published_at` (no por `fetched_at`) contra un
  umbral de "día flaco" = 20% de la mediana; consenso por `snapshot_date`.

**Un instrumento que hubo que tirar.** La primera versión del script de cobertura medía
"app abierta" como sesiones entre un *"Iniciando FinanzIAs"* y la última línea anterior
al siguiente — y **rellenaba los minutos intermedios**. Daba 53,8% de cobertura de RTH y
declaraba el corte del 25/07 al 08/08 como **"app abierta 24 h/día los 16 días"**, que
es lo contrario de lo que pasó: el 2026-07-27 el log no tiene **ni una línea**. El
número era limpio, plausible y falso. Los dos instrumentos que quedaron no interpolan
nada, y se cruzaron contra la DB (las ruedas con 0 baldes de log son las mismas que
tienen 0 filas recolectadas).

## Fuentes de los límites gratuitos

Los límites de AWS se verificaron contra las páginas de precios el 2026-09-14; los
marcados abajo dependen de la fecha de alta de la cuenta y **no** se pudieron verificar
contra la cuenta de Chapa, que todavía no existe o no se conoce (§9).

- [AWS Free Tier](https://aws.amazon.com/free/) · [términos](https://aws.amazon.com/free/terms)
- [Lambda pricing](https://aws.amazon.com/lambda/pricing/) — 1M req + 400.000 GB-s/mes
- [S3 pricing](https://aws.amazon.com/s3/pricing/) — **12 meses, no always-free**
- [EventBridge pricing](https://aws.amazon.com/eventbridge/pricing/) — 14M invocaciones/mes
- [CloudWatch pricing](https://aws.amazon.com/cloudwatch/pricing/) — 5 GB/mes de ingesta
- [AWS Free Tier en 2026: qué cambió](https://infratally.com/articles/aws-free-tier-2026/) — el corte del 2025-07-15
- [GitHub Actions free tier 2026](https://cicdcalculator.com/github-actions-free-tier) — público ilimitado, privado 2.000 min/mes
- [yfinance y los 429](https://github.com/ranaroussi/yfinance/discussions/2581) — por qué el scraping se bloquea

Hardware propio y el otro «always free» (§4.4, §4.5):

- [Raspberry Pi: consumo 2026, todos los modelos](https://raspberry.tips/en/raspberrypi-tutorials/raspberry-pi-power-consumption-update-2026-all-models-compared) — Pi 5 ~2,7-3,0 W idle; Zero 2 W ~0,7 W
- [Precios Raspberry Pi 2026](https://ecosistemastartup.com/raspberry-pi-2026-precios-suben-70-guia-de-compra/) — tres subidas entre nov-2025 y abr-2026
- [Oracle bajó a la mitad el always-free de Ampere A1, sin anuncio](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/) — vigente desde 2026-06-15, terminaciones desde el 2026-08-18
- [Oracle — Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) — política de reclamo de instancias ociosas
