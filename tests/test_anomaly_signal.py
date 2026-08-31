"""
Tests de ``analysis.anomaly_signal`` — detector de anomalía precio/volumen
(Tarea 11, Brazo B). Pre-registro: ``docs/anomaly_signal_prereg_t11b_2026-07-23.md``.

Qué fijan:
1. Disparo cuando SE CUMPLEN LAS DOS condiciones (salto de precio ≥ k·ATR **y**
   volumen ≥ m·ADV20), con la entrada resuelta a ``i+1``.
2. NO dispara con solo una condición: solo-precio (volumen normal) y, clave,
   **solo-volumen sin salto de precio** = el artefacto de split que el ``AND``
   está diseñado para no confundir con evento.
3. Point-in-time: la detección en ``i`` no depende de barras ``> i``; una anomalía
   en la última barra no produce entrada operable.
4. Refractario: dos anomalías dentro de la ventana → solo la primera dispara.
5. Fail-safe: warmup respetado, ADV20 con historia insuficiente no dispara,
   guardas de NaN/cero, alineación de volumen.
6. ``build_anomaly_entries``: entradas ``(ticker, i+1)``, orden cronológico,
   descarte de la anomalía sin rueda posterior, determinismo.
"""

from __future__ import annotations

from datetime import date, timedelta

from analysis.anomaly_signal import (
    AnomalyParams,
    build_anomaly_entries,
    detect_anomalies,
)

# ── Builders sintéticos ──────────────────────────────────────────────────────

_BASE_CLOSE = 100.0
_HALF_RANGE = 0.5  # → TR ≈ 1.0/día en la serie plana → ATR14 ≈ 1.0
_ADV = 1_000_000.0  # volumen "normal"
_WARMUP = 30  # chico para tests rápidos (start = max(warmup, 20, 15))


def _dates(n: int) -> list[str]:
    d0 = date(2020, 1, 1)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _flat_series(n: int):
    """Serie plana: close constante, TR≈1 (ATR≈1), volumen constante _ADV."""
    ds = _dates(n)
    bars = [
        (ds[i], _BASE_CLOSE, _BASE_CLOSE + _HALF_RANGE, _BASE_CLOSE - _HALF_RANGE, _BASE_CLOSE)
        for i in range(n)
    ]
    volumes = [_ADV] * n
    return bars, volumes


def _inject(bars, volumes, i, *, jump, vol_mult):
    """Convierte la barra ``i`` en un evento: close salta ``jump`` desde el previo
    y el volumen es ``vol_mult × _ADV``. Deja el resto de la serie intacto."""
    prev_close = bars[i - 1][4]
    new_close = prev_close + jump
    hi = max(new_close, prev_close) + _HALF_RANGE
    lo = min(new_close, prev_close) - _HALF_RANGE
    bars[i] = (bars[i][0], prev_close, hi, lo, new_close)
    volumes[i] = vol_mult * _ADV


# ── 1. Disparo con las dos condiciones ───────────────────────────────────────


def test_fires_when_both_conditions_hold():
    bars, vols = _flat_series(60)
    _inject(bars, vols, 40, jump=5.0, vol_mult=5.0)  # +5 >> k·ATR, 5× ADV
    fires = detect_anomalies(bars, vols, AnomalyParams(k=2.0, m=2.0), warmup=_WARMUP)
    assert fires == [40]


def test_entry_is_next_business_day():
    bars, vols = _flat_series(60)
    _inject(bars, vols, 40, jump=5.0, vol_mult=5.0)
    entries = build_anomaly_entries({"AAA": bars}, {"AAA": vols}, AnomalyParams(), warmup=_WARMUP)
    assert entries == [("AAA", 41)]  # entrada al día hábil siguiente (i+1)


# ── 2. Un solo lado no alcanza ───────────────────────────────────────────────


def test_no_fire_price_jump_without_volume():
    bars, vols = _flat_series(60)
    _inject(bars, vols, 40, jump=5.0, vol_mult=1.0)  # precio salta, volumen normal
    assert detect_anomalies(bars, vols, AnomalyParams(), warmup=_WARMUP) == []


def test_no_fire_volume_spike_without_price_move_split_artifact():
    """El caso split: volumen enorme, precio SIN salto → no dispara.

    Es la razón del AND ret+volumen (un split ajusta precio pero puede inflar
    volumen; sin salto de precio no hay evento)."""
    bars, vols = _flat_series(60)
    _inject(bars, vols, 40, jump=0.0, vol_mult=10.0)  # volumen 10×, close plano
    assert detect_anomalies(bars, vols, AnomalyParams(), warmup=_WARMUP) == []


def test_no_fire_on_negative_move_even_with_volume():
    """Long-only: un desplome con volumen alto no es candidato de BUY."""
    bars, vols = _flat_series(60)
    _inject(bars, vols, 40, jump=-5.0, vol_mult=5.0)
    assert detect_anomalies(bars, vols, AnomalyParams(), warmup=_WARMUP) == []


# ── 3. Point-in-time ─────────────────────────────────────────────────────────


