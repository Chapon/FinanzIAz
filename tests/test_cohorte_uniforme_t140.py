"""Tarea 140 (COHORTE-UNIFORME) — un cohorte atrasado ENTERO deja de pasar en verde.

``stale_artifacts`` compara cada artefacto contra ``cohort_end(bars_by)``, que es la
última barra **modal del propio cohorte**. Si todo el cohorte está igual de viejo, **la
moda se mueve con él y no acusa a nadie**: es
[[guard-no-puede-usar-de-verdad-lo-que-chequea]] en el guard que existe para que la
muestra no esté torcida.

**La demostración estaba medida:** el cohorte `5y` tenía su última barra el 2026-06-01
—71 ruedas atrás— y ``stale_artifacts`` devolvía **CERO**.

**Y la asimetría estaba premiada**, que es lo que explica por qué el hueco no se cerraba
solo: ``WINDOW_LIVE`` era exactamente la ventana del cohorte de hoy,
así que ``reproduction_check`` daba un veredicto usable; **refrescar** lo pasa a
``REPRO_INDETERMINATE`` y obliga a re-anclar constantes (la T68 re-ancló 17). Un refresh
parcial aborta la corrida; no refrescar nunca no costaba nada. El gradiente apuntaba a
no refrescar.

**El camino elegido (Chapa, 2026-09-09) es el (a): el hermano como reloj**, sobre el
mecanismo que dejó la tarea 139. Y no es sólo el más barato: es **más correcto**. El
conteo de ruedas de cola es un lag en **sesiones reales**, porque el hermano sólo tiene
los días que el mercado abrió. Medido: el `2y` tiene 09-02, 03, 04, 08 y 09 y **no**
tiene el 2026-09-07 (Labor Day) ⇒ lag **5**. ``_busday_lag``, que no tiene calendario de
feriados, habría dicho **6**. El camino (b) necesitaba esa tabla justamente para no ser
ruidoso alrededor de cada feriado.

**Lo que este guard NO cubre, y va declarado:** el ticker con **un solo** frame. No hay
contra qué cruzarlo, así que queda afuera — la misma propiedad que la T110 se ganó a
propósito (*«un ticker sin otro frame no es comparable y queda afuera, sin umbrales
inventados»*). Cubrir ése es el camino (b), y sigue sin hacerse.
"""

from __future__ import annotations

import pandas as pd
import pytest

import analysis.harness_config as hc
from analysis.harness_config import (
    ARTIFACT_MAX_LAG_DAYS,
    LIVE_MAX_POSITIONS,
    LIVE_WATCHLIST_SIZE,
    HarnessConfig,
    StaleArtifactError,
    announce_continuity,
    stale_artifacts,
)


def _frame(fechas: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"Close": [10.0] * len(fechas)}, index=pd.to_datetime(fechas))


_RUEDAS = [
    "2026-09-01",
    "2026-09-02",
    "2026-09-03",
    "2026-09-04",
    "2026-09-08",  # el 09-07 es Labor Day y NO está: el hermano trae el calendario
    "2026-09-09",
]


@pytest.fixture
def cohorte_atrasado(monkeypatch):
    """Un cohorte de N tickers **todos** cortados en la misma fecha, con hermano al día."""

    def _armar(n_tickers: int, corte: int):
        monkeypatch.setattr(hc, "ARTIFACT_REFRESH_EXCEPTIONS", {}, raising=False)
        from data import parquet_cache

        monkeypatch.setattr(parquet_cache, "labelled_1d", lambda t: [("2y", _frame(_RUEDAS))])
        tickers = [f"T{i}" for i in range(n_tickers)]

        # Dos archivos POR TICKER: `cross_period_gaps` cuenta frames por nombre y
        # saltea al que tiene uno solo. La primera versión de este fixture devolvía
        # dos archivos con un nombre ajeno y el barrido no miraba a nadie — los tres
        # tests pasaban a "sin ruedas faltantes" y dos de ellos fallaban por eso.
        archivos = [
            type("F", (), {"name": f"{t}__{p}__1d.parquet"})() for t in tickers for p in ("2y", "10y")
        ]

        class _Dir:
            @staticmethod
            def exists():
                return True

            @staticmethod
            def glob(_p):
                return archivos

        monkeypatch.setattr(parquet_cache, "get_parquet_dir", lambda: _Dir)
        return {t: [(f, 10.0) for f in _RUEDAS[:corte]] for t in tickers}

    return _armar


# ── El defecto que esta tarea cierra ─────────────────────────────────────────


def test_stale_artifacts_NO_ve_el_atraso_uniforme(cohorte_atrasado):
    """La premisa de la tarea, fijada como test: el guard viejo devuelve CERO.

    No es un reproche al guard —hace exactamente lo que dice, comparar contra la moda—
    sino la razón de que haga falta una referencia **externa al cohorte**.
    """
    bars = cohorte_atrasado(n_tickers=10, corte=1)  # todos parados en el 2026-09-01
    assert stale_artifacts(bars) == ()


