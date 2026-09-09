"""Tarea 139 (XPERIOD-COLA) — el borde derecho deja de recortarse.

El bloque de diseño de la T110 enuncia el principio y nombra el mecanismo: *«la fuente
de verdad tiene que ser **independiente del cohorte que se chequea**. La que hay sin
red y sin dependencias nuevas: **el mismo ticker en otro período**»*.
``cross_period_gaps`` lo implementaba y después se recortaba a sí mismo:

    hi = min(hi_p, max(otras))   # ← descarta todo lo que el hermano tenga DESPUÉS

**La justificación vale para un borde y no para el otro.** *«Fuera del solape la
ausencia no es un hueco, es que el frame no llega»* es cierto del lado **izquierdo**
—un `2y` no llega diez años atrás— y **falso del derecho**: un hermano con barras más
nuevas no es un frame que no llega, es **evidencia directa de que este frame está
atrasado**. Que es exactamente el dato que la T110 declaró estar buscando.

**Medido el 2026-09-09 sobre el cohorte real:** los 127 tickers del universo vivo
tenían el `2y` al **2026-09-08** y el `10y` al **2026-09-01**, y la función reportaba
**cero huecos**. Des-recortada, acusa a **125** (los otros dos son AVB, exento, y el
que no tiene segundo frame). La evidencia estaba en el disco y el guard la tiraba.

**Dos decisiones de alcance, y las dos son deliberadas:**

1. **La cola NO aborta.** Si entrara al ``strict``, los 26 lectores del cohorte
   fallarían **hoy** — y ésta es una tarea de gate técnico que no re-corre ni
   re-publica nada. Que un cohorte uniformemente atrasado **falle** es la decisión de
   la tarea **140**, que tiene dos caminos y es de Chapa.
2. **La excepción de refresh exime la cola y NO el interior.** ``AVB`` está viejo
   **a propósito** (tarea 63: refrescarlo lo pondría a la escala podrida y el ticker
   pasaría de vendible a trabado), así que su atraso está justificado. Un hueco
   **interior** no lo justifica esa excepción, y se le sigue reportando.
"""

from __future__ import annotations

import pandas as pd
import pytest

import analysis.harness_config as hc
from analysis.harness_config import MissingSession, announce_continuity, cross_period_gaps


def _frame(fechas: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"Close": [10.0] * len(fechas)}, index=pd.to_datetime(fechas))


@pytest.fixture
def cohorte(monkeypatch):
    """Un ticker con dos frames: el auditado (`10y`) y un hermano (`2y`) más nuevo."""

    def _armar(propias: list[str], hermano: list[str], ticker: str = "XYZ"):
        monkeypatch.setattr(hc, "ARTIFACT_REFRESH_EXCEPTIONS", {}, raising=False)

        from data import parquet_cache

        monkeypatch.setattr(parquet_cache, "labelled_1d", lambda t: [("2y", _frame(hermano))])

        class _Dir:
            @staticmethod
            def exists():
                return True

            @staticmethod
            def glob(_p):
                return [type("F", (), {"name": f"{ticker}__2y__1d.parquet"})()] * 2

        monkeypatch.setattr(parquet_cache, "get_parquet_dir", lambda: _Dir)
        return {ticker: [(f, 10.0) for f in propias]}

    return _armar


# ── El defecto ───────────────────────────────────────────────────────────────


def test_la_cola_del_hermano_SE_REPORTA(cohorte):
    """**El corazón de la tarea.** Antes esto devolvía `()` porque `hi` se clampeaba."""
    bars = cohorte(propias=["2026-09-01", "2026-09-02"], hermano=["2026-09-01", "2026-09-02", "2026-09-03"])
    (gap,) = cross_period_gaps(bars)

    assert gap == MissingSession("XYZ", "2026-09-03", "2y", cola=True)
    assert "ATRASADO" in str(gap) and "refrescar, no reparar" in str(gap)


