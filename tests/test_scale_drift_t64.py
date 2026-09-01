"""SCALEDRIFT (tarea 64) — la zona muerta DEBAJO de la banda del 50%.

E5 y la **63** encima se disparan sólo cuando el precio vivo se sale de la banda
(`price_sanity_band_pct`, 50%). Un ajuste espurio **menor** —un split fantasma de
1.3, un re-ajuste mal conciliado— deja el histórico fuera de escala con el precio
vivo **adentro**: no hay WARNING, no se evalúa disputa, no corre nada. Y duele
igual, porque el **ATR y las barreras** salen del histórico
(`paper_history_period`, default `2y`): un frame 1,3× chico da un stop 1,3× más
ajustado que el que la política dice.

Acá no sirve el truco de la 63 —definir la disputa por el *veredicto* de banda—
porque sin rechazo previo no hay veredicto que comparar. Hace falta un umbral de
magnitud, y está **calibrado sobre los frames reales**
(`docs/scale_drift_t64_2026-09-01.md`): 365 pares del cache vivo, el drift
legítimo se termina en **1,719%** y el único caso real está en **64,196%**. Estos
tests fijan las dos mitades: que el umbral separe esas dos poblaciones, y que la
política sea la misma asimetría que shipeó la 63 — **salir sí, entrar no**.
"""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
import pytest

from data import yahoo_finance as yfm

# ── Helpers ───────────────────────────────────────────────────────────────────


def _seed(ticker: str, closes: list[tuple[str, float]], period: str, *, fetched: str) -> None:
    """Frame ``1d`` cacheado para ``(ticker, period)``, con su ``fetched_at``.

    El sello va **explícito y distinto** entre frames por la misma razón que en la
    63: quién es "el más fresco" no puede depender de la resolución del reloj.
    """
    from database.models import HistoricalDataCache, session_scope

    df = pd.DataFrame(
        {
            "Open": [c for _, c in closes],
            "High": [c for _, c in closes],
            "Low": [c for _, c in closes],
            "Close": [c for _, c in closes],
            "Volume": [1_000_000.0] * len(closes),
        },
        index=pd.to_datetime([d for d, _ in closes]),
    )
    with session_scope() as s:
        s.add(
            HistoricalDataCache(
                ticker=ticker.upper(),
                period=period,
                interval="1d",
                data_json=df.to_json(orient="split", date_format="iso"),
                fetched_at=datetime.fromisoformat(fetched),
            )
        )


def _serie(base: float, n: int = 20, factor: float = 1.0) -> list[tuple[str, float]]:
    """``n`` ruedas desde el 2026-01-05, con el precio escalado por ``factor``."""
    fechas = pd.bdate_range("2026-01-05", periods=n).strftime("%Y-%m-%d")
    return [(d, base * factor * (1.0 + 0.001 * i)) for i, d in enumerate(fechas)]


def _dos_frames(ticker: str, factor: float, *, n: int = 20) -> None:
    """El ``2y`` (más fresco) escalado por ``factor`` contra un ``10y`` sano."""
    _seed(ticker, _serie(100.0, n, factor), "2y", fetched="2026-08-20")
    _seed(ticker, _serie(100.0, n), "10y", fetched="2026-01-10")


# ── El instrumento ────────────────────────────────────────────────────────────


def test_two_frames_on_the_same_scale_are_not_drift():
    """El caso normal, que es casi todo el cache: 365 pares medidos, mediana 0,000%."""
    _dos_frames("SANO", 1.0)
    assert yfm.scale_drift("SANO") is None


def test_a_small_phantom_split_is_caught_although_the_price_stays_in_band():
    """El caso que abre la tarea. Un 1.3 nunca saca al precio de la banda del 50%,
    así que E5 y la 63 no llegan a correr — y el ATR igual sale del frame malo."""
    _dos_frames("FANT", 1 / 1.3)
    d = yfm.scale_drift("FANT")
    assert d is not None
    assert d.factor == pytest.approx(1 / 1.3, rel=1e-6)
    assert d.deviation == pytest.approx(0.2308, abs=1e-3)
    assert (d.fresh_label, d.other_label) == ("2y", "10y")
    assert "FANT" in str(d) and "fechas solapadas" in str(d)