def test_el_cohorte_uniformemente_atrasado_AHORA_falla(cohorte_atrasado):
    """**El corazón de la 140.** Cinco ruedas de cola pasan; la sexta no.

    Acá el cohorte está parado en el 2026-09-01 y el hermano llega al 09-09: son
    **5** sesiones reales de cola, o sea justo la tolerancia. Se le agrega una y falla.
    """
    bars = cohorte_atrasado(n_tickers=10, corte=1)
    with pytest.raises(StaleArtifactError, match="ATRASADOS"):
        announce_continuity(bars, strict=True, max_lag_days=4)


def test_dentro_de_la_tolerancia_no_falla(cohorte_atrasado):
    """La contraprueba: el guard no puede ser un freno permanente.

    Con la tolerancia viva (5) el cohorte de hoy —5 ruedas de cola— **no** aborta.
    """
    bars = cohorte_atrasado(n_tickers=10, corte=1)
    assert announce_continuity(bars, strict=True, max_lag_days=ARTIFACT_MAX_LAG_DAYS)


def test_un_cohorte_AL_DIA_no_falla(cohorte_atrasado):
    """Y el control positivo, que es lo que impide que el guard acuse a todo el mundo."""
    bars = cohorte_atrasado(n_tickers=10, corte=len(_RUEDAS))
    assert announce_continuity(bars, strict=True, max_lag_days=0) == ()


def test_el_mensaje_dice_QUE_hacer_y_que_la_ventana_se_mueve(cohorte_atrasado):
    """Un guard que frena 26 corridas tiene que decir cómo salir, y decir el costo.

    Refrescar mueve la ventana ⇒ `reproduction_check` pasa a INDETERMINADO y hay que
    re-anclar constantes. Si el mensaje no lo dice, el próximo refresca y se encuentra
    con 17 constantes rotas sin saber por qué (que es lo que pasó en la T68).
    """
    bars = cohorte_atrasado(n_tickers=3, corte=1)
    with pytest.raises(StaleArtifactError) as e:
        announce_continuity(bars, strict=True, max_lag_days=4)

    msg = str(e.value)
    assert "re-anclar las constantes de reproducción" in msg
    assert "strict=False" in msg
    assert "moda del propio cohorte" in msg  # dice POR QUÉ el otro guard no lo vio


# ── El límite declarado ──────────────────────────────────────────────────────


def test_con_el_switch_apagado_los_OTROS_dos_desvios_de_barreras_lo_dicen(monkeypatch):
    """Tarea 151 — el resto de la familia, que la 132 había dejado afuera.

    Los desvíos de la **T32** (precio de evaluación) y la **T33** (fill) comparan el
    harness *«vs en vivo»*, y con `atr_stops_enabled` apagado **el lado vivo no
    existe**. No se suprimen —el harness sí simula barreras, y cómo las evalúa sigue
    siendo un hecho suyo— pero la comparación se corrige, o el banner afirma que en
    vivo se decide al precio corriente algo que en vivo no se decide nunca.

    Apareció escribiendo el test de la 132: filtré por `"barreras ATR"` y me trajo
    **tres** líneas de tres ejes distintos. El filtro estaba mal; la pregunta, no.
    """
    from analysis.harness_config import deviations_keyed

    cfg = HarnessConfig(LIVE_MAX_POSITIONS, "x.txt", LIVE_WATCHLIST_SIZE)
    por_clave = {d.clave: d.texto for d in deviations_keyed(cfg)}
    assert "no tiene lado derecho" not in por_clave["barrier_eval"]  # hoy el switch está ON

    monkeypatch.setattr(hc, "LIVE_ATR_STOPS_ENABLED", False)
    por_clave = {d.clave: d.texto for d in deviations_keyed(cfg)}
    for clave in ("barrier_eval", "barrier_fill"):
        assert "APAGADO" in por_clave[clave] and "atr_master_off" in por_clave[clave], clave


def test_un_ticker_con_UN_SOLO_frame_queda_afuera(monkeypatch):
    """El agujero que el camino (a) **no** cubre, y por eso está escrito.

    Sin un segundo frame no hay contra qué cruzar. Es la propiedad que la T110 se ganó
    a propósito —nada de umbrales inventados— y el precio es que un ticker solitario y
    atrasado pasa. Cubrirlo es el camino (b): un reloj externo con tabla de feriados.
    """
    monkeypatch.setattr(hc, "ARTIFACT_REFRESH_EXCEPTIONS", {}, raising=False)
    from data import parquet_cache

    class _Dir:
        @staticmethod
        def exists():
            return True

        @staticmethod
        def glob(_p):
            return [type("F", (), {"name": "SOLO__10y__1d.parquet"})()]  # UN solo frame

    monkeypatch.setattr(parquet_cache, "get_parquet_dir", lambda: _Dir)
    monkeypatch.setattr(parquet_cache, "labelled_1d", lambda t: [])

    bars = {"SOLO": [("2020-01-02", 10.0)]}  # atrasadísimo
    assert announce_continuity(bars, strict=True, max_lag_days=0) == ()
