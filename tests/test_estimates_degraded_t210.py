"""Tarea 210 — el veredicto de `_yf_estimates` deja de ser ciego adentro de yfinance.

**La mecánica del hueco.** `_yf_estimates` lee **cuatro** propiedades del `Ticker`
(`earnings_estimate`, `revenue_estimate`, `analyst_price_targets`, `info`) a través de
`_getattr`, que envuelve cada acceso en su propio `try` **a propósito**: yfinance fetchea
de verdad al acceder a la propiedad, y una que falle no debe hundir a las otras. El `try`
de afuera —el que arma el `SourceOutcome`— sólo ve lo que **escapa**, o sea en la
práctica que `_ticker()` no resuelva. Resultado: una fuente que contestaba 2 de 4 se
declaraba `ok`.

**Y el log del 2026-08-14 lo muestra.** Ese día `yfinance_news` registró 52 fallas de 52
y `yfinance_estimates` **ninguna**. No es que la segunda anduviera bien: es que sus
fallas no se registraban.

**Lo que NO cambió, y es el punto.** El `try` de `_getattr` sigue exactamente igual —
tolerar una propiedad caída es correcto y deliberado. Lo que dejó de pasar es que
tolerar y **ocultar** fueran la misma cosa.

**Por qué `degraded` y no `failed`.** Una propiedad de cuatro no es la fuente caída;
forzar el binario diría de más. Y `degraded` **no entra al gate** de
`SOURCE_FAILURE_ALARM_RATE`: ese umbral se calibró en la 207 contra una población donde
esto era invisible, así que no dice nada sobre cuántos `degraded` tiene un día sano.
Meterlo sería inventar un umbral en vez de calibrarlo — que es justo lo que la 207 se
negó a hacer con `cero_resultados`, y por la misma razón. Se reporta como contexto.
"""

from __future__ import annotations

import pytest

import data.yahoo_finance as yh
from data.news_sources import _SUBFETCHES_DE_ESTIMATES, _getattr, _yf_estimates


def _ticker_fake(**props):
    """Un `Ticker` cuyas propiedades hacen lo que se le pida: valor, None, o reventar.

    Se arma con `property` de verdad y no con un `MagicMock` **a propósito**: lo que se
    está probando es el acceso a **propiedades**, que es donde yfinance fetchea, y un
    mock devuelve atributos sin ejercitar ese camino.
    """

    def _hacer(v):
        if isinstance(v, Exception):

            def _p(self, _v=v):
                raise _v

            return property(_p)
        return property(lambda self, _v=v: _v)

    return type("_TickerFake", (), {k: _hacer(v) for k, v in props.items()})()


_SANAS = {
    "earnings_estimate": None,
    "revenue_estimate": None,
    "analyst_price_targets": {"mean": 123.0},
    "info": {"recommendationMean": 2.0, "numberOfAnalystOpinions": 9},
}


def _correr(monkeypatch, **overrides):
    props = dict(_SANAS)
    props.update(overrides)
    monkeypatch.setattr(yh, "_ticker", lambda s: _ticker_fake(**props))
    return _yf_estimates("NVDA")


# ── Las dos direcciones del kill-criteria ────────────────────────────────────


def test_las_cuatro_sanas_NO_acusan(monkeypatch):
    """La dirección que evita el falso positivo, y es la mitad que más fácil se olvida."""
    items, o = _correr(monkeypatch)
    assert o.status == "ok", o
    assert o.detail == ""
    assert len(items) > 0


def test_una_caida_de_cuatro_da_degraded_y_la_nombra(monkeypatch):
    items, o = _correr(monkeypatch, analyst_price_targets=RuntimeError("timeout de Yahoo"))

    assert o.status == "degraded", o
    assert "analyst_price_targets" in o.detail, "tiene que NOMBRAR la propiedad"
    assert "timeout de Yahoo" in o.detail, "y el motivo"
    assert f"1/{_SUBFETCHES_DE_ESTIMATES}" in o.detail, "y cuántas de cuántas"
    assert len(items) > 0, "lo que sí contestó tiene que entrar igual: tolerar sigue vivo"


def test_las_cuatro_caidas_tambien_es_degraded_y_las_nombra_a_todas(monkeypatch):
    """**El borde, y la decisión de no escalarlo a `failed`.**

    Con las cuatro caídas la fuente no trajo nada, así que la tentación es declararla
    `failed`. No se hace, y el motivo es el mismo que para no meter `degraded` al gate:
    hoy **no hay población** que diga con qué frecuencia pasa en un día sano (nunca se
    registró), así que el umbral *«todas ⇒ caída»* sería inventado. El reporte dice
    cuántas se cayeron y quien lo lee decide; si algún día hay datos, se calibra.
    """
    boom = RuntimeError("boom")
    items, o = _correr(
        monkeypatch,
        earnings_estimate=boom,
        revenue_estimate=boom,
        analyst_price_targets=boom,
        info=boom,
    )

    assert o.status == "degraded", o
    assert f"{_SUBFETCHES_DE_ESTIMATES}/{_SUBFETCHES_DE_ESTIMATES}" in o.detail
    for nombre in _SANAS:
        assert nombre in o.detail, f"{nombre} no aparece en {o.detail!r}"
    assert items == []


