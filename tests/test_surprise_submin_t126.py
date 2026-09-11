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
    fabricado. Ahora si.

    **Tarea 174 — el sujeto se MONTA, no se toma del artefacto vivo.** Hasta el
    2026-09-11 este test leia `_meta.insufficient_history` del JSON real y hacia
    `pytest.skip` si estaba vacio. Se vacio: AVB era su unico miembro y la 156 lo saco
    del universo, asi que la afirmacion que esta tarea existe para probar dejo de
    ejercitarse **por un cambio de datos y no por una decision**. Lo que el caso
    necesita es *"un perfil bajo el minimo"*, no *"el que hoy este en el artefacto"* —
    el mismo *literal derivado vs montaje* de la 166, y la misma forma de la 110 y la
    101 (la poblacion sale de lo mismo que puede vaciarse). El `payload` se construye
    con el `_payload` de produccion, asi que lo que se prueba sigue siendo el contrato
    real y no una reimplementacion.
    """
    payload = _payload({"BUENO": _perfil(24), "CORTO": _perfil(MIN_QUARTERS - 1)}, n_tickers=2)
    assert "CORTO" in payload["_meta"]["insufficient_history"], "montaje inutil: el corto no salio"

    load = make_surprise_loader(payload["profiles"])
    assert load("CORTO") is None, "el sub-minimo devolvio perfil: el fallback queda desactivado"
    assert load("BUENO") is not None, "contraprueba: el loader tiene que resolver a los usables"


def test_el_artefacto_vivo_es_COHERENTE_con_su_insufficient_history():
    """La pata sobre el archivo real, separada de la de arriba a proposito (tarea 174).

    **Puede quedar vacia y esta bien** — hoy lo esta—, y por eso no lleva `skip`: lo que
    hace legitima la vacuidad es que el contrato ya se prueba arriba con un montaje que
    no depende de los datos. Aca lo unico que se verifica es que las dos mitades del
    artefacto no se contradigan: nadie puede estar en `insufficient_history` **y** en
    `profiles`, porque entonces el loader lo resolveria y el fallback no correria.
    """
    d = json.loads(_ARTEFACTO.read_text(encoding="utf-8"))
    sin_historia = set(d["_meta"]["insufficient_history"])
    solapados = sin_historia & set(d["profiles"])
    assert not solapados, f"estan en las dos mitades del artefacto: {sorted(solapados)}"

    load = make_surprise_loader(d["profiles"])
    assert all(load(t) is None for t in sin_historia)
