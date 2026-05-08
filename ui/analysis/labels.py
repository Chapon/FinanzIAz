"""
Labels, color palette, and HTML tooltips for the Analysis tab.

These were originally inlined as ``TOOLTIPS``, ``_YAHOO_COLORS``,
``_YAHOO_LABELS_ES`` and the private ``_tt`` helper inside
``analysis_tab.py``. Centralising them here keeps the orchestrator file
focused on layout/wiring instead of presentation strings.
"""
from __future__ import annotations


# ── Yahoo-level display palette ──────────────────────────────────────────────
YAHOO_COLORS: dict[str, str] = {
    "Strong Buy":   "#22c55e",
    "Buy":          "#4ade80",
    "Hold":         "#fbbf24",
    "Underperform": "#fb923c",
    "Sell":         "#f87171",
}

YAHOO_LABELS_ES: dict[str, str] = {
    "Strong Buy":   "Compra Fuerte",
    "Buy":          "Comprar",
    "Hold":         "Mantener",
    "Underperform": "Vender",
    "Sell":         "Venta Fuerte",
}


# ── Indicator tooltips (rich HTML, displayed by SignalCard / overall badge) ──
TOOLTIPS: dict[str, str] = {
    "RSI": (
        "<b>RSI — Índice de Fuerza Relativa</b><br><br>"
        "Mide la velocidad y magnitud de los movimientos de precio en una escala de 0 a 100.<br><br>"
        "<b>Cómo interpretarlo:</b><br>"
        "• <span style='color:#f87171'>RSI &gt; 70</span> → Sobrecompra: el precio subió demasiado rápido, "
        "posible corrección a la baja.<br>"
        "• <span style='color:#4ade80'>RSI &lt; 30</span> → Sobreventa: el precio cayó demasiado rápido, "
        "posible rebote al alza.<br>"
        "• RSI entre 30 y 70 → Zona neutral, sin señal clara.<br><br>"
        "<b>Período estándar:</b> 14 días."
    ),
    "MACD": (
        "<b>MACD — Convergencia/Divergencia de Medias Móviles</b><br><br>"
        "Compara dos medias móviles exponenciales (EMA 12 y EMA 26) para detectar cambios de tendencia.<br><br>"
        "<b>Componentes:</b><br>"
        "• <b>Línea MACD</b>: diferencia entre EMA12 y EMA26.<br>"
        "• <b>Línea de señal</b>: EMA9 del MACD.<br>"
        "• <b>Histograma</b>: diferencia entre MACD y señal.<br><br>"
        "<b>Cómo usarlo:</b><br>"
        "• MACD cruza <i>por encima</i> de la señal → señal de <span style='color:#4ade80'>COMPRA</span>.<br>"
        "• MACD cruza <i>por debajo</i> de la señal → señal de <span style='color:#f87171'>VENTA</span>.<br>"
        "• Histograma en verde creciente → momentum alcista."
    ),
    "Bollinger Bands": (
        "<b>Bandas de Bollinger</b><br><br>"
        "Envuelven el precio con una banda superior e inferior basadas en la desviación estándar "
        "respecto a una media móvil de 20 períodos.<br><br>"
        "<b>Cómo interpretarlas:</b><br>"
        "• Precio toca la <b>banda inferior</b> → posible <span style='color:#4ade80'>rebote alcista</span>: "
        "el precio está estadísticamente barato.<br>"
        "• Precio toca la <b>banda superior</b> → posible <span style='color:#f87171'>retroceso bajista</span>: "
        "el precio está estadísticamente caro.<br>"
        "• Bandas muy juntas (<i>squeeze</i>) → se viene un movimiento fuerte, pero la dirección es incierta.<br><br>"
        "<b>La línea del medio</b> es la SMA20 y actúa como imán de precio."
    ),
    "Golden/Death Cross": (
        "<b>Golden Cross / Death Cross</b><br><br>"
        "Compara la media móvil simple de 50 días (SMA50) con la de 200 días (SMA200) "
        "para detectar cambios de tendencia de largo plazo.<br><br>"
        "<b>Señales:</b><br>"
        "• <span style='color:#4ade80'><b>Golden Cross</b></span>: SMA50 cruza <i>por encima</i> de SMA200 "
        "→ inicio de tendencia alcista de largo plazo. Señal muy confiable.<br>"
        "• <span style='color:#f87171'><b>Death Cross</b></span>: SMA50 cruza <i>por debajo</i> de SMA200 "
        "→ inicio de tendencia bajista de largo plazo. Señal de precaución.<br><br>"
        "<b>Limitación:</b> es un indicador rezagado — confirma tendencias ya en curso, "
        "no las predice con anticipación."
    ),
    "señal_general": (
        "<b>Señal General</b><br><br>"
        "Resumen ponderado de todos los indicadores técnicos, usando el sistema de "
        "5 niveles de Yahoo Finance.<br><br>"
        "• <span style='color:#22c55e'><b>● Compra Fuerte</b></span>: consenso alcista fuerte.<br>"
        "• <span style='color:#4ade80'><b>● Comprar</b></span>: mayoría alcista moderada.<br>"
        "• <span style='color:#fbbf24'><b>● Mantener</b></span>: señales mixtas o neutrales.<br>"
        "• <span style='color:#fb923c'><b>● Vender</b></span>: mayoría bajista moderada.<br>"
        "• <span style='color:#f87171'><b>● Venta Fuerte</b></span>: consenso bajista fuerte.<br><br>"
        "<i>No es asesoramiento financiero. Siempre considerá el contexto del mercado.</i>"
    ),
    "soporte": (
        "<b>Soporte</b><br><br>"
        "Nivel de precio donde históricamente el activo encontró demanda suficiente para "
        "detener su caída y rebotar.<br><br>"
        "Calculado como el mínimo de las últimas 60 velas."
    ),
    "resistencia": (
        "<b>Resistencia</b><br><br>"
        "Nivel de precio donde históricamente el activo encontró oferta suficiente para "
        "frenar su subida y retroceder.<br><br>"
        "Calculado como el máximo de las últimas 60 velas."
    ),
    "precio_actual": (
        "<b>Precio Actual</b><br><br>"
        "Último precio operado en el mercado para este ticker.<br>"
        "Se actualiza con caché de 5 minutos desde Yahoo Finance."
    ),
    "cambio_hoy": (
        "<b>Variación del Día</b><br><br>"
        "Cambio porcentual del precio respecto al cierre del día anterior.<br><br>"
        "• <span style='color:#4ade80'>Verde</span>: el precio subió hoy.<br>"
        "• <span style='color:#f87171'>Rojo</span>: el precio bajó hoy."
    ),
    "XGBoost ML": (
        "<b>XGBoost — Modelo de Machine Learning</b><br><br>"
        "Clasificador entrenado en cada análisis con los datos históricos del propio ticker.<br><br>"
        "<b>Features:</b> retornos (1/3/5/10/20 días), RSI y su tendencia de 5 días, "
        "histograma MACD y su aceleración, posición en Bandas de Bollinger, "
        "ancho del squeeze, ratio de volumen, volatilidad realizada, y ratios precio/SMA.<br><br>"
        "<b>Target:</b> ¿sube el precio en los próximos 5 días?<br><br>"
        "<b>Interpretación:</b><br>"
        "• &gt;75%: <span style='color:#22c55e'>Compra Fuerte</span> — patrones alcistas sólidos.<br>"
        "• 65-75%: <span style='color:#4ade80'>Comprar</span><br>"
        "• 35-65%: <span style='color:#fbbf24'>Neutral</span><br>"
        "• 25-35%: <span style='color:#fb923c'>Vender</span><br>"
        "• &lt;25%: <span style='color:#f87171'>Venta Fuerte</span> — patrones bajistas sólidos.<br><br>"
        "<b>Split de entrenamiento:</b> 80% histórico (entrenamiento) / 20% más reciente (validación).<br>"
        "<i>Requiere <code>pip install xgboost</code>.</i>"
    ),
    "Volumen": (
        "<b>Volumen — Acumulación / Distribución</b><br><br>"
        "Compara el volumen promedio en días alcistas vs bajistas "
        "en las últimas 10 sesiones.<br><br>"
        "<b>Señales:</b><br>"
        "• Vol. en días alcistas &gt; 1.5× días bajistas → "
        "<span style='color:#4ade80'>acumulación</span> (compradores institucionales).<br>"
        "• Vol. en días bajistas &gt; 1.5× días alcistas → "
        "<span style='color:#f87171'>distribución</span> (presión vendedora).<br>"
        "• Diferencia &lt; 1.5× → neutral.<br><br>"
        "<i>El volumen confirma (o contradice) los movimientos de precio.</i>"
    ),
    "regimen": (
        "<b>Régimen de Mercado</b><br><br>"
        "Clasifica el contexto actual del activo basándose en momentum de precio "
        "y posición respecto a medias móviles de largo plazo.<br><br>"
        "<b>Algoritmo:</b> scoring ponderado sobre retornos de 5, 20 y 60 días, "
        "más la posición del precio respecto a SMA50 y SMA200.<br><br>"
        "• <span style='color:#22c55e'><b>Alcista</b></span>: tendencia de fondo positiva — "
        "señales de compra son más confiables.<br>"
        "• <span style='color:#f87171'><b>Bajista</b></span>: tendencia de fondo negativa — "
        "señales de compra van contra la corriente; mayor riesgo.<br>"
        "• <span style='color:#fbbf24'><b>Lateral</b></span>: sin tendencia clara — "
        "señales técnicas son menos confiables.<br><br>"
        "El régimen <b>ajusta la probabilidad</b> del panel inferior."
    ),
}


def get_tooltip(key: str) -> str:
    """Return the HTML tooltip for ``key`` or an empty string if unknown."""
    return TOOLTIPS.get(key, "")
