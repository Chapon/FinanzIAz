"""Acceso a columnas de un DataFrame que no se rompe con un frame de una fila.

**Por qué existe — Tarea 125.** El idiom que este repo usaba era
``df["Close"].squeeze()``, y ``squeeze()`` devuelve un **escalar** cuando el frame
tiene **una sola fila**. Ahí todo lo que viene después —``.diff``, ``.rolling``,
``.ewm``, ``.pct_change``, ``.replace``— revienta con ``AttributeError`` en pleno
scan. Medido antes de arreglarlo: con un frame de una barra explotan los **seis**
indicadores de ``technical`` y también ``get_cached_indicators``, que es el que
llama ``analyze()``.

``squeeze`` estaba ahí por otra razón, y esa razón sigue siendo válida: aplanar el
caso de una columna **duplicada** (yfinance las emite). Eso se resuelve tomando la
primera columna, sin el efecto colateral sobre el frame de una fila.

**Por qué en un módulo propio.** La tarea 19 ya había diagnosticado esto y lo
centralizó en ``garch_signals._close_series`` — **sólo para ese módulo**. Quedaron
**26** llamadas crudas en cinco módulos (``technical`` 10, ``ml_signals`` 11,
``meta_labeling`` 3, ``regime_detector`` 1, ``catalyst_reaction`` 1). Es el patrón
que la tarea 99 dejó escrito: *la población del arreglo se definió por dónde se
encontró el defecto, no por la propiedad que lo hace un defecto*. Un módulo hoja
—sólo pandas— evita el import circular que tendría meterlo en cualquiera de los
cinco.

``data/quality._serie`` es una copia deliberada y **no** importa de acá: ``data/``
no depende de ``analysis/``, e invertir esa dirección por cinco líneas sería peor
que duplicarlas.
"""

from __future__ import annotations

import pandas as pd

__all__ = ["series"]


def series(df: pd.DataFrame, col: str) -> pd.Series:
    """La columna ``col`` **siempre** como Series, aunque el frame tenga una fila.

    Con una columna duplicada devuelve la primera, que es lo que ``squeeze`` hacía
    bien. Con una sola fila devuelve una Series de largo 1 en vez de un escalar,
    que es lo que ``squeeze`` hacía mal.
    """
    s = df[col]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return s if isinstance(s, pd.Series) else pd.Series(s)
