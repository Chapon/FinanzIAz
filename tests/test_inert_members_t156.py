"""Tarea 156 — un miembro del cohorte que no puede producir ni una entrada tiene que decirlo.

Yahoo **corrompió el registro de AVB** (le reseteó el `firstTradeDate` al 2026-07-17 y le
metió un split fantasma de 2,793) y devuelve **27 filas para cualquier período**. Durante
el refresh de la 140 ese frame se re-bajó por error —AVB estaba en
`ARTIFACT_REFRESH_EXCEPTIONS` justamente porque refrescarlo es destructivo— y su histórico
de ~2.500 barras se perdió: el cache Parquet no tiene backup.

**Lo que queda, y es lo que este archivo cubre:** con 27 barras y warmup 250 AVB no puede
generar una sola entrada, pero sigue en `bars_by`, así que la población declara **127** y
ninguna línea aclara que uno de esos 127 es inerte. Y los dos guards que uno esperaría
que lo vieran no lo ven, **por diseño**:

* `signal_store_gaps` saltea al que tiene `len(bars) <= warmup` (no hay fechas que
  precomputar — correcto para lo suyo, ciego para esto);
* `stale_artifacts` no lo mira porque está declarado como excepción de refresh.

Encima su artefacto PIT sigue diciendo `n_bars: 2514, complete: True`: describe un frame
que ya no existe.

**Esto declara y no aborta, a propósito.** El frame no se puede reparar desde acá —medido
otra vez el 2026-09-10: Yahoo sigue devolviendo 27 filas, y sin barras nuevas desde el
2026-08-24—, así que abortar convertiría una situación conocida en un bloqueo de todas las
corridas. Sacar AVB del universo mueve la población de 127 a 126 y obliga a **re-anclar 17
constantes**: es la decisión de fondo de la 156, no un efecto lateral de un chequeo.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from analysis.harness_config import (
    announce_inert_members,
    announce_signal_store,
    inert_members,
)

_REPO = Path(__file__).resolve().parent.parent


def _bars(n: int) -> list[tuple]:
    return [(f"2026-01-{i:02d}", 1.0, 1.0, 1.0, 1.0) for i in range(1, n + 1)]


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Redirige el store PIT a un tmp y devuelve un escritor de artefactos."""
    import scripts.precompute_pit_signals as pre

    monkeypatch.setattr(pre, "OUT_DIR", tmp_path)

    def escribir(ticker: str, *, n_bars: int, warmup: int = 2, cubre: list[tuple] | None = None):
        blob = {
            "schema_version": pre.SCHEMA_VERSION,
            "complete": True,
            "n_bars": n_bars,
            # El store se compara contra las **fechas** del frame, así que un artefacto
            # "sano" tiene que cubrirlas: si no, el que se queja es el guard de cobertura
            # y no se llega a ver el de miembros inertes.
            "signals": {b[0]: ["BUY", 0.5] for b in (cubre or [])},
        }
        (tmp_path / f"{ticker}__10y__w{warmup}.json").write_text(json.dumps(blob), encoding="utf-8")

    return escribir


# ── El predicado ─────────────────────────────────────────────────────────────


def test_un_miembro_con_menos_barras_que_el_warmup_es_INERTE():
    inertes = inert_members({"OK": _bars(10), "CORTO": _bars(3)}, "10y", 5)
    assert [m.ticker for m in inertes] == ["CORTO"]
    assert inertes[0].n_bars == 3 and inertes[0].warmup == 5


def test_el_borde_es_ESTRICTO_y_no_arbitrario():
    """Con exactamente `warmup` barras no queda **ninguna** fecha evaluable: la primera
    señal sale en la barra `warmup`, o sea que hacen falta `warmup + 1`. Es el mismo
    borde que usa `signal_store_gaps` para saltear, y por eso son consistentes."""
    assert [m.ticker for m in inert_members({"X": _bars(5)}, "10y", 5)] == ["X"]
    assert inert_members({"X": _bars(6)}, "10y", 5) == ()


def test_un_cohorte_sano_no_declara_nada():
    assert inert_members({"A": _bars(300), "B": _bars(280)}, "10y", 250) == ()


def test_un_frame_vacio_tambien_es_inerte():
    assert [m.ticker for m in inert_members({"VACIO": []}, "10y", 250)] == ["VACIO"]


def test_declara_lo_que_el_artefacto_PIT_dice_que_tiene(store):
    """**La mitad que hace ver el desastre.** El número del artefacto contra el número
    del frame: `2514` vs `27` no es un frame corto, es un artefacto que describe otro
    frame."""
    store("AVB", n_bars=2514)
    (inerte,) = inert_members({"AVB": _bars(2)}, "10y", 2)
    assert inerte.pit_n_bars == 2514
    assert "2514" in str(inerte) and "2 barras" in str(inerte)


def test_sin_artefacto_no_inventa_el_numero():
    (inerte,) = inert_members({"NUEVO": _bars(2)}, "10y", 2)
    assert inerte.pit_n_bars is None
    assert "artefacto PIT" not in str(inerte)


# ── La declaración ───────────────────────────────────────────────────────────


