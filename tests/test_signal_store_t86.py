"""Tarea 86 — el store de señales PIT tiene que cubrir el cohorte, y alguien tiene que mirarlo.

La tarea 69 arregló el **productor**: `pending_dates()` decide por fechas y su
docstring dice que `complete` *"ya no alcanza solo"*. Pero esa función vivía sólo
en los dos `precompute_*`: los **seis** sitios consumidores hacían
`if not blob.get("complete")` y nada más, y `announce_artifacts` —el guard que la
76 cableó a los 21 runners— mira **las barras**, no el store.

O sea que un runner podía **pasar el guard del cohorte y correr igual sobre una
muestra encogida**. Cuando pasó (2026-09-01) movió el universo vivo de 141.777 a
142.670 entradas y obligó a re-medir **17 constantes publicadas** (tarea 68).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from analysis.harness_config import (
    SignalStoreGapError,
    announce_signal_store,
    signal_store_gaps,
)

_REPO = Path(__file__).resolve().parent.parent


def _bars(fechas: list[str]) -> list[tuple]:
    return [(d, 1.0, 1.0, 1.0, 1.0) for d in fechas]


def _dias(n: int, desde: int = 1) -> list[str]:
    return [f"2026-01-{i:02d}" for i in range(desde, desde + n)]


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Redirige el store PIT a un tmp y devuelve un escritor de artefactos."""
    import scripts.precompute_pit_signals as pre

    monkeypatch.setattr(pre, "OUT_DIR", tmp_path)

    def escribir(ticker: str, fechas: list[str], *, complete: bool = True, schema=None):
        blob = {
            "schema_version": pre.SCHEMA_VERSION if schema is None else schema,
            "complete": complete,
            "signals": {d: ["BUY", 0.5] for d in fechas},
        }
        (tmp_path / f"{ticker}__10y__w2.json").write_text(json.dumps(blob), encoding="utf-8")

    return escribir


# ── El barrido ───────────────────────────────────────────────────────────────


def test_sin_huecos_cuando_el_store_cubre_el_cohorte(store):
    store("AAA", _dias(6))
    assert signal_store_gaps({"AAA": _bars(_dias(6))}, "10y", 2) == {}


def test_detecta_la_cola_faltante(store):
    """El caso real: las barras se refrescaron y el store no."""
    store("AAA", _dias(6))
    gaps = signal_store_gaps({"AAA": _bars(_dias(9))}, "10y", 2)
    assert gaps == {"AAA": (3, "2026-01-06")}


def test_compara_contra_las_fechas_CRUDAS_del_artefacto(tmp_path, monkeypatch):
    """**El detalle que hace que el guard sirva.** Los loaders filtran a señal
    *truthy* (`if sv[0]`), así que una fecha evaluada **sin** señal no está en su
    `sigs_by`. Comparar contra eso reportaría un hueco por cada día sin BUY — o
    sea, casi todos. El guard mira las claves del blob, no las señales."""
    import scripts.precompute_pit_signals as pre

    monkeypatch.setattr(pre, "OUT_DIR", tmp_path)
    # Cuatro fechas evaluadas; sólo una tiene señal.
    blob = {
        "schema_version": pre.SCHEMA_VERSION,
        "complete": True,
        "signals": {d: ["", None] for d in _dias(4)},
    }
    blob["signals"]["2026-01-03"] = ["BUY", 0.7]
    (tmp_path / "AAA__10y__w2.json").write_text(json.dumps(blob), encoding="utf-8")

    assert signal_store_gaps({"AAA": _bars(_dias(4))}, "10y", 2) == {}


def test_el_warmup_no_cuenta(store):
    """Las fechas anteriores al warmup no se evalúan nunca, así que no son hueco."""
    store("AAA", _dias(4, desde=3))  # el store arranca en el día 3
    assert signal_store_gaps({"AAA": _bars(_dias(6))}, "10y", 2) == {}


def test_un_ticker_sin_artefacto_no_es_hueco(store):
    """El loader ya lo excluye y lo reporta como `missing`: contarlo acá sería
    reportar dos veces la misma cosa, y encima como si fuera otra."""
    assert signal_store_gaps({"ZZZ": _bars(_dias(6))}, "10y", 2) == {}


def test_varios_tickers_se_reportan_por_separado(store):
    store("AAA", _dias(6))
    store("BBB", _dias(4))
    gaps = signal_store_gaps({"AAA": _bars(_dias(6)), "BBB": _bars(_dias(6))}, "10y", 2)
    assert set(gaps) == {"BBB"} and gaps["BBB"][0] == 2