def test_detection_ignores_future_bars():
    """Cambiar barras posteriores a i no altera la detección en i (PIT)."""
    bars_a, vols_a = _flat_series(60)
    _inject(bars_a, vols_a, 40, jump=5.0, vol_mult=5.0)
    fires_a = detect_anomalies(bars_a, vols_a, AnomalyParams(), warmup=_WARMUP)

    bars_b, vols_b = _flat_series(60)
    _inject(bars_b, vols_b, 40, jump=5.0, vol_mult=5.0)
    # perturbación fuerte DESPUÉS del evento (índices 42, 45)
    _inject(bars_b, vols_b, 45, jump=8.0, vol_mult=9.0)
    fires_b = detect_anomalies(bars_b, vols_b, AnomalyParams(), warmup=_WARMUP)

    assert fires_a[0] == 40 and fires_b[0] == 40  # el disparo en 40 es idéntico


def test_last_bar_anomaly_has_no_operable_entry():
    """Una anomalía en la última barra no puede producir una entrada (i+1 no existe)."""
    n = 60
    bars, vols = _flat_series(n)
    _inject(bars, vols, n - 1, jump=5.0, vol_mult=5.0)
    assert detect_anomalies(bars, vols, AnomalyParams(), warmup=_WARMUP) == [n - 1]
    # pero build_anomaly_entries la descarta (sin rueda de fill + posterior)
    assert build_anomaly_entries({"AAA": bars}, {"AAA": vols}, AnomalyParams(), warmup=_WARMUP) == []


# ── 4. Refractario ───────────────────────────────────────────────────────────


def test_refractory_suppresses_second_anomaly_within_window():
    bars, vols = _flat_series(80)
    _inject(bars, vols, 40, jump=5.0, vol_mult=5.0)
    _inject(bars, vols, 45, jump=5.0, vol_mult=5.0)  # dentro de refractory=20
    fires = detect_anomalies(bars, vols, AnomalyParams(refractory=20), warmup=_WARMUP)
    assert fires == [40]


def test_second_anomaly_fires_after_refractory():
    bars, vols = _flat_series(90)
    _inject(bars, vols, 40, jump=5.0, vol_mult=5.0)
    _inject(bars, vols, 65, jump=5.0, vol_mult=5.0)  # 25 > refractory=20
    fires = detect_anomalies(bars, vols, AnomalyParams(refractory=20), warmup=_WARMUP)
    assert fires == [40, 65]


# ── 5. Fail-safe ─────────────────────────────────────────────────────────────


def test_warmup_suppresses_early_anomaly():
    bars, vols = _flat_series(60)
    _inject(bars, vols, 25, jump=5.0, vol_mult=5.0)  # antes del warmup=30
    assert detect_anomalies(bars, vols, AnomalyParams(), warmup=30) == []


def test_mismatched_volume_length_is_safe():
    bars, vols = _flat_series(60)
    _inject(bars, vols, 40, jump=5.0, vol_mult=5.0)
    assert detect_anomalies(bars, vols[:-1], AnomalyParams(), warmup=_WARMUP) == []


def test_zero_adv_does_not_divide_by_zero():
    bars, vols = _flat_series(60)
    for j in range(20, 40):  # ADV window de la barra 40 queda todo en cero
        vols[j] = 0.0
    _inject(bars, vols, 40, jump=5.0, vol_mult=5.0)  # vol_mult sobre _ADV, no sobre 0
    # ADV20 = 0 → no se puede afirmar "anómalo"; no dispara y no rompe
    fires = detect_anomalies(bars, vols, AnomalyParams(), warmup=_WARMUP)
    assert 40 not in fires


def test_empty_input():
    assert detect_anomalies([], [], AnomalyParams()) == []


# ── 6. build_anomaly_entries ─────────────────────────────────────────────────


def test_entries_are_chronological_across_tickers():
    a_bars, a_vols = _flat_series(70)
    _inject(a_bars, a_vols, 55, jump=5.0, vol_mult=5.0)  # más tarde
    b_bars, b_vols = _flat_series(70)
    _inject(b_bars, b_vols, 40, jump=5.0, vol_mult=5.0)  # más temprano

    entries = build_anomaly_entries(
        {"AAA": a_bars, "BBB": b_bars},
        {"AAA": a_vols, "BBB": b_vols},
        AnomalyParams(),
        warmup=_WARMUP,
    )
    # BBB (evento en 40 → entrada 41) antes que AAA (evento en 55 → entrada 56)
    assert entries == [("BBB", 41), ("AAA", 56)]


def test_build_entries_skips_ticker_with_bad_volume():
    bars, vols = _flat_series(60)
    _inject(bars, vols, 40, jump=5.0, vol_mult=5.0)
    entries = build_anomaly_entries(
        {"AAA": bars, "BAD": bars},
        {"AAA": vols, "BAD": vols[:10]},  # volumen desalineado → se saltea
        AnomalyParams(),
        warmup=_WARMUP,
    )
    assert entries == [("AAA", 41)]


def test_deterministic():
    bars, vols = _flat_series(60)
    _inject(bars, vols, 40, jump=5.0, vol_mult=5.0)
    p = AnomalyParams(k=1.5, m=3.0)
    r1 = detect_anomalies(bars, vols, p, warmup=_WARMUP)
    r2 = detect_anomalies(bars, vols, p, warmup=_WARMUP)
    assert r1 == r2 == [40]
