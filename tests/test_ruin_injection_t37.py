"""Tests del enabler de inyección de ruina — Tarea 37 (STOP-VALUE).

Cubre el §11.4 del pre-registro congelado (``docs/stop_value_prereg_t37_2026-08-19.md``):
determinismo por semilla, el evento cae dentro del rango del ticker, ``gradual`` llega
a ``−d`` exactamente en 20 ruedas, ``rate=0`` devuelve las barras **idénticas**, y todos
los brazos reciben el mismo objeto.

Offline puro: no toca red, ni disco, ni ``finanzias.db``.
"""

from __future__ import annotations

import math

import pytest

from analysis.exit_replay import Bar
from analysis.ruin_injection import (
    BASE_SEED,
    DECIDING_SHAPE,
    N_SEEDS,
    SHAPE_SPANS,
    TRADING_DAYS,
    bars_digest,
    event_summary,
    inject_ruin,
    seeds,
    ticker_years,
)


def _bars(n: int, start_price: float = 100.0, drift: float = 0.0005) -> list[Bar]:
    """Serie sintética determinista: close creciente suave, rango intradía ±1%."""
    out: list[Bar] = []
    price = start_price
    for i in range(n):
        date = f"20{20 + i // 252:02d}-{1 + (i // 21) % 12:02d}-{1 + i % 21:02d}"
        c = price
        out.append((date, c * 0.999, c * 1.01, c * 0.99, c))
        price *= 1.0 + drift
    return out


def _universe(n_tickers: int = 6, n_bars: int = 600) -> dict[str, list[Bar]]:
    return {f"T{i:02d}": _bars(n_bars, start_price=50.0 + 10 * i) for i in range(n_tickers)}


# ── rate=0 ⇒ IDENTIDAD (no equivalencia) ─────────────────────────────────────


def test_rate_zero_devuelve_los_mismos_objetos():
    """``r=0`` tiene que devolver las barras idénticas — es el ancla del barrido."""
    uni = _universe()
    out, events = inject_ruin(uni, rate=0.0, depth=0.50, seed=BASE_SEED)

    assert events == []
    assert set(out) == set(uni)
    for t in uni:
        assert out[t] is uni[t], f"{t}: se copió la lista en vez de reusarla"
    assert bars_digest(out) == bars_digest(uni)


def test_rate_zero_no_consume_extracciones_del_rng():
    """Dos formas y dos profundidades distintas a ``r=0`` dan el mismo mundo."""
    uni = _universe()
    a, _ = inject_ruin(uni, rate=0.0, depth=0.50, shape="gradual", seed=BASE_SEED)
    b, _ = inject_ruin(uni, rate=0.0, depth=0.70, shape="gap", seed=BASE_SEED + 7)
    assert bars_digest(a) == bars_digest(b) == bars_digest(uni)


# ── determinismo ─────────────────────────────────────────────────────────────


def test_determinista_por_semilla():
    uni = _universe()
    kw = dict(rate=0.05, depth=0.50, shape="gradual", seed=BASE_SEED)
    a, ea = inject_ruin(uni, **kw)
    b, eb = inject_ruin(uni, **kw)
    assert bars_digest(a) == bars_digest(b)
    assert [(e.ticker, e.start_idx) for e in ea] == [(e.ticker, e.start_idx) for e in eb]


def test_semillas_distintas_dan_mundos_distintos():
    uni = _universe(n_tickers=10, n_bars=1200)
    kw = dict(rate=0.05, depth=0.50, shape="gradual")
    a, _ = inject_ruin(uni, seed=BASE_SEED, **kw)
    b, _ = inject_ruin(uni, seed=BASE_SEED + 1, **kw)
    assert bars_digest(a) != bars_digest(b)


def test_el_sorteo_no_depende_del_orden_ni_del_tamano_del_universo():
    """El RNG se deriva del NOMBRE, así que un ticker recibe su evento aunque el
    universo cambie de tamaño o de orden de iteración."""
    big = _universe(n_tickers=8, n_bars=900)
    small = {k: big[k] for k in ("T03", "T01")}  # subconjunto, orden invertido
    kw = dict(rate=0.08, depth=0.50, seed=BASE_SEED)
    out_big, ev_big = inject_ruin(big, **kw)
    out_small, ev_small = inject_ruin(small, **kw)

    starts_big = {e.ticker: e.start_idx for e in ev_big}
    starts_small = {e.ticker: e.start_idx for e in ev_small}
    for t in small:
        assert starts_big.get(t) == starts_small.get(t)
        assert [b[4] for b in out_big[t]] == [b[4] for b in out_small[t]]


# ── el evento cae dentro del rango del ticker ────────────────────────────────


def test_el_evento_cae_dentro_del_rango_de_fechas():
    uni = _universe(n_tickers=10, n_bars=900)
    _, events = inject_ruin(uni, rate=0.10, depth=0.50, seed=BASE_SEED)
    assert events, "con 10%/año y 900 barras tiene que haber al menos un evento"
    for e in events:
        bars = uni[e.ticker]
        assert 0 <= e.start_idx < len(bars)
        assert e.start_date == bars[e.start_idx][0]
        assert bars[0][0] <= e.start_date <= bars[-1][0]


