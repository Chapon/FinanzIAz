"""Tarea 430 — un run que GitHub nunca arrancó no es «en curso», ni un rojo de los tests.

El caso real (2026-11-11): dos incidentes de GitHub dejaron huérfanos los runs de ``d9b9d4c`` y de
``6b1fdba`` (``HEAD``), **sin ningún job**. El de ``6b1fdba`` siguió ``queued`` días enteros y
``--ultimo`` dijo **VERDE** —del run de ``564f2f7``, «el anterior»— cuatro días; cuando alguien
canceló el de ``d9b9d4c`` pasó a decir **ROJO (cancelled)** sin una línea de detalle. Ninguno de
los dos veredictos decía nada de ``main``.

Sin red: la API va inyectada como ``fetch``, y el reloj de pared como ``ahora``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts import check_ci as cc

_REPO = "dueno/repo"
_MAIN = "6" * 40  # 6b1fdba: el de `main`, huérfano en `queued`
_D9 = "d" * 40  # d9b9d4c: huérfano, cancelado el 15/11
_OK = "5" * 40  # 564f2f7: el último verde de verdad

_CREADO_MAIN = "2026-11-11T20:39:00Z"
_CUATRO_DIAS = datetime(2026, 11, 15, 17, 0, tzinfo=timezone.utc)
_DIEZ_MIN = datetime(2026, 11, 11, 20, 49, tzinfo=timezone.utc)


def _run(conclusion, status="completed", sha=_MAIN, run_id=1, creado=_CREADO_MAIN):
    return {
        "id": run_id,
        "head_branch": "main",
        "event": "push",
        "head_sha": sha,
        "status": status,
        "conclusion": conclusion,
        "run_attempt": 1,
        "created_at": creado,
        "html_url": f"https://github.com/{_REPO}/actions/runs/{run_id}",
    }


def _fetch_de(runs, jobs_por_run=None, jobs_falla=False):
    """``jobs_por_run``: {run_id: [jobs]}; un run que no está ahí no tiene ningún job."""
    llamadas = []

    def fetch(url):
        llamadas.append(url)
        if "/actions/workflows/" in url:
            return {"workflow_runs": runs}
        if url.endswith("/jobs"):
            if jobs_falla:
                raise cc.SinRespuesta("HTTP 403 (cuota)")
            run_id = int(url.rsplit("/runs/", 1)[1].split("/")[0])
            jobs = (jobs_por_run or {}).get(run_id, [])
            return {"total_count": len(jobs), "jobs": jobs}
        if "/annotations" in url:
            return []
        raise AssertionError(f"URL inesperada: {url}")

    fetch.llamadas = llamadas
    return fetch


def _consultar(fetch, sha=_MAIN, ahora=_CUATRO_DIAS, **kw):
    lineas, siestas = [], []
    kw.setdefault("contar", lambda desde, hasta: None)
    rc = cc.consultar(
        _REPO,
        sha,
        fetch=fetch,
        out=lineas.append,
        dormir=siestas.append,
        ahora=lambda: ahora,
        **kw,
    )
    return rc, "\n".join(lineas), siestas


def _huerfanos():
    """La lista que devolvía la API: `main` huérfano en `queued`, el anterior verde."""
    return [
        _run(None, status="queued", sha=_MAIN, run_id=3, creado=_CREADO_MAIN),
        _run("success", sha=_OK, run_id=1, creado="2026-11-11T19:50:00Z"),
    ]


# ── --ultimo ─────────────────────────────────────────────────────────────────


def test_ultimo_con_main_ATASCADO_y_el_anterior_verde_NO_es_verde():
    """El modo VERDE del 11/11 al 15/11: antes salía exit 0 del run de 564f2f7."""
    rc, texto, _ = _consultar(_fetch_de(_huerfanos()), sha=None, sha_main=_MAIN)
    assert rc == cc.NO_SE_SABE
    assert "ATASCADO" in texto and "sin ningún job" in texto and _CREADO_MAIN in texto
    assert "NO es un verde" in texto and "VERDE" not in texto.replace("NO es un verde", "")


def test_CONTROL_un_run_de_main_RECIEN_creado_sigue_siendo_el_retraso_uno():
    """Diez minutos sin jobs es lo normal al arrancar: se lee el anterior, como desde la 307."""
    rc, texto, _ = _consultar(_fetch_de(_huerfanos()), sha=None, sha_main=_MAIN, ahora=_DIEZ_MIN)
    assert rc == cc.VERDE and "sigue en curso" in texto and "ATASCADO" not in texto


def test_CONTROL_un_run_viejo_CON_jobs_no_es_atascado():
    """Un run que GitHub sí arrancó (tiene jobs) y tarda no es huérfano: sigue el retraso uno."""
    fetch = _fetch_de(_huerfanos(), jobs_por_run={3: [{"id": 9, "name": "pytest", "status": "queued"}]})
    rc, texto, _ = _consultar(fetch, sha=None, sha_main=_MAIN)
    assert rc == cc.VERDE and "ATASCADO" not in texto


def test_un_run_viejo_cuyos_jobs_no_se_pueden_leer_NO_presta_el_verde_del_anterior():
    rc, texto, _ = _consultar(_fetch_de(_huerfanos(), jobs_falla=True), sha=None, sha_main=_MAIN)
    assert rc == cc.NO_SE_SABE and "sin poder leer sus jobs" in texto


def test_ultimo_con_el_huerfano_CANCELADO_no_es_rojo():
    """El modo ROJO desde el 15/11: el último terminado es el de d9b9d4c, cancelado sin jobs."""
    runs = [
        _run(None, status="queued", sha=_MAIN, run_id=3, creado=_CREADO_MAIN),
        _run("cancelled", sha=_D9, run_id=2, creado="2026-11-11T20:21:00Z"),
        _run("success", sha=_OK, run_id=1, creado="2026-11-11T19:50:00Z"),
    ]
    # Recién creado el de main (no atascado): el veredicto es el del cancelado, que nunca arrancó.
    rc, texto, _ = _consultar(_fetch_de(runs), sha=None, sha_main=_MAIN, ahora=_DIEZ_MIN)
    assert rc == cc.NO_SE_SABE and "nunca arrancó" in texto and "ROJO" not in texto
    # Y días después, lo que manda es que el de main está atascado.
    rc, texto, _ = _consultar(_fetch_de(runs), sha=None, sha_main=_MAIN)
    assert rc == cc.NO_SE_SABE and "ATASCADO" in texto


def test_ultimo_dice_cuantos_commits_de_main_no_tienen_un_run_terminado():
    contados = []

    def contar(desde, hasta):
        contados.append((desde, hasta))
        return 2

    rc, texto, _ = _consultar(_fetch_de(_huerfanos()), sha=None, sha_main=_MAIN, contar=contar)
    assert rc == cc.NO_SE_SABE and "2 commit(s) sin un run terminado" in texto
    assert contados == [(_OK, _MAIN)]


def test_sin_commits_pendientes_no_dice_nada_de_eso():
    runs = [_run("success", sha=_MAIN, run_id=3)]
    rc, texto, _ = _consultar(_fetch_de(runs), sha=None, sha_main=_MAIN, contar=lambda a, b: 5)
    assert rc == cc.VERDE and "commit(s)" not in texto


# ── el commit propio (--esperar y --sha) ─────────────────────────────────────


def test_esperar_un_run_ATASCADO_corta_enseguida_sin_dormir():
    """Esperar 15 min a un run que GitHub no va a arrancar no cambia nada."""
    runs = [_run(None, status="queued", run_id=3)]
    t = iter(range(0, 10_000, 100))  # reloj falso: sin el corte, la espera termina igual (y rojo)
    rc, texto, siestas = _consultar(_fetch_de(runs), esperar=True, timeout_s=900, reloj=lambda: next(t))
    assert rc == cc.NO_SE_SABE and "ATASCADO" in texto and "Actions" in texto
    assert siestas == []


def test_esperar_un_run_recien_creado_sin_jobs_sigue_esperando():
    estados = iter(
        [
            [_run(None, status="queued", run_id=3)],
            [_run(None, status="in_progress", run_id=3)],
            [_run("success", run_id=3)],
        ]
    )

    def fetch(url):
        if url.endswith("/jobs"):
            raise AssertionError("un run recién creado no gasta el request de sus jobs")
        return {"workflow_runs": next(estados)}

    rc, _, siestas = _consultar(fetch, esperar=True, timeout_s=10_000, ahora=_DIEZ_MIN)
    assert rc == cc.VERDE and len(siestas) == 2


def test_cancelado_SIN_jobs_nunca_arranco_y_no_es_rojo():
    rc, texto, _ = _consultar(_fetch_de([_run("cancelled", run_id=2)]))
    assert rc == cc.NO_SE_SABE and "nunca arrancó" in texto and "NO es un verde" in texto


def test_cancelado_CON_un_job_fallido_sigue_siendo_rojo():
    """La rama que la 430 no puede ablandar: un cancelado que corrió algo es el rojo de la 300."""
    jobs = {2: [{"id": 9, "name": "pytest", "conclusion": "cancelled"}]}
    rc, texto, _ = _consultar(_fetch_de([_run("cancelled", run_id=2)], jobs_por_run=jobs))
    assert rc == cc.ROJO and "nunca arrancó" not in texto


def test_cancelado_con_los_jobs_ilegibles_sigue_siendo_rojo():
    rc, _, _ = _consultar(_fetch_de([_run("cancelled", run_id=2)], jobs_falla=True))
    assert rc == cc.ROJO


def test_startup_failure_SIN_jobs_sigue_siendo_rojo():
    """Tampoco tiene jobs, pero es un workflow que no se pudo leer: eso sí hay que arreglarlo."""
    rc, texto, _ = _consultar(_fetch_de([_run("startup_failure", run_id=2)]))
    assert rc == cc.ROJO and "nunca arrancó" not in texto


def test_la_edad_se_mide_contra_el_reloj_de_pared():
    run = _run(None, status="queued")
    assert cc.edad_s(run, _DIEZ_MIN) == 600
    assert cc.edad_s(run, _DIEZ_MIN + timedelta(hours=1)) == 4200
    assert cc.edad_s({"created_at": "no es una fecha"}, _DIEZ_MIN) is None