def test_un_hueco_INTERIOR_sigue_siendo_interior(cohorte):
    """La contraprueba del eje: lo que ya funcionaba no puede cambiar de categoría."""
    bars = cohorte(propias=["2026-09-01", "2026-09-03"], hermano=["2026-09-01", "2026-09-02", "2026-09-03"])
    (gap,) = cross_period_gaps(bars)

    assert gap.date == "2026-09-02" and gap.cola is False
    assert "falta la rueda" in str(gap)


def test_el_borde_IZQUIERDO_se_sigue_clampeando(cohorte):
    """Un `2y` que empieza antes que el `10y` auditado no genera huecos hacia atrás.

    Es la mitad de la justificación original que **sí** era cierta, y sacarla habría
    convertido cada diferencia de ventana en un falso positivo.
    """
    bars = cohorte(propias=["2026-09-02", "2026-09-03"], hermano=["2026-08-01", "2026-09-02", "2026-09-03"])
    assert cross_period_gaps(bars) == ()


def test_sin_atraso_ni_hueco_no_acusa_nada(cohorte):
    bars = cohorte(propias=["2026-09-01", "2026-09-02"], hermano=["2026-09-01", "2026-09-02"])
    assert cross_period_gaps(bars) == ()


# ── La excepción declarada ───────────────────────────────────────────────────


def test_una_excepcion_de_refresh_declarada_EXIME_la_cola(cohorte, monkeypatch):
    """AVB está viejo a propósito (tarea 63): refrescarlo lo dejaría TRABADO."""
    bars = cohorte(
        propias=["2026-09-01"],
        hermano=["2026-09-01", "2026-09-02"],
        ticker="AVB",
    )
    monkeypatch.setattr(hc, "ARTIFACT_REFRESH_EXCEPTIONS", {"AVB": "tarea 63"}, raising=False)
    assert cross_period_gaps(bars) == ()


def test_pero_NO_le_exime_un_hueco_interior(cohorte, monkeypatch):
    """La excepción justifica estar **viejo**, no que le falte una rueda adentro.

    Sin esta distinción, declarar una excepción de refresh apagaría también el guard
    de continuidad para ese ticker — que es el defecto de la 109 con otra ropa.
    """
    bars = cohorte(
        propias=["2026-09-01", "2026-09-03"],
        hermano=["2026-09-01", "2026-09-02", "2026-09-03"],
        ticker="AVB",
    )
    monkeypatch.setattr(hc, "ARTIFACT_REFRESH_EXCEPTIONS", {"AVB": "tarea 63"}, raising=False)
    (gap,) = cross_period_gaps(bars)
    assert gap.date == "2026-09-02" and gap.cola is False


# ── Lo que la cola NO cambia todavía ─────────────────────────────────────────


def test_la_cola_se_declara_pero_NO_aborta(cohorte, capsys):
    """El alcance acotado de esta tarea, y la razón está en el mensaje.

    Con el cohorte de hoy, 125 de 127 tickers tienen el `10y` atrasado. Si eso entrara
    al `strict`, **los 26 lectores del cohorte abortarían** — y esta tarea no re-corre
    ni re-publica nada. Que el atraso uniforme falle es la tarea 140.
    """
    bars = cohorte(propias=["2026-09-01"], hermano=["2026-09-01", "2026-09-02"])
    salida = announce_continuity(bars, strict=True)  # strict y NO levanta

    texto = capsys.readouterr().out
    assert "ATRASADO" in texto
    assert "NO aborta la corrida" in texto and "tarea 140" in texto
    assert len(salida) == 1 and salida[0].cola


def test_un_hueco_interior_SI_aborta_con_strict(cohorte):
    """Y la contraprueba: lo que abortaba antes tiene que seguir abortando, o esta
    tarea habría aflojado el guard en vez de afinarlo."""
    bars = cohorte(propias=["2026-09-01", "2026-09-03"], hermano=["2026-09-01", "2026-09-02", "2026-09-03"])
    with pytest.raises(hc.StaleArtifactError, match="rueda"):
        announce_continuity(bars, strict=True)