def test_en_el_caso_sano_NO_imprime_nada():
    """Va adentro de un guard que corren los 21 runners: si hablara siempre, sería ruido
    en cada corrida y el aviso real se perdería entre 20 líneas iguales."""
    buf = io.StringIO()
    assert announce_inert_members({"A": _bars(300)}, "10y", 250, file=buf) == ()
    assert buf.getvalue() == ""


def test_cuando_hay_uno_lo_nombra_con_los_dos_numeros(store):
    store("AVB", n_bars=2514)
    buf = io.StringIO()
    inertes = announce_inert_members({"AVB": _bars(2), "OK": _bars(300)}, "10y", 2, file=buf)
    texto = buf.getvalue()
    assert len(inertes) == 1
    assert "AVB" in texto and "2514" in texto and "0 entradas" in texto
    assert "1 de 2" in texto, "tiene que decir cuántos de cuántos"


def test_declara_pero_NO_aborta(store):
    """La corrida sigue: el frame no se puede arreglar desde acá y la decisión de sacarlo
    del universo es de Chapa (tarea 156). Un chequeo que frena todo no la ayuda a
    tomarla."""
    store("AVB", n_bars=2514)
    announce_inert_members({"AVB": _bars(2)}, "10y", 2, file=io.StringIO())  # no levanta


def test_el_aviso_sale_pegado_a_la_cobertura_del_store(store):
    """Cableado **adentro** de `announce_signal_store` para llegar a los 21 runners sin
    editar 21 archivos — y por eso mismo hay que verificar que salga por ahí.

    Con la cobertura **sana**, que es el caso de hoy: el store cubre a los 127 y AVB ni
    aparece en ese chequeo porque tiene menos barras que el warmup.
    """
    sanas = _bars(300)
    store("AVB", n_bars=2514)
    store("OK", n_bars=300, cubre=sanas)
    buf = io.StringIO()
    faltantes = announce_signal_store({"AVB": _bars(2), "OK": sanas}, "10y", 2, strict=True, file=buf)
    texto = buf.getvalue()
    assert faltantes == {}, "la cobertura tenía que dar sana en este montaje"
    assert "sin fechas pendientes" in texto
    assert "Miembros INERTES" in texto


def test_y_tambien_sale_cuando_la_cobertura_esta_CORTA(store):
    """La otra salida de la misma función. Son dos caminos distintos en el código, y un
    aviso cableado en uno solo se pierde justo cuando más cosas están mal a la vez."""
    store("AVB", n_bars=2514)
    store("OK", n_bars=300)  # sin cubrir ninguna fecha ⇒ el store está corto
    buf = io.StringIO()
    announce_signal_store({"AVB": _bars(2), "OK": _bars(300)}, "10y", 2, strict=False, file=buf)
    texto = buf.getvalue()
    assert "SIN señal precomputada" in texto
    assert "Miembros INERTES" in texto


# ── El caso real ─────────────────────────────────────────────────────────────


def test_el_cohorte_vivo_ya_no_tiene_miembros_INERTES():
    """**Decisión de Chapa 2026-09-10: se fue por la (a)** — AVB salió de la watchlist de la
    cuenta viva, del universo del harness y del store PIT, y las anclas se re-midieron.

    Este test decía lo contrario hasta hoy (*«el cohorte vivo declara a AVB»*), y era
    correcto entonces: existía para avisar el día que la respuesta de la 156 cambiara.
    Cambió porque se decidió, no porque Yahoo repare nada.

    Ahora afirma lo que quedó: **el cohorte vivo no tiene ningún miembro inerte**. Si
    apareciera otro —un ticker nuevo sin historia, un frame que se corrompe— esto se pone
    rojo y hay que decidir igual que con AVB. Se saltea sin sustrato (lección 107).
    """
    from scripts.precompute_pit_signals import parse_universe_file
    from scripts.run_scaleout_replay_t7 import load_bars_and_signals

    universo = _REPO / "data" / "harness_universe_live_acct2.txt"
    if not universo.exists():
        pytest.skip("sin universo vivo en esta máquina")
    tickers = parse_universe_file(universo)
    assert "AVB" not in tickers, "AVB volvió al universo: ver la decisión de la tarea 156"
    bars_by, _, _, _ = load_bars_and_signals(tickers, "10y", 250)
    if len(bars_by) < 10:
        pytest.skip("sin artefactos suficientes en esta máquina")
    assert inert_members(bars_by, "10y", 250) == (), (
        "apareció un miembro inerte en el cohorte vivo: hay que decidir qué hacer con él "
        "(la 156 es el precedente), no bajarle el warmup"
    )


def test_el_artefacto_PIT_de_AVB_salio_del_store():
    """La otra mitad de la decisión: el artefacto que declaraba `n_bars: 2514` sobre un
    frame de 27 barras **ya no está en el store**.

    Se preservó fuera del store (`backups/`) porque sus 2.264 señales son lo último que
    queda del histórico sano de AVB —el frame se perdió— y borrarlo habría sido destruir
    evidencia irrecuperable por segunda vez en la misma tarea.
    """
    assert not list((_REPO / "data" / "pit_signals").glob("AVB__*.json")), (
        "el artefacto PIT de AVB volvió al store: miente sobre un frame que no existe"
    )
