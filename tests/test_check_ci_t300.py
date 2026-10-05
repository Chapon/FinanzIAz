"""Tarea 300 — ``scripts/check_ci.py`` dice verde sólo cuando el CI del commit terminó en verde.

Sin red: la API va inyectada como ``fetch``. Lo que importa fijar es que **ningún caso dudoso se
lee como verde** —sin run, en curso, sin red, cuota agotada—: el cierre de una tarea depende de
este exit code, y un falso verde es exactamente el defecto que lo motivó (17 tareas cerradas con
el CI en rojo).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts import check_ci as cc

_RAIZ = Path(__file__).resolve().parent.parent
_REPO = "dueno/repo"

# Los lugares que declaran CÓMO SE CIERRA una tarea. Si el paso del CI falta en uno, ese lugar
# se sigue leyendo como un cierre completo —la forma de la 66 y de la 72—, y el que lo siga cierra
# con el CI en rojo sin haber hecho nada mal.
_DECLARAN_EL_CIERRE = ("CLAUDE.md", ".claude/commands/ship.md", ".claude/skills/git-workflow/SKILL.md")


def _cuerpo(rel: str) -> str:
    """Sin el frontmatter: `ship.md` nombra `check_ci.py` también en `allowed-tools`, y ese
    permiso satisfaría un `in` aunque el cuerpo no mandara correrlo (la trampa de la 176)."""
    texto = (_RAIZ / rel).read_text(encoding="utf-8")
    return re.sub(r"\A---\n.*?\n---\n", "", texto, count=1, flags=re.S)


@pytest.mark.parametrize("rel", _DECLARAN_EL_CIERRE)
def test_cada_lugar_que_declara_el_cierre_manda_esperar_el_CI(rel):
    assert "scripts/check_ci.py --esperar" in _cuerpo(rel), f"{rel} no manda leer el CI al cerrar (regla 7)"


def test_al_abrir_una_sesion_se_lee_el_ultimo_CI():
    assert "scripts/check_ci.py --ultimo" in _cuerpo("CLAUDE.md")


def test_CONTROL_el_frontmatter_no_cuenta():
    """`ship.md` tiene el permiso en el frontmatter: sacarlo del cuerpo tiene que ser rojo."""
    crudo = (_RAIZ / ".claude/commands/ship.md").read_text(encoding="utf-8")
    assert "check_ci.py" in crudo.split("---", 2)[1], "el control perdió su caso: el permiso ya no está"
    assert "scripts/check_ci.py --esperar" not in re.sub(
        r"scripts/check_ci\.py --esperar", "", _cuerpo(".claude/commands/ship.md")
    )


def test_ship_no_prohibe_el_push_que_el_cierre_necesita():
    """`ship.md` decía «NO hagas `git push` salvo que te lo pida», contra la orden de Chapa del
    2026-07-15 (`git-workflow`). Con la regla 7 el push es parte del cierre."""
    assert "NO hagas `git push`" not in _cuerpo(".claude/commands/ship.md")


_SHA = "a" * 40


def _run(
    conclusion="success",
    status="completed",
    sha=_SHA,
    run_id=1,
    attempt=1,
    creado="2026-10-04T10:00:00Z",
    rama="main",
    evento="push",
):
    return {
        "id": run_id,
        "head_branch": rama,
        "event": evento,
        "head_sha": sha,
        "status": status,
        "conclusion": conclusion,
        "run_attempt": attempt,
        "created_at": creado,
        "html_url": f"https://github.com/{_REPO}/actions/runs/{run_id}",
    }


def _fetch_de(runs, jobs=None, anotaciones=None):
    llamadas = []

    def fetch(url):
        llamadas.append(url)
        if "/actions/workflows/" in url:
            return {"workflow_runs": runs}
        if url.endswith("/jobs"):
            return {"jobs": jobs or []}
        if "/annotations" in url:
            return anotaciones or []
        raise AssertionError(f"URL inesperada: {url}")

    fetch.llamadas = llamadas
    return fetch


def _consultar(fetch, sha=_SHA, **kw):
    lineas = []
    rc = cc.consultar(_REPO, sha, fetch=fetch, out=lineas.append, dormir=lambda s: None, **kw)
    return rc, "\n".join(lineas)


def test_verde_solo_con_success():
    assert _consultar(_fetch_de([_run("success")]))[0] == cc.VERDE


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "startup_failure"])
def test_todo_lo_que_no_es_success_es_rojo(conclusion):
    assert _consultar(_fetch_de([_run(conclusion)]))[0] == cc.ROJO


def test_sin_run_para_el_commit_NO_es_verde():
    rc, texto = _consultar(_fetch_de([_run("success", sha="b" * 40)]))
    assert rc == cc.NO_SE_SABE and "NO es un verde" in texto


def test_un_run_en_curso_sin_esperar_NO_es_verde():
    assert _consultar(_fetch_de([_run(None, status="in_progress")]))[0] == cc.NO_SE_SABE


def test_sin_red_NO_es_verde():
    def fetch(url):
        raise cc.SinRespuesta("HTTP 403 (cuota)")

    rc, texto = _consultar(fetch)
    assert rc == cc.NO_SE_SABE and "403" in texto


def test_el_rojo_dice_que_tests_fallaron():
    """El dato que hizo falta el 2026-10-04: sin él, el rojo se ve pero no se sabe qué arreglar."""
    anot = [
        {"message": "Process completed with exit code 1."},
        {
            "message": "...\nSKIPPED [1] tests/x.py:3: algo\n"
            "FAILED tests/test_log_con_origen_t288.py::test_el_origen_del_proceso[argv0-None] - AssertionError\n"
            "= 1 failed, 4240 passed ="
        },
    ]
    jobs = [
        {"id": 9, "name": "pytest", "conclusion": "failure"},
        {"id": 8, "name": "lint", "conclusion": "success"},
    ]
    rc, texto = _consultar(_fetch_de([_run("failure")], jobs=jobs, anotaciones=anot))
    assert rc == cc.ROJO
    assert "job 'pytest': failure" in texto and "lint" not in texto
    assert "FAILED tests/test_log_con_origen_t288.py::test_el_origen_del_proceso[argv0-None]" in texto


def test_el_detalle_que_falla_no_cambia_el_rojo():
    def fetch(url):
        if "/actions/workflows/" in url:
            return {"workflow_runs": [_run("failure")]}
        raise cc.SinRespuesta("sin red")

    rc, texto = _consultar(fetch)
    assert rc == cc.ROJO and "no se pudo leer el detalle" in texto


def test_esperar_reintenta_hasta_que_termina():
    estados = iter([[_run(None, status="queued")], [_run(None, status="in_progress")], [_run("success")]])

    def fetch(url):
        return {"workflow_runs": next(estados)}

    assert _consultar(fetch, esperar=True, timeout_s=10_000)[0] == cc.VERDE


def test_esperar_con_la_espera_agotada_NO_es_verde():
    t = iter(range(0, 10_000, 100))
    rc, texto = _consultar(
        _fetch_de([_run(None, status="in_progress")]), esperar=True, timeout_s=250, reloj=lambda: next(t)
    )
    assert rc == cc.NO_SE_SABE and "no terminó dentro de la espera" in texto


def test_un_reintento_del_run_manda_sobre_el_primero():
    """Re-correr un job crea otro intento del mismo commit: vale el último, no el primero."""
    runs = [_run("failure", run_id=1, attempt=1), _run("success", run_id=1, attempt=2)]
    assert _consultar(_fetch_de(runs))[0] == cc.VERDE


def test_ultimo_toma_el_ultimo_TERMINADO_de_main():
    """Al abrir una tarea (retraso uno): un run en curso no tapa el rojo del anterior."""
    runs = [
        _run(None, status="in_progress", sha="c" * 40, creado="2026-10-04T12:00:00Z"),
        _run("failure", sha="b" * 40, creado="2026-10-04T11:00:00Z"),
        _run("success", sha="a" * 40, creado="2026-10-04T10:00:00Z"),
    ]
    assert _consultar(_fetch_de(runs), sha=None)[0] == cc.ROJO


def test_la_consulta_filtra_por_workflow_y_commit_pero_NO_por_rama():
    """Tarea 307: el ``branch=`` de la API devolvía un subconjunto atrasado. La rama se filtra acá."""
    fetch = _fetch_de([_run("success")])
    _consultar(fetch)
    url = fetch.llamadas[0]
    assert f"/actions/workflows/{cc.WORKFLOW}/runs" in url and f"head_sha={_SHA}" in url
    assert "branch=" not in url


def test_la_rama_y_el_evento_se_filtran_del_lado_del_cliente():
    """Un run verde de otra rama, o de un pull request desde un ``main`` de un fork, no es el de main."""
    runs = [
        _run("success", rama="otra", creado="2026-10-04T12:00:00Z", sha="c" * 40),
        _run("success", evento="pull_request", creado="2026-10-04T11:00:00Z", sha="d" * 40),
        _run("failure", creado="2026-10-04T10:00:00Z", sha="b" * 40),
    ]
    assert _consultar(_fetch_de(runs), sha=None)[0] == cc.ROJO


# ── Tarea 307: --ultimo con la lista atrasada ───────────────────────────────

_MAIN = "f" * 40


def test_ultimo_con_una_lista_ATRASADA_no_es_verde():
    """El caso del 2026-10-05: la API devolvió runs de hasta un mes atrás, todos verdes, y ninguno
    del commit en que está `main`. Antes salía VERDE del más nuevo de ese subconjunto."""
    viejos = [_run("success", sha="a" * 40, creado="2026-09-08T01:26:26Z")]
    rc, texto = _consultar(_fetch_de(viejos), sha=None, sha_main=_MAIN)
    assert rc == cc.NO_SE_SABE and "NO es un verde" in texto and "fffffff" in texto


def test_ultimo_con_el_run_de_main_EN_CURSO_lee_el_anterior_y_lo_dice():
    runs = [
        _run(None, status="in_progress", sha=_MAIN, creado="2026-10-05T12:00:00Z"),
        _run("failure", sha="b" * 40, creado="2026-10-05T11:00:00Z"),
    ]
    rc, texto = _consultar(_fetch_de(runs), sha=None, sha_main=_MAIN)
    assert rc == cc.ROJO and "sigue en curso" in texto


def test_ultimo_con_el_run_de_main_terminado_es_ese():
    runs = [_run("success", sha=_MAIN, creado="2026-10-05T12:00:00Z"), _run("failure", sha="b" * 40)]
    assert _consultar(_fetch_de(runs), sha=None, sha_main=_MAIN)[0] == cc.VERDE


def test_la_skill_de_auditoria_compara_el_sha_contra_origin_main():
    """La skill manda leer el CI primero en `guards`: un VERDE solo no alcanza (la 307)."""
    texto = (_RAIZ / ".claude/skills/auditoria/SKILL.md").read_text(encoding="utf-8")
    # El párrafo del resultado del CI, no cualquier línea del archivo: un `in` sobre el archivo
    # entero se satisface con una mención suelta (la trampa de la 173 y la 176).
    inicio = texto.index("**Y la PRIMERA pregunta es por el RESULTADO")
    parrafo = texto[inicio : texto.index("**Corolario:", inicio)]
    assert "check_ci.py --ultimo" in parrafo
    assert "git rev-parse origin/main" in parrafo


@pytest.mark.parametrize(
    "url,esperado",
    [
        ("https://github.com/Chapon/FinanzIAz.git", "Chapon/FinanzIAz"),
        ("https://github.com/Chapon/FinanzIAz", "Chapon/FinanzIAz"),
        ("git@github.com:Chapon/FinanzIAz.git", "Chapon/FinanzIAz"),
        ("https://gitlab.com/x/y.git", None),
    ],
)
def test_repo_de_origin(url, esperado):
    assert cc.repo_de_origin(url) == esperado


def test_ultimo_con_el_run_de_main_TERMINADO_pero_otro_mas_nuevo_no_es_verde():
    """Una lista incoherente: el run de `main` terminó (rojo) y otro commit figura creado después
    (verde). No es «el de main sigue en curso»: el veredicto de `main` es otro, y se dice que no
    se sabe en vez de prestarle el verde del otro commit."""
    runs = [
        _run("success", sha="b" * 40, creado="2026-10-05T12:00:00Z"),
        _run("failure", sha=_MAIN, creado="2026-10-05T11:00:00Z"),
    ]
    rc, texto = _consultar(_fetch_de(runs), sha=None, sha_main=_MAIN)
    assert rc == cc.NO_SE_SABE and "sigue en curso" not in texto