def test_the_legitimate_dividend_drift_does_not_trip_it():
    """Pin de la calibración: el drift legítimo medido sobre el cache real llega
    hasta **1,719%** (PFE, re-ajuste por dividendos entre dos fetches). Si esto
    empezara a disparar, el guard estaría bloqueando entradas sanas."""
    _dos_frames("DIVI", 1.0 - 0.01719)
    assert yfm.scale_drift("DIVI") is None
    # y con la tolerancia bajada a mano, sí aparece: no es que no lo vea
    assert yfm.scale_drift("DIVI", tol=0.01) is not None


def test_the_tolerance_separates_the_two_measured_populations():
    """El umbral no se eligió de memoria. Tiene que quedar **arriba** del máximo
    legítimo observado (1,719%) y **abajo** del split más chico que existe en la
    práctica (3:2 ⇒ 33% de desvío). El default cae en ese hueco de 37×."""
    tol = yfm._DEFAULT_SCALE_DRIFT_TOLERANCE
    assert 0.01719 < tol < 1 - (1 / 1.5)


def test_it_compares_on_OVERLAPPING_dates_not_on_the_last_close():
    """Los frames se bajan en momentos distintos, así que sus últimos closes
    difieren por el **movimiento real** del precio. Comparar esa punta acusaría a
    cualquier ticker que se haya movido entre dos fetches."""
    _seed("MOVIO", _serie(100.0, 30), "2y", fetched="2026-08-20")  # llega más lejos
    _seed("MOVIO", _serie(100.0, 12), "10y", fetched="2026-01-10")
    assert yfm.scale_drift("MOVIO") is None


def test_a_handful_of_overlapping_dates_is_not_enough_to_call_it_scale():
    """Con pocas fechas, un par de días raros pesarían como si fueran la escala.
    AVB —el único caso real— solapa 16."""
    _seed("POCAS", _serie(100.0, 3, 0.5), "2y", fetched="2026-08-20")
    _seed("POCAS", _serie(100.0, 3), "10y", fetched="2026-01-10")
    assert yfm.scale_drift("POCAS") is None


def test_a_single_frame_cannot_be_disputed():
    """Sin un segundo frame no hay con qué cruzar: es el mismo límite que la 63."""
    _seed("SOLO", _serie(100.0), "2y", fetched="2026-08-20")
    assert yfm.scale_drift("SOLO") is None


def test_zero_tolerance_turns_the_guard_off():
    """Misma convención que ``price_sanity_band_pct``: 0 = apagado, no 0 = todo drift."""
    _dos_frames("OFFTK", 0.5)
    assert yfm.scale_drift("OFFTK") is not None
    assert yfm.scale_drift("OFFTK", tol=0.0) is None


def test_it_reports_the_WORST_pair_not_the_first():
    """Con tres frames, el que manda es el que más se aparta: si el aviso nombrara
    el primero que encuentra, el operador iría a mirar el problema chico."""
    _seed("TRES", _serie(100.0, 20, 0.4), "2y", fetched="2026-08-20")
    _seed("TRES", _serie(100.0, 20, 0.9), "5y", fetched="2026-05-10")
    _seed("TRES", _serie(100.0, 20), "10y", fetched="2026-01-10")
    d = yfm.scale_drift("TRES")
    assert d is not None and d.other_label == "10y"
    assert d.deviation == pytest.approx(0.6, abs=1e-6)


def test_a_broken_cache_fails_open(monkeypatch):
    """Un guard nuevo que rompe un scan es peor que el problema que resuelve."""

    def _boom(_t):
        raise RuntimeError("cache podrido")

    monkeypatch.setattr(yfm, "_labelled_1d_frames", _boom)
    assert yfm.scale_drift("CUALQUIERA") is None


