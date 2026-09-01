"""PITROLL (tarea 69) — la ventana de los artefactos RUEDA, y contar filas no lo ve.

Al refrescar un artefacto `10y`, el frame **suelta barras por la cabeza y agrega
por la cola**: `len(df)` casi no se mueve mientras las **fechas** cambian. El store
de señales PIT, en cambio, **acumula** fechas de ventanas anteriores, así que
termina con *más* filas de las que el frame necesita.

Con eso, la guarda vieja —`prev["complete"] and len(rows) >= n - warmup`— decía
**"ya completo — se saltea"** justo cuando peor estaba. Medido el 2026-09-01 sobre
AAPL después del refresh de la tarea 30: `len(rows)=2284` contra `n-warmup=2263`
⇒ *completo*, con **17 fechas faltando**. El `--dry-run` tenía el mismo defecto en
su estimación (`max(0, len(df) - warmup - have)` daba **negativo** ⇒ 0 pendientes).

El loop interno **ya** iteraba por fechas (`if iso in rows: continue`): lo que
estaba mal era la guarda que no lo dejaba correr. Estos tests fijan el caso que se
le escapaba, que es exactamente el que produjo el bug.
"""

from __future__ import annotations

import pandas as pd

from scripts.precompute_pit_signals import pending_dates


def _frame(desde: str, n: int) -> pd.DataFrame:
    idx = pd.bdate_range(desde, periods=n)
    return pd.DataFrame({"Close": [100.0 + i for i in range(n)]}, index=idx)


def _rows(desde: str, n: int) -> dict:
    return {d.strftime("%Y-%m-%d"): ["HOLD", None] for d in pd.bdate_range(desde, periods=n)}


def test_a_rolled_window_with_MORE_rows_than_needed_still_has_gaps():
    """**El caso real.** El store tiene más filas que `n - warmup` —porque acumuló
    fechas de ventanas viejas— y sin embargo le faltan las últimas. La guarda por
    cantidad decía "completo"; la de fechas encuentra el hueco."""
    warmup = 5
    df = _frame("2026-02-02", 40)  # ventana nueva
    rows = _rows("2026-01-05", 45)  # ventana vieja: MÁS filas, otras fechas

    assert len(rows) > len(df) - warmup  # la guarda vieja habría dicho "completo"
    faltan = pending_dates(df, rows, warmup)
    assert faltan  # y sin embargo faltan
    assert faltan[-1] == df.index[-1].strftime("%Y-%m-%d")


def test_the_gap_is_exactly_the_tail_the_refresh_added():
    """Lo que falta es la **cola**, que es lo que el refresh agrega. Nada más: las
    fechas viejas que el store trae de más no son un problema, son historia."""
    warmup = 0
    df = _frame("2026-01-05", 30)
    rows = _rows("2026-01-05", 25)  # el store se quedó 5 ruedas atrás
    assert pending_dates(df, rows, warmup) == [d.strftime("%Y-%m-%d") for d in df.index[25:]]


def test_a_store_that_really_covers_the_frame_has_nothing_pending():
    """La otra mitad: el incremental tiene que seguir salteando lo que ya está, o
    recomputar de cero cuesta ~5,5 h."""
    df = _frame("2026-01-05", 30)
    assert pending_dates(df, _rows("2026-01-05", 30), 0) == []
    assert pending_dates(df, _rows("2026-01-05", 30), 10) == []


def test_the_warmup_prefix_is_never_pending():
    """Las primeras `warmup` barras no se evalúan nunca — pedirlas sería inventar
    trabajo que el barrido no hace."""
    df = _frame("2026-01-05", 30)
    assert pending_dates(df, {}, 10) == [d.strftime("%Y-%m-%d") for d in df.index[10:]]


def test_an_empty_store_needs_the_whole_frame():
    df = _frame("2026-01-05", 12)
    assert len(pending_dates(df, {}, 0)) == 12


def test_the_guard_and_the_estimate_use_THE_SAME_function():
    """El `--dry-run` decía **0 pendientes** con 2.062 barras faltando porque tenía
    su propia cuenta. Que los dos pasen por `pending_dates` es lo que impide que
    vuelvan a divergir — mismo criterio con el que la 62 subió `changed_exits` y la
    63 hizo que los dos guards decidieran con la misma función."""
    from pathlib import Path

    txt = (Path(__file__).resolve().parent.parent / "scripts" / "precompute_pit_signals.py").read_text(
        encoding="utf-8"
    )
    assert txt.count("pending_dates(") >= 3  # la definición + la guarda + la estimación
    assert "len(df) - args.warmup - have" not in txt  # la cuenta vieja no volvió


def test_the_SIBLING_precompute_has_the_same_guard():
    """El mismo defecto estaba **copiado** en `precompute_pit_risk_score.py`, línea
    por línea. Arreglar uno solo habría dejado el store de riesgo atrasado con el de
    señales al día — y encima sin nadie que lo notara, porque los dos dirían
    "completo"."""
    from pathlib import Path

    txt = (Path(__file__).resolve().parent.parent / "scripts" / "precompute_pit_risk_score.py").read_text(
        encoding="utf-8"
    )
    assert "pending_dates(df, rows, warmup)" in txt
    # la guarda vieja no volvió **como código** (el comentario sí la cita, a
    # propósito: quien lea el arreglo tiene que ver qué decía antes)
    assert 'prev.get("complete") and len(rows) >=' not in txt
