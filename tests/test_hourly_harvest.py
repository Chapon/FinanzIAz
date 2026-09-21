"""Tests del harvest horario in-app (tarea 10) — gate puro ``hourly_harvest_due``.

La decisión de Chapa 2026-07-07: el harvest intradía corre SOLO con la app
abierta (rides el tick por minuto del PaperScheduler); Windows Task Scheduler
queda únicamente con el pipeline completo diario de las 15:00.
"""

from datetime import datetime, timedelta

from paper_trading.scheduler import hourly_harvest_due

NOW = datetime(2026, 7, 7, 15, 0, 0)


def _due(**overrides) -> bool:
    """Baseline: todo a favor → True. Cada test pisa un solo gate."""
    kwargs = dict(
        enabled=True,
        now=NOW,
        last=None,
        interval_min=60,
        hourly_worker_running=False,
        daily_worker_running=False,
        market_open=True,
    )
    kwargs.update(overrides)
    return hourly_harvest_due(**kwargs)


def test_baseline_all_clear_fires():
    assert _due() is True


def test_flag_off_blocks():
    assert _due(enabled=False) is False


def test_market_closed_blocks():
    assert _due(market_open=False) is False


def test_interval_not_elapsed_blocks():
    assert _due(last=NOW - timedelta(minutes=59)) is False


def test_interval_elapsed_fires():
    assert _due(last=NOW - timedelta(minutes=60)) is True


def test_first_run_of_the_day_fires_without_last():
    assert _due(last=None) is True


def test_hourly_worker_running_blocks():
    assert _due(hourly_worker_running=True) is False


def test_daily_refresh_running_blocks():
    # No solapar con el refresh diario (mismo pipeline, contención SQLite).
    assert _due(daily_worker_running=True) is False


def test_interval_floor_is_15_minutes():
    # interval_min=1 se eleva al piso de 15: a los 10 min NO dispara...
    assert _due(interval_min=1, last=NOW - timedelta(minutes=10)) is False
    # ...y a los 15 sí.
    assert _due(interval_min=1, last=NOW - timedelta(minutes=15)) is True


# ── Tarea 216 — el gate de mercado NO pega a la red ──────────────────────────


def test_el_chequeo_de_mercado_abierto_no_toca_la_red():
    """**La afirmación que el docstring hacía y era falsa**, ahora atada a la función.

    Decía *«mercado abierto (puede pegar a Yahoo; por eso va último)»*. `is_market_open`
    es aritmética de reloj pura: zona horaria, día de semana y comparación de horas. La
    frase no costaba nada en runtime — hacía daño **dirigiendo mal a quien la lee**, que
    podía reordenar gates o agregar caché para proteger algo que cuesta microsegundos.

    Se verifica con el cortafuegos de la **209**, que es el instrumento correcto: si
    algún día `is_market_open` empezara a consultar algo, esto se pone rojo con
    `RedBloqueadaEnLaSuite` en vez de quedar como un comentario que nadie re-verifica.
    """
    from data.yahoo_finance import is_market_open

    abierto, etiqueta = is_market_open()
    assert isinstance(abierto, bool)
    assert isinstance(etiqueta, str) and etiqueta


def test_el_gate_de_mercado_se_evalua_EAGER_y_el_docstring_ya_no_dice_lo_contrario():
    """La otra mitad falsa: *«por eso va último»*.

    El llamador lo pasa como **argumento** de `hourly_harvest_due`, así que Python lo
    evalúa antes de entrar a la función — o sea antes que el flag y el intervalo. No es
    un defecto (no cuesta nada y el patrón de argumentos-bool es lo que hace a la
    función pura y testeable), pero el docstring afirmaba un orden que no existe.
    """
    import inspect

    from paper_trading.scheduler import PaperScheduler

    fuente = inspect.getsource(PaperScheduler._maybe_hourly_harvest)
    assert "market_open=_is_market_open_now()" in fuente, (
        "si esto cambió, el gate dejó de evaluarse eager y el docstring hay que revisarlo de nuevo"
    )

    # **Acá NO se afirma que la frase falsa no esté**, y el motivo vale escribirlo: la
    # primera versión de este test pedía `"puede pegar a Yahoo" not in fuente` y salió
    # roja — porque el docstring corregido **cita** la frase para explicar por qué era
    # falsa. Es exactamente la lección de las tareas 128 y 135: para un guard de texto,
    # la prosa que cita un defecto es indistinguible del defecto. Lo que se puede atar
    # mecánicamente es el orden de evaluación, que es lo de arriba; que el texto diga la
    # verdad lo sostiene la lectura, no un grep.
