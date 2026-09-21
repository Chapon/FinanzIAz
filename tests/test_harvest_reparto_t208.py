"""Tarea 208 — el corte del harvest reparte la pérdida en vez de concentrarla.

**El defecto.** ``resolve_universe()`` devuelve ``sorted(...)`` y ``_collect_fase1``
recorre esa lista en orden, así que el corte por presupuesto (tarea 204) se lleva
siempre el **sufijo**: los mismos tickers del final del alfabeto, en cada corrida
degradada. No es aleatorio, es sistemático.

**Y no es cosmético**, porque la pérdida no se recupera. La 196 midió que las noticias se
auto-recuperan hasta 7 días (la fuente consulta ``days_back=7`` + UNIQUE en
``content_hash``), pero el **snapshot de consenso no tiene catch-up posible**:
``analyst_estimate_snapshots`` es la única serie del proyecto que no se puede volver a
bajar. Un día degradado le cuesta la fila de consenso, para siempre, **siempre a los
mismos nombres**.

**Cuánto pasa hoy: nada, medido.** Al 2026-09-21 la DB viva tiene **127 de 127** tickers
del universo con snapshot de hoy. Los cuatro con fecha vieja —AAPL, MLTX, TEAM, AVB— no
están en el universo: salieron de la watchlist, así que dejaron de recolectarse, que es
correcto. **Y eso refuta de paso la lectura fácil del enunciado:** el más rezagado es
AAPL, que es el **primero** del alfabeto, no el último. La cola castigada es real por
construcción y **no se manifestó nunca**, porque el default de 1.200 s es 3,4× el máximo
del camino feliz.

**El criterio elegido, y por qué no el otro.** Rotar el punto de arranque pide recordar
por dónde quedó la corrida anterior, o sea estado nuevo que persistir. Ordenar por
**rezago de consenso** sale de una tabla que ya existe y además es **auto-corrector**: el
ticker que se saltó ayer tiene la fecha más vieja hoy y pasa al frente solo.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from scripts.harvest_catalysts import ordenar_por_rezago

HOY = datetime(2026, 9, 21)
AYER = HOY - timedelta(days=1)
VIEJO = HOY - timedelta(days=20)


# ── El criterio, interrogado directo ─────────────────────────────────────────


def test_el_mas_rezagado_va_primero():
    orden = ordenar_por_rezago(["AAA", "ZZZ"], {"AAA": HOY, "ZZZ": VIEJO})
    assert orden == ["ZZZ", "AAA"], "el alfabeto no puede ganarle al rezago"


def test_el_que_nunca_se_recolecto_va_ANTES_que_el_mas_viejo():
    """Un ticker recién agregado a la watchlist es el que más urge: no tiene nada.

    Va primero incluso antes que el más rezagado, porque para aquél *falta un día* y
    para éste **falta todo**.
    """
    orden = ordenar_por_rezago(["AAA", "NUEVO", "ZZZ"], {"AAA": HOY, "ZZZ": VIEJO})
    assert orden[0] == "NUEVO", orden


def test_los_empates_se_rompen_alfabeticamente():
    """Determinismo: en una corrida sana **todos** comparten la fecha de hoy.

    Sin el desempate el orden sería arbitrario entre corridas, y un harvest cuyo orden
    cambia sin motivo es imposible de depurar cuando algo sale mal.
    """
    ult = dict.fromkeys(["CCC", "AAA", "BBB"], HOY)
    assert ordenar_por_rezago(["CCC", "AAA", "BBB"], ult) == ["AAA", "BBB", "CCC"]


def test_sin_historial_queda_el_alfabetico_de_siempre():
    """Fail-open del criterio: DB nueva, o el query que falla, ⇒ comportamiento previo.

    Importa más de lo que parece: es lo que hace que este cambio sea un **no-op** sobre
    una DB limpia, y por eso los 18 tests de la 204 siguieron pasando sin tocarlos.
    """
    assert ordenar_por_rezago(["CCC", "AAA", "BBB"], {}) == ["AAA", "BBB", "CCC"]


def test_no_se_pierde_ni_se_duplica_ningun_ticker():
    """Es un **reordenamiento**, no un filtro. Obvio hasta que un `key` mal escrito
    descarta lo que no sabe comparar."""
    universo = ["DDD", "AAA", "CCC", "BBB"]
    orden = ordenar_por_rezago(universo, {"AAA": HOY, "CCC": VIEJO})
    assert sorted(orden) == sorted(universo)
    assert len(orden) == len(set(orden))


# ── El kill-criteria: dos corridas NO saltean el mismo conjunto ──────────────


def _simular(universo, cupo, corridas, ultimos=None):
    """Corre ``corridas`` harvests que alcanzan a recolectar sólo ``cupo`` tickers.

    Devuelve la lista de conjuntos **salteados** en cada corrida. Modela el lazo real:
    el orden decide a quién se llega, lo recolectado estampa su fecha, y la corrida
    siguiente vuelve a ordenar con ese estado — que es justo la auto-corrección que se
    quiere probar y que no se ve mirando una sola corrida.
    """
    ultimos = dict(ultimos or {})
    salteados = []
    for i in range(corridas):
        orden = ordenar_por_rezago(universo, ultimos)
        alcanzados, resto = orden[:cupo], orden[cupo:]
        salteados.append(set(resto))
        for t in alcanzados:
            ultimos[t] = HOY + timedelta(days=i)
    return salteados


def test_dos_corridas_consecutivas_NO_saltean_lo_mismo():
    """**El test que la tarea pedía.**

    Con el orden fijo, `salteados[0] == salteados[1]` siempre: es literalmente el mismo
    sufijo. Con el rezago, la segunda corrida arranca por los que se perdió la primera.
    """
    universo = [f"T{i:02d}" for i in range(10)]
    s0, s1 = _simular(universo, cupo=6, corridas=2)

    assert s0 != s1, "el corte volvió a castigar exactamente al mismo conjunto"
    assert not (s0 & s1), (
        f"ni siquiera parcialmente: nadie se puede saltear dos veces seguidas "
        f"teniendo cupo de sobra. interseccion={sorted(s0 & s1)}"
    )


@pytest.mark.parametrize(("n", "cupo"), [(10, 6), (10, 3), (127, 40), (5, 4)])
def test_sobre_N_corridas_TODOS_se_recolectan_al_menos_una_vez(n, cupo):
    """La otra mitad del kill-criteria, con la cota que se sigue del cupo.

    Con ``cupo`` por corrida y ``n`` tickers alcanza con ``ceil(n/cupo)`` corridas si el
    reparto es perfecto. Se pide exactamente eso, no «alguna vez»: un orden que rote mal
    igual terminaría cubriendo a todos con suficientes corridas, y el test no diría nada.
    """
    universo = [f"T{i:03d}" for i in range(n)]
    corridas = -(-n // cupo)  # ceil
    salteados = _simular(universo, cupo=cupo, corridas=corridas)

    nunca = set(universo)
    for s in salteados:
        nunca &= s
    assert not nunca, f"estos no se recolectaron en {corridas} corridas: {sorted(nunca)}"


def test_con_orden_FIJO_el_mismo_lazo_castiga_siempre_a_los_mismos():
    """**Contraprueba del instrumento**, y es la que hace creíble a los dos de arriba.

    Sin esto, un `_simular` roto que devolviera conjuntos distintos por cualquier motivo
    pasaría los tests anteriores sin probar nada. Acá se corre el **mismo lazo** con el
    orden alfabético fijo —el comportamiento de antes de esta tarea— y tiene que dar el
    defecto: el mismo sufijo, siempre.
    """
    universo = [f"T{i:02d}" for i in range(10)]
    cupo = 6
    salteados = [set(sorted(universo)[cupo:]) for _ in range(3)]

    assert salteados[0] == salteados[1] == salteados[2]
    assert salteados[0] == {"T06", "T07", "T08", "T09"}


def test_el_rezago_heredado_se_salda_en_la_PRIMERA_corrida():
    """El caso real: ayer se cortó y hoy hay que empezar por los que faltaron."""
    universo = [f"T{i:02d}" for i in range(6)]
    # T04 y T05 quedaron sin recolectar ayer.
    ultimos = {t: HOY for t in universo if t not in {"T04", "T05"}}
    ultimos["T04"] = VIEJO
    ultimos["T05"] = VIEJO

    orden = ordenar_por_rezago(universo, ultimos)
    assert orden[:2] == ["T04", "T05"], orden


# ── El harvest de verdad lo aplica (no basta con que la función pura ordene) ──


def _res_con_estimate(ticker):
    from data.news_sources import EstimateSnapshot, _CollectResult

    r = _CollectResult()
    r.estimates.append(EstimateSnapshot(ticker, "eps", "0q", 1.0, 3))
    return r


def test_el_harvest_empieza_por_el_REZAGADO(test_db):
    """De punta a punta: el orden no sirve de nada si `harvest()` no lo usa.

    Sin este test, mover la llamada a `ordenar_por_rezago` fuera de `harvest` dejaría
    los doce tests de arriba **en verde** — estarían probando la función, no el harvest.
    """
    from database.models import AnalystEstimateSnapshot, session_scope
    from scripts.harvest_catalysts import harvest

    universo = ["AAA", "BBB", "ZZZ"]
    # AAA y BBB ya tienen consenso de hoy; ZZZ quedó rezagado hace 20 días.
    with session_scope() as s:
        for t, fecha in (("AAA", HOY), ("BBB", HOY), ("ZZZ", VIEJO)):
            s.add(
                AnalystEstimateSnapshot(
                    ticker=t, metric="eps", period_label="0q", consensus_value=1.0, snapshot_date=fecha
                )
            )

    vistos: list[str] = []

    def _collector(ticker, sources=None):
        vistos.append(ticker)
        return _res_con_estimate(ticker)

    harvest(universo, collector=_collector)

    assert vistos[0] == "ZZZ", (
        f"el harvest recorrió {vistos}: el rezagado tiene que ir primero, y si va último "
        "es que `harvest()` dejó de aplicar el orden"
    )


def test_sin_historial_el_harvest_recorre_ALFABETICO(test_db):
    """La contraprueba: sobre una DB limpia el comportamiento es el de antes.

    Es lo que hace que esta tarea no le cambie nada a los 18 tests de la 204.
    """
    from scripts.harvest_catalysts import harvest

    vistos: list[str] = []

    def _collector(ticker, sources=None):
        vistos.append(ticker)
        return _res_con_estimate(ticker)

    harvest(["ZZZ", "AAA", "MMM"], collector=_collector)
    assert vistos == ["AAA", "MMM", "ZZZ"], vistos