def test_un_evento_como_maximo_por_ticker():
    uni = _universe(n_tickers=12, n_bars=1500)
    _, events = inject_ruin(uni, rate=0.20, depth=0.50, seed=BASE_SEED)
    tickers = [e.ticker for e in events]
    assert len(tickers) == len(set(tickers))


def test_el_largo_de_la_serie_no_cambia():
    uni = _universe(n_tickers=8, n_bars=700)
    out, _ = inject_ruin(uni, rate=0.10, depth=0.50, seed=BASE_SEED)
    for t in uni:
        assert len(out[t]) == len(uni[t])
        assert [b[0] for b in out[t]] == [b[0] for b in uni[t]]


# ── la forma: gradual llega a −d EXACTAMENTE en span ruedas ──────────────────


@pytest.mark.parametrize("depth", [0.50, 0.70])
def test_gradual_llega_a_menos_d_exactamente_en_20_ruedas(depth: float):
    bars = _bars(400)
    uni = {"AAA": bars}
    # rate=100%/año durante 400 barras: dispara casi seguro y temprano.
    out, events = inject_ruin(uni, rate=1.0, depth=depth, shape="gradual", seed=BASE_SEED)
    assert len(events) == 1
    ev = events[0]
    assert ev.span == SHAPE_SPANS["gradual"] == 20
    if not ev.completes:
        pytest.skip("el evento cayó tan al final que la caída no entra en la serie")

    k, span = ev.start_idx, ev.span
    anchor = bars[k][4]
    assert out["AAA"][k] == bars[k], "la barra del evento no se toca"
    assert out["AAA"][k + span][4] == pytest.approx(anchor * (1.0 - depth), rel=1e-12)


def test_gradual_es_monotona_y_log_lineal():
    bars = _bars(400)
    out, events = inject_ruin({"AAA": bars}, rate=1.0, depth=0.50, shape="gradual", seed=BASE_SEED)
    ev = events[0]
    if not ev.completes:
        pytest.skip("evento sin espacio para la caída completa")
    k, span = ev.start_idx, ev.span
    closes = [out["AAA"][k + j][4] for j in range(span + 1)]
    assert all(closes[j + 1] < closes[j] for j in range(span))
    # log-lineal ⇒ el ratio entre ruedas consecutivas es constante.
    ratios = [closes[j + 1] / closes[j] for j in range(span)]
    assert all(r == pytest.approx(ratios[0], rel=1e-9) for r in ratios)


def test_gap_cae_en_una_sola_rueda():
    bars = _bars(400)
    out, events = inject_ruin({"AAA": bars}, rate=1.0, depth=0.50, shape="gap", seed=BASE_SEED)
    ev = events[0]
    assert ev.span == SHAPE_SPANS["gap"] == 1
    if not ev.completes:
        pytest.skip("evento sin espacio")
    k = ev.start_idx
    assert out["AAA"][k] == bars[k]
    assert out["AAA"][k + 1][4] == pytest.approx(bars[k][4] * 0.50, rel=1e-12)
    assert out["AAA"][k + 1][1] == pytest.approx(bars[k][4] * 0.50, rel=1e-12)


def test_despues_del_span_la_serie_queda_plana():
    bars = _bars(500)
    out, events = inject_ruin({"AAA": bars}, rate=1.0, depth=0.50, shape="gradual", seed=BASE_SEED)
    ev = events[0]
    if ev.n_bars_after <= ev.span + 3:
        pytest.skip("evento sin cola para verificar el plano")
    k, span = ev.start_idx, ev.span
    terminal = ev.terminal_close
    for j in range(span, ev.n_bars_after):
        _, o, h, lo, c = out["AAA"][k + j]
        assert o == h == lo == c == pytest.approx(terminal, rel=1e-12)


def test_las_barras_previas_al_evento_no_se_tocan():
    bars = _bars(500)
    out, events = inject_ruin({"AAA": bars}, rate=1.0, depth=0.50, seed=BASE_SEED)
    k = events[0].start_idx
    assert out["AAA"][: k + 1] == bars[: k + 1]


def test_la_forma_intradia_se_preserva_durante_la_caida():
    """Escalar la barra entera mantiene el rango relativo high/low."""
    bars = _bars(500)
    out, events = inject_ruin({"AAA": bars}, rate=1.0, depth=0.50, seed=BASE_SEED)
    ev = events[0]
    if not ev.completes:
        pytest.skip("evento sin espacio")
    k = ev.start_idx
    for j in range(1, ev.span):
        _, _, h0, lo0, c0 = bars[k + j]
        _, _, h1, lo1, c1 = out["AAA"][k + j]
        assert h1 / c1 == pytest.approx(h0 / c0, rel=1e-9)
        assert lo1 / c1 == pytest.approx(lo0 / c0, rel=1e-9)


# ── monotonía en la tasa (la propiedad que hace legible el barrido) ──────────


