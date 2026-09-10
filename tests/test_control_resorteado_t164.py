"""Tarea 164 — el control igualado deja de re-sortearse con cada refresh.

`random_stop_filter` es el **control post-hoc** del sanity de oráculo: suprime la misma
proporción de stops que el oráculo *sin elegir cuáles*. Si el oráculo no le gana, el
harness responde al **número** de stops y no a su **calidad**, y el sanity no podía pasar
por construcción. Hasta el 2026-09-10 ese control sorteaba con
``(semilla, fecha, índice de barra)``, y eso lo rompía por los dos lados:

* **el índice se mueve con la ventana.** Un refresh que corre el ``start`` del cohorte
  desplaza todos los índices ⇒ el control se **re-sortea entero**. Medido antes de
  arreglarlo: recortando 24 barras de la cabeza de un frame de 200, **el 51% de las
  decisiones se da vuelta para las mismas fechas** (90 de 176).
* **sin ticker, era una moneda por fecha.** Dos tickers con la misma fecha recibían la
  **misma** decisión (176 de 176), así que el control suprimía stops en bloque el mismo
  día en toda la cartera — y le inflaba la varianza del drawdown, que es justo la métrica
  con la que se lo compara.

**Lo que costó:** el ``ΔmaxDD`` del oráculo contra el control pasó de **−15.19 pp** (T26b,
2026-08-16) y **−17.59 pp** (T37, 2026-08-27) a **−4.30 pp** (2026-09-10), cruzando el
umbral de −5.00 pp ⇒ ``oracle_quality_ok`` en falso ⇒ **dos corridas con veredicto
publicado VÁLIDO pasaron a INVÁLIDAS** (T37 y T47), y la del T37 es el **SHIP que justificó
cablear el mecanismo de stops** (tarea 53). Era la tarea **40**, declarada el 2026-08-19 y
no migrada.

**Ningún umbral se tocó acá, y es deliberado:** mover el umbral para que la corrida pase
sería arreglar el termómetro cambiándole las marcas. Lo que se arregla es el sorteo; si con
un control estable el T37 sigue inválido, eso es un hallazgo sobre la decisión cableada y
tiene su propia tarea.
"""

from __future__ import annotations

import pytest

from scripts.run_stop_cal_replay_t26 import (
    RANDOM_KEEP_PROB,
    _anti_oracle_stop_filter,
    _oracle_stop_filter,
    random_stop_filter,
)


def _bars(n: int, *, desde: int = 0) -> list[tuple]:
    """``n`` barras con fechas reales y distinguibles, arrancando en ``desde``."""
    return [
        (f"2016-{1 + d // 28:02d}-{1 + d % 28:02d}", 100.0, 101.0, 99.0, 100.0)
        for d in range(desde, desde + n)
    ]


# ── El invariante que la tarea viene a instalar ──────────────────────────────


def test_recortar_la_cabeza_del_frame_NO_cambia_una_sola_decision():
    """**El corazón de la 164, y la prueba por mutación del kill-criteria.**

    Es exactamente lo que hace un refresh que mueve el `start`: las mismas fechas, con
    otros índices. Antes del arreglo, el 51% de las decisiones se daba vuelta acá.
    """
    f = random_stop_filter(RANDOM_KEEP_PROB)
    largo = _bars(200)
    corto = largo[24:]  # la cabeza se va, como en un refresh

    antes = {largo[i][0]: f(largo, i, "AAPL") for i in range(24, len(largo))}
    despues = {corto[i][0]: f(corto, i, "AAPL") for i in range(len(corto))}

    comunes = set(antes) & set(despues)
    assert len(comunes) == 176, "el montaje tiene que comparar las mismas 176 fechas"
    distintas = {d for d in comunes if antes[d] != despues[d]}
    assert not distintas, f"{len(distintas)} de {len(comunes)} decisiones cambiaron por el recorte"


def test_agregar_barras_por_la_COLA_tampoco_mueve_nada():
    """La otra mitad del mismo refresh: el cohorte crece por la cola todas las ruedas."""
    f = random_stop_filter(RANDOM_KEEP_PROB)
    corto, largo = _bars(100), _bars(130)
    assert [f(corto, i, "MSFT") for i in range(100)] == [f(largo, i, "MSFT") for i in range(100)]


