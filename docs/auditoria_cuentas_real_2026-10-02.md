# Auditoría — cuentas: la cartera real — 2026-10-02

Tarea **273**, primera corrida de la cartera real dentro de `cuentas` (ampliada por la 271). READ-ONLY. Kill-criteria congelado en `docs/auditoria_tanda_killcriteria_2026-10-02.md` §2.

## 1. Alcance real

**Mirado:**
- `portfolios`, `positions` y `transactions` de la DB viva, abierta en solo lectura.
- Todos los caminos que escriben `Position` o `Transaction` en `ui/`, `data/`, `database/` y `paper_trading/`:
  - `ui/dialogs.py`: alta, venta y edición de ticker;
  - `ui/import_dialog.py`: importación de CSV;
  - el cruce paper→real de `ui/paper/real_portfolio.py`, que abre esos mismos diálogos desde `ui/paper_tab.py:1215/1231`.
- La relación `Position.transactions` de `database/models.py`.

**NO mirado:**
- El parser de CSV renglón por renglón contra formatos de broker reales. Motivo: no hay un CSV real versionado para probarlo. Queda dicho, sin tarea: el import escribe su transacción y promedia bien, que es lo que decide el cuadre.

## 2. Hallazgos

### [R-1] Vender entera una posición real borra su compra, su ticker y su costo, y deja la venta huérfana e invisible
Severidad: **HIGH** (bajada desde CRITICAL por el `verificador`: es latente, nunca pasó) · Confianza: **ALTA**

**Ubicación:**
- `ui/dialogs.py:515-529` (`SellPositionDialog`): agrega la `Transaction` SELL y, si la cantidad vendida es toda, hace `session.delete(pos)`.
- `database/models.py` (`Position.transactions`): `relationship(..., cascade="all, delete-orphan")`.

**Evidencia** (corregida por el `verificador`, que atacó el instrumento):
- Mi reproducción usaba una sesión con `autoflush=True` y daba 0 posiciones y 0 transacciones.
- La app usa `sessionmaker(autoflush=False, expire_on_commit=False)` (`database/models.py:100`), y con esa configuración el resultado es **0 posiciones y una sola transacción, la SELL, huérfana**: su `position_id` apunta a una posición que ya no existe.
- El BUY se borra por la cascada. Con él se pierden el ticker, el `avg_buy_price`, la fecha de compra y las notas.
- La SELL huérfana es **invisible**: `reports/excel_report.py:206-213` y `:252-259` filtran por las posiciones que existen.
- No hay `PRAGMA foreign_keys` en el repo, así que la fila viola la FK sin que nada lo note. Si algún día se prende `foreign_keys`, el huérfano rompe.

**En la DB viva:** 29 transacciones, todas BUY, y `max(id) = count = 29` tanto en `transactions` como en `positions`. **Nunca se borró una posición**, así que todavía no se perdió nada real: el defecto es latente. Por eso el `verificador` lo bajó a HIGH. El diseño muestra que preservar las transacciones era la intención: el docstring de `EditTickerDialog` las conserva a propósito.

**Razonamiento:** el código existe así desde el commit inicial (`3438b85`, 2026-04-29). Nada lee las ventas reales: `grep` de `"SELL"` en `reports/`, `ui/portfolio_tab.py` y `database/` da sólo el escritor. O sea que el P&L realizado de la cartera real **no existe en ningún lado**, y el registro que lo permitiría calcular se destruye en la venta total.

**Impacto:** se pierde el registro de lo que se pagó y a cuánto se vendió, que es justo lo que hace falta para el P&L realizado y para impuestos. Desde la 264, además, Home va a mostrar esta cartera.

**¿Por qué no antes?** (b) FUERA DE ALCANCE: la cartera real no estaba en ningún área hasta la 271.

**Acción:**
1. La venta total no borra: deja la posición en cantidad 0, o la archiva, con sus transacciones.
2. Las vistas filtran las posiciones en cero.
3. Revisar que ningún otro `delete` deje transacciones huérfanas con las FK apagadas.

→ tarea **277**.

## 3. Barrido limpio en lo demás

- **Cuadre:**
  - las 29 posiciones cuadran en cantidad con sus transacciones;
  - el `avg_buy_price` de cada una es el VWAP de sus compras (diferencia 0);
  - ninguna posición en cero o negativa, ninguna transacción huérfana.
- **Escritores:** alta (`dialogs.py:301-323`), importación (`import_dialog.py:431-453`) y venta escriben su `Transaction`; la importación promedia el precio igual que el alta. `EditTickerDialog` cambia sólo el símbolo.
- **Cruce paper→real:** no tiene escritor propio. Elige la cartera o la posición y abre los mismos diálogos, así que hereda su conducta, R-1 incluido.

## 4. Fase adversarial

La hizo el agente `verificador`, independiente. Corrigió el **instrumento**: la reproducción tenía otra configuración de sesión que la app, y eso cambiaba qué se borra. Mantuvo el núcleo (se pierde la compra y la venta queda invisible) y bajó la severidad a HIGH, porque nunca pasó en la DB viva. Se buscaron y no se encontraron: otro camino de venta (`portfolio_tab.py:697/753`, `paper_tab.py:1241` usan el mismo diálogo) y otro registro de las ventas.

## 5. Mapeo hallazgo → tarea

| hallazgo | tarea |
|---|---|
| R-1 | 277 |