def test_el_ticker_que_no_resuelve_sigue_siendo_FAILED(monkeypatch):
    """`degraded` no se come al `failed` que ya existía: son dos cosas distintas.

    Si `_ticker()` revienta no hubo fuente en absoluto, y eso **sí** es una falla que
    entra al gate calibrado de la 207.
    """

    def _explota(_s):
        raise RuntimeError("no resuelve")

    monkeypatch.setattr(yh, "_ticker", _explota)
    items, o = _yf_estimates("NVDA")
    assert o.status == "failed", o
    assert items == []


# ── None no es una falla ─────────────────────────────────────────────────────


def test_una_propiedad_que_devuelve_None_NO_es_una_falla(monkeypatch):
    """La distinción que define todo: **levantar** vs **devolver vacío**.

    Un ticker sin price targets devuelve `None` sin excepción, y eso es normal y
    frecuente. Contarlo como falla sería el mismo error que la 207 arregló un nivel más
    arriba, donde `[]` significaba a la vez *«no había nada»* y *«se cayó»* — o sea
    reintroducir el defecto adentro de su propio arreglo.
    """
    _items, o = _correr(monkeypatch, analyst_price_targets=None, info=None)
    assert o.status == "ok", f"None no puede contar como caída: {o}"


# ── `_getattr`, la pieza de abajo ────────────────────────────────────────────


def test_getattr_sigue_tolerando_y_ahora_anota():
    """Las dos mitades del contrato, en la función misma."""
    caidas: list[str] = []

    class _X:
        @property
        def bomba(self):
            raise ValueError("kaboom")

        @property
        def sana(self):
            return 7

    x = _X()
    assert _getattr(x, "sana", caidas) == 7
    assert caidas == [], "una propiedad sana no anota nada"

    assert _getattr(x, "bomba", caidas) is None, "sigue tolerando: devuelve None, no levanta"
    assert len(caidas) == 1 and "bomba" in caidas[0] and "kaboom" in caidas[0]


def test_getattr_sin_lista_sigue_andando():
    """El parámetro es opcional: el fallback de `earnings_dates` llama con dos args."""

    class _X:
        @property
        def bomba(self):
            raise ValueError("kaboom")

    assert _getattr(_X(), "bomba") is None


def test_el_atributo_que_no_existe_no_es_una_caida():
    """`getattr(obj, name, None)` con default no levanta, así que no hay nada que anotar.

    Se fija porque es la diferencia entre *«yfinance cambió de API»* —que se vería como
    datos faltantes— y *«el fetch se cayó»*, y meterlos en la misma bolsa haría que
    cualquier upgrade de yfinance pareciera un outage.
    """
    caidas: list[str] = []
    assert _getattr(object(), "no_existe_esta_propiedad", caidas) is None
    assert caidas == []


# ── El conteo declarado coincide con el código ───────────────────────────────


def test_la_constante_de_sub_fetches_coincide_con_los_getattr_reales():
    """**Un número en un mensaje que nadie verifica es un número que se pudre.**

    El docstring que escribió la 207 decía *«cinco propiedades»* y listaba **cuatro**; el
    enunciado de la 210 heredó el error en un lado y lo corrigió en el otro. Acá se
    cuenta sobre el AST de la función, así que si alguien agrega o saca un sub-fetch y no
    toca la constante, el `detail` deja de mentir por un test en rojo y no por suerte.
    """
    import ast
    import inspect

    import data.news_sources as ns

    arbol = ast.parse(inspect.getsource(ns._yf_estimates))
    llamadas = [
        n
        for n in ast.walk(arbol)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_getattr"
    ]
    assert len(llamadas) == _SUBFETCHES_DE_ESTIMATES, (
        f"`_yf_estimates` hace {len(llamadas)} `_getattr` y la constante dice "
        f"{_SUBFETCHES_DE_ESTIMATES}: el `detail` estaría reportando 'n/{_SUBFETCHES_DE_ESTIMATES}' "
        "sobre un total que no es"
    )
    assert all(len(c.args) == 3 for c in llamadas), (
        "todos los sub-fetches de esta función tienen que pasar la lista de caídas: "
        "uno que no la pase vuelve a ser invisible para el veredicto"
    )


@pytest.mark.parametrize("estado", ["ok", "degraded", "failed", "skipped"])
def test_los_cuatro_estados_son_distinguibles(estado):
    """Las propiedades de conveniencia no se pisan entre sí."""
    from data.news_sources import SourceOutcome

    o = SourceOutcome("x", estado)
    assert o.failed is (estado == "failed")
    assert o.skipped is (estado == "skipped")
    assert o.degraded is (estado == "degraded")


# ── El reporte: degraded es contexto, NO gate ────────────────────────────────


def _res_con(*outcomes):
    from data.news_sources import _CollectResult

    r = _CollectResult()
    r.outcomes.extend(outcomes)
    return r