def test_mas_tasa_no_puede_dar_menos_eventos():
    """Con el mismo stream por ticker, subir el hazard sólo puede ADELANTAR el
    disparo — nunca eliminarlo. Es lo que hace comparable la rejilla de tasas."""
    uni = _universe(n_tickers=14, n_bars=1200)
    prev_hits: set[str] = set()
    prev_starts: dict[str, int] = {}
    for rate in (0.005, 0.01, 0.026, 0.05, 0.10):
        _, events = inject_ruin(uni, rate=rate, depth=0.50, seed=BASE_SEED)
        hits = {e.ticker for e in events}
        starts = {e.ticker: e.start_idx for e in events}
        assert prev_hits <= hits, f"a {rate:.3%} se perdió un ticker que ya golpeaba"
        for t in prev_hits:
            assert starts[t] <= prev_starts[t], f"{t}: el evento se atrasó al subir la tasa"
        prev_hits, prev_starts = hits, starts


# ── digest / sanity §7.6 ─────────────────────────────────────────────────────


def test_digest_distingue_mundos_y_es_estable():
    uni = _universe(n_tickers=8, n_bars=800)
    a, _ = inject_ruin(uni, rate=0.026, depth=0.50, seed=BASE_SEED)
    b, _ = inject_ruin(uni, rate=0.026, depth=0.50, seed=BASE_SEED)
    c, _ = inject_ruin(uni, rate=0.026, depth=0.70, seed=BASE_SEED)
    assert bars_digest(a) == bars_digest(b)
    assert bars_digest(a) != bars_digest(c)


def test_digest_detecta_un_solo_float_movido():
    uni = _universe(n_tickers=3, n_bars=50)
    d0 = bars_digest(uni)
    tocado = {k: list(v) for k, v in uni.items()}
    date, o, h, lo, c = tocado["T01"][10]
    tocado["T01"][10] = (date, o, h, lo, c * (1 + 1e-12))
    assert bars_digest(tocado) != d0


# ── validación de argumentos ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "kw",
    [
        {"shape": "instantanea"},
        {"depth": 0.0},
        {"depth": 1.0},
        {"depth": 1.5},
        {"rate": -0.01},
    ],
)
def test_argumentos_invalidos(kw: dict):
    uni = _universe(n_tickers=2, n_bars=60)
    base = dict(rate=0.026, depth=0.50, shape="gradual", seed=BASE_SEED)
    with pytest.raises(ValueError):
        inject_ruin(uni, **{**base, **kw})


# ── constantes congeladas ────────────────────────────────────────────────────


def test_constantes_del_preregistro():
    assert TRADING_DAYS == 252
    assert SHAPE_SPANS == {"gradual": 20, "gap": 1}
    assert DECIDING_SHAPE == "gradual"
    assert BASE_SEED == 20260819
    assert N_SEEDS == 3
    assert seeds() == (20260819, 20260820, 20260821)


# ── descriptivos ─────────────────────────────────────────────────────────────


def test_ticker_years_y_event_summary():
    uni = _universe(n_tickers=5, n_bars=TRADING_DAYS * 2)
    assert ticker_years(uni) == pytest.approx(10.0)
    _, events = inject_ruin(uni, rate=0.10, depth=0.50, seed=BASE_SEED)
    s = event_summary(events, n_tickers=len(uni), total_ticker_years=ticker_years(uni))
    assert s["n_events"] == len(events)
    assert s["n_tickers"] == 5
    assert 0.0 <= s["share_tickers_hit"] <= 1.0
    assert s["events_per_ticker_year"] == pytest.approx(len(events) / 10.0)


def test_la_tasa_efectiva_se_parece_a_la_pedida():
    """Sanity estadístico laxo: con 120 tickers × 10 años y 5%/año, la tasa
    observada de tickers golpeados tiene que estar en el orden correcto."""
    uni = {f"T{i:03d}": _bars(TRADING_DAYS * 10) for i in range(120)}
    _, events = inject_ruin(uni, rate=0.05, depth=0.50, seed=BASE_SEED)
    # P(al menos un evento en 10 años) = 1 − (1 − 0.05/252)^2520 ≈ 39,3%.
    share = len({e.ticker for e in events}) / len(uni)
    assert 0.25 < share < 0.55, f"share de tickers golpeados fuera de rango: {share:.3f}"


def test_la_ruina_hace_dano_al_precio_final():
    """Si inyectar ruina no baja el precio, el barrido no mide nada (sanity §7.5)."""
    uni = _universe(n_tickers=20, n_bars=1200)
    out, events = inject_ruin(uni, rate=0.10, depth=0.50, seed=BASE_SEED)
    assert events
    for e in events:
        if e.completes:
            assert out[e.ticker][-1][4] == pytest.approx(e.terminal_close, rel=1e-12)
            assert out[e.ticker][-1][4] < uni[e.ticker][e.start_idx][4]


def test_no_hay_precios_no_positivos_ni_nan():
    uni = _universe(n_tickers=10, n_bars=900)
    out, _ = inject_ruin(uni, rate=0.10, depth=0.70, seed=BASE_SEED)
    for bars in out.values():
        for _, o, h, lo, c in bars:
            for v in (o, h, lo, c):
                assert math.isfinite(v) and v > 0
