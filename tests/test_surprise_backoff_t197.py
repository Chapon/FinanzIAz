"""Tarea 197 — un rebuild de surprise que falla no reintenta cada minuto.

**El incidente, que es de donde salen los números.** Del 2026-09-10 17:58 al 2026-09-11
11:41 el log vivo tiene **390** ``surprise rebuild starting`` y **389**
``surprise rebuild failed``, uno **por minuto**. La causa inmediata fue un `ImportError`
(la app corriendo con el código viejo en memoria tras el commit de la 160), pero el
mecanismo es independiente de ella: la cadencia sale del ``_meta.built_at`` del artefacto
(tarea 160) y ese sello lo escribe **sólo un build exitoso**, así que una falla no deja
marca, ``build_due`` sigue diciendo ``True``, y el "tick diario" del scheduler **dispara
cada minuto** (``_DAILY_CHECK_MS = 60_000``). Cualquier falla persistente —Yahoo caído,
un disco lleno, un import roto— daba 1.440 intentos por día, cada uno pegándole a
yfinance.

**Lo que estos tests fijan es la cota, no la implementación.** El kill-criteria de la
tarea pedía: avanzando el reloj de a un minuto durante un día con un build que falla
siempre, se lanzan **como máximo** los intentos que el backoff declara, y un éxito
posterior vuelve a la cadencia normal. Las dos direcciones están abajo.

Se prueba contra ``surprise_build_due``, que es **pura** —los gates baratos del job sin
Qt ni disco—, igual que ``hourly_harvest_due`` para el harvest horario (tarea 10). El
gate de cadencia (``build_due`` sobre el artefacto) queda afuera a propósito: es el que
lee disco y no es lo que esta tarea cambia.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from paper_trading.scheduler import _SURPRISE_RETRY_HOURS, surprise_build_due

AHORA = datetime(2026, 9, 10, 17, 58, 0)  # el minuto en que arrancó el incidente real


def _due(**overrides) -> bool:
    """Baseline: todo a favor → True. Cada test pisa un solo gate."""
    kwargs = dict(enabled=True, worker_running=False, now=AHORA, retry_after=None)
    kwargs.update(overrides)
    return surprise_build_due(**kwargs)


# ── Los gates, uno por uno ───────────────────────────────────────────────────


def test_baseline_sin_falla_pendiente_dispara():
    assert _due() is True


def test_flag_apagado_bloquea():
    assert _due(enabled=False) is False


def test_worker_vivo_bloquea():
    """Dos builds concurrentes escriben el mismo artefacto."""
    assert _due(worker_running=True) is False


def test_backoff_vigente_bloquea():
    assert _due(retry_after=AHORA + timedelta(hours=1)) is False


def test_backoff_vencido_deja_pasar():
    assert _due(retry_after=AHORA - timedelta(seconds=1)) is True


def test_el_borde_del_backoff_deja_pasar():
    """``now == retry_after`` **no** bloquea: el corte es estricto.

    Se fija porque un ``<=`` acá haría que el reintento dependa de que el tick caiga en
    un microsegundo posterior, y el tick es de un minuto.
    """
    assert _due(retry_after=AHORA) is True


# ── El kill-criteria: la cota sobre un día entero ────────────────────────────


def _simular_un_dia(build_falla: bool, minutos: int = 24 * 60) -> int:
    """Corre el tick de a un minuto durante ``minutos`` y cuenta los **lanzamientos**.

    Reproduce el lazo real: cada tick evalúa los gates baratos y, si pasan, "lanza" —
    y el resultado del build es lo único que mueve el estado. El fallo arma el backoff
    igual que ``_posponer_surprise``; el éxito lo borra, igual que
    ``_on_surprise_completed``.

    ``build_due`` (la cadencia semanal del artefacto) se deja en ``True`` **a propósito**:
    es la condición del incidente —el artefacto viejo, nunca reescrito porque el build
    nunca termina— y es lo que hace visible el lazo. Con la cadencia diciendo ``False``
    no habría nada que medir.
    """
    lanzamientos = 0
    retry_after: datetime | None = None
    for i in range(minutos):
        ahora = AHORA + timedelta(minutes=i)
        if not surprise_build_due(enabled=True, worker_running=False, now=ahora, retry_after=retry_after):
            continue
        lanzamientos += 1
        retry_after = ahora + timedelta(hours=_SURPRISE_RETRY_HOURS) if build_falla else None
    return lanzamientos


def test_un_dia_de_fallas_no_supera_la_cota_del_backoff():
    """**El test que la tarea pedía.** 1.440 ticks, y no 1.440 intentos."""
    lanzamientos = _simular_un_dia(build_falla=True)
    # Una ventana completa por cada `_SURPRISE_RETRY_HOURS` del día: con 6 h, los
    # intentos caen en t=0, 6, 12 y 18 => 4. El de t=24 ya es del día siguiente (el lazo
    # recorre los minutos 0..1439), y por eso NO se suma uno.
    cota = 24 // _SURPRISE_RETRY_HOURS

    assert lanzamientos <= cota, (
        f"{lanzamientos} intentos en un día con backoff de {_SURPRISE_RETRY_HOURS}h: "
        "el backoff no está frenando el lazo (tarea 197)."
    )
    assert lanzamientos == cota, (
        "tampoco tiene que frenar de MÁS: un build que falla igual debe reintentar una "
        "vez por ventana, porque la falla suele ser transitoria."
    )


def test_la_cota_es_MUCHO_menor_que_la_del_incidente():
    """Contraprueba del instrumento: sin backoff el mismo lazo da un intento por minuto.

    Sin esto, un `_simular_un_dia` que devolviera 5 por cualquier otro motivo —un bug en
    el simulador, un gate de más— pasaría el test de arriba sin probar nada. Acá se mide
    el brazo **sin** el arreglo y tiene que dar la cifra del incidente.
    """
    sin_backoff = sum(
        1
        for i in range(24 * 60)
        if surprise_build_due(
            enabled=True, worker_running=False, now=AHORA + timedelta(minutes=i), retry_after=None
        )
    )
    assert sin_backoff == 24 * 60, "sin backoff tiene que haber un intento por tick"

    con_backoff = _simular_un_dia(build_falla=True)
    assert con_backoff * 100 < sin_backoff, (
        f"{sin_backoff} → {con_backoff}: la mejora tiene que ser de dos órdenes de "
        "magnitud, que es lo que separa 389 fallos de un puñado"
    )


def test_un_exito_devuelve_la_cadencia_normal():
    """La otra dirección del kill-criteria: el backoff no se queda pegado.

    Un éxito borra ``retry_after``, así que el job vuelve a depender **sólo** de la
    cadencia del artefacto — que es donde la 160 la puso a propósito.
    """
    lanzamientos = _simular_un_dia(build_falla=False)
    assert lanzamientos == 24 * 60, (
        "con builds exitosos el backoff no debe intervenir: quien manda es `build_due` "
        "sobre el artefacto, y este gate tiene que ser transparente"
    )


def test_una_racha_de_fallas_y_despues_un_exito():
    """El caso del incidente de punta a punta: falla 18h, después anda."""
    retry_after: datetime | None = None
    intentos_fallidos = 0

    # 18 horas fallando (17,7 h fue el incidente real).
    for i in range(18 * 60):
        ahora = AHORA + timedelta(minutes=i)
        if surprise_build_due(enabled=True, worker_running=False, now=ahora, retry_after=retry_after):
            intentos_fallidos += 1
            retry_after = ahora + timedelta(hours=_SURPRISE_RETRY_HOURS)

    assert intentos_fallidos == 3, (
        f"{intentos_fallidos} intentos en 18h con backoff de {_SURPRISE_RETRY_HOURS}h; "
        "el incidente real fueron 389"
    )

    # El siguiente sale bien (como pasó de verdad) → el backoff se borra.
    retry_after = None
    despues = AHORA + timedelta(hours=18, minutes=1)
    assert surprise_build_due(enabled=True, worker_running=False, now=despues, retry_after=retry_after), (
        "tras el éxito el job vuelve a estar disponible sin esperar la ventana"
    )


# ── El número del backoff, y sus dos límites ─────────────────────────────────


def test_el_backoff_cae_entre_sus_dos_limites():
    """El valor no es libre: lo acotan el tick por abajo y la cadencia por arriba.

    Por abajo, tiene que ser **mucho** mayor que el minuto del tick, o no frena nada.
    Por arriba, mucho menor que la cadencia semanal del artefacto, o una falla
    transitoria dejaría el perfil sin actualizar una semana entera — que es peor que el
    problema que esto arregla. Si alguien mueve el número fuera de ese rango, se entera.
    """
    from analysis.surprise_score import DEFAULT_BUILD_INTERVAL_DAYS

    horas_de_cadencia = DEFAULT_BUILD_INTERVAL_DAYS * 24

    # El backoff en MINUTOS contra el tick, que es de 1 minuto: 6 h = 360 ticks.
    ticks_de_backoff = _SURPRISE_RETRY_HOURS * 60
    assert ticks_de_backoff >= 60, (
        f"backoff de {ticks_de_backoff} ticks: demasiado corto para frenar un lazo que se evalúa cada minuto"
    )
    assert horas_de_cadencia >= _SURPRISE_RETRY_HOURS * 4, (
        f"backoff de {_SURPRISE_RETRY_HOURS}h contra una cadencia de {horas_de_cadencia}h: "
        "demasiado cerca; una falla transitoria costaría casi un ciclo entero"
    )


@pytest.mark.parametrize("horas", [0, -1])
def test_un_backoff_no_positivo_seria_un_no_op(horas):
    """Fija la semántica del borde, que es la trampa de `paper_whipsaw_min_loss_pct`.

    Un backoff de 0 no es "sin backoff configurado": es **reintentar en el próximo
    tick**, o sea el defecto de vuelta. No se soporta, y queda escrito acá para que
    nadie lo lea como un apagado.
    """
    ahora = AHORA
    retry_after = ahora + timedelta(hours=horas)
    assert (
        surprise_build_due(enabled=True, worker_running=False, now=ahora, retry_after=retry_after) is True
    ), "con un backoff <= 0 el gate no frena: sería volver al reintento por tick"
