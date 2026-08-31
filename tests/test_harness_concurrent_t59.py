"""HARNESS-CONCURRENT (tarea 59) — un solo dueño por cache-dir.

Cerrando la 51 pasó en vivo: la corrida cortada de una sesión anterior seguía viva
cuando se lanzó la nueva. Las dos escribieron el mismo ``--cache-dir`` y el mismo
artefacto — el log quedó entrelazado y el JSON final lo escribieron las dos. Se
descartó ese cache y se re-corrió con un solo proceso (la corrida limpia dio
idéntica campo por campo, así que aquel veredicto no quedó contaminado), pero eso
fue **conducta, no defensa**.

Lo caro es que **nada lo detecta después**: un ``.pkl`` mezclado se lee como un
``PortfolioResult`` cualquiera y entra a un veredicto sin dejar rastro. De ahí las
dos cosas que estos tests fijan:

1. **El cache-dir tiene un solo dueño vivo**, con lock de archivo — si el dueño se
   muere, el sistema operativo lo suelta solo y no quedan locks rancios.
2. **El temporal es único por proceso.** El ``.tmp`` de nombre fijo era el punto
   filoso, y un test lo pinea para que nadie lo revierta sin enterarse.
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path

import pytest

from analysis import harness_config as hc


# ── Helpers ───────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_locks_leaked():
    """Los locks son estado de módulo: no cruzarlos entre tests."""
    hc._held_locks.clear()
    yield
    hc._held_locks.clear()


def _simular_otro_proceso() -> dict:
    """Suelta el registro local **sin cerrar los handles**, y los devuelve.

    Es lo que hace falta para probar la contención dentro de un solo proceso: el
    registro es lo que mantiene vivo el descriptor, así que hay que quedarse con
    una referencia o el sistema operativo suelta el lock — que es, exactamente, la
    propiedad por la que se eligió un lock de archivo y no un PID guardado.
    """
    vivos = dict(hc._held_locks)
    hc._held_locks.clear()
    return vivos


# ── El lock del cache-dir ─────────────────────────────────────────────────────


def test_the_second_run_on_the_same_cache_dir_is_refused(tmp_path):
    d = tmp_path / "cache"
    hc.lock_cache_dir(d)
    vivos = _simular_otro_proceso()

    with pytest.raises(hc.CacheDirBusy):
        hc.lock_cache_dir(d)

    assert vivos  # el handle del "otro proceso" sigue abierto


def test_the_error_names_the_culprit(tmp_path):
    """Sin esto el operador ve «ocupado» y no sabe a quién matar."""
    d = tmp_path / "cache"
    hc.lock_cache_dir(d)
    vivos = _simular_otro_proceso()

    with pytest.raises(hc.CacheDirBusy) as exc:
        hc.lock_cache_dir(d)

    assert str(os.getpid()) in str(exc.value)
    assert "--cache-dir" in str(exc.value)  # dice qué hacer, no sólo qué pasó
    assert vivos


def test_a_different_cache_dir_is_free(tmp_path):
    hc.lock_cache_dir(tmp_path / "uno")
    _simular_otro_proceso()
    hc.lock_cache_dir(tmp_path / "dos")  # no levanta


def test_asking_twice_in_the_same_process_is_idempotent(tmp_path):
    """Un runner que arme dos SimCache sobre el mismo dir no puede chocar consigo mismo."""
    d = tmp_path / "cache"
    assert hc.lock_cache_dir(d) == d
    assert hc.lock_cache_dir(d) == d


def test_releasing_the_handle_frees_the_dir(tmp_path):
    """Es la propiedad que hace que no existan locks rancios.

    Soltar el descriptor es lo que hace el sistema operativo cuando el proceso
    termina —incluso si lo matan a mitad de corrida—, así que después de eso el
    cache-dir tiene que quedar libre sin que nadie limpie nada a mano.
    """
    d = tmp_path / "cache"
    hc.lock_cache_dir(d)
    for fh in _simular_otro_proceso().values():
        fh.close()  # el "otro proceso" murió

    hc.lock_cache_dir(d)  # no levanta: no hay lock rancio que limpiar


def test_the_owner_file_is_written_and_readable(tmp_path):
    d = tmp_path / "cache"
    hc.lock_cache_dir(d)
    quien = hc.describe_owner(d)
    assert str(os.getpid()) in quien


def test_describe_owner_without_a_cache_dir_does_not_explode(tmp_path):
    assert "otro proceso" in hc.describe_owner(tmp_path / "no-existe")


def test_a_filesystem_that_cannot_lock_fails_OPEN(tmp_path, monkeypatch, capsys):
    """Fail-open declarado: no poder tomar el lock no puede romper una corrida buena.

    Es el default conservador que la 52 tuvo que restaurar por el otro eje — un
    guard nuevo que mata corridas buenas es peor que el problema que resuelve.
    """

    def _boom(fh):
        raise OSError("este FS no soporta locks")

    monkeypatch.setattr(hc, "_lock_exclusive", _boom)
    d = tmp_path / "cache"
    assert hc.lock_cache_dir(d) == d
    assert "AVISO" in capsys.readouterr().err


# ── El temporal único por proceso ─────────────────────────────────────────────


def test_the_temp_file_is_unique_per_call(tmp_path):
    from scripts.run_stop_value_t37 import _tmp_for

    f = tmp_path / "abc123.pkl"
    a, b = _tmp_for(f), _tmp_for(f)
    assert a != b


def test_the_temp_file_carries_the_pid(tmp_path):
    """Pinea el arreglo: con el nombre fijo de antes, dos procesos escribían el mismo."""
    from scripts.run_stop_value_t37 import _tmp_for

    f = tmp_path / "abc123.pkl"
    tmp = _tmp_for(f)
    assert str(os.getpid()) in tmp.name
    assert tmp != f.with_suffix(".tmp"), "volvió el nombre fijo por tag"
    assert tmp.parent == f.parent, "el replace tiene que ser dentro del mismo dir"


def test_the_cache_round_trips_and_leaves_no_temp_behind(tmp_path):
    from scripts.run_stop_value_t37 import SimCache

    c = SimCache(tmp_path / "cache", None)
    assert c.run("tag-a", lambda: {"x": 1}) == {"x": 1}
    assert c.run("tag-a", lambda: {"x": 2}) == {"x": 1}  # el segundo es hit
    assert (c.hits, c.misses) == (1, 1)
    assert list((tmp_path / "cache").glob("*.tmp*")) == []


def test_two_tags_do_not_share_a_file(tmp_path):
    from scripts.run_stop_value_t37 import SimCache

    c = SimCache(tmp_path / "cache", None)
    c.run("tag-a", lambda: "A")
    c.run("tag-b", lambda: "B")
    pkls = sorted((tmp_path / "cache").glob("*.pkl"))
    assert len(pkls) == 2
    assert {pickle.loads(p.read_bytes()) for p in pkls} == {"A", "B"}


def test_simcache_without_a_dir_locks_nothing(tmp_path):
    """El default (sin ``--cache-dir``) no toca el disco ni toma locks."""
    from scripts.run_stop_value_t37 import SimCache

    SimCache(None, None)
    assert hc._held_locks == {}


def test_simcache_takes_the_lock(tmp_path):
    from scripts.run_stop_value_t37 import SimCache

    d = tmp_path / "cache"
    SimCache(d, None)
    assert str(Path(d).resolve()) in hc._held_locks


# ── Los tres runners abortan temprano ─────────────────────────────────────────
# El lock vive en ``SimCache``, que es por donde pasan los tres, así que la
# protección no depende de que quien escriba el próximo harness se acuerde. Estos
# tests son el par de eso: verifican que cada runner **traduce** el choque en una
# salida limpia en vez de un traceback a mitad de corrida.


@pytest.mark.parametrize(
    "modulo",
    [
        "scripts.run_stop_value_t37",
        "scripts.run_event_timestop_t51",
        "scripts.run_trail_arm_t54",
    ],
)
def test_a_runner_aborts_early_when_the_cache_dir_is_busy(modulo, tmp_path, capsys):
    import importlib

    d = tmp_path / "cache"
    hc.lock_cache_dir(d)
    vivos = _simular_otro_proceso()

    rc = importlib.import_module(modulo).main(["--cache-dir", str(d)])

    assert rc == 2, "tiene que salir con código de error, no seguir"
    assert "ABORTA" in capsys.readouterr().err
    assert vivos