def test_degraded_cuenta_como_CORRIDA_y_no_como_falla():
    """**La decisión central de esta tarea, fijada donde se puede romper.**

    `SOURCE_FAILURE_ALARM_RATE` se calibró en la 207 contra una población donde una
    falla por sub-propiedad era **invisible**. Esa población no dice nada sobre cuántos
    `degraded` tiene un día sano, así que meterlos al numerador sería mover un umbral
    calibrado con datos que no existen. Cuenta en el denominador —la fuente **sí**
    corrió— y no en el numerador.
    """
    from data.news_sources import SourceOutcome
    from scripts.harvest_catalysts import HarvestReport, _anotar_salud

    r = HarvestReport()
    for _ in range(10):
        _anotar_salud(r, "NVDA", _res_con(SourceOutcome("yfinance_estimates", "degraded", 2)))

    assert r.src_run["yfinance_estimates"] == 10, "la fuente corrió: va al denominador"
    assert r.src_fail["yfinance_estimates"] == 0, "pero no está caída: no va al numerador"
    assert r.src_degraded["yfinance_estimates"] == 10
    assert r.source_failure_rates()["yfinance_estimates"] == 0.0
    assert not r.degraded, "10 de 10 degradadas NO tienen que disparar la alarma calibrada"


def test_el_resumen_DICE_las_degradadas():
    """Si el código las distingue y el reporte no, es el defecto de la 207 con otro nombre.

    La 207 existió porque `[]` significaba tres cosas y el reporte no podía separarlas.
    Un `degraded` que no se imprime en ningún lado sería exactamente lo mismo: un estado
    que el código sabe y el operador no.
    """
    from data.news_sources import SourceOutcome
    from scripts.harvest_catalysts import HarvestReport, _anotar_salud

    r = HarvestReport()
    _anotar_salud(r, "NVDA", _res_con(SourceOutcome("yfinance_estimates", "degraded", 2)))
    resumen = r.summary()

    assert "degradadas" in resumen, resumen
    assert "yfinance_estimates 1" in resumen, resumen


def test_sin_degradadas_el_resumen_no_las_menciona():
    """La otra dirección: no se agrega ruido a una corrida sana."""
    from data.news_sources import SourceOutcome
    from scripts.harvest_catalysts import HarvestReport, _anotar_salud

    r = HarvestReport()
    _anotar_salud(r, "NVDA", _res_con(SourceOutcome("yfinance_estimates", "ok", 5)))
    assert "degradadas" not in r.summary()


def test_una_fuente_CAIDA_sigue_disparando_la_alarma():
    """Contraprueba del gate: el cambio de la 210 no lo ablandó.

    Sin esto, sacarle la alarma a `failed` entero pasaría desapercibido mientras los
    tests de arriba siguen verdes.
    """
    from data.news_sources import SourceOutcome
    from scripts.harvest_catalysts import SOURCE_FAILURE_ALARM_RATE, HarvestReport, _anotar_salud

    r = HarvestReport()
    for i in range(10):
        estado = "failed" if i < 5 else "ok"
        _anotar_salud(r, "NVDA", _res_con(SourceOutcome("yfinance_news", estado, 0)))

    assert r.source_failure_rates()["yfinance_news"] == 0.5 >= SOURCE_FAILURE_ALARM_RATE
    assert r.degraded, "la mitad caída tiene que alarmar"
    assert "FUENTES CAIDAS" in r.summary()


def test_una_fuente_degradada_NO_se_cuenta_como_limpia():
    """**El resumen no puede afirmar y desmentir en el mismo renglón.**

    Con la cuenta vieja una fuente degradada tenía tasa de falla 0, así que el resumen
    salía `fuentes 1/1 limpias | degradadas: yfinance_estimates 1` — las dos cosas a la
    vez, y quien lee se queda con la primera. El gate no cambió; lo que cambió es que la
    etiqueta para humanos deje de contradecir al dato que tiene al lado.
    """
    from data.news_sources import SourceOutcome
    from scripts.harvest_catalysts import HarvestReport, _anotar_salud

    r = HarvestReport()
    _anotar_salud(r, "NVDA", _res_con(SourceOutcome("yfinance_estimates", "degraded", 2)))
    resumen = r.summary()

    assert "0/1 limpias" in resumen, resumen
    assert "1/1 limpias" not in resumen, f"una fuente degradada no está limpia: {resumen}"
    assert not r.degraded, "y sin embargo NO alarma: el gate calibrado no se movió"


def test_la_fuente_sana_sigue_contando_como_limpia():
    """La otra dirección: no se ensucia a quien no tiene nada."""
    from data.news_sources import SourceOutcome
    from scripts.harvest_catalysts import HarvestReport, _anotar_salud

    r = HarvestReport()
    _anotar_salud(r, "NVDA", _res_con(SourceOutcome("yfinance_news", "ok", 3)))
    _anotar_salud(r, "NVDA", _res_con(SourceOutcome("yfinance_estimates", "degraded", 1)))

    assert "1/2 limpias" in r.summary(), r.summary()
