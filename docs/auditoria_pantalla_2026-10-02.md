# Auditoría — F · pantalla — 2026-10-02

Tarea **261** (primera corrida del área, creada por la 260). Skill `auditoria`, categoría F. READ-ONLY.

## 1. Kill-criteria

**Congelado:** 2026-10-02, junto con los de `pantalla` y `cuentas`/`operacion` (los tres a la vez, antes de abrir el primer archivo de código), aprobado por Chapa con un «seguir».

**Contaminación declarada:** antes de congelar ya se había visto (tarea 260) que la caja y las posiciones de las cuentas 1 y 2 cuadran al centavo contra fills, comisiones y dividendos, que `reconcile_account` sólo expira pendientes, y que `ui/news_tab.py` abre la URL de la noticia con `QDesktopServices`. Nada más.

### Alcance

- **Alcance (lista):** las pantallas del `QStackedWidget` de `ui/main_window.py`: Home, Portfolio, Analysis, Leads, Alerts, Paper, Reports, Failed tickers, Settings, News, Metrics.
- **Afuera:** estética, layout y performance de la GUI, salvo que oculten un número. Motivo: no cambian ninguna decisión.

### Qué se busca

- **F1** un número cuya fuente vacía/vieja/equivocada se pinta como dato (`0`, `—`, último valor) sin decirlo.
- **F2** un rótulo que promete más de lo que mide.
- **F3** una selección por defecto (cuenta, ventana, benchmark) que no es la viva.
- **F4** un estado que queda trabado y no se re-arma.

### Barrido limpio (las dos direcciones)

- **Dirección 1 (lo mostrado es falso):** cada número visible en alcance tiene fuente identificada y, recalculado contra la DB en solo lectura, coincide.
- **Dirección 2 (lo verdadero no se muestra):** toda fuente que puede estar vacía o vieja tiene un aviso visible que lo dice.

## 2. Alcance real

**Mirado:**
- **Home:** `_resolve_account_id`, `load_paper_data`, `update_status` y la torta.
- **Paper:** la tabla de posiciones, con su precio, valor de mercado y P&L.
- **Metrics:** la tarjeta *VS SPY* con fuente vacía o vieja.
- **Reports:** de qué datos sale, y el `.html` del repo.
- **Todo `ui/`:**
  - un barrido AST de `suppress(Exception)` y `except: pass`;
  - los usos de `list_accounts`/`get_account(1)`.

**NO mirado a fondo:**
- **Pantallas enteras:** Analysis, Leads, Portfolio, Failed tickers, News y Alerts.
- **Settings, sólo en parte:** el cruce entre lo que muestra cada fila y el fallback con que la lee el motor no se pudo hacer, porque mi extractor de claves no encontró las listas de secciones. La 154 cerró el caso de flags leídos con un fallback no declarado, pero eso no se re-verificó acá.
- **Motivo:** el tamaño. Es la primera corrida del área y se priorizaron las pantallas que muestran plata.

El diferimiento va como tarea **267**.

## 3. Hallazgos

### [F-1] Home muestra la cuenta 1, cerrada, como si fuera la viva
Severidad: **MEDIUM** (la misma con que la 254 calificó el mismo defecto en Métricas) · Confianza: **ALTA** · Categoría: F3

**Ubicación:**
- `ui/home_tab.py:46-56`: `_resolve_account_id`, cuyo docstring dice *«prefers id=1 ("Sim Principal")»*.
- Lo usa `load_paper_data` (`:286-344`).

**Evidencia:**
- `get_account` no filtra por `is_active` (`paper_trading/account.py:86-91`), así que devuelve siempre 1.
- `refresh(portfolio_tab)` ignora el argumento.
- Ninguna señal le pasa la cuenta seleccionada.
- **Lo que muestra hoy** (cuenta 1, cerrada): equity **$49.257**, P/L **−1,49%** en rojo, **5** posiciones (SBUX, LRCX, MO, KO, CL), curva congelada en el 2026-07-01.
- **Lo que debería mostrar** (cuenta 2, viva): **$51.353**, **+2,71%**, **10** posiciones.