def test_un_artefacto_con_schema_viejo_cuenta_como_ausente(store):
    """`_load_existing` descarta un blob de otra `schema_version`, así que el guard
    lo ve como *sin artefacto* — no como un hueco. Es lo correcto: el loader
    tampoco lo va a cargar, y reportarlo como cobertura faltante mandaría a
    re-correr el precompute cuando lo que hay que hacer es migrar el esquema."""
    store("AAA", _dias(6), schema="viejo")
    assert signal_store_gaps({"AAA": _bars(_dias(9))}, "10y", 2) == {}


# ── El anuncio ───────────────────────────────────────────────────────────────


def test_el_caso_sano_dice_que_esta_sano(store, capsys):
    store("AAA", _dias(6))
    announce_signal_store({"AAA": _bars(_dias(6))}, "10y", 2, strict=True)
    assert "sin fechas pendientes" in capsys.readouterr().out


def test_falla_ruidoso_y_nombra_al_peor(store, capsys):
    store("AAA", _dias(6))
    store("BBB", _dias(3))
    with pytest.raises(SignalStoreGapError) as exc:
        announce_signal_store({"AAA": _bars(_dias(9)), "BBB": _bars(_dias(9))}, "10y", 2, strict=True)
    salida = capsys.readouterr().out
    assert "BBB" in str(exc.value)  # el peor va en el mensaje del error
    assert "precompute_pit_signals" in salida  # y el aviso dice qué correr


def test_sin_strict_declara_pero_no_aborta(store, capsys):
    """Para un harness que a propósito corre sobre un store corto y lo dice en su
    pre-registro — misma política que `announce_artifacts`."""
    store("AAA", _dias(6))
    gaps = announce_signal_store({"AAA": _bars(_dias(9))}, "10y", 2, strict=False)
    assert gaps and "SIN señal precomputada" in capsys.readouterr().out


# ── El cableado ──────────────────────────────────────────────────────────────


# Lee el cohorte de BARRAS pero **no** el store de señales: son dos sustratos, y
# hasta la 102 ninguno los usaba por separado, así que el predicado de las barras
# alcanzaba como proxy del store. Dejó de alcanzar — y la exclusión va con motivo
# escrito, no por prefijo (mismo criterio que la 101).
_NO_LEE_EL_STORE = {
    "run_exit_replay_t61.py": (
        "Replaya SELL fills REALES de la DB, no señales precomputadas: cero "
        "referencias a `data/pit_signals/` en todo el archivo. Sí lee las barras, "
        "así que le corresponde `announce_artifacts` — y lo llama."
    ),
}


def _runners_del_cohorte() -> list[tuple[str, str]]:
    out = []
    for p in sorted((_REPO / "scripts").glob("run_*.py")):
        if p.name in _NO_LEE_EL_STORE:
            continue
        txt = p.read_text(encoding="utf-8")
        if re.search(r"load_bars_signals|load_bars_and_signals|parquet_cache\.read|artifact_window\(", txt):
            out.append((p.name, txt))
    return out


def test_lo_excluido_del_store_sigue_sin_leerlo():
    """Una exclusión escrita a mano caduca sola. Ésta se re-verifica contra el
    archivo: si el runner empieza a leer señales PIT, vuelve a la población."""
    for nombre, motivo in _NO_LEE_EL_STORE.items():
        ruta = _REPO / "scripts" / nombre
        assert ruta.exists(), f"excluido inexistente: {nombre}"
        assert len(motivo) > 40, f"exclusión sin motivo escrito: {nombre}"
        txt = ruta.read_text(encoding="utf-8")
        codigo = "\n".join(ln for ln in txt.splitlines() if not ln.lstrip().startswith("#"))
        assert "pit_signals" not in codigo, f"{nombre} empezó a leer el store: sacarlo de la lista"
        assert "load_bars_signals" not in codigo, f"{nombre} empezó a leer el store"


def test_hay_poblacion_de_runners():
    assert len(_runners_del_cohorte()) >= 20


def test_todos_los_runners_del_cohorte_chequean_el_store():
    """El guard es del **sustrato compartido**, igual que el de la 76: cablearlo en
    uno solo no protege nada. Los dos se llaman juntos porque preguntan lo mismo
    —*¿la muestra es la que digo que es?*— sobre los dos sustratos."""
    faltan = [n for n, txt in _runners_del_cohorte() if "announce_signal_store(" not in txt]
    assert faltan == [], f"leen el cohorte y no chequean el store de señales: {faltan}"


def test_el_abort_cubre_las_dos_excepciones():
    """Si el `except` sólo atrapa `StaleArtifactError`, el guard nuevo aborta con
    traceback en vez del mensaje limpio y el código de salida 3."""
    malos = [
        n
        for n, txt in _runners_del_cohorte()
        if "announce_signal_store(" in txt and "SignalStoreGapError" not in txt
    ]
    assert malos == [], f"no atrapan SignalStoreGapError: {malos}"
