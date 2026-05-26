# Rediseño UI — Estética "Fuse Admin" sobre PyQt6

> **Decisión de alcance (2026-05-25):** rediseñar la app de escritorio **PyQt6 actual** (no migrar a React). Se replica la *estética* de la plantilla Fuse React Admin usando QSS + matplotlib, y se mapea el contenido demo a **datos reales de FinanzIAs**. No se crea proyecto web ni API nueva.

## 1. Por qué esta traducción

La spec original describe un stack web (React + MUI + Recharts). FinanzIAs es una app de escritorio en **PyQt6** (56 imports `from PyQt6`), con tema oscuro propio en `ui/styles.py` y gráficos en **matplotlib**. Por lo tanto cada elemento de la spec se traduce a su equivalente PyQt6, y las métricas demo (Conversion / Impressions / Sessions by device) se reemplazan por métricas del motor de paper-trading.

Mapa de equivalencias de stack:

| Spec Fuse (web) | Equivalente FinanzIAs (PyQt6) |
|---|---|
| React components | `QFrame`/`QWidget` + clases en `ui/widgets.py` |
| Material UI | QSS centralizado en `ui/styles.py` (`DARK_THEME`, `PALETTE`) |
| Recharts / Chart.js | matplotlib embebido (`ui/chart_widget.py`, `ui/paper/equity_chart.py`) |
| Sidebar colapsable | `ui/sidebar.py` (ya existe, 232 líneas) |
| Header delgado | topbar en `ui/main_window.py` (`page_label`, `market_label`, `user_chip`) |
| Routing | `QStackedWidget` con 8 páginas en `main_window.py` |

## 2. Estado actual (punto de partida)

- **Tema:** negro profundo `#0a0b0d`, acento **verde** `#4ade80` ("IQON-inspired"). Definido en `ui/styles.py` (`PALETTE`, `DARK_THEME`, 462 líneas).
- **Layout:** sidebar persistente + `QStackedWidget`. Páginas: Home(0), Portfolio(1), Analysis(2), Alerts(3), PaperTrading(4), Reports(5), FailedTickers(6), Settings(7).
- **Widgets reutilizables** en `ui/widgets.py`: `CircularGauge`, `MiniProgressBar`, `ToggleSwitch`, `StatusDot`, `MetricCard`, `StatusRow`, `GaugeCard`, `FeatureCard`, `SettingsRow`, `NumericSettingsRow`, `ChoiceSettingsRow`, `SignalBadge`, `SectionHeader`, `HSeparator`.
- **Home actual** (`ui/home_tab.py`): `WelcomeCard` (status rows) + `PlatformSettingsCard` + cards de métricas/feature shortcuts. **No** tiene hero area-chart ni grilla de KPIs con mini-gráficos ni donut.

## 3. Cambios de diseño visual

### 3.1 Paleta (objetivo Fuse)
Migrar de la paleta verde a carbón + acentos pastel. Cambiar **solo** en `ui/styles.py` para que se propague a toda la app:

| Token | Actual | Objetivo Fuse |
|---|---|---|
| `BG_BASE` | `#0a0b0d` | `#121212` (gris muy oscuro) |
| `BG_SIDEBAR` | `#0f1012` | `#1a1a1a` (gris carbón) |
| `BG_CARD` | `#111318` | `#1e1e1e` |
| Acento primario | verde `#4ade80` | **cian pastel** `#22d3ee` |
| Positivo / negativo | verde / `#f87171` | verde suave / **rojo suave** `#fb7185` |
| Acento secundario | — | **naranja** `#fb923c` |

> Nota: el verde puede conservarse como color "positivo P/L" si se prefiere; lo que cambia es el **acento de navegación/branding** a cian. Confirmar con el usuario antes de tocar semántica de colores P/L.

### 3.2 Tipografía
Mantener sans-serif moderna (ya usa `'Segoe UI','Inter'`). Reforzar jerarquía por **peso + opacidad** (text1/text2/text3 ya existen en `PALETTE`).

## 4. Componentes nuevos a construir

