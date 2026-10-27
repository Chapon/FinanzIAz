# FinanzIAs

Aplicación de escritorio para seguimiento de cartera de inversión, paper trading y análisis técnico/cuantitativo.

## Características

- **Portafolio**: gestión de posiciones, transacciones y cálculo de P&L con datos de Yahoo Finance.
- **Análisis técnico**: indicadores (RSI, MACD, Bollinger, etc.) calculados con pandas puro, modelos GARCH y señales basadas en ML.
- **Paper trading**: motor de simulación con scheduler en background, watchlist, órdenes pendientes y curva de equity.
- **Alertas**: alertas de precio configurables.
- **Reportes**: exportación a Excel (`openpyxl`) y PDF (`reportlab`).
- **UI**: PyQt6 con tema oscuro estilo IQON.

## Stack

- Python 3.10+ / 3.13
- PyQt6, SQLAlchemy (SQLite), pandas, matplotlib, mplfinance
- yfinance, hmmlearn, arch, reportlab, openpyxl

## Instalación

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.lock
abrir_app.bat
```

El `.venv` es el entorno del lock y del CI (tarea 401).

## Estructura

```
FinanzIAs/
├── main.py                 # Punto de entrada
├── database/               # Modelos SQLAlchemy
├── data/                   # yfinance + import CSV
├── analysis/               # Indicadores, GARCH, ML, backtest
├── paper_trading/          # Motor de simulación
├── alerts/                 # Alertas de precio
├── reports/                # Exportadores Excel/PDF
├── config/                 # Settings manager
└── ui/                     # PyQt6 (tabs, widgets, estilos)
```
