# Auditoría — pantalla (lo que la 261 no barrió) — 2026-10-02

Tarea **267**. READ-ONLY. Kill-criteria congelado en `docs/auditoria_tanda_killcriteria_2026-10-02.md` §5.

## 1. Alcance real

**Mirado:**
- **Portfolio:** tabla, tarjetas de totales y dividendos (`ui/portfolio_tab.py:438-598`).
- **Analysis:** la barra de probabilidad, su tooltip y el tooltip de XGBoost (`ui/analysis_tab.py:250-440`, `ui/analysis/labels.py:110-130`).
- **Failed tickers:** el registro en la DB contra el universo vivo y las carteras.
- **Alerts:** estados y alcance por cartera.
- **Leads:** rótulos y estados de error.
- **News:** sólo el rótulo, porque la arreglaron hace dos días la 255, la 257 y la 258.
- **Settings:** el cruce de cada toggle contra quién lo lee. El extractor AST se validó contra una clave conocida (`paper_min_holding_minutes`) antes de creerle; encontró 24 claves.

**NO mirado a fondo:**
- News, más allá del rótulo. Motivo: tres tareas la tocaron en los últimos dos días y su verificación está en esas tareas.
- Leads, número por número contra Yahoo. Motivo: muestra el consenso tal cual, con su propio cache de 6 h.

## 2. Hallazgos

### [P-1] Las tarjetas de totales de Portfolio valúan al costo, sin avisarlo, una posición sin precio
Severidad: **MEDIUM** · Confianza: **ALTA**

**Ubicación:** `ui/portfolio_tab.py:565-568`: `quantity × (precio si existe, si no avg_buy_price)`.

**Evidencia:** la tabla muestra `—` en el precio, el valor y el P&L de esa fila (`:458-503`), pero las tarjetas *Valor total*, *P&L* y *%* suman la posición **al costo**, es decir, con P&L cero, y no dicen que falta un precio.

**Impacto:** el número titular de la cartera real se ve completo cuando no lo está. La **264** va a llevar estas cifras a Home.

**¿Por qué no antes?** (c-alcance): la 261 dejó Portfolio afuera, declarado.

**Acción:** que las tarjetas digan *«N sin precio»* y no los valúen en silencio, o que los excluyan diciéndolo.

→ tarea **281**.

### [P-2] *«Dividendos cobrados»* es una estimación que cuenta dividendos de acciones que todavía no se tenían
Severidad: **LOW** · Confianza: **ALTA**

**Ubicación:**
- `ui/portfolio_tab.py:413`: una sola fecha por posición, `purchase_date or created_at`.
- `:463` y `:573`: el dividendo por acción desde esa fecha, por la cantidad **actual**.

**Razonamiento:** cuando se suman acciones a una posición, `ui/dialogs.py:301` actualiza la cantidad y conserva la primera fecha. Los dividendos de las acciones nuevas se cuentan desde la primera compra.

**Impacto:** sobreestima el P&L total en las posiciones compradas en tramos. El rótulo dice *cobrados*.

**Acción:** calcular por transacción (cada compra desde su fecha) o rotular *«estimados»*.

→ tarea **281**.

### [A-1] La barra de Analysis presenta un número no validado como *«Probabilidad cuantitativa de compra»*
Severidad: **MEDIUM** · Confianza: **ALTA**

**Ubicación:**
- `ui/analysis_tab.py:254-261`: el tooltip dice *«zona de compra probable»* y *«zona de venta probable»*.
- `:409-440`: el rótulo es *«▲ Compra 72%»*.
- `ui/analysis/labels.py:110-125`: el tooltip de XGBoost.

**Razonamiento:**
- Es la forma de la 255: el rótulo promete una medición que no existe. El número nunca se validó como probabilidad, porque no hay medición de calibración contra el retorno.
- La medición más cercana (la 73, `docs/buyscore_fwd5_t73_2026-09-01.md`) no detectó relación con el retorno a 5 días: r = −0,05, n = 85.
- El tooltip de XGBoost describe un *«split de entrenamiento 80/20»*, cuando `analysis/ml_signals.py` hace walk-forward con `TimeSeriesSplit` y calibración isotónica.
- Los umbrales del tooltip (75/65/35/25) no son los de la barra (65/55/45/35).

**Impacto:** quien mira Analysis lee *«72% de compra»* como una probabilidad, y no lo es.

**¿Por qué no antes?** (c-alcance), Analysis afuera en la 261. Pero la **255** arregló este mismo defecto en News sin buscarlo en las otras pantallas: es la lección de la 254 y la 264 una vez más.

**Acción:**
1. Rotular la barra como lo que es (un puntaje de consenso de indicadores) y sacar *«probable»* hasta que una medición lo sostenga.
2. Corregir el tooltip de XGBoost (método y umbrales).

→ tarea **282**.

### [ST-1] Tres toggles no hacen nada aunque su rótulo promete una conducta
Severidad: **LOW** · Confianza: **ALTA**

**Evidencia** (`git grep` del nombre de la clave en todo el código, sin tests ni el schema):
- **`notif`**, *«Notificaciones al disparar alertas — muestra una notificación cuando una alerta de precio se activa»*: sólo lo lee la tarjeta de Home (`ui/home_tab.py:149`), que repite el toggle. Ningún código de alertas lo consulta: **apagarlo no apaga nada**.
- **`pre_market`**, *«Mostrar precios pre/post mercado»*: **ningún lector**.
- **`realtime`**, *«Precios en tiempo real»*, de la tarjeta de Home (`:170`): **ningún lector**, y no está en el schema.
- (`perf_log` tampoco hace nada, pero su texto lo dice: *«función futura»*.)

**Acción:** cablearlos o sacarlos. Un toggle que no hace nada es un rótulo que miente.

→ tarea **283**.

## 3. Barrido limpio en lo demás

- **Portfolio, tabla:** un precio faltante es `—` en precio, valor y P&L, sin ceros inventados. El precio promedio sale de las transacciones (cuadrado en `docs/auditoria_cuentas_real_2026-10-02.md`).
- **Failed tickers:** los 8 registrados (`ACENTURE`, `BRK_B`, `BF_B`, `PFE1`, `K`, `LRXC`, `LQT`, `LKT`) son símbolos mal escritos o deslistados. **Ninguno** está en la watchlist viva, en la cartera paper ni en las carteras reales, así que `get_failing_set()` no le quita precio a nadie que importe.
- **Alerts:** tres estados explícitos (activa, pausada, disparada; ALRT1 y la 227), chequeo por cartera (`check_alerts(self._portfolio_id)`).
- **Leads:** se presenta como *«consensus de analistas»*, se escanea a mano, y dice si falla la carga del universo o el scan.
- **Settings:**
  - de las 24 claves, las que lee el motor muestran el mismo valor que el motor recibe: todas existen en el settings vivo o en el schema, así que ningún fallback del código entra en juego;
  - los demás toggles tienen lector real: `confirm_sell` → `dialogs.py:496`, `pdf_dark`/`tx_history` → `reports_tab.py`, `sma_cross` → `analysis/worker.py:44`, `bb` → `analysis_tab.py:650`, `auto_refresh`/`default_home` → `main_window.py`, y `rsi_alerts` dispara el escáner desde `settings_tab.py:648`.

## 4. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| P-1 | 281 |
| P-2 | 281 |
| A-1 | 282 |
| ST-1 | 283 |