# ── La política: salir sí, entrar no ─────────────────────────────────────────


def test_with_drifted_frames_the_BUY_is_blocked_even_with_the_price_in_band(caplog):
    """La mitad que importa: la cotización puede ser perfecta y el stop salir igual
    de otra escala, porque el ATR no se calcula con la cotización."""
    from paper_trading import engine

    _dos_frames("ENTRA", 1 / 1.3)
    with caplog.at_level(logging.WARNING, logger="paper_trading.engine"):
        assert engine._price_out_of_band("ENTRA", 100.0, "BUY") is True
    assert any("ENTRADA se bloquea" in r.getMessage() for r in caplog.records)


def test_with_drifted_frames_the_SELL_is_NOT_blocked():
    """La asimetría que shipeó la 63, acá abajo del umbral: quedar trapeado es peor
    que salir con un histórico en duda. Entrar es opcional; salir no."""
    from paper_trading import engine

    _dos_frames("SALE", 1 / 1.3)
    assert engine._price_out_of_band("SALE", 100.0, "SELL") is False


def test_an_unknown_side_is_treated_as_an_exit():
    """Mismo default conservador que la 63: si no sabemos el lado, no trabamos."""
    from paper_trading import engine

    _dos_frames("NOSIDE", 1 / 1.3)
    assert engine._price_out_of_band("NOSIDE", 100.0) is False


def test_frames_in_the_same_scale_do_not_block_anything():
    """Regresión del caso normal: el guard nuevo no puede empezar a trabar compras
    sanas. Medido sobre el cache real: 0 de 364 pares legítimos lo dispararían."""
    from paper_trading import engine

    _dos_frames("LIMPIO", 1.0)
    assert engine._price_out_of_band("LIMPIO", 100.0, "BUY") is False
    assert engine._price_out_of_band("LIMPIO", 100.0, "SELL") is False


# ── La declaración incondicional, en el scan ─────────────────────────────────


def test_the_scan_declares_the_drift_even_if_nobody_intenta_operar(caplog):
    """Lo que la 63 no podía hacer: el cruce corre **siempre**, no sólo cuando un
    precio ya fue rechazado. Sin esto un ticker puede estar 1,3× fuera de escala
    durante meses sin una sola línea de log."""
    from paper_trading import engine

    _dos_frames("DECL", 1 / 1.3)
    with caplog.at_level(logging.WARNING, logger="paper_trading.engine"):
        avisos = engine._declare_scale_drift(["DECL", "NOEXISTE"])
    assert len(avisos) == 1
    assert "DECL" in avisos[0] and "ENTRADAS" in avisos[0]
    assert any("DRIFT DE ESCALA" in r.getMessage() for r in caplog.records)


def test_the_declaration_is_best_effort_and_never_breaks_a_scan(monkeypatch):
    """Corre dentro de ``run_scan``: si explota, se lleva puesto el scan entero."""
    from paper_trading import engine

    def _boom(_t):
        raise RuntimeError("qué se yo")

    monkeypatch.setattr(yfm, "scale_drift", _boom)
    assert engine._declare_scale_drift(["LOQUESEA"]) == []


def test_the_scan_wires_the_declaration_after_the_warm_up():
    """Regresión del cableado, con el mismo criterio que la 58 y la 62: si el
    instrumento existe pero no lo llama nadie, el drift sigue siendo invisible. Y
    el orden importa — antes del warm-up leería el cache viejo."""
    from pathlib import Path

    txt = (Path(__file__).resolve().parent.parent / "paper_trading" / "engine.py").read_text(encoding="utf-8")
    assert "_declare_scale_drift(tickers)" in txt
    assert txt.index("_warm_up_history_cache(tickers)") < txt.index(
        "scan_warnings.extend(_declare_scale_drift"
    )