**Dos menores de la misma pantalla**, que van en la misma tarea:
- `update_status(..., 0)` (`:344`) pasa `n_alerts=0` fijo, así que la fila *Alertas* dice siempre *«Sin disparar»*.
- La torta *«Distribución de cartera»* y la sparkline de posiciones usan el **costo** (`shares × avg_cost`, `:338-341`), no el valor de mercado.
- Además, `load_paper_data` corre dentro de `suppress(Exception)` (`:195`, `:348`): si falla, Home se queda con los valores anteriores sin decir nada.

**Impacto:** la primera pantalla de la app pinta en rojo una cuenta que no opera desde julio.

**Verificación (`verificador`):** buscó que Home recibiera el id de otro lado, un test de la 254 que cubriera Home y un commit que lo arreglara. El último commit sobre `home_tab.py` es de lint (la 65).

**¿Por qué no antes?** (b) FUERA DE ALCANCE: el área no existía. Para la 254 también vale como lección: arregló dos de tres pantallas con el mismo patrón y no buscó el patrón en todo `ui/`. Es la regla de *claims* (*«las correcciones viejas se BUSCAN en todo el repo»*) aplicada a código.

**Acción:** tarea **264**.

**Remedio redefinido por Chapa (2026-10-02, después de publicar este informe):** el defecto es más ancho que *«la cuenta equivocada»*. Home **no debe mostrar paper trading en absoluto**, sino la cartera real **«Mis Acciones»**. El hallazgo queda igual (lo que Home muestra hoy no es lo que el usuario toma por cierto); lo que cambió es el arreglo, y la 264 se reescribió con ese alcance.

### [F-2] Paper pinta un precio faltante como «sin ganancia ni pérdida», en verde
Severidad: **LOW** · Confianza: **ALTA** · Categoría: F1

**Ubicación:** `ui/paper_tab.py:1394-1414`.

**Evidencia:** sin precio, la columna de precio muestra `—`, pero el valor de mercado pasa a ser el costo y el P&L queda `+$0.00` / `+0.00%` en **verde**.

**Impacto:** chico, porque el `—` está al lado. Pero los scans con *«N tickers sin precio»* existen (log del 2026-09-11 y del 2026-09-23).

**¿Por qué no antes?** (b).

**Acción:** tarea **268**.

### [F-3] `reports/dashboard_sim_principal.html` es una foto de mayo de la cuenta cerrada, versionada y sin uso
Severidad: **LOW** · Confianza: **ALTA** · Categoría: F1

**Evidencia:**
- Último commit `9b4bc00` (2026-05-27).
- Ninguna referencia en `*.py` ni en `*.md`.
- El dashboard vivo es otro: `C:\Users\chapa\Documents\Claude\Artifacts\finanzias-dashboard\index.html`, refrescado hoy con la cuenta 2.

**Impacto:** quien abra el del repo ve la cuenta 1 en mayo.

**¿Por qué no antes?** (b).

**Acción:** tarea **268**.

## 4. Barrido limpio en lo demás

- **Metrics:** con SPY vacío o atrasado muestra `—` y *«SPY desactualizado (hasta DD/MM)»*, que es lo que fijaron la 22 y la 218. La cuenta por defecto es la viva desde la 254.
- **Paper:** la cuenta por defecto es la viva desde la 254.
- **Reports** genera PDF/Excel de la **cartera real** (`Portfolio`/`Position`), no de la paper: no le aplica F3.
- **El barrido AST:** fuera de Home, los `suppress` y `except: pass` de `ui/` son cosméticos (gráficos, tooltips, toasts). Ninguno envuelve una carga de datos.

## 5. Hallazgos rechazados

- Ninguno. La extracción de claves de Settings no se convirtió en hallazgo: el instrumento falló (no encontró las listas) y por eso Settings quedó como **no mirado**, no como limpio.

## 6. Limitaciones

- Es la primera corrida del área, con muestreo declarado. La 267 completa el resto.
- La fase adversarial la hizo el agente `verificador`, independiente, sobre F-1. F-2 y F-3 son LOW y no la requieren.

## 7. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| F-1 | 264 |
| F-2 | 268 |
| F-3 | 268 |
| diferimiento (pantallas no barridas) | 267 |