def test_dos_tickers_reciben_sorteos_DISTINTOS():
    """Sin el ticker en la clave esto daba 176 de 176 **idénticas**: el control suprimía
    en bloque el mismo día en toda la cartera, que no es *«sin elegir»* — es elegir por
    fecha, y es lo que le infla la varianza del drawdown."""
    f = random_stop_filter(RANDOM_KEEP_PROB)
    bars = _bars(200)
    a = [f(bars, i, "AAPL") for i in range(len(bars))]
    b = [f(bars, i, "MSFT") for i in range(len(bars))]
    iguales = sum(1 for x, y in zip(a, b, strict=True) if x == y)
    # Dos sorteos independientes coinciden ~la mitad de las veces por azar; lo que NO
    # puede pasar es que coincidan en todas, que era el estado anterior.
    assert iguales < len(bars), "los dos tickers siguen recibiendo el mismo sorteo"
    assert 0.3 < iguales / len(bars) < 0.8, f"coincidencia sospechosa: {iguales}/{len(bars)}"


def test_la_fecha_manda_y_no_la_posicion():
    """El mismo (semilla, ticker, fecha) decide igual aunque la barra esté en otro lugar
    del frame — que es la propiedad que hace reproducible al control."""
    f = random_stop_filter(RANDOM_KEEP_PROB)
    a, b = _bars(50), _bars(50, desde=10)
    fecha = b[0][0]
    i_a = [x[0] for x in a].index(fecha)
    assert f(a, i_a, "NVDA") == f(b, 0, "NVDA")


# ── Lo que NO cambió ─────────────────────────────────────────────────────────


def test_sigue_siendo_determinista_entre_procesos():
    """Dos instancias con la misma semilla deciden igual: el digest no usa ``hash()``,
    que está salteado por proceso. Era el motivo original de la función."""
    bars = _bars(120)
    f1, f2 = random_stop_filter(0.463, seed=42), random_stop_filter(0.463, seed=42)
    assert [f1(bars, i, "KO") for i in range(120)] == [f2(bars, i, "KO") for i in range(120)]


def test_la_semilla_sigue_moviendo_el_sorteo():
    bars = _bars(200)
    a = [random_stop_filter(0.463, seed=42)(bars, i, "KO") for i in range(200)]
    b = [random_stop_filter(0.463, seed=43)(bars, i, "KO") for i in range(200)]
    assert a != b


def test_la_tasa_sigue_siendo_la_declarada():
    """La propiedad que le da sentido al control: suprime **la misma proporción**."""
    bars = _bars(600)
    f = random_stop_filter(RANDOM_KEEP_PROB)
    tasa = sum(f(bars, i, "XOM") for i in range(len(bars))) / len(bars)
    assert abs(tasa - RANDOM_KEEP_PROB) < 0.06, f"tasa {tasa:.3f} vs {RANDOM_KEEP_PROB}"


def test_la_tasa_se_sostiene_ticker_por_ticker():
    """Contraprueba de la independencia: con el sorteo por ticker, cada nombre tiene que
    llegar a la tasa por su cuenta. Un sorteo que colapsara por fecha daría la misma
    secuencia —y la misma tasa— en todos, que es lo que no se puede distinguir mirando
    sólo el agregado."""
    bars = _bars(400)
    f = random_stop_filter(RANDOM_KEEP_PROB)
    tasas = {
        t: sum(f(bars, i, t) for i in range(len(bars))) / len(bars) for t in ("AAPL", "MSFT", "KO", "XOM")
    }
    for t, tasa in tasas.items():
        assert abs(tasa - RANDOM_KEEP_PROB) < 0.08, f"{t}: {tasa:.3f}"
    assert len(set(tasas.values())) > 1, "tasas idénticas entre tickers: ¿el sorteo colapsó?"


def test_sin_ticker_REVIENTA_en_vez_de_volver_al_defecto():
    """Un default silencioso sería el defecto otra vez: con la cadena vacía el sorteo es
    común a toda la cartera. Preferimos que falle ruidoso."""
    f = random_stop_filter(RANDOM_KEEP_PROB)
    with pytest.raises(ValueError, match="necesita el ticker"):
        f(_bars(10), 0, "")


# ── Los filtros oráculo no se tocaron ────────────────────────────────────────


@pytest.mark.parametrize("filtro", [_oracle_stop_filter, _anti_oracle_stop_filter])
def test_los_oraculo_aceptan_la_firma_nueva_y_IGNORAN_el_ticker(filtro):
    """Deciden con el futuro del propio frame, que ya es por ticker. La firma es una sola
    para los tres; el comportamiento de estos dos no cambia."""
    bars = _bars(60)
    assert filtro(bars, 5, "AAPL") == filtro(bars, 5, "MSFT") == filtro(bars, 5)
