"""Tarea 126 — el archivo de perfiles tiene que cumplir el filtro que declara.

``surprise_profiles.json`` traia ``_meta.min_quarters = 4`` y escribia igual los
perfiles que no lo alcanzan, **con todos los campos en cero**. Produccion no se veia
afectada (``SurpriseProfile.is_usable`` y el gate de ``imminent_catalyst`` los
descartan y caen al ``basis="reaction"``), pero **cualquier lectura ad-hoc del JSON**
ve un ``directional_score: 0.0`` indistinguible de un neutral medido sobre 24
trimestres — que es la trampa de "el numero sale limpio y significa otra cosa".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.surprise_score import MIN_QUARTERS, make_surprise_loader
from scripts.build_surprise_profiles import _payload, split_by_min_quarters

_ARTEFACTO = Path(__file__).resolve().parent.parent / "data" / "catalyst" / "surprise_profiles.json"


def _perfil(n: int, dir_score: float = 0.5) -> dict:
    return {
        "ticker": "X",
        "n_quarters": n,
        "beat_rate": 0.8,
        "miss_rate": 0.1,
        "mean_surprise": 0.02,
        "median_surprise": 0.02,
        "last_surprise": 0.01,
        "directional_score": dir_score,
    }


def test_el_split_saca_los_que_no_llegan_al_minimo():
    usables, cortos = split_by_min_quarters(
        {"BUENO": _perfil(MIN_QUARTERS), "CORTO": _perfil(0, 0.0), "JUSTO": _perfil(MIN_QUARTERS - 1)}
    )
    assert set(usables) == {"BUENO"}
    assert cortos == {"CORTO": 0, "JUSTO": MIN_QUARTERS - 1}


def test_los_cortos_NO_se_pierden_van_al_meta():
    """La mitad que hace que esto sea mejor que borrarlos: *"se intento y no habia
    datos"* es distinto de *"no se intento"*, y esa diferencia se conserva."""
    payload = _payload({"BUENO": _perfil(24), "CORTO": _perfil(0, 0.0)}, n_tickers=2)
    assert set(payload["profiles"]) == {"BUENO"}
    assert payload["_meta"]["insufficient_history"] == {"CORTO": 0}
    assert payload["_meta"]["n_tickers"] == 2, "intentados"
    assert payload["_meta"]["n_profiles"] == 1, "escritos"


def test_el_payload_nunca_escribe_un_perfil_bajo_su_propio_minimo():
    payload = _payload({f"T{i}": _perfil(i) for i in range(0, 30)}, n_tickers=30)
    malos = [t for t, p in payload["profiles"].items() if p["n_quarters"] < payload["_meta"]["min_quarters"]]
    assert malos == []


def test_EL_ARTEFACTO_VIVO_cumple_el_filtro_que_declara():
    """El guard sobre el archivo real, que es lo que los barridos leen."""
    d = json.loads(_ARTEFACTO.read_text(encoding="utf-8"))
    minimo = d["_meta"]["min_quarters"]
    malos = {t: p["n_quarters"] for t, p in d["profiles"].items() if p["n_quarters"] < minimo}
    assert malos == {}, f"perfiles bajo el min_quarters declarado: {malos}"
    assert d["_meta"]["n_profiles"] == len(d["profiles"])


def test_el_artefacto_vivo_NO_esta_vacio():
    """Contraprueba del guard de arriba: con `profiles` vacio tambien daria lista
    vacia y pasaria en verde 'demostrando' que no hay violaciones."""
    d = json.loads(_ARTEFACTO.read_text(encoding="utf-8"))
    assert len(d["profiles"]) > 100, f"solo {len(d['profiles'])} perfiles, el barrido no prueba nada"


def test_un_ticker_sin_historia_cae_al_fallback_documentado():
    """El loader dice: *"Unknown ticker -> None, so `imminent_catalyst` simply falls
    back to its reaction-mean direction"*. Con el perfil de ceros adentro eso NO
    pasaba: devolvia un perfil, y el fallback quedaba desactivado por un neutral
    fabricado. Ahora si."""
    d = json.loads(_ARTEFACTO.read_text(encoding="utf-8"))
    sin_historia = list(d["_meta"]["insufficient_history"])
    if not sin_historia:
        pytest.skip("hoy no hay tickers sin historia suficiente")
    load = make_surprise_loader(d["profiles"])
    assert load(sin_historia[0]) is None