Todos como clases nuevas en `ui/widgets.py` (o un módulo `ui/charts/`), reutilizando matplotlib ya presente.

1. **`AreaChartHero`** — gráfico de área full-width con degradado bajo la línea.
   - **Dato real:** curva de equity de la cuenta `Sim Principal` (id=1) desde la tabla `paper_equity_snapshots` (modelo `PaperEquitySnapshot` en `paper_trading/models.py`).
   - Eje X temporal, degradado del color de acento hacia transparente.

2. **`KpiCard`** (variante de `MetricCard`) — número grande + mini-gráfico debajo. Tres instancias en una fila:
   - **"P/L Total"** → % y valor; mini area-chart de equity reciente.
   - **"Operaciones"** → conteo abreviado (ej. `87` trades); mini bar-chart de trades por día (`paper_orders` / modelo `PaperOrder`).
   - **"Posiciones abiertas"** → número; mini "picos" de exposición por posición (`paper_positions`, vía `paper_trading/account.get_positions(account_id)`).

3. **`DonutChart`** — dona para **"Distribución de cartera"** (reemplaza "Sessions by device").
   - **Dato real:** allocation por ticker (o por sector) de posiciones abiertas, con leyenda y porcentajes. Las posiciones y su market value salen de `paper_trading/account.get_positions(1)` (campos `shares`, `avg_cost`, market value calculado).
   - Ej. leyenda: `AAPL 42.8% · MSFT 31.1% · resto 26.1%`.

## 5. Reestructura del Home (`ui/home_tab.py`)

Nuevo layout vertical con scroll (ya hay `QScrollArea`):

```
┌────────────────────────────────────────────┐
│  AreaChartHero (equity, full-width)          │
├──────────────┬──────────────┬───────────────┤
│ KpiCard P/L  │ KpiCard Ops  │ KpiCard Posic. │   ← fila grilla KPIs
├──────────────┴──────────────┼───────────────┤
│ WelcomeCard / status         │ DonutChart    │
│ (se conserva)                │ distribución  │
└──────────────────────────────┴───────────────┘
```

## 6. Sidebar y Header

- **Sidebar** (`ui/sidebar.py`): asegurar comportamiento **colapsable** (íconos lineales + perfil con avatar circular arriba). Verificar si ya colapsa; si no, agregar toggle.
- **Header** (`ui/main_window.py`): barra delgada con buscador, notificaciones y utilidades. Ya hay `market_label` + `user_chip`; agregar campo de búsqueda e ícono de notificaciones si se quiere fidelidad con Fuse.

## 7. Fuentes de datos (mapeo demo → real)

| Card Fuse (demo) | Métrica FinanzIAs | Origen |
|---|---|---|
| Hero area chart | Curva de equity | `paper_equity` / `equity_snapshot` (cuenta id=1) |
| Conversion | P/L total % | `paper_equity` (último vs inicial $50k) |
| Impressions (87k) | Nº de operaciones | `paper_orders` |
| Visits | Posiciones abiertas | `paper_positions` |
| Sessions by device (donut) | Distribución de cartera | `paper_positions` agregado por ticker/sector |

## 8. Criterios de aceptación

1. La app sigue arrancando (`main.py`) sin romper navegación del `QStackedWidget`.
2. Paleta carbón + acento cian aplicada desde `ui/styles.py` (cambio centralizado, no hardcodeos dispersos).
3. Home muestra: hero area-chart de equity, fila de 3 KPIs con mini-gráficos, y donut de distribución — **con datos reales**, no placeholders.
4. Sidebar colapsable funcional con perfil arriba.
5. Sin regresiones de tests existentes (`pytest`). Charts nuevos con al menos un smoke test de construcción de widget.

## 9. Fuera de alcance

- Migración a React/MUI/web (descartado).
- API HTTP sobre `finanzias.db`.
- Cambiar semántica de colores P/L sin confirmación.

## 10. Referencia

Diseño base: plantilla **Fuse React Admin** (dark, modular, card-based). Solo se toma como **referencia estética**; la implementación es 100% PyQt6.
