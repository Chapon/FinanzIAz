"""Tarea 446 — pares y una serie de referencia a mano cuando la industria de Yahoo no sirve.

Yahoo pone a MARA, una minera de bitcoin, en *Capital Markets*: con la 420 recibía GS, MS y SCHW
(medido el 2026-11-20), bancos de inversión. Su precio sigue al bitcoin.
"""

from __future__ import annotations

from analysis import opinion_claude as oc


def _serie(inicio: float, fin: float, n: int = 30):
    paso = (fin - inicio) / (n - 1)
    return [(f"2026-10-{i + 1:02d}", inicio + paso * i) for i in range(n)]


# Elegido para que la industria de Yahoo SÍ tenga pares guardados: sin el mapa, MARA recibiría
# los bancos; con el mapa, no.
_UNIVERSO = {
    "MARA": ("Financial Services", "Capital Markets"),
    "GS": ("Financial Services", "Capital Markets"),
    "MS": ("Financial Services", "Capital Markets"),
}
_GUARDADAS = {"GS": _serie(500, 520), "MS": _serie(100, 104)}
# Los pares a mano y BTC-USD no están en el cache: llegan por `referencia`, que en la app los baja.
_BAJABLES = {
    "RIOT": _serie(10, 8),
    "CLSK": _serie(12, 9),
    "CIFR": _serie(5, 4),
    "HUT": _serie(20, 15),
    "BTC-USD": _serie(100_000, 85_000),
    "XLF": _serie(50, 49),
}


def _bloque(ticker="MARA", universo=_UNIVERSO):
    return oc.bloque_pares(
        ticker,
        universo.get(ticker, (None, None))[1],
        universo.get(ticker, (None, None))[0],
        universo,
        _GUARDADAS.get,
        referencia=lambda t: _BAJABLES.get(t) or _GUARDADAS.get(t),
    )


def test_mara_recibe_las_mineras_y_no_los_bancos():
    b = _bloque()
    assert [p["ticker"] for p in b["pares"]] == ["RIOT", "CLSK", "CIFR", "HUT"]
    assert "minera de bitcoin" in b["pares_a_mano"]


def test_mara_recibe_el_bitcoin_con_su_motivo():
    ref = _bloque()["referencia"]
    assert ref["ticker"] == "BTC-USD" and ref["20d"] == round(
        (85_000 / _BAJABLES["BTC-USD"][-21][1] - 1) * 100, 1
    )
    assert "bitcoin" in ref["motivo"]


def test_un_ticker_sin_entrada_en_el_mapa_es_como_la_420():
    universo = dict(_UNIVERSO, JPM=("Financial Services", "Capital Markets"))
    b = _bloque("JPM", universo)
    assert [p["ticker"] for p in b["pares"]] == ["GS", "MS"]
    assert "pares_a_mano" not in b and "referencia" not in b


def test_cada_entrada_del_mapa_dice_por_que():
    for ticker, (pares, motivo) in oc.PARES_A_MANO.items():
        assert pares and motivo.strip(), ticker
        assert ticker not in pares
    for ticker, (ref, motivo) in oc.REFERENCIA_A_MANO.items():
        assert ref and motivo.strip(), ticker


def test_el_prompt_explica_los_pares_a_mano():
    assert "pares_a_mano" in oc.SYSTEM_PROMPT and "referencia" in oc.SYSTEM_PROMPT


def test_sube_version_datos():
    assert oc.VERSION_DATOS >= 14
